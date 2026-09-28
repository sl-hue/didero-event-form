"""Step 2 — normalization.

Runs on step 1's output and produces the upload-ready contact and company
files. Two stages, with Claude (the skill) in between:

  prepare  Normalize names, check LinkedIn slugs against names, and write
           review_step2.json: LinkedIn URLs whose slug doesn't contain the
           contact's first and last name (for Claude to judge), plus name
           changes and website conflicts to report in chat.
  apply    Read decisions_step2.json and write contacts_upload.csv and
           companies_upload.csv. The files hold only upload columns — no notes
           or audit columns; everything to review is reported in chat from
           report_step2.json.

decisions_step2.json:
  {"linkedin": {"<ZoomInfo Contact ID>": {"action": "keep" | "blank" | "replace",
                                          "url": "<new URL, for replace>", "reason": "..."}},
   "email":    {"<ZoomInfo Contact ID>": {"action": "keep" | "clear", "reason": "..."}}}

  keep     plausible match, or the user chose to keep it
  blank    wrong person (Claude's call for clear cases, the user's otherwise)
  replace  the user supplied the correct URL
"""
import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path

CONTACT_ID = "ZoomInfo Contact ID"
COMPANY_ID = "ZoomInfo Company ID"
LINKEDIN = "LinkedIn Contact Profile URL"

CONTACT_COLUMNS = [
    CONTACT_ID, "First Name", "Last Name", "Job Title", "Management Level", "Job Function",
    "Department", "Direct Phone Number", "Email Address", "Email Domain", "Mobile phone",
    "ZoomInfo Contact Profile URL", LINKEDIN, "Person Street", "Person City", "Person State",
    "Person Zip Code", "Country", "Company Name", "Website", "Company HQ Phone",
]

COMPANY_COLUMNS = [
    COMPANY_ID, "Company Name", "Website", "Founded Year", "Company HQ Phone",
    "Revenue (in USD)", "Revenue Range (in USD)", "Employees", "Employee Range",
    "SIC Code 1", "SIC Code 2", "NAICS Code 1", "NAICS Code 2", "Primary Industry",
    "ZoomInfo Company Profile URL", "LinkedIn Company Profile URL",
    "Facebook Company Profile URL", "Twitter Company Profile URL", "Company City",
    "Company State", "Company Zip Code", "Company Country", "Full Address",
    "Company Domain", "Additional Domains",
]

# Professional credentials stripped from names. Generational suffixes
# (Jr, Sr, II, III) are part of the name and are kept.
CREDENTIALS = {
    "cpa", "pe", "mba", "phd", "jd", "esq", "cfa", "pmp", "cscp", "cpsm", "cpim", "cpm",
    "cltd", "cppm", "mcips", "cssbb", "cssgb", "leedap", "shrmcp", "shrmscp", "sphr", "phr",
    "cma", "cia", "cisa", "cissp", "cfe", "macc", "cem", "cmrp", "cpcm", "cfpim", "csp",
}
GENERATIONAL = {"jr", "sr", "ii", "iii", "iv", "v"}


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def ascii_letters(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def cap_word(word):
    """Capitalize one badly-cased word: mcdonald -> McDonald, o'brien -> O'Brien."""
    parts = re.split(r"([-'’])", word.lower())
    out = []
    for p in parts:
        if p in ("-", "'", "’") or not p:
            out.append(p)
        elif p in GENERATIONAL:
            out.append(p.upper() if p != "jr" and p != "sr" else p.capitalize())
        elif p.startswith("mc") and len(p) > 2:
            out.append("Mc" + p[2:].capitalize())
        else:
            out.append(p.capitalize())
    return "".join(out)


def strip_credentials(name):
    """Drop credentials after a comma or at the end: 'Smith, CPA, PE' -> 'Smith'."""
    head, *tail = [p.strip() for p in name.split(",")]
    kept_tail = [t for t in tail if ascii_letters(t) not in CREDENTIALS]
    words = head.split()
    while len(words) > 1 and ascii_letters(words[-1]) in CREDENTIALS and words[-1].isupper():
        words.pop()
    return ", ".join([" ".join(words)] + kept_tail) if kept_tail else " ".join(words)


def normalize_name(name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        return name
    name = strip_credentials(name)
    words = []
    for w in name.split(" "):
        letters = re.sub(r"[^A-Za-z]", "", w)
        # Only fix words that are all lower or all upper; McKee/DeBose stay as they are.
        if letters and (letters.islower() or (letters.isupper() and len(letters) > 1
                                              and ascii_letters(w) not in GENERATIONAL)):
            words.append(cap_word(w))
        else:
            words.append(w)
    return " ".join(words)


def slug_of(url):
    url = (url or "").strip().rstrip("/")
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url, re.I)
    return m.group(1).lower() if m else ""


def slug_matches(slug, first, last):
    s = ascii_letters(slug)
    f, l = ascii_letters(first), ascii_letters(last.split(",")[0].split(" ")[-1] if last else "")
    return bool(f and l and f in s and l in s)


def email_matches(email, first, last):
    """True if the email's local part plausibly belongs to this person.

    Accepts the first or last name (or a 3+ letter prefix of the first name,
    for nicknames), and initials patterns like jdoe, johnd, jd.
    """
    local = ascii_letters((email or "").split("@")[0])
    f, l = ascii_letters(first), ascii_letters(last.split(",")[0].split(" ")[-1] if last else "")
    if not local or not (f and l):
        return True
    if l in local or f in local or f[:3] in local and len(local) > 3:
        return True
    return local in {f[0] + l[0], f[0] + l, f + l[0], l + f[0]} or local.startswith(f[0] + l[:3])


def most_common_website(contacts):
    by_company = {}
    for r in contacts:
        by_company.setdefault(r[COMPANY_ID], Counter())[r.get("Website", "")] += 1
    return {k: v.most_common(1)[0][0] for k, v in by_company.items()}


def prepare(args):
    _, contacts = read_rows(args.contacts)
    name_changes, linkedin_review, email_review = [], [], []
    for r in contacts:
        for col in ("First Name", "Last Name"):
            new = normalize_name(r[col])
            if new != r[col]:
                name_changes.append({CONTACT_ID: r[CONTACT_ID], "column": col, "from": r[col], "to": new})
                r[col] = new
        url = r.get(LINKEDIN, "")
        slug = slug_of(url)
        if url and not slug:
            linkedin_review.append({CONTACT_ID: r[CONTACT_ID], "first": r["First Name"],
                                    "last": r["Last Name"], "company": r["Company Name"],
                                    "url": url, "slug": "", "issue": "not a linkedin.com/in/ URL"})
        elif slug and not slug_matches(slug, r["First Name"], r["Last Name"]):
            linkedin_review.append({CONTACT_ID: r[CONTACT_ID], "first": r["First Name"],
                                    "last": r["Last Name"], "company": r["Company Name"],
                                    "job_title": r.get("Job Title", ""), "url": url, "slug": slug,
                                    "issue": "slug does not contain first and last name"})

        email = r.get("Email Address", "")
        if email and not email_matches(email, r["First Name"], r["Last Name"]):
            email_review.append({CONTACT_ID: r[CONTACT_ID], "first": r["First Name"],
                                 "last": r["Last Name"], "company": r["Company Name"],
                                 "job_title": r.get("Job Title", ""), "email": email,
                                 "linkedin_slug": slug})

    _, companies = read_rows(args.companies)
    contact_sites = most_common_website(contacts)
    website_conflicts = [
        {COMPANY_ID: c[COMPANY_ID], "company": c["Company Name"], "company_file": c.get("Website", ""),
         "contact_file": contact_sites[c[COMPANY_ID]]}
        for c in companies
        if c[COMPANY_ID] in contact_sites and c.get("Website", "") != contact_sites[c[COMPANY_ID]]
    ]

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    review = {"name_changes": name_changes, "linkedin_review": linkedin_review,
              "email_review": email_review,
              "website_conflicts": website_conflicts}
    (out / "review_step2.json").write_text(json.dumps(review, indent=2))
    print(f"{len(contacts)} contacts: {len(name_changes)} name fixes, "
          f"{len(linkedin_review)} LinkedIn URLs and {len(email_review)} emails to judge; "
          f"{len(website_conflicts)} website conflicts -> {out / 'review_step2.json'}")


def times_thousand(value):
    v = (value or "").replace(",", "").strip()
    if not v:
        return ""
    try:
        n = float(v) * 1000
    except ValueError:
        return value
    return str(int(round(n)))


def apply(args):
    _, contacts = read_rows(args.contacts)
    _, companies = read_rows(args.companies)
    _, domains = read_rows(args.company_domains)
    decisions = json.loads(Path(args.decisions).read_text()) if args.decisions else {}
    linkedin_decisions = decisions.get("linkedin", {})
    email_decisions = decisions.get("email", {})
    cleared_emails = []

    blanked, replaced = [], []
    for r in contacts:
        r["First Name"] = normalize_name(r["First Name"])
        r["Last Name"] = normalize_name(r["Last Name"])
        e = email_decisions.get(r[CONTACT_ID])
        if e and e["action"] == "clear":
            # The domain stays: it is still the company's domain.
            cleared_emails.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                                   "company": r["Company Name"], "removed_email": r["Email Address"],
                                   "reason": e.get("reason", "")})
            r["Email Address"] = ""
        d = linkedin_decisions.get(r[CONTACT_ID])
        if d and d["action"] == "blank":
            blanked.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                            "company": r["Company Name"], "removed_url": r[LINKEDIN],
                            "reason": d.get("reason", "")})
            r[LINKEDIN] = ""
        elif d and d["action"] == "replace":
            replaced.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                             "company": r["Company Name"], "from": r[LINKEDIN], "to": d["url"]})
            r[LINKEDIN] = d["url"]

    # Company file: only the companies of this list's contacts (two-file rule).
    in_list = OrderedDict((r[COMPANY_ID], None) for r in contacts)
    by_id = {c[COMPANY_ID]: c for c in companies}
    domain_by_id = {d[COMPANY_ID]: d for d in domains}
    contact_sites = most_common_website(contacts)
    missing = [k for k in in_list if k not in by_id]
    dropped = [c["Company Name"] for c in companies if c[COMPANY_ID] not in in_list]

    out_companies = []
    for key in in_list:
        c = by_id.get(key)
        if c is None:
            continue
        c = dict(c)
        c["Website"] = contact_sites.get(key, c.get("Website", ""))
        c["Revenue (in USD)"] = times_thousand(c.get("Revenue (in 000s USD)", ""))
        c["Employee Range"] = re.sub(r"^Employees\.", "", c.get("Employee Range", ""))
        sub = c.get("Primary Sub-Industry", "").strip()
        c["Primary Industry"] = f"{c.get('Primary Industry', '').strip()}- {sub}" if sub else c.get("Primary Industry", "")
        d = domain_by_id.get(key, {})
        c["Company Domain"] = d.get("Company Domain", "")
        c["Additional Domains"] = d.get("Additional Domains", "")
        out_companies.append(c)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_rows(out / "contacts_upload.csv", CONTACT_COLUMNS, contacts)
    write_rows(out / "companies_upload.csv", COMPANY_COLUMNS, out_companies)
    report = {"linkedin_blanked": blanked, "linkedin_replaced": replaced,
              "emails_cleared": cleared_emails, "companies_missing_from_company_export": missing,
              "companies_dropped_not_in_list": dropped}
    (out / "report_step2.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {out / 'contacts_upload.csv'} ({len(contacts)} rows, {len(CONTACT_COLUMNS)} cols) and "
          f"{out / 'companies_upload.csv'} ({len(out_companies)} rows, {len(COMPANY_COLUMNS)} cols); "
          f"{len(blanked)} LinkedIn URLs blanked, {len(replaced)} replaced, {len(cleared_emails)} emails cleared")
    if missing:
        print("contacts' companies missing from the company export:", missing)
    if dropped:
        print("companies dropped (no contacts in this list):", ", ".join(dropped))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--contacts", required=True, help="contacts_step1.csv")
    p.add_argument("--companies", required=True, help="ZoomInfo company export")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=prepare)
    a = sub.add_parser("apply")
    a.add_argument("--contacts", required=True, help="contacts_step1.csv")
    a.add_argument("--companies", required=True, help="ZoomInfo company export")
    a.add_argument("--company-domains", required=True, help="company_domains_step1.csv")
    a.add_argument("--decisions", help="decisions_step2.json")
    a.add_argument("--out-dir", required=True)
    a.set_defaults(func=apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
