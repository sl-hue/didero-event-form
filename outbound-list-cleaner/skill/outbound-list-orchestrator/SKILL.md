---
name: outbound-list-orchestrator
description: Start here for any new outbound prospect list at Didero — figure out what kind of list it is (ZoomInfo export, LinkedIn Sales Navigator / Evaboot export, or event list), confirm with the user, and run the right skills in the right order through to the HubSpot import, Clay enrichment and BDR assignment. Use whenever someone brings a new list, file or export to clean, screen, prepare or import, even if they don't say where it came from.
---

# Outbound list orchestrator

The first thing that happens to every new list. It decides the list type,
then hands over to the skills below in order. It doesn't clean anything
itself.

## Step 0 — what kind of list is it?

1. Run `python3 scripts/detect_list_type.py <file> [<company file>]`. It
   reads only the header row and returns its guess with the columns that
   gave it away.
2. **Always confirm with the user** (one multiple-choice question): show the
   guess and the evidence, options: ZoomInfo export / LinkedIn (Sales Nav or
   Evaboot) export / Event list. Never start on a guess.

## The flows

**ZoomInfo export** → `outbound-list-cleaner`, steps 1–6 as written there.

**LinkedIn (Sales Nav or Evaboot)**:

| # | Stage | Skill |
|---|---|---|
| 1 | Load the list | `linkedin-list-screening` step 1 |
| 2 | Multiple current jobs — the user sets each person's real title and company | `linkedin-list-screening` step 2 |
| 3 | Research + review companies (based or present in the target countries), then contacts | `linkedin-list-screening` steps 3–5 |
| 4 | Title and company name cleaning | `linkedin-list-screening` step 6 |
| 5 | Hand-off into the working file (contacts + companies) | `linkedin-list-screening` step 7 |
| 6 | Steps 1–2 (email domains, normalization) | `outbound-list-cleaner` |
| 7 | ZoomInfo pull — tell the user the maximum credits first | `outbound-list-cleaner` — LinkedIn lists, stage 7 |
| 8 | Pick the source per field | `outbound-list-cleaner` — LinkedIn lists, stage 8 |
| 9 | Consistency: within a contact → across a company's contacts → contacts ↔ companies | `outbound-list-cleaner` — LinkedIn lists, stage 9 |
| 10 | Prune columns | `outbound-list-cleaner` — LinkedIn lists, stage 10 |
| 11 | Steps 1–2 again (only what changed is shown) | `outbound-list-cleaner` |
| 12 | HubSpot duplicates → import → Clay → BDRs (steps 3–6) | `outbound-list-cleaner` |

Stop after each stage, show the user what changed and wait for their OK
before the next one.

**Event list** → not built yet. Tell the user and stop.

## Before you start

Same checks as `outbound-list-cleaner`: Opus 5.x or Fable, HubSpot connector
and web search enabled. The list contains personal data: keep it on the
user's device; never publish it.
