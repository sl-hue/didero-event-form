"""Step 3 — HubSpot duplicate matching.

The script never talks to HubSpot itself: Claude runs the searches through the
HubSpot connector, saves each raw response as a JSON file in a folder, and the
script scores the results. Companies first (they are the anchor records), then
contacts.

  check-token       Confirm HUBSPOT_PRIVATE_APP_TOKEN works (never prints it).
  run-plan          Run a search plan directly against the HubSpot API with the
                    private app token, saving responses in the same format the
                    connector returns. Much faster than running the plan
                    through the connector; use the connector only as fallback.
  plan-companies    Write the HubSpot searches to run for the company file.
  match-companies   Score saved HubSpot company results against the company
                    file -> company_matches.json.
  apply-companies   Add "HubSpot Company Record ID" to the company file (from
                    company_decisions.json) and sync company fields into the
                    contact file.
  plan-contacts     Write the HubSpot searches to run for the contact file.
  match-contacts    Score saved HubSpot contact results -> contact_matches.json.
  apply-contacts    Add "HubSpot Contact Record ID" to the contact file.

Decision files map the list record to the surviving HubSpot record, or null
when it is not in HubSpot:
  company_decisions.json  {"<ZoomInfo Company ID>": {"record_id": "123" | null, "note": "..."}}
  contact_decisions.json  {"<ZoomInfo Contact ID>": {"record_id": "456" | null, "note": "..."}}
"""
import argparse
import csv
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

COMPANY_ID = "ZoomInfo Company ID"
CONTACT_ID = "ZoomInfo Contact ID"
COMPANY_RECORD = "HubSpot Company Record ID"
CONTACT_RECORD = "HubSpot Contact Record ID"
NOT_IN_HUBSPOT = "Not in HubSpot"
HUBSPOT_LINKEDIN = "lgm_linkedinurl"  # "Linkedin Url (Default)"
CHUNK = 100

COMPANY_PROPERTIES = [
    "name", "domain", "website", "city", "state", "country", "zoominfo_company_id",
    "linkedin_company_page", "numberofemployees", "annualrevenue", "industry",
    "num_associated_contacts", "type", "createdate",
]
CONTACT_PROPERTIES = [
    "firstname", "lastname", "email", "jobtitle", "company", "city", "state", "country",
    HUBSPOT_LINKEDIN, "associatedcompanyid", "zoominfo_contact_id", "createdate",
]
# Company fields the contact file carries; kept identical to the company file.
SYNCED_COMPANY_FIELDS = ["Company Name", "Website", "Company HQ Phone"]

NICKNAMES = {
    "william": {"bill", "billy", "will", "willy", "liam"}, "robert": {"bob", "bobby", "rob", "robbie", "bert"},
    "richard": {"rick", "ricky", "rich", "dick"}, "michael": {"mike", "mikey", "mick"},
    "james": {"jim", "jimmy", "jamie"}, "joseph": {"joe", "joey"}, "thomas": {"tom", "tommy"},
    "christopher": {"chris", "topher"}, "daniel": {"dan", "danny"}, "matthew": {"matt"},
    "anthony": {"tony"}, "andrew": {"andy", "drew", "aj"}, "joshua": {"josh"},
    "jeffrey": {"jeff"}, "steven": {"steve"}, "stephen": {"steve"}, "timothy": {"tim"},
    "patrick": {"pat"}, "peter": {"pete"}, "ronald": {"ron", "ronnie"}, "donald": {"don", "donnie"},
    "samuel": {"sam", "sammy"}, "benjamin": {"ben", "benny"}, "edward": {"ed", "eddie", "ted"},
    "gregory": {"greg"}, "kenneth": {"ken", "kenny"}, "nicholas": {"nick"}, "jonathan": {"jon"},
    "bradley": {"brad"}, "arthur": {"art"}, "charles": {"charlie", "chuck"}, "david": {"dave"},
    "douglas": {"doug"}, "gerald": {"jerry"}, "lawrence": {"larry"}, "raymond": {"ray"},
    "elizabeth": {"liz", "beth", "betsy", "eliza"}, "katherine": {"kate", "katie", "kathy"},
    "catherine": {"cathy", "kate", "katie"}, "jennifer": {"jen", "jenny"}, "rebecca": {"becky"},
    "susan": {"sue", "susie"}, "margaret": {"maggie", "peggy", "meg"}, "sandra": {"sandy"},
    "patricia": {"pat", "patty", "trish"}, "deborah": {"deb", "debbie"}, "kimberly": {"kim"},
    "christine": {"chris", "chrissy"}, "jacob": {"jake"}, "zachary": {"zach"}, "alexander": {"alex"},
    "frederick": {"fred"}, "phillip": {"phil"}, "philip": {"phil"}, "leonard": {"len", "lenny"},
}


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def letters(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_domain(value):
    v = (value or "").strip().lower()
    v = re.sub(r"^[a-z]+://", "", v)
    v = v.split("/")[0].split("?")[0]
    return v[4:] if v.startswith("www.") else v


def linkedin_slug(url, kind):
    m = re.search(rf"linkedin\.com/{kind}/([^/?#]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


COMPANY_STOPWORDS = {"the", "inc", "llc", "co", "corp", "corporation", "company", "ltd", "lp", "plc", "and"}


def norm_company_name(name):
    words = re.sub(r"[^a-z0-9 ]", " ", re.sub(r"['’.]", "", (name or "").lower()).replace("&", " and ")).split()
    return " ".join(w for w in words if w not in COMPANY_STOPWORDS)


# Words too common in company names to signal a duplicate on their own.
GENERIC_WORDS = {"supply", "supplies", "industries", "industry", "group", "distribution", "products",
                 "materials", "building", "solutions", "services", "international", "holdings",
                 "manufacturing", "mfg", "systems", "enterprises", "partners", "global", "usa", "america"}


def name_similarity(a, b):
    a, b = norm_company_name(a), norm_company_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta = [w for w in a.split() if w not in GENERIC_WORDS] or a.split()
    tb = [w for w in b.split() if w not in GENERIC_WORDS] or b.split()
    da, db = " ".join(ta), " ".join(tb)
    ratio = SequenceMatcher(None, da, db).ratio()
    # Whole-word containment ("Kodiak" in "Kodiak Building Partners"); weaker
    # for short acronyms, which collide with unrelated names ("EMS").
    small, big = (set(ta), set(tb)) if len(ta) <= len(tb) else (set(tb), set(ta))
    if small <= big:
        ratio = max(ratio, 0.85 if len("".join(small)) >= 5 else 0.7)
    return ratio


def load_records(raw_dir):
    """Every record in every saved HubSpot response, de-duplicated by id."""
    records, url_template = {}, ""
    for path in sorted(Path(raw_dir).glob("*.json")):
        data = json.loads(path.read_text())
        for resp in data if isinstance(data, list) else [data]:
            url_template = resp.get("urlTemplate") or url_template
            for rec in resp.get("results", []):
                records[str(rec["id"])] = rec.get("properties", {})
    return records, url_template


def record_url(template, record_id):
    return template.replace("{id}", str(record_id)).split("?")[0] if template else ""


def chunks(values, size=CHUNK):
    values = sorted(set(v for v in values if v))
    return [values[i:i + size] for i in range(0, len(values), size)]


def in_searches(object_type, prop, values, properties):
    return [{"objectType": object_type, "properties": properties,
             "filterGroups": [{"filters": [{"propertyName": prop, "operator": "IN", "values": chunk}]}],
             "limit": 200} for chunk in chunks(values)]


# ---------------------------------------------------------------- HubSpot API

API = "https://api.hubapi.com"
TOKEN_VAR = "HUBSPOT_PRIVATE_APP_TOKEN"
OBJECT_PATHS = {"COMPANY": "companies", "CONTACT": "contacts"}
OBJECT_TYPE_IDS = {"COMPANY": "0-2", "CONTACT": "0-1"}


def api(method, path, body=None):
    token = os.environ.get(TOKEN_VAR)
    if not token:
        raise SystemExit(f"{TOKEN_VAR} is not set; see the skill's setup section, or run the plan "
                         "through the HubSpot connector instead")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(6):
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:  # rate limit / transient: back off
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f"HubSpot API {method} {path} failed: {e.code} {e.read()[:300]!r}")
    raise SystemExit(f"HubSpot API {method} {path}: still rate-limited after retries")


def check_token(args):
    info = api("GET", "/account-info/v3/details")
    api("POST", "/crm/v3/objects/companies/search", {"limit": 1})
    api("POST", "/crm/v3/objects/contacts/search", {"limit": 1})
    print(f"token OK for HubSpot portal {info.get('portalId')}: can read companies and contacts")


def run_plan(args):
    searches = json.loads(Path(args.plan).read_text())
    out = Path(args.raw_dir)
    out.mkdir(parents=True, exist_ok=True)
    portal = api("GET", "/account-info/v3/details").get("portalId")
    total = 0
    for i, spec in enumerate(searches):
        obj = spec["objectType"]
        template = f"https://app.hubspot.com/contacts/{portal}/record/{OBJECT_TYPE_IDS[obj]}/{{id}}"
        groups = spec.get("filterGroups") or []
        assoc = groups[0].get("associatedWith") if groups else None
        if assoc:
            results = associated_records(assoc[0], spec["properties"])
        else:
            body = {"limit": min(spec.get("limit", 100), 200), "properties": spec["properties"]}
            if groups:
                body["filterGroups"] = groups
            if spec.get("query"):
                body["query"] = spec["query"]
            results, after = [], None
            while True:
                if after:
                    body["after"] = after
                resp = api("POST", f"/crm/v3/objects/{OBJECT_PATHS[obj]}/search", body)
                results += resp.get("results", [])
                after = (resp.get("paging") or {}).get("next", {}).get("after")
                # Free-text name searches only need the first page.
                if not after or spec.get("query"):
                    break
                time.sleep(0.25)
        recs = [{"id": r["id"], "properties": r.get("properties", {})} for r in results]
        (out / f"{i:03d}.json").write_text(json.dumps({"results": recs, "total": len(recs),
                                                        "urlTemplate": template}))
        total += len(recs)
        time.sleep(0.25)  # stay under the search API's per-second limit
    print(f"ran {len(searches)} searches, {total} records -> {out}")


def associated_records(assoc, properties):
    """Contacts associated with any of the given companies (REST search can't filter on this)."""
    ids = []
    for company_id in assoc["objectIdValues"]:
        after = None
        while True:
            path = f"/crm/v4/objects/companies/{company_id}/associations/contacts?limit=500"
            resp = api("GET", path + (f"&after={after}" if after else ""))
            ids += [str(r["toObjectId"]) for r in resp.get("results", [])]
            after = (resp.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break
    results, unique = [], sorted(set(ids))
    for k in range(0, len(unique), 100):
        resp = api("POST", "/crm/v3/objects/contacts/batch/read",
                   {"properties": properties, "inputs": [{"id": x} for x in unique[k:k + 100]]})
        results += resp.get("results", [])
    return results


# ---------------------------------------------------------------- companies

def company_domains(row):
    extra = [d.strip() for d in (row.get("Additional Domains") or "").split(";")]
    return [d for d in [row.get("Company Domain", "").strip()] + extra if d]


def plan_companies(args):
    _, companies = read_rows(args.companies)
    domains, websites, zi_ids, linkedin = [], [], [], []
    for c in companies:
        domains += company_domains(c)
        site = norm_domain(c.get("Website"))
        if site:
            websites += [site, "www." + site]
        zi_ids.append(c.get(COMPANY_ID, ""))
        slug = linkedin_slug(c.get("LinkedIn Company Profile URL"), "company")
        if slug:
            linkedin += [f"{p}www.linkedin.com/company/{slug}{t}" for p in ("http://", "https://") for t in ("", "/")]
    searches = (in_searches("COMPANY", "domain", domains, COMPANY_PROPERTIES)
                + in_searches("COMPANY", "website", websites, COMPANY_PROPERTIES)
                + in_searches("COMPANY", "zoominfo_company_id", zi_ids, COMPANY_PROPERTIES)
                + in_searches("COMPANY", "linkedin_company_page", linkedin, COMPANY_PROPERTIES))
    # Free-text name search per company catches duplicates filed under another domain.
    for c in companies:
        query = norm_company_name(c["Company Name"]) or c["Company Name"]
        searches.append({"objectType": "COMPANY", "query": query[:200], "properties": COMPANY_PROPERTIES,
                         "limit": 20, "for": c[COMPANY_ID]})
    write_plan(args.out_dir, "company_search_plan.json", searches)


def write_plan(out_dir, name, searches):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(searches, indent=2))
    print(f"{len(searches)} HubSpot searches -> {out / name}")


def match_companies(args):
    _, companies = read_rows(args.companies)
    records, template = load_records(args.raw_dir)
    matches = []
    for c in companies:
        domains = {d.lower() for d in company_domains(c)}
        site = norm_domain(c.get("Website"))
        li = linkedin_slug(c.get("LinkedIn Company Profile URL"), "company")
        cands = []
        for rid, p in records.items():
            reasons = []
            if norm_domain(p.get("domain")) in domains:
                reasons.append(f"domain {norm_domain(p.get('domain'))}")
            if site and norm_domain(p.get("website")) == site:
                reasons.append("same website")
            elif norm_domain(p.get("website")) in domains:
                reasons.append(f"website on {norm_domain(p.get('website'))}")
            if p.get("zoominfo_company_id") and str(p["zoominfo_company_id"]).split(".")[0] == c[COMPANY_ID]:
                reasons.append("same ZoomInfo Company ID")
            if li and linkedin_slug(p.get("linkedin_company_page"), "company") == li:
                reasons.append("same LinkedIn company page")
            sim = name_similarity(c["Company Name"], p.get("name"))
            same_place = [f for f, h in (("Company City", "city"), ("Company State", "state"),
                                         ("Company Country", "country"))
                          if c.get(f) and (p.get(h) or "").strip().lower() == c[f].strip().lower()]
            if sim >= 0.85:
                reasons.append(f"similar name ({p.get('name')})" + (f", same {'/'.join(h.split()[-1].lower() for h in same_place)}" if same_place else ""))
            elif sim >= 0.7 and len(same_place) >= 2:
                reasons.append(f"partly similar name ({p.get('name')}) in same {'/'.join(h.split()[-1].lower() for h in same_place)}")
            if not reasons:
                continue
            strong = any(r.startswith(("domain", "same website", "website on", "same ZoomInfo", "same LinkedIn")) for r in reasons)
            cands.append({"record_id": rid, "url": record_url(template, rid), "strength": "strong" if strong else "possible",
                          "reasons": reasons, "name": p.get("name"), "domain": p.get("domain"),
                          "website": p.get("website"), "location": ", ".join(x for x in (p.get("city"), p.get("state"), p.get("country")) if x),
                          "employees": p.get("numberofemployees"), "revenue": p.get("annualrevenue"),
                          "contacts": p.get("num_associated_contacts"), "type": p.get("type"),
                          "created": (p.get("createdate") or "")[:10]})
        cands.sort(key=lambda x: (x["strength"] != "strong", -len(x["reasons"])))
        matches.append({COMPANY_ID: c[COMPANY_ID], "company": c["Company Name"], "company_domain": c.get("Company Domain"),
                        "additional_domains": c.get("Additional Domains"), "website": c.get("Website"),
                        "location": ", ".join(x for x in (c.get("Company City"), c.get("Company State"), c.get("Company Country")) if x),
                        "employees": c.get("Employees"), "revenue": c.get("Revenue (in USD)"), "candidates": cands})
    write_matches(args.out_dir, "company_matches.json", matches)


def write_matches(out_dir, name, matches):
    out = Path(out_dir)
    (out / name).write_text(json.dumps(matches, indent=2))
    none = sum(1 for m in matches if not m["candidates"])
    single = sum(1 for m in matches if len(m["candidates"]) == 1 and m["candidates"][0]["strength"] == "strong")
    review = len(matches) - none - single
    print(f"{len(matches)} records: {none} not in HubSpot, {single} single strong match, "
          f"{review} need review (several candidates or only possible matches) -> {out / name}")


def apply_companies(args):
    fields, companies = read_rows(args.companies)
    decisions = json.loads(Path(args.decisions).read_text())
    missing = [c[COMPANY_ID] for c in companies if c[COMPANY_ID] not in decisions]
    if missing:
        raise SystemExit(f"company_decisions.json has no decision for: {missing}")
    for c in companies:
        c[COMPANY_RECORD] = decisions[c[COMPANY_ID]].get("record_id") or NOT_IN_HUBSPOT
    if COMPANY_RECORD not in fields:
        fields = fields + [COMPANY_RECORD]
    write_rows(args.companies, fields, companies)

    # Keep the contact file's company fields identical to the company file.
    cfields, contacts = read_rows(args.contacts)
    _, step1 = read_rows(args.contacts_step1)
    company_of = {r[CONTACT_ID]: r[COMPANY_ID] for r in step1}
    by_id = {c[COMPANY_ID]: c for c in companies}
    synced = 0
    for r in contacts:
        c = by_id.get(company_of.get(r[CONTACT_ID]))
        if not c:
            continue
        for f in SYNCED_COMPANY_FIELDS:
            if f in r and r[f] != c.get(f, ""):
                r[f] = c.get(f, "")
                synced += 1
    write_rows(args.contacts, cfields, contacts)
    found = sum(1 for c in companies if c[COMPANY_RECORD] != NOT_IN_HUBSPOT)
    print(f"{args.companies}: {found} in HubSpot, {len(companies) - found} not; "
          f"{args.contacts}: {synced} company fields synced")


# ---------------------------------------------------------------- contacts

def first_name_forms(first):
    f = letters(first)
    forms = {f}
    for full, nicks in NICKNAMES.items():
        if f == full or f in nicks:
            forms |= {full} | nicks
    return forms


def plan_contacts(args):
    _, contacts = read_rows(args.contacts)
    _, companies = read_rows(args.companies)
    urls, emails, last_names = [], [], []
    for r in contacts:
        slug = linkedin_slug(r.get("LinkedIn Contact Profile URL"), "in")
        if slug:
            urls += [f"{p}{slug}{t}" for p in ("https://www.linkedin.com/in/", "http://www.linkedin.com/in/",
                                               "https://linkedin.com/in/") for t in ("", "/")]
        if r.get("Email Address"):
            emails.append(r["Email Address"].lower())
        if r.get("Last Name"):
            last_names.append(r["Last Name"])
    searches = (in_searches("CONTACT", HUBSPOT_LINKEDIN, urls, CONTACT_PROPERTIES)
                + in_searches("CONTACT", "email", emails, CONTACT_PROPERTIES)
                + in_searches("CONTACT", "lastname", last_names, CONTACT_PROPERTIES))
    # Everyone already at the list's companies: catches short names and
    # same-title, different-name records.
    record_ids = [c[COMPANY_RECORD] for c in companies if c.get(COMPANY_RECORD) not in ("", None, NOT_IN_HUBSPOT)]
    for chunk in chunks(record_ids):
        searches.append({"objectType": "CONTACT", "properties": CONTACT_PROPERTIES, "limit": 200,
                         "filterGroups": [{"associatedWith": [{"objectType": "companies", "operator": "IN",
                                                               "objectIdValues": [int(i) for i in chunk]}]}],
                         "note": "page through with offset until all results are saved"})
    write_plan(args.out_dir, "contact_search_plan.json", searches)


def match_contacts(args):
    _, contacts = read_rows(args.contacts)
    _, companies = read_rows(args.companies)
    _, step1 = read_rows(args.contacts_step1)
    company_of = {r[CONTACT_ID]: r[COMPANY_ID] for r in step1}
    record_of = {c[COMPANY_ID]: c.get(COMPANY_RECORD) for c in companies}
    records, template = load_records(args.raw_dir)
    matches = []
    for r in contacts:
        slug = linkedin_slug(r.get("LinkedIn Contact Profile URL"), "in")
        email = (r.get("Email Address") or "").lower()
        first, last = letters(r["First Name"]), letters(r["Last Name"])
        forms = first_name_forms(r["First Name"])
        company_record = record_of.get(company_of.get(r[CONTACT_ID]))
        title = (r.get("Job Title") or "").strip().lower()
        cands = []
        for rid, p in records.items():
            reasons = []
            if slug and linkedin_slug(p.get(HUBSPOT_LINKEDIN), "in") == slug:
                reasons.append("same LinkedIn URL")
            if email and (p.get("email") or "").lower() == email:
                reasons.append("same email")
            pf, pl = letters(p.get("firstname")), letters(p.get("lastname"))
            same_company = company_record and str(p.get("associatedcompanyid") or "") == str(company_record)
            if pl == last and pf == first:
                where = [x for x, h in (("state", "Person State"), ("country", "Country"))
                         if r.get(h) and (p.get(x) or "").lower() == r[h].lower()]
                reasons.append("same name" + (", same " + "/".join(where) if where else "")
                               + (", same company" if same_company else ""))
            elif pl == last and (pf in forms or (pf and first and pf[0] == first[0] and same_company)):
                reasons.append(f"short/alternate first name ({p.get('firstname')} {p.get('lastname')})"
                               + (", same company" if same_company else ""))
            if same_company and title and (p.get("jobtitle") or "").strip().lower() == title and pl != last:
                reasons.append(f"same job title at same company, different name ({p.get('firstname')} {p.get('lastname')})")
            if not reasons:
                continue
            strong = any(x.startswith(("same LinkedIn", "same email")) for x in reasons)
            cands.append({"record_id": rid, "url": record_url(template, rid), "strength": "strong" if strong else "possible",
                          "reasons": reasons, "name": f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip(),
                          "email": p.get("email"), "job_title": p.get("jobtitle"), "company": p.get("company"),
                          "location": ", ".join(x for x in (p.get("city"), p.get("state"), p.get("country")) if x),
                          "linkedin": p.get(HUBSPOT_LINKEDIN), "created": (p.get("createdate") or "")[:10]})
        cands.sort(key=lambda x: (x["strength"] != "strong", -len(x["reasons"])))
        matches.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                        "company": r["Company Name"], "job_title": r.get("Job Title"), "email": r.get("Email Address"),
                        "linkedin": r.get("LinkedIn Contact Profile URL"),
                        "location": ", ".join(x for x in (r.get("Person City"), r.get("Person State"), r.get("Country")) if x),
                        "candidates": cands})
    write_matches(args.out_dir, "contact_matches.json", matches)


def apply_contacts(args):
    fields, contacts = read_rows(args.contacts)
    decisions = json.loads(Path(args.decisions).read_text())
    missing = [r[CONTACT_ID] for r in contacts if r[CONTACT_ID] not in decisions]
    if missing:
        raise SystemExit(f"contact_decisions.json has no decision for: {missing}")
    for r in contacts:
        r[CONTACT_RECORD] = decisions[r[CONTACT_ID]].get("record_id") or NOT_IN_HUBSPOT
    if CONTACT_RECORD not in fields:
        fields = fields + [CONTACT_RECORD]
    write_rows(args.contacts, fields, contacts)
    found = sum(1 for r in contacts if r[CONTACT_RECORD] != NOT_IN_HUBSPOT)
    print(f"{args.contacts}: {found} in HubSpot, {len(contacts) - found} not")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, func, *opts):
        p = sub.add_parser(name)
        for o in opts:
            p.add_argument(f"--{o}", required=True)
        p.set_defaults(func=func)

    add("check-token", check_token)
    add("run-plan", run_plan, "plan", "raw-dir")
    add("plan-companies", plan_companies, "companies", "out-dir")
    add("match-companies", match_companies, "companies", "raw-dir", "out-dir")
    add("apply-companies", apply_companies, "companies", "contacts", "contacts-step1", "decisions")
    add("plan-contacts", plan_contacts, "contacts", "companies", "out-dir")
    add("match-contacts", match_contacts, "contacts", "companies", "contacts-step1", "raw-dir", "out-dir")
    add("apply-contacts", apply_contacts, "contacts", "decisions")
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
