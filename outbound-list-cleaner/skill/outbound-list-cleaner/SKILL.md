---
name: outbound-list-cleaner
description: Clean and standardize outbound prospecting lists (ZoomInfo, Clay, HubSpot, lemlist exports) into Didero's two-file HubSpot upload format — a contact file and a matching company file per list. Use whenever someone gives you a raw contact or company export to clean, enrich, or prepare for a HubSpot/lemlist upload, or asks to fix email domains so contacts associate with the right company.
---

# Outbound list cleaner

Status: **steps 1 (email domain cleaning), 2 (normalization), 3 (HubSpot duplicate check) and 4 (HubSpot import prep).** Later steps are being
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

## Step 2 — Normalization

Output files contain only upload columns: never add notes or flag columns.
Everything the user needs to review goes in the chat.

1. **Prepare.** Run
   `python3 scripts/normalize.py prepare --contacts <run_dir>/contacts_step1.csv --companies <zoominfo_company_export.csv> --out-dir <run_dir>`.
   It fixes name casing and strips credentials, and writes
   `review_step2.json` listing LinkedIn URLs whose slug doesn't contain the
   contact's first and last name.

2. **Judge each LinkedIn slug** (no live check):
   - Nickname (Bill/William, Pat/Patrick), initials (`jbsunderbruch`),
     credentials in the slug, or an obvious typo → `keep`.
   - Clearly a different person (both names differ) → `blank`.
   - First name matches, last name differs (possibly a married/maiden name)
     → ask the user with the multiple-choice tool: show name, company, job
     title and the URL, and offer Keep / Blank (they can type a corrected URL
     under "Other" → `replace`). The user checks LinkedIn themselves; you
     don't need to.

   Judge `email_review` the same way on the email's local part: nickname or
   initials → `keep`; clearly someone else's email → `clear` (the domain
   stays); last name differs → ask the user.

3. **Write `<run_dir>/decisions_step2.json`:**
   `{"linkedin": {"<ZoomInfo Contact ID>": {"action": "keep|blank|replace", "url": "...", "reason": "..."}},
     "email": {"<ZoomInfo Contact ID>": {"action": "keep|clear", "reason": "..."}}}`

4. **Apply.** Run
   `python3 scripts/normalize.py apply --contacts <run_dir>/contacts_step1.csv --companies <zoominfo_company_export.csv> --company-domains <run_dir>/company_domains_step1.csv --decisions <run_dir>/decisions_step2.json --out-dir <run_dir>`.
   Outputs `contacts_upload.csv`, `companies_upload.csv` (only the list's
   companies; revenue ×1000, `Employees.` prefix stripped, industry combined,
   website and domains synced from contacts), and `report_step2.json`.

5. **Report in chat:** dropdown values with no matching HubSpot option
   (`dropdown_values_not_matching`, e.g. a Management Level or Department
   value HubSpot's dropdown doesn't have), name fixes, blanked LinkedIn URLs (name, company,
   removed URL, reason), the user's last-name decisions, and any companies
   dropped or missing.

## Step 3 — HubSpot duplicate check

Claude cannot merge HubSpot records; the user merges manually and then tells
you the survivor. Companies first, then contacts. `S=scripts/hubspot_match.py`.

**Companies**
1. `python3 $S plan-companies --companies <run_dir>/companies_upload.csv --out-dir <run_dir>`
   writes `company_search_plan.json`.
2. Run every search in the plan with the HubSpot connector's
   `search_crm_objects` (objectType, properties, limit, filterGroups or
   query as given; page with `offset` when `total` exceeds the results) and
   save each raw JSON response to `<run_dir>/hs_companies/NNN.json`. For large
   plans, hand this to a subagent so raw results don't flood the chat.
3. `python3 $S match-companies --companies <run_dir>/companies_upload.csv --raw-dir <run_dir>/hs_companies --out-dir <run_dir>`
   writes `company_matches.json` (per company: candidates with HubSpot URL,
   strength, reasons, domain, location, employees, revenue, contacts).
4. Judge the candidates. Drop obvious false positives from free-text name
   hits (different company, different place and size). Use firmographics for
   unclear cases.
   - No candidates → `null` (Not in HubSpot).
   - Exactly one strong candidate → record it, no question.
   - Two or more real candidates, or only a possible match → review with the user.
5. **Review with the user**, one company at a time:
   - In a chat message, list each candidate: HubSpot link, name, domain,
     location, contacts, created date, and why it matches.
   - Tell the user to open them and merge the duplicates in HubSpot
     themselves, one by one, into the record they want to keep.
   - Then ask with the multiple-choice tool: "After merging, which record
     survived?" — one option per candidate ID, plus "Not a duplicate / keep
     separate" where relevant. Up to 4 companies per call.
   - Re-search the merged-away IDs (`hs_object_id IN [...]`); if they still
     exist, the merge isn't done — tell the user and ask again.
6. Write `<run_dir>/company_decisions.json`
   (`{"<ZoomInfo Company ID>": {"record_id": "..." | null, "note": "..."}}`) and run
   `python3 $S apply-companies --companies <run_dir>/companies_upload.csv --contacts <run_dir>/contacts_upload.csv --contacts-step1 <run_dir>/contacts_step1.csv --decisions <run_dir>/company_decisions.json`.
   This adds `HubSpot Company Record ID` and syncs Company Name / Website /
   Company HQ Phone into the contact file.

**Contacts** — same loop:
1. `python3 $S plan-contacts --contacts <run_dir>/contacts_upload.csv --companies <run_dir>/companies_upload.csv --out-dir <run_dir>`
   (LinkedIn URL on `lgm_linkedinurl`, email, last name, and everyone
   associated with the list's HubSpot companies).
2. Run the searches, saving to `<run_dir>/hs_contacts/`.
3. `python3 $S match-contacts --contacts <run_dir>/contacts_upload.csv --companies <run_dir>/companies_upload.csv --contacts-step1 <run_dir>/contacts_step1.csv --raw-dir <run_dir>/hs_contacts --out-dir <run_dir>`
4. Judge, review with the user (same merge-first flow), write
   `contact_decisions.json`, then
   `python3 $S apply-contacts --contacts <run_dir>/contacts_upload.csv --decisions <run_dir>/contact_decisions.json`
   to add `HubSpot Contact Record ID`.

## Step 4 — HubSpot import

The user runs the import in HubSpot; you prepare it and walk them through it.

1. **Choose Type.** Default `Prospect`. Look at the list: if the companies
   don't look like prospects (partners, vendors, existing customers), ask the
   user which Type fits before continuing.
2. Run
   `python3 scripts/hubspot_import.py prepare --companies <run_dir>/companies_upload.csv --contacts <run_dir>/contacts_upload.csv --raw-dir <run_dir>/hs_companies --type Prospect --out-dir <run_dir>`.
   It adds the Type column, writes `companies_import.csv` / `contacts_import.csv`
   (record IDs blanked where "Not in HubSpot"), `import_mapping.md` and
   `report_step4.json`.
3. **In chat**, paste both tables from `import_mapping.md` and tell the user:
   - import the company file first, then the contact file;
   - map each column to the HubSpot property shown and set "Don't import
     column" where indicated;
   - tick "Don't overwrite" on any column where they want to keep what's
     already in HubSpot (the table suggests some);
   - how many rows will update vs. create, and any existing records whose
     Type differs (from `report_step4.json`) — suggest "Don't overwrite" on
     Type for those.
4. After the company import, the user can run the contact import; contacts
   associate to companies through the company domain.
5. **If HubSpot reports import errors**, tell the user to either fix the
   value in the file and re-import those rows, or edit the records directly
   in HubSpot. If a dropdown value keeps failing, check the property's
   current options with the HubSpot connector (`get_properties`) and add the
   conversion to `DROPDOWNS` in `scripts/normalize.py` so step 2 fixes it
   next time.

## Data handling

These files contain personal contact data. Never commit them to a repository
or publish them; keep inputs and run outputs in local, git-ignored folders.
