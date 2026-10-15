"""The upload files' one format — the skill checks and fixes it itself before step 5, so every run
(whoever runs it) produces the same files. Nothing here stops the run: every problem has a rule.

`worksheet.py export` always writes the same columns in the same order, then:
  1. normalize   safe, mechanical formatting (below)
  2. resolve     the rules for problems, each one logged in <run_dir>/decisions.md:
     - same website or same HubSpot record on two companies -> one company (HubSpot treats them as one):
       the one with more contacts (then more data) is kept, the other's contacts move to it
     - every contact's company name and website come from its company row
     - websites and domains on both files: company domain from the website; contact email domain from
       the email, else the company's domain
     - invalid email: blanked only when it has no domain (no "@something.tld"); otherwise kept as it is
     - duplicate email: the email stays with the contact whose name matches it more closely (then the one
       with more data); the other contact stays, without the email. The same person twice -> one row,
       combined
     - Sales Navigator links are fine (kept as they are)
     - any other value that isn't valid for its column -> that cell left blank
  3. report      counts printed; contacts with no name and companies with no website/domain listed

The format (from the hand-cleaned CBM M&A files and Didero's HubSpot properties):
  names .......... no stray spaces; ALL CAPS / all lower -> Capitalized
  email .......... lowercase
  phones ......... US / Canada "(312) 555-0142" (+ " ext. 12"); others "+<country code> …"
  website ........ "www.acme.com" — no https://, no path (subdomains other than www kept)
  LinkedIn ....... https://www.linkedin.com/in/<slug> · /company/<slug> (Sales Navigator links kept)
  ZoomInfo ....... https://app.zoominfo.com/#/apps/profile/person/<id> · …/company/<id>
  country ........ full name ("United States", "United Kingdom")
  state .......... full name for the US and Canada ("Illinois", "Ontario")
  numbers / IDs .. digits only
  dropdowns ...... HubSpot's options (Type, Employee range, industries, Lead Source from the start answer)
"""
import re

from location import CA_PROVINCE_CODES, US_STATE_CODES

PLACEHOLDERS = {"nan", "none", "null", "n/a", "na", "-", "--", "not in hubspot", "#n/a", "undefined"}
TYPE_OPTIONS = {"Prospect", "Partner", "Reseller", "Vendor", "Other", "Customer", "Manually Reviewed, Not Propsect"}
HAS_DOMAIN = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
DIGITS = re.compile(r"^\d+$")
DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
LI_IN = re.compile(r"^https://www\.linkedin\.com/(in|sales/lead|sales/people)/\S+$")
LI_CO = re.compile(r"^https://www\.linkedin\.com/(company|sales/company)/\S+$")
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
COMPANY_ID = "ZoomInfo Company ID"


# ---------- 1. normalize ----------
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
    if h and not h.startswith("www.") and (h.count(".") == 1 or (h.count(".") == 2 and TWO_LEVEL.search(h))):
        h = "www." + h
    return h


def linkedin(v, kind):
    m = re.search(rf"linkedin\.com/{kind}/([^/?#\s]+)", v, re.I)
    if m:
        return f"https://www.linkedin.com/{kind}/{m.group(1).rstrip('/')}"
    return re.sub(r"^(https?://)?(www\.)?linkedin\.com", "https://www.linkedin.com", v.strip(), flags=re.I)


def zoominfo(v, kind):
    m = re.search(rf"/profile/{kind}/(-?\d+)", v)
    return f"https://app.zoominfo.com/#/apps/profile/{kind}/{m.group(1)}" if m else v.strip()


def name_case(v):
    if v.isupper() or v.islower():
        return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in v.split(" "))
    return v


def normalize(rows, cols):
    """Safe formatting on the rows going into an upload file. Returns {column: n changed}."""
    changed = {}
    for r in rows:
        for c in cols:
            v = "" if r.get(c) is None else str(r.get(c))
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
    for r in rows:
        for sc, cc in STATE_COUNTRY.items():
            if sc in cols and r.get(sc) and (r.get(cc) in NORTH_AMERICA or not r.get(cc)):
                full = STATES.get(r[sc].lower().strip("."))
                if full and full != r[sc]:
                    r[sc] = full
                    changed[sc] = changed.get(sc, 0) + 1
    return changed


# ---------- 2. resolve ----------
def filled(r):
    return sum(1 for v in r.values() if v)


def name_score(email, first, last):
    """How closely the email's local part matches the person's name (3 = first + last)."""
    loc = re.sub(r"[^a-z]", "", (email or "").split("@")[0].lower())
    f, l = re.sub(r"[^a-z]", "", (first or "").lower()), re.sub(r"[^a-z]", "", (last or "").lower())
    if f and l and f in loc and l in loc:
        return 3
    if f and l and (loc.startswith(f[0] + l) or loc.startswith(f + l[0])):
        return 2
    if (l and l in loc) or (f and len(f) > 2 and f in loc):
        return 1
    return 0


def valid(col, v):
    if not v:
        return True
    if col in NUMBER_COLS | ID_COLS:
        return bool(DIGITS.match(v))
    if col in PHONE_COLS:
        return bool(re.match(r"^\(\d{3}\) \d{3}-\d{4}( ext\. \d+)?$", v)) or (
            v.startswith("+") and len(re.sub(r"\D", "", v)) >= 7)
    if col in ("Website", "Email Domain", "Company Domain"):
        return bool(DOMAIN.match(v))
    if col == "Additional Domains":
        return all(DOMAIN.match(x.strip()) for x in v.split(";") if x.strip())
    if col == "LinkedIn Contact Profile URL":
        return bool(LI_IN.match(v))
    if col == "LinkedIn Company Profile URL":
        return bool(LI_CO.match(v))
    if col == "ZoomInfo Contact Profile URL":
        return bool(ZI_P.match(v))
    if col == "ZoomInfo Company Profile URL":
        return bool(ZI_C.match(v))
    if col in ("First Name", "Last Name"):
        return not re.search(r"[@\d]|https?:", v)
    if col == "Type":
        return v in TYPE_OPTIONS
    return True


def resolve(contacts, companies, contact_cols, company_cols, options):
    """Apply the rules (module docstring). companies: {company id: row}.
    Returns (contacts, companies, notes, blanked counts, info lines)."""
    notes = []
    who = lambda r: f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip() or r.get("Email Address", "")
    # same website / HubSpot record on two companies -> one company
    n_contacts = {}
    for r in contacts:
        n_contacts[r.get(COMPANY_ID)] = n_contacts.get(r.get(COMPANY_ID), 0) + 1
    rank = lambda cid: (n_contacts.get(cid, 0), filled(companies[cid]))
    moved = {}
    for key in ("Website", "HubSpot Company Record ID"):
        seen = {}
        for cid in list(companies):
            v = companies.get(cid, {}).get(key, "")
            if not v:
                continue
            other = seen.get(v)
            if other and other in companies and other != cid:
                keep, drop = (other, cid) if rank(other) >= rank(cid) else (cid, other)
                for c, val in companies[drop].items():
                    if val and not companies[keep].get(c):
                        companies[keep][c] = val
                notes.append(f"{companies[drop].get('Company Name')} and {companies[keep].get('Company Name')} share "
                             f"{key.lower()} {v}: kept one company, {companies[keep].get('Company Name')}")
                moved[drop] = keep
                n_contacts[keep] = n_contacts.get(keep, 0) + n_contacts.pop(drop, 0)
                del companies[drop]
                seen[v] = keep
            else:
                seen[v] = cid

    def final(cid):
        while cid in moved:
            cid = moved[cid]
        return cid
    # contacts take their company's name and website; domains on both files
    for k in companies.values():
        if not k.get("Company Domain") and k.get("Website"):
            k["Company Domain"] = re.sub(r"^(https?://)?(www\.)?", "", k["Website"])
    for r in contacts:
        r[COMPANY_ID] = final(r.get(COMPANY_ID))
        k = companies.get(r[COMPANY_ID], {})
        for c in ("Company Name", "Website"):
            if k.get(c):
                r[c] = k[c]
    # invalid email: only when it has no domain
    for r in contacts:
        e = r.get("Email Address", "")
        if e and not HAS_DOMAIN.match(e):
            notes.append(f"{who(r)}: email '{e}' has no domain — blanked")
            r["Email Address"] = ""
        if r.get("Additional Emails"):
            r["Additional Emails"] = ";".join(x.strip() for x in r["Additional Emails"].split(";")
                                              if HAS_DOMAIN.match(x.strip()))
        em = r.get("Email Address") or ""
        if "@" in em:  # the email domain always follows the email
            r["Email Domain"] = em.split("@")[1]
        elif not r.get("Email Domain"):
            r["Email Domain"] = companies.get(r[COMPANY_ID], {}).get("Company Domain", "")
    # duplicate emails: keep the closer name match, then more data
    by_email = {}
    for r in contacts:
        if r.get("Email Address"):
            by_email.setdefault(r["Email Address"], []).append(r)
    dropped = set()
    for e, group in by_email.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: (name_score(e, r.get("First Name"), r.get("Last Name")), filled(r)), reverse=True)
        keeper = group[0]
        for other in group[1:]:
            same = who(other).lower() == who(keeper).lower()
            if same:  # the same person twice: one row, with everything both rows had
                for c, v in other.items():
                    if v and not keeper.get(c):
                        keeper[c] = v
                dropped.add(id(other))
                notes.append(f"email {e}: {who(keeper)} was on the list twice — rows combined")
            else:  # two people: the email stays with the closer name; the other keeps everything but the email
                other["Email Address"] = ""
                other["Email Domain"] = companies.get(other.get(COMPANY_ID), {}).get("Company Domain", "")
                notes.append(f"email {e} on {who(keeper)} and {who(other)}: the email stays with {who(keeper)} "
                             f"(name matches it more closely); {who(other)} stays as a contact without an email")
    contacts = [r for r in contacts if id(r) not in dropped]
    # any other invalid value -> blank cell
    blanked = {}

    def blank(r, c, label, why):
        blanked[f"{label} · {c}"] = blanked.get(f"{label} · {c}", 0) + 1
        place = r.get("Company Name", "") + (f" / {who(r)}" if label == "contacts" else "")
        notes.append(f"{place}: {c} '{r[c]}' {why} — left blank")
        r[c] = ""
    for rows, cols, label in ((contacts, contact_cols, "contacts"), (list(companies.values()), company_cols, "companies")):
        for r in rows:
            for c in cols:
                if not valid(c, r.get(c, "")):
                    blank(r, c, label, "isn't valid")
            for sc, cc in STATE_COUNTRY.items():
                if sc in cols and r.get(sc) and r.get(cc) in NORTH_AMERICA and r[sc] not in STATES.values():
                    blank(r, sc, label, "isn't a US state / Canadian province")
    ranges = set(options.get("company_employee_range", []))
    for k in companies.values():
        if ranges and k.get("Employee Range") and k["Employee Range"] not in ranges:
            blank(k, "Employee Range", "companies", "isn't a HubSpot range")
    for r in contacts:
        if r.get("Lead Source") and not r.get("Lead Source Detail 1"):  # e.g. per-owner detail but no owner
            blank(r, "Lead Source", "contacts", "has no lead source detail with it")
    info = [f"contact with no name (kept): {r.get('Email Address') or r.get('Company Name')}"
            for r in contacts if not (r.get("First Name") or r.get("Last Name"))]
    info += [f"company with no website or domain (kept; HubSpot can't link its contacts by domain — step 6 checks "
             f"the associations): {k.get('Company Name')}" for k in companies.values()
             if not (k.get("Website") or k.get("Company Domain"))]
    return contacts, companies, notes, blanked, info
