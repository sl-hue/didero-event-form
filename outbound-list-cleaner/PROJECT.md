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
| Step 2 — Normalization (names, LinkedIn, company fields, column pruning) | Specified (draft in SPEC.md); questions out to user |
| Later steps (, company file build, personalization, HubSpot record IDs, splitting, filtering) | Not yet specified — waiting on the user's walkthrough |

## Next up

1. User walks through the next step of the manual process; add it to
   `SPEC.md`, then build it.
2. Once the pipeline is complete, compare its output against the hand-cleaned
   samples (files 4 and 5) column by column.

## Open questions

- Step 2: name casing edge cases, LinkedIn liveness method and action, website changes, column list, industry separator (see chat of 2026-09-28).

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

## Using this in Cowork

- Create a Cowork project, e.g. "Outbound List Cleaner", and add
  `PROJECT.md` and `SPEC.md` as project files (or paste PROJECT.md into the
  project instructions).
- Install the skill: zip `skill/outbound-list-cleaner/` and upload it as a
  skill.
- Put sample/input files in the project's local folder, not in the repo.
- At the end of each session, update the Status, Next up, Open questions and
  Decision log sections above so the next chat can pick up from here.
