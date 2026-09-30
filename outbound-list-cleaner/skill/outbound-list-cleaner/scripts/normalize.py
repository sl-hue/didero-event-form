"""Step 2 — normalization.

Works on the run's working.csv (see worksheet.py). Two stages, with Claude
(the skill) in between:

  prepare  Normalize names, check LinkedIn slugs against names, and write
           review_step2.json: LinkedIn URLs whose slug doesn't contain the
           contact's first and last name (for Claude to judge), plus name
           changes and website conflicts to report in chat.
  apply    Apply decisions_step2.json and the formatting rules to working.csv
           in place (names, LinkedIn, emails, dropdown values, revenue x1000,
           employee range, industry, one website per company). Column pruning
           happens only at export (worksheet.py export). What changed goes to
           report_step2.json for the chat.

decisions_step2.json:
  {"linkedin": {"<ZoomInfo Contact ID>": {"action": "keep" | "blank" | "replace",
                                          "url": "<new URL, for replace>", "reason": "..."}},
   "email":    {"<ZoomInfo Contact ID>": {"action": "keep" | "clear", "reason": "..."}}}

  keep     plausible match, or the user chose to keep it
  blank    wrong person (Claude's call for clear cases, the user's otherwise)
  replace  the user supplied the correct URL
"""
import argparse
import json
import re
import unicodedata
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet as ws  # noqa: E402

CONTACT_ID = "ZoomInfo Contact ID"
COMPANY_ID = "ZoomInfo Company ID"
LINKEDIN = "LinkedIn Contact Profile URL"

# Professional credentials stripped from names. Generational suffixes
# (Jr, Sr, II, III) are part of the name and are kept.
CREDENTIALS = {
    "cpa", "pe", "mba", "phd", "jd", "esq", "cfa", "pmp", "cscp", "cpsm", "cpim", "cpm",
    "cltd", "cppm", "mcips", "cssbb", "cssgb", "leedap", "shrmcp", "shrmscp", "sphr", "phr",
    "cma", "cia", "cisa", "cissp", "cfe", "macc", "cem", "cmrp", "cpcm", "cfpim", "csp",
}
GENERATIONAL = {"jr", "sr", "ii", "iii", "iv", "v"}

# Values rewritten so they match HubSpot dropdown options exactly on import.
# Column -> (HubSpot property, {ZoomInfo value (lowercase): HubSpot option label}).
# Option lists as of 2026-09-28; re-check with the HubSpot connector
# (get_properties) if an import rejects a value.
DROPDOWNS = {
    "Management Level": ("hs_seniority (Employment Seniority)", {
        "c-level": "Executive", "vp-level": "VP", "director": "Director", "manager": "Manager",
        "non-manager": "Employee", "owner": "Owner", "partner": "Partner", "board member": "Executive",
        "senior": "Senior", "entry": "Entry", "employee": "Employee", "executive": "Executive", "vp": "VP",
    }),
    "Department": ("department (Department)", {
        v.lower(): v for v in ("Finance", "C-Suite", "Engineering & Technical", "Operations", "Legal",
                               "Information Technology", "Human Resources", "Sales", "Marketing")
    }),
}


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


def prepare(args):
    _, contacts = ws.load(args.run_dir)
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

    # Rows of one company that disagree on the website (it's company data).
    sites = {}
    for r in contacts:
        sites.setdefault(r[COMPANY_ID], Counter())[r.get("Website", "")] += 1
    website_conflicts = [{COMPANY_ID: k, "websites": dict(v)} for k, v in sites.items() if len(v) > 1]

    review = {"name_changes": name_changes, "linkedin_review": linkedin_review,
              "email_review": email_review, "website_conflicts": website_conflicts}
    out = Path(args.run_dir)
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
    fields, contacts = ws.load(args.run_dir)
    decisions = json.loads(Path(args.decisions).read_text()) if args.decisions else {}
    linkedin_decisions = decisions.get("linkedin", {})
    email_decisions = decisions.get("email", {})
    cleared_emails, blanked, replaced = [], [], []
    unmapped_dropdowns = Counter()

    # Contact fields.
    for r in contacts:
        for col, (_, options) in DROPDOWNS.items():
            value = (r.get(col) or "").strip()
            if not value:
                continue
            mapped = options.get(value.lower())
            if mapped:
                r[col] = mapped
            else:
                unmapped_dropdowns[(col, value)] += 1
        r["First Name"] = normalize_name(r["First Name"])
        r["Last Name"] = normalize_name(r["Last Name"])
        e = email_decisions.get(r[CONTACT_ID])
        if e and e["action"] == "clear" and r["Email Address"]:
            # The domain stays: it is still the company's domain.
            cleared_emails.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                                   "company": r["Company Name"], "removed_email": r["Email Address"],
                                   "reason": e.get("reason", "")})
            r["Email Address"] = ""
        d = linkedin_decisions.get(r[CONTACT_ID])
        if d and d["action"] == "blank" and r[LINKEDIN]:
            blanked.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                            "company": r["Company Name"], "removed_url": r[LINKEDIN],
                            "reason": d.get("reason", "")})
            r[LINKEDIN] = ""
        elif d and d["action"] == "replace" and r[LINKEDIN] != d["url"]:
            replaced.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                             "company": r["Company Name"], "from": r[LINKEDIN], "to": d["url"]})
            r[LINKEDIN] = d["url"]

    # Company fields — every step is safe to re-run.
    fields = ws.ensure_columns(fields, ["Revenue (in USD)"], after="Revenue (in 000s USD)")
    sites = {}
    for r in contacts:
        sites.setdefault(r[COMPANY_ID], Counter())[r.get("Website", "")] += 1
    for r in contacts:
        r["Website"] = sites[r[COMPANY_ID]].most_common(1)[0][0]
        if not r.get("Revenue (in USD)"):
            r["Revenue (in USD)"] = times_thousand(r.get("Revenue (in 000s USD)", ""))
        r["Employee Range"] = re.sub(r"^Employees\.", "", r.get("Employee Range", ""))
        sub = (r.get("Primary Sub-Industry") or "").strip()
        industry = (r.get("Primary Industry") or "").strip()
        if sub and not industry.endswith(f"- {sub}"):
            r["Primary Industry"] = f"{industry}- {sub}"

    ws.save(args.run_dir, fields, contacts)
    report = {"linkedin_blanked": blanked, "linkedin_replaced": replaced, "emails_cleared": cleared_emails,
              "dropdown_values_not_matching": [
                  {"column": col, "value": v, "rows": n, "hubspot_property": DROPDOWNS[col][0],
                   "allowed": sorted(set(DROPDOWNS[col][1].values()))}
                  for (col, v), n in unmapped_dropdowns.items()]}
    (Path(args.run_dir) / "report_step2.json").write_text(json.dumps(report, indent=2))
    ws.log(args.run_dir, {"action": "step2", "linkedin_blanked": len(blanked), "linkedin_replaced": len(replaced),
                          "emails_cleared": len(cleared_emails)})
    ws.snapshot_copy(args.run_dir, "02_normalize")
    print(f"working.csv updated: {len(contacts)} contacts; {len(blanked)} LinkedIn URLs blanked, "
          f"{len(replaced)} replaced, {len(cleared_emails)} emails cleared, "
          f"{sum(unmapped_dropdowns.values())} dropdown values with no matching HubSpot option")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=prepare)
    a = sub.add_parser("apply")
    a.add_argument("--run-dir", required=True)
    a.add_argument("--decisions", help="decisions_step2.json")
    a.set_defaults(func=apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
