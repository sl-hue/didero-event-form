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

- The website is **not** used to derive or check the email domain.

Sub-steps, in order:
1. **Company-match check (needs judgment).** For each email, decide whether its
   domain plausibly belongs to the contact's current company name. Matches are
   often not literal: shortened names, acronyms, partial acronyms
   (UFP Industries → `ufpi.com`, First Supply → `1supply.com`). Claude makes
   this call, not string matching. This is *not* a deliverability check —
   email validity is out of scope at this stage.
   - Clear match → keep.
   - Clear mismatch (old employer) → clear the email.
   - Doubtful, or a possible parent/child relationship (e.g. `kodiakbp.com`
     under QXO) → queue for human review.
2. **Human review of doubtful rows.** For each queued row, Claude shows the
   user: the contact, company, email domain, why it thinks it does or doesn't
   match, and whether a parent/child relationship exists. The user picks from
   a decision box in chat: keep / clear / map to parent domain.
3. **Extract domain.** Build `Email Domain` from each surviving email.
4. **Reconcile with ZoomInfo.** If the extracted domain differs from
   ZoomInfo's `Email Domain`, the extracted domain wins.
5. **Backfill from colleagues.** Contacts without an email get the email domain
   from another contact at the same company.
6. **Backfill from the web.** If no contact at a company has an email, Claude
   searches the web for publicly listed general inboxes (info@, support@,
   help@, general@, sales@, marketing@, inquiry@, and variants) and takes the
   domain from those. Applied to the company and all its contacts. If no
   general inbox exists, publicly listed staff addresses are acceptable
   evidence of the domain (confirmed by user on the CBM M&A run).
7. **Build company domains.** Every domain used by the company's contacts
   goes on the company record:
   - `Company Domain` — the primary domain: the one **most used** by the
     company's contacts. Ties go to the user.
   - `Additional Domains` — all other domains, separated by `;`.
   Contacts without an email are backfilled with the primary domain.

### Decision rules (confirmed by user)

- Subsidiary / acquired-company emails (e.g. `kodiakbp.com` at QXO) are
  **kept**; whichever domain is most used becomes `Company Domain`, the rest
  go in `Additional Domains`.
- Web backfill: use the ultimate owner and the email domain it actually uses
  (e.g. Threaded Fasteners → `tfmfg.com`, the domain its public inboxes use).
- Acquisitions don't change a company's domain by themselves: FBM stays on
  its own domains even though Lowe's owns it.
- Company file: `Company Domain` + `Additional Domains` replace file 5's
  single `Email Domain` column (confirmed).
- ZoomInfo placeholder domains (e.g. `zoomhubs.com`) are cleared automatically.
- Doubled TLDs (`.com.com`) are fixed, not cleared.
- A ZoomInfo company name that doesn't resemble the domain is not by itself a
  mismatch — check what company the domain actually belongs to
  (Sign & Awning Services → `arch-fab.com`, Architectural Fabrication: keep).

### Observed in the CBM M&A sample (raw → final)

- Typo fixed rather than dropped: `…@afcind.com.com` → `…@afcind.com`.
- Junk/placeholder domain cleared: `zoomhubs.com`.
- Acquired-subsidiary email cleared and domain set to parent: `kodiakbp.com`
  → `qxo.com` (QXO).
- A company can hold several domains, joined with `; `
  (Foundation Building Materials: `fbmsales.com; myfbm.com`).
- Sample file 5 leaves `Email Domain` blank for companies with no contact
  emails (e.g. The Gund Company, Threaded Fasteners); under sub-step 6 the
  script should fill these, so differences there are expected when testing.
