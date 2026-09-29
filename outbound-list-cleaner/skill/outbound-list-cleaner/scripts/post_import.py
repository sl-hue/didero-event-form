"""Step 4 (after the import) — associations and leftover company duplicates.

Runs after the user has imported the files and built a segment of the
imported contacts with the exclusion lists applied (config.json). Uses the
HubSpot private app token (see hubspot_match.py setup-token).

  pull-segment        Read the segment's contacts, their company associations
                      (with the primary flag) and those companies ->
                      segment_snapshot.json
  review-associations Contacts with no company, and contacts with several
                      companies but the wrong/no primary -> association_fixes.json:
                      a proposed fix per contact plus ready-to-send connector
                      batches (<= 10 per call); cases Claude can't resolve are
                      listed for the user.
  find-dupes          Search HubSpot for duplicates of the segment's companies
                      (domain variants, name + location, LinkedIn page, phone)
                      -> company_dupes.json
  coverage            Step 5: how many of the segment's contacts have each
                      enrichment field filled (config.json enrichment_fields).
                      Run with --label before and --label after the Clay run;
                      the second run prints the change.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hubspot_match as hm  # noqa: E402  (shared HubSpot API + matching helpers)

CONTACT_PROPS = ["firstname", "lastname", "email", "jobtitle", "company", "company_domain",
                 "hs_email_domain", "associatedcompanyid"]
COMPANY_PROPS = ["name", "domain", "hs_additional_domains", "website", "city", "state", "country", "location",
                 "phone", "linkedin_company_page", "numberofemployees", "annualrevenue",
                 "num_associated_contacts", "type", "createdate"]
PRIMARY_TYPE_ID = 1  # HubSpot-defined contact -> company "Primary" association


def batch_read(object_path, ids, properties):
    out = []
    ids = sorted(set(str(i) for i in ids))
    for k in range(0, len(ids), 100):
        resp = hm.api("POST", f"/crm/v3/objects/{object_path}/batch/read",
                      {"properties": properties, "inputs": [{"id": x} for x in ids[k:k + 100]]})
        out += resp.get("results", [])
    return {r["id"]: r.get("properties", {}) for r in out}


def find_list(segment):
    if segment.isdigit():
        return segment, segment
    resp = hm.api("POST", "/crm/v3/lists/search", {"query": segment, "count": 20})
    lists = [l for l in resp.get("lists", []) if l.get("name", "").strip().lower() == segment.strip().lower()]
    if len(lists) != 1:
        found = ", ".join(f"{l.get('name')} ({l.get('listId')})" for l in resp.get("lists", [])) or "none"
        raise SystemExit(f"Couldn't pick one segment named {segment!r}; matches: {found}. Pass the list ID.")
    return lists[0]["listId"], lists[0]["name"]


def pull_segment(args):
    list_id, name = find_list(args.segment)
    contact_ids, after = [], None
    while True:
        resp = hm.api("GET", f"/crm/v3/lists/{list_id}/memberships?limit=250" + (f"&after={after}" if after else ""))
        contact_ids += [str(r["recordId"]) for r in resp.get("results", [])]
        after = (resp.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    contacts = batch_read("contacts", contact_ids, CONTACT_PROPS)

    associations = defaultdict(list)
    for k in range(0, len(contact_ids), 100):
        resp = hm.api("POST", "/crm/v4/associations/contacts/companies/batch/read",
                      {"inputs": [{"id": x} for x in contact_ids[k:k + 100]]})
        for r in resp.get("results", []):
            for to in r.get("to", []):
                primary = any(t.get("typeId") == PRIMARY_TYPE_ID and t.get("category") == "HUBSPOT_DEFINED"
                              for t in to.get("associationTypes", []))
                associations[str(r["from"]["id"])].append({"company_id": str(to["toObjectId"]), "primary": primary})

    # Companies already associated, plus any company owning an unassociated
    # contact's domain (the candidate to associate them with).
    company_ids = {a["company_id"] for links in associations.values() for a in links}
    domains = {contact_domain(p) for cid, p in contacts.items() if not associations.get(cid)} - {""}
    for chunk in hm.chunks(domains):
        resp = hm.api("POST", "/crm/v3/objects/companies/search", {
            "limit": 200, "properties": COMPANY_PROPS,
            "filterGroups": [{"filters": [{"propertyName": "domain", "operator": "IN", "values": chunk}]}]})
        company_ids |= {r["id"] for r in resp.get("results", [])}
    companies = batch_read("companies", company_ids, COMPANY_PROPS)
    portal = hm.api("GET", "/account-info/v3/details").get("portalId")

    snapshot = {"segment": {"id": list_id, "name": name}, "portal": portal,
                "contacts": {cid: {"properties": p, "companies": associations.get(cid, [])}
                             for cid, p in contacts.items()},
                "companies": companies}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "segment_snapshot.json").write_text(json.dumps(snapshot, indent=2))
    none = sum(1 for c in snapshot["contacts"].values() if not c["companies"])
    many = sum(1 for c in snapshot["contacts"].values() if len(c["companies"]) > 1)
    print(f"segment {name!r}: {len(contacts)} contacts ({none} with no company, {many} with several), "
          f"{len(companies)} companies -> {out / 'segment_snapshot.json'}")


def contact_domain(p):
    d = (p.get("company_domain") or "").strip().lower()
    if not d and "@" in (p.get("email") or ""):
        d = p["email"].split("@")[1].lower()
    return hm.norm_domain(d)


def company_domains(p):
    extra = [d.strip() for d in (p.get("hs_additional_domains") or "").split(";")]
    return {hm.norm_domain(d) for d in [p.get("domain")] + extra if d}


def url(portal, obj, rid):
    return f"https://app.hubspot.com/contacts/{portal}/record/{obj}/{rid}"


def review_associations(args):
    snap = json.loads(Path(args.snapshot).read_text())
    companies, portal = snap["companies"], snap["portal"]
    by_domain = defaultdict(list)
    for cid, p in companies.items():
        for d in company_domains(p):
            by_domain[d].append(cid)

    fixes, ask = [], []
    for contact_id, c in snap["contacts"].items():
        p, links = c["properties"], c["companies"]
        name = f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip()
        dom = contact_domain(p)
        row = {"contact_id": contact_id, "contact": name, "email": p.get("email"), "domain": dom,
               "contact_url": url(portal, "0-1", contact_id),
               "current": [{"company_id": l["company_id"], "name": companies.get(l["company_id"], {}).get("name"),
                            "primary": l["primary"]} for l in links]}
        if not links:
            matches = by_domain.get(dom, [])
            if len(matches) == 1:
                fixes.append({**row, "action": "associate as primary", "company_id": matches[0],
                              "company": companies[matches[0]].get("name"),
                              "reason": f"company domain {dom} matches the contact"})
            else:
                ask.append({**row, "issue": "no company", "options": [
                    {"company_id": m, "name": companies[m].get("name")} for m in matches],
                    "reason": "several companies share the domain" if matches else f"no company with domain {dom}"})
            continue
        if len(links) == 1:
            continue
        # Several companies: the list's company (the one owning the contact's
        # domain) should be primary; the others stay as secondary associations.
        owning = [l["company_id"] for l in links if dom and dom in company_domains(companies.get(l["company_id"], {}))]
        current_primary = [l["company_id"] for l in links if l["primary"]]
        if len(owning) == 1:
            if current_primary != owning:
                fixes.append({**row, "action": "set primary", "company_id": owning[0],
                              "company": companies[owning[0]].get("name"),
                              "reason": f"its domain {dom} matches the contact's; other companies stay as secondary"})
        else:
            ask.append({**row, "issue": "several companies, unclear which is primary", "options": [
                {"company_id": l["company_id"], "name": companies.get(l["company_id"], {}).get("name")} for l in links],
                "reason": "no associated company owns the contact's domain" if not owning
                else "more than one associated company owns the contact's domain"})

    batches = [{"objects": [{"objectType": "contacts", "objectId": int(f["contact_id"]),
                             "associations": [{"targetObjectId": int(f["company_id"]),
                                               "targetObjectType": "companies", "labels": ["Primary"]}]}
                            for f in fixes[i:i + 10]]} for i in range(0, len(fixes), 10)]
    out = Path(args.out_dir)
    (out / "association_fixes.json").write_text(json.dumps({"fixes": fixes, "ask_user": ask,
                                                            "connector_batches": batches}, indent=2))
    print(f"{len(fixes)} fixes proposed ({sum(f['action'] == 'associate as primary' for f in fixes)} "
          f"associate, {sum(f['action'] == 'set primary' for f in fixes)} set primary) in {len(batches)} "
          f"batches; {len(ask)} need the user -> {out / 'association_fixes.json'}")


def domain_root(domain):
    """acme.com / acme.co.uk / shop.acme.com -> acme"""
    parts = hm.norm_domain(domain).split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "net", "org") and len(parts[-1]) == 2:
        parts = parts[:-2]
    else:
        parts = parts[:-1]
    return parts[-1] if parts else ""


def digits(phone):
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def find_dupes(args):
    snap = json.loads(Path(args.snapshot).read_text())
    portal = snap["portal"]
    # The segment's companies: those associated with its contacts.
    seg_ids = {l["company_id"] for c in snap["contacts"].values() for l in c["companies"]}
    seg = {cid: snap["companies"][cid] for cid in seg_ids if cid in snap["companies"]}

    queries, linkedin, phones = set(), set(), set()
    for p in seg.values():
        for d in company_domains(p):
            root = domain_root(d)
            if len(root) >= 3:
                queries |= {root, root.replace("-", "")}
        name = hm.norm_company_name(p.get("name"))
        if name:
            queries.add(name[:200])
        slug = hm.linkedin_slug(p.get("linkedin_company_page"), "company")
        if slug:
            linkedin |= {f"{s}www.linkedin.com/company/{slug}{t}" for s in ("http://", "https://") for t in ("", "/")}
        if digits(p.get("phone")):
            phones.add(p["phone"])

    found = {}
    for q in sorted(queries):
        resp = hm.api("POST", "/crm/v3/objects/companies/search", {"query": q, "limit": 50, "properties": COMPANY_PROPS})
        found.update({r["id"]: r.get("properties", {}) for r in resp.get("results", [])})
    for prop, values in (("linkedin_company_page", linkedin), ("phone", phones)):
        for chunk in hm.chunks(values):
            resp = hm.api("POST", "/crm/v3/objects/companies/search", {
                "limit": 200, "properties": COMPANY_PROPS,
                "filterGroups": [{"filters": [{"propertyName": prop, "operator": "IN", "values": chunk}]}]})
            found.update({r["id"]: r.get("properties", {}) for r in resp.get("results", [])})

    groups = []
    for cid, p in seg.items():
        doms = company_domains(p)
        roots = {domain_root(d) for d in doms} - {""}
        roots |= {r.replace("-", "") for r in roots}
        cands = []
        for rid, q in found.items():
            if rid == cid:
                continue
            reasons = []
            qdoms = company_domains(q)
            if doms & qdoms:
                reasons.append("same domain")
            elif roots & ({domain_root(d) for d in qdoms} | {domain_root(d).replace("-", "") for d in qdoms}):
                reasons.append(f"domain variant ({', '.join(sorted(qdoms))})")
            li = hm.linkedin_slug(p.get("linkedin_company_page"), "company")
            if li and hm.linkedin_slug(q.get("linkedin_company_page"), "company") == li:
                reasons.append("same LinkedIn company page")
            if digits(p.get("phone")) and digits(p.get("phone")) == digits(q.get("phone")):
                reasons.append("same phone")
            sim = hm.name_similarity(p.get("name"), q.get("name"))
            place = hm.same_location(p, q)
            if sim >= 0.85 and place:
                reasons.append(f"similar name, same {place}")
            elif sim >= 0.85 and reasons:
                reasons.append("similar name")
            if not reasons:
                continue
            cands.append({"record_id": rid, "url": url(portal, "0-2", rid), "name": q.get("name"),
                          "domain": q.get("domain"), "location": ", ".join(x for x in (q.get("city"), q.get("state"), q.get("country")) if x) or q.get("location") or "",
                          "employees": q.get("numberofemployees"), "contacts": q.get("num_associated_contacts"),
                          "type": q.get("type"), "created": (q.get("createdate") or "")[:10], "reasons": reasons})
        if cands:
            groups.append({"company_id": cid, "url": url(portal, "0-2", cid), "name": p.get("name"),
                           "domain": p.get("domain"), "location": ", ".join(x for x in (p.get("city"), p.get("state"), p.get("country")) if x) or p.get("location") or "",
                           "employees": p.get("numberofemployees"), "contacts": p.get("num_associated_contacts"),
                           "candidates": cands})
    # A pair found from both sides is one group.
    seen, unique = set(), []
    for g in groups:
        key = frozenset([g["company_id"]] + [c["record_id"] for c in g["candidates"]])
        if key not in seen:
            seen.add(key)
            unique.append(g)
    out = Path(args.out_dir)
    (out / "company_dupes.json").write_text(json.dumps(unique, indent=2))
    print(f"{len(seg)} segment companies checked; {len(unique)} have possible duplicates -> {out / 'company_dupes.json'}")


def coverage(args):
    config = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
    fields = config["enrichment_fields"]
    list_id, name = find_list(args.segment)
    ids, after = [], None
    while True:
        resp = hm.api("GET", f"/crm/v3/lists/{list_id}/memberships?limit=250" + (f"&after={after}" if after else ""))
        ids += [str(r["recordId"]) for r in resp.get("results", [])]
        after = (resp.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    contacts = batch_read("contacts", ids, fields)
    counts = {f: sum(1 for p in contacts.values() if (p.get(f) or "").strip()) for f in fields}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"coverage_{args.label}.json"
    path.write_text(json.dumps({"segment": name, "contacts": len(contacts), "filled": counts}, indent=2))
    before = out / "coverage_before.json"
    base = json.loads(before.read_text())["filled"] if args.label != "before" and before.exists() else None
    print(f"segment {name!r}: {len(contacts)} contacts")
    for f in fields:
        change = f" ({counts[f] - base.get(f, 0):+d})" if base is not None else ""
        print(f"  {f}: {counts[f]}/{len(contacts)}{change}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull-segment")
    p.add_argument("--segment", required=True, help="segment name or list ID")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=pull_segment)
    c = sub.add_parser("coverage")
    c.add_argument("--segment", required=True)
    c.add_argument("--label", required=True, help="before | after")
    c.add_argument("--out-dir", required=True)
    c.set_defaults(func=coverage)
    for name, func in (("review-associations", review_associations), ("find-dupes", find_dupes)):
        s = sub.add_parser(name)
        s.add_argument("--snapshot", required=True)
        s.add_argument("--out-dir", required=True)
        s.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
