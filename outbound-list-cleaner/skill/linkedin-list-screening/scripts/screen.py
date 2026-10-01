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

HERE = Path(__file__).resolve().parent.parent
CONFIG = json.loads((HERE / "config.json").read_text())

ALIASES = {
    "first": ["First Name", "first_name", "firstName", "FirstName"],
    "last": ["Last Name", "last_name", "lastName", "LastName"],
    "full": ["Full Name", "Name", "full_name", "fullName"],
    "title": ["Job Title", "Title", "Current Title", "title", "jobTitle", "Position"],
    "company": ["Company Name", "Company", "Current Company", "company", "companyName", "Organization"],
    "website": ["Website", "Company Website", "Company Domain", "Domain", "companyWebsite"],
    "linkedin": ["LinkedIn Contact Profile URL", "Profile URL", "LinkedIn URL", "Person Linkedin Url",
                 "linkedinUrl", "LinkedIn Profile", "profileUrl"],
    "contact_location": ["Location", "Person Location", "Geography", "location"],
    "contact_country": ["Country", "Person Country", "Contact Country"],
    "contact_state": ["Person State", "State"],
    "company_country": ["Company Country", "Company HQ Country", "HQ Country"],
    "company_location": ["Company Location", "Company HQ", "Company Headquarters", "companyLocation"],
    "id": ["ZoomInfo Contact ID", "LinkedIn ID", "Profile ID", "Sales Navigator ID", "id"],
}
STD = ["Row ID", "Contact", "Title", "Company", "Contact Country", "Company Country",
       "Title Fit", "Title Reason", "Company Fit", "Company Reason", "Geo Fit", "Geo Reason",
       "Recommendation", "Decision"]

COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States", "u.s.": "United States", "united states": "United States",
    "united states of america": "United States", "america": "United States",
    "ca": "Canada", "canada": "Canada",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "united kingdom": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom", "gb": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    "ireland": "Ireland", "republic of ireland": "Ireland", "ie": "Ireland",
    "mexico": "Mexico", "méxico": "Mexico", "germany": "Germany", "deutschland": "Germany",
    "france": "France", "netherlands": "Netherlands", "switzerland": "Switzerland", "japan": "Japan",
    "china": "China", "india": "India", "australia": "Australia",
}
US_STATES = {"alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
             "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
             "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
             "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
             "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
             "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
             "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia"}
CA_PROVINCES = {"alberta", "british columbia", "manitoba", "new brunswick", "newfoundland and labrador",
                "nova scotia", "ontario", "prince edward island", "quebec", "québec", "saskatchewan"}


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
        parts = [p.strip().lower() for p in re.split(r"[,/|]", text) if p.strip()]
        for p in reversed(parts):
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


def init(args):
    with open(args.input, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields, rows = list(reader.fieldnames), list(reader)
    found = {k: next((n for n in v if n in fields), None) for k, v in ALIASES.items()}
    missing = [k for k in ("title", "company") if not found[k]] + ([] if found["first"] or found["full"] else ["name"])
    if missing:
        raise SystemExit(f"couldn't find columns for: {', '.join(missing)}. Columns are: {fields}. "
                         "Ask the user which column holds each.")
    for i, r in enumerate(rows, 1):
        name = pick(r, "full") or f"{pick(r, 'first')} {pick(r, 'last')}".strip()
        r.update({"Row ID": pick(r, "id") or f"R{i:04d}", "Contact": name, "Title": pick(r, "title"),
                  "Company": pick(r, "company"),
                  "Contact Country": country_of(pick(r, "contact_country"), pick(r, "contact_location"),
                                                pick(r, "contact_state")),
                  "Company Country": country_of(pick(r, "company_country"), pick(r, "company_location"))})
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fields = [c for c in STD if c not in fields] + fields
    save(out, fields, rows)
    print(f"screening.csv: {len(rows)} contacts at {len({r['Company'] for r in rows})} companies. "
          f"Columns used: " + ", ".join(f"{k}={v}" for k, v in found.items() if v))
    unknown = sum(1 for r in rows if not r["Contact Country"])
    if unknown:
        print(f"{unknown} contacts with no recognisable country (geo-checker will judge them)")


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


def check(args):
    fields, rows = load(args.run_dir)
    companies = args.company_countries or CONFIG["default_company_countries"]
    contacts = args.contact_countries or CONFIG["default_contact_countries"]
    for r in rows:
        if not r.get("Title Fit"):
            r["Title Fit"], r["Title Reason"] = title_fit(r["Title"])
        cc, pc = r["Company Country"], r["Contact Country"]
        problems = []
        if not cc:
            problems.append("company country unknown")
        elif cc not in companies:
            problems.append(f"company in {cc}")
        if not pc:
            problems.append("contact country unknown")
        elif pc not in contacts:
            problems.append(f"contact in {pc}")
        if not problems:
            r["Geo Fit"], r["Geo Reason"] = "fit", f"company {cc}, contact {pc}"
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
    """research.json: {"<company name>": {"fit": "fit|unclear|no", "reason": "...", "hq_country": "..."}}"""
    fields, rows = load(args.run_dir)
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


def apply_decisions(args):
    """Code from the flashcards: 'LS1;<n cards>;X:<card numbers>;K:<card numbers>'."""
    fields, rows = load(args.run_dir)
    cards = json.loads((Path(args.run_dir) / "cards.json").read_text())
    m = re.match(r"LS1;(\d+);X:([\d,\-]*);K:([\d,\-]*)$", args.code.strip())
    if not m or int(m.group(1)) != len(cards):
        raise SystemExit("that code doesn't match this review (wrong list or an old review) — ask the user to copy it again")
    def num(s):
        out = set()
        for part in filter(None, s.split(",")):
            a, _, b = part.partition("-")
            out |= set(range(int(a), int(b or a) + 1))
        return out
    exclude, keep = num(m.group(2)), num(m.group(3))
    by_id = {r["Row ID"]: r for r in rows}
    for c in cards:
        r = by_id[c["row_id"]]
        if c["n"] in exclude:
            r["Decision"] = "exclude"
        elif c["n"] in keep:
            r["Decision"] = "keep"
    save(args.run_dir, fields, rows)
    print(f"decisions applied: {len(keep)} keep, {len(exclude)} exclude, "
          f"{len(cards) - len(keep) - len(exclude)} not decided")
    summary(args)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--input", required=True); p.add_argument("--out-dir", required=True)
    p.set_defaults(func=init)
    p = sub.add_parser("check"); p.add_argument("--run-dir", required=True)
    p.add_argument("--company-countries", nargs="*"); p.add_argument("--contact-countries", nargs="*")
    p.set_defaults(func=check)
    for name, func in (("apply-research", apply_research), ("set-title", set_title)):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True); p.add_argument("--file", required=True)
        p.set_defaults(func=func)
    p = sub.add_parser("summary"); p.add_argument("--run-dir", required=True); p.set_defaults(func=summary)
    p = sub.add_parser("apply-decisions"); p.add_argument("--run-dir", required=True); p.add_argument("--code", required=True)
    p.set_defaults(func=apply_decisions)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
