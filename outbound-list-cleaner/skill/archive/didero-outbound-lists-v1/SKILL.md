---
name: didero-outbound-lists
description: Didero's outbound prospect lists, start to finish — work out what kind of list it is (ZoomInfo export, LinkedIn Sales Navigator / Evaboot export, event contact list, or company-only event list) — announced, or asked only when unclear; for any other list, asks what the data is for and how to handle its contacts — then check and log the requirements, track every step, screen, research, clean and standardize it, match ZoomInfo, find LinkedIn URLs, check HubSpot for duplicates, prepare the HubSpot import, fix associations after import, guide the Clay enrichment and assign BDR owners. Use whenever someone brings a list, file, export, exhibitor list or attendee list to clean, screen, enrich, dedupe, import into HubSpot, enrich in Clay or hand out to BDRs — even if they don't say where it came from.
---

# Didero outbound lists

One skill for every list type.

**Hold this skill for the whole chat.** Long runs drifted away from the
instructions (cleaning skipped, ZoomInfo URLs, import and Clay instructions
left out). So the step order lives in `scripts/progress.py`: right after the
requirements check run `progress.py start`, and **before every step** run
`python3 scripts/progress.py next --run-dir <run_dir>` and follow what it
prints: that step's full instructions, read fresh from the reference page,
the pages to open in the browser and the standing rules. Never do a step from
memory. After the user's OK, `progress.py done --step <id>` (it refuses steps
out of order). After any interruption, or when unsure where the run is, run
`progress.py status` and `next` again.

This page decides the list type and the order of the steps; the detailed instructions for each step are in three reference
pages — read the one a step points to before running it:

- `references/zoominfo-lists.md` — the working file, email domains,
  normalization, HubSpot duplicates, import, post-import checks, Clay, BDRs
  (steps 1–6), plus the ZoomInfo / LinkedIn / event stages that run on the
  working file.
- `references/screening.md` — loading LinkedIn lists, multiple jobs, company
  and contact review page, title / company cleaning, hand-off.
- `references/event-lists.md` — event contact lists and company-only event
  lists (research, country filter, ZoomInfo guide, title finder).

All scripts are in `scripts/` and all settings in `config.json`, at this
skill's root. Run them with the skill folder's absolute path.

## Step 0 — what kind of list is it?

1. Run `python3 scripts/detect_list_type.py <file> [<company file>]`. It
   reads the header and the first rows and returns the type, a
   **confidence** and the evidence (columns that gave it away, whether names
   / titles are filled).
2. **High confidence → don't ask.** Say what it is in one line, with the
   evidence, and carry on — e.g. "This is an event company list (company and
   website columns, no names, no job titles), so I'll start with the HubSpot
   company lookup. Tell me if that's wrong." The user can correct it at any
   point.
3. **Low confidence → ask** (one multiple-choice question: ZoomInfo export /
   LinkedIn (Sales Nav or Evaboot) export / event contact list / event
   company list / none of these), showing the guess and the evidence.
4. **None of these** (`unknown`, or the user says so; e.g. a partner list, a
   customer export, a webinar list, a hand-made sheet): don't force it into a
   flow. Ask the user first:
   - **What is this data for?** (prospects to import for outbound, an update
     to records already in HubSpot, research only, something else)
   - **If it has contacts: how should they be handled?** (import as new
     contacts, update existing ones only, skip contacts and keep companies,
     not imported at all)
   Then say which steps you'll run and get their OK. Prospects to import go
   through the shared steps (`progress.py start --list-type other`: steps 1–6
   of `references/zoominfo-lists.md`); anything else, do only what they asked,
   still never importing through the connector.

The detected type picks the flow below directly: `zoominfo`, `linkedin`,
`event-contacts`, `event-companies` (no titles → branch A) or
`event-companies-titles` (titles, no names → branch B).

## The flows

**ZoomInfo export** → `references/zoominfo-lists.md`, steps 1–6 (import:
upload files + `HOW_TO_IMPORT.md`; Clay: `clay_guide.py`).

**LinkedIn (Sales Nav or Evaboot)**:

| # | Stage | Skill |
|---|---|---|
| 1 | Load the list | `references/screening.md` step 1 |
| 2 | Multiple current jobs — the user sets each person's real title and company | `references/screening.md` step 2 |
| 3 | Research + review companies (based or present in the target countries), then contacts | `references/screening.md` steps 3–5 |
| 4 | Title and company name cleaning | `references/screening.md` step 6 |
| 5 | Hand-off into the working file (contacts + companies) | `references/screening.md` step 7 |
| 6 | Steps 1–2 (email domains, normalization) | `references/zoominfo-lists.md` |
| 7 | ZoomInfo pull — tell the user the maximum credits first; calls in parallel (`zi_workers.py`) | `references/zoominfo-lists.md` — LinkedIn lists, stage 7 |
| 8 | Pick the source per field | `references/zoominfo-lists.md` — LinkedIn lists, stage 8 |
| 9 | Consistency: within a contact → across a company's contacts → contacts ↔ companies | `references/zoominfo-lists.md` — LinkedIn lists, stage 9 |
| 10 | Prune columns | `references/zoominfo-lists.md` — LinkedIn lists, stage 10 |
| 11 | Steps 1–2 again (only what changed is shown) | `references/zoominfo-lists.md` |
| 12 | HubSpot duplicates → import (upload files + HOW_TO_IMPORT.md) → Clay (`clay_guide.py`) → BDRs (steps 3–6) | `references/zoominfo-lists.md` |

Stop after each stage, show the user what changed and wait for their OK
before the next one.

**Rules for every flow** (they were missed in real runs, so they are not optional):
- **Never import through the connector (MCP).** No creating or updating the
  list's contacts or companies in HubSpot with `manage_crm_objects` or any
  other connector tool, not even "just a few". The user imports the upload
  files through HubSpot's import screen. The connector only reads, plus two
  approved updates on records that already exist: association fixes (step 4)
  and owners (step 6), each after the user's OK.
- **Open HubSpot in the browser window.** At the start of the run open
  HubSpot (`https://app.hubspot.com/contacts/<portal>`) in the browser
  (Claude in Chrome / the built-in browser) and keep it open. Whenever the
  user has to look at or do something in HubSpot (duplicates and merges,
  import, segment, associations, owners), open that page there; a link in
  the chat alone is not enough. `progress.py next` lists the pages. No
  browser tool → paste the link and say so.
- **Cleaning is step 2, every list type:** contact first/last names, company
  names (the contact's company too) and job titles are rewritten there; the
  export refuses if step 2 didn't run or left decisions open.
- **ZoomInfo calls run in parallel** through `scripts/zi_workers.py` and
  sub-agents started all at once, never one by one in the main chat.
- **Import (step 4):** always send the two upload files **and**
  `upload/HOW_TO_IMPORT.md`, and paste the instructions in the chat.
- **Clay (step 5):** always start by running `scripts/clay_guide.py` and
  pasting its output: template links, copy/rename, tabs, button order.

**Event company list** (exhibitors, sponsors — no contact names):

| # | Stage | Skill |
|---|---|---|
| 1 | Collect the companies (+ any job titles) from every source | `references/event-lists.md` — company-only, step 1 |
| 2 | HubSpot first: bulk lookup of every company (`hubspot_companies.py`), then web research only for what HubSpot doesn't have (re-check what the list says) | step 2 |
| 3 | Drop non-target countries (ask which each run) | step 3 |
| 4 | Clean company names (same rules as LinkedIn lists) | step 4 |
| 5A | No titles: ZoomInfo upload CSV + guide page next to ZoomInfo (filters asked each run; select → Excel → Suppression / 4 per company by seniority) → the export is a normal ZoomInfo list, event tagged | branch A, then `references/zoominfo-lists.md` steps 1–6 |
| 5B | Titles, no names: ZoomInfo search per title → **user chooses** → finder page for the rest (LinkedIn URL + typed name) → enrich (max credits first) → contact file | branch B, then `references/zoominfo-lists.md` steps 1–6 |

Mixed lists: 5B for companies with titles, 5A for the rest.

Event **contact** lists:

| # | Stage | Skill |
|---|---|---|
| 1 | Collect every source; ask for screenshots of dropdowns / contact pages / sub-pages | `references/event-lists.md` step 1 |
| 2 | First name, last name, job title, company (+ whatever else is there) | `references/event-lists.md` step 2 |
| 3 | Company website, HQ city / state / country: HubSpot first (`hubspot_companies.py`), web research only for the rest | `references/event-lists.md` step 3 |
| 4 | Screening: companies (based / present in) → contacts (titles), contact geography skipped | `references/screening.md` steps 1, 3–5 (`--skip-contact-geo`) |
| 5 | Title and company name cleaning | `references/screening.md` step 6 |
| 6 | Hand-off into the working file | `references/screening.md` step 7 (`--list-type Event`) |
| 7 | Steps 1–2 (email domains, normalization) | `references/zoominfo-lists.md` |
| 8 | ZoomInfo: free candidate search → pick best (unclear → user) → enrich picked (max credits first) | `references/zoominfo-lists.md` — event lists, ZoomInfo |
| 9 | LinkedIn URL finder for people ZoomInfo couldn't match (browser + card page) | `references/zoominfo-lists.md` — event lists, LinkedIn finder |
| 10 | Source per field, consistency, prune | `references/zoominfo-lists.md` — LinkedIn lists, stages 8–10 |
| 11 | Steps 1–2 again (only what changed is shown) | `references/zoominfo-lists.md` |
| 12 | HubSpot duplicates (existing record IDs go in the upload) → import with Lead Source = Events + Lead Source Detail 1 = event name → Clay → BDRs | `references/zoominfo-lists.md` steps 3–6 |

## Before you start — requirements check (every run, logged)

Right after Step 0, before any other step, run the requirements check and
show its output to the user, then `progress.py start --run-dir <run_dir> --list-type <type>`
(use `other` for "none of these"):

```
python3 scripts/preflight.py --list-type <type> --run-dir <run_dir> \
  --user "<the user's name or email, if you know it>" \
  --observed '{"model": "<your model id>", "connectors": {"hubspot": true|false,
              "zoominfo": true|false, "web_search": true|false, "clay": true|false}}'
```

- `--observed` is what **you** see: your model, and for each connector
  whether its tools are in your tool list (HubSpot: `query_crm_data`;
  ZoomInfo: `enrich_contacts`; web search; Clay). Report honestly — `false`
  if a tool isn't there. Use the type Step 0 detected.
- The script checks Python, openpyxl, scripts, page templates, config.json
  and the run folder itself, then writes the result to the run folder, to a
  log on this device and — when `backend.json` is set up — to the team's log
  (one row per run, whoever runs it). Tell the user the "log:" line.
- **MISSING / exit code 1 → stop** and tell the user what to fix (connectors
  are added in Claude's Settings → Connectors, then a new chat). Details on
  each requirement: `references/zoominfo-lists.md` "Before you start".

The list contains personal data: keep it on the user's device; never
publish it.
