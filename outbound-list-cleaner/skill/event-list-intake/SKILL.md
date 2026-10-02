---
name: event-list-intake
description: Turn an event contact list (attendees, speakers, registrants — people already named, from a file, the event's website, screenshots or PDFs) into Didero's outbound list format — collect every source, fill first name / last name / job title / company, find each company's website and HQ by web research, then hand over to screening, ZoomInfo matching, LinkedIn URL finding, cleaning, HubSpot import, Clay and BDR assignment. Use whenever someone brings a conference / trade show / webinar / event list of people to prospect. Not for exhibitor or sponsor lists that only name companies (a separate skill, not built yet).
---

# Event list intake

The first stages for an **event contact list** — a list where the people are
already named. (Company-only lists, where we'd work out who to contact at each
company, are a different skill that isn't built yet: say so and stop.) The
orchestrator (`outbound-list-orchestrator`) runs these stages, then hands over
to `linkedin-list-screening` and `outbound-list-cleaner`.

Scripts are in this skill's `scripts/` folder. Create a run folder per event
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

**3. Company website, then HQ** — `company-researcher` (subagent), web research only
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
- Then `linkedin-list-screening`: `screen.py init --input <run_dir>/event_for_screening.csv --out-dir <run_dir>/screening --event`
  (skip its multiple-jobs step — event lists have no job count), company
  research + review (based / present in the target countries), contacts
  (titles). Event attendees' own location isn't known: run
  `screen.py check … --skip-contact-geo`. Then its step 6 (title / company
  name cleaning) and step 7 hand-off with `--list-type Event`.

**5. Event property in HubSpot**
At the import (outbound-list-cleaner step 4), the **Event Name** column maps to
the property the user chose. In Didero's HubSpot: **Event name** (text, any
value), **Lead Source - Event** (dropdown like `Events_2026_IMTS` — a new
event's option must be added in HubSpot first) and **LEAD SOURCE** = `Events`.
Confirm with the user every run.

The rest of the flow (ZoomInfo search → pick → enrich, LinkedIn URL finder,
source priority, cleaning, HubSpot) is in `outbound-list-cleaner` — the
orchestrator lists the order.
