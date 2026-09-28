# Sample file manifest

Data files are git-ignored (the repo is public). This manifest records what
each sample is so the test setup is reproducible.

## List types

- **Type 1 – wholesale:** list built purely from a source list of companies;
  data taken as-is, only essential fields. A single file holds both company and
  contact columns; it's uploaded to HubSpot twice (company fields, then contact
  fields).
- **Type 2 – ZoomInfo + personalization:** list built in ZoomInfo from a
  source list of companies, plus a personalization field required for
  customized sequences. Separate company and contact files.

## Samples

| # | Type | Path | Stage | Status |
|---|------|------|-------|--------|
| 1 | 1 | `type1_wholesale/grata_packaging_ai_it_2026-09-02/combined.csv` | Old combined company+contact file (Grata Packaging AI/IT); close to the ideal output | Present |
| 2 | 2 | `type2_zoominfo_personalized/cbm_mna_2026-09-28/raw/companies_zi_raw.csv` | Company file, straight from ZoomInfo, unedited | Present (59 rows) |
| 3 | 2 | `type2_zoominfo_personalized/cbm_mna_2026-09-28/raw/contacts_zi_raw.csv` | Contact file, straight from ZoomInfo, unedited | Present |
| 4 | 2 | `type2_zoominfo_personalized/cbm_mna_2026-09-28/final/contacts_final.csv` | Contact file after manual cleanup (target output) | Present |
| 5 | 2 | `type2_zoominfo_personalized/cbm_mna_2026-09-28/final/companies_final.csv` | Company file after manual cleanup (target output) | Present (59 rows) |

## Notes

- File 4: the last three columns — `lemlist Status (live)`,
  `HubSpot Last lemlist Campaign`, `HubSpot Old Contact Outbound
  Personalization Token` — are reference-only and not pushed to HubSpot. Do not
  treat them as part of the target output format.
