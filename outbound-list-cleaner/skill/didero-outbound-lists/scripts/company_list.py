"""Company-only event lists (exhibitors, sponsors — no contact names).

One file per run: <run_dir>/companies.csv (one row per company), plus
<run_dir>/targets.csv when the source names job titles at a company (one row
per company + title; no person names).

  init      --input <file> [...] --event "<event>" --out-dir <run_dir>
            Reads the list (CSV / Excel). Company, plus website / city / state /
            country / employees / revenue / job title when present.
  add       --run-dir <run_dir> --file companies.json --source "<screenshot/page>"
            Companies (and titles) read off screenshots / pages:
            [{"company": "", "website": "", "title": ""}] — merged, blanks only.
  plan      --run-dir <run_dir>  companies_todo.json: every company to research
            (website, city, state, country; employees / revenue if published).
            Values already in the list are re-checked, not trusted.
  apply     --run-dir <run_dir> --file found.json
            {"<company>": {"website", "city", "state", "country", "employees",
             "revenue", "source", "confidence"}} — research wins over the list's
             own values; every value it changes is listed.
  filter    --run-dir <run_dir> [--countries <...>]  Excludes companies whose HQ
            country isn't a target (default: config target_countries; any case /
            common spelling). Preview first; --confirm writes it. Unknown
            countries are never excluded silently — they're listed to ask about.
  clean     --run-dir <run_dir>  Company names: same rules as the LinkedIn
            title/company cleaning (legal suffixes, symbols; judgment calls
            listed). --decisions <json> {"<before>": "<after>"} applies them.
  zoominfo  --run-dir <run_dir> --out <file.csv>  Branch A upload file: Company
            Name, Company Website, Company City, Company State, Company Country,
            Number of Employees, Annual Revenue (kept companies only).
  guide     --run-dir <run_dir> [--title "<event>"] [--filters <json>]  Branch A:
            zoominfo_guide.html, the step-by-step page shown next to ZoomInfo.
            Filters: config.json defaults, changed by the user for this run.
  tag-event --run-dir <run_dir> --working <working-file run_dir>  Branch A:
            after the ZoomInfo export is loaded, write Event Name on every
            contact whose company is on this event's list.
"""
import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIBLING = HERE  # all scripts live in one folder
CONFIG = json.loads((HERE.parent / "config.json").read_text())
COMPANY_COLS = ["Company ID", "Company", "Website", "City", "State", "Country", "Employees", "Revenue",
                "Status", "Status Note", "Event Name", "Source", "Research Source", "Confidence"]
TARGET_COLS = ["Target ID", "Company ID", "Company", "Job Title", "Status", "Note"]
ALIASES = {
    "Company": ["company", "company name", "organization", "organisation", "exhibitor", "exhibitor name",
                "sponsor", "sponsor name", "account", "account name", "name"],
    "Website": ["website", "company website", "url", "web", "domain", "company url", "web site"],
    "City": ["city", "company city", "hq city"],
    "State": ["state", "province", "state/province", "company state", "region"],
    "Country": ["country", "company country", "hq country"],
    "Employees": ["employees", "number of employees", "employee count", "headcount", "company size", "size"],
    "Revenue": ["revenue", "annual revenue", "sales", "company revenue"],
    "Job Title": ["job title", "title", "titles", "position", "role", "contact title"],
}


def p_companies(run):
    return Path(run) / "companies.csv"


def p_targets(run):
    return Path(run) / "targets.csv"


def read_csv(p, cols):
    if not Path(p).exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(p, cols, rows):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(p).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(p)


def read_table(p):
    if str(p).lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        ws = openpyxl.load_workbook(p, read_only=True, data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        fields = [str(h).strip() if h is not None else f"Column {i}" for i, h in enumerate(next(it), 1)]
        return fields, [{f: "" if v is None else str(v).strip() for f, v in zip(fields, r)} for r in it if any(r)]
    with open(p, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), [{k: (v or "").strip() for k, v in row.items()} for row in r]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def upsert(companies, targets, rec, event, source):
    """Merge one company (+ optional titles) in; blanks filled only."""
    k = norm(rec.get("Company"))
    if not k:
        return
    co = next((c for c in companies if norm(c["Company"]) == k), None)
    if not co:
        co = {c: "" for c in COMPANY_COLS}
        co.update({"Company ID": f"C{len(companies) + 1:04d}", "Company": rec["Company"].strip(),
                   "Event Name": event, "Source": source})
        companies.append(co)
    elif source and source not in co["Source"]:
        co["Source"] = (co["Source"] + "; " if co["Source"] else "") + source
    for c in ("Website", "City", "State", "Country", "Employees", "Revenue"):
        if not co.get(c) and rec.get(c):
            co[c] = rec[c].strip()
    for t in re.split(r"\s*[;\n]\s*", rec.get("Job Title") or ""):
        if t and not any(x["Company ID"] == co["Company ID"] and norm(x["Job Title"]) == norm(t) for x in targets):
            targets.append({"Target ID": f"T{len(targets) + 1:04d}", "Company ID": co["Company ID"],
                            "Company": co["Company"], "Job Title": t.strip(), "Status": "", "Note": ""})


def init(args):
    companies, targets = read_csv(p_companies(args.out_dir), COMPANY_COLS), read_csv(p_targets(args.out_dir), TARGET_COLS)
    for f in args.input:
        fields, data = read_table(f)
        low = {h.lower().strip(): h for h in fields}
        found = {k: next((low[a] for a in v if a in low), None) for k, v in ALIASES.items()}
        if not found["Company"]:
            raise SystemExit(f"{Path(f).name}: no company column found. Columns: {fields}. Ask the user which one.")
        for d in data:
            upsert(companies, targets, {k: d.get(v, "") for k, v in found.items() if v}, args.event, Path(f).name)
        print(f"{Path(f).name}: columns used " + ", ".join(f"{k}={v}" for k, v in found.items() if v))
    write_csv(p_companies(args.out_dir), COMPANY_COLS, companies)
    write_csv(p_targets(args.out_dir), TARGET_COLS, targets)
    summary(args.out_dir)


def add(args):
    companies, targets = read_csv(p_companies(args.run_dir), COMPANY_COLS), read_csv(p_targets(args.run_dir), TARGET_COLS)
    event = companies[0]["Event Name"] if companies else ""
    for x in json.loads(Path(args.file).read_text()):
        upsert(companies, targets, {"Company": x.get("company", ""), "Website": x.get("website", ""),
                                    "Job Title": x.get("title", "")}, event, args.source)
    write_csv(p_companies(args.run_dir), COMPANY_COLS, companies)
    write_csv(p_targets(args.run_dir), TARGET_COLS, targets)
    summary(args.run_dir)


def summary(run):
    companies, targets = read_csv(p_companies(run), COMPANY_COLS), read_csv(p_targets(run), TARGET_COLS)
    live = [c for c in companies if c["Status"] != "excluded"]
    with_t = {t["Company ID"] for t in targets}
    print(f"companies.csv: {len(companies)} companies ({len(companies) - len(live)} excluded); "
          f"{len(targets)} job titles at {len(with_t)} companies -> "
          f"branch B (titles) for {len([c for c in live if c['Company ID'] in with_t])}, "
          f"branch A (ZoomInfo list build) for {len([c for c in live if c['Company ID'] not in with_t])}")


def plan(args):
    companies = read_csv(p_companies(args.run_dir), COMPANY_COLS)
    todo = [{"company": c["Company"],
             "in_the_list": {k: c[k] for k in ("Website", "City", "State", "Country", "Employees", "Revenue") if c[k]}}
            for c in companies if c["Status"] != "excluded"]
    (Path(args.run_dir) / "companies_todo.json").write_text(json.dumps(todo, indent=1, ensure_ascii=False))
    print(f"{len(todo)} companies to research -> companies_todo.json (website, then city/state/country; "
          "employees and revenue if published). Re-check what the list already says.")


def clean_site(url):
    host = re.sub(r"^[a-z]+://", "", (url or "").strip(), flags=re.I).split("/")[0].split("?")[0].lower().strip(".")
    bare = host[4:] if host.startswith("www.") else host
    bad = ("linkedin.com", "facebook.com", "linktr.ee", "bit.ly", "instagram.com", "twitter.com", "x.com",
           "youtube.com", "greenhouse.io", "lever.co", "indeed.com", "glassdoor.com")
    if not host or "." not in host or any(bare == d or bare.endswith("." + d) for d in bad):
        return ""
    return re.sub(r"^(careers?|jobs)\.", "www.", host)


def apply(args):
    companies = read_csv(p_companies(args.run_dir), COMPANY_COLS)
    found = json.loads(Path(args.file).read_text())
    by = {norm(c["Company"]): c for c in companies}
    low, unknown, changed = [], [], []
    for name, f in found.items():
        c = by.get(norm(name))
        if not c:
            unknown.append(name)
            continue
        new = {"Website": clean_site(f.get("website", "")), "City": f.get("city"), "State": f.get("state"),
               "Country": canonical(f["country"]) if f.get("country") else "", "Employees": f.get("employees"),
               "Revenue": f.get("revenue")}
        same = lambda a, b, col: (re.sub(r"^www\.", "", a.lower()) == re.sub(r"^www\.", "", b.lower()) if col == "Website"
                                  else (canonical(a) == canonical(b) if col == "Country" and a and b else a == b))
        for col, v in new.items():
            v = str(v).strip() if v not in (None, "") else ""
            if v and v != c[col] and same(v, c[col], col):
                c[col] = v  # only formatting differs
            elif v and v != c[col]:
                if c[col]:
                    changed.append(f"{c['Company']} {col}: {c[col]} -> {v}")
                c[col] = v
        c["Research Source"], c["Confidence"] = f.get("source", ""), f.get("confidence", "")
        if f.get("confidence") == "low":
            low.append(f"{c['Company']}: {c['Website'] or '(no site)'} — {c['City']}, {c['State']}, {c['Country']}")
    write_csv(p_companies(args.run_dir), COMPANY_COLS, companies)
    left = [c["Company"] for c in companies if c["Status"] != "excluded" and not (c["Website"] and c["Country"])]
    print(f"research applied to {len(found) - len(unknown)} companies; {len(left)} still missing a website or country")
    if changed:
        print("the list said something else — research used:\n  " + "\n  ".join(changed))
    if low:
        print("low confidence — confirm with the user:\n  " + "\n  ".join(low))
    if unknown:
        print("not in companies.csv (check spelling): " + ", ".join(unknown))


def canonical(c):
    sys.path.insert(0, str(SIBLING))
    from screen import country_of  # same country matching as the review page
    return country_of(c) or c


def filter_(args):
    run = Path(args.run_dir)
    companies = read_csv(p_companies(run), COMPANY_COLS)
    sys.path.insert(0, str(SIBLING))
    from screen import canonical_countries
    targets = canonical_countries(args.countries) if args.countries else CONFIG["target_countries"]
    out, unknown = [], []
    for c in companies:
        if c["Status"] == "excluded":
            continue
        cc = canonical(c["Country"]) if c["Country"] else ""
        if not cc:
            unknown.append(c["Company"])
        elif cc not in targets:
            out.append((c, cc))
    print(f"target countries: {', '.join(targets)}")
    print(f"{'EXCLUDED' if args.confirm else 'would exclude'} {len(out)}: " +
          (", ".join(f"{c['Company']} ({cc})" for c, cc in out) or "none"))
    if unknown:
        print(f"country unknown — ask the user / research more ({len(unknown)}): " + ", ".join(unknown))
    if args.confirm:
        for c, cc in out:
            c["Status"], c["Status Note"] = "excluded", f"HQ in {cc}"
        write_csv(p_companies(run), COMPANY_COLS, companies)
        summary(run)
    else:
        print("Show this to the user; after their OK: filter … --confirm")


def clean(args):
    run = Path(args.run_dir)
    companies = read_csv(p_companies(run), COMPANY_COLS)
    targets = read_csv(p_targets(run), TARGET_COLS)
    if args.decisions:
        dec = json.loads(Path(args.decisions).read_text())
        n = 0
        for c in companies:
            if c["Company"] in dec and dec[c["Company"]] != c["Company"]:
                new = dec[c["Company"]]
                for t in targets:
                    if t["Company ID"] == c["Company ID"]:
                        t["Company"] = new
                c["Company"], n = new, n + 1
        write_csv(p_companies(run), COMPANY_COLS, companies)
        write_csv(p_targets(run), TARGET_COLS, targets)
        print(f"{n} company names changed")
        return
    sys.path.insert(0, str(SIBLING))
    from fields import clean_company  # the same rules as the LinkedIn title/company cleaning
    review = []
    for c in companies:
        if c["Status"] == "excluded":
            continue
        after, judge, why = clean_company(c["Company"])
        if after != c["Company"] or judge:
            review.append({"before": c["Company"], "after": after, "auto": not judge, "why": why})
    (run / "names_review.json").write_text(json.dumps(review, indent=1, ensure_ascii=False))
    print(f"{sum(r['auto'] for r in review)} safe fixes, {sum(not r['auto'] for r in review)} to judge "
          "-> names_review.json; write {\"<before>\": \"<after>\"} and run clean --decisions <file>")


def number(v, kind):
    """HubSpot's number format: '1,200' -> '1200'; '$250M' -> '250000000'. A range
    ('1,001-5,000', '$10M-$50M') stays as written (only the ZoomInfo upload takes it)."""
    s = (v or "").strip()
    m = re.fullmatch(r"\$?\s*([\d.,]+)\s*([kKmMbB]|thousand|million|billion|mil\.?|bil\.?)?\s*(usd)?", s, re.I)
    if not m:
        return s
    n = float(m.group(1).replace(",", ""))
    mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "mil": 1e6, "mil.": 1e6,
            "b": 1e9, "billion": 1e9, "bil": 1e9, "bil.": 1e9}.get((m.group(2) or "").lower(), 1)
    return str(int(round(n * mult)))


def set_(args):
    """The user's answer for one company: --field "Country=Canada" … or --exclude "<reason>"."""
    companies = read_csv(p_companies(args.run_dir), COMPANY_COLS)
    c = next((x for x in companies if norm(x["Company"]) == norm(args.company)), None)
    if not c:
        raise SystemExit(f"no company called {args.company!r}")
    before = dict(c)
    if args.exclude:
        c["Status"], c["Status Note"] = "excluded", args.exclude
    for kv in args.field or []:
        k, _, v = kv.partition("=")
        if k not in COMPANY_COLS:
            raise SystemExit(f"unknown field {k}; one of {COMPANY_COLS}")
        c[k] = canonical(v) if k == "Country" and v else (clean_site(v) if k == "Website" else v)
    write_csv(p_companies(args.run_dir), COMPANY_COLS, companies)
    print(" | ".join(f"{k}: {before[k]} -> {c[k]}" for k in COMPANY_COLS if before[k] != c[k]) or "no change")


def zoominfo(args):
    companies = [c for c in read_csv(p_companies(args.run_dir), COMPANY_COLS) if c["Status"] != "excluded"]
    unknown = [c["Company"] for c in companies if not c["Country"]]
    if unknown:
        raise SystemExit("country still unknown for: " + ", ".join(unknown) + " — ask the user, then "
                         "company_list.py set --company … --field \"Country=…\" (or --exclude \"reason\")")
    targets = read_csv(p_targets(args.run_dir), TARGET_COLS)
    if not args.all:
        with_t = {t["Company ID"] for t in targets}
        companies = [c for c in companies if c["Company ID"] not in with_t]
    cols = ["Company Name", "Company Website", "Company City", "Company State", "Company Country",
            "Number of Employees", "Annual Revenue"]
    rows = [{"Company Name": c["Company"], "Company Website": c["Website"], "Company City": c["City"],
             "Company State": c["State"], "Company Country": c["Country"],
             "Number of Employees": number(c["Employees"], "emp"), "Annual Revenue": number(c["Revenue"], "rev")}
            for c in companies]
    write_csv(args.out, cols, rows)
    missing = [r["Company Name"] for r in rows if not r["Company Website"]]
    print(f"{args.out}: {len(rows)} companies for the ZoomInfo upload"
          + (f"; no website for: {', '.join(missing)}" if missing else ""))


def tag_event(args):
    sys.path.insert(0, str(HERE))
    import worksheet as ws
    companies = [c for c in read_csv(p_companies(args.run_dir), COMPANY_COLS) if c["Status"] != "excluded"]
    names = {norm(c["Company"]): c["Event Name"] for c in companies}
    sites = {re.sub(r"^www\.", "", c["Website"].lower()): c["Event Name"] for c in companies if c["Website"]}
    fields, rows = ws.load(args.working)
    if "Event Name" not in fields:
        fields.append("Event Name")
    hit, miss = 0, set()
    for r in rows:
        site = re.sub(r"^(https?://)?(www\.)?", "", (r.get("Website") or "").lower()).split("/")[0]
        ev = names.get(norm(r.get("Company Name"))) or sites.get(site)
        if ev:
            r["Event Name"], hit = ev, hit + 1
        else:
            miss.add(r.get("Company Name", ""))
    ws.save(args.working, fields, rows)
    ws.log(args.working, {"action": "tag_event", "tagged": hit})
    print(f"Event Name set on {hit} of {len(rows)} contacts"
          + (f"; companies not matched to the event list (ask the user): {', '.join(sorted(miss))}" if miss else ""))


def guide(args):
    f = dict(CONFIG["zoominfo_filters"])
    if args.filters:
        f.update(json.loads(Path(args.filters).read_text()))
    f.pop("_note", None)
    tpl = (HERE / "zoominfo_guide_template.html").read_text(encoding="utf-8")
    page = tpl.replace("__TITLE__", html.escape(args.title or "ZoomInfo list build")) \
              .replace("__FILTERS__", json.dumps(f, ensure_ascii=False)) \
              .replace("__FILE__", html.escape(args.upload or "zoominfo_upload.csv"))
    out = Path(args.run_dir) / "zoominfo_guide.html"
    out.write_text(page, encoding="utf-8")
    print(f"{out}: open it next to ZoomInfo")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--input", nargs="+", required=True); p.add_argument("--event", required=True)
    p.add_argument("--out-dir", required=True); p.set_defaults(func=init)
    p = sub.add_parser("add"); p.add_argument("--run-dir", required=True); p.add_argument("--file", required=True)
    p.add_argument("--source", required=True); p.set_defaults(func=add)
    p = sub.add_parser("plan"); p.add_argument("--run-dir", required=True); p.set_defaults(func=plan)
    p = sub.add_parser("apply"); p.add_argument("--run-dir", required=True); p.add_argument("--file", required=True)
    p.set_defaults(func=apply)
    p = sub.add_parser("filter"); p.add_argument("--run-dir", required=True); p.add_argument("--countries", nargs="*")
    p.add_argument("--confirm", action="store_true"); p.set_defaults(func=filter_)
    p = sub.add_parser("clean"); p.add_argument("--run-dir", required=True); p.add_argument("--decisions")
    p.set_defaults(func=clean)
    p = sub.add_parser("set"); p.add_argument("--run-dir", required=True); p.add_argument("--company", required=True)
    p.add_argument("--field", action="append"); p.add_argument("--exclude"); p.set_defaults(func=set_)
    p = sub.add_parser("zoominfo"); p.add_argument("--run-dir", required=True); p.add_argument("--out", required=True)
    p.add_argument("--all", action="store_true", help="include branch-B companies too")
    p.set_defaults(func=zoominfo)
    p = sub.add_parser("guide"); p.add_argument("--run-dir", required=True); p.add_argument("--title")
    p.add_argument("--upload", help="name of the upload file to show")
    p.add_argument("--filters", help="this run's filters (json), over the config defaults"); p.set_defaults(func=guide)
    p = sub.add_parser("tag-event"); p.add_argument("--run-dir", required=True); p.add_argument("--working", required=True)
    p.set_defaults(func=tag_event)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
