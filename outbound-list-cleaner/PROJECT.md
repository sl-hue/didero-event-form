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
| Later steps (column mapping/formatting, company file build, personalization, HubSpot record IDs, splitting, filtering) | Not yet specified — waiting on the user's walkthrough |

## Next up

1. User answers the open questions below.
2. User walks through the next step of the manual process; add it to
   `SPEC.md`, then build it.
3. Once the pipeline is complete, compare its output against the hand-cleaned
   samples (files 4 and 5) column by column.

## Open questions

- **Scope of "use the ultimate owner":** should operating subsidiaries with
  their own brand also take the parent's domain as primary? E.g. Foundation
  Building Materials was acquired by Lowe's — should FBM's `Company Domain`
  become `lowes.com`, or does the rule only apply when contacts at the same
  company record use both domains (like QXO/Kodiak)? Current behaviour: the
  latter.
- **Company file `Email Domain` column:** file 5 has a single `Email Domain`
  column; the new format replaces it with `Company Domain` +
  `Additional Domains`. Confirm the exact HubSpot column names.

## Decision log

- 2026-09-28 — Sample data kept out of git (repo is public).
- 2026-09-28 — Step 1 rules confirmed: website is never the email domain;
  match check is by Claude's judgment of domain vs company name, not email
  validity; doubtful rows go to the user; web backfill uses general inboxes,
  falling back to public staff addresses.
- 2026-09-28 — All contact domains go on the company: primary in
  `Company Domain` (ultimate owner's), others in `Additional Domains`
  (`;`-separated). Subsidiary emails are kept, not cleared.

## Using this in Cowork

- Create a Cowork project, e.g. "Outbound List Cleaner", and add
  `PROJECT.md` and `SPEC.md` as project files (or paste PROJECT.md into the
  project instructions).
- Install the skill: zip `skill/outbound-list-cleaner/` and upload it as a
  skill.
- Put sample/input files in the project's local folder, not in the repo.
- At the end of each session, update the Status, Next up, Open questions and
  Decision log sections above so the next chat can pick up from here.
