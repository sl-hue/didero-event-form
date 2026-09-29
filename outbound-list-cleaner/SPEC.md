# Outbound list cleaner — process spec

**Prerequisites (checked before every run):** run on Opus 5.x or Fable; the
HubSpot connector is connected; `HUBSPOT_PRIVATE_APP_TOKEN` (read-only private
app) is set on the device so the script can search HubSpot directly.

Captured from the user's walkthrough. This is the source of truth for what the
scripts and skill must do; update it as steps are added.

## Core output rule

Every list produces **two files**: a contact file and a company file.

- A *list* is a set of people to reach out to. The company file contains only
  the companies of the contacts in that list.
- If a list is split into sublists, each sublist gets its own company file.
- Reference target format: sample files 4 (contacts) and 5 (companies) in
  `samples/MANIFEST.md`. File 4's last three columns are reference-only.

## Flow: straight enrichment (no filtering, no splitting)

### Step 1 — Email domain cleaning

Goal: every contact ends up with an email domain that matches its company's
domain, so HubSpot associates the contact with the company record.

Key concepts:
- **Email domain** = company domain (same thing). Drives HubSpot association.
- **Website** is a separate field; it must also be correct but can differ from
  the email domain (e.g. website `doitbestonline.com`, email domain
  `doitbest.com`).

- The website is **not** used to derive or check the email domain.

Sub-steps, in order:
1. **Company-match check (needs judgment).** For each email, decide whether its
   domain plausibly belongs to the contact's current company name. Matches are
   often not literal: shortened names, acronyms, partial acronyms
   (UFP Industries → `ufpi.com`, First Supply → `1supply.com`). Claude makes
   this call, not string matching. This is *not* a deliverability check —
   email validity is out of scope at this stage.
   - Clear match → keep.
   - Clear mismatch (old employer) → clear the email.
   - Doubtful, or a possible parent/child relationship (e.g. `kodiakbp.com`
     under QXO) → queue for human review.
2. **Human review of doubtful rows.** For each queued row, Claude shows the
   user: the contact, company, email domain, why it thinks it does or doesn't
   match, and whether a parent/child relationship exists. The user picks from
   a decision box in chat: keep / clear / map to parent domain.
3. **Extract domain.** Build `Email Domain` from each surviving email.
4. **Reconcile with ZoomInfo.** If the extracted domain differs from
   ZoomInfo's `Email Domain`, the extracted domain wins.
5. **Backfill from colleagues.** Contacts without an email get the email domain
   from another contact at the same company.
6. **Backfill from the web.** If no contact at a company has an email, Claude
   searches the web for publicly listed general inboxes (info@, support@,
   help@, general@, sales@, marketing@, inquiry@, and variants) and takes the
   domain from those. Applied to the company and all its contacts. If no
   general inbox exists, publicly listed staff addresses are acceptable
   evidence of the domain (confirmed by user on the CBM M&A run).
7. **Build company domains.** Every domain used by the company's contacts
   goes on the company record:
   - `Company Domain` — the primary domain: the one **most used** by the
     company's contacts. Ties go to the user.
   - `Additional Domains` — all other domains, separated by `;`.
   Contacts without an email are backfilled with the primary domain.

### Decision rules (confirmed by user)

- Subsidiary / acquired-company emails (e.g. `kodiakbp.com` at QXO) are
  **kept**; whichever domain is most used becomes `Company Domain`, the rest
  go in `Additional Domains`.
- Web backfill: use the ultimate owner and the email domain it actually uses
  (e.g. Threaded Fasteners → `tfmfg.com`, the domain its public inboxes use).
- Acquisitions don't change a company's domain by themselves: FBM stays on
  its own domains even though Lowe's owns it.
- Company file: `Company Domain` + `Additional Domains` replace file 5's
  single `Email Domain` column (confirmed).
- ZoomInfo placeholder domains (e.g. `zoomhubs.com`) are cleared automatically.
- Doubled TLDs (`.com.com`) are fixed, not cleared.
- A ZoomInfo company name that doesn't resemble the domain is not by itself a
  mismatch — check what company the domain actually belongs to
  (Sign & Awning Services → `arch-fab.com`, Architectural Fabrication: keep).

### Observed in the CBM M&A sample (raw → final)

- Typo fixed rather than dropped: `…@afcind.com.com` → `…@afcind.com`.
- Junk/placeholder domain cleared: `zoomhubs.com`.
- Acquired-subsidiary email cleared and domain set to parent: `kodiakbp.com`
  → `qxo.com` (QXO).
- A company can hold several domains, joined with `; `
  (Foundation Building Materials: `fbmsales.com; myfbm.com`).
- Sample file 5 leaves `Email Domain` blank for companies with no contact
  emails (e.g. The Gund Company, Threaded Fasteners); under sub-step 6 the
  script should fill these, so differences there are expected when testing.

### Step 2 — Normalization

Runs on step 1's output. Produces the upload files. **Output files contain only
upload columns** — no notes, flags or audit columns. Everything the user must
review is reported in chat.

**Contact file**
1. **Names.** Fix first/last names that are all lowercase or all caps
   (handling Mc, O', hyphens, Jr/Sr/II/III). Leave correctly mixed-case names
   alone (McKee, DeBose). Strip credentials (", CPA", " PE", "CSCP"…);
   generational suffixes stay.
2. **LinkedIn URL.** No live check. Compare the slug with the name:
   - Slug contains first and last name → keep.
   - Nickname, initials, credentials in the slug, or a typo → keep.
   - Clearly a different person → **blank the URL**, then list it in chat.
   - First name matches but last name differs (maybe married/maiden name) →
     **ask the user** in a decision box (keep / blank / paste the correct URL).
     The user checks LinkedIn themselves before answering.

2b. **Email vs. person.** Same logic as LinkedIn, on the email's local part:
   nicknames, initials (`jdoe`, `mike.n`) are fine; an email that clearly
   belongs to someone else (Jordan Esco → `jwiggins@…`) is cleared (the
   domain stays); last name differs → ask the user.

2c. **Dropdown values.** Values going into HubSpot dropdown properties are
   rewritten to the exact option labels so the import doesn't reject them:
   Management Level → Employment Seniority options (`VP-Level` → `VP`,
   `C-Level` → `Executive`, Director, Manager, `Non-Manager` → `Employee`);
   Department must be one of HubSpot's Department options. Values with no
   matching option are listed in chat for the user to fix.

**Company file** (from the ZoomInfo company export)
3. **Only this list's companies** (two-file rule).
4. **Sync with contacts.** `Website` taken from the contact file;
   `Company Domain` and `Additional Domains` from step 1.
5. **Revenue.** `Revenue (in 000s USD)` × 1,000 → `Revenue (in USD)`.
   All ZoomInfo values pass through as given — no outlier flagging.
6. **Employee range.** Strip the `Employees.` prefix.
7. **Industry.** `<Primary Industry>- <Primary Sub-Industry>` in
   `Primary Industry` (no space before the hyphen).

**Both files**
8. **Prune columns** to the upload set (see `CONTACT_COLUMNS` and
   `COMPANY_COLUMNS` in `scripts/normalize.py`). The contact file's first column
   is `ZoomInfo Contact ID`. Later-step columns (HubSpot record IDs,
   personalization, `Type`) are added by those steps.

### Step 3 — HubSpot duplicate check

Companies first (they are the anchor records contacts associate to), then
contacts. Claude runs the HubSpot searches through the connector; the script
scores the results.

**Company matching signals**
- Strong: `domain` equals the Company Domain or an Additional Domain (domain is
  unique in HubSpot); same website; same ZoomInfo Company ID
  (`zoominfo_company_id`); same LinkedIn company page
  (`linkedin_company_page`).
- Possible: similar company name, especially with the same city / state /
  country. Use firmographics (employees, revenue, industry) to judge unclear
  cases.

**Contact matching signals**
- Strong: same LinkedIn URL (HubSpot property `lgm_linkedinurl`,
  "Linkedin Url (Default)") — the most reliable, survives job changes; same
  email (often stale when people change jobs).
- Possible: same first + last name (with state / country) — may have moved
  companies; short/alternate first name with the same last name; same job
  title at the same company under a different name.

**Review and merge flow (both object types)**
1. Show the user every possible match for a record, each with its HubSpot
   link, plus why it matches, so they can open them one by one.
2. Claude cannot merge records. The user merges the duplicates **manually in
   HubSpot**, one by one, into one survivor (records that turn out not to be
   duplicates stay separate).
3. Only after merging, the user tells Claude the survivor record ID (via the
   decision box). A merge usually creates a **new** record ID. Claude verifies
   the survivor through `hs_merged_object_ids`, and checks its name and
   primary domain still match the list (HubSpot may keep the other record's
   values).
4. A single strong match with no other candidates needs no question.
5. Output: `HubSpot Company Record ID` column on the company file and
   `HubSpot Contact Record ID` on the contact file; `Not in HubSpot` when
   there's no record.
6. After companies, the contact file's company fields (Company Name,
   Website, Company HQ Phone) are synced to match the company file.

### Step 4 — HubSpot import

The user imports through HubSpot's import screen: **companies first** (anchors),
then contacts. Claude doesn't write the records; it prepares the files and
shows the field mapping in chat as a table so the user picks the same fields.

- **Type:** every company in a list is `Prospect` unless the user says
  otherwise. If the list looks like it isn't prospects (e.g. partners,
  vendors, customers), ask whether another Type fits. Flag existing HubSpot
  records whose Type differs (e.g. Customer).
- **Don't overwrite:** the table suggests which columns to tick "Don't
  overwrite" for (company name, domain and Type on companies; email and
  company name on contacts); the user decides.
- **Record IDs** map to HubSpot's `Record ID`: a number updates that record;
  "Not in HubSpot" is blanked in the import copy (HubSpot rejects text IDs), so
  those rows create new records.
- **Not imported:** ZoomInfo Company ID and ZoomInfo Contact ID (they confuse a
  calling tool). Fax is removed from the company file in step 2.
- **Website** maps to `Website URL`, not "Website URL (Cleaned)".
- **Management Level → Employment Seniority** (`hs_seniority`, a dropdown);
  record IDs → HubSpot's built-in `Record ID` only (both confirmed).
- **Import errors:** the user either fixes the value in the file and
  re-imports, or edits the record directly in HubSpot. Recurring value
  mismatches should be added to step 2's dropdown conversion.
- Full column → property mapping: `COMPANY_MAPPING` / `CONTACT_MAPPING` in
  `scripts/hubspot_import.py`.

### Step 4 (after the import) — associations and leftover duplicates

After the import the files are done; the user works in HubSpot.
1. The user builds a contact segment of the imported contacts, excluding
   "Exclusion List A" … "Exclusion List F" (`config.json`), and gives Claude
   its name.
2. Claude pulls the segment's contacts and their company associations:
   - No association → associate with the company owning the contact's
     domain, as primary.
   - Several associations → the list's company (owning the contact's domain)
     becomes primary; others stay secondary.
   Claude proposes the fixes, the user approves, Claude applies them with the
   connector; unclear cases go to the user.
3. Claude checks the segment's companies against all of HubSpot for
   duplicates the pre-import check missed: domain variants (other TLD,
   subdomain, hyphen), same LinkedIn page or phone, similar name in a similar
   location (city may differ; state as code or name, e.g. TX = Texas).
   Location uses City, State/Region and Country/Region first; HubSpot's
   `location` field ("Salinas, CA, USA") only fills whichever of those is
   empty — many older records have only `location` set. It
   reports how many, lists each group in chat, and the user merges them.

### Step 5 — Enrichment in Clay

Assumes: segment created, duplicates merged, contacts associated. Happens in
Clay (team workspace); Clay writes results back to HubSpot. The Clay
connector can't open/duplicate/run workbooks, so the user runs it and Claude
guides. No HubSpot check afterwards.

- **Workbook:** Claude gives both template links (`config.json`) and the user
  chooses: Europe template for European contacts (poor ZoomInfo coverage);
  Americas/global template otherwise. The links are the live templates: the
  user duplicates one and renames the copy `name_segment_date` (the user
  names it if unclear); nothing is run in the template itself.
- **Tabs:** 1 ZoomInfo — only when the list wasn't built in ZoomInfo;
  2 PDL — always, first (most reliable); 3 Import Objects from HubSpot —
  always, after PDL (other providers, less reliable).
- **Import** (first column of each tab): import objects → Contacts → the
  segment → schedule Manual / one-time only.
- **Buttons:** ZoomInfo: Enrich Contact → Update Object. PDL: import again →
  Verify Email → Work Email → Enrich Person → LinkedIn URL → Update Object.
  Import Objects from HubSpot: Import Object → Mobile Phone → Update Object.
- **Gate:** step 6 starts only after the user confirms the enrichments are done.

### Step 6 — BDR assignment

Uses the `hubspot-bdr-list-assignment` skill on the segment, with these rules
taking precedence:
- BDRs only; the user names the pool each round (default Noah, Davis, Bart —
  must be HubSpot users). Anyone else → out of scope.
- Read-only until the user approves the CSV.
- Per company: count BDR-owned contacts in the segment **plus** the company's
  other contacts (pool BDRs only). The BDR with the most gets all the
  segment's contacts on that company and the company record (priority rule:
  one BDR per company).
- Segment contacts already owned by a pool BDR start with that BDR, but the
  company rule wins.
- Remaining companies are spread so each BDR gets a roughly equal number of
  contacts, then companies; new contacts may be moved between BDRs for
  balance, a company never split.
- Companies already worked by a BDR stay locked (priority). If the contact
  gap between BDRs is still > 10% of the average and > 3 contacts, Claude
  suggests specific locked companies to move and the user decides one by
  one (a moved company takes its other BDR-owned contacts with it).
- CSV: Company, Company Record ID, Old Company Owner, New Company Owner,
  Contact Name, Contact Record ID, Old Contact Owner, New Contact Owner,
  Reason; sorted by company A→Z, contacts adjacent and A→Z.
- After approval (or changes and re-approval), Claude writes contact then
  company owners to HubSpot and verifies.
