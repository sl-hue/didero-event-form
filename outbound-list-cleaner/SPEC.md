# Outbound list cleaner — process spec

Captured from the user's walkthrough. This is the source of truth for what the
scripts and skill must do; update it as steps are added.

## Core output rule

Every list produces **two files**: a contact file and a company file.

- A *list* is a set of people to reach out to. The company file contains only
  the companies of the contacts in that list.
- If a list is split into sublists, each sublist gets its own company file.
- Reference target format: sample files 4 (contacts) and 5 (companies) in
  `samples/MANIFEST.md`. File 4's last three columns are reference-only.

## Flow: straight enrichment (no filtering, no splitting)

### Step 1 — Email domain cleaning

Goal: every contact ends up with an email domain that matches its company's
domain, so HubSpot associates the contact with the company record.

Key concepts:
- **Email domain** = company domain (same thing). Drives HubSpot association.
- **Website** is a separate field; it must also be correct but can differ from
  the email domain (e.g. website `doitbestonline.com`, email domain
  `doitbest.com`).

Sub-steps, in order:
1. **Drop outdated emails.** If an email's domain doesn't belong to the
   contact's current company (e.g. an old work email from a prior employer or
   an acquired subsidiary still on the HubSpot record), clear the email.
2. **Validate emails.** Check each remaining email is valid.
3. **Extract domain.** Build an `Email Domain` column from the email address.
4. **Reconcile with ZoomInfo.** Compare the extracted domain with ZoomInfo's
   `Email Domain`. If they differ, the extracted domain wins.
5. **Backfill.** Contacts without an email get the email domain from another
   contact at the same company, so every contact has an email domain.
6. **Feed the company file.** The company list's `Email Domain` is taken from
   its contacts' email domains.

### Observed in the CBM M&A sample (raw → final)

- Typo fixed rather than dropped: `…@afcind.com.com` → `…@afcind.com`.
- Junk/placeholder domain cleared: `zoomhubs.com`.
- Acquired-subsidiary email cleared and domain set to parent: `kodiakbp.com`
  → `qxo.com` (QXO).
- A company can hold several domains, joined with `; `
  (Foundation Building Materials: `fbmsales.com; myfbm.com`).
