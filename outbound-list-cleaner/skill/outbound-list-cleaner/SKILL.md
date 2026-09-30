---
name: outbound-list-cleaner
description: Didero's outbound list workflow, end to end — clean and standardize a raw prospect list (ZoomInfo, LinkedIn, Clay, HubSpot exports) into a contact file and a matching company file, fix email domains, check HubSpot for duplicate companies and contacts, prepare the HubSpot import, fix associations and leftover duplicates after import, guide the Clay enrichment, and assign BDR owners. Use whenever someone gives you a raw contact or company export to clean or prepare for HubSpot, asks to dedupe a list against HubSpot, prepare or check an import, run the Clay enrichment step, or assign a new list to BDRs.
---

# Outbound list cleaner

## Steps and sub-agents

The table is the source of truth for the **order** of the workflow. When a
step or sub-skill is added, insert it here and renumber — the step sections
below follow this order. The workflow ends after the last step. Ask the user
which step to start from if it isn't clear (e.g. a list that is already
imported starts at step 4's post-import part).

| # | Step | Sub-agents | Scripts | The user decides / confirms |
|---|---|---|---|---|
| 1 | Email domain cleaning | `domain-judge` — judges each company/email-domain pair · `web-domain-finder` — finds public inboxes for companies with no email | `email_domain.py` | doubtful domains, parent/child cases |
| 2 | Normalization | `name-and-linkedin-checker` — judges LinkedIn slugs and emails against names | `normalize.py` | last-name mismatches |
| 3 | HubSpot duplicate check | `hubspot-searcher` — runs the search plan · `duplicate-reviewer` — judges candidates, prepares merge questions | `hubspot_match.py` | merges (done in HubSpot) and survivor IDs |
| 4 | HubSpot import and post-import checks | `import-mapper` — mapping table · `segment-guide` — exclusion lists and segment link · `association-fixer` — primary company fixes · `leftover-duplicate-finder` | `hubspot_import.py`, `post_import.py` | the import, the segment and its exclusion lists, association fixes, merges |
| 5 | Clay enrichment (guided) | `clay-guide` — walks the user through the workbook | — | template, button runs, "enrichment done" |
| 6 | BDR assignment | `hubspot-bdr-list-assignment` (skill) · `bdr-assigner` — applies this workflow's rules | `bdr_assign.py` | BDR pool, approval of the CSV |

All steps read and update the one working file through `worksheet.py`
(see "One working file").

Sub-agents are roles. Where the host supports subagents (Cowork, Claude
Code), run the heavy ones — `web-domain-finder`, `hubspot-searcher`,
`leftover-duplicate-finder` — as subagents so raw results stay out of the
chat; run the others inline. Name the sub-agent when you start its work
("Step 3 · hubspot-searcher: …") so the user can follow along.

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

Decision boxes can't hold links, so list the linked records in a message
right before the question. The scripts put a `url` on every record they
report; use it.

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
  common value is used; tell the user what was harmonized
  (`init_report.json`).
- **Company values are company-wide:** the scripts write company fields
  (domain, record ID, website, Type …) to every row of that company.
- **No hand edits — ever.** The user never edits the CSV, and you never edit
  it except through `worksheet.py` or a step's `apply` command.
- **Flags, never silent drops.** When a row needs the user's judgment (e.g.
  HubSpot has the person at another company), it is flagged (`Flag`,
  `Flag Reason` columns) — never removed or changed on your own:
  1. Pull the row out and show it in the chat window:
     `python3 scripts/worksheet.py show --run-dir <run_dir> --row <id> --columns "<the relevant columns>"`
     (a markdown table), with the HubSpot links of the records involved.
  2. Ask the user what should change (multiple-choice tool where the options
     are clear; otherwise let them say it).
  3. Apply exactly that with `worksheet.py set --row <id> --field "Column=value" … --reason "…"`,
     or `resolve --row <id> --note "…"` if it stays as it is, or — only if
     the user explicitly says so — `remove --row <id> --reason "…"`.
  4. **Show the change again** (the before → after table the command prints,
     or `show` the row) and wait for the user's OK **before** continuing to
     the next step.
  `python3 scripts/worksheet.py flags --run-dir <run_dir>` lists open flags.
- **History:** after each step a read-only copy is saved in `history/`
  (`01_email_domains.csv`, `02_normalize.csv`, …); every change is logged in
  `changes.jsonl`. Never read the history copies back as input.
- **Output:** the two upload files — a contact file and a company file with
  only the list's companies (a sublist gets its own pair) — are generated at
  step 4 into `upload/` by `worksheet.py export`, and never edited. Export
  refuses while any row is still flagged, and lists any rows the user chose
  to remove so the list's owner can be told.

## Before you start (do this first, every run)

1. **Model check.** This workflow needs a top-tier model: Opus 5 (any 5.x)
   or Fable. Older or smaller models tend to take shortcuts on the judgment
   calls. Before running any step, tell the user this, and if you are not
   running on Opus 5.x or Fable, stop and ask them to switch models (e.g.
   `/model` in Claude Code, or the model picker in Cowork) and start again.
2. **First-time connector check (manual, one-time).** Check which
   connectors this session has, by looking at your available tools:
   - **HubSpot connector — required.** Tools like `search_crm_objects`,
     `query_crm_data`, `manage_crm_objects`.
   - **Web search — required** for step 1's `web-domain-finder`.
   - Clay and ZoomInfo connectors — optional (step 5 is manual either way).
   If a required one is missing, stop and tell the user plainly: **connectors
   can't be added from inside Cowork or this chat — this is a real
   limitation.** They have to open Claude's settings (Settings → Connectors),
   connect HubSpot (and turn on web search if it's off), then start a new
   session. It's a one-time setup: once connected, every future session has
   it and the rest of the workflow runs without this step.
3. **Mode: connector mode is the normal way to run.** Everything in this
   workflow works through the HubSpot connector alone ("connector mode"):
   the scripts plan the HubSpot searches, the `hubspot-searcher` sub-agent
   runs them with the connector, and `hubspot_match.py ingest` turns each
   saved result into the files the scripts read — nothing is typed out by
   hand. Say once at the start: "Running in connector mode."
   A **HubSpot private app token** is an optional speed-up for large lists
   (hundreds of companies: seconds instead of minutes). Only offer it where a
   script can read it — Claude Code on the user's computer, or Cowork with a
   shared folder; never in claude.ai chat, where it can't work. Check with
   `python3 scripts/hubspot_match.py check-token`; if it passes, say
   "Running in token mode" and use the token commands. To set one up (only if
   the user wants it):
   1. Explain: the script reads HubSpot companies, contacts and lists with
      their team's private app (read scopes `crm.objects.companies.read`,
      `crm.objects.contacts.read`, `crm.lists.read`); the token stays on
      their device and is never shown in chat. Ask for consent with the
      multiple-choice tool.
   2. **Claude Code on their computer:** run
      `python3 scripts/hubspot_match.py setup-token --open-terminal`; they
      paste the token in the terminal window (hidden input).
      **Cowork with a shared folder:** they save the token alone in
      `hubspot_token.txt` in that folder; then run
      `python3 scripts/hubspot_match.py setup-token --from-file <path> --authorized`
      (checks it, stores it privately, deletes the text file).
      **Claude Code on the web:** an environment variable
      `HUBSPOT_PRIVATE_APP_TOKEN` in the environment's settings.
   **Never** ask for the token in chat, and never read, print or open the
   token file. If a token is pasted into the chat anyway, don't use it; tell
   the user to rotate it in HubSpot.

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
   - Anything doubtful → ask the user (step 3).
   If the ZoomInfo company name looks unrelated to the domain, check what
   company the domain actually belongs to before calling it a mismatch.

3. **Ask the user about doubtful rows** (list each company with its HubSpot link if it has one). Use the multiple-choice question tool
   (up to 4 questions per call; batch in rounds). For each row show: company,
   email domain, number of contacts, other domains at that company, why you
   think it does/doesn't match, and any parent/child relationship. Offer
   options such as keep / clear / map to parent, with your recommendation
   first. Treat free-text answers as rules to apply going forward.

4. **`web-domain-finder`: web backfill.** For each company with no email at all, search the web for
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
   `python3 scripts/email_domain.py apply --run-dir <run_dir> --decisions <run_dir>/decisions.json`.
   It updates `working.csv`: `Email Address`, `Email Domain`, and on every
   row of each company `Company Domain` (most used) and `Additional Domains`
   (`;`-separated). What changed and why is in `step1_report.json`.

7. **Report** counts (own email / backfilled / web / cleared / fixed) and any
   company still without a domain.

## Step 2 — Normalization

Output files contain only upload columns: never add notes or flag columns.
Everything the user needs to review goes in the chat.

1. **Prepare.** Run
   `python3 scripts/normalize.py prepare --run-dir <run_dir>`.
   It fixes name casing and strips credentials, and writes
   `review_step2.json` listing LinkedIn URLs whose slug doesn't contain the
   contact's first and last name.

2. **`name-and-linkedin-checker`: judge each LinkedIn slug** (no live check):
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
   `python3 scripts/normalize.py apply --run-dir <run_dir> --decisions <run_dir>/decisions_step2.json`.
   It updates `working.csv` (names, LinkedIn, emails, dropdown values,
   revenue ×1000 as `Revenue (in USD)`, `Employees.` prefix stripped,
   industry combined, one website per company) and writes
   `report_step2.json`. Upload columns are chosen only at export.

5. **Report in chat:** dropdown values with no matching HubSpot option
   (`dropdown_values_not_matching`, e.g. a Management Level or Department
   value HubSpot's dropdown doesn't have), name fixes, blanked LinkedIn URLs (name, company,
   removed URL, reason), and the user's last-name decisions.

## Step 3 — HubSpot duplicate check

Claude cannot merge HubSpot records; the user merges manually and then tells
you the survivor. Companies first, then contacts. `S=scripts/hubspot_match.py`.

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
   - Two or more real candidates, or only a possible match → review with the user.
5. **Review with the user**, one company at a time:
   - In a chat message, list each candidate: HubSpot link, name, domain,
     location, contacts, created date, and why it matches.
   - Tell the user to open them and merge the duplicates in HubSpot
     themselves, one by one, into the record they want to keep.
   - Then ask with the multiple-choice tool: "After merging, which record
     survived?" Merging in HubSpot usually creates a **new record ID**, so the
     user typically types it under "Other"; offer "Not a duplicate / keep
     separate" where relevant. Up to 4 companies per call.
   - **Verify:** search `hs_object_id IN [new ID + old IDs]` with
     `hs_merged_object_ids`. The survivor must exist and list the merged-away
     IDs; if the old IDs still come back on their own, the merge isn't done —
     tell the user and ask again.
   - **Check the survivor's values:** HubSpot may keep the other record's
     name or domain (e.g. SRS Distribution merged into a record still named
     "Superior Distribution"). If the survivor's name or primary domain
     doesn't match the list, tell the user to fix it in HubSpot or to leave
     "Don't overwrite" unticked for those columns on import.
   - Dismiss name-only hits that are clearly other companies (different
     place and size, e.g. "EMSI" for EMS) without asking.
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
4. **Same person, different company → flag.** A candidate with strength
   `review` matched on LinkedIn URL or email, but HubSpot has the person at a
   different company than the list (`company_mismatch`). Don't drop it: give
   the row `"flag": "<reason>"` in `contact_decisions.json` (with its
   `record_id`), then handle it with the flag workflow ("One working file"):
   show the row next to the HubSpot contact (company linked, job title,
   location) and ask what should change —
   - **List is current** → `resolve` (the import updates the contact);
   - **HubSpot is current** → the user says what to change (e.g. set the
     row's company to the HubSpot one) and you `set` it, or — only if they
     say so — `remove` the row;
   - **Unsure** → leave it flagged and move on; export will stop until it's
     settled.
5. Judge the rest, review with the user (same merge-first flow), write
   `contact_decisions.json`, then
   `python3 $S apply-contacts --run-dir <run_dir> --decisions <run_dir>/contact_decisions.json`
   to write `HubSpot Contact Record ID` (and any flags) on the rows.

## Step 4 — HubSpot import

`import-mapper` prepares the files and the mapping table.

The user runs the import in HubSpot; you prepare it and walk them through it.

1. **Choose Type.** Default `Prospect`. Look at the list: if the companies
   don't look like prospects (partners, vendors, existing customers), ask the
   user which Type fits before continuing.
2. **Settle open flags first** (`worksheet.py flags`) — export refuses
   while any row is flagged. Then run
   `python3 scripts/hubspot_import.py prepare --run-dir <run_dir> --raw-dir <run_dir>/hs_companies --type Prospect`.
   It sets Type on the working file, exports the two import-ready upload
   files into `<run_dir>/upload/` (blank Record ID = create a new record),
   and writes `import_mapping.md` and `report_step4.json`. Send the user the
   two files in `upload/` — those are what they import.
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

## Step 4 (after the import) — segment, associations, leftover duplicates

Once the user has imported both files, the files are finished: from here
on the work happens in HubSpot and the files are not updated again.
`P=scripts/post_import.py`.

1. **`segment-guide`: build the segment.** Ask the user to create a
   contact segment of the contacts they just imported, excluding the six
   exclusion lists. Show them in chat as a table, each name linked to the list
   (`exclusion_lists` in `config.json`; link
   `https://app.hubspot.com/contacts/<portal>/objectLists/<list_id>`):

   | Exclusion list | Link |
   |---|---|
   | Exclusion List A — Open Deals, Closed Lost Last 6 Mths, Customers, Not Persona | list 1511 |
   | Exclusion List B — Actively Worked On | list 1515 |
   | Exclusion List C — Contacts, Not ICP Companies | list 2605 |
   | Exclusion List D — Irrelevant titles (Retired, student, intern, SWE) | list 1184 |
   | Exclusion List E — Product Research Panel, Refined List | list 1633 |
   | Exclusion List F — Contacts, Vendor, Partners, Resellers | list 2613 |

   Tell them to add each as a "not a member of" filter and to check
   themselves that all six are applied — you don't verify membership against
   the lists.
2. **Get the segment link.** Ask the user to paste the segment's HubSpot link
   (e.g. `…/objectLists/2780/filters`). Then ask with the multiple-choice
   tool: "Are all six exclusion lists applied to this segment?" (Yes / Not
   yet). Don't continue until they answer Yes.
3. **Pull it** → `segment_snapshot.json` (every contact in the segment, its
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
4. **`association-fixer`: fix associations** (Claude proposes, user approves, Claude applies):
   `python3 $P review-associations --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`
   → `association_fixes.json`:
   - **No company** → associate with the company that owns the contact's
     domain, as primary.
   - **Several companies** (usually an existing contact that got another
     company) → make the company owning the contact's domain (the list's
     company) primary; the others stay as secondary.
   - `ask_user`: cases the script can't decide (no company with that domain,
     several candidates). Ask the user with the multiple-choice tool, one
     contact per question, with contact and company links.
   Show the proposed fixes as a table (contact, email, current companies,
   action, company, reason) and get approval, then send `connector_batches`
   with the connector's `manage_crm_objects` (`updateRequest`, 10 per call).
   The "Primary" label works through the connector (tested). The contact's
   `associatedcompanyid` takes about a minute to reflect it — wait before
   re-checking. Afterwards re-run `pull-segment` + `review-associations` to
   confirm nothing is left. Two companies can share a domain (e.g. Roche and
   Genentech on `roche.com`); the script then asks the user rather than
   guessing.
5. **`leftover-duplicate-finder`: leftover company duplicates.**
   Connector mode: `python3 $P plan-dupes --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`,
   run `dupes_search_plan.json` with the connector (search + `ingest` into
   `<run_dir>/hs_dupes`), then
   `python3 $P match-dupes --snapshot <run_dir>/segment_snapshot.json --raw-dir <run_dir>/hs_dupes --out-dir <run_dir>`.
   Token mode: `python3 $P find-dupes --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`.
   Either way it checks every company associated with the segment's contacts against all
   of HubSpot: same or variant domain (other TLD, subdomain, hyphen), same
   LinkedIn page, same phone, similar name in the same location (state codes
   and names treated as equal, e.g. TX = Texas) → `company_dupes.json`.
   Tell the user how many companies have possible duplicates, then list each
   group in chat with HubSpot links, location, size, contacts and reasons.
   Dismiss obvious false positives yourself. The user merges in HubSpot and
   gives the survivor ID (usually a new ID); verify via
   `hs_merged_object_ids` and check the survivor's name/domain, as in step 3.

## Step 5 — Enrichment in Clay (user-run, guided)

Sub-agent: `clay-guide`.

Assumes the segment exists, duplicates are merged and every contact is
associated with its company. This step happens in Clay, not HubSpot. The
Clay connector can't open, duplicate or run workbooks, so the user does it
and you walk them through it one tab at a time. Clay writes results back to
HubSpot itself — no files are imported or exported, and you don't need to
check HubSpot afterwards.

1. **Workbook.** Give the user **both** template links from `config.json`
   (`clay_workbooks`) with what each is for, and let them decide which to
   open:
   - Europe template — European contacts (often missing from ZoomInfo).
   - Americas/global template — American and other global contacts
     (providers proven for those regions).
   The links are the live templates: the user **duplicates** the one they
   chose and **renames the copy** as `name_segment_date`. If you're unsure
   what the name should be, let the user name it. All work happens in the
   copy — never run buttons in the template. Whenever the user gets lost,
   send both links again. Remind them each button run spends Clay credits.
2. **Tabs:**
   - **Tab 1 "ZoomInfo"** — only if the list was *not* built in ZoomInfo
     (e.g. pulled from LinkedIn). Skip it for ZoomInfo lists.
   - **Tab 2 "PDL"** — always; the most reliable provider, so it runs first.
   - **Tab 3 "Import Objects from HubSpot"** — always, after PDL; a mix of
     other providers for what PDL didn't find.
3. **Importing into a tab** (first column of each tab): import objects →
   select **Contacts** → select the segment → schedule **Manual / one-time
   import only**, so the list doesn't keep updating in the background.
4. **Walk the user through the buttons, one at a time.** Wait for each
   column to finish before the next; ask them to confirm, and to tell you
   about errors.
   - **ZoomInfo tab** (only when used): import the segment → **Enrich
     Contact** → **Update Object**.
   - **PDL tab:** import the segment again → **Verify Email** → **Work
     Email** → **Enrich Person** → **LinkedIn URL** → **Update Object**.
   - **Import Objects from HubSpot tab:** **Import Object** → **Mobile Phone**
     enrichment → **Update Object**.
5. **Gate before step 6.** Ask with the multiple-choice tool whether all the
   enrichments are done (Update Object has run on every tab used). Do not
   start step 6 until the user confirms. If some contacts didn't change,
   that's fine — the user ran it.

## Step 6 — Assign BDRs (contact and company owners)

Starts only after the user confirmed step 5. Use the
**`hubspot-bdr-list-assignment`** skill on the step 4 segment, with the
rules below. Where this section and that skill differ, **this section wins**.

**Only for BDRs.** This step assigns BDRs only. If the user wants to assign
anyone else (AEs, managers, …), say this workflow doesn't cover it and stop.

1. **Ask who the BDRs are** for this round. Default pool: `bdr_pool` in
   `config.json` (currently Noah, Davis, Bart). Everyone must already be a
   HubSpot user; resolve each to an owner ID (`search_owners`) and confirm
   any first name that matches more than one user.
2. **No HubSpot changes until approval.** Everything up to the approval
   is read-only; results go to the user as a CSV file in chat.
3. **Read the current owners:** contact owner of every contact in the
   segment, and company owner of every company associated with them.
4. **Count the whole account.** For each of those companies, count all the
   contacts associated with it in HubSpot and who owns them.
5. **Contacts in the segment:** if a contact is already owned by one of the
   selected BDRs, that BDR is its starting owner. Any other owner (a
   non-BDR, or nobody) → it needs a BDR.
6. **Combine the counts per company:** (a) BDR owners of the segment's
   contacts on that company **plus** (b) BDR owners of the company's other
   contacts. Only owners in the selected pool count; contacts owned by
   anyone else don't. (This differs from the base skill, which subtracts the
   in-list contacts: here they count.)
7. **One BDR per company — the priority rule.** The BDR with the most
   contacts on the company (from 6) gets **all** of the segment's contacts
   on it **and** the company record. Example: Bart already owns 2 contacts
   at a company; the 3 new contacts would have gone 2 to Bart and 1 to Noah
   → all 3 go to Bart, and so does the company. Ties: lightest load, as in
   the base skill. The company owner is what tells future imports who
   should get that company's new contacts.
8. **Companies with no BDR contacts yet:** keep the company with a pool BDR
   who already owns the company record; otherwise distribute them so that,
   across this list, each BDR ends up with a roughly equal number of
   **contacts**, and then of **companies**. To balance, you may move the
   segment's new contacts on such companies between BDRs (the whole company
   moves together), but never split a company.
   **Companies already worked by a BDR stay locked** (their other contacts
   are BDR-owned) — that's the priority. Only if, after balancing, the gap
   between the most- and least-loaded BDR is **more than 10% of the average
   contacts per BDR and more than 3 contacts** (`bdr_balance_flag` in
   `config.json`), point it out in chat and suggest specific locked
   companies that could move to even it out: company, contacts in the
   segment, how many other contacts the current BDR owns there, and who'd
   take it. Moving one means its other BDR-owned contacts move too, so the
   company stays with one BDR. The user decides company by company; apply
   only the ones they approve, then re-deliver the CSV.
9. **`bdr-assigner`: build the CSV with the script.** Pull the inputs with the connector
   (read-only), then run `scripts/bdr_assign.py`:
   - contacts: `query_crm_data` —
     `SELECT hs_object_id, firstname, lastname, hubspot_owner_id, associatedcompanyid, … FROM CONTACT WHERE hs_crm_search.ilsListIds = '<list id>' LIMIT 500`
     (pad the SELECT so the result spills to a file; parse it into
     `{id: properties}` JSON; check the count against `COUNT(*)`);
   - companies: `get_crm_objects` on the unique `associatedcompanyid`s
     (≤100 per call) → TSV `id, name, owner_id, domain`;
   - incumbency: `SELECT associatedcompanyid, hubspot_owner_id, COUNT(*) FROM CONTACT WHERE associatedcompanyid IN (…) GROUP BY associatedcompanyid, hubspot_owner_id`
     → TSV `company_id, owner_id, count` (segment contacts included);
   - owners: `search_owners` → `{owner_id: name}` JSON;
   - deals: `search_crm_objects` on DEAL `associatedWith` the companies;
     resolve stage names with `SELECT dealstage, COUNT(*) FROM DEAL … GROUP BY dealstage`.
   `python3 scripts/bdr_assign.py --contacts … --companies … --incumbency … --pool "Noah=<id>,Davis=<id>,Bart=<id>" --owners … --out-dir <run_dir>`
   writes `bdr_assignment.csv` — columns `Company, Company Record ID, Old
   Company Owner, New Company Owner, Contact Name, Contact Record ID, Old
   Contact Owner, New Contact Owner, Reason`, sorted by company A→Z with each
   company's contacts adjacent and A→Z — and `bdr_summary.json`. Deliver the
   CSV with `SendUserFile`; in chat give only: per-BDR totals (contacts,
   companies), how many contacts and company records change hands and from
   whom, companies moving between BDRs, ties, imbalance suggestions, open
   deals on these companies with stage, amount and owner (their companies
   would move to a BDR — the user's call), and company records that are
   really personal mailboxes (Gmail, Hotmail, 139.com …) to fix.
10. **Ask for approval or changes.** On changes, re-deliver the CSV.
11. **On approval, update HubSpot** as the base skill describes: contacts
   first, then companies, owner only, 10 per call, then verify every record.

## Data handling

These files contain personal contact data. Never commit them to a repository
or publish them; keep inputs and run outputs in local, git-ignored folders.
