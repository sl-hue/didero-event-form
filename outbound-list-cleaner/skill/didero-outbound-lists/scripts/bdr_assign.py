"""Step 6 — BDR assignment (read-only; produces the review CSV).

Implements the list-specific rules on top of the hubspot-bdr-list-assignment
skill. Inputs are pulled from HubSpot beforehand (see SKILL.md step 6):

  --contacts     JSON {contact_id: {firstname, lastname, hubspot_owner_id,
                 associatedcompanyid}} — the segment's contacts
  --companies    TSV: company_id, name, owner_id, domain — their primary companies
  --incumbency   TSV: company_id, owner_id, contact_count — ALL contacts on each
                 company (segment included) grouped by owner
  --pool         BDRs as "Name=owner_id,Name=owner_id,..."
  --owners       JSON {owner_id: name} for readable owner columns

Rules (SKILL.md step 6):
  1. Per company, count contacts owned by pool BDRs — segment contacts
     included. The BDR with the most gets every segment contact on it and the
     company record (one BDR per company). Ties -> lightest load.
  2. No BDR contacts but the company record is owned by a pool BDR -> keep.
  3. Everything else: largest company first, to the BDR with the fewest
     contacts (then fewest companies).
  4. If the contact gap between BDRs is > 10% of the average and > 3 contacts,
     suggest locked companies that could move (the user decides).

Writes bdr_assignment.csv (sorted by company, then contact name) and
bdr_summary.json.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

FREE_MAIL = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "aol.com",
             "live.com", "msn.com", "139.com", "163.com", "126.com", "qq.com", "proton.me",
             "protonmail.com", "gmx.com", "gmx.de", "web.de", "mail.com", "yandex.ru"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ("contacts", "companies", "incumbency", "pool", "owners", "out-dir"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--flag-percent", type=float, default=10)
    ap.add_argument("--flag-min", type=int, default=3)
    args = ap.parse_args()

    config = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
    portal = config.get("hubspot_portal_id", "")

    def link(obj, rid):
        return f"https://app.hubspot.com/contacts/{portal}/record/{obj}/{rid}"

    contacts = json.loads(Path(args.contacts).read_text())
    owners = {str(k): v for k, v in json.loads(Path(args.owners).read_text()).items()}
    pool = dict(p.split("=") for p in args.pool.split(","))           # name -> id
    pool_ids = {v: owners.get(v, k) for k, v in pool.items()}          # id -> full name
    order = list(pool.values())
    companies = {}
    with open(args.companies, encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            companies[row[0]] = {"name": row[1], "owner": row[2] if len(row) > 2 else "",
                                 "domain": row[3] if len(row) > 3 else ""}
    incumbency = defaultdict(Counter)
    totals = Counter()
    with open(args.incumbency, encoding="utf-8") as f:
        for cid, oid, n in csv.reader(f, delimiter="\t"):
            totals[cid] += int(n)
            if oid in pool_ids:
                incumbency[cid][oid] += int(n)

    by_company = defaultdict(list)
    no_company = []
    for kid, c in contacts.items():
        if c.get("associatedcompanyid"):
            by_company[c["associatedcompanyid"]].append(kid)
        else:
            no_company.append(kid)

    # Sanity check: HubSpot's per-company total must cover the segment's contacts.
    mismatches = [cid for cid, ks in by_company.items() if totals.get(cid, 0) < len(ks)]

    load = Counter({o: 0 for o in order})
    company_load = Counter({o: 0 for o in order})
    assign, rule = {}, {}

    def give(cid, oid, why):
        assign[cid], rule[cid] = oid, why
        load[oid] += len(by_company[cid])
        company_load[oid] += 1

    def lightest(cands):
        return min(cands, key=lambda o: (load[o], company_load[o], order.index(o)))

    # 1 — BDR contacts on the company decide (segment contacts included).
    for cid in sorted(by_company, key=lambda c: -len(by_company[c])):
        counts = incumbency.get(cid)
        if not counts:
            continue
        top = max(counts.values())
        winners = [o for o, n in counts.items() if n == top]
        oid = winners[0] if len(winners) == 1 else lightest(winners)
        detail = ", ".join(f"{pool_ids[o]} {n}" for o, n in counts.most_common())
        give(cid, oid, f"BDR contacts on company: {detail}" + (" (tie -> lightest load)" if len(winners) > 1 else ""))
    # 2 — company record already owned by a pool BDR.
    for cid in by_company:
        if cid not in assign and companies.get(cid, {}).get("owner") in pool_ids:
            give(cid, companies[cid]["owner"], "company already owned by this BDR, no BDR contacts")
    # 3 — the rest, largest first, to the lightest BDR.
    for cid in sorted((c for c in by_company if c not in assign), key=lambda c: (-len(by_company[c]), c)):
        give(cid, lightest(order), "balance: no BDR history, lightest load")

    # 4 — imbalance flag and suggestions (locked companies whose move would help).
    avg = sum(load.values()) / len(order)
    gap = max(load.values()) - min(load.values())
    flagged = gap > avg * args.flag_percent / 100 and gap > args.flag_min
    suggestions = []
    if flagged:
        heavy, light = max(order, key=lambda o: load[o]), min(order, key=lambda o: load[o])
        for cid, oid in assign.items():
            n = len(by_company[cid])
            if oid == heavy and rule[cid].startswith("BDR contacts") and n <= gap:
                other = incumbency[cid][heavy] - n
                suggestions.append({"company": companies[cid]["name"], "company_id": cid, "url": link("0-2", cid),
                                    "segment_contacts": n, "other_contacts_owned_by_" + pool_ids[heavy]: max(other, 0),
                                    "from": pool_ids[heavy], "to": pool_ids[light]})
        suggestions.sort(key=lambda s: (s["other_contacts_owned_by_" + pool_ids[heavy]], -s["segment_contacts"]))

    rows = []
    for cid, kids in by_company.items():
        co = companies.get(cid, {"name": "", "owner": ""})
        for kid in kids:
            c = contacts[kid]
            old = c.get("hubspot_owner_id") or ""
            reason = rule[cid]
            if old == assign[cid]:
                reason = "kept: already " + pool_ids[old] + "'s; " + reason
            rows.append({"Company": co["name"], "Company Record ID": cid,
                         "Old Company Owner": owners.get(co["owner"], co["owner"]),
                         "New Company Owner": pool_ids[assign[cid]],
                         "Contact Name": f"{c.get('firstname') or ''} {c.get('lastname') or ''}".strip(),
                         "Contact Record ID": kid, "Old Contact Owner": owners.get(old, old),
                         "New Contact Owner": pool_ids[assign[cid]], "Reason": reason})
    rows.sort(key=lambda r: (r["Company"].lower(), r["Contact Name"].lower()))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "bdr_assignment.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    changing = Counter(owners.get(companies[c]["owner"], companies[c]["owner"] or "(none)")
                       for c, o in assign.items() if companies.get(c, {}).get("owner") != o)
    between = [{"company": companies[c]["name"], "url": link("0-2", c), "from": pool_ids[companies[c]["owner"]], "to": pool_ids[o]}
               for c, o in assign.items() if companies[c]["owner"] in pool_ids and companies[c]["owner"] != o]
    ties = [{"company": companies[c]["name"], "url": link("0-2", c)} for c in assign if "tie" in rule[c]]
    free_mail = [{"company": companies[c]["name"], "url": link("0-2", c), "contacts": len(by_company[c])}
                 for c in by_company if companies.get(c, {}).get("domain", "").lower() in FREE_MAIL]
    summary = {
        "per_bdr": {pool_ids[o]: {"contacts": load[o], "companies": company_load[o]} for o in order},
        "contacts": len(contacts), "companies": len(by_company),
        "no_company": [{"contact_id": k, "url": link("0-1", k)} for k in no_company],
        "contacts_changing_owner": sum(1 for r in rows if r["Old Contact Owner"] != r["New Contact Owner"]),
        "rule_counts": dict(Counter(r.split(":")[0].split(" (")[0] for r in rule.values())),
        "company_owner_changes_from": dict(changing), "companies_moving_between_bdrs": between,
        "ties": ties, "free_mail_company_records": free_mail, "count_mismatches": mismatches,
        "imbalance": {"gap": gap, "average": round(avg, 1), "flagged": flagged, "suggestions": suggestions},
    }
    (out / "bdr_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
