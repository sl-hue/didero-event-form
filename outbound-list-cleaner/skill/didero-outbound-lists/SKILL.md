---
name: didero-outbound-lists
description: Didero's outbound prospect lists, v2 — the user gives the file and answers a few questions at the start (end state with or without BDR owners, countries, BDRs and split, ZoomInfo credits); Claude works out the list type and enrichment path itself (ZoomInfo export, LinkedIn Sales Navigator / Evaboot export, or a list of named contacts such as event attendees), then runs on its own, screening, researching, cleaning, matching ZoomInfo, checking HubSpot for duplicates (read-only) and building the company and contact upload files with owner columns, stopping only where the user acts (import, segment, Clay). Use whenever someone brings a contact list, export or attendee list to clean, enrich, dedupe, prepare for HubSpot import or assign to BDRs. Company-only lists go to didero-contact-sourcing.
---

# Didero outbound lists (v2)

**The user gives the file and answers the start questions; after that the
run is independent.** It stops only at steps where the user has to act
(HubSpot import, building the segment, Clay, fixing anything in HubSpot the
checks find). Everything else, including every judgment call, is Claude's.

Lists that name **companies but no people** (exhibitors, sponsors, target
accounts) are not for this skill: use **didero-contact-sourcing**, which
finds the contacts and hands a contact file back here.

All scripts are in `scripts/` and all settings in `config.json`, at this
skill's root. Run them with the skill folder's absolute path. Make a run
folder per list in the user's working folder (`<list>_<date>/`). The list
contains personal data: keep it on the user's device; never publish it.

## Start (in this order, all before any work)

**1. Checks — the only valid reasons to stop before doing anything.**
Run `python3 scripts/preflight.py --list-type <path, or "unknown" if not yet known> --run-dir <run_dir> --user "<name or email if known>" --observed '<json>'`
with what you see: `{"model": "<your model id>", "effort": "<if you know it>",
"connectors": {"hubspot": true|false, "zoominfo": true|false, "web_search":
true|false, "clay": true|false}}` (HubSpot: `query_crm_data` in your tools;
ZoomInfo: `enrich_contacts`). It stops the run only when **HubSpot or
ZoomInfo isn't connected**, or the model isn't **Opus 5.5 or newer**
(Fable passes; effort should be medium or higher — say so if you can't
tell). Missing → tell the user exactly what to change (Settings →
Connectors, or the model picker) and stop. Otherwise show the result in one
line, including its "log:" line.

**2. Claude determines the list type and enrichment path — no question.**
`python3 scripts/setup.py start --file <list> [--file <second file>] --run-dir <run_dir>`
reads the columns and filled values and picks the path:
- **zoominfo** — a ZoomInfo export (no ZoomInfo calls needed);
- **linkedin** — a Sales Navigator / Evaboot export (screening, then a
  ZoomInfo pull for contacts and companies, merged field by field);
- **contacts** — names and companies without ZoomInfo / LinkedIn data, e.g.
  event attendees (HubSpot + web for companies, screening, ZoomInfo search
  and enrichment of the matched people).
Say what it found in one line ("This is a LinkedIn Sales Navigator export:
153 contacts at 141 companies → LinkedIn path"). A company-only list → tell
the user it belongs to didero-contact-sourcing. Only if the file has no
recognisable names and companies, ask which columns hold them.

**3. The start questions — all at once, in one multiple-choice call.**
`setup.py start` prints them ready for the multiple-choice tool:
1. **End state:** upload files only, or upload files + BDR owners (even
   split — all contacts of one account go to one BDR first — or another
   split the user describes). Either way the result is the same company and
   contact CSVs; with BDRs they carry Contact Owner / Company Owner columns.
2. **Countries:** US + Canada / North America + English-speaking (US,
   Canada, UK, Ireland, Australia, New Zealand) / other (the user types every
   country). Companies are narrowed first (headquartered **or present** in
   these countries), then contacts at the companies that stay.
3. **BDRs** (if assigning): who gets the list (default pool in `config.json`).
4. **ZoomInfo credits** (LinkedIn and contacts paths): approve the maximum
   for this file once; the run never stops for credits again.
Then `python3 scripts/setup.py save --run-dir <run_dir> --answers '<json>'`
and `python3 scripts/progress.py start --run-dir <run_dir>`. Tell the user in
one short message what will happen and where it will stop for them — then
start.

## The run

`progress.py` holds the steps for the chosen path. **Before every step run
`python3 scripts/progress.py next --run-dir <run_dir>` and follow what it
prints**: the step's full instructions (read fresh from the reference
pages), whether it's a stop, pages to open in the browser and the standing
rules. After the step, `progress.py done --step <id>` and go straight on.
Never do a step from memory; after any interruption run `progress.py
status` and `next`.

| Path | Steps |
|---|---|
| zoominfo | 1 email domains · 2 normalization + cleaning · 3 HubSpot duplicates (read-only) · 4 BDR owners* · **5 import** · **6 segment + checks** · **7 Clay** |
| linkedin | load · research + titles + countries → keep / exclude · hand-off · 1–2 · ZoomInfo pull · source per field · consistency · prune · 1–2 again · 3 · 4* · **5** · **6** · **7** |
| contacts | load · website + HQ (HubSpot first) · screening + hand-off · 1–2 · ZoomInfo search → pick → enrich · source per field, consistency, prune · 1–2 again · Lead Source (events) · 3 · 4* · **5** · **6** · **7** |

\* only when the end state includes BDR owners. **Bold** = the user acts.
ZoomInfo stages are skipped when credits weren't approved.

Reference pages (`progress.py next` prints the right sections):
`references/zoominfo-lists.md` (steps 1–7 and the ZoomInfo stages),
`references/screening.md`, `references/event-lists.md` (named-contact lists).

## Rules for the whole run

- **No questions after the start.** Judgment calls (domains, LinkedIn slugs,
  company names, titles, primary industry, keep / exclude, HubSpot record
  picks, ZoomInfo matches, ties) are Claude's, made with the rules in each
  step and written one line each in `<run_dir>/decisions.md`. The end-of-run
  summary shows them.
- **Stop only where the user acts.** Everywhere else: report in a line or
  two and go on — no OK gates.
- **Claude never writes to HubSpot.** The connector only reads: no creating,
  updating, associating, merging, or owner changes, not even "just a few".
  Everything that changes HubSpot goes into the upload files (owners
  included) or is done by the user from a list Claude gives them.
- **Open HubSpot / Clay in the browser window** whenever the user has to act
  there (import page, segments, Clay template), not just a link.
- **ZoomInfo calls run in parallel** through `scripts/zi_workers.py` and
  sub-agents started all at once; within the credit cap from the start.
- **Cleaning is step 2, every path:** contact names, company names and job
  titles are rewritten there; the export refuses if step 2 didn't run, if
  ZoomInfo was pulled but not merged, or if BDR owners were chosen but not
  assigned.
- **Upload format before step 5, every run — checked and fixed by the
  skill itself, never a stop:** same columns in the same order, every value
  in the one format, websites and domains on both files. Duplicate email →
  it stays with the contact whose name matches it more closely (then more
  data), the other contact stays without it;
  invalid email → blanked only if it has no domain; Sales Navigator links are
  fine; two companies with one website / HubSpot record → one company; any
  other invalid value → blank cell. Every fix goes in `decisions.md`.
- **Every step runs, in order — no skipping.** `progress.py done` checks the
  step's own output (run log, files) and refuses a step that didn't run; the
  export also refuses if steps 1–2 (or the ZoomInfo merge, or the BDR step
  when chosen) never ran.
- **Import step:** always send the two upload files, `HOW_TO_IMPORT.md` and
  (with BDRs) `bdr_assignment.csv`, and paste the instructions in the chat.
- **Clay step:** start with `scripts/clay_guide.py` and paste its output.
