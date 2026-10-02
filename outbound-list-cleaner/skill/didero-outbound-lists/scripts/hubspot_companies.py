"""Event lists — pull company data from HubSpot first (fast), research only the rest.

HubSpot already holds most companies we meet at events. One query_crm_data
call can match dozens of names / domains at once and returns website domain,
city, state, country, employees, revenue and the record ID — far faster than
researching each company on the web. Only what HubSpot doesn't have goes to web
research; later enrichment (ZoomInfo, Clay) keeps the data up to date.

Works on either file: --kind companies (company-only lists: companies.csv) or
--kind event (event contact lists: event.csv, one row per person).

  plan    --run-dir <run_dir> --kind companies|event [--pass 1|2]
          hs/plan_<pass>.json: SQL queries for the HubSpot connector's
          query_crm_data (pass 1: exact name or domain; pass 2, for companies
          still unmatched: name contains the company's main word).
  ingest  --run-dir <run_dir> --pass <n> --batch <i> --response <file>
  apply   --run-dir <run_dir> --kind companies|event
          Matches HubSpot records to the list's companies (domain = sure; same
          name = sure; similar name = ask the user), writes the HubSpot values
          and the HubSpot record ID, and lists what still needs web research.
          --decisions <json> {"<company>": "<hs_object_id>" | "none"} settles the
          "ask the user" ones.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from zoominfo_merge import norm_company, same_company  # noqa: E402

BATCH = 40
PROPS = "hs_object_id, name, domain, city, state, country, numberofemployees, annualrevenue"
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com", "msn.com"}
GENERIC = {"inc", "llc", "ltd", "corp", "company", "co", "group", "the", "and", "of", "international", "global",
           "industries", "solutions", "services", "systems", "products", "technologies", "holdings", "usa", "us"}


# ---------- adapters: one company list, whatever the file ----------
def load(run, kind):
    p = Path(run) / ("companies.csv" if kind == "companies" else "event.csv")
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return p, list(r.fieldnames), list(r)


def save(p, fields, rows):
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(p)


COLS = {"companies": {"name": "Company", "site": "Website", "city": "City", "state": "State", "country": "Country",
                      "emp": "Employees", "rev": "Revenue", "src": "Research Source"},
        "event": {"name": "Company", "site": "Company Website", "city": "Company City", "state": "Company State",
                  "country": "Company Country", "emp": "Company Employees", "rev": "Company Revenue",
                  "src": "Company Data Source"}}


def host(url):
    h = re.sub(r"^[a-z]+://", "", (url or "").strip().lower()).split("/")[0]
    return h[4:] if h.startswith("www.") else h


def companies(rows, kind):
    """{company name: {"domains": set, "rows": [...]}} (excluded companies left out)."""
    c = COLS[kind]
    out = {}
    for r in rows:
        if r.get("Status") == "excluded" or not r.get(c["name"]):
            continue
        e = out.setdefault(r[c["name"]], {"domains": set(), "rows": []})
        e["rows"].append(r)
        if r.get(c["site"]):
            e["domains"].add(host(r[c["site"]]))
        em = (r.get("Email") or "").lower()
        if "@" in em and em.split("@")[1] not in FREE:
            e["domains"].add(em.split("@")[1])
    return out


def q(s):
    return "'" + s.replace("'", "''") + "'"


def main_word(name):
    words = [w for w in norm_company(name).split() if w not in GENERIC and len(w) >= 3]
    return max(words, key=len) if words else ""


def plan(args):
    _, _, rows = load(args.run_dir, args.kind)
    cos = companies(rows, args.kind)
    d = Path(args.run_dir) / "hs"
    d.mkdir(exist_ok=True)
    if args.pass_ == 2:
        state = json.loads((d / "matches.json").read_text()) if (d / "matches.json").exists() else {}
        todo = [n for n in cos if not state.get(n, {}).get("id")]
        conds = sorted({f"name LIKE {q('%' + main_word(n) + '%')}" for n in todo if main_word(n)})
    else:
        conds = []
        for n, e in cos.items():
            conds.append(f"name = {q(n)}")
            conds += [f"domain = {q(dm)}" for dm in sorted(e["domains"]) if dm]
        conds = list(dict.fromkeys(conds))
    sqls = [f"SELECT {PROPS} FROM COMPANY WHERE " + " OR ".join(conds[i:i + BATCH]) + " LIMIT 500"
            for i in range(0, len(conds), BATCH)]
    (d / f"plan_{args.pass_}.json").write_text(json.dumps(sqls, indent=1, ensure_ascii=False))
    done = [i for i in range(len(sqls)) if (d / f"result_{args.pass_}_{i}.json").exists()]
    print(f"pass {args.pass_}: {len(sqls)} HubSpot queries for {len(cos)} companies -> hs/plan_{args.pass_}.json "
          f"({len(done)} already run). Run each with query_crm_data (verbosityLevel LOW), save the result, then "
          f"hubspot_companies.py ingest --pass {args.pass_} --batch <i> --response <file>.")


def ingest(args):
    d = Path(args.run_dir) / "hs"
    data = json.loads(Path(args.response).read_text())
    (d / f"result_{args.pass_}_{args.batch}.json").write_text(json.dumps(data, ensure_ascii=False))
    print(f"saved pass {args.pass_} batch {args.batch}: {len(records(data))} HubSpot companies")


def records(data):
    """query_crm_data results: {"results": [{"content": "<json with properties>"}]} (or already parsed)."""
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


def apply(args):
    run = Path(args.run_dir)
    d = run / "hs"
    p, fields, rows = load(run, args.kind)
    c = COLS[args.kind]
    for col in [c[k] for k in ("site", "city", "state", "country", "emp", "rev", "src")] + ["HubSpot Company Record ID"]:
        if col not in fields:
            fields.append(col)
    recs = {}
    for f in sorted(d.glob("result_*_*.json")):
        for r in records(json.loads(f.read_text())):
            recs[r["hs_object_id"]] = r
    decisions = json.loads(Path(args.decisions).read_text()) if args.decisions else {}
    cos = companies(rows, args.kind)
    matches, ask, research = {}, [], []
    for name, e in cos.items():
        if name in decisions:
            hid = decisions[name]
            matches[name] = {"id": "" if hid in ("none", "", None) else str(hid), "how": "user"}
            continue
        by_domain = [r for r in recs.values() if host(r.get("domain")) and host(r.get("domain")) in e["domains"]]
        by_name = [r for r in recs.values() if norm_company(r.get("name")) == norm_company(name)]
        similar = [r for r in recs.values() if r not in by_name and same_company(name, r.get("name"))]
        sure = {r["hs_object_id"]: r for r in by_domain + by_name}
        if len(sure) == 1:
            matches[name] = {"id": next(iter(sure)), "how": "domain" if by_domain else "name"}
        elif len(sure) > 1 or similar:
            cands = list(sure.values()) or similar
            ask.append((name, cands[:6]))
            matches[name] = {"id": "", "how": "ask", "candidates": [x["hs_object_id"] for x in cands[:6]]}
        else:
            matches[name] = {"id": "", "how": "none"}
    filled = 0
    for name, m in matches.items():
        r = recs.get(m["id"]) if m["id"] else None
        for row in cos[name]["rows"]:
            if not r:
                continue
            row["HubSpot Company Record ID"] = m["id"]
            vals = {c["site"]: r.get("domain"), c["city"]: r.get("city"), c["state"]: r.get("state"),
                    c["country"]: r.get("country"), c["emp"]: r.get("numberofemployees"),
                    c["rev"]: r.get("annualrevenue")}
            for col, v in vals.items():
                if v:
                    row[col] = str(v).split(".")[0] if col in (c["emp"], c["rev"]) else str(v)
            row[c["src"]] = "HubSpot"
        if r:
            filled += 1
        missing = [k for k in ("site", "city", "state", "country") if not cos[name]["rows"][0].get(c[k])]
        if not r or missing:
            research.append((name, missing if r else ["everything"]))
    save(p, fields, rows)
    (d / "matches.json").write_text(json.dumps(matches, indent=1))
    portal = json.loads((HERE.parent / "config.json").read_text()).get("hubspot_portal_id", "")
    hs = lambda i: f"https://app.hubspot.com/contacts/{portal}/record/0-2/{i}"
    print(f"HubSpot: {filled} of {len(cos)} companies filled from HubSpot; {len(ask)} to confirm with the user; "
          f"{len([n for n, m in matches.items() if m['how'] == 'none'])} not in HubSpot")
    for name, cands in ask:
        print(f"ASK {name}: " + " | ".join(f"{x['hs_object_id']}: {x.get('name')} ({x.get('domain') or 'no domain'}, "
                                           f"{x.get('city') or '?'}, {x.get('country') or '?'}) {hs(x['hs_object_id'])}"
                                           for x in cands))
    if ask:
        print("Ask the user per ASK line (which record, or none); write {\"<company>\": \"<id>|none\"} and re-run "
              "apply --decisions <file>.")
    print(f"web research still needed for {len(research)} companies" +
          (": " + "; ".join(f"{n} ({', '.join(m)})" for n, m in research[:40]) if research else ""))
    if any(m["how"] == "none" for m in matches.values()) and not (d / "plan_2.json").exists():
        print("tip: run plan --pass 2 first to catch HubSpot names that differ slightly from the list's.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--run-dir", required=True)
    p.add_argument("--kind", choices=["companies", "event"], required=True)
    p.add_argument("--pass", dest="pass_", type=int, default=1, choices=[1, 2]); p.set_defaults(func=plan)
    p = sub.add_parser("ingest"); p.add_argument("--run-dir", required=True)
    p.add_argument("--pass", dest="pass_", type=int, default=1, choices=[1, 2])
    p.add_argument("--batch", type=int, required=True); p.add_argument("--response", required=True)
    p.set_defaults(func=ingest)
    p = sub.add_parser("apply"); p.add_argument("--run-dir", required=True)
    p.add_argument("--kind", choices=["companies", "event"], required=True); p.add_argument("--decisions")
    p.set_defaults(func=apply)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
