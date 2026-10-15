# Outbound list cleaner — project status & plan

Handoff doc for new chats (Claude Code or Cowork). Read this first, then
`SPEC.md` for the detailed rules.

## Goal

Python scripts + a Claude skill that turn any outbound list export (ZoomInfo,
Clay, HubSpot, lemlist) into Didero's standard HubSpot upload format: **two
files per list** — contacts, and the companies of those contacts. Claude
handles the judgment calls and web lookups; the user makes the final decision
on unclear rows through multiple-choice prompts in chat.

## Layout

| Path | What |
|------|------|
| `SPEC.md` | Process spec and confirmed decision rules — source of truth |
| `skill/didero-outbound-lists/` | The one skill (merged 2026-10-02 from outbound-list-cleaner, linkedin-list-screening, event-list-intake and the orchestrator): SKILL.md (list type + order), references/ (zoominfo-lists, screening, event-lists), scripts/, config.json. Zip this folder to install in Cowork |
| `skill/didero-outbound-lists/scripts/email_domain.py` | Step 1 script (`prepare` / `apply`) |
| `samples/MANIFEST.md` | What each sample file is. **Sample data is local-only, never committed** |
| `runs/` | Run outputs (git-ignored; contain personal data) |

## Status

| Step | State |
|------|-------|
| Sample files (5) collected | Done (local only; the repo is public) |
| Step 1 — Email domain cleaning | **Built and tested** on the CBM M&A raw contact file: 170/170 contacts got a domain; 4 review questions put to the user; rules from the answers folded into SPEC.md |
| Step 2 — Normalization (names, LinkedIn, company fields, column pruning) | **Built and tested** on CBM M&A: output matches hand-cleaned files 4/5 except where confirmed rules differ |
| Step 3 — HubSpot duplicate check | Companies done on CBM M&A (47/59 match the hand file; the rest explained by today's import and 3 merges). Contacts next |
| Step 4 — HubSpot import prep (mapping table, Type, record IDs) | Built; dry-run OK |
| Step 4 (after import) — segment + exclusions, association fixes, leftover duplicates | Built; untested against HubSpot (needs the token) |
| Step 5 — Clay enrichment (guided checklist, user confirms before step 6) | Built |
| Step 6 — BDR assignment (hubspot-bdr-list-assignment + bdr_assign.py) | Tested up to the CSV on list 2759: 81 contacts / 72 companies, 27 contacts each |
| **End of workflow** | No step 7 |

## Next up

1. User walks through the next step of the manual process; add it to
   `SPEC.md`, then build it.
2. Once the pipeline is complete, compare its output against the hand-cleaned
   samples (files 4 and 5) column by column.

## LinkedIn list flow (agreed with the user, 2026-10-01)

0. Orchestrator: identify the list type first — ZoomInfo / LinkedIn (Sales
   Nav or Evaboot) / event list — and confirm with the user. Event lists:
   separate flow, designed later. Evaboot's Matches Filters / No Match
   Reasons columns are ignored.
1. linkedin-list-screening: load → **multiple jobs** (contacts with
   `Current Jobs Number` > 1; the other jobs aren't in the file, so the user
   checks each LinkedIn profile via an "Open LinkedIn" button and sets the real
   title + company; next contact follows) → company review (based/present in)
   → contact review.
2. Title + company name cleaning (new; name cleaning reuses normalize.py).
3. Hand-off into outbound-list-cleaner's working file (contacts + companies).
4. outbound-list-cleaner steps 1–2 only.
5. ZoomInfo pull (enrich_contacts / enrich_companies, 10 per call, Bulk
   Credits; tell the user the maximum credits first). Good matches' data go in
   separate ZI columns.
6. Source priority per field (user's rules: names ZI; contact LinkedIn URL
   LinkedIn, format only — no live check; emails both if domain matches the
   company, else cleared, majority domain preferred; website ZI then cleaned —
   no shorteners/linktree/careers/subpages; company name ZI only if it matches
   the LinkedIn company after the multiple-jobs step, otherwise the whole ZI
   record is distrusted; company LinkedIn URL LinkedIn; person/company
   location: ZoomInfo's person city/state/country when ZoomInfo has them;
   otherwise inferred from the LinkedIn location, filling only what's certain
   (metro area → its main city + state + country) — screen.py/location.py.
   Note: the ZoomInfo connector's enrich_contacts doesn't return a person's
   location; check whether search_contacts does (one test search, with the
   user's OK); job title LinkedIn (more current), as long as the
   LinkedIn company is the target company after the multiple-jobs step,
   otherwise flag).
7. Consistency: within contact → across contacts of a company → contacts ↔
   companies. Ties go to the user.
8. Prune columns.
9. outbound-list-cleaner steps 1–2 again (full re-run: company domains are
   re-decided from all emails incl. ZoomInfo's), showing the user only what
   changed since the first pass; earlier decisions are kept.
10. outbound-list-cleaner steps 3–6 (HubSpot duplicates, import, Clay, BDRs).

Build status (2026-10-02): every LinkedIn stage is built — orchestrator
(list type), screening steps 1–7 (load, multiple jobs, research, geography,
review page, title/company cleaning, hand-off), outbound-list-cleaner
`zoominfo_merge.py` (stages 7–10, diff-review for stage 11). Tested on the
Sales Nav sample with simulated ZoomInfo answers; the first real ZoomInfo run
still needs checking (response shape, person location fields). Open: where a
second matching email goes in HubSpot ("Secondary Email" column for now, not
in the upload yet); event-list flow (user to design).

## Event list flow (agreed with the user, 2026-10-02)

Only lists where the people are already named (attendees, speakers,
registrants). Company-only event lists (exhibitors/sponsors → find who to
contact) are a separate skill, not built yet. Flow: orchestrator (type) →
event-list-intake (all sources; screenshots of dropdowns / contact pages /
sub-pages instead of clicking through; first/last/title/company; website then
HQ by web research only) → linkedin-list-screening (company + contact review,
`--event`, `--skip-contact-geo`; title/company cleaning; hand-off
`--list-type Event`) → outbound-list-cleaner steps 1–2 → ZoomInfo free search
→ pick (unclear → user) → enrich picked only, no company enrichment → LinkedIn
URL finder page for the unmatched (can't find = stays unenriched) → stages
8–10 → steps 1–2 again → steps 3–6 (existing record IDs in the upload; Event
Name exported as Lead Source = Events + Lead Source Detail 1 = event name).
Tested on a fictional 6-person list.

## Company-only event lists (agreed 2026-10-02)

event-list-intake company_list.py / titles.py: collect companies (+titles) →
web research for every company (re-check list values; employees/revenue exact
numbers in HubSpot number format, ranges as written) → drop non-target
countries (asked each run) → clean names (fields.py rules) → branch A (no
titles): ZoomInfo upload CSV (7 columns) + guide page (filters asked each run;
defaults Director+, include procurement/supply-chain words, exclude
sales/marketing/HR/talent/people…; select → Excel → Suppression button → 4 per
company by seniority) → export processed as a normal ZoomInfo list +
tag-event; branch B (titles, no names): ZoomInfo search per title → user
always chooses → finder page (LinkedIn URL + typed name) → enrich → contact
file → outbound-list-cleaner. Event contact lists: ZoomInfo title only when
it's the same job. Tested with fictional data.

## Cowork test feedback (2026-10-02)

1. **List type:** `detect_list_type.py` reads the first rows too and returns a
   confidence. High → Claude announces the type and carries on (the user can
   correct it); only low confidence is asked.
2. **Requirements check, logged:** `scripts/preflight.py` runs right after
   Step 0 on every run. Script checks + model/connectors reported by Claude
   → run folder, `~/.didero-outbound-lists/preflight.jsonl`, and the team
   log (Supabase `preflight_runs`, insert-only key in git-ignored
   `backend.json`). Setup: `setup/RUN_LOG_SETUP.md` + `setup/preflight_log.sql`.
   Waiting on: restoring the Supabase project, running the SQL, the key, and
   allowing `*.supabase.co` in Cowork.
3. **Event in HubSpot:** Lead Source (`lead_source`) = `Events`, Lead Source
   Detail 1 (`lead_source_detail_1`) = event name, written by the export.
4. **Company data from HubSpot first:** `scripts/hubspot_companies.py`, used by
   both event list kinds. It runs bulk `query_crm_data` (exact name / domain,
   then name LIKE main word), fills website/HQ/employees/revenue/record ID,
   and asks about ambiguous matches. Web research covers only the rest.
   Tested against the live HubSpot: Lawson Products, A O Smith, Orgill found.

## Cowork test feedback (2026-10-06)

1. **ZoomInfo too slow** (20–30 min each for companies and contacts):
   `scripts/zi_workers.py` splits the remaining calls into briefs for 4
   sub-agents started at once (contacts and companies together). Raw results
   stay out of the main chat. Used by every ZoomInfo stage. Responses are
   smaller too (only the fields the merge uses).
2. **Industry used ";"**: enrichment returns primaryIndustry as [industry,
   sub-industry] (checked on a real call). Now written
   `Manufacturing- Building Materials` like the hand-cleaned files.
3. **ZoomInfo profile URLs missing**: built from the person `id` /
   company `id` (or the contacts' zoominfoCompanyId):
   `https://app.zoominfo.com/#/apps/profile/person/<id>` and `/company/<id>`.
   Also found: the Do-Not-Call flags were never requested, so the "never copy
   a DNC number" rule couldn't work. Now requested.
4. **Clay step had no links/instructions**: `scripts/clay_guide.py` prints the
   checklist from config (both templates, copy/rename, tabs, buttons). SKILL.md
   makes running it the first thing in step 5.
5. **No upload instructions**: `hubspot_import.py prepare` writes
   `upload/HOW_TO_IMPORT.md` (click-by-click import + mapping tables). It must
   be sent and pasted at step 4.

## Cowork test feedback (2026-10-13)

1. **Other list types:** detect_list_type says "unknown" → Claude asks what the
   data is for and how to handle any contacts in it; prospects to import run
   the shared steps (`progress.py start --list-type other`).
2. **Never import through the connector (MCP):** rule in SKILL.md and in
   every `progress.py next` output. The connector reads only, plus the
   approved association fixes (step 4) and owner updates (step 6).
3. **Holding the skill all chat:** `scripts/progress.py` keeps the step order
   in progress.json, prints each step's instructions fresh from the reference
   pages when the step starts, and refuses `done` out of order.
4. **Open HubSpot in the browser window:** at the start, and on every step
   where the user works in HubSpot (`progress.py next` lists the pages).
5. **Employee range = HubSpot's options** (`1,001-5,000`, not `1000-5000`):
   `scripts/hs_values.py`, from the count; ZoomInfo range only if there's no count.
6. **Industry fills every property:** company Primary industry
   (Manufacturing/Distribution/Software/Services/Other), Industry, Industry
   group; contact Primary Industry, Primary Sub-Industry, Company Industry.
   Works from ZoomInfo or LinkedIn industry names; "Other" ones are decided by
   Claude/the user in decisions_step2.json. Dropdown values HubSpot lacks
   are blanked in the upload and listed (options in config.json `hubspot_options`).
7. **ZoomInfo URLs missing:** the scripts produce them (tested on the real
   ZoomInfo reply); the run had skipped the merge. The export now refuses when
   ZoomInfo was pulled but not merged, and prints URL counts.
8. **Cleaning skipped:** company names and job titles are now cleaned in
   step 2 (every list type) next to contact names; the export refuses if
   step 2 didn't run or left decisions open.

## v2 (2026-10-15): start questions, then independent

`skill/didero-outbound-lists/`, same skill name as v1 so it replaces it in Cowork (v1 moved to `skill/archive/didero-outbound-lists-v1/`). Goal: the user gives the
file, answers everything at the start, and the run is independent.
- **Checks (only reasons to stop before starting):** HubSpot + ZoomInfo
  connected; Opus 5.5 or newer (Fable passes). `preflight.py`.
- **Claude determines** the list type and path from the columns:
  zoominfo / linkedin / contacts (`setup.py start`). Company-only lists →
  didero-contact-sourcing.
- **Start questions, one call:** end state (upload files, or + BDR owners —
  even split with accounts kept together, or the user's own split);
  countries (US + Canada / US, CA, UK, IE, AU, NZ / typed), companies by HQ or
  presence first, then contacts; BDRs; ZoomInfo credit cap. `setup.py save`
  → `run_setup.json`.
- **Stops only where the user acts:** import, segment (+ fix lists from the
  read-only checks), Clay. All OK gates, review pages, the multiple-jobs page
  and the LinkedIn finder page are gone; Claude's calls go to `decisions.md`.
- **Claude never writes to HubSpot** (manager's rule): owners are upload
  columns (Contact Owner / Company Owner = HubSpot owner ID, plus name
  columns), assigned before the import by `owners.py`; association fixes and
  duplicate merges are lists for the user.
- Duplicates at step 3: Claude picks the record (primary domain, most
  contacts, oldest) and lists the rest for the user to merge after import.
- Not yet tested in Cowork. To check on the first import: HubSpot accepts the
  owner ID in the owner columns.

**Upload format (2026-10-15):** colleagues got inconsistent files. `scripts/upload_format.py`,
run by `worksheet.py export`, never stops the run: fixed column set and order; safe
normalization (phones, websites, LinkedIn / ZoomInfo links, countries, US/CA states, numbers,
IDs, emails); rules (from the user): duplicate email → keep the closer name match, then more
data, drop the other (same person → combined); invalid email → blank only if no domain; Sales
Nav links fine; one website / HubSpot record on two companies → one company; any other invalid
value → blank cell; websites + domains filled on both files. Fixes go to decisions.md (no
report file).
**No skipping:** progress.py has no skip; `done` checks each step's output (run log / files)
and refuses a step that didn't run.

**Excluded lists + HubSpot fields (2026-10-15):** export also writes
`excluded_contacts.csv` / `excluded_companies.csv` (screening exclusions from
the hand-off + rows removed during the run; same columns + Why Rejected).
Upload files have the columns of the team's reference files (EDGE 2026 upload files, + Type, + Primary industry; hs_fields.SPEC), headed with HubSpot's field labels; every dropdown value is
one of the property's current options, both from a live `get_properties` check
each run (`hs_fields.py`; export refuses without it). Live check found:
additional emails = `secondary_email`; contact email domain is HubSpot-set (not
imported); no importable additional-domains property; LEAD SOURCE labels in caps.

**Speed at the connector steps (2026-10-15):** step 3 reads HubSpot with bulk
`query_crm_data` SQL (~25 companies per call as IN lists on domain / website /
ZoomInfo ID / name / LinkedIn page; name LIKE pass only for companies not found;
contacts by email / LinkedIn / company record IDs) instead of one search per
company: 127 companies went from ~140 calls to ~6 (+ a few name calls). HubSpot
refuses a WHERE with >20 OR'ed conditions — the plans stay ≤15 (the event-list
lookup used 40 and would have failed; fixed in both skills). These SQL plans and
the event lookup run through `zi_workers.py` (jobs hs-companies / hs-names /
hs-contacts / hs-event-1/2) with parallel sub-agents, default 6; raw results stay
out of the main chat. Named-contact lists: ZoomInfo direct enrich, 10 per call
(no per-person search → pick), `attach` judges the matches.

**New Hires run feedback (2026-10-15):** industry columns were empty — on the
named-contacts path the HubSpot lookup only fills website/HQ/size and ZoomInfo
ran `--no-companies`, so nothing supplied industry. Now ZoomInfo enriches the
companies there too (credits = contacts + companies), and export stops if no
company has an industry. Owner columns hold the owner's **name** (live option
label; an unknown ID falls back to the Owner Name column), not the ID. Contact
file no longer carries company industry fields.

**Upload columns (2026-10-15):** the user's EDGE 2026 upload files decide which
columns the upload files have (and their order); headers stay HubSpot's field
labels. Companies add Type (came after that template) and Primary industry.
Contacts add Secondary email / Contact owner only when filled. ZoomInfo
management levels map to HubSpot's Employment Seniority (VP-Level → VP,
C-Level → Executive, Non-Manager → Employee). Email Domain is included (HubSpot
fills it itself). Dropped: Industry group, outbound personalization columns,
contact Street Address.

**Industries (2026-10-15):** company file carries the team's two levels from the
Industries cleanup file (cols C/D): Primary industry (5 values) + Industry group
(48 values; `hs_industry_group`, text in HubSpot until they make it a dropdown —
held to the list meanwhile). `config.json` → `industry_map` maps all 180 ZoomInfo
industry|sub-industry values (79 judgment calls, sent to the user for review)
and LinkedIn names by keyword. HubSpot's default `industry` dropdown is no
longer uploaded.

`skill/didero-contact-sourcing/`: the two event-company flows (no titles →
ZoomInfo list build; titles → ZoomInfo search per title), ending in a contact
file for v2 (`tag-event` now writes Event Name into the export CSV).

## Open questions

- Cowork review 2.4–2.13 (LinkedIn global pages, noisy phone matches, stale
  renamed companies, non-ZoomInfo inputs, nickname overwrites, skip path for
  Clay, etc.) — not yet decided.

## Decision log

- 2026-09-28 — Sample data kept out of git (repo is public).
- 2026-09-28 — Step 1 rules confirmed: website is never the email domain;
  match check is by Claude's judgment of domain vs company name, not email
  validity; doubtful rows go to the user; web backfill uses general inboxes,
  falling back to public staff addresses.
- 2026-09-28 — All contact domains go on the company: primary in
  `Company Domain` (superseded below), others in `Additional Domains`
  (`;`-separated). Subsidiary emails are kept, not cleared.
- 2026-09-28 — `Company Domain` = the domain most used by the company's
  contacts (not automatically the parent's); ties go to the user. Acquired
  companies keep their own domains (FBM is not moved to `lowes.com`).
  `Company Domain` + `Additional Domains` replace file 5's `Email Domain`.

- 2026-09-28 — Step 2 rules: fix bad casing + strip credentials; no LinkedIn
  live check; wrong-person LinkedIn URLs blanked and reported in chat;
  last-name mismatches go to the user as a decision box (keep / blank /
  corrected URL; the user checks LinkedIn themselves); output files carry no audit/notes columns;
  ZoomInfo values (e.g. revenue) passed through without outlier checks;
  company file syncs website/domains from contacts; industry joined with
  "- "; contact file's first column is `ZoomInfo Contact ID`.

- 2026-09-28 — Step 3: companies first (domain, website, ZoomInfo ID,
  LinkedIn page, name + location, firmographics), then contacts (LinkedIn on
  `lgm_linkedinurl`, email, name + location, short names, same title at same
  company). User merges manually in HubSpot before giving the survivor ID.
- 2026-09-28 — Step 4: user imports via HubSpot's import screen, companies
  first; Claude shows a mapping table in chat with "Don't overwrite"
  suggestions; Type defaults to Prospect (ask if the list doesn't look like
  prospects); ZoomInfo IDs not imported; Fax dropped; Website → Website URL.

- 2026-09-28 — Management Level → Employment Seniority (dropdown); step 2
  converts ZoomInfo values (VP-Level → VP, C-Level → Executive, …). Record IDs
  → HubSpot's built-in Record ID only. User imports; on errors they fix the
  file and re-import or edit in HubSpot.

- 2026-09-28 — HubSpot merges create a new record ID; the user supplies it and
  Claude verifies via `hs_merged_object_ids`, then checks the survivor's
  name/domain (SRS merge kept "Superior Distribution").

- 2026-09-28 — Always run on Opus 5.x or Fable (first reminder in the skill).
  HubSpot searches run through the private app token
  (`HUBSPOT_PRIVATE_APP_TOKEN`) via `hubspot_match.py run-plan`; each user sets
  it up on their own device first. The connector is the slow fallback
  (Claude has to re-type every result).

- 2026-09-29 — After the import: the user builds a segment excluding
  Exclusion List A–F; Claude proposes association fixes (no company →
  associate; several → list's company primary) and applies them after
  approval; then checks the segment's companies for leftover duplicates
  (domain variants, LinkedIn, phone, similar name + location with state
  codes = names). Files are not updated after import.

- 2026-09-29 — Step 5 in Clay is user-run: the Clay connector can't reach
  workbooks (it is also pinned to a personal workspace, not the team one).
  Claude guides tab by tab (ZoomInfo only for non-ZoomInfo lists; PDL, then
  Import Objects from HubSpot). Both template links go to the user, who
  picks one, duplicates it and names the copy `name_segment_date`. No HubSpot
  check afterwards; step 6 waits for the user's confirmation. Not turning
  tabs into Clay Functions.

- 2026-09-29 — Step 6: the company rule wins over an existing BDR contact
  owner (moved to the company's majority BDR); no separate conflicts file
  (Reason column + chat summary instead).

- 2026-09-29 — Step 6 balance: worked companies stay locked; if the contact
  gap is > 10% of the average and > 3 contacts, Claude suggests locked
  companies to move and the user decides one by one.

- 2026-09-30 — Tests: setting a contact's primary company via the connector
  works ("Primary" label; `associatedcompanyid` lags ~1 min). Step 6 dry run on
  list 2759 produced an even 27/27/27 split. Found free-mail company records
  (Gmail, Hotmail, 139.com) → step 1 now never uses personal mailbox domains.
  Fast HubSpot search and post-import duplicate check still untested: need
  `HUBSPOT_PRIVATE_APP_TOKEN` in the environment.

- 2026-09-30 — After the Cowork test: steps/sub-agents table; HubSpot links
  on every record in chat; segment exclusions verified by the user (Claude
  lists the six lists with links, asks for the segment link + confirmation;
  no membership check); connector mode first-class (ingest, build-snapshot,
  plan/match-dupes); first-time connector check (manual, in Claude
  settings); same-person-different-company contacts go to review.
  Open: Cowork review items 2.3 (drop command) and 2.4–2.13.

- 2026-09-30 — Replaced the multi-CSV design with one working file
  (`worksheet.py`): flags instead of drops, all edits done by Claude in the
  chat (no manual CSV edits), before → after shown and confirmed before the
  next step, upload files generated only at export. Cowork review 2.3
  (drop command) is superseded by this.

- 2026-10-01 — Started skill 2: `linkedin-list-screening` (for non-ZoomInfo
  lists): load → company-researcher + title-reviewer → geography (ask company
  and contact countries separately; default US, Canada, UK incl. Scotland,
  Ireland) → flashcard review (local HTML, Keep/Exclude/Back, code pasted back
  into chat) → Decision column in `screening.csv`. Tested on the CBM sample.

## Using this in Cowork

- Create a Cowork project, e.g. "Outbound List Cleaner", and add
  `PROJECT.md` and `SPEC.md` as project files (or paste PROJECT.md into the
  project instructions).
- Set `HUBSPOT_PRIVATE_APP_TOKEN` on the device and connect the HubSpot
  connector before the first run.
- Test plan: `COWORK_TEST_PLAN.md`.
- Install the skill: zip `skill/didero-outbound-lists/` and upload it as a
  skill.
- Put sample/input files in the project's local folder, not in the repo.
- At the end of each session, update the Status, Next up, Open questions and
  Decision log sections above so the next chat can pick up from here.
