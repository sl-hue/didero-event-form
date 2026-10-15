# Screening (LinkedIn lists; also named-contact lists)

Part of the `didero-outbound-lists-v2` skill — `SKILL.md` says when to use these steps. Scripts are in `scripts/`, settings in `config.json`.

The first stage for any list that wasn't built in ZoomInfo. It decides **who
stays on the list**; `references/zoominfo-lists.md` then cleans the survivors
and builds the upload files. **No stops and no questions**: the countries come
from the start (`run_setup.json`), and every keep / exclude call is Claude's,
written to `screening_decisions.json` and `decisions.md` for the end-of-run
summary. The list contains personal data: keep it on the user's device;
never publish it.

## Steps and sub-agents

**1. Load the list** — `screen.py init --input <file> --out-dir <run_dir>/screen`
builds `screening.csv`: the original columns plus Row ID, Contact, Title,
Company, Contact City / State / Country, Location Note, Company Country and
the verdict columns. It reads CSV or Excel.
**Contact location:** separate city/state/country columns are used as they
are. A LinkedIn location is split, filling only what's certain: "Austin,
Texas, United States" → all three; a metro area gives its main (first-named)
city ("Greater Chicago Area" → Chicago / Illinois, "Dallas-Fort Worth
Metroplex" → Dallas / Texas); just a country → country only. Anything it
can't place gets a Location Note: work those out (company HQ, the profile)
and run `screen.py set-location --run-dir <run_dir>/screen --file locations.json`
with `{"<Row ID>": {"city": "", "state": "", "country": ""}}`; never guess a
city — leave it blank when unsure.
If it can't find the name, title or company column, pick it from the
columns' contents. Pre-filter columns (e.g. `Matches Filters`) are ignored:
every row is screened.
**Multiple current jobs:** LinkedIn shows one "main" job per person. v2 keeps
the job the file lists (no profile checking); the ZoomInfo pull later
replaces an outdated company only when ZoomInfo confirms the person.

**2. Research companies and review titles**
- `company-researcher` (subagent) — for each company: what it does, HQ
  country, **every country where it has a real presence** (offices, plants,
  warehouses, distribution — e.g. a Canadian company with US plants is
  present in the US), size, and whether it fits Didero's ICP (manufacturers
  and physical-goods companies with real supply chains — the
  `didero-icp-check` skill's criteria). Web search only. Write
  `{"<company>": {"fit": "fit|unclear|no", "reason": "…", "hq_country": "…", "presence": ["United States", …]}}`
  and run `screen.py apply-research --run-dir <run_dir>/screen --file research.json`.
- `title-reviewer` (subagent) — `screen.py check` (step 3) gives every title a
  first pass from keywords and seniority (`config.json`). Review every title
  the keywords didn't pass: many target roles use other words ("Integrated
  Supply", "Commodities", "Procure to Pay", "MRO"). Write
  `{"<Row ID>": {"fit": "…", "reason": "…"}}` and run
  `screen.py set-title --run-dir <run_dir>/screen --file title_reviews.json`.

**3. Countries and the decision**
- `screen.py check --run-dir <run_dir>/screen` (named-contact lists: add
  `--skip-contact-geo`, their own location isn't known) uses the countries
  chosen at the start, **companies first**: a company stays if it's
  headquartered **or present** in one of them; then **contacts** at the
  companies that stay must be in one of them. Each row gets a
  recommendation: keep (title, company and geography fit), exclude (any one
  doesn't), or review (something unclear, e.g. a contact with no country).
- Decide every review row yourself: look up unclear locations (LinkedIn
  location, company HQ), take the company research and the title rules, and
  write `{"<Row ID>": {"decision": "keep|exclude", "note": "why"}}`. Then
  `screen.py decide --run-dir <run_dir>/screen --file screening_calls.json`
  writes Decision + Decision Note on every row (nothing is deleted) and
  `screening_decisions.json`. Report the counts in one line and go on.

**4. Hand-off to references/zoominfo-lists.md**
- `python3 scripts/handoff.py --run-dir <run_dir>/screen --out <run_dir>/handoff_contacts.csv --list-type LinkedIn|Event`
  writes the kept contacts in the working file's columns (ZoomInfo's names):
  contact and company LinkedIn URLs in standard form, Person City / State /
  Country, company location, size, revenue range, industry. IDs are
  `LI-<Row ID>` / `LIC-<n>` (never imported).
- Then `python3 scripts/worksheet.py init --contacts <run_dir>/handoff_contacts.csv --out-dir <run_dir>`
  and go on to steps 1–2 (title and company-name cleaning happens there,
  for every list type).
