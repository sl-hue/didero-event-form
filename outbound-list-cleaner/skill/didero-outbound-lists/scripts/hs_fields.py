"""The upload files' columns = HubSpot's own fields, as they are in HubSpot right now.

Each upload file has one column per HubSpot property, headed with the property's current HubSpot
label, so HubSpot's import maps every column by itself, and every dropdown value is one of the
property's current options (dropdown_values: matched on label or internal value, any case, written as
HubSpot's label; anything else blank). Before the export, the run reads the
properties live (read-only get_properties) and the export uses exactly those labels; a property
HubSpot doesn't have (renamed, deleted) is left out and listed.

  plan   --run-dir <run_dir>   prints the two get_properties calls to make (contacts, companies)
  check  --run-dir <run_dir> --contacts <saved result> --companies <saved result>
         writes <run_dir>/hubspot_fields.json (label, type, options per property) and lists any
         label that changed or property that's missing.

Working-file column -> HubSpot internal name. Labels below are as checked on 2026-10-15; the live
check overrides them. Not here = not imported (e.g. the internal row IDs, owner names for reading,
the contact's email domain — HubSpot sets it from the email —, additional domains — no importable
property, and company data such as industry: it goes on the company file only).
"""
import argparse
import json
from pathlib import Path

CONTACT = [  # (working column, internal name, label on 2026-10-15)
    ("First Name", "firstname", "First Name"), ("Last Name", "lastname", "Last Name"),
    ("Job Title", "jobtitle", "Job Title"), ("Management Level", "hs_seniority", "Employment Seniority"),
    ("Job Function", "job_function", "Job function"), ("Department", "department", "Department"),
    ("Email Address", "email", "Email"), ("Additional Emails", "secondary_email", "Secondary email"),
    ("Direct Phone Number", "work_direct_phone", "Work Direct Phone"),
    ("Mobile phone", "mobilephone", "Mobile Phone Number"), ("Company HQ Phone", "corporate_phone", "Corporate Phone"),
    ("LinkedIn Contact Profile URL", "lgm_linkedinurl", "Linkedin Url (Default)"),
    ("ZoomInfo Contact Profile URL", "zoominfo_contact_profile_url", "ZoomInfo Contact Profile URL"),
    ("Person Street", "address", "Street Address"), ("Person City", "city", "City"),
    ("Person State", "state", "State/Region"), ("Person Zip Code", "zip", "Postal Code"),
    ("Country", "country", "Country/Region"), ("Company Name", "company", "Company Name"),
    ("Website", "website", "Website URL"),
    ("Lead Source", "lead_source", "LEAD SOURCE"), ("Lead Source Detail 1", "lead_source_detail_1", "LEAD SOURCE DETAIL 1"),
    ("New Contact Outbound Personalization", "contact_outbound_personalization", "Contact Outbound Personalization"),
    ("Contact Owner", "hubspot_owner_id", "Contact owner"),
    ("HubSpot Contact Record ID", "hs_object_id", "Record ID"),
]
COMPANY = [
    ("Company Name", "name", "Company name"), ("Website", "website", "Website URL"),
    ("Company Domain", "domain", "Company Domain Name"), ("Company HQ Phone", "phone", "Phone Number"),
    ("Founded Year", "founded_year", "Year Founded"), ("Revenue (in USD)", "annualrevenue", "Annual Revenue"),
    ("Revenue Range (in USD)", "hs_revenue_range", "Revenue range"), ("Employees", "numberofemployees", "Number of Employees"),
    ("Employee Range", "hs_employee_range", "Employee range"), ("SIC Code 1", "sic_code_1", "SIC Code 1"),
    ("SIC Code 2", "sic_code_2", "SIC Code 2"), ("NAICS Code 1", "naics_code_1", "NAICS Code 1"),
    ("NAICS Code 2", "naics_code_2", "NAICS Code 2"), ("Didero Primary Industry", "primary_industry", "Primary industry"),
    ("Industry", "industry", "Industry"), ("Industry Group", "hs_industry_group", "Industry group"),
    ("ZoomInfo Company Profile URL", "zoominfo_company_profile_url", "ZoomInfo Company Profile URL"),
    ("LinkedIn Company Profile URL", "linkedin_company_page", "LinkedIn Company Page"),
    ("Facebook Company Profile URL", "facebook_company_page", "Facebook Company Page"),
    ("Twitter Company Profile URL", "twitter_company_profile_url", "Twitter Company Profile URL"),
    ("Full Address", "address", "Street Address"), ("Company City", "city", "City"),
    ("Company State", "state", "State/Region"), ("Company Zip Code", "zip", "Postal Code"),
    ("Company Country", "country", "Country/Region"), ("Type", "type", "Type"),
    ("Outbound Personalization Token", "company_outbound_personalization", "Company Outbound Personalization"),
    ("Company Owner", "hubspot_owner_id", "Company owner"),
    ("HubSpot Company Record ID", "hs_object_id", "Record ID"),
]
SPEC = {"contacts": CONTACT, "companies": COMPANY}
LIVE = "hubspot_fields.json"


def live(run_dir):
    p = Path(run_dir) / LIVE
    return json.loads(p.read_text()) if p.exists() else None


def columns(kind, run_dir):
    """[(working column, HubSpot label)] for the upload file, labels from the live check when there is one."""
    lv = live(run_dir)
    out = []
    for col, internal, label in SPEC[kind]:
        if lv is not None:
            prop = lv[kind].get(internal)
            if not prop:
                continue  # not in HubSpot any more: left out (listed by `check`)
            label = prop["label"]
        out.append((col, label))
    return out


def dropdown_values(rows, kind, run_dir):
    """Every dropdown value as one of HubSpot's current options (live check): matched on the option's label
    or internal value, any case, and written as HubSpot's label (owners: the owner's name). A value that isn't
    an option -> blank. Returns [(column, value, n)] of values blanked."""
    lv = live(run_dir) or {}
    blanked = {}
    for col, internal, _ in SPEC[kind]:
        prop = lv.get(kind, {}).get(internal)
        if not prop or prop.get("type") != "enumeration" or not prop.get("options"):
            continue
        lookup = {}
        for label, value in prop["options"]:
            target = label  # owners too: "Bart Lynn", not the owner ID (HubSpot's import accepts the name)
            lookup[str(label).strip().lower()] = target
            lookup[str(value).strip().lower()] = target
        for r in rows:
            v = (r.get(col) or "").strip()
            if not v:
                continue
            hit = lookup.get(v.lower())
            if hit is None and internal == "hubspot_owner_id":
                hit = lookup.get((r.get(col + " Name") or "").strip().lower())  # ID not an option: try the name
            if hit is None:
                blanked[(col, v)] = blanked.get((col, v), 0) + 1
                r[col] = ""
            else:
                r[col] = hit
    return [(c, v, n) for (c, v), n in sorted(blanked.items())]


def plan(args):
    for kind, obj in (("contacts", "contacts"), ("companies", "companies")):
        print(f"get_properties objectType={obj} propertyNames={json.dumps([i for _, i, _ in SPEC[kind]])}")
    print(f"Save each raw result, then: hs_fields.py check --run-dir {args.run_dir} --contacts <file> --companies <file>")


def check(args):
    out, notes = {}, []
    for kind, f in (("contacts", args.contacts), ("companies", args.companies)):
        data = json.loads(Path(f).read_text())
        props = {r["name"]: {"label": r.get("label", ""), "type": r.get("type", ""),
                             "options": [[o.get("label", ""), o.get("value", "")] for o in r.get("options", [])]}
                 for r in data.get("results", [])}
        out[kind] = props
        for col, internal, label in SPEC[kind]:
            if internal not in props:
                notes.append(f"{kind}: '{col}' -> {internal} isn't in HubSpot — left out of the upload")
            elif props[internal]["label"] != label:
                notes.append(f"{kind}: {internal} is now labelled '{props[internal]['label']}' (was '{label}')")
    (Path(args.run_dir) / LIVE).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"HubSpot fields checked live -> {LIVE}: {len(out['contacts'])} contact and {len(out['companies'])} company "
          "properties" + ("" if notes else "; everything matches"))
    for n in notes:
        print("  -", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--run-dir", required=True); p.set_defaults(func=plan)
    p = sub.add_parser("check"); p.add_argument("--run-dir", required=True)
    p.add_argument("--contacts", required=True); p.add_argument("--companies", required=True)
    p.set_defaults(func=check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
