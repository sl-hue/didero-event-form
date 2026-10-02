# Event-list steps (contact lists and company-only lists)

Part of the `didero-outbound-lists` skill — `SKILL.md` says when to use these steps. Scripts are in `scripts/`, settings in `config.json`.


**Contact lists** (people named) use steps 1–5 below. **Company-only lists**
(exhibitors, sponsors — no names) use the section at the end. The
`SKILL.md` runs these stages, then hands over
to `references/screening.md` and `references/zoominfo-lists.md`.

Scripts are in the skill's `scripts/` folder. Create a run folder per event
in the user's working folder (`<event>_<date>/`). The list holds personal data:
keep it on the user's device; never publish it.

## Steps and sub-agents

**1. Every source first** — `source-collector` (subagent)
- Ask the user for **everything they have for this event**: the attendee file,
  the event's website (attendee / speaker / exhibitor-staff pages), PDFs,
  badge-scan exports, emails.
- For web pages: look at what you can reach, but if the page hides people
  behind **dropdowns, tabs, "load more", profile pop-ups, contact pages or
  links to click into**, don't click through them one by one — it takes far
  too long. Tell the user exactly which parts to open and **screenshot**
  (every dropdown expanded, every page of the list, every contact page) and
  to drop the screenshots in the chat or the shared folder.
- Ask which HubSpot property records the event (see step 5) and the event's
  name as it should appear.

**2. Load the essentials** — `intake.py`
- Files: `python3 scripts/intake.py init --input <file> [<file> …] --event "<event name>" --out-dir <run_dir>`
  → `<run_dir>/event.csv` with **First Name, Last Name, Job Title, Company**
  (plus email, phone, LinkedIn URL, website, location when the files have
  them). If it can't find the name / company columns, ask which column holds
  them.
- Screenshots, PDFs, pasted pages: read the people off them yourself into
  `people.json` (`[{"first", "last", "full", "title", "company", "email",
  "linkedin", "website"}]` — only what's visible, never invent), then
  `python3 scripts/intake.py add --run-dir <run_dir> --file people.json --source "<which screenshot/page>"`.
  The same person (name + company) is merged, filling blanks only.
- `python3 scripts/intake.py gaps --run-dir <run_dir>` lists anyone missing an
  essential field and names that couldn't be split safely. Look in the other
  sources first, then ask the user. Show the counts and wait for the OK.

**3. Company website, then HQ** — HubSpot first, then `company-researcher` (subagent) for the rest
- **HubSpot first** (see "HubSpot company lookup" below) with `--kind event`.
  Companies HubSpot fills completely are done; only the rest is researched.
- `python3 scripts/companies.py plan --run-dir <run_dir>` → `companies_todo.json`
  (with the corporate email domains seen on each company's attendees — the
  best clue to the right website).
- For each company: find the **website** first (the company's own site — not
  a LinkedIn page, Linktree, careers page or directory), then the **HQ city,
  state and country** from the site (contact / about / locations page) or a
  reliable source. Same-name companies: the attendees' email domain decides.
  Write `found.json` (`{"<company>": {"website", "city", "state", "country",
  "source", "confidence": "high|medium|low"}}`) and run
  `python3 scripts/companies.py apply --run-dir <run_dir> --file found.json`.
  Show low-confidence ones and anything still missing to the user.

**4. Hand over to screening**
- `python3 scripts/companies.py export --run-dir <run_dir> --out <run_dir>/event_for_screening.csv`
- Then `references/screening.md`: `screen.py init --input <run_dir>/event_for_screening.csv --out-dir <run_dir>/screening --event`
  (skip its multiple-jobs step — event lists have no job count), company
  research + review (based / present in the target countries), contacts
  (titles). Event attendees' own location isn't known: run
  `screen.py check … --skip-contact-geo`. Then its step 6 (title / company
  name cleaning) and step 7 hand-off with `--list-type Event`.

**5. Event in HubSpot: Lead Source + Lead Source Detail 1**
The working file keeps the event in **Event Name**. The export (`worksheet.py
export`) turns it into two upload columns, mapped at the import
(references/zoominfo-lists.md step 4):
- **Lead Source** (`lead_source`, dropdown) = `Events`
- **Lead Source Detail 1** (`lead_source_detail_1`, text) = the event name,
  e.g. `IMTS 2026`. Agree the exact wording with the user once per event.

The rest of the flow (ZoomInfo search → pick → enrich, LinkedIn URL finder,
source priority, cleaning, HubSpot) is in `references/zoominfo-lists.md` — the
`SKILL.md` lists the order.


## HubSpot company lookup (both kinds of event list)

HubSpot already has most companies we meet at events, and one
`query_crm_data` call checks dozens at once — much faster than researching
each one on the web. So company data comes from HubSpot first; web research
only covers what HubSpot doesn't have; enrichment later (ZoomInfo, Clay)
keeps the data up to date.

1. `python3 scripts/hubspot_companies.py plan --run-dir <run_dir> --kind event|companies`
   → `hs/plan_1.json`: SQL queries (exact company name OR domain — website
   and attendees' email domains — 40 conditions each, `LIMIT 500`).
2. Run each query with the HubSpot connector's `query_crm_data`
   (`verbosityLevel: "LOW"`; call its tool guidance once first if the
   connector asks), save the raw result to a file and run
   `hubspot_companies.py ingest --run-dir <run_dir> --pass 1 --batch <i> --response <file>`.
3. `hubspot_companies.py apply --run-dir <run_dir> --kind …` — matches by
   domain or same name (sure), writes website, HQ city / state / country,
   employees, revenue and **HubSpot Company Record ID** (source "HubSpot").
4. If some aren't found: `plan --pass 2` (company name contains its main
   word — catches "Orgill" for "Orgill Inc"), run + `ingest --pass 2`, then
   `apply` again.
5. **ASK lines** (similar names, or more than one record): ask the user
   which record is the company (or none), with the record links; write
   `{"<company>": "<record id>" | "none"}` and re-run `apply --decisions <file>`.
6. Tell the user: X of Y filled from HubSpot, Z go to web research.

## Company-only event lists (exhibitors, sponsors — no contact names)

Script: `scripts/company_list.py` (and `scripts/titles.py` for branch B). Run
folder as above. Stop after each step, show what changed, wait for the OK.

**1. Collect the companies** — same as step 1 above (every source;
screenshots for dropdowns / sub-pages). Note any **job titles** the source
gives per company.
`python3 scripts/company_list.py init --input <file> … --event "<event name>" --out-dir <run_dir>`;
screenshots / pages → `companies.json` (`[{"company", "website", "title"}]`) →
`company_list.py add --run-dir <run_dir> --file companies.json --source "<…>"`.
It says how many companies go to **branch A** (no titles) and **branch B**
(titles).

**2. HubSpot first, then web research** — "HubSpot company lookup" below
with `--kind companies`, then `company-researcher` (subagent) for the rest:
`company_list.py plan --run-dir <run_dir>` → for every company HubSpot
didn't fill (companies filled from HubSpot are skipped; values the list
already has are **re-checked**, not trusted): website, HQ city / state /
country, and number of employees / annual revenue if published (exact numbers;
a range only if that's all there is). `found.json` →
`company_list.py apply --run-dir <run_dir> --file found.json` (shows what
differed from the list, and low-confidence finds — confirm those).

**3. Drop non-target countries** — `company_list.py filter --run-dir <run_dir> [--countries …]`
(default United States, Canada, United Kingdom, Ireland; ask the user each run).
Show who would be excluded and anyone whose country is still unknown; after the
OK, `filter … --confirm`. Settle unknowns with
`company_list.py set --company "<name>" --field "Country=…"` (or `--exclude "<reason>"`).

**4. Clean the company names** — the same rules as the LinkedIn title /
company cleaning: `company_list.py clean --run-dir <run_dir>` → `names_review.json`
(safe fixes + judgment calls — ask when unsure) →
`company_list.py clean --run-dir <run_dir> --decisions <json>`.

**Branch A — no job titles: the user builds the list in ZoomInfo**
1. `company_list.py zoominfo --run-dir <run_dir> --out <run_dir>/zoominfo_upload.csv`
   — Company Name, Company Website, Company City, Company State, Company
   Country, Number of Employees, Annual Revenue (numbers in HubSpot's format).
   Refuses while a company's country is unknown.
2. **Ask the user for this run's filters**, showing the defaults from
   `config.json`: company HQ countries and contact countries (US, Canada, UK,
   Ireland), seniority **Director and above** (C-Level, VP-Level, Director),
   titles to include (procurement, purchasing, sourcing, supply chain, buyer,
   category manager, materials, operations, planning, inventory, logistics,
   supplier) and to exclude (intern, assistant, recruiter, software engineer,
   student, retired, sales, marketing, HR, talent, people). Save their changes
   as a json and run
   `company_list.py guide --run-dir <run_dir> --title "<event>" --upload zoominfo_upload.csv [--filters <json>]`.
3. Open `<run_dir>/zoominfo_guide.html` for the user next to ZoomInfo: upload
   the companies → contacts at those companies → each filter (with Copy
   buttons) → **select the contacts first** → Export → **Excel** →
   **Suppression** / limits: **4 contacts per company, prioritized by
   seniority** → wait 10–15 minutes → give Claude the file. (Suppression lists
   live in HubSpot; nothing else to set up.)
4. The export is a **normal ZoomInfo list**: `references/zoominfo-lists.md`
   `worksheet.py init`, then **`company_list.py tag-event --run-dir <run_dir> --working <cleaner run_dir>`**
   (Event Name on every contact at an event company; unmatched companies →
   ask), then steps 1–6.

**Branch B — job titles but no names: Claude finds the people**
1. `titles.py search-plan --run-dir <run_dir>` → one ZoomInfo `search_contacts`
   per company + title (no credits; retry without `companyWebsite` if empty);
   save each and `titles.py search-ingest --run-dir <run_dir> --target <T…> --response <file>`.
2. `titles.py candidates --run-dir <run_dir>` — show the user every company's
   candidates. **The user always chooses** (several people, someone with a
   better title, or nobody). `{"<T…>": ["<personId>", …]}` →
   `titles.py choose --run-dir <run_dir> --decisions <file>`.
3. Titles with nobody: `titles.py finder --run-dir <run_dir> --title "<event>"`
   and open `<run_dir>/title_finder.html` next to the Cowork browser — the card
   shows the title and company; **Search Google / Search LinkedIn** open in the
   same tab; the user pastes the LinkedIn URL and **types the first and last
   name**; Can't find leaves it unfilled. Code → `titles.py finder-apply --code …`
   (preview) → after the OK `--confirm`.
4. `titles.py enrich-plan --run-dir <run_dir>` → **maximum credits** (chosen
   people + finder people); after the OK run `enrich_contacts` per batch and
   `titles.py enrich-ingest --run-dir <run_dir> --batch <n> --response <file>`.
5. `titles.py build-contacts --run-dir <run_dir> --out <run_dir>/title_contacts.csv`
   (company data from the research, Event Name on every row; a finder person's
   title becomes ZoomInfo's only when it's the same job) →
   `references/zoominfo-lists.md` `worksheet.py init --contacts …`, then steps 1–6.

**Mixed lists** (titles for some companies only): branch B for the titled
companies, branch A for the rest, in the same run.
