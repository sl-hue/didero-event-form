"""Step 4 — upload to HubSpot through the connector.

Companies go first so they exist as anchors for the contacts. The script maps
upload-file columns to HubSpot properties and splits the rows into batches of
at most 10 (the connector's limit): records with a HubSpot Record ID are
updated, "Not in HubSpot" rows are created. Claude sends each batch with the
connector's manage_crm_objects tool after the user approves.

  prepare-companies  -> company_upload_batches.json + company_upload_preview.csv
  record-created     Read the saved create responses and write the new
                     HubSpot Record IDs back into the upload file.

Blank cells are never sent, so an empty value in the file never wipes data
already in HubSpot.
"""
import argparse
import csv
import json
import re
from pathlib import Path

COMPANY_RECORD = "HubSpot Company Record ID"
NOT_IN_HUBSPOT = "Not in HubSpot"
BATCH = 10

# Upload-file column -> HubSpot company property (internal name).
COMPANY_MAPPING = {
    "Company Name": "name",
    "Website": "website",
    "Founded Year": "founded_year",
    "Company HQ Phone": "phone",
    "Revenue (in USD)": "annualrevenue",
    "Revenue Range (in USD)": "hs_revenue_range",
    "Employees": "numberofemployees",
    "Employee Range": "hs_employee_range",
    "SIC Code 1": "sic_code_1",
    "SIC Code 2": "sic_code_2",
    "NAICS Code 1": "naics_code_1",
    "NAICS Code 2": "naics_code_2",
    "Primary Industry": "hs_industry_group",
    "ZoomInfo Company Profile URL": "zoominfo_company_profile_url",
    "LinkedIn Company Profile URL": "linkedin_company_page",
    "Facebook Company Profile URL": "facebook_company_page",
    "Twitter Company Profile URL": "twitter_company_profile_url",
    "Company City": "city",
    "Company State": "state",
    "Company Zip Code": "zip",
    "Company Country": "country",
    "Full Address": "address",
    "Company Domain": "domain",
    "Additional Domains": "hs_additional_domains",
    "Type": "type",
    "Outbound Personalization Token": "company_outbound_personalization",
}
# Enumeration properties: file label -> HubSpot option value.
ENUM_VALUES = {"type": {"prospect": "PROSPECT", "partner": "PARTNER", "reseller": "RESELLER",
                        "vendor": "VENDOR", "other": "OTHER", "customer": "Customer"}}


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def to_properties(row, mapping):
    props = {}
    for column, prop in mapping.items():
        value = (row.get(column) or "").strip()
        if not value:
            continue
        if prop in ENUM_VALUES:
            value = ENUM_VALUES[prop].get(value.lower(), value)
        props[prop] = value
    return props


def prepare_companies(args):
    fields, rows = read_rows(args.companies)
    unmapped = [f for f in fields if f not in COMPANY_MAPPING and f not in ("ZoomInfo Company ID", COMPANY_RECORD)]
    creates, updates, preview = [], [], []
    for row in rows:
        props = to_properties(row, COMPANY_MAPPING)
        record = (row.get(COMPANY_RECORD) or "").strip()
        key = row.get("ZoomInfo Company ID", "")
        if record and record != NOT_IN_HUBSPOT:
            updates.append({"objectType": "companies", "objectId": int(record), "properties": props, "_key": key})
            action = "update"
        else:
            creates.append({"objectType": "companies", "properties": props, "_key": key})
            action = "create"
        preview.append({"Action": action, "HubSpot Record ID": record if action == "update" else "",
                        "Company Name": row.get("Company Name", ""), "Company Domain": row.get("Company Domain", ""),
                        "Properties sent": len(props)})
    batches = ([{"kind": "update", "objects": updates[i:i + BATCH]} for i in range(0, len(updates), BATCH)]
               + [{"kind": "create", "objects": creates[i:i + BATCH]} for i in range(0, len(creates), BATCH)])
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "company_upload_batches.json").write_text(json.dumps(batches, indent=2))
    write_rows(out / "company_upload_preview.csv", list(preview[0].keys()), preview)
    print(f"{len(updates)} updates, {len(creates)} creates in {len(batches)} batches -> "
          f"{out / 'company_upload_batches.json'}")
    if unmapped:
        print("columns in the file with no HubSpot mapping (not sent):", ", ".join(unmapped))


def record_created(args):
    """Match created records back to rows by domain, then by name."""
    fields, rows = read_rows(args.companies)
    created = []
    for path in sorted(Path(args.raw_dir).glob("*.json")):
        data = json.loads(path.read_text())
        for resp in data if isinstance(data, list) else [data]:
            for rec in resp.get("results", resp.get("objects", [])):
                created.append((str(rec.get("id")), rec.get("properties", {})))
    by_domain = {(p.get("domain") or "").lower(): rid for rid, p in created if p.get("domain")}
    by_name = {(p.get("name") or "").lower(): rid for rid, p in created if p.get("name")}
    filled = 0
    for row in rows:
        if (row.get(COMPANY_RECORD) or NOT_IN_HUBSPOT) != NOT_IN_HUBSPOT:
            continue
        rid = by_domain.get((row.get("Company Domain") or "").lower()) or by_name.get((row.get("Company Name") or "").lower())
        if rid:
            row[COMPANY_RECORD] = rid
            filled += 1
    write_rows(args.companies, fields, rows)
    left = sum(1 for r in rows if r.get(COMPANY_RECORD) == NOT_IN_HUBSPOT)
    print(f"{filled} new HubSpot Record IDs written; {left} rows still without one")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare-companies")
    p.add_argument("--companies", required=True)
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=prepare_companies)
    r = sub.add_parser("record-created")
    r.add_argument("--companies", required=True)
    r.add_argument("--raw-dir", required=True)
    r.set_defaults(func=record_created)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
