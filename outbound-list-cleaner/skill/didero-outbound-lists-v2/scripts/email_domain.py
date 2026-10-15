"""Step 1 — email domain cleaning.

Works on the run's working.csv (see worksheet.py). Two stages, with Claude
(the skill) in between:

  prepare  Normalize email domains and write review.json: one entry per
           (company, email domain) pair for Claude to judge, plus companies
           that have no email domain at all.
  apply    Apply decisions.json (Claude's judgments, the user's answers on
           doubtful rows, and web-sourced domains) to working.csv in place:
           Email Address, Email Domain, and the company-level Company Domain
           and Additional Domains on every row of each company. What changed
           and why goes to step1_report.json, not into the file.

decisions.json:
  {
    "pairs": {"<company_id>|<domain>": {"action": "keep" | "clear" | "map",
                                        "map_to": "<domain>", "reason": "..."}},
    "web_domains": {"<company_id>": {"domain": "...", "source": "..."}},
    "primary_domains": {"<company_id>": {"domain": "...", "reason": "..."}}
  }

Company file: every domain the company's contacts use is kept. The primary
goes in "Company Domain" (the domain most used by its contacts, unless
overridden in primary_domains); the rest go in "Additional Domains",
separated by ";". Ties for most used are listed in review.json under
"primary_ties" so Claude can ask the user and record the answer in
primary_domains.
"""
import argparse
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet as ws  # noqa: E402

EMAIL = "Email Address"
DOMAIN = "Email Domain"
COMPANY = "Company Name"
COMPANY_ID = "ZoomInfo Company ID"

# Personal mailbox providers are never a company's domain.
FREE_MAIL = {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
             "yahoo.com", "ymail.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com",
             "gmx.com", "gmx.de", "web.de", "mail.com", "yandex.ru", "qq.com", "139.com", "163.com",
             "126.com", "sina.com", "naver.com"}

# Doubled TLDs like "acme.com.com" are typos, not a different domain.
DOUBLED_TLD = re.compile(r"(\.[a-z]{2,})\1+$")


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
    _, rows = ws.load(args.run_dir)
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
        if not email or email.split("@")[1] in FREE_MAIL:
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

    ties = []
    for key, company in companies.items():
        counts = sorted((p["contacts"] for p in pairs.values() if p["company_id"] == key), reverse=True)
        if len(counts) > 1 and counts[0] == counts[1]:
            ties.append({"company_id": key, "company": company["company"],
                         "domains": {p["email_domain"]: p["contacts"] for p in pairs.values()
                                     if p["company_id"] == key}})

    review = {
        "source": "working.csv",
        "pairs": list(pairs.values()),
        "companies_without_email": [c for c in companies.values() if not c["with_email"]],
        "primary_ties": ties,
    }
    out = Path(args.run_dir)
    (out / "review.json").write_text(json.dumps(review, indent=2))
    print(f"{len(rows)} contacts, {len(companies)} companies, {len(pairs)} company/domain pairs, "
          f"{len(review['companies_without_email'])} companies with no email, "
          f"{len(ties)} primary-domain ties -> {out / 'review.json'}")


def apply(args):
    fieldnames, rows = ws.load(args.run_dir)
    decisions = json.loads(Path(args.decisions).read_text())
    pair_decisions = decisions.get("pairs", {})
    web_domains = decisions.get("web_domains", {})
    primary_domains = decisions.get("primary_domains", {})

    missing = set()
    report = {}
    for row in rows:
        zoominfo_domain = row.get(DOMAIN, "")
        original = row[EMAIL]
        email, fix = normalize_email(row[EMAIL])
        notes = [fix] if fix else []
        domain = ""
        if email and email.split("@")[1] in FREE_MAIL:
            notes.append(f"personal email ({email.split('@')[1]}): kept, but its domain is not used")
        elif email:
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
        if domain and domain != (zoominfo_domain or "").lower():
            notes.append(f"differs from ZoomInfo ({zoominfo_domain or 'blank'}); extracted wins")
        report[row[ws.CONTACT_ID]] = {"name": f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                                      "company": row[COMPANY], "original_email": original,
                                      "source": "email" if domain and email else ("mapped to parent" if domain else ""),
                                      "notes": notes}

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
            report[row[ws.CONTACT_ID]]["source"] = (f"web: {web_domains[key]['source']}"
                                                    if key in web_domains and row[DOMAIN] == web_domains[key]["domain"]
                                                    else "backfilled from colleague")

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
            source = "primary chosen by user: " + primary_domains[key].get("reason", "")
        else:
            source = "contacts"
        summary.append({COMPANY_ID: key, COMPANY: row[COMPANY], "Website": row.get("Website", ""),
                        "Company Domain": domains[0] if domains else "",
                        "Additional Domains": ";".join(domains[1:]),
                        "Domain Source": source})
        ws.set_company_field(rows, key, "Company Domain", domains[0] if domains else "")
        ws.set_company_field(rows, key, "Additional Domains", ";".join(domains[1:]))

    ws.save(args.run_dir, fieldnames, rows)
    changed = {k: v for k, v in report.items() if v["notes"] or v["source"] != "email"}
    (Path(args.run_dir) / "step1_report.json").write_text(json.dumps(
        {"contacts_changed": changed, "companies": summary}, indent=2, ensure_ascii=False))
    ws.log(args.run_dir, {"action": "step1", "contacts_changed": len(changed), "companies": len(summary)})
    ws.snapshot_copy(args.run_dir, "01_email_domains")
    unresolved = [s[COMPANY] for s in summary if not s["Company Domain"]]
    print(f"working.csv updated: {len(rows)} contacts ({len(changed)} changed), {len(summary)} companies; "
          f"details in step1_report.json")
    if unresolved:
        print("companies still without a domain:", ", ".join(unresolved))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=prepare)
    a = sub.add_parser("apply")
    a.add_argument("--run-dir", required=True)
    a.add_argument("--decisions", required=True)
    a.set_defaults(func=apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
