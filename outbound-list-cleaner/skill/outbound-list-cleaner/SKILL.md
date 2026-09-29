---
name: outbound-list-cleaner
description: Clean and standardize outbound prospecting lists (ZoomInfo, Clay, HubSpot, lemlist exports) into Didero's two-file HubSpot upload format — a contact file and a matching company file per list. Use whenever someone gives you a raw contact or company export to clean, enrich, or prepare for a HubSpot/lemlist upload, or asks to fix email domains so contacts associate with the right company.
---

# Outbound list cleaner

Status: **steps 1 (email domain cleaning), 2 (normalization), 3 (HubSpot duplicate check), 4 (HubSpot import and post-import checks) and 5 (Clay enrichment, guided).** Later steps are being
specified; see `PROJECT.md` and `SPEC.md` in the project repo for the full plan.

Every list produces two files: a contact file and a company file containing
only that list's companies. A sublist gets its own company file.

## Before you start (do this first, every run)

1. **Model check.** This workflow needs a top-tier model: Opus 5 (any 5.x)
   or Fable. Older or smaller models tend to take shortcuts on the judgment
   calls. Before running any step, tell the user this, and if you are not
   running on Opus 5.x or Fable, stop and ask them to switch models (e.g.
   `/model` in Claude Code, or the model picker in Cowork) and start again.
2. **HubSpot setup on this device.** Confirm both:
   - The **HubSpot connector** is connected (used to verify merges and look
     up properties).
   - The **HubSpot private app is authorized on this device.** Run
     `python3 scripts/hubspot_match.py check-token`. If it fails, get the
     user to authorize it before step 3:
     1. Explain: the script reads HubSpot companies and contacts directly
        with their team's private app (read scopes
        `crm.objects.companies.read`, `crm.objects.contacts.read`,
        `crm.lists.read`); the token
        is stored only on their device and never shown in chat.
     2. Ask with the multiple-choice tool whether they authorize this.
     3. Then, depending on where you're running:
        - **Claude Code on their computer:** run
          `python3 scripts/hubspot_match.py setup-token --open-terminal`. A
          terminal window opens where they confirm and paste the token
          (hidden input). Wait for them to say they're done.
        - **Cowork, or no terminal:** ask them to create a text file named
          `hubspot_token.txt` in the folder they've given Cowork access to,
          containing only the token, and tell you when it's saved. Then run
          `python3 scripts/hubspot_match.py setup-token --from-file <that path> --authorized`,
          which checks the token, moves it to the private token file and
          deletes `hubspot_token.txt`.
        - **Claude Code on the web:** they can instead add
          `HUBSPOT_PRIVATE_APP_TOKEN` as an environment variable in the
          environment's settings (picked up by a new session).
     4. Re-run `check-token`.
     **Never** ask for the token in chat, and never read, print or open the
     token file yourself. If the user pastes a token into the chat anyway,
     don't use it; tell them to rotate it in HubSpot and use the steps above.
     If they decline, step 3 falls back to the connector, which is many
     times slower (roughly 10–15 minutes per 60 companies instead of
     seconds).

## Step 1 — Email domain cleaning

Goal: every contact has an email domain matching its company's domain so
HubSpot associates them. The website is **never** used as the email domain.

1. **Prepare.** Run
   `python3 scripts/email_domain.py prepare <contacts.csv> --out-dir <run_dir>`.
   It normalizes emails (lowercase domain, fixes doubled TLDs like `.com.com`)
   and writes `<run_dir>/review.json`: one entry per company/email-domain pair,
   plus companies where no contact has an email.

2. **Judge each pair.** Decide whether the email domain plausibly belongs to
   the contact's current company. Matches are often not literal — acronyms,
   tickers, shortened names (UFP Industries → `ufpi.com`, Builders FirstSource
   → `bldr.com`, EMS → `easternmetal.com`). This is not an email-validity check.
   - Clear match → `keep`.
   - Clear mismatch (a prior employer, a data-vendor placeholder such as
     `zoomhubs.com`) → `clear`.
   - Parent/child (subsidiary or acquired company, e.g. `kodiakbp.com` at
     QXO) → `keep`; it becomes an additional domain unless it is the most
     used one.
   - Anything doubtful → ask the user (step 3).
   If the ZoomInfo company name looks unrelated to the domain, check what
   company the domain actually belongs to before calling it a mismatch.

3. **Ask the user about doubtful rows.** Use the multiple-choice question tool
   (up to 4 questions per call; batch in rounds). For each row show: company,
   email domain, number of contacts, other domains at that company, why you
   think it does/doesn't match, and any parent/child relationship. Offer
   options such as keep / clear / map to parent, with your recommendation
   first. Treat free-text answers as rules to apply going forward.

4. **Web backfill.** For each company with no email at all, search the web for
   publicly listed general inboxes (info@, sales@, support@, help@, general@,
   marketing@, inquiry@ and variants, including location inboxes such as
   `infomobile@`). Use that domain. If none exists, publicly listed staff
   addresses are acceptable evidence. Always use the ultimate owner's domain.
   If the answer is unclear, ask the user.

5. **Write decisions.json** in the run dir:
   ```json
   {
     "pairs": {"<company_id>|<domain>": {"action": "keep|clear|map", "map_to": "...", "reason": "..."}},
     "web_domains": {"<company_id>": {"domain": "...", "source": "..."}},
     "primary_domains": {"<company_id>": {"domain": "...", "reason": "..."}}
   }
   ```
   Every pair in review.json needs an entry; the script refuses to run otherwise.
   `primary_domains` is only for overrides — e.g. the user's pick when
   review.json lists a company under `primary_ties`. By default the most used
   domain is primary.

6. **Apply.** Run
   `python3 scripts/email_domain.py apply <contacts.csv> --decisions <run_dir>/decisions.json --out-dir <run_dir>`.
   Outputs:
   - `contacts_step1.csv` — the input columns with `Email Address` and
     `Email Domain` cleaned, plus audit columns `Original Email`,
     `ZoomInfo Email Domain`, `Email Domain Source`, `Step 1 Notes`.
   - `company_domains_step1.csv` — per company: `Company Domain` (most used),
     `Additional Domains` (`;`-separated), `Domain Source`.

7. **Report** counts (own email / backfilled / web / cleared / fixed) and any
   company still without a domain.

## Step 2 — Normalization

Output files contain only upload columns: never add notes or flag columns.
Everything the user needs to review goes in the chat.

1. **Prepare.** Run
   `python3 scripts/normalize.py prepare --contacts <run_dir>/contacts_step1.csv --companies <zoominfo_company_export.csv> --out-dir <run_dir>`.
   It fixes name casing and strips credentials, and writes
   `review_step2.json` listing LinkedIn URLs whose slug doesn't contain the
   contact's first and last name.

2. **Judge each LinkedIn slug** (no live check):
   - Nickname (Bill/William, Pat/Patrick), initials (`jbsunderbruch`),
     credentials in the slug, or an obvious typo → `keep`.
   - Clearly a different person (both names differ) → `blank`.
   - First name matches, last name differs (possibly a married/maiden name)
     → ask the user with the multiple-choice tool: show name, company, job
     title and the URL, and offer Keep / Blank (they can type a corrected URL
     under "Other" → `replace`). The user checks LinkedIn themselves; you
     don't need to.

   Judge `email_review` the same way on the email's local part: nickname or
   initials → `keep`; clearly someone else's email → `clear` (the domain
   stays); last name differs → ask the user.

3. **Write `<run_dir>/decisions_step2.json`:**
   `{"linkedin": {"<ZoomInfo Contact ID>": {"action": "keep|blank|replace", "url": "...", "reason": "..."}},
     "email": {"<ZoomInfo Contact ID>": {"action": "keep|clear", "reason": "..."}}}`

4. **Apply.** Run
   `python3 scripts/normalize.py apply --contacts <run_dir>/contacts_step1.csv --companies <zoominfo_company_export.csv> --company-domains <run_dir>/company_domains_step1.csv --decisions <run_dir>/decisions_step2.json --out-dir <run_dir>`.
   Outputs `contacts_upload.csv`, `companies_upload.csv` (only the list's
   companies; revenue ×1000, `Employees.` prefix stripped, industry combined,
   website and domains synced from contacts), and `report_step2.json`.

5. **Report in chat:** dropdown values with no matching HubSpot option
   (`dropdown_values_not_matching`, e.g. a Management Level or Department
   value HubSpot's dropdown doesn't have), name fixes, blanked LinkedIn URLs (name, company,
   removed URL, reason), the user's last-name decisions, and any companies
   dropped or missing.

## Step 3 — HubSpot duplicate check

Claude cannot merge HubSpot records; the user merges manually and then tells
you the survivor. Companies first, then contacts. `S=scripts/hubspot_match.py`.

**Companies**
1. `python3 $S plan-companies --companies <run_dir>/companies_upload.csv --out-dir <run_dir>`
   writes `company_search_plan.json`.
2. Run the plan:
   `python3 $S run-plan --plan <run_dir>/company_search_plan.json --raw-dir <run_dir>/hs_companies`
   (uses the private app token; seconds). **Fallback only if no token:** run
   every search with the HubSpot connector's `search_crm_objects`
   (objectType, properties, limit, filterGroups or query as given; page with
   `offset`) and save each raw JSON response to `<run_dir>/hs_companies/NNN.json`,
   in a subagent so raw results don't flood the chat.
3. `python3 $S match-companies --companies <run_dir>/companies_upload.csv --raw-dir <run_dir>/hs_companies --out-dir <run_dir>`
   writes `company_matches.json` (per company: candidates with HubSpot URL,
   strength, reasons, domain, location, employees, revenue, contacts).
4. Judge the candidates. Drop obvious false positives from free-text name
   hits (different company, different place and size). Use firmographics for
   unclear cases.
   - No candidates → `null` (Not in HubSpot).
   - Exactly one strong candidate → record it, no question.
   - Two or more real candidates, or only a possible match → review with the user.
5. **Review with the user**, one company at a time:
   - In a chat message, list each candidate: HubSpot link, name, domain,
     location, contacts, created date, and why it matches.
   - Tell the user to open them and merge the duplicates in HubSpot
     themselves, one by one, into the record they want to keep.
   - Then ask with the multiple-choice tool: "After merging, which record
     survived?" Merging in HubSpot usually creates a **new record ID**, so the
     user typically types it under "Other"; offer "Not a duplicate / keep
     separate" where relevant. Up to 4 companies per call.
   - **Verify:** search `hs_object_id IN [new ID + old IDs]` with
     `hs_merged_object_ids`. The survivor must exist and list the merged-away
     IDs; if the old IDs still come back on their own, the merge isn't done —
     tell the user and ask again.
   - **Check the survivor's values:** HubSpot may keep the other record's
     name or domain (e.g. SRS Distribution merged into a record still named
     "Superior Distribution"). If the survivor's name or primary domain
     doesn't match the list, tell the user to fix it in HubSpot or to leave
     "Don't overwrite" unticked for those columns on import.
   - Dismiss name-only hits that are clearly other companies (different
     place and size, e.g. "EMSI" for EMS) without asking.
6. Write `<run_dir>/company_decisions.json`
   (`{"<ZoomInfo Company ID>": {"record_id": "..." | null, "note": "..."}}`) and run
   `python3 $S apply-companies --companies <run_dir>/companies_upload.csv --contacts <run_dir>/contacts_upload.csv --contacts-step1 <run_dir>/contacts_step1.csv --decisions <run_dir>/company_decisions.json`.
   This adds `HubSpot Company Record ID` and syncs Company Name / Website /
   Company HQ Phone into the contact file.

**Contacts** — same loop:
1. `python3 $S plan-contacts --contacts <run_dir>/contacts_upload.csv --companies <run_dir>/companies_upload.csv --out-dir <run_dir>`
   (LinkedIn URL on `lgm_linkedinurl`, email, last name, and everyone
   associated with the list's HubSpot companies).
2. `python3 $S run-plan --plan <run_dir>/contact_search_plan.json --raw-dir <run_dir>/hs_contacts`
   (connector fallback as above if there's no token).
3. `python3 $S match-contacts --contacts <run_dir>/contacts_upload.csv --companies <run_dir>/companies_upload.csv --contacts-step1 <run_dir>/contacts_step1.csv --raw-dir <run_dir>/hs_contacts --out-dir <run_dir>`
4. Judge, review with the user (same merge-first flow), write
   `contact_decisions.json`, then
   `python3 $S apply-contacts --contacts <run_dir>/contacts_upload.csv --decisions <run_dir>/contact_decisions.json`
   to add `HubSpot Contact Record ID`.

## Step 4 — HubSpot import

The user runs the import in HubSpot; you prepare it and walk them through it.

1. **Choose Type.** Default `Prospect`. Look at the list: if the companies
   don't look like prospects (partners, vendors, existing customers), ask the
   user which Type fits before continuing.
2. Run
   `python3 scripts/hubspot_import.py prepare --companies <run_dir>/companies_upload.csv --contacts <run_dir>/contacts_upload.csv --raw-dir <run_dir>/hs_companies --type Prospect --out-dir <run_dir>`.
   It adds the Type column, writes `companies_import.csv` / `contacts_import.csv`
   (record IDs blanked where "Not in HubSpot"), `import_mapping.md` and
   `report_step4.json`.
3. **In chat**, paste both tables from `import_mapping.md` and tell the user:
   - import the company file first, then the contact file;
   - map each column to the HubSpot property shown and set "Don't import
     column" where indicated;
   - tick "Don't overwrite" on any column where they want to keep what's
     already in HubSpot (the table suggests some);
   - how many rows will update vs. create, and any existing records whose
     Type differs (from `report_step4.json`) — suggest "Don't overwrite" on
     Type for those.
4. After the company import, the user can run the contact import; contacts
   associate to companies through the company domain.
5. **If HubSpot reports import errors**, tell the user to either fix the
   value in the file and re-import those rows, or edit the records directly
   in HubSpot. If a dropdown value keeps failing, check the property's
   current options with the HubSpot connector (`get_properties`) and add the
   conversion to `DROPDOWNS` in `scripts/normalize.py` so step 2 fixes it
   next time.

## Step 4 (after the import) — segment, associations, leftover duplicates

Once the user has imported both files, the files are finished: from here
on the work happens in HubSpot and the files are not updated again.
`P=scripts/post_import.py`.

1. **Build the segment.** Prompt the user to create a contact segment of the
   contacts they just imported, and to exclude every list in `config.json`
   (`exclusion_lists`: "Exclusion List A" … "Exclusion List F"; they can
   search for each by name in HubSpot). Ask for the segment's name when it's
   done. (You may offer to create it with the connector's `manage_segment`
   — e.g. `IN_LIST(import = '<id>') AND NOT IN_LIST(list = <id>) …`, ids
   looked up, never guessed — only with their approval.)
2. **Pull it.** `python3 $P pull-segment --segment "<name or list ID>" --out-dir <run_dir>`
   reads every contact in the segment, its company associations (with the
   primary flag) and those companies → `segment_snapshot.json`.
3. **Fix associations** (Claude proposes, user approves, Claude applies):
   `python3 $P review-associations --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`
   → `association_fixes.json`:
   - **No company** → associate with the company that owns the contact's
     domain, as primary.
   - **Several companies** (usually an existing contact that got another
     company) → make the company owning the contact's domain (the list's
     company) primary; the others stay as secondary.
   - `ask_user`: cases the script can't decide (no company with that domain,
     several candidates). Ask the user with the multiple-choice tool, one
     contact per question, with contact and company links.
   Show the proposed fixes as a table (contact, email, current companies,
   action, company, reason) and get approval, then send `connector_batches`
   with the connector's `manage_crm_objects` (`updateRequest`, 10 per call).
   Afterwards re-run `pull-segment` + `review-associations` to confirm
   nothing is left; if the "Primary" label is rejected, tell the user to set
   primary on those contacts in HubSpot and list them.
4. **Leftover company duplicates.**
   `python3 $P find-dupes --snapshot <run_dir>/segment_snapshot.json --out-dir <run_dir>`
   checks every company associated with the segment's contacts against all
   of HubSpot: same or variant domain (other TLD, subdomain, hyphen), same
   LinkedIn page, same phone, similar name in the same location (state codes
   and names treated as equal, e.g. TX = Texas) → `company_dupes.json`.
   Tell the user how many companies have possible duplicates, then list each
   group in chat with HubSpot links, location, size, contacts and reasons.
   Dismiss obvious false positives yourself. The user merges in HubSpot and
   gives the survivor ID (usually a new ID); verify via
   `hs_merged_object_ids` and check the survivor's name/domain, as in step 3.

## Step 5 — Enrichment in Clay (user-run, guided)

Assumes the segment exists, duplicates are merged and every contact is
associated with its company. This step happens in Clay, not HubSpot. The
Clay connector can't open, duplicate or run workbooks, so the user does it;
you walk them through it one tab at a time and check the result in HubSpot.
Clay writes results back to HubSpot itself — no files are imported or
exported.

1. **Baseline.** `python3 scripts/post_import.py coverage --segment "<segment>" --label before --out-dir <run_dir>`
   (how many contacts have email, work direct phone, mobile, LinkedIn URL,
   job title).
2. **Pick the workbook** (team workspace; links in `config.json`
   `clay_workbooks`):
   - European contacts → the Europe template (they're often missing from
     ZoomInfo).
   - American and other global contacts → the Americas/global template.
   Remind the user that each button run spends Clay credits.
3. **Pick the tabs:**
   - **Tab 1 "ZoomInfo"** — only if the list was *not* built in ZoomInfo
     (e.g. pulled from LinkedIn). Skip it for ZoomInfo lists.
   - **Tab 2 "PDL"** — always; the most reliable provider, so it runs first.
   - **Tab 3 "Import Objects from HubSpot"** — always, after PDL; a mix of
     other providers for what PDL didn't find.
4. **Importing into a tab** (first column of each tab): import objects →
   select **Contacts** → select the segment → schedule **Manual / one-time
   import only**, so the list doesn't keep updating in the background.
5. **Walk the user through the buttons, one at a time.** Wait for each
   column to finish before the next; ask them to confirm, and to tell you
   about errors.
   - **ZoomInfo tab** (only when used): import the segment → **Enrich
     Contact** → **Update Object**.
   - **PDL tab:** import the segment again → **Verify Email** → **Work
     Email** → **Enrich Person** → **LinkedIn URL** → **Update Object**.
   - **Import Objects from HubSpot tab:** **Import Object** → **Mobile Phone**
     enrichment → **Update Object**.
6. **Check the write-back.** After the last **Update Object**, run
   `python3 scripts/post_import.py coverage --segment "<segment>" --label after --out-dir <run_dir>`
   and report the change per field. If nothing changed, the Update Object
   step likely didn't run or failed — ask the user to check that column.

## Data handling

These files contain personal contact data. Never commit them to a repository
or publish them; keep inputs and run outputs in local, git-ignored folders.
