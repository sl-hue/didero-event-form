# Outbound list cleaner

Read `PROJECT.md` (status, plan, open questions) and `SPEC.md` (rules) before
working here. Keep `PROJECT.md` current at the end of each session.

- Sample and run files contain personal contact data and the repo is public:
  never commit anything under `samples/` except README/MANIFEST, or anything
  under `runs/`.
- Skills (each folder self-contained for Cowork: SKILL.md + references/ +
  scripts/ + config.json):
  - `skill/didero-outbound-lists-v2/` — current: start questions, then an
    independent run; stops only where the user acts; never writes to HubSpot.
  - `skill/didero-contact-sourcing/` — company-only lists (exhibitors,
    sponsors): finds the contacts, hands the file to v2.
  - `skill/didero-outbound-lists/` — v1, kept for reference; don't develop it.
