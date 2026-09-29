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
| `skill/outbound-list-cleaner/` | Self-contained skill (SKILL.md + scripts). Zip this folder to install in Cowork |
| `skill/outbound-list-cleaner/scripts/email_domain.py` | Step 1 script (`prepare` / `apply`) |
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
| Later steps (, company file build, personalization, HubSpot record IDs, splitting, filtering) | Not yet specified — waiting on the user's walkthrough |

## Next up

1. User walks through the next step of the manual process; add it to
   `SPEC.md`, then build it.
2. Once the pipeline is complete, compare its output against the hand-cleaned
   samples (files 4 and 5) column by column.

## Open questions

- None right now.

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

## Using this in Cowork

- Create a Cowork project, e.g. "Outbound List Cleaner", and add
  `PROJECT.md` and `SPEC.md` as project files (or paste PROJECT.md into the
  project instructions).
- Set `HUBSPOT_PRIVATE_APP_TOKEN` on the device and connect the HubSpot
  connector before the first run.
- Install the skill: zip `skill/outbound-list-cleaner/` and upload it as a
  skill.
- Put sample/input files in the project's local folder, not in the repo.
- At the end of each session, update the Status, Next up, Open questions and
  Decision log sections above so the next chat can pick up from here.
