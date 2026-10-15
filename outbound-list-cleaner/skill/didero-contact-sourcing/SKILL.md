---
name: didero-contact-sourcing
description: Didero's contact sourcing for company-only lists — exhibitor and sponsor lists, or any list that names companies (with or without job titles) but no people. Researches the companies (HubSpot first, then the web), keeps the target countries, cleans the names, then finds the contacts — branch A, the user builds the list in ZoomInfo from an upload file and a guide page; branch B, ZoomInfo search per job title with the user choosing the people, then enrichment. Ends with a contact file handed to didero-outbound-lists for cleaning, HubSpot upload files and BDR owners. Use whenever someone brings a list of companies and needs the people at them.
---

# Didero contact sourcing

For lists that name **companies but no people** (exhibitors, sponsors, a
target-account list). This skill finds the contacts; **didero-outbound-lists**
then cleans them, checks HubSpot and builds the upload files. Lists that
already name people (attendees, ZoomInfo / LinkedIn exports) go straight to
didero-outbound-lists.

Scripts are in `scripts/`, settings in `config.json` (both at this skill's
root). Run folder per list in the user's working folder (`<list>_<date>/`).
The list holds company and, later, personal data: keep it on the user's
device; never publish it. Claude never writes to HubSpot: the connector is
read-only.

## Before you start

`python3 scripts/preflight.py --list-type event-companies --run-dir <run_dir> --observed '<json>'`
(see the script's help). Stop only if HubSpot or ZoomInfo isn't connected or
the model isn't Opus 5.5 or newer.

## Steps

**1. Collect the companies.** Ask for everything the user has (file, links,
pages); for dropdowns and sub-pages ask for **screenshots** instead of
clicking through. Note any **job titles** per company.
`python3 scripts/company_list.py init --input <file> … --event "<event or list name>" --out-dir <run_dir>`;
screenshots / pages → `companies.json` (`[{"company", "website", "title"}]`) →
`company_list.py add --run-dir <run_dir> --file companies.json --source "<…>"`.
It says how many companies go to **branch A** (no titles) and **branch B**
(titles). Mixed lists run both.

**2. HubSpot first, then web research.**
1. `python3 scripts/hubspot_companies.py plan --run-dir <run_dir> --kind companies`
   → `hs/plan_1.json` (one `name IN` + one `domain IN` per query, ~40
   companies each). Run them in parallel: `python3 scripts/zi_workers.py --run-dir <run_dir> --job hs-event-1`
   and start the sub-agents it lists all at once (each runs `query_crm_data`,
   saves and ingests its result, and replies with one line).
2. `hubspot_companies.py apply --run-dir <run_dir> --kind companies`. Not found:
   `plan --pass 2` (name contains its main word), `zi_workers.py ... --job hs-event-2`, apply again.
   ASK lines (similar names, several records): ask the user which record (or
   none) → `apply --decisions <file>`.
3. `company-researcher` (subagent) for the rest: `company_list.py plan --run-dir <run_dir>`
   → website, HQ city / state / country, employees / revenue if published
   (exact numbers; a range only if that's all there is) → `found.json` →
   `company_list.py apply --run-dir <run_dir> --file found.json`. Confirm
   low-confidence finds with the user.

**3. Drop non-target countries.** Ask which countries (default United
States, Canada, United Kingdom, Ireland) →
`company_list.py filter --run-dir <run_dir> --countries …`, show who would be
excluded and anyone whose country is unknown, then `--confirm`. Unknowns:
`company_list.py set --company "<name>" --field "Country=…"` (or `--exclude "<reason>"`).

**4. Clean the company names.** `company_list.py clean --run-dir <run_dir>`
→ `names_review.json` (safe fixes + judgment calls; ask when unsure) →
`company_list.py clean --run-dir <run_dir> --decisions <json>`.

**Branch A — no job titles: the user builds the list in ZoomInfo**
1. `company_list.py zoominfo --run-dir <run_dir> --out <run_dir>/zoominfo_upload.csv`
   (Company Name, Company Website, Company City, Company State, Company
   Country, Number of Employees, Annual Revenue). Refuses while a country is unknown.
2. **Ask for this run's filters**, showing the defaults in `config.json`
   (`zoominfo_filters`): seniority Director and above; titles to include
   (procurement, purchasing, sourcing, supply chain, buyer, category manager,
   materials, operations, planning, inventory, logistics, supplier) and to
   exclude (intern, assistant, recruiter, software engineer, student,
   retired, sales, marketing, HR, talent, people). Save changes as json →
   `company_list.py guide --run-dir <run_dir> --title "<event>" --upload zoominfo_upload.csv [--filters <json>]`.
3. Open `<run_dir>/zoominfo_guide.html` next to ZoomInfo: upload the
   companies → contacts at those companies → each filter → **select the
   contacts first** → Export → **Excel** → **Suppression** / limits: **4
   contacts per company, prioritized by seniority** → wait 10–15 minutes →
   give Claude the file.
4. `company_list.py tag-event --run-dir <run_dir> --export <the export> --out <run_dir>/sourced_contacts.csv`
   (Event Name on every contact at a listed company) → **hand-off**.

**Branch B — job titles but no names: Claude finds the people**
1. `titles.py search-plan --run-dir <run_dir>` → one ZoomInfo `search_contacts`
   per company + title (free). Run in parallel: `zi_workers.py --run-dir <run_dir> --job title-search`
   and start the sub-agents it lists **all at once** (each reads its brief,
   calls ZoomInfo, saves the raw result, runs the ingest line, replies one
   line per call). Re-run `zi_workers.py` afterwards for anything missing.
2. `titles.py candidates --run-dir <run_dir>` — show every company's
   candidates. **The user always chooses** (several people, a better title,
   or nobody) → `{"<T…>": ["<personId>", …]}` → `titles.py choose --run-dir <run_dir> --decisions <file>`.
3. Titles with nobody: `titles.py finder --run-dir <run_dir> --title "<event>"`,
   open `<run_dir>/title_finder.html` next to the browser; the user pastes
   the LinkedIn URL and **types the name**; code → `titles.py finder-apply --code …`
   (preview) → after the OK `--confirm`.
4. `titles.py enrich-plan --run-dir <run_dir>` → **maximum credits**; after
   the user's OK, `zi_workers.py --run-dir <run_dir> --job title-enrich` and
   its sub-agents all at once.
5. `titles.py build-contacts --run-dir <run_dir> --out <run_dir>/sourced_contacts.csv`
   (company data from the research, Event Name on every row) → **hand-off**.

**Hand-off.** Tell the user the contact file is ready and start
**didero-outbound-lists** with `sourced_contacts.csv` (both branches of a
mixed list: give it both files). That skill asks its start questions (end
state, countries, BDRs), cleans the contacts, checks HubSpot and builds the
upload files, with Lead Source = Events and Lead Source Detail 1 = the event
name.
