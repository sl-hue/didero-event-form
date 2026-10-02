---
name: didero-outbound-lists
description: Didero's outbound prospect lists, start to finish — work out what kind of list it is (ZoomInfo export, LinkedIn Sales Navigator / Evaboot export, event contact list, or company-only event list), confirm with the user, then screen, research, clean and standardize it, match ZoomInfo, find LinkedIn URLs, check HubSpot for duplicates, prepare the HubSpot import, fix associations after import, guide the Clay enrichment and assign BDR owners. Use whenever someone brings a list, file, export, exhibitor list or attendee list to clean, screen, enrich, dedupe, import into HubSpot, enrich in Clay or hand out to BDRs — even if they don't say where it came from.
---

# Didero outbound lists

One skill for every list type. This page decides the list type and the order
of the steps; the detailed instructions for each step are in three reference
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
   reads only the header row and returns its guess with the columns that
   gave it away.
2. **Always confirm with the user** (one multiple-choice question): show the
   guess and the evidence, options: ZoomInfo export / LinkedIn (Sales Nav or
   Evaboot) export / Event list. Never start on a guess.

## The flows

**ZoomInfo export** → `references/zoominfo-lists.md`, steps 1–6.

**LinkedIn (Sales Nav or Evaboot)**:

| # | Stage | Skill |
|---|---|---|
| 1 | Load the list | `references/screening.md` step 1 |
| 2 | Multiple current jobs — the user sets each person's real title and company | `references/screening.md` step 2 |
| 3 | Research + review companies (based or present in the target countries), then contacts | `references/screening.md` steps 3–5 |
| 4 | Title and company name cleaning | `references/screening.md` step 6 |
| 5 | Hand-off into the working file (contacts + companies) | `references/screening.md` step 7 |
| 6 | Steps 1–2 (email domains, normalization) | `references/zoominfo-lists.md` |
| 7 | ZoomInfo pull — tell the user the maximum credits first | `references/zoominfo-lists.md` — LinkedIn lists, stage 7 |
| 8 | Pick the source per field | `references/zoominfo-lists.md` — LinkedIn lists, stage 8 |
| 9 | Consistency: within a contact → across a company's contacts → contacts ↔ companies | `references/zoominfo-lists.md` — LinkedIn lists, stage 9 |
| 10 | Prune columns | `references/zoominfo-lists.md` — LinkedIn lists, stage 10 |
| 11 | Steps 1–2 again (only what changed is shown) | `references/zoominfo-lists.md` |
| 12 | HubSpot duplicates → import → Clay → BDRs (steps 3–6) | `references/zoominfo-lists.md` |

Stop after each stage, show the user what changed and wait for their OK
before the next one.

**Event list** — first ask: are the **people already named** (attendees,
speakers, registrants) — the table below — or does it only name companies
(exhibitors, sponsors)? For company-only lists:

| # | Stage | Skill |
|---|---|---|
| 1 | Collect the companies (+ any job titles) from every source | `references/event-lists.md` — company-only, step 1 |
| 2 | Web research: website, HQ city / state / country, employees / revenue (re-check what the list says) | step 2 |
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
| 3 | Company website, then HQ city / state / country (web research) | `references/event-lists.md` step 3 |
| 4 | Screening: companies (based / present in) → contacts (titles), contact geography skipped | `references/screening.md` steps 1, 3–5 (`--skip-contact-geo`) |
| 5 | Title and company name cleaning | `references/screening.md` step 6 |
| 6 | Hand-off into the working file | `references/screening.md` step 7 (`--list-type Event`) |
| 7 | Steps 1–2 (email domains, normalization) | `references/zoominfo-lists.md` |
| 8 | ZoomInfo: free candidate search → pick best (unclear → user) → enrich picked (max credits first) | `references/zoominfo-lists.md` — event lists, ZoomInfo |
| 9 | LinkedIn URL finder for people ZoomInfo couldn't match (browser + card page) | `references/zoominfo-lists.md` — event lists, LinkedIn finder |
| 10 | Source per field, consistency, prune | `references/zoominfo-lists.md` — LinkedIn lists, stages 8–10 |
| 11 | Steps 1–2 again (only what changed is shown) | `references/zoominfo-lists.md` |
| 12 | HubSpot duplicates (existing record IDs go in the upload) → import with the event property → Clay → BDRs | `references/zoominfo-lists.md` steps 3–6 |

## Before you start

Same checks as in `references/zoominfo-lists.md` ("Before you start"): Opus 5.x or Fable, HubSpot connector
and web search enabled. The list contains personal data: keep it on the
user's device; never publish it.
