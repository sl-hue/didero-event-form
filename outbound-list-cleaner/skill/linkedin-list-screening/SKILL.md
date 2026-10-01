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
- The page shows one contact per card — name (linked to LinkedIn), title,
  company, countries, the three verdicts with reasons, and your
  recommendation — with **Keep**, **Exclude** and **Back** (keys Y, N, ←). The
  user can review all cards, or only those that need a look or would be
  excluded (clear passes are kept). Progress is saved in the page if it's
  reopened.
- When they finish, the page shows a short code (e.g.
  `LS1;170;X:8;K:1-7,9-170`). Ask them to paste it into the chat, then run
  `screen.py apply-decisions --run-dir <run_dir> --code "<code>"`, which
  records **Decision = keep / exclude** on every row of `screening.csv` —
  nothing is deleted.
- Show the result: counts, and every excluded contact (name, title,
  company). Wait for the user's OK before the next stage.

`screening.csv` is the state carried to the next stage: only rows with
Decision = keep go on.
