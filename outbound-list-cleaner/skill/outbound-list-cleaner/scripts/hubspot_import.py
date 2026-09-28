"""Step 4 — prepare the HubSpot import.

The user imports the files through HubSpot's import screen (companies first,
so they exist as anchors for the contacts). This script:

  prepare   Adds the Type column to the company file (default "Prospect"),
            checks the Type already on matched HubSpot records, and writes
            import_mapping.md: for each file, every column -> HubSpot property
            (label + internal name), how many rows have a value, and whether to
            tick "Don't overwrite" for it. Claude shows these tables in chat so
            the user can pick the same fields in the import screen.

Record IDs: rows marked "Not in HubSpot" are blanked in the Record ID column
of the import copy, because HubSpot rejects non-numeric Record IDs; blank
means "create", a number means "update that record".
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

COMPANY_RECORD = "HubSpot Company Record ID"
CONTACT_RECORD = "HubSpot Contact Record ID"
NOT_IN_HUBSPOT = "Not in HubSpot"

# File column -> (HubSpot property label, internal name). None = don't import.
COMPANY_MAPPING = {
    "ZoomInfo Company ID": None,  # not sent: it confuses a calling tool
    "Company Name": ("Company name", "name"),
    "Website": ("Website URL", "website"),  # not "Company Website URL (Cleaned)"
    "Founded Year": ("Year Founded", "founded_year"),
    "Company HQ Phone": ("Phone Number", "phone"),
    "Revenue (in USD)": ("Annual Revenue", "annualrevenue"),
    "Revenue Range (in USD)": ("Revenue range", "hs_revenue_range"),
    "Employees": ("Number of Employees", "numberofemployees"),
    "Employee Range": ("Employee range", "hs_employee_range"),
    "SIC Code 1": ("SIC Code 1", "sic_code_1"),
    "SIC Code 2": ("SIC Code 2", "sic_code_2"),
    "NAICS Code 1": ("NAICS Code 1", "naics_code_1"),
    "NAICS Code 2": ("NAICS Code 2", "naics_code_2"),
    "Primary Industry": ("Industry group", "hs_industry_group"),
    "ZoomInfo Company Profile URL": ("ZoomInfo Company Profile URL", "zoominfo_company_profile_url"),
    "LinkedIn Company Profile URL": ("LinkedIn Company Page", "linkedin_company_page"),
    "Facebook Company Profile URL": ("Facebook Company Page", "facebook_company_page"),
    "Twitter Company Profile URL": ("Twitter Company Profile URL", "twitter_company_profile_url"),
    "Company City": ("City", "city"),
    "Company State": ("State/Region", "state"),
    "Company Zip Code": ("Postal Code", "zip"),
    "Company Country": ("Country/Region", "country"),
    "Full Address": ("Street Address", "address"),
    "Company Domain": ("Company Domain Name", "domain"),
    "Additional Domains": ("Additional Domains", "hs_additional_domains"),
    "Type": ("Type", "type"),
    "Outbound Personalization Token": ("Company Outbound Personalization", "company_outbound_personalization"),
    COMPANY_RECORD: ("Record ID", "hs_object_id"),
}

CONTACT_MAPPING = {
    "ZoomInfo Contact ID": None,
    "First Name": ("First Name", "firstname"),
    "Last Name": ("Last Name", "lastname"),
    "Job Title": ("Job Title", "jobtitle"),
    "Management Level": ("Seniority", "seniority"),
    "Job Function": ("Job function", "job_function"),
    "Department": ("Department", "department"),
    "Direct Phone Number": ("Work Direct Phone", "work_direct_phone"),
    "Email Address": ("Email", "email"),
    "Email Domain": ("Company Domain", "company_domain"),
    "Mobile phone": ("Mobile Phone Number", "mobilephone"),
    "ZoomInfo Contact Profile URL": ("ZoomInfo Contact Profile URL", "zoominfo_contact_profile_url"),
    "LinkedIn Contact Profile URL": ("Linkedin Url (Default)", "lgm_linkedinurl"),
    "Person Street": ("Street Address", "address"),
    "Person City": ("City", "city"),
    "Person State": ("State/Region", "state"),
    "Person Zip Code": ("Postal Code", "zip"),
    "Country": ("Country/Region", "country"),
    "Company Name": ("Company Name", "company"),
    "Website": ("Website URL", "website"),  # not "Contact Website URL (Cleaned)"
    "Company HQ Phone": ("Corporate Phone", "corporate_phone"),
    CONTACT_RECORD: ("Record ID", "hs_object_id"),
    "New Contact Outbound Personalization": ("Contact Outbound Personalization", "contact_outbound_personalization"),
}

# Columns where an existing HubSpot value is usually worth keeping: suggest
# ticking "Don't overwrite" (the user decides).
PROTECT = {
    "companies": {"Company Name": "keeps the name already curated in HubSpot",
                  "Type": "keeps Customer/Partner/etc. on existing records",
                  "Company Domain": "the primary domain is HubSpot's unique key for the company"},
    "contacts": {"Email Address": "changing the primary email on an existing contact can break its history",
                 "Company Name": "keeps the company name already on the contact"},
}


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_rows(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def hubspot_types(raw_dir):
    types = {}
    if raw_dir:
        for path in Path(raw_dir).glob("*.json"):
            data = json.loads(path.read_text())
            for resp in data if isinstance(data, list) else [data]:
                for rec in resp.get("results", []):
                    types[str(rec["id"])] = (rec.get("properties") or {}).get("type") or ""
    return types


def mapping_table(kind, fields, rows, mapping):
    lines = [f"### {kind.capitalize()} file → HubSpot {kind}", "",
             "| File column | HubSpot property | Internal name | Rows with a value | Don't overwrite? |",
             "|---|---|---|---|---|"]
    unknown = []
    for f in fields:
        if f not in mapping:
            unknown.append(f)
            continue
        filled = sum(1 for r in rows if (r.get(f) or "").strip())
        target = mapping[f]
        if target is None:
            lines.append(f"| {f} | *Don't import column* | — | {filled}/{len(rows)} | — |")
            continue
        protect = PROTECT[kind].get(f)
        lines.append(f"| {f} | {target[0]} | `{target[1]}` | {filled}/{len(rows)} | "
                     f"{'Suggested — ' + protect if protect else ''} |")
    return lines, unknown


def prepare(args):
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfields, companies = read_rows(args.companies)
    if "Type" not in cfields:
        at = cfields.index("Outbound Personalization Token") if "Outbound Personalization Token" in cfields else len(cfields)
        cfields = cfields[:at] + ["Type"] + cfields[at:]
    for c in companies:
        c["Type"] = c.get("Type") or args.type
    write_rows(args.companies, cfields, companies)

    # Existing HubSpot records whose Type differs from the file's.
    types = hubspot_types(args.raw_dir)
    type_conflicts = []
    for c in companies:
        rid = c.get(COMPANY_RECORD, "")
        existing = types.get(rid, "")
        if existing and existing.lower() != c["Type"].lower():
            type_conflicts.append({"company": c["Company Name"], "record_id": rid,
                                   "hubspot_type": existing, "file_type": c["Type"]})

    lines = ["# HubSpot import mapping", "",
             "Import the company file first, then the contact file. In HubSpot's import "
             "screen, map each column as below. Tick \"Don't overwrite\" for any column "
             "where you'd rather keep the value already in HubSpot.", ""]
    notes = []
    for kind, path, mapping, record in (("companies", args.companies, COMPANY_MAPPING, COMPANY_RECORD),
                                        ("contacts", args.contacts, CONTACT_MAPPING, CONTACT_RECORD)):
        fields, rows = read_rows(path)
        table, unknown = mapping_table(kind, fields, rows, mapping)
        lines += table + [""]
        if unknown:
            notes.append(f"{kind}: columns with no agreed mapping (don't import): {', '.join(unknown)}")
        # Import copy: HubSpot rejects "Not in HubSpot" as a Record ID.
        for r in rows:
            if r.get(record) == NOT_IN_HUBSPOT:
                r[record] = ""
        write_rows(out / f"{kind}_import.csv", fields, rows)
        new = sum(1 for r in rows if not r.get(record))
        notes.append(f"{kind}: {len(rows) - new} update existing records, {new} create new records")
    type_counts = Counter(c["Type"] for c in companies)
    report = {"type_counts": dict(type_counts), "type_conflicts": type_conflicts, "notes": notes}
    (out / "import_mapping.md").write_text("\n".join(lines))
    (out / "report_step4.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {out / 'import_mapping.md'}, {out / 'companies_import.csv'}, {out / 'contacts_import.csv'}")
    print("Type:", dict(type_counts), f"| {len(type_conflicts)} existing records with a different Type")
    for n in notes:
        print(n)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--companies", required=True, help="companies_upload.csv (after step 3)")
    p.add_argument("--contacts", required=True, help="contacts_upload.csv (after step 3)")
    p.add_argument("--raw-dir", help="step 3 HubSpot company search results, to check existing Type")
    p.add_argument("--type", default="Prospect", help="Type for the list's companies (default Prospect)")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=prepare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
