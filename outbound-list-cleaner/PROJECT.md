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
Name mapped to the event property the user picks: Event name / Lead Source -
Event + LEAD SOURCE = Events). Tested on a fictional 6-person list.

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
