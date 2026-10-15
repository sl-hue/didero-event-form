"""The upload files' one format — normalized and checked before step 5, so every run (whoever runs it)
produces the same files.

Different runs gave different files: columns depended on the source, and values on how each run
formatted them. Now `worksheet.py export` always writes the same columns in the same order, puts every
value into the format below (safe, mechanical fixes only), then checks both files. Any error stops the
export (no upload files are written); warnings are listed. The result is saved as
upload/format_report.json, and the import step can't be marked done without a passed report.

The format (from the hand-cleaned CBM M&A files and Didero's HubSpot properties):
  names .................. no stray spaces; first letter capital
  email .................. lowercase, valid address; unique across the contact file
  email domain ........... lowercase domain
  phones ................. US / Canada "(312) 555-0142" (+ " ext. 12"); others "+<country code> …"
  website ................ "www.acme.com" — no https://, no path (subdomains other than www kept)
  LinkedIn ............... https://www.linkedin.com/in/<slug>  ·  https://www.linkedin.com/company/<slug>
  ZoomInfo ............... https://app.zoominfo.com/#/apps/profile/person/<id>  ·  …/company/<id>
  country ................ full name ("United States", "United Kingdom")
  state .................. full name for the US and Canada ("Illinois", "Ontario")
  numbers ................ digits only (revenue in USD, employees, founded year, SIC / NAICS)
  record / owner IDs ..... digits or blank
  dropdowns .............. HubSpot's options (Type, Employee range, industries, Lead Source = Events)
  websites + domains ..... always on both files: Website and Email Domain on every contact (the
                           company's website), Website and Company Domain on every company
  every contact's company is a row of the company file
"""
import re

from location import CA_PROVINCE_CODES, US_STATE_CODES

PLACEHOLDERS = {"nan", "none", "null", "n/a", "na", "-", "--", "not in hubspot", "#n/a", "undefined"}
TYPE_OPTIONS = {"Prospect", "Partner", "Reseller", "Vendor", "Other", "Customer", "Manually Reviewed, Not Propsect"}
EMAIL = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
DIGITS = re.compile(r"^\d+$")
LI_IN = re.compile(r"^https://www\.linkedin\.com/in/[^/?#\s]+$")
LI_CO = re.compile(r"^https://www\.linkedin\.com/company/[^/?#\s]+$")
ZI_P = re.compile(r"^https://app\.zoominfo\.com/#/apps/profile/person/-?\d+$")
ZI_C = re.compile(r"^https://app\.zoominfo\.com/#/apps/profile/company/-?\d+$")
STATES = {**{k.lower(): v for k, v in US_STATE_CODES.items()}, **{v.lower(): v for v in US_STATE_CODES.values()},
          **{k.lower(): v for k, v in CA_PROVINCE_CODES.items()}, **{v.lower(): v for v in CA_PROVINCE_CODES.values()},
          "québec": "Quebec", "washington dc": "District of Columbia", "washington d.c.": "District of Columbia"}
NORTH_AMERICA = {"United States", "Canada"}
COUNTRY_FIX = {"us": "United States", "usa": "United States", "u.s.": "United States", "u.s.a.": "United States",
               "united states of america": "United States", "america": "United States", "uk": "United Kingdom",
               "u.k.": "United Kingdom", "great britain": "United Kingdom", "england": "United Kingdom",
               "scotland": "United Kingdom", "wales": "United Kingdom", "northern ireland": "United Kingdom",
               "gb": "United Kingdom", "ca": "Canada", "uae": "United Arab Emirates", "the netherlands": "Netherlands",
               "holland": "Netherlands", "republic of ireland": "Ireland", "korea": "South Korea"}
TWO_LEVEL = re.compile(r"\.(co|com|org|net|ac|gov)\.[a-z]{2}$")

PHONE_COLS = {"Direct Phone Number", "Mobile phone", "Company HQ Phone"}
NUMBER_COLS = {"Revenue (in USD)", "Employees", "Founded Year", "SIC Code 1", "SIC Code 2", "NAICS Code 1", "NAICS Code 2"}
ID_COLS = {"HubSpot Contact Record ID", "HubSpot Company Record ID", "Contact Owner", "Company Owner"}
STATE_COUNTRY = {"Person State": "Country", "Company State": "Company Country"}


def phone(v):
    """US / Canada -> (312) 555-0142 [ext. 12]; +<code> numbers kept; anything else unchanged."""
    m = re.match(r"^(.*?)(?:\s*(?:x|ext\.?|extension)\s*(\d+))?$", v.strip(), re.I)
    main, ext = m.group(1), m.group(2)
    if main.strip().startswith("+") and not main.strip().startswith("+1"):
        return v.strip()
    d = re.sub(r"\D", "", main)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if len(d) != 10:
        return v.strip()
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" + (f" ext. {ext}" if ext else "")


def website(v):
    h = re.sub(r"^[a-z]+://", "", v.strip().lower()).split("/")[0].split("?")[0].split("#")[0].strip(".")
    if not h:
        return ""
    if not h.startswith("www.") and (h.count(".") == 1 or (h.count(".") == 2 and TWO_LEVEL.search(h))):
        h = "www." + h
    return h


def linkedin(v, kind):
    m = re.search(rf"linkedin\.com/{kind}/([^/?#\s]+)", v, re.I)
    return f"https://www.linkedin.com/{kind}/{m.group(1).rstrip('/')}" if m else v.strip()


def zoominfo(v, kind):
    m = re.search(rf"/profile/{kind}/(-?\d+)", v)
    return f"https://app.zoominfo.com/#/apps/profile/{kind}/{m.group(1)}" if m else v.strip()


def name_case(v):
    if v.isupper() or v.islower():
        return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in v.split(" "))
    return v


def normalize(rows, cols):
    """Safe, mechanical fixes on the rows going into an upload file. Returns {column: n changed}."""
    changed = {}
    for r in rows:
        for c in cols:
            v = r.get(c)
            v = "" if v is None else str(v)
            new = re.sub(r"\s+", " ", v).strip()
            if new.lower() in PLACEHOLDERS:
                new = ""
            if new:
                if c in ("First Name", "Last Name"):
                    new = name_case(new)
                elif c in ("Email Address", "Additional Emails", "Email Domain", "Company Domain", "Additional Domains"):
                    new = new.lower().replace(" ", "")
                elif c in PHONE_COLS:
                    new = phone(new)
                elif c == "Website":
                    new = website(new)
                elif c == "LinkedIn Contact Profile URL":
                    new = linkedin(new, "in")
                elif c == "LinkedIn Company Profile URL":
                    new = linkedin(new, "company")
                elif c == "ZoomInfo Contact Profile URL":
                    new = zoominfo(new, "person")
                elif c == "ZoomInfo Company Profile URL":
                    new = zoominfo(new, "company")
                elif c in ("Country", "Company Country"):
                    new = COUNTRY_FIX.get(new.lower(), new)
                elif c in NUMBER_COLS:
                    d = re.sub(r"[,$\s]", "", new)
                    new = d.split(".")[0] if re.match(r"^\d+(\.\d+)?$", d) else new
                elif c in ID_COLS:
                    new = new.split(".")[0] if re.match(r"^\d+\.0$", new) else new
            r[c] = new
            if new != v:
                changed[c] = changed.get(c, 0) + 1
    for r in rows:  # state names, once the country is settled
        for sc, cc in STATE_COUNTRY.items():
            if sc in cols and r.get(sc) and (r.get(cc) in NORTH_AMERICA or not r.get(cc)):
                full = STATES.get(r[sc].lower().strip("."))
                if full and full != r[sc]:
                    r[sc] = full
                    changed[sc] = changed.get(sc, 0) + 1
    return changed


def fill_links(contacts, companies):
    """Websites and domains on both files (a run once shipped files without them): the company's domain
    from its website; each contact's Website from its company; Email Domain from the email, else the
    company's domain. Returns {what: n filled}."""
    filled = {}
    bump = lambda k: filled.__setitem__(k, filled.get(k, 0) + 1)
    by_name = {}
    for k in companies:
        if not k.get("Company Domain") and k.get("Website"):
            k["Company Domain"] = re.sub(r"^www\.", "", k["Website"])
            bump("companies · Company Domain from the website")
        by_name.setdefault((k.get("Company Name") or "").lower(), k)
    for r in contacts:
        k = by_name.get((r.get("Company Name") or "").lower(), {})
        if not r.get("Website") and k.get("Website"):
            r["Website"] = k["Website"]
            bump("contacts · Website from the company")
        if not r.get("Email Domain"):
            e = r.get("Email Address") or ""
            d = e.split("@")[1] if "@" in e else k.get("Company Domain", "")
            if d:
                r["Email Domain"] = d
                bump("contacts · Email Domain")
    return filled


def check(contacts, contact_cols, companies, company_cols, options):
    """-> (errors, warnings), each a list of strings naming the row and the value."""
    errors, warnings = [], []
    who = lambda r: f"{r.get('First Name', '')} {r.get('Last Name', '')} ({r.get('Company Name', '')})".strip()
    seen = {}
    for r in contacts:
        for c in ("First Name", "Last Name", "Company Name"):
            if c in contact_cols and not r.get(c):
                errors.append(f"contact {who(r)}: no {c}")
        e = r.get("Email Address", "")
        if e:
            if not EMAIL.match(e):
                errors.append(f"contact {who(r)}: email not valid: {e}")
            elif e in seen:
                errors.append(f"email {e} on two contacts: {seen[e]} and {who(r)}")
            seen.setdefault(e, who(r))
        for c, pat in (("LinkedIn Contact Profile URL", LI_IN), ("ZoomInfo Contact Profile URL", ZI_P)):
            if r.get(c) and not pat.match(r[c]):
                errors.append(f"contact {who(r)}: {c} isn't a profile link: {r[c]}")
        for c in ("First Name", "Last Name"):
            if r.get(c) and not r[c][:1].isupper():
                warnings.append(f"contact {who(r)}: {c} '{r[c]}' doesn't start with a capital")
        if r.get("Lead Source") and r["Lead Source"] != "Events":
            errors.append(f"contact {who(r)}: Lead Source '{r['Lead Source']}' (only 'Events' is written)")
        if r.get("Lead Source") and not r.get("Lead Source Detail 1"):
            errors.append(f"contact {who(r)}: Lead Source without Lead Source Detail 1 (the event name)")
    co_names = set()
    seen_site, seen_id = {}, {}
    for k in companies:
        n = k.get("Company Name", "")
        if not n:
            errors.append(f"company row with no name (website {k.get('Website', '')})")
        co_names.add(n.lower())
        site = k.get("Website", "")
        if site:
            if site in seen_site and seen_site[site] != n:
                errors.append(f"website {site} on two companies: {seen_site[site]} and {n}")
            seen_site.setdefault(site, n)
            if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", site):
                errors.append(f"company {n}: website not a plain domain: {site}")
        if not site and not k.get("Company Domain"):
            errors.append(f"company {n}: no website and no domain — find the website (web research) or "
                          "remove the company's contacts; HubSpot matches companies and contacts by domain")
        hid = k.get("HubSpot Company Record ID", "")
        if hid:
            if hid in seen_id and seen_id[hid] != n:
                errors.append(f"HubSpot record {hid} on two companies: {seen_id[hid]} and {n}")
            seen_id.setdefault(hid, n)
        for c, pat in (("LinkedIn Company Profile URL", LI_CO), ("ZoomInfo Company Profile URL", ZI_C)):
            if k.get(c) and not pat.match(k[c]):
                errors.append(f"company {n}: {c} isn't a profile link: {k[c]}")
        if k.get("Type") and k["Type"] not in TYPE_OPTIONS:
            errors.append(f"company {n}: Type '{k['Type']}' isn't a HubSpot option")
        if k.get("Employee Range") and k["Employee Range"] not in set(options.get("company_employee_range", [])):
            errors.append(f"company {n}: Employee Range '{k['Employee Range']}' isn't a HubSpot range")
    for rows, label, cols in ((contacts, "contact", contact_cols), (companies, "company", company_cols)):
        for r in rows:
            for c in (NUMBER_COLS | ID_COLS) & set(cols):
                if r.get(c) and not DIGITS.match(r[c]):
                    errors.append(f"{label} {r.get('Company Name', '')}: {c} must be digits: {r[c]}")
            for c in PHONE_COLS & set(cols):
                v = r.get(c, "")
                if v and not (re.match(r"^\(\d{3}\) \d{3}-\d{4}( ext\. \d+)?$", v) or v.startswith("+")):
                    warnings.append(f"{label} {who(r) if label == 'contact' else r.get('Company Name', '')}: "
                                    f"{c} in an unknown format: {v}")
            for sc, cc in STATE_COUNTRY.items():
                if sc in cols and r.get(sc) and r.get(cc) in NORTH_AMERICA and r[sc] not in STATES.values():
                    warnings.append(f"{label} {r.get('Company Name', '')}: {sc} '{r[sc]}' isn't a US state / "
                                    "Canadian province")
    site_of = {(k.get("Company Name") or "").lower(): k.get("Website", "") for k in companies}
    for r in contacts:
        if r.get("Company Name") and r["Company Name"].lower() not in co_names:
            errors.append(f"contact {who(r)}: company '{r['Company Name']}' isn't in the company file")
            continue
        cs = site_of.get((r.get("Company Name") or "").lower(), "")
        if cs and r.get("Website") != cs:
            errors.append(f"contact {who(r)}: Website '{r.get('Website', '')}' isn't the company's ({cs})")
        if "Email Domain" in contact_cols and not r.get("Email Domain"):
            errors.append(f"contact {who(r)}: no Email Domain (it links the contact to its company in HubSpot)")
    return errors, sorted(set(warnings))
