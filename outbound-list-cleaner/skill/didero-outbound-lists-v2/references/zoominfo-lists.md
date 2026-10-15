# Shared steps 1–7 (and the ZoomInfo stages)

Part of the `didero-outbound-lists-v2` skill — `SKILL.md` says which list type uses which steps. Scripts are in `scripts/`, settings in `config.json` (both at the skill's root).


## Steps and sub-agents

The order of the workflow; `scripts/progress.py` prints each step when it
starts. The start questions (end state, countries, BDRs, credits) are already
answered in `run_setup.json`: **no step asks the user anything**. Judgment
calls are Claude's, made with the rules in each step and written as one line
each in `<run_dir>/decisions.md`. The run **stops only where the user acts**
(steps 5, 6, 7).

**1. Email domain cleaning** — `email_domain.py`
- `domain-judge` (subagent) — judges each company/email-domain pair
- `web-domain-finder` (subagent) — finds public inboxes for companies with no email

**2. Normalization** — `normalize.py`
- `name-and-linkedin-checker` (subagent) — judges LinkedIn slugs and emails against names

**3. HubSpot duplicate check** — `hubspot_match.py` (read-only)
- `hubspot-searcher` (subagent) — runs the search plan
- `duplicate-reviewer` (subagent) — picks each company's record; lists duplicates for the user to merge later

**4. BDR owners** — `owners.py` (only when the end state includes BDR owners)

**5. HubSpot import** — `hubspot_import.py` — **USER ACTS**: imports the two files

**6. After the import** — `post_import.py` (read-only) — **USER ACTS**: builds the segment; fixes what the checks find

**7. Clay enrichment** — `clay_guide.py` — **USER ACTS**: runs the Clay buttons

All steps read and update the one working file through `worksheet.py`
(see "One working file"). Run the heavy sub-agents (`web-domain-finder`,
`hubspot-searcher`) as sub-agents so raw results stay out of the chat. Name
the sub-agent when you start its work ("Step 3 · hubspot-searcher: …").

## HubSpot links in chat — always

Every time you mention a HubSpot record in the chat — in a question, a
decision box, a table, a summary — link it, so the user can open it in one
click. Put the link on the record's name. Portal ID: `hubspot_portal_id` in
`config.json` (the connector's `urlTemplate` carries it too).

| Record | Link |
|---|---|
| Contact | `https://app.hubspot.com/contacts/<portal>/record/0-1/<id>` |
| Company | `https://app.hubspot.com/contacts/<portal>/record/0-2/<id>` |
| Deal | `https://app.hubspot.com/contacts/<portal>/record/0-3/<id>` |
| Segment / list | `https://app.hubspot.com/contacts/<portal>/objectLists/<id>` |

The scripts put a `url` on every record they report; use it.

## Paths

- **Scripts** live in this skill's own `scripts/` folder, and `config.json`
  next to this file. Commands below say `scripts/…`: run them with the
  absolute path of this skill's folder (find it once, e.g. the directory
  containing this SKILL.md) — don't copy the scripts elsewhere.
- **Run folder** (`<run_dir>`): create one per list in the user's working
  folder (in Cowork, the folder they've shared), named like the list, e.g.
  `<list>_<date>/`.
- The user's input files contain personal data: keep them and the run folder
  on the user's device. Never commit or publish them.

## One working file

The whole run works on **one data file**: `<run_dir>/working.csv` — one row
per contact, with the company's columns on the same row (a ZoomInfo contact
export already carries every company column). Every step reads and updates
it through the scripts; nothing else holds list data, so nothing can
disagree.

- **Start:** `python3 scripts/worksheet.py init --contacts <contact export> [--companies <company export>] --out-dir <run_dir>`.
  A company export is optional — if given, its company values win. Where a
  company's rows disagree (ZoomInfo sometimes varies per contact), the most
  common value is used (`init_report.json`, for the summary).
- **Company values are company-wide:** the scripts write company fields
  (domain, record ID, website, Type …) to every row of that company.
- **No hand edits — ever.** The user never edits the CSV, and you never edit
  it except through `worksheet.py` or a step's `apply` command.
- **Flags, never silent drops.** When a row needs a judgment (e.g. HubSpot
  has the person at another company), Claude decides with the step's rule —
  never silently: `worksheet.py set --row <id> --field "Column=value" … --reason "…"`,
  `resolve --row <id> --note "…"` if it stays as it is, or `remove --row <id>
  --reason "…"` when the rule says the row leaves the list. Every one of these
  goes in `decisions.md`. `worksheet.py flags --run-dir <run_dir>` lists open
  flags; export refuses while any is open.
- **History:** after each step a read-only copy is saved in `history/`
  (`01_email_domains.csv`, `02_normalize.csv`, …); every change is logged in
  `changes.jsonl`. Never read the history copies back as input.
- **Output:** the two upload files — a contact file and a company file with
  only the list's companies (a sublist gets its own pair) — are generated at
  step 5 into `upload/` by `worksheet.py export`, and never edited. Export
  refuses while any row is still flagged, and lists removed rows for the
  end-of-run summary.

## Before you start

Done at the start (`SKILL.md`): the requirements check (HubSpot and ZoomInfo
connected, Opus 5.5 or newer — the only reasons to stop before starting) and
the start questions. HubSpot is read through the connector ("connector
mode"); if `python3 scripts/hubspot_match.py check-token` passes (a private
app token already set up on this device), the token commands may be used
instead — never ask for a token, never set one up during a run. **Claude
never writes to HubSpot.**

### Connector mode: running searches and saving results

Wherever a step says `run-plan` (token mode), in connector mode the
`hubspot-searcher` sub-agent instead runs each search in the plan file with
`search_crm_objects` (objectType, properties, limit, filterGroups or query as
given; `chatInsights` is required; page with `offset` when `total` exceeds
the results). For each result, save it to a file — when the host has already
saved a large result to a file, use that path — and run
`python3 scripts/hubspot_match.py ingest --response <file> --raw-dir <raw dir>`.
`ingest` also accepts `query_crm_data` results (call the connector's
`tool_guidance` for `query_crm_data` once before the first query).

## Step 1 — Email domain cleaning

Goal: every contact has an email domain matching its company's domain so
HubSpot associates them. The website is **never** used as the email domain.

1. **Prepare.** Run
   `python3 scripts/email_domain.py prepare --run-dir <run_dir>` (after `worksheet.py init`).
   It normalizes emails (lowercase domain, fixes doubled TLDs like `.com.com`)
   and writes `<run_dir>/review.json`: one entry per company/email-domain pair,
   plus companies where no contact has an email.

2. **`domain-judge`: judge each pair.** Decide whether the email domain plausibly belongs to
   the contact's current company. Matches are often not literal — acronyms,
   tickers, shortened names (UFP Industries → `ufpi.com`, Builders FirstSource
   → `bldr.com`, EMS → `easternmetal.com`). This is not an email-validity check.
   - Clear match → `keep`.
   - Clear mismatch (a prior employer, a data-vendor placeholder such as
     `zoomhubs.com`) → `clear`.
   - Personal mailboxes (gmail.com, hotmail.com, 139.com, …) never appear
     here: the script keeps those emails but never uses their domain, and
     backfills the company domain instead.
   - Parent/child (subsidiary or acquired company, e.g. `kodiakbp.com` at
     QXO) → `keep`; it becomes an additional domain unless it is the most
     used one.
   - Doubtful → check what company the domain belongs to (web search) and
     decide; still unclear → `clear` (the company's other domains or the web
     backfill cover it). One line per decision in `decisions.md`.
   If the ZoomInfo company name looks unrelated to the domain, check what
   company the domain actually belongs to before calling it a mismatch.

3. **`web-domain-finder`: web backfill.** For each company with no email at all, search the web for
   publicly listed general inboxes (info@, sales@, support@, help@, general@,
   marketing@, inquiry@ and variants, including location inboxes such as
   `infomobile@`). Use that domain. If none exists, publicly listed staff
   addresses are acceptable evidence. Always use the ultimate owner's domain.
   If nothing reliable turns up, leave the company without a domain (noted in
   `decisions.md`; HubSpot matches it by name).

4. **Write decisions.json** in the run dir:
   ```json
   {
     "pairs": {"<company_id>|<domain>": {"action": "keep|clear|map", "map_to": "...", "reason": "..."}},
     "web_domains": {"<company_id>": {"domain": "...", "source": "..."}},
     "primary_domains": {"<company_id>": {"domain": "...", "reason": "..."}}
   }
   ```
   Every pair in review.json needs an entry; the script refuses to run otherwise.
   `primary_domains` is only for overrides — e.g. your pick when review.json
   lists a company under `primary_ties` (the domain on the company's website). By default the most used
   domain is primary.

5. **Apply.** Run
   `python3 scripts/email_domain.py apply --run-dir <run_dir> --decisions <run_dir>/decisions.json`.
   It updates `working.csv`: `Email Address`, `Email Domain`, and on every
   row of each company `Company Domain` (most used) and `Additional Domains`
   (`;`-separated). What changed and why is in `step1_report.json`.

6. **Report** counts (own email / backfilled / web / cleared / fixed) and any
   company still without a domain.

## Step 2 — Normalization

Output files contain only upload columns: never add notes or flag columns.
Everything the user needs to review goes in the chat.

1. **Prepare.** Run
   `python3 scripts/normalize.py prepare --run-dir <run_dir>`.
   It fixes name casing and strips credentials, and writes
   `review_step2.json` listing LinkedIn URLs whose slug doesn't contain the
   contact's first and last name, plus **company names** and **job titles**
   to clean (`company_names`, `job_titles`). This is the cleaning step for
   every list type, and it is never skipped: the contact's first and last
   name, the company name (the contact's company is the same column) and the
   job title are all rewritten here.

2. **`name-and-linkedin-checker`: judge each LinkedIn slug** (no live check):
   - Nickname (Bill/William, Pat/Patrick), initials (`jbsunderbruch`),
     credentials in the slug, or an obvious typo → `keep`.
   - Clearly a different person (both names differ) → `blank`.
   - First name matches, last name differs (possibly a married/maiden name):
     `keep` when the email or ZoomInfo also points to this person at this
     company; otherwise `blank` (a wrong LinkedIn URL is worse than none).

   Judge `email_review` the same way on the email's local part: nickname or
   initials → `keep`; clearly someone else's email → `clear` (the domain
   stays); last name differs → `keep` if the email's domain is the company's
   and the first name or initial matches, else `clear`.

   **Company names and job titles:** entries with `"judgment": false` are
   safe fixes (legal suffix like Inc./LLC/Co. removed, symbols, spacing,
   ALL-CAPS titles) and are applied automatically. For `"judgment": true`
   decide the clean value: ALL-CAPS company names (keep only if the company
   writes it that way, e.g. NIBCO; otherwise `TCC MATERIALS` → `TCC
   Materials`), text in brackets, division labels, several roles in one
   title (keep the role at this company / the most procurement-relevant one).
   When unsure, the safe fix only (the original wording otherwise kept).

3. **Write `<run_dir>/decisions_step2.json`:**
   `{"linkedin": {"<ZoomInfo Contact ID>": {"action": "keep|blank|replace", "url": "...", "reason": "..."}},
     "email": {"<ZoomInfo Contact ID>": {"action": "keep|clear", "reason": "..."}},
     "companies": {"<name before>": "<after>"}, "titles": {"<title before>": "<after>"},
     "didero_primary_industry": {"<company name>": "Manufacturing|Distribution|Software|Services|Other"}}`

4. **Apply.** Run
   `python3 scripts/normalize.py apply --run-dir <run_dir> --decisions <run_dir>/decisions_step2.json`.
   It updates `working.csv` (names, company names, job titles, LinkedIn,
   emails, dropdown values, revenue ×1000 as `Revenue (in USD)`, websites
   cleaned, one website per company) and writes `report_step2.json`. Upload
   columns are chosen only at export. If it prints **STILL TO DECIDE**, decide
   those and re-run apply: the export refuses while any are open.
   **HubSpot values** (`scripts/hs_values.py`, written exactly as the
   properties' options, so nothing is remapped by hand):
   - **Employee range** (`hs_employee_range`): `1-10`, `11-50`, `51-200`,
     `201-500`, `501-1,000`, `1,001-5,000`, `5,001-10,000`, `10,000+`, from the
     exact employee count (e.g. 1,000 → `501-1,000`; 4,500 → `1,001-5,000`).
     With no count, ZoomInfo's range (`Employees.1000to4999`) goes to the
     HubSpot range covering most of it. **Number of Employees** gets exact
     counts only.
   - **Industry**, filled together every time the industry changes:
     company **Primary industry** (`primary_industry`: Manufacturing /
     Distribution / Software / Services / Other; column `Didero Primary
     Industry`), company **Industry** (`industry`: ZoomInfo's top level as a
     HubSpot option, e.g. Manufacturing, Retail), company **Industry group**
     (`hs_industry_group`: `Manufacturing- Building Materials`), and on the
     contact **Primary Industry**, **Primary Sub-Industry** and **Company
     Industry**. Companies the rule puts in **Other** are listed (`primary
     industry other`): decide each one (a building-supply "retailer" that
     sells to contractors is Distribution; check the website when unsure; still
     unsure → Other) in `didero_primary_industry` and re-run apply.
   **Websites** are cut back to the site itself (subpages, index pages,
   `?…` dropped: `acme.com/about/index.html` → `acme.com`), careers
   subdomains become the main site (`careers.acme.com` → `www.acme.com`), and
   link shorteners, Linktree-style pages, social profiles and job boards are
   blanked (`websites_fixed` in the report); the company's website is then
   the most common cleaned one across its rows.

5. **Report in a few lines** (counts, no stop): company names and job titles
   changed, Didero Primary Industry decisions, dropdown values with no
   matching HubSpot option, websites cleaned or blanked, name fixes, blanked
   LinkedIn URLs. The details go in `decisions.md` for the end-of-run summary.

## Step 3 — HubSpot duplicate check

Read-only, no stop. Claude never merges or edits HubSpot records: each
company and contact gets the record it should update (or none = create),
and real duplicates go on a list the user merges later (shown at step 6).
Companies first, then contacts. `S=scripts/hubspot_match.py`.

**Companies**
1. `python3 $S plan-companies --run-dir <run_dir>`
   writes `company_search_plan.json`.
2. **`hubspot-searcher`:** run the plan into `<run_dir>/hs_companies`.
   Connector mode: run each search with the connector and `ingest` each
   result (see "Connector mode" above). Token mode:
   `python3 $S run-plan --plan <run_dir>/company_search_plan.json --raw-dir <run_dir>/hs_companies`.
3. `python3 $S match-companies --run-dir <run_dir> --raw-dir <run_dir>/hs_companies`
   writes `company_matches.json` (per company: candidates with HubSpot URL,
   strength, reasons, domain, location, employees, revenue, contacts).
4. **`duplicate-reviewer`:** judge the candidates. Drop obvious false positives from free-text name
   hits (different company, different place and size). Use firmographics for
   unclear cases.
   - No candidates → `null` (Not in HubSpot).
   - Exactly one strong candidate → record it, no question.
   - Two or more real candidates (duplicates in HubSpot): use the one with
     the company's primary domain; then the most contacts; then the oldest.
     Add the group to `<run_dir>/hubspot_duplicates.json`
     (`[{"company": "...", "keep": "<id>", "others": ["<id>", ...], "why": "..."}]`)
     — the user merges them after the import; the upload updates the kept one.
   - Only a possible match (name only, different domain / place / size) →
     `null` (Not in HubSpot) unless the website or location confirms it.
   - Dismiss name-only hits that are clearly other companies (e.g. "EMSI"
     for EMS). One line per non-obvious call in `decisions.md`.
5. **Check the chosen record's values:** if its name or primary domain
   doesn't match the list (e.g. a record still named after a merged-away
   company), note it in `decisions.md`; the import mapping then suggests not
   ticking "Don't overwrite" on those columns.
6. Write `<run_dir>/company_decisions.json`
   (`{"<ZoomInfo Company ID>": {"record_id": "..." | null, "note": "..."}}`) and run
   `python3 $S apply-companies --run-dir <run_dir> --decisions <run_dir>/company_decisions.json`.
   This writes `HubSpot Company Record ID` on every row of each company.

**Contacts** — same loop:
1. `python3 $S plan-contacts --run-dir <run_dir>`
   (LinkedIn URL on `lgm_linkedinurl`, email, last name, and everyone
   associated with the list's HubSpot companies).
2. **`hubspot-searcher`:** run `contact_search_plan.json` into
   `<run_dir>/hs_contacts` (connector: search + `ingest`; token: `run-plan`).
   In connector mode, skip the last-name searches for contacts that already
   matched on LinkedIn URL or email — common surnames return hundreds of
   unrelated contacts.
3. `python3 $S match-contacts --run-dir <run_dir> --raw-dir <run_dir>/hs_contacts`
4. **Same person, different company.** A candidate with strength `review`
   matched on LinkedIn URL or email, but HubSpot has the person at a
   different company (`company_mismatch`). Decide with the enrichment data:
   if ZoomInfo / LinkedIn (this list's source) has them at the list's
   company → the list is current: record the `record_id` (the import updates
   the contact's company). If the sources disagree or point to the HubSpot
   company → `remove` the row from the list (reason "HubSpot has them at
   <company>"). One line each in `decisions.md`.
5. Judge the rest (same rules as companies: one record per person; extra
   HubSpot duplicates go in `hubspot_duplicates.json`), write
   `contact_decisions.json`, then
   `python3 $S apply-contacts --run-dir <run_dir> --decisions <run_dir>/contact_decisions.json`
   to write `HubSpot Contact Record ID` on the rows.

## Step 4 — BDR owners

Only when the end state chosen at the start includes BDR owners
(`run_setup.json` → `bdr_pool`); otherwise skip. No stop, and **nothing is
written to HubSpot**: the owners become columns in the upload files
(**Contact Owner** / **Company Owner** = the HubSpot owner ID, plus a
**… Owner Name** column for reading), so the import sets them.
`O=scripts/owners.py`.
1. `python3 $O plan --run-dir <run_dir>` → `hs_owners/plan.json`: read-only
   `query_crm_data` calls (current owners of the list's existing contacts and
   companies; contacts per owner on those companies). Run each, save the raw
   result, `owners.py ingest --run-dir <run_dir> --kind contacts|companies|incumbency --batch <i> --response <file>`.
2. `search_owners` for each BDR in `run_setup.json` → `owners.json`
   (`{"Noah": "<owner id>", …}`; a first name that matches several users →
   the active one in the BDR team; note it in `decisions.md`).
3. Open deals on the list's existing companies: `search_crm_objects` on
   DEAL associated with each company, not closed → `deals.json`
   (`{"<company record id>": [{"name", "stage", "owner"}]}`).
4. `python3 $O assign --run-dir <run_dir> --owners owners.json --deals deals.json`.
   Rules: one BDR per company with all its contacts; a company with an open
   deal keeps its owners; a pool BDR who already has contacts on the company
   gets it (most contacts wins); a company record owned by a pool BDR stays
   with them; the rest is the even split (largest company first, to the BDR
   with the fewest contacts). If the user chose another split at the start,
   decide the companies with their rule and pass `--company-assign <json>`
   (`{"<company name>": "<BDR>"}`).
5. Report the per-BDR totals in one line; `bdr_assignment.csv` (old → new
   owner per contact and company) goes to the user with the upload files.

## Step 5 — HubSpot import

`import-mapper` prepares the files and the mapping table.

**USER ACTS** — the run stops here: the user imports the files in HubSpot;
you prepare them and walk them through it.

1. **Choose Type.** Default `Prospect`. Companies that clearly aren't
   prospects (partners, vendors, existing customers in HubSpot) keep their
   HubSpot Type (suggest "Don't overwrite" on Type); note it in `decisions.md`.
2. **Settle open flags first** (`worksheet.py flags`) — export refuses
   while any row is flagged. It also refuses when step 2 never ran or left
   decisions open, or when ZoomInfo was pulled but not merged (no profile
   URLs), or when BDR owners were chosen but step 4 didn't run. It prints how
   many rows have ZoomInfo contact / company profile URLs, employee range and
   industry; show that line to the user. Dropdown values HubSpot doesn't have
   are left blank in the upload and listed (the user can add the option in
   HubSpot and re-export). Then run
   `python3 scripts/hubspot_import.py prepare --run-dir <run_dir> --raw-dir <run_dir>/hs_companies --type Prospect`.
   It sets Type on the working file and exports the two import-ready upload
   files into `<run_dir>/upload/` (blank Record ID = create a new record).
   **Format check, every run:** the export always writes the same columns in
   the same order (blank where the source had none), puts every value in the
   one format (`scripts/upload_format.py`: phones `(312) 555-0142`, websites
   `www.acme.com`, standard LinkedIn / ZoomInfo links, full country and
   US/Canada state names, digits-only numbers and IDs, HubSpot dropdown
   options, lowercase emails) and checks both files: unique emails, every
   contact's company in the company file, no website or HubSpot record on two
   companies, valid emails and links. **Any error → no files are written**:
   fix each one in the working file by the step rules (`worksheet.py set` /
   `remove`, noted in `decisions.md`) and run prepare again. Result:
   `upload/format_report.json`; show its one-line result. The import step
   can't be marked done without a passed report. It also writes
   `import_mapping.md`, `report_step4.json` and
   **`upload/HOW_TO_IMPORT.md`** (click-by-click import steps + mapping).
   **Always** send the user the two upload files, `HOW_TO_IMPORT.md` and (with
   BDR owners) `bdr_assignment.csv`, paste `HOW_TO_IMPORT.md` in the chat, and
   open the HubSpot import page in the browser. Never finish this step without
   giving the upload instructions. Then wait for the user to say it's imported.
3. The instructions cover:
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
5. **If HubSpot reports import errors** (the user tells you), tell them to either fix the
   value in the file and re-import those rows, or edit the records directly
   in HubSpot. If a dropdown value keeps failing, check the property's
   current options with the HubSpot connector (`get_properties`) and add the
   conversion to `DROPDOWNS` in `scripts/normalize.py` so step 2 fixes it
   next time.

## Step 6 — After the import

Once the user has imported both files, the files are finished. **USER ACTS**
— the run stops for the segment, and again only if the checks find
something for the user to fix. Claude only reads HubSpot.
`P=scripts/post_import.py`.

1. **`segment-guide`: build the segment** (open the segments page in the
   browser). The user creates a contact segment of the contacts they just
   imported, excluding the six exclusion lists (`exclusion_lists` in
   `config.json`; link `https://app.hubspot.com/contacts/<portal>/objectLists/<list_id>`),
   each as a "not a member of" filter:

   | Exclusion list | Link |
   |---|---|
   | Exclusion List A — Open Deals, Closed Lost Last 6 Mths, Customers, Not Persona | list 1511 |
   | Exclusion List B — Actively Worked On | list 1515 |
   | Exclusion List C — Contacts, Not ICP Companies | list 2605 |
   | Exclusion List D — Irrelevant titles (Retired, student, intern, SWE) | list 1184 |
   | Exclusion List E — Product Research Panel, Refined List | list 1633 |
   | Exclusion List F — Contacts, Vendor, Partners, Resellers | list 2613 |

   They paste the segment's link when it's done (e.g. `…/objectLists/2780/filters`).
   If the connector can read the segment's filters (read-only), check that
   all six exclusion lists are there and tell them which is missing, if any.
2. **Pull it** → `segment_snapshot.json` (every contact in the segment, its
   company associations with the primary flag, and those companies).
   - **Connector mode** — three `query_crm_data` calls, each result saved to
     a file:
     1. members: `SELECT hs_object_id, firstname, lastname, email, company_domain, hs_email_domain, associatedcompanyid FROM CONTACT WHERE hs_crm_search.ilsListIds = '<list id>' LIMIT 500`
     2. associations: `SELECT hs_object_id, associatedcompanyid, COMPANY.hs_object_id, COMPANY.name, COMPANY.domain FROM CONTACT WHERE hs_object_id IN ('<id>', …)`
        (one row per contact–company link; don't combine the list filter
        with `COMPANY.` columns — it breaks the list filter)
     3. companies: `SELECT hs_object_id, name, domain, website, city, state, country, location, phone, linkedin_company_page, numberofemployees, num_associated_contacts, type, createdate FROM COMPANY WHERE hs_object_id IN (…)`
        for every associated company, plus a second query `WHERE domain IN (…)`
        for the domains of contacts with no company.
     Then `python3 $P build-snapshot --members <1> --associations <2> --companies <3> [<3b>] --segment "<segment link>" --portal <portal id> --out-dir <run_dir>`.
   - **Token mode:** `python3 $P pull-segment --segment "<segment link>" --out-dir <run_dir>`.
3. **`association-fixer`: check associations (read-only).**
   `python3 $P review-associations --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`
   → `association_fixes.json`: contacts with **no company** (→ the company
   owning their domain, as primary) and contacts with **several companies**
   (→ the list's company primary). For `ask_user` cases (no company with that
   domain, several candidates, two companies sharing a domain) pick the one
   that matches the list's company and website. **Never send the fixes to
   HubSpot** (`connector_batches` is not used): give the user the fix list as
   a table (contact link, current companies, company to make primary, why)
   and they make the changes in HubSpot. No fixes → no stop.
4. **`leftover-duplicate-finder`: company duplicates.**
   Connector mode: `python3 $P plan-dupes --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`,
   run `dupes_search_plan.json` with the connector (search + `ingest` into
   `<run_dir>/hs_dupes`), then
   `python3 $P match-dupes --snapshot <run_dir>/segment_snapshot.json --raw-dir <run_dir>/hs_dupes --out-dir <run_dir>`.
   Token mode: `python3 $P find-dupes --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`.
   It checks every company of the segment's contacts against all of HubSpot
   (same or variant domain, same LinkedIn page, same phone, similar name in
   the same location) → `company_dupes.json`. Dismiss false positives
   yourself. Together with step 3's `hubspot_duplicates.json`, give the user
   one merge list (HubSpot links, which record to keep and why); they merge
   in HubSpot. Nothing found → no stop.

## Step 7 — Enrichment in Clay

Agent: `clay-guide`. **USER ACTS** — the user runs Clay; Claude guides.
This step happens in Clay, not HubSpot. The Clay connector can't open,
duplicate or run workbooks, so the user does it. Clay writes results back to
HubSpot itself (that's Clay, not Claude) — no files are imported or exported.

1. **First:** pick the template yourself — Europe if most contacts are in
   Europe, otherwise Americas / global — then run
   `python3 scripts/clay_guide.py --run-dir <run_dir> --list-type <path> --segment "<segment>"`
   and paste its output as it is (both template links, copy and rename, the
   tabs, the button order), saying which template you picked and why. Open
   the template in the browser.
2. **Tabs:** Tab 1 "ZoomInfo" only if the list was *not* built in ZoomInfo;
   Tab 2 "PDL" always, first; Tab 3 "Import Objects from HubSpot" always,
   after PDL. Each tab's first column: import objects → **Contacts** → the
   segment → **Manual / one-time import only**.
3. **Buttons, one at a time** (each spends Clay credits): ZoomInfo tab →
   import → **Enrich Contact** → **Update Object**; PDL tab → import →
   **Verify Email** → **Work Email** → **Enrich Person** → **LinkedIn URL** →
   **Update Object**; Import Objects tab → **Import Object** → **Mobile
   Phone** → **Update Object**. The user tells you when a column is done or
   shows an error; help with errors.
4. **End of the run** when the user says Clay is done: post the summary —
   what was decided along the way (`decisions.md`), rows removed and why,
   the HubSpot merge / association lists if any, the files delivered.

## Running ZoomInfo calls (all ZoomInfo stages)

Every ZoomInfo stage (enrich, event-list search, title search, title enrich)
runs through `scripts/zi_workers.py`. It splits the calls still to do between
sub-agents (default 4) and writes one brief per sub-agent in `zi/workers/`.
Start them **in one message**, so they run at the same time, each as
`zoominfo-puller` with the one-line brief the script prints. Each sub-agent
calls ZoomInfo, saves the raw result as returned, runs the ingest command and
replies with one line per call. Raw results never come into the main chat.
If the host has no sub-agents, work through the brief files yourself, in
order, without commenting between calls. Tell the user before starting:
"Running N ZoomInfo calls with 4 helpers in parallel."

## LinkedIn lists: ZoomInfo pull, source priority, consistency, prune

Only for lists that came through `references/screening.md` (`SKILL.md`
says when). They run after steps 1–2, then steps 1–2 run again, then 3–7.
Script: `scripts/zoominfo_merge.py`. No stops: report each stage in a line or
two and go on. Skipped entirely when ZoomInfo wasn't approved at the start
(`plan` refuses; carry on with the next stage).

**Stage 7 — ZoomInfo pull** (`zoominfo-puller`)
1. `python3 scripts/zoominfo_merge.py plan --run-dir <run_dir>`: batches of
   10 and the **maximum credits** (contacts + companies), checked against the
   cap approved at the start — within it, go on without asking.
2. **Run the calls in parallel — never one by one in the main chat** (that
   took 20–30 minutes each for contacts and companies). See "Running ZoomInfo
   calls" below: `python3 scripts/zi_workers.py --run-dir <run_dir> --job enrich`,
   then start the sub-agents it lists **all at once** (contacts and companies
   together). Re-run `zi_workers.py` when they're back; it lists anything
   missing (a refused call) and writes new briefs for just those.
3. `zoominfo_merge.py attach --run-dir <run_dir>` adds the "ZI …" columns and
   judges each match: **good** (same person, same company), **outdated** (same
   person at another company — the whole ZoomInfo record is ignored),
   **review** (name differs), **none**. Decide each review match: a nickname
   or shortened surname at the same company → treat as good
   (`worksheet.py set --row <id> --field "ZI Match=good"`); anything else →
   `none`. One line each in `decisions.md`.
   Nothing in the list's own columns changes yet.
   What ZoomInfo returns (checked on a real call): person ID (→ **ZoomInfo
   Contact Profile URL**), name, email (sometimes none), title, company +
   ZoomInfo company ID, management level, job function, phones with
   Do-Not-Call flags (a Do-Not-Call number is never copied), accuracy score,
   LinkedIn URLs. Companies: company ID (→ **ZoomInfo Company Profile URL**)
   and primary industry as [industry, sub-industry], written
   `Manufacturing- Building Materials` (the hand-cleaned format). It does **not** return the person's city /
   state / country (neither does search), so contact location stays as worked
   out from LinkedIn.

**Stage 8 — pick the source per field** — `zoominfo_merge.py merge --run-dir <run_dir>`
Rules (from the user): names → ZoomInfo; job title → LinkedIn; contact
LinkedIn URL → LinkedIn (format only); emails → every email on the company's
domains from either source, others cleared; with two, the one on the
company's most-used domain / address format is primary, the other goes in
**Additional Emails** (HubSpot "Additional email addresses"); person city/state/country → ZoomInfo when it has them;
website → ZoomInfo then cleaned; company name → ZoomInfo's when it's the same
company as LinkedIn's; company LinkedIn URL → LinkedIn; company location,
phone, industry (`Industry- Sub-industry`), size, revenue, management
level, job function, phones, ZoomInfo contact / company profile URLs →
ZoomInfo. Only "good" matches are used. Ties are flagged: decide each
(company name → the one on the company's website; otherwise the most recent
source) with `worksheet.py set` / `resolve`, noted in `decisions.md`.

**Stage 9 — consistency** — `zoominfo_merge.py consistency --run-dir <run_dir>`
1. within each contact (email on the company's domain, state vs country,
   title present); 2. across a company's contacts (company values agree, email
   domains are the company's, ZoomInfo doesn't put them at different
   companies); 3. contacts vs the company (website vs email domain, HQ vs
   contact countries, company name present). Anything flagged in
   `consistency_report.json` → decide it (the company's website and email
   domain are the tiebreak) and fix with `worksheet.py set`, noted in
   `decisions.md`.

**Stage 10 — prune** — `zoominfo_merge.py prune --run-dir <run_dir>`
Removes the ZI and helper columns (copy kept in `zi/zi_columns.csv`); lists
empty columns; run with `--drop-empty` to remove them too.

**Stage 11 — steps 1–2 again.** Before re-running, copy the first pass's
`review.json` and `review_step2.json` (e.g. to `review_pass1.json`); after
each `prepare`, run `zoominfo_merge.py diff-review --old <pass-1 file> --new <new file>`
and judge **only the new entries** — reuse the first pass's decisions for
everything else. Then steps 3–7.

## Named-contact lists: ZoomInfo search

Only for the named-contacts path (`references/event-lists.md`: attendee lists
and other lists with names and companies but no ZoomInfo / LinkedIn data).
They have no LinkedIn URL to match on, so ZoomInfo is searched first (free)
and only the matched people are enriched. Company HQ already came from
HubSpot / web research, so **no company enrichment**. Skipped when ZoomInfo
wasn't approved at the start. No stops.

**ZoomInfo** (`zoominfo-puller`)
1. `python3 scripts/zoominfo_merge.py search-plan --run-dir <run_dir>` → one
   `search_contacts` per person (name + company + company website; no credits).
   Run them in parallel: `zi_workers.py --run-dir <run_dir> --job search` and
   start the sub-agents it lists all at once (see "Running ZoomInfo calls").
2. `zoominfo_merge.py pick --run-dir <run_dir>`: a candidate with the same name
   at the same company is picked; for each **REVIEW** line decide yourself
   (same person: nickname / initial and same company or email domain → pick;
   otherwise none), write `{"<row>": "<personId>|none"}` and re-run
   `pick --decisions <file>`. Note the calls in `decisions.md`.
3. `zoominfo_merge.py plan --run-dir <run_dir> --from-picks --no-companies`
   (within the credit cap from the start), then
   `zi_workers.py --run-dir <run_dir> --job enrich` (sub-agents, in parallel)
   and `attach` exactly as in stage 7 above. People ZoomInfo couldn't match
   keep the list's own data (no LinkedIn URL search).

**Job titles on named-contact lists:** these titles vary in quality, so in
stage 8 ZoomInfo's title is used **only when it's the same job** as the list's
(then ZoomInfo's cleaner wording wins, e.g. "Dir. Procurement" →
"Director, Procurement"); a different job keeps the list's title, and
`merge_report.json` → `titles_kept` lists those. A blank title takes
ZoomInfo's.

Then stages 8–10 (source per field, consistency, prune), steps 1–2 again, and
steps 3–7. For event lists the export writes **Lead Source** = `Events` and
**Lead Source Detail 1** = the event name.

## Data handling

These files contain personal contact data. Never commit them to a repository
or publish them; keep inputs and run outputs in local, git-ignored folders.
