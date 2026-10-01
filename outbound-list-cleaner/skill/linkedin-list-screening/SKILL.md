---
name: linkedin-list-screening
description: Screen a LinkedIn-sourced prospect list (LinkedIn, Sales Navigator, Evaboot or similar exports) before it goes into Didero's outbound-list-cleaner — research and review every company and job title, check companies and contacts against the target countries, and let the user keep or exclude each contact in a flashcard review. Use whenever someone brings a list that did not come from ZoomInfo, or asks to screen, filter, qualify or review a LinkedIn list's companies, titles or geography.
---

# LinkedIn list screening

The first stage for any list that wasn't built in ZoomInfo. It decides **who
stays on the list**; `outbound-list-cleaner` then cleans and imports the
survivors. More stages for LinkedIn lists will be added after this one.

## Before you start

Same as `outbound-list-cleaner`: run on Opus 5.x or Fable (stop and ask the
user to switch otherwise), and check that web search is available (the
company research needs it). Scripts are in this skill's `scripts/` folder;
defaults are in `config.json`. Create a run folder per list in the user's
working folder (`<list>_<date>/`). The list contains personal data: keep it
on the user's device; never publish it.

## Steps and sub-agents

**1. Load the list** — `screen.py init --input <file> --out-dir <run_dir>`
builds the one screening file, `<run_dir>/screening.csv`: the original
columns plus Row ID, Contact, Title, Company, Contact Country, Company Country
and the verdict columns. It recognises common LinkedIn / Sales Navigator /
ZoomInfo column names; if it can't find the name, title or company column, ask
the user which column holds it. If the file has pre-filter columns (e.g.
`Matches Filters`), ask the user whether to screen all rows or only some.

**2. Research and review companies and job titles**
- `company-researcher` (subagent) — for each company: what it does, HQ
  country, size, and whether it fits Didero's ICP (North American and UK/IE
  manufacturers and physical-goods companies with real supply chains — use
  the `didero-icp-check` skill's criteria). Web search only; don't spend paid
  enrichment credits without asking. Write the result as
  `{"<company>": {"fit": "fit|unclear|no", "reason": "…", "hq_country": "…"}}`
  and run `screen.py apply-research --run-dir <run_dir> --file research.json`.
- `title-reviewer` (subagent) — `screen.py check` (step 3) gives every title a
  first-pass verdict from keywords and seniority (`config.json`). Review every
  title the keywords didn't pass: many target roles use other words
  ("Integrated Supply", "Commodities", "Procure to Pay", "MRO"). Write
  `{"<Row ID>": {"fit": "…", "reason": "…"}}` and run
  `screen.py set-title --run-dir <run_dir> --file title_reviews.json`.

**3. Geography** — `geo-checker` (subagent)
- **Ask the user**, as two separate questions, which countries the
  **companies** (HQ) and the **contacts** (where the person is) must be in.
  Defaults if they don't specify: United States, Canada, United Kingdom
  (England, Scotland, Wales, Northern Ireland) and Ireland — contacts the same
  as companies.
- Run `screen.py check --run-dir <run_dir> --company-countries <…> --contact-countries <…>`.
  It also sets each row's recommendation: **keep** (title, company and
  geography all fit), **exclude** (any one is not a fit) or **review**
  (anything unclear). Contacts with no recognisable country are `unclear` —
  look them up (LinkedIn location, company HQ) before the review.
- Report the counts (`screen.py summary`).

**4. User review — flashcards** — `screening-reviewer` (subagent)
- Stop here and let the user decide. Run
  `python3 scripts/flashcards.py build --run-dir <run_dir> --title "<list name>"`
  and open `<run_dir>/review.html` for the user in the Cowork / Claude Code
  window (send the file; it's a local page, never published).
- **One card per company** with all its contacts: the company verdict once,
  then each person's title and geography verdicts and your recommendation.
  **Keep all / Exclude all** (keys Y, N), or ✓ / ✗ per person then
  **Confirm as marked** (Enter). Moving is separate from answering:
  **Previous / Next** (← →) and a company list beside the card (status dots,
  "!" for needs a look, search) let the user look around and see patterns
  before deciding. The start screen shows **all the data** in a searchable
  table (filters: everyone / needs a look / hit by a rule), also one click
  away from every card. The user can go through every company, or only
  companies with someone who needs a look or would be excluded (clear passes
  are kept). Progress is saved in the page if it's reopened.
- **Country rules bar** (top of the page): the user types a country, picks
  **Include only** or **Exclude**, and **Company / Contact / Both**. Any case
  or common spelling matches ("united states", "USA", "scotland" → United
  Kingdom). If the page isn't sure (typos, "CA", "Georgia", a state name) it
  asks "did you mean…" and never guesses; an include rule nobody on the list
  matches asks before it's added. A person's own ✓/✗ always beats a rule.
  Contacts with an unknown country are never touched by a rule.
- **Final review**: when the cards are done the page shows every contact,
  grouped by company, with what changed highlighted — yellow where the result
  differs from your recommendation or came from a rule, blue where you left it
  to the user — and an **edit** link on every company. When they approve it
  shows a code (e.g. `LS1;170;X:9-11,153;K:1-8,12-152,154-170;R:-c:Canada`).
- Ask them to paste the code into the chat, then run
  `screen.py apply-decisions --run-dir <run_dir> --code "<code>"`. This only
  **previews**: show the user its table of changes (company, contact, title,
  your recommendation, final, why) and the not-answered contacts. If they want
  changes, they edit in the page and paste a new code.
- **Only after the user's OK** run `screen.py apply-decisions --run-dir <run_dir> --confirm`,
  which writes **Decision** (keep / exclude) and **Decision Note** (why) on
  every row of `screening.csv` and saves the rules in `geo_rules.json` —
  nothing is deleted.
- If the user gives countries in the chat instead, the same matching applies:
  `screen.py check` stops with "not sure which country is meant … did you
  mean …" — ask the user, never pick one yourself.

`screening.csv` is the state carried to the next stage: only rows with
Decision = keep go on.
