"""Step 1 — email domain cleaning.

Two stages, with Claude (the skill) in between:

  prepare  Read a contact file, normalize email domains, and write
           review.json: one entry per (company, email domain) pair for Claude
           to judge, plus companies that have no email domain at all.
  apply    Read the contact file and a decisions.json (Claude's judgments,
           the user's answers on doubtful rows, and web-sourced domains), and
           write the cleaned contact file plus a company -> domain summary.

decisions.json:
  {
    "pairs": {"<company_id>|<domain>": {"action": "keep" | "clear" | "map",
                                        "map_to": "<domain>", "reason": "..."}},
    "web_domains": {"<company_id>": {"domain": "...", "source": "..."}},
    "primary_domains": {"<company_id>": {"domain": "...", "reason": "..."}}
  }

Company file: every domain the company's contacts use is kept. The primary
goes in "Company Domain" (the ultimate owner's domain when set in
primary_domains, otherwise the most common one); the rest go in
"Additional Domains", separated by ";".
"""
import argparse
import csv
import json
import re
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

EMAIL = "Email Address"
DOMAIN = "Email Domain"
COMPANY = "Company Name"
COMPANY_ID = "ZoomInfo Company ID"

# Doubled TLDs like "acme.com.com" are typos, not a different domain.
DOUBLED_TLD = re.compile(r"(\.[a-z]{2,})\1+$")


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_email(email):
    """Return (email, fix_note). Lowercases the domain and repairs doubled TLDs."""
    email = (email or "").strip()
    if "@" not in email:
        return "", ""
    local, domain = email.rsplit("@", 1)
    domain = domain.strip().lower().rstrip(".")
    fixed = DOUBLED_TLD.sub(r"\1", domain)
    note = f"fixed doubled TLD ({domain} -> {fixed})" if fixed != domain else ""
    return f"{local}@{fixed}", note


def company_key(row):
    return row.get(COMPANY_ID) or row[COMPANY].strip().lower()


def prepare(args):
    _, rows = read_rows(args.contacts)
    pairs = OrderedDict()
    companies = OrderedDict()
    for row in rows:
        key = company_key(row)
        company = companies.setdefault(key, {
            "company_id": key, "company": row[COMPANY], "website": row.get("Website", ""),
            "contacts": 0, "with_email": 0,
        })
        company["contacts"] += 1
        email, fix = normalize_email(row[EMAIL])
        if not email:
            continue
        company["with_email"] += 1
        domain = email.split("@")[1]
        pair = pairs.setdefault(f"{key}|{domain}", {
            "key": f"{key}|{domain}", "company_id": key, "company": row[COMPANY],
            "email_domain": domain, "contacts": 0,
            "zoominfo_domains": Counter(), "fixes": [],
        })
        pair["contacts"] += 1
        pair["zoominfo_domains"][(row.get(DOMAIN) or "").lower()] += 1
        if fix and fix not in pair["fixes"]:
            pair["fixes"].append(fix)

    for pair in pairs.values():
        pair["zoominfo_domains"] = dict(pair["zoominfo_domains"])
        # Other domains seen at the same company help spot parent/child cases.
        pair["other_domains_at_company"] = sorted(
            p["email_domain"] for p in pairs.values()
            if p["company_id"] == pair["company_id"] and p["key"] != pair["key"])

    review = {
        "source": str(args.contacts),
        "pairs": list(pairs.values()),
        "companies_without_email": [c for c in companies.values() if not c["with_email"]],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "review.json").write_text(json.dumps(review, indent=2))
    print(f"{len(rows)} contacts, {len(companies)} companies, {len(pairs)} company/domain pairs, "
          f"{len(review['companies_without_email'])} companies with no email -> {out / 'review.json'}")


def apply(args):
    fieldnames, rows = read_rows(args.contacts)
    decisions = json.loads(Path(args.decisions).read_text())
    pair_decisions = decisions.get("pairs", {})
    web_domains = decisions.get("web_domains", {})
    primary_domains = decisions.get("primary_domains", {})

    missing = set()
    for row in rows:
        row["ZoomInfo Email Domain"] = row.get(DOMAIN, "")
        row["Original Email"] = row[EMAIL]
        email, fix = normalize_email(row[EMAIL])
        notes = [fix] if fix else []
        domain = ""
        if email:
            domain = email.split("@")[1]
            key = f"{company_key(row)}|{domain}"
            decision = pair_decisions.get(key)
            if decision is None:
                missing.add(key)
                decision = {"action": "keep"}
            action = decision["action"]
            if action == "clear":
                notes.append(f"email cleared: {decision.get('reason', 'domain does not match company')}")
                email, domain = "", ""
            elif action == "map":
                notes.append(f"email cleared, domain mapped {domain} -> {decision['map_to']}: "
                             f"{decision.get('reason', '')}".rstrip(": "))
                email, domain = "", decision["map_to"]
        row[EMAIL] = email
        row[DOMAIN] = domain
        row["Email Domain Source"] = "email" if email else ("mapped to parent" if domain else "")
        if domain and domain != (row["ZoomInfo Email Domain"] or "").lower():
            notes.append(f"differs from ZoomInfo ({row['ZoomInfo Email Domain'] or 'blank'}); extracted wins")
        row["Step 1 Notes"] = "; ".join(notes)

    if missing:
        raise SystemExit(f"decisions.json has no judgment for: {sorted(missing)}")

    # Company domain set = distinct domains from its contacts, most common first.
    by_company = defaultdict(Counter)
    for row in rows:
        if row[DOMAIN]:
            by_company[company_key(row)][row[DOMAIN]] += 1
    for key, info in web_domains.items():
        if key not in by_company:
            by_company[key][info["domain"]] += 1

    def domains_for(key):
        """Primary first, then the rest by frequency."""
        ordered = [d for d, _ in by_company[key].most_common()]
        primary = primary_domains.get(key, {}).get("domain")
        if primary:
            ordered = [primary] + [d for d in ordered if d != primary]
        return ordered

    for row in rows:
        if row[DOMAIN]:
            continue
        key = company_key(row)
        if key in by_company:
            row[DOMAIN] = domains_for(key)[0]
            if key in web_domains and row[DOMAIN] == web_domains[key]["domain"]:
                row["Email Domain Source"] = f"web: {web_domains[key]['source']}"
            else:
                row["Email Domain Source"] = "backfilled from colleague"

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    extra = ["Original Email", "ZoomInfo Email Domain", "Email Domain Source", "Step 1 Notes"]
    write_rows(out / "contacts_step1.csv", fieldnames + extra, rows)

    summary, seen = [], set()
    for row in rows:
        key = company_key(row)
        if key in seen:
            continue
        seen.add(key)
        domains = domains_for(key) if key in by_company else []
        if key in web_domains and not any(r[EMAIL] for r in rows if company_key(r) == key):
            source = "web: " + web_domains[key]["source"]
        elif key in primary_domains:
            source = "ultimate owner: " + primary_domains[key].get("reason", "")
        else:
            source = "contacts"
        summary.append({COMPANY_ID: key, COMPANY: row[COMPANY], "Website": row.get("Website", ""),
                        "Company Domain": domains[0] if domains else "",
                        "Additional Domains": ";".join(domains[1:]),
                        "Domain Source": source})
    write_rows(out / "company_domains_step1.csv", list(summary[0].keys()), summary)

    unresolved = [s[COMPANY] for s in summary if not s["Company Domain"]]
    changed = sum(1 for r in rows if r["Step 1 Notes"] or r["Email Domain Source"] != "email")
    print(f"wrote {out / 'contacts_step1.csv'} ({len(rows)} rows, {changed} changed) and "
          f"{out / 'company_domains_step1.csv'} ({len(summary)} companies)")
    if unresolved:
        print("companies still without a domain:", ", ".join(unresolved))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("contacts")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=prepare)
    a = sub.add_parser("apply")
    a.add_argument("contacts")
    a.add_argument("--decisions", required=True)
    a.add_argument("--out-dir", required=True)
    a.set_defaults(func=apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
