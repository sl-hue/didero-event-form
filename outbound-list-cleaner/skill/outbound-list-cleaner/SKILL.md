---
name: outbound-list-cleaner
description: Clean and standardize outbound prospecting lists (ZoomInfo, Clay, HubSpot, lemlist exports) into Didero's two-file HubSpot upload format — a contact file and a matching company file per list. Use whenever someone gives you a raw contact or company export to clean, enrich, or prepare for a HubSpot/lemlist upload, or asks to fix email domains so contacts associate with the right company.
---

# Outbound list cleaner

Status: **step 1 (email domain cleaning) only.** Later steps are being
specified; see `PROJECT.md` and `SPEC.md` in the project repo for the full plan.

Every list produces two files: a contact file and a company file containing
only that list's companies. A sublist gets its own company file.

## Step 1 — Email domain cleaning

Goal: every contact has an email domain matching its company's domain so
HubSpot associates them. The website is **never** used as the email domain.

1. **Prepare.** Run
   `python3 scripts/email_domain.py prepare <contacts.csv> --out-dir <run_dir>`.
   It normalizes emails (lowercase domain, fixes doubled TLDs like `.com.com`)
   and writes `<run_dir>/review.json`: one entry per company/email-domain pair,
   plus companies where no contact has an email.

2. **Judge each pair.** Decide whether the email domain plausibly belongs to
   the contact's current company. Matches are often not literal — acronyms,
   tickers, shortened names (UFP Industries → `ufpi.com`, Builders FirstSource
   → `bldr.com`, EMS → `easternmetal.com`). This is not an email-validity check.
   - Clear match → `keep`.
   - Clear mismatch (a prior employer, a data-vendor placeholder such as
     `zoomhubs.com`) → `clear`.
   - Parent/child (subsidiary or acquired company, e.g. `kodiakbp.com` at
     QXO) → `keep`; it becomes an additional domain unless it is the most
     used one.
   - Anything doubtful → ask the user (step 3).
   If the ZoomInfo company name looks unrelated to the domain, check what
   company the domain actually belongs to before calling it a mismatch.

3. **Ask the user about doubtful rows.** Use the multiple-choice question tool
   (up to 4 questions per call; batch in rounds). For each row show: company,
   email domain, number of contacts, other domains at that company, why you
   think it does/doesn't match, and any parent/child relationship. Offer
   options such as keep / clear / map to parent, with your recommendation
   first. Treat free-text answers as rules to apply going forward.

4. **Web backfill.** For each company with no email at all, search the web for
   publicly listed general inboxes (info@, sales@, support@, help@, general@,
   marketing@, inquiry@ and variants, including location inboxes such as
   `infomobile@`). Use that domain. If none exists, publicly listed staff
   addresses are acceptable evidence. Always use the ultimate owner's domain.
   If the answer is unclear, ask the user.

5. **Write decisions.json** in the run dir:
   ```json
   {
     "pairs": {"<company_id>|<domain>": {"action": "keep|clear|map", "map_to": "...", "reason": "..."}},
     "web_domains": {"<company_id>": {"domain": "...", "source": "..."}},
     "primary_domains": {"<company_id>": {"domain": "...", "reason": "..."}}
   }
   ```
   Every pair in review.json needs an entry; the script refuses to run otherwise.
   `primary_domains` is only for overrides — e.g. the user's pick when
   review.json lists a company under `primary_ties`. By default the most used
   domain is primary.

6. **Apply.** Run
   `python3 scripts/email_domain.py apply <contacts.csv> --decisions <run_dir>/decisions.json --out-dir <run_dir>`.
   Outputs:
   - `contacts_step1.csv` — the input columns with `Email Address` and
     `Email Domain` cleaned, plus audit columns `Original Email`,
     `ZoomInfo Email Domain`, `Email Domain Source`, `Step 1 Notes`.
   - `company_domains_step1.csv` — per company: `Company Domain` (most used),
     `Additional Domains` (`;`-separated), `Domain Source`.

7. **Report** counts (own email / backfilled / web / cleared / fixed) and any
   company still without a domain.

## Data handling

These files contain personal contact data. Never commit them to a repository
or publish them; keep inputs and run outputs in local, git-ignored folders.
