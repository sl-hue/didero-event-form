# Cowork test plan — outbound-list-cleaner skill

Tick each item as it passes. Anything that fails: paste what Claude said/did
into the build chat so the skill can be fixed.

## 0. Setup
- [ ] Upload `outbound-list-cleaner-skill.zip` as a skill (don't unzip it).
- [ ] Create a Cowork project; add `PROJECT.md` and `SPEC.md` as project files.
- [ ] Share a folder with the sample files (CBM M&A raw contacts + companies, Grata file).
- [ ] HubSpot connector connected in Cowork.
- [ ] Clay connector points at the **team** workspace (335212), not "Samantha's Workspace" — only matters if you ever use it; step 5 is manual.

## 1. Start of a run
- [ ] Skill triggers from a plain request ("clean this list for HubSpot").
- [ ] First thing it does: model check (Opus 5.x / Fable). Try once on another model — it should stop and ask you to switch.
- [ ] It asks which step to start from when that's unclear.
- [ ] It creates a run folder named after the list inside your shared folder.

## 2. HubSpot token (private app)
- [ ] `check-token` fails cleanly when no token is set.
- [ ] It explains the private app (read scopes: companies, contacts, lists), asks your consent in a decision box, never asks for the token in chat.
- [ ] Save the token in `hubspot_token.txt` → it verifies, moves it to the private file, **deletes** `hubspot_token.txt`.
- [ ] A wrong token is rejected with nothing saved.
- [ ] `check-token` then passes.

## 2b. One working file
- [ ] The run folder has one data file (`working.csv`), plus `history/` copies and, after step 4, `upload/`.
- [ ] Init reports any company values it harmonized across a company's rows.
- [ ] A flagged row is shown in the chat as a table; you say the change; Claude applies it and shows before → after, and waits for your OK before the next step.
- [ ] Nothing is removed unless you say so; removals are listed at export.
- [ ] Export/import prep refuses while a row is flagged.

## 3. Step 1 — email domain cleaning (CBM M&A raw contacts)
- [ ] Decision boxes for the doubtful rows (QXO/Kodiak, Sign & Awning → arch-fab.com).
- [ ] Web lookup for the 4 companies with no emails (Threaded Fasteners → tfmfg.com; Wagner; Bliffert; Gund).
- [ ] Every contact ends with an email domain; `zoomhubs.com` cleared; `afcind.com.com` fixed.
- [ ] Company domains: most-used domain primary, others in Additional Domains (`;`).
- [ ] A Gmail/Hotmail email is kept but its domain is never used.

## 4. Step 2 — normalization
- [ ] Names: "charul smardin" → "Charul Smardin"; McKee/DeBose untouched.
- [ ] LinkedIn: 2 wrong-person URLs blanked and listed in chat; last-name mismatches (Rich, Sanders) put to you in a decision box.
- [ ] Email check: Jordan Esco's `jwiggins@` cleared.
- [ ] Management Level converted (VP-Level → VP, C-Level → Executive).
- [ ] Company file: revenue ×1000 as "Revenue (in USD)", "Employees." prefix gone, industry "Retail- Home Improvement…", no Fax, only the list's companies.
- [ ] Output files have **no** notes/audit columns.

## 5. Step 3 — HubSpot duplicate check (fast path, with token)
- [ ] `run-plan` finishes in seconds (not minutes).
- [ ] Companies: ~52 single matches, FBM/SRS show as merged survivors, S.W. Anderson "Not in HubSpot"; false name hits (EMSI, CMC Group, Ferguson Box) dismissed.
- [ ] Review message lists candidates with HubSpot links; decision box asks for the survivor ID *after* you merge; it verifies via merged IDs and checks the survivor's name/domain.
- [ ] HubSpot Company Record ID column added; contact file company fields synced.
- [ ] Contacts: same flow → HubSpot Contact Record ID column.
- [ ] A contact HubSpot has at a different company is flagged (not dropped) and shown to you with both jobs and links.

## 6. Step 4 — import prep and after-import checks
- [ ] Mapping tables in chat (company, contact) with "Don't overwrite" suggestions; ZoomInfo IDs "Don't import"; Management Level → Employment Seniority; record IDs → Record ID.
- [ ] Type defaults to Prospect; it asks if the list doesn't look like prospects.
- [ ] Only two upload files, in `upload/`; "Not in HubSpot" companies have a blank Record ID (= create).
- [ ] After you import: prompts you to build a segment excluding Exclusion List A–F.
- [ ] `pull-segment` reads the segment; association fixes proposed in a table; after approval applied via connector; re-check shows none left. (Primary label already confirmed working.)
- [ ] Shared-domain case (e.g. Roche/Genentech on roche.com) goes to you as a question.
- [ ] Leftover duplicate check lists groups with links; location matches with state codes / `location` field.

## 7. Step 5 — Clay (guided)
- [ ] Both template links given; you choose; copy named `name_segment_date`.
- [ ] Tab guidance: ZoomInfo tab only for non-ZoomInfo lists; PDL then Import Objects from HubSpot; import = Contacts → segment → manual/one-time.
- [ ] Button order correct for each tab; waits for you per column.
- [ ] Won't start step 6 until you confirm enrichment is done.

## 8. Step 6 — BDR assignment
- [ ] Asks for the BDRs (default Noah, Davis, Bart); refuses non-BDRs.
- [ ] Read-only until approval; CSV columns and sort order as specified; each company has one BDR.
- [ ] Chat summary: per-BDR totals, owner changes, ties, open deals (AE-owned), free-mail company records.
- [ ] Imbalance > 10% and > 3 contacts → suggests specific companies, you decide.
- [ ] After approval: writes contact owners then company owners, verifies every record. (Try on a small test list first.)
- [ ] The run ends after step 6.

## 9. LinkedIn list (Sales Nav / Evaboot) — orchestrator flow
- [ ] `outbound-list-orchestrator` guesses "LinkedIn" from the columns and asks you to confirm.
- [ ] Load: locations split into city/state/country (metro areas → main city + state).
- [ ] Multiple jobs page opens in the Cowork panel; Open LinkedIn reuses one tab; Confirm and next; code → preview → your OK → saved.
- [ ] Company review (based / present in), then contacts grouped by company; Finish → code → preview → OK.
- [ ] Title / company name cleaning: safe fixes listed, judgment calls asked.
- [ ] Hand-off → `worksheet.py init` → steps 1–2 run as for ZoomInfo lists.
- [ ] ZoomInfo: maximum credits shown and your OK asked before any call; good / outdated / review / none shown; outdated records ignored.
- [ ] Source priority: names from ZoomInfo, title from LinkedIn, extra matching email in Additional Emails; ties asked.
- [ ] Consistency report (3 levels); prune lists the removed columns; steps 1–2 again show only new items.

## Known limits
- Setting the token needs your own terminal or the Cowork file route; the token never goes in chat.
- The Clay connector can't run workbooks; step 5 is always manual.
- Connector-only fallback (no token) works but is slow (~10–15 min per 60 companies).
