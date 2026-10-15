"""The upload files' columns = HubSpot's own fields, as they are in HubSpot right now.

Which columns (and their order) follow the team's reference upload files (EDGE 2026, + Type, + Primary
industry); each is headed with the property's current HubSpot label, so HubSpot's import maps every
column by itself, and every dropdown value is one of the
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

# Which columns, and in what order = the team's reference upload files (EDGE 2026, user 2026-10-15), plus Type
# on companies (added after that template) and Primary industry. Headers = HubSpot's own field labels (the
# live check overrides these), so the import maps every column by itself.
# (working column, HubSpot internal name, label on 2026-10-15, optional) — optional columns appear only when
# some row has a value (owners: only with BDR assignment).
CONTACT = [
    ("First Name", "firstname", "First Name", False), ("Last Name", "lastname", "Last Name", False),
    ("Company Name", "company", "Company Name", False), ("Job Title", "jobtitle", "Job Title", False),
    ("Website", "website", "Website URL", False), ("Person Zip Code", "zip", "Postal Code", False),
    ("Country", "country", "Country/Region", False), ("Person City", "city", "City", False),
    ("Person State", "state", "State/Region", False),
    ("Management Level", "hs_seniority", "Employment Seniority", False),
    ("Job Function", "job_function", "Job function", False), ("Department", "department", "Department", False),
    ("Direct Phone Number", "work_direct_phone", "Work Direct Phone", False),
    ("Email Address", "email", "Email", False),
    ("Email Domain", "hs_email_domain", "Email Domain", False),
    ("Mobile phone", "mobilephone", "Mobile Phone Number", False),
    ("ZoomInfo Contact Profile URL", "zoominfo_contact_profile_url", "ZoomInfo Contact Profile URL", False),
    ("LinkedIn Contact Profile URL", "lgm_linkedinurl", "Linkedin Url (Default)", False),
    ("Company HQ Phone", "corporate_phone", "Corporate Phone", False),
    ("Lead Source", "lead_source", "LEAD SOURCE", False),
    ("Lead Source Detail 1", "lead_source_detail_1", "LEAD SOURCE DETAIL 1", False),
    ("HubSpot Contact Record ID", "hs_object_id", "Record ID", False),
    ("Additional Emails", "secondary_email", "Secondary email", True),
    ("Contact Owner", "hubspot_owner_id", "Contact owner", True),
]
COMPANY = [
    ("Company Name", "name", "Company name", False), ("Website", "website", "Website URL", False),
    ("Founded Year", "founded_year", "Year Founded", False), ("Company HQ Phone", "phone", "Phone Number", False),
    ("Revenue (in USD)", "annualrevenue", "Annual Revenue", False),
    ("Revenue Range (in USD)", "hs_revenue_range", "Revenue range", False),
    ("Employees", "numberofemployees", "Number of Employees", False),
    ("Employee Range", "hs_employee_range", "Employee range", False),
    ("SIC Code 1", "sic_code_1", "SIC Code 1", False), ("SIC Code 2", "sic_code_2", "SIC Code 2", False),
    ("NAICS Code 1", "naics_code_1", "NAICS Code 1", False), ("NAICS Code 2", "naics_code_2", "NAICS Code 2", False),
    ("Didero Primary Industry", "primary_industry", "Primary industry", False),  # team's level 1 (cleanup file col C)
    ("Industry Group", "hs_industry_group", "Industry group", False),         # team's level 2 (col D), not the EDGE file
    ("ZoomInfo Company Profile URL", "zoominfo_company_profile_url", "ZoomInfo Company Profile URL", False),
    ("LinkedIn Company Profile URL", "linkedin_company_page", "LinkedIn Company Page", False),
    ("Facebook Company Profile URL", "facebook_company_page", "Facebook Company Page", False),
    ("Twitter Company Profile URL", "twitter_company_profile_url", "Twitter Company Profile URL", False),
    ("Company City", "city", "City", False), ("Company State", "state", "State/Region", False),
    ("Company Zip Code", "zip", "Postal Code", False), ("Company Country", "country", "Country/Region", False),
    ("Full Address", "address", "Street Address", False), ("Company Domain", "domain", "Company Domain Name", False),
    ("HubSpot Company Record ID", "hs_object_id", "Record ID", False),
    ("Type", "type", "Type", False),
    ("Company Owner", "hubspot_owner_id", "Company owner", True),
]
# ZoomInfo management levels -> HubSpot's Employment Seniority options
SENIORITY = {"c-level": "Executive", "vp-level": "VP", "director": "Director", "manager": "Manager",
             "non-manager": "Employee", "board member": "Executive"}
SPEC = {"contacts": CONTACT, "companies": COMPANY}
LIVE = "hubspot_fields.json"


def live(run_dir):
    p = Path(run_dir) / LIVE
    return json.loads(p.read_text()) if p.exists() else None


def columns(kind, run_dir, rows=None):
    """[(working column, HubSpot label)] for the upload file, labels from the live check when there is one.
    A property HubSpot no longer has is left out (listed by `check`); optional columns only when filled."""
    lv = live(run_dir)
    out = []
    for col, internal, label, optional in SPEC[kind]:
        if lv is not None:
            prop = lv[kind].get(internal)
            if not prop:
                continue
            label = prop["label"]
        if optional and not any((r.get(col) or "").strip() for r in (rows or [])):
            continue
        out.append((col, label))
    return out


def dropdown_values(rows, kind, run_dir):
    """Every dropdown value as one of HubSpot's current options (live check): matched on the option's label
    or internal value, any case, and written as HubSpot's label (owners: the owner's name). A value that isn't
    an option -> blank. Returns [(column, value, n)] of values blanked."""
    lv = live(run_dir) or {}
    blanked = {}
    for col, internal, _, _ in SPEC[kind]:
        prop = lv.get(kind, {}).get(internal)
        if internal == "hs_industry_group" and prop and not prop.get("options"):
            # still a text field in HubSpot (becoming a dropdown): hold it to the team's list meanwhile
            import hs_values
            groups = hs_values.industry_map().get("groups", [])
            prop = dict(prop, type="enumeration", options=[[g, g] for g in groups]) if groups else prop
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
            if hit is None and internal == "hs_seniority":
                hit = lookup.get(SENIORITY.get(v.lower(), "").lower())
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
        print(f"get_properties objectType={obj} propertyNames={json.dumps([x[1] for x in SPEC[kind]])}")
    print(f"Save each raw result, then: hs_fields.py check --run-dir {args.run_dir} --contacts <file> --companies <file>")


def check(args):
    out, notes = {}, []
    for kind, f in (("contacts", args.contacts), ("companies", args.companies)):
        data = json.loads(Path(f).read_text())
        props = {r["name"]: {"label": r.get("label", ""), "type": r.get("type", ""),
                             "options": [[o.get("label", ""), o.get("value", "")] for o in r.get("options", [])]}
                 for r in data.get("results", [])}
        out[kind] = props
        for col, internal, label, _ in SPEC[kind]:
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
