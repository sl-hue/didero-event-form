"""BDR owners as upload columns (v2): Claude never writes to HubSpot, so owners go into the import files.

Runs after the HubSpot duplicate check (step 3 gave each row its HubSpot company / contact
record ID, or none) and before the import files are made. Only when the end state chosen at
the start includes BDR owners (run_setup.json: bdr_pool, split).

  plan    --run-dir <run_dir>     hs_owners/plan.json: read-only query_crm_data queries — current
                                  owners of the list's existing contacts and companies, and how many
                                  contacts each owner has on those companies.
  ingest  --run-dir <run_dir> --kind contacts|companies|incumbency --batch <i> --response <file>
  assign  --run-dir <run_dir> --owners <owners.json> [--deals <deals.json>] [--company-assign <json>]
          owners.json   {"Noah": "<owner id>", ...}  (search_owners, for every BDR in run_setup.json)
          deals.json    {"<HubSpot company record id>": [{"name": "...", "stage": "...", "owner": "<id>"}]}
                        open deals only (search_crm_objects on DEAL associated with the companies)
          --company-assign {"<company name>": "<BDR name>"} — for a split rule that isn't the even split
          (the user's own rule from the start), Claude decides the companies and passes them here.
          Writes Contact Owner / Contact Owner Name / Company Owner / Company Owner Name on every row,
          bdr_assignment.csv (for the user) and owners_report.json.

Rules, per company (one BDR per company, all its contacts together):
  0. An open deal on the company -> nothing changes hands: the company owner stays, existing contacts
     keep their owner, new contacts get the company owner. Listed in the report.
  1. Pool BDRs already owning contacts on the company (HubSpot) -> the one with the most gets the
     company and every list contact on it. Ties -> lightest load.
  2. The company record already owned by a pool BDR -> that BDR.
  3. Everything else, even split: largest company first, to the BDR with the fewest contacts so far
     (then fewest companies). All contacts of one account go to one BDR.
Existing contacts owned by anyone outside the pool get the company's BDR (rule 0 aside).
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import worksheet as ws  # noqa: E402
from setup import load_setup  # noqa: E402

BATCH = 100
NUM = re.compile(r"^\d+$")


def rid(v):
    v = (v or "").strip()
    return v if NUM.match(v) else ""


def plan(args):
    _, rows = ws.load(args.run_dir)
    contacts = sorted({rid(r.get("HubSpot Contact Record ID")) for r in rows} - {""})
    companies = sorted({rid(r.get("HubSpot Company Record ID")) for r in rows} - {""})
    q = lambda xs: ", ".join(f"'{x}'" for x in xs)
    chunks = lambda xs: [xs[i:i + BATCH] for i in range(0, len(xs), BATCH)]
    p = {"contacts": [f"SELECT hs_object_id, hubspot_owner_id FROM CONTACT WHERE hs_object_id IN ({q(c)})"
                      for c in chunks(contacts)],
         "companies": [f"SELECT hs_object_id, name, hubspot_owner_id FROM COMPANY WHERE hs_object_id IN ({q(c)})"
                       for c in chunks(companies)],
         "incumbency": [f"SELECT associatedcompanyid, hubspot_owner_id, COUNT(*) FROM CONTACT WHERE associatedcompanyid "
                        f"IN ({q(c)}) GROUP BY associatedcompanyid, hubspot_owner_id" for c in chunks(companies)]}
    d = Path(args.run_dir) / "hs_owners"
    d.mkdir(exist_ok=True)
    (d / "plan.json").write_text(json.dumps(p, indent=1))
    st = load_setup(args.run_dir)
    print(f"{len(contacts)} existing contacts, {len(companies)} existing companies -> hs_owners/plan.json "
          f"({sum(len(v) for v in p.values())} read-only query_crm_data calls; ingest each with --kind/--batch).")
    print(f"Also: search_owners for {', '.join(st.get('bdr_pool', [])) or 'the BDRs'} -> owners.json "
          "{\"Name\": \"<owner id>\"}; open deals on those companies (search_crm_objects, DEAL associated with "
          "the company, not closed) -> deals.json. Then: owners.py assign.")


def ingest(args):
    d = Path(args.run_dir) / "hs_owners"
    data = json.loads(Path(args.response).read_text())
    (d / f"{args.kind}_{args.batch}.json").write_text(json.dumps(data, ensure_ascii=False))
    print(f"saved {args.kind} batch {args.batch}")


def records(data):
    out = []
    for item in (data.get("results", []) if isinstance(data, dict) else data):
        c = item.get("content", item) if isinstance(item, dict) else item
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except ValueError:
                continue
        props = c.get("properties", c) if isinstance(c, dict) else {}
        if props.get("hs_object_id"):
            out.append(props)
    return out


def incumbency_rows(data):
    """GROUP BY results come back as a TSV inside 'content' (checked on a real call)."""
    out = []
    for item in data.get("results", []) if isinstance(data, dict) else []:
        text = item.get("content", "") if isinstance(item, dict) else ""
        if "\t" not in text:
            continue
        lines = [l for l in text.splitlines() if "\t" in l]
        for l in lines[1:]:
            parts = l.split("\t")
            if len(parts) >= 3 and NUM.match(parts[0].strip()):
                out.append((parts[0].strip(), parts[1].strip(), int(float(parts[2] or 0))))
    return out


def assign(args):
    run = Path(args.run_dir)
    st = load_setup(run)
    pool_names = st.get("bdr_pool") or []
    if not pool_names:
        raise SystemExit("no BDRs in run_setup.json: the end state is 'upload files only' — skip this step")
    owners = {k: str(v) for k, v in json.loads(Path(args.owners).read_text()).items()}
    missing = [n for n in pool_names if n not in owners]
    if missing:
        raise SystemExit(f"no owner id for {', '.join(missing)} in {args.owners} (search_owners)")
    pool = {owners[n]: n for n in pool_names}                       # owner id -> name
    deals = json.loads(Path(args.deals).read_text()) if args.deals else {}
    manual = json.loads(Path(args.company_assign).read_text()) if args.company_assign else {}
    d = run / "hs_owners"
    c_owner, co_owner, co_names, inc = {}, {}, {}, defaultdict(Counter)
    for f in sorted(d.glob("contacts_*.json")):
        for r in records(json.loads(f.read_text())):
            c_owner[r["hs_object_id"]] = r.get("hubspot_owner_id") or ""
    for f in sorted(d.glob("companies_*.json")):
        for r in records(json.loads(f.read_text())):
            co_owner[r["hs_object_id"]] = r.get("hubspot_owner_id") or ""
            if r.get("hubspot_owner_id_formatted"):
                co_names[r["hubspot_owner_id"]] = r["hubspot_owner_id_formatted"]
    for f in sorted(d.glob("incumbency_*.json")):
        for co, own, n in incumbency_rows(json.loads(f.read_text())):
            inc[co][own] += n

    fields, rows = ws.load(run)
    fields = ws.ensure_columns(fields, ["Contact Owner", "Contact Owner Name", "Company Owner", "Company Owner Name"])
    groups = defaultdict(list)
    for r in rows:
        groups[r[ws.COMPANY_ID]].append(r)
    load_c, load_k = Counter(), Counter()
    decided, queue, notes = {}, [], defaultdict(list)
    for key, rs in groups.items():
        name = rs[0].get("Company Name", "")
        hs = rid(rs[0].get("HubSpot Company Record ID"))
        if name in manual:
            decided[key] = (owners.get(manual[name], ""), f"split rule from the start: {manual[name]}")
            continue
        if hs and deals.get(hs):
            decided[key] = ("KEEP", f"open deal(s): {', '.join(x.get('name', '') for x in deals[hs])} — owners unchanged")
            continue
        counts = {o: n for o, n in inc.get(hs, {}).items() if o in pool}
        for r in rs:  # list contacts already owned by a pool BDR count too
            o = c_owner.get(rid(r.get("HubSpot Contact Record ID")), "")
            if o in pool and not hs:
                counts[o] = counts.get(o, 0) + 1
        if counts:
            top = max(counts.values())
            best = sorted([o for o, n in counts.items() if n == top], key=lambda o: (load_c[o], load_k[o]))[0]
            decided[key] = (best, f"{pool[best]} already has {top} contact(s) on this company")
        elif hs and co_owner.get(hs) in pool:
            decided[key] = (co_owner[hs], f"company record already owned by {pool[co_owner[hs]]}")
        else:
            queue.append(key)
            continue
        load_c[decided[key][0]] += len(rs)
        load_k[decided[key][0]] += 1
    for key in sorted(queue, key=lambda k: -len(groups[k])):
        best = sorted(pool, key=lambda o: (load_c[o], load_k[o]))[0]
        decided[key] = (best, "even split (account kept together)")
        load_c[best] += len(groups[key])
        load_k[best] += 1

    name_of = lambda o: pool.get(o) or co_names.get(o, o)
    out = []
    for key, rs in groups.items():
        bdr, why = decided[key]
        hs = rid(rs[0].get("HubSpot Company Record ID"))
        if bdr == "KEEP":
            company_owner = co_owner.get(hs, "")
        else:
            company_owner = bdr
        for r in rs:
            existing = c_owner.get(rid(r.get("HubSpot Contact Record ID")), "")
            contact_owner = (existing or company_owner) if bdr == "KEEP" else bdr
            r["Contact Owner"], r["Contact Owner Name"] = contact_owner, name_of(contact_owner) if contact_owner else ""
            r["Company Owner"], r["Company Owner Name"] = company_owner, name_of(company_owner) if company_owner else ""
            out.append({"Company": r.get("Company Name", ""), "Company Record ID": hs or "new",
                        "Old Company Owner": name_of(co_owner.get(hs, "")) if hs else "",
                        "New Company Owner": r["Company Owner Name"],
                        "Contact": f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip(),
                        "Contact Record ID": rid(r.get("HubSpot Contact Record ID")) or "new",
                        "Old Contact Owner": name_of(existing) if existing else "",
                        "New Contact Owner": r["Contact Owner Name"], "Reason": why})
            if bdr == "KEEP":
                notes["open deals"].append(r.get("Company Name", ""))
    ws.save(run, fields, rows)
    ws.log(run, {"action": "owners", "bdrs": pool_names, "contacts": dict(Counter(r["Contact Owner Name"] for r in rows))})
    out.sort(key=lambda x: (x["Company"].lower(), x["Contact"].lower()))
    with open(run / "bdr_assignment.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    per = {pool[o]: {"contacts": load_c[o], "companies": load_k[o]} for o in pool}
    (run / "owners_report.json").write_text(json.dumps({"per_bdr": per, "open_deal_companies": sorted(set(notes["open deals"])),
                                                       "split": st.get("split")}, indent=1))
    print("owners set on every row: " + "; ".join(f"{n}: {v['contacts']} contacts / {v['companies']} companies"
                                                  for n, v in per.items()))
    if notes["open deals"]:
        print(f"open deals, owners left unchanged: {', '.join(sorted(set(notes['open deals'])))}")
    print("bdr_assignment.csv written (send it with the upload files). Carry on: no stop.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--run-dir", required=True); p.set_defaults(func=plan)
    p = sub.add_parser("ingest"); p.add_argument("--run-dir", required=True)
    p.add_argument("--kind", required=True, choices=["contacts", "companies", "incumbency"])
    p.add_argument("--batch", type=int, required=True); p.add_argument("--response", required=True)
    p.set_defaults(func=ingest)
    p = sub.add_parser("assign"); p.add_argument("--run-dir", required=True); p.add_argument("--owners", required=True)
    p.add_argument("--deals"); p.add_argument("--company-assign"); p.set_defaults(func=assign)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
