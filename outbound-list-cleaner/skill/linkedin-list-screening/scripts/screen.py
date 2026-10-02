"""LinkedIn-sourced list screening: one screening file, verdicts, user decisions.

  init            Read the source file (LinkedIn / Sales Navigator / ZoomInfo
                  columns are recognised) into <run_dir>/screening.csv: the
                  original columns plus standard ones (Row ID, name, title,
                  company, countries) and empty verdict columns.
  check           Title fit (first pass from keywords + seniority, for Claude's
                  title-reviewer to confirm) and geography fit against the
                  countries the user chose — companies and contacts separately.
  apply-research  Write the company-researcher's findings (fit, reason, HQ
                  country) onto every row of each company.
  set-title       Write the title-reviewer's verdicts for given rows.
  summary         Counts per verdict, for the chat.
  apply-decisions Apply the code the user pasted from the flashcard review:
                  Decision = keep / exclude on each row (nothing is deleted).
"""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from location import parse_location  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
CONFIG = json.loads((HERE / "config.json").read_text())

ALIASES = {
    "first": ["First Name", "first_name", "firstName", "FirstName"],
    "last": ["Last Name", "last_name", "lastName", "LastName"],
    "full": ["Full Name", "Name", "full_name", "fullName"],
    "title": ["Job Title", "Title", "Current Title", "Current Job", "title", "jobTitle", "Position"],
    "company": ["Company Name", "Company", "Current Company", "company", "companyName", "Organization"],
    "website": ["Website", "Company Website", "Company Website URL", "Company Domain", "Domain", "companyWebsite"],
    "linkedin": ["LinkedIn Contact Profile URL", "Linkedin URL Public", "Profile URL", "LinkedIn URL", "Person Linkedin Url",
                 "linkedinUrl", "LinkedIn Profile", "profileUrl"],
    "contact_location": ["Location", "Person Location", "Geography", "location"],
    "contact_country": ["Country", "Person Country", "Contact Country"],
    "contact_state": ["Person State", "State"],
    "contact_city": ["Person City", "City"],
    "company_country": ["Company Country", "Company HQ Country", "HQ Country"],
    "company_location": ["Company Location", "Company HQ", "Company Headquarters", "companyLocation"],
    "jobs": ["Current Jobs Number", "Current Jobs", "Number of Current Positions"],
    "headline": ["Profile Headline", "Headline", "headline"],
    "id": ["ZoomInfo Contact ID", "LinkedIn ID", "Profile ID", "Sales Navigator ID", "id"],
}
STD = ["Row ID", "Contact", "Title", "Company", "Current Jobs", "Jobs Check", "Contact City", "Contact State", "Contact Country", "Location Note",
       "Company Country", "Company Presence",
       "Title Fit", "Title Reason", "Company Fit", "Company Reason", "Geo Fit", "Geo Reason",
       "Recommendation", "Decision"]

COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States", "u.s.": "United States", "united states": "United States",
    "united states of america": "United States", "america": "United States",
    "canada": "Canada",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "united kingdom": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom", "gb": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    "ireland": "Ireland", "republic of ireland": "Ireland", "ie": "Ireland",
    "mexico": "Mexico", "méxico": "Mexico", "germany": "Germany", "deutschland": "Germany",
    "france": "France", "netherlands": "Netherlands", "switzerland": "Switzerland", "japan": "Japan",
    "china": "China", "india": "India", "australia": "Australia",
}
# More countries, so whatever the user types (any case) can be matched.
for _c in ("Argentina", "Austria", "Bangladesh", "Belgium", "Brazil", "Bulgaria", "Chile", "Colombia",
           "Costa Rica", "Croatia", "Czech Republic", "Denmark", "Dominican Republic", "Egypt", "Estonia",
           "Finland", "Greece", "Guatemala", "Hong Kong", "Hungary", "Indonesia", "Israel", "Italy",
           "Kenya", "Latvia", "Lithuania", "Luxembourg", "Malaysia", "Morocco", "New Zealand", "Nigeria",
           "Norway", "Pakistan", "Peru", "Philippines", "Poland", "Portugal", "Puerto Rico", "Romania",
           "Saudi Arabia", "Serbia", "Singapore", "Slovakia", "Slovenia", "South Africa", "South Korea",
           "Spain", "Sri Lanka", "Sweden", "Taiwan", "Thailand", "Turkey", "Ukraine",
           "United Arab Emirates", "Uruguay", "Vietnam"):
    COUNTRY_ALIASES.setdefault(_c.lower(), _c)
COUNTRY_ALIASES.update({"uae": "United Arab Emirates", "korea": "South Korea", "czechia": "Czech Republic",
                        "türkiye": "Turkey", "holland": "Netherlands", "the netherlands": "Netherlands",
                        "españa": "Spain", "italia": "Italy", "brasil": "Brazil"})
# Typed by a user these could mean two places: always ask.
AMBIGUOUS = {"ca": ["Canada", "United States (California)"], "georgia": ["Georgia (the country)", "United States (Georgia)"]}
US_STATES = {"alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
             "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
             "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
             "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
             "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
             "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
             "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia"}
CA_PROVINCES = {"alberta", "british columbia", "manitoba", "new brunswick", "newfoundland and labrador",
                "nova scotia", "ontario", "prince edward island", "quebec", "québec", "saskatchewan"}
US_STATE_CODES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
                     "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
CA_PROVINCE_CODES = set("AB BC MB NB NL NS ON PE QC SK".split())


def pick(row, key):
    for name in ALIASES[key]:
        if row.get(name):
            return row[name].strip()
    return ""


def country_of(*texts):
    """Country from a country field or a location like 'Austin, Texas, United States'."""
    for text in texts:
        if not text:
            continue
        raw = [p.strip() for p in re.split(r"[,/|]", text) if p.strip()]
        parts = [p.lower() for p in raw]
        for q, p in zip(reversed(raw), reversed(parts)):
            if q in US_STATE_CODES:      # "Austin, TX" (CA here = California)
                return "United States"
            if q in CA_PROVINCE_CODES:
                return "Canada"
            if p in COUNTRY_ALIASES:
                return COUNTRY_ALIASES[p]
            if p in US_STATES:
                return "United States"
            if p in CA_PROVINCES:
                return "Canada"
        for p in reversed(parts):
            for alias, country in COUNTRY_ALIASES.items():
                if len(alias) > 3 and alias in p:
                    return country
    return ""


def path(run_dir):
    return Path(run_dir) / "screening.csv"


def load(run_dir):
    with open(path(run_dir), newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def save(run_dir, fields, rows):
    tmp = path(run_dir).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path(run_dir))


def read_table(path):
    """CSV or Excel (first sheet) -> (headers, rows as dicts of strings)."""
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        fields = [str(h).strip() if h is not None else f"Column {i}" for i, h in enumerate(next(it), 1)]
        rows = [{f: "" if v is None else str(v).strip() for f, v in zip(fields, r)} for r in it if any(r)]
        return fields, rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames), list(reader)


def init(args):
    fields, rows = read_table(args.input)
    found = {k: next((n for n in v if n in fields), None) for k, v in ALIASES.items()}
    missing = [k for k in ("title", "company") if not found[k]] + ([] if found["first"] or found["full"] else ["name"])
    if missing:
        raise SystemExit(f"couldn't find columns for: {', '.join(missing)}. Columns are: {fields}. "
                         "Ask the user which column holds each.")
    for i, r in enumerate(rows, 1):
        name = pick(r, "full") or f"{pick(r, 'first')} {pick(r, 'last')}".strip()
        r.update({"Row ID": pick(r, "id") or f"R{i:04d}", "Contact": name, "Title": pick(r, "title"),
                  "Company": pick(r, "company"),
                  "Current Jobs": pick(r, "jobs"), "Jobs Check": "",
                  **(contact_location(r) if not args.event else
                     {"Contact City": "", "Contact State": "", "Contact Country": "", "Location Note": ""}),
                  "Company Country": country_of(pick(r, "company_country"), pick(r, "company_location"))})
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fields = [c for c in STD if c not in fields] + fields
    save(out, fields, rows)
    print(f"screening.csv: {len(rows)} contacts at {len({r['Company'] for r in rows})} companies. "
          f"Columns used: " + ", ".join(f"{k}={v}" for k, v in found.items() if v))
    if args.event:
        print("event list: no multiple-jobs check and no contact location (companies are screened instead; "
              "run check with --skip-contact-geo)")
        return
    multi = sum(1 for r in rows if (r["Current Jobs"] or "1").isdigit() and int(r["Current Jobs"] or 1) > 1)
    print(f"{multi} contacts have more than one current job (next: jobs.py build)" if found["jobs"] else
          "no current-jobs column in this file: ask the user whether to check for people with several jobs")
    unknown = sum(1 for r in rows if r["Location Note"] or not r["Contact Country"])
    metro = sum(1 for r in rows if r["Contact State"] and not r["Contact City"])
    print(f"locations: {len(rows) - unknown} placed ({metro} with state and country but no city); "
          f"{unknown} uncertain (see Location Note; resolve with set-location)")


def contact_location(r):
    """Contact City / State / Country: separate columns win (ZoomInfo-style files); otherwise the
    LinkedIn location is split, filling only what's certain (a metro area gives no city)."""
    loc = parse_location(pick(r, "contact_location"), COUNTRY_ALIASES)
    city, state = pick(r, "contact_city") or loc["city"], pick(r, "contact_state") or loc["state"]
    country = country_of(pick(r, "contact_country")) or loc["country"] or country_of(state)
    note = "" if (pick(r, "contact_country") or loc["certain"]) else loc["note"]
    return {"Contact City": city, "Contact State": state, "Contact Country": country, "Location Note": note}


def set_location(args):
    """locations.json: {"<Row ID>": {"city": "", "state": "", "country": ""}} — for locations the
    parser couldn't place (Claude resolves them, asking the user when unsure; never guess a city)."""
    fields, rows = load(args.run_dir)
    fixes = json.loads(Path(args.file).read_text())
    by_id = {r["Row ID"]: r for r in rows}
    for rid, f in fixes.items():
        r = by_id[rid]
        r["Contact City"], r["Contact State"] = f.get("city", ""), f.get("state", "")
        r["Contact Country"] = country_of(f.get("country", "")) or f.get("country", "")
        r["Location Note"] = ""
    save(args.run_dir, fields, rows)
    left = sum(1 for r in rows if r.get("Location Note"))
    print(f"locations set for {len(fixes)} contacts; {left} still uncertain")


def title_fit(title):
    t = (title or "").lower()
    if not t:
        return "unclear", "no title"
    word = lambda k: re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t)
    bad = [k for k in CONFIG["exclude_title_keywords"] if word(k)]
    if bad:
        return "no", f"excluded title ({bad[0]})"
    area = [k for k in CONFIG["target_title_keywords"] if word(k)]
    senior = [k for k in CONFIG["min_seniority_keywords"] if word(k)]
    if area and senior:
        return "fit", f"{area[0]} · {senior[0]}"
    if area:
        return "unclear", f"{area[0]}, seniority unclear"
    if senior:
        return "unclear", f"{senior[0]}, function outside the target areas"
    return "no", "function and seniority outside the targets"


def canonical_countries(values):
    """User-typed countries -> canonical names, any case or common variant
    ("united states", "USA", "scotland" -> United Kingdom). Anything unknown
    stops with suggestions, so Claude checks with the user instead of guessing."""
    import difflib
    known = sorted(set(COUNTRY_ALIASES.values()))
    out, unknown = [], []
    for v in values:
        low = v.strip().lower()
        if low in AMBIGUOUS:
            unknown.append(f"{v!r} (could be {' or '.join(AMBIGUOUS[low])})")
            continue
        if low in US_STATES or low in CA_PROVINCES or v.strip() in US_STATE_CODES | CA_PROVINCE_CODES:
            unknown.append(f"{v!r} (a state/province, not a country — did they mean "
                           f"{'Canada' if low in CA_PROVINCES or v.strip() in CA_PROVINCE_CODES else 'United States'}?)")
            continue
        c = country_of(v) or next((k for k in known if k.lower() == v.strip().lower()), "")
        if c:
            out.append(c)
        else:
            close = difflib.get_close_matches(v.strip().title(), known, n=3, cutoff=0.6)
            unknown.append(f"{v!r}" + (f" (did you mean {', '.join(close)}?)" if close else ""))
    if unknown:
        raise SystemExit("not sure which country is meant: " + "; ".join(unknown) + " — ask the user")
    return sorted(set(out))


def presence_of(row):
    """Countries the company is based in or present in."""
    return {c.strip() for c in (row.get("Company Presence") or "").split(";") if c.strip()} | ({row["Company Country"]} - {""})


def check(args):
    fields, rows = load(args.run_dir)
    companies = canonical_countries(args.company_countries) if args.company_countries else CONFIG["default_company_countries"]
    contacts = canonical_countries(args.contact_countries) if args.contact_countries else CONFIG["default_contact_countries"]
    for r in rows:
        if not r.get("Title Fit"):
            r["Title Fit"], r["Title Reason"] = title_fit(r["Title"])
        cc, pc = r["Company Country"], r["Contact Country"]
        problems = []
        presence = presence_of(r)
        if not presence:
            problems.append("company country unknown")
        elif not presence & set(companies):
            problems.append(f"company in {cc or ', '.join(sorted(presence))}, no presence in the target countries")
        if args.skip_contact_geo:
            pass  # event lists: attendees' own location isn't known; companies are screened instead
        elif not pc:
            problems.append("contact country unknown")
        elif pc not in contacts:
            problems.append(f"contact in {pc}")
        if not problems:
            r["Geo Fit"], r["Geo Reason"] = "fit", (f"company {cc}" if args.skip_contact_geo
                                                    else f"company {cc}, contact {pc}")
        elif any("unknown" in p for p in problems) and not any(" in " in p for p in problems):
            r["Geo Fit"], r["Geo Reason"] = "unclear", "; ".join(problems)
        else:
            r["Geo Fit"], r["Geo Reason"] = "no", "; ".join(problems)
        recommend(r)
    save(args.run_dir, fields, rows)
    (Path(args.run_dir) / "geo_settings.json").write_text(json.dumps(
        {"company_countries": companies, "contact_countries": contacts}, indent=2))
    summary(args)


def recommend(r):
    verdicts = [r.get("Title Fit"), r.get("Company Fit") or "unclear", r.get("Geo Fit")]
    if "no" in verdicts:
        r["Recommendation"] = "exclude"
    elif all(v == "fit" for v in verdicts):
        r["Recommendation"] = "keep"
    else:
        r["Recommendation"] = "review"


def apply_research(args):
    """research.json: {"<company name>": {"fit": "fit|unclear|no", "reason": "...", "hq_country": "...",
    "presence": ["<every country it has offices, plants or warehouses in>"]}}"""
    fields, rows = load(args.run_dir)
    if "Company Presence" not in fields:
        fields.insert(fields.index("Company Country") + 1, "Company Presence")
    research = json.loads(Path(args.file).read_text())
    hit = 0
    for r in rows:
        f = research.get(r["Company"])
        if not f:
            continue
        hit += 1
        r["Company Fit"], r["Company Reason"] = f["fit"], f.get("reason", "")
        if f.get("hq_country") and not r["Company Country"]:
            r["Company Country"] = country_of(f["hq_country"]) or f["hq_country"]
        presence = {country_of(c) or c for c in f.get("presence", [])} | ({r["Company Country"]} - {""})
        r["Company Presence"] = "; ".join(sorted(presence))
        recommend(r)
    save(args.run_dir, fields, rows)
    missing = sorted({r["Company"] for r in rows if not r.get("Company Fit")})
    print(f"company research applied to {hit} rows; companies still unresearched: {len(missing)}")


def set_title(args):
    """reviews.json: {"<Row ID>": {"fit": "fit|unclear|no", "reason": "..."}}"""
    fields, rows = load(args.run_dir)
    reviews = json.loads(Path(args.file).read_text())
    for r in rows:
        if r["Row ID"] in reviews:
            r["Title Fit"], r["Title Reason"] = reviews[r["Row ID"]]["fit"], reviews[r["Row ID"]].get("reason", "")
            recommend(r)
    save(args.run_dir, fields, rows)
    print(f"title verdicts updated for {sum(1 for r in rows if r['Row ID'] in reviews)} rows")


def summary(args):
    _, rows = load(args.run_dir)
    for col in ("Title Fit", "Company Fit", "Geo Fit", "Recommendation", "Decision"):
        print(f"{col}: {dict(Counter(r.get(col) or '—' for r in rows))}")


RULE_SCOPE = {"c": "company", "p": "contact", "b": "company and contact"}


def parse_rules(text):
    """'+b:United States|-c:Germany' -> [{"mode": "include", "scope": "b", "country": "United States"}, ...]"""
    out = []
    for part in filter(None, (text or "").split("|")):
        mode, scope, country = part[0], part[1], part[3:]
        out.append({"mode": "include" if mode == "+" else "exclude", "scope": scope, "country": country})
    return out


def rule_hit(row, rules):
    """The country rule that excludes this row, if any (same logic as the review page).
    Company rules: "include only" keeps companies based in OR present in a country;
    "exclude" drops companies based in it. Contact rules use the contact's country."""
    hq, contact, presence = row["Company Country"], row["Contact Country"], presence_of(row)
    for r in rules:
        if r["mode"] == "exclude" and r["scope"] in ("c", "b") and hq == r["country"]:
            return f"company rule: exclude companies based in {r['country']}"
        if r["mode"] == "exclude" and r["scope"] in ("p", "b") and contact == r["country"]:
            return f"contact rule: exclude contacts in {r['country']}"
    inc = [r["country"] for r in rules if r["mode"] == "include" and r["scope"] in ("c", "b")]
    if inc and presence and not presence & set(inc):
        return f"company rule: not based or present in {', '.join(inc)}"
    inc = [r["country"] for r in rules if r["mode"] == "include" and r["scope"] in ("p", "b")]
    if inc and contact and contact not in inc:
        return f"contact rule: contact not in {', '.join(inc)}"
    return ""


def apply_decisions(args):
    """Code from the review page: 'LS1;<n cards>;X:<numbers>;K:<numbers>[;CX:<company numbers>][;R:<rules>]'.
    Without --confirm it only previews: writes decisions_pending.json and prints every
    change. With --confirm (after the user approves) it writes the pending decisions
    into screening.csv."""
    run = Path(args.run_dir)
    fields, rows = load(args.run_dir)
    pending_path = run / "decisions_pending.json"
    if args.confirm:
        if not pending_path.exists():
            raise SystemExit("nothing pending — paste the review code first (apply-decisions --code …)")
        pending = json.loads(pending_path.read_text())
        for col in ("Decision", "Decision Note"):
            if col not in fields:
                fields.insert(fields.index("Decision") + 1 if col == "Decision Note" else len(fields), col)
        by_id = {r["Row ID"]: r for r in rows}
        for rid, d in pending["decisions"].items():
            by_id[rid]["Decision"], by_id[rid]["Decision Note"] = d["decision"], d["note"]
        save(args.run_dir, fields, rows)
        (run / "geo_rules.json").write_text(json.dumps(pending["rules"], indent=2))
        pending_path.rename(run / "decisions_applied.json")
        print(f"saved to screening.csv: {sum(d['decision'] == 'keep' for d in pending['decisions'].values())} keep, "
              f"{sum(d['decision'] == 'exclude' for d in pending['decisions'].values())} exclude")
        return summary(args)
    if not args.code:
        raise SystemExit("give --code (preview) or --confirm (after the user approves)")
    cards = json.loads((run / "cards.json").read_text())
    m = re.match(r"LS1;(\d+);X:([\d,\-]*);K:([\d,\-]*)(?:;CX:([\d,\-]*))?(?:;R:(.*))?$", args.code.strip())
    if not m or int(m.group(1)) != len(cards):
        raise SystemExit("that code doesn't match this review (wrong list or an old review) — ask the user to copy it again")
    def num(s):
        out = set()
        for part in filter(None, s.split(",")):
            a, _, b = part.partition("-")
            out |= set(range(int(a), int(b or a) + 1))
        return out
    exclude, keep = num(m.group(2)), num(m.group(3))
    rules = parse_rules(m.group(5))
    company_out = num(m.group(4) or "")
    by_id = {r["Row ID"]: r for r in rows}
    cos_path = run / "companies.json"
    companies = {co["n"]: co for co in json.loads(cos_path.read_text())} if cos_path.exists() else {}
    decisions, changes, open_ = {}, [], []
    for c in cards:
        r = by_id[c["row_id"]]
        rec = c.get("suggestion") or r["Recommendation"]
        d = "exclude" if c["n"] in exclude else "keep" if c["n"] in keep else ""
        if not d:
            open_.append(r)
            continue
        hit = rule_hit(r, rules)
        if c.get("company_n") in company_out and d == "exclude":
            note = f"company excluded ({hit})" if hit.startswith("company rule") else "company excluded by the reviewer"
        elif hit and d == "exclude":
            note = hit
        elif hit:
            note = f"reviewer kept, overriding {hit}"
        elif rec == "review":
            note = "reviewer (Claude left it to the user)"
        elif d != rec:
            note = "reviewer, against Claude's recommendation"
        else:
            note = "Claude's recommendation"
        decisions[r["Row ID"]] = {"decision": d, "note": note}
        if c.get("company_n") in company_out:
            continue  # reported once per company below
        if d != rec or hit or (r.get("Decision") and r["Decision"] != d):
            changes.append((r, rec, d, note))
    pending_path.write_text(json.dumps({"code": args.code.strip(), "rules": rules, "decisions": decisions}, indent=1))
    print(f"PREVIEW — nothing saved yet. {len(keep)} keep, {len(exclude)} exclude, {len(open_)} not answered")
    if rules:
        print("country rules: " + "; ".join(f"{r['mode']} {r['country']} ({RULE_SCOPE[r['scope']]})" for r in rules))
    if company_out:
        print(f"\nCompanies excluded ({len(company_out)}) — all their contacts are excluded:")
        print("Company | Based in | Also present in | Contacts | Claude suggested | Why")
        sample = {c["company_n"]: by_id[c["row_id"]] for c in cards}
        for n in sorted(company_out, key=lambda n: companies.get(n, {}).get("name", "").lower()):
            co, row = companies.get(n, {}), sample[n]
            hit = rule_hit(row, rules)
            why = hit if hit.startswith("company rule") else "reviewer"
            others = ", ".join(x for x in co.get("presence", []) if x != co.get("hq")) or "—"
            print(f"{co.get('name', row['Company'])} | {co.get('hq', '')} | {others} | {co.get('contacts', '')} | "
                  f"{co.get('suggestion', '')} | {why}")
    left = [co["name"] for n, co in companies.items() if n not in company_out and co["suggestion"] != "keep"]
    if left:
        print(f"\nCompanies kept that Claude had left to the user or suggested excluding ({len(left)}): {', '.join(sorted(left))}")
    print(f"\n{len(changes)} contacts (at kept companies) where the result differs from Claude's suggestion or came from a rule:")
    print("Company | Contact | Title | Claude suggested | Final | Why")
    for r, rec, d, note in sorted(changes, key=lambda x: (x[0]["Company"].lower(), x[0]["Contact"])):
        print(f"{r['Company']} | {r['Contact']} | {r['Title']} | {rec} | {d.upper()} | {note}")
    if open_:
        print(f"\nnot answered ({len(open_)}): " + ", ".join(f"{r['Contact']} ({r['Company']})" for r in open_))
    print("\nShow this to the user. After they approve: apply-decisions --run-dir … --confirm")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--input", required=True); p.add_argument("--out-dir", required=True)
    p.add_argument("--event", action="store_true", help="event list (from event-list-intake)")
    p.set_defaults(func=init)
    p = sub.add_parser("check"); p.add_argument("--run-dir", required=True)
    p.add_argument("--company-countries", nargs="*"); p.add_argument("--contact-countries", nargs="*")
    p.add_argument("--skip-contact-geo", action="store_true",
                   help="event lists: don't judge the contact's own country (it isn't known)")
    p.set_defaults(func=check)
    for name, func in (("apply-research", apply_research), ("set-title", set_title), ("set-location", set_location)):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True); p.add_argument("--file", required=True)
        p.set_defaults(func=func)
    p = sub.add_parser("summary"); p.add_argument("--run-dir", required=True); p.set_defaults(func=summary)
    p = sub.add_parser("apply-decisions"); p.add_argument("--run-dir", required=True); p.add_argument("--code")
    p.add_argument("--confirm", action="store_true", help="write the previewed decisions into screening.csv")
    p.set_defaults(func=apply_decisions)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
