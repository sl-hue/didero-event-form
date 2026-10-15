# Named-contact lists (event attendees and other lists with names)

Part of the `didero-outbound-lists` skill — `SKILL.md` says when to use these steps. Scripts are in `scripts/`, settings in `config.json`.

For lists that name **people and their companies** but carry no ZoomInfo or
LinkedIn data: event attendees, speakers, registrants, a hand-made sheet.
Company-only lists (exhibitors, sponsors, no names) belong to the
**didero-contact-sourcing** skill. These steps run, then
`references/screening.md` and `references/zoominfo-lists.md` take over.
**No stops and no questions**: Claude decides, and notes every judgment call
in `<run_dir>/decisions.md`. The list holds personal data: keep it on the
user's device; never publish it.

## Steps and sub-agents

**1. Load the essentials** — `intake.py`
- The event name: take it from the file, its name or the sources the user
  gave (e.g. `IMTS 2026`), and record it with
  `python3 scripts/setup.py set --run-dir <run_dir> --event-name "<event>"`. If the start
  answer left the lead source detail open, it's written from this (step 4).
- `python3 scripts/intake.py init --input <file> [<file> …] --event "<event name>" --out-dir <run_dir>`
  → `<run_dir>/event.csv` with **First Name, Last Name, Job Title, Company**
  (plus email, phone, LinkedIn URL, website, location when the files have
  them). If it can't find the name / company columns, pick them from the
  columns' contents.
- If the user also gave screenshots, PDFs or pages: read the people off them
  into `people.json` (`[{"first", "last", "full", "title", "company", "email",
  "linkedin", "website"}]` — only what's visible, never invent), then
  `python3 scripts/intake.py add --run-dir <run_dir> --file people.json --source "<which screenshot/page>"`.
  The same person (name + company) is merged, filling blanks only.
- `python3 scripts/intake.py gaps --run-dir <run_dir>` lists anyone missing an
  essential field. Fill from the other sources; anyone still missing a name
  or company leaves the list (noted in `decisions.md`); a missing title stays
  blank (ZoomInfo may fill it).

**2. Company website, then HQ** — HubSpot first, then web research for the rest, in parallel
- **HubSpot first** (see "HubSpot company lookup" below) with `--kind event`.
  Companies HubSpot fills completely are done; only the rest is researched.
- `python3 scripts/companies.py plan --run-dir <run_dir>` → `companies_todo.json`
  (with the corporate email domains seen on each company's attendees — the
  best clue to the right website).
- `python3 scripts/research_workers.py brief --run-dir <run_dir> --kind companies-hq` and start
  the helpers it lists all at once (over 20 contacts; smaller lists in the main chat), then
  `research_workers.py merge … --kind companies-hq` (→ `research/companies-hq.json`, used as
  `found.json` below). What each helper does: for each company: find the **website** first (the company's own site — not
  a LinkedIn page, Linktree, careers page or directory), then the **HQ city,
  state and country** from the site (contact / about / locations page) or a
  reliable source. Same-name companies: the attendees' email domain decides.
  Write `found.json` (`{"<company>": {"website", "city", "state", "country",
  "source", "confidence": "high|medium|low"}}`) and run
  `python3 scripts/companies.py apply --run-dir <run_dir> --file found.json`.
  Low-confidence finds stay (noted in `decisions.md`); a company with no
  country found is screened as unknown.

**3. Screening and hand-off**
- `python3 scripts/companies.py export --run-dir <run_dir> --out <run_dir>/event_for_screening.csv`
- Then `references/screening.md`: `screen.py init --input <run_dir>/event_for_screening.csv --out-dir <run_dir>/screen --event`,
  company research, `screen.py check … --skip-contact-geo` (attendees' own
  location isn't known: companies are screened by HQ / presence), the
  decision, and the hand-off with `--list-type Event`.

**4. Lead source detail** (only when the start answer left it to you)
The lead source was asked at the start, the way the team's lead source sheet
categorizes it (Lead Source → Lead Channel → Lead Source Detail;
`python3 scripts/leadsource.py show`). When the user picked e.g. "Events —
Conference" without the detail, work it out from the file name, the event
name and the event's own site, written exactly like the sheet: `Name - YYYY -
City, ST` (e.g. `EDGE - 2026 - Nashville, TN`; dinners `ASCM Dinner - 2026 -
Denver, CO`). Then `python3 scripts/setup.py set --run-dir <run_dir>
--lead-source "Events / Conference / <detail>"` (it checks the format). The
export writes **LEAD SOURCE** and **LEAD SOURCE DETAIL 1** on every contact;
when the user didn't know the lead source, both columns are left out.

## HubSpot company lookup

HubSpot already has most companies we meet at events, and one
`query_crm_data` call checks dozens at once — much faster than researching
each one on the web. Read-only.

1. `python3 scripts/hubspot_companies.py plan --run-dir <run_dir> --kind event`
   → `hs/plan_1.json`: SQL queries (one `name IN` + one `domain IN` —
   website and attendees' email domains — ~40 companies each, `LIMIT 500`).
2. Run them in parallel: `python3 scripts/zi_workers.py --run-dir <run_dir> --job hs-event-1`
   and start the `hubspot-searcher` sub-agents it lists all at once (each runs
   `query_crm_data`, saves and ingests its result, replies with one line).
3. `hubspot_companies.py apply --run-dir <run_dir> --kind event` — matches by
   domain or same name (sure), writes website, HQ city / state / country,
   employees, revenue and **HubSpot Company Record ID** (source "HubSpot").
4. If some aren't found: `plan --pass 2` (company name contains its main
   word — catches "Orgill" for "Orgill Inc"), `zi_workers.py ... --job hs-event-2`,
   then `apply` again.
5. **ASK lines** (similar names, or more than one record): decide yourself —
   the record whose domain matches the attendees' email domain or website;
   otherwise the one with the same city / country; otherwise none. Write
   `{"<company>": "<record id>" | "none"}` and re-run `apply --decisions <file>`.
6. Report in one line: X of Y filled from HubSpot, Z go to web research.

The rest of the flow (ZoomInfo direct enrich, source priority,
cleaning, HubSpot) is in `references/zoominfo-lists.md`; `progress.py` gives
the order.
