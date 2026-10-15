"""Values written exactly as Didero's HubSpot properties expect them, so nothing is remapped by hand.

Checked against the portal's property definitions (get_properties, 2026-10-13):

Employee range (companies.hs_employee_range, dropdown): 1-10, 11-50, 51-200, 201-500, 501-1,000,
  1,001-5,000, 5,001-10,000, 10,000+. From the exact employee count when there is one; otherwise
  ZoomInfo's range ("Employees.1000to4999") goes to the HubSpot range that covers most of it.
  Number of Employees (numberofemployees) is a plain number: an exact count only, never a range.

Industry — the company file carries the team's two levels (Industries cleanup file, columns C and D):
  company  Primary industry (primary_industry, dropdown) .. Manufacturing / Distribution / Software /
                                                           Services / Other  -> column "Didero Primary Industry"
           Industry group (hs_industry_group) ............. one of the team's 48 sub-industries
                                                           (config industry_map.groups), mapped from ZoomInfo's
                                                           industry|sub-industry (industry_map.zoominfo) or a
                                                           LinkedIn industry name  -> "Industry Group"
           (Industry, the HubSpot default dropdown, is still worked out but not uploaded.)
  contact  Primary Industry (primary_industry, dropdown) .. ZoomInfo top level  -> "Primary Industry"
           Primary Sub-Industry (dropdown) ................ ZoomInfo sub-industry  -> "Primary Sub-Industry"
           Company Industry (company_industry, dropdown) .. same as the company's Industry -> "Company Industry"
Values that aren't options of a dropdown are left out of the upload and listed (add the option in
HubSpot first, or leave it blank).
"""
import json
import re
from pathlib import Path

_CFG = Path(__file__).resolve().parent.parent / "config.json"

EMPLOYEE_RANGES = ["1-10", "11-50", "51-200", "201-500", "501-1,000", "1,001-5,000", "5,001-10,000", "10,000+"]
_BOUNDS = [(1, 10), (11, 50), (51, 200), (201, 500), (501, 1000), (1001, 5000), (5001, 10000), (10001, 10 ** 12)]

DIDERO_PRIMARY = ["Manufacturing", "Distribution", "Software", "Services", "Other"]
SERVICES = {"business services", "consumer services", "transportation", "telecommunications", "hospitality",
            "finance", "insurance", "real estate", "law firms & legal services", "hospitals & physicians clinics",
            "healthcare services", "media & internet", "education", "organizations"}
# ZoomInfo top-level industry -> HubSpot company "Industry" option label (only where the label differs).
INDUSTRY_OPTION = {"retail": "Retail", "construction": "Construction", "insurance": "Insurance",
                   "telecommunications": "Telecommunications", "real estate": "Real Estate",
                   "hospitality": "Hospitality", "education": "Education Management",
                   "government": "Government Administration", "agriculture": "Farming",
                   "consumer services": "Consumer Services", "hospitals & physicians clinics": "Hospital & Health Care",
                   "healthcare services": "Hospital & Health Care", "law firms & legal services": "Legal Services",
                   "cultural": "Museums and Institutions", "energy, utilities & waste": "Energy, Utilities & Waste",
                   "minerals & mining": "Minerals & Mining", "minerals and mining": "Minerals & Mining"}
# contact "Primary Industry" option spelled differently from ZoomInfo
CONTACT_PRIMARY = {"Minerals & Mining": "Minerals and Mining"}
INDUSTRY_SAME = {"Manufacturing", "Business Services", "Software", "Finance", "Holding Companies & Conglomerates",
                 "Media & Internet", "Minerals & Mining", "Transportation", "Organizations",
                 "Energy, Utilities & Waste"}


ZI_TOPS = {"Agriculture", "Business Services", "Construction", "Consumer Services", "Cultural", "Education",
           "Energy, Utilities & Waste", "Finance", "Government", "Healthcare Services", "Holding Companies & Conglomerates",
           "Hospitality", "Hospitals & Physicians Clinics", "Insurance", "Law Firms & Legal Services", "Manufacturing",
           "Media & Internet", "Minerals & Mining", "Organizations", "Real Estate", "Retail", "Software",
           "Telecommunications", "Transportation"}
# LinkedIn-style industry names ("Food and Beverage Manufacturing") -> ZoomInfo top level, by keyword
_COARSE = [(r"manufactur", "Manufacturing"), (r"software", "Software"), (r"retail", "Retail"),
           (r"construct", "Construction"), (r"transport|logistic|trucking|freight|airline|maritime", "Transportation"),
           (r"utilit|energy|oil|gas|power generation", "Energy, Utilities & Waste"), (r"mining|metals", "Minerals & Mining"),
           (r"bank|financ|invest|capital market", "Finance"), (r"insur", "Insurance"), (r"telecom|wireless", "Telecommunications"),
           (r"hospital|health care|medical practice", "Hospitals & Physicians Clinics"), (r"real estate", "Real Estate"),
           (r"consult|staffing|marketing|advertis|accounting|legal|it services|business services|outsourc", "Business Services"),
           (r"education|e-learning", "Education"), (r"hospitality|restaurant|food and beverage services", "Hospitality"),
           (r"government", "Government"), (r"farming|agricultur|dairy|ranching", "Agriculture")]


def hubspot_industries():
    try:
        return set(json.loads(_CFG.read_text()).get("hubspot_options", {}).get("company_industry", []))
    except (OSError, ValueError):
        return set()


def to_zi_top(name):
    n = (name or "").strip()
    if n in ZI_TOPS:
        return n
    if n == "Minerals and Mining":
        return "Minerals & Mining"
    low = n.lower()
    return next((top for pat, top in _COARSE if re.search(pat, low)), "")


def _int(v):
    try:
        return int(float(re.sub(r"[^\d.]", "", str(v)))) if re.search(r"\d", str(v or "")) else None
    except ValueError:
        return None


def employee_range(count, zi_range=""):
    """-> (HubSpot option or "", how)"""
    n = _int(count)
    if n and n > 0:
        return next(lab for lab, (lo, hi) in zip(EMPLOYEE_RANGES, _BOUNDS) if lo <= n <= hi), "from the count"
    raw = str(zi_range or "").strip()
    if raw in EMPLOYEE_RANGES:
        return raw, "already a HubSpot range"
    s = re.sub(r"^employees\.", "", raw.lower()).replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+)(?:to|-)(\d+)$", s) or re.match(r"^(\d+)(?:plus|\+)$", s)
    if not m:
        return "", f"can't read '{raw}'" if raw else ""
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.lastindex == 2 else 10 ** 12
    if s.endswith(("plus", "+")) and lo >= 10000:
        return "10,000+", "from ZoomInfo's range"
    # the HubSpot range that covers most of ZoomInfo's range
    best = max(zip(EMPLOYEE_RANGES, _BOUNDS), key=lambda x: min(hi, x[1][1]) - max(lo, x[1][0]))
    return best[0], f"from ZoomInfo's range {raw} (no exact count)"


def split_industry(primary, sub=""):
    """'Manufacturing- Building Materials' / 'Manufacturing; X' (combined forms) or separate columns -> (top, sub)."""
    p, sub = (primary or "").strip(), (sub or "").strip()
    parts = re.split(r"\s*-{1,2}\s+|\s*;\s*", p, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), sub or parts[1].strip()
    return p, sub


def industry_map():
    try:
        return json.loads(_CFG.read_text()).get("industry_map", {})
    except (OSError, ValueError):
        return {}


def industry_group(top, sub, imap=None):
    """Company Industry group (the team's sub-industry list, config industry_map.groups) from ZoomInfo's
    industry + sub-industry, or from a LinkedIn industry name. "" when nothing fits (listed for review)."""
    imap = imap if imap is not None else industry_map()
    zi = imap.get("zoominfo", {})
    t, s_ = (top or "").strip(), (sub or "").strip()
    if t in ZI_TOPS and s_ and f"{t}|{s_}" in zi:          # ZoomInfo industry + sub-industry
        return zi[f"{t}|{s_}"][0]
    raw = f"{t} {s_}".lower()
    for pat, group in imap.get("linkedin_keywords", []):   # LinkedIn names ("Chemical Manufacturing", ...)
        if re.search(pat, raw):
            return group
    return (zi.get(t if t in ZI_TOPS else to_zi_top(t)) or [""])[0]  # industry only


def didero_primary(top, sub, company="", group="", imap=None):
    """Primary industry: Manufacturing / Distribution / Software / Services / Other (the team's column C).
    Distributors / wholesalers -> Distribution; ZoomInfo Manufacturing -> Manufacturing, Software -> Software,
    Retail -> Distribution; anything else -> the Primary industry the team pairs most often with the
    company's Industry group (cleanup file), else Services / Other."""
    imap = imap if imap is not None else industry_map()
    t, s, c = (to_zi_top(top) or top or "").lower(), (sub or "").lower(), (company or "").lower()
    if any(w in s or w in t for w in ("wholesale", "distribut")):
        return "Distribution"
    if t == "manufacturing":
        return "Manufacturing"
    if re.search(r"\b(supply|supplies|wholesale|distribut\w*)\b", c):  # a "Retail" supply house sells to trades
        return "Distribution"
    if t == "software":
        return "Software"
    if t == "retail":
        return "Distribution"
    by_group = imap.get("primary_by_group", {}).get(group)
    if by_group:
        return by_group
    if t in SERVICES:
        return "Services"
    return "Other" if t else ""


def industry_option(name, options=None):
    """HubSpot company Industry option: the value itself when HubSpot has it (LinkedIn names often are
    options, e.g. "Food and Beverage Manufacturing"), else ZoomInfo's top level as an option."""
    t = (name or "").strip()
    if not t:
        return ""
    if t in (options if options is not None else hubspot_industries()):
        return t
    top = to_zi_top(t)
    if top in INDUSTRY_SAME:
        return top
    return INDUSTRY_OPTION.get(top.lower(), "")


def apply_rows(rows, fields, overrides=None):
    """Fill the HubSpot-ready columns on every row. Returns notes for the chat.
    overrides: {"<company name>": "<Didero primary industry>"} — Claude's / the user's decisions for the
    companies the rule can't place (decisions_step2.json "didero_primary_industry")."""
    overrides = overrides or {}
    for col in ("Employee Range", "Primary Industry", "Primary Sub-Industry", "Industry Group", "Industry",
                "Didero Primary Industry", "Company Industry"):
        if col not in fields:
            fields.append(col)
    options = hubspot_industries()
    if "Industry Source" not in fields:
        fields.append("Industry Source")
    notes = {"employee_range_estimated": set(), "employee_range_unreadable": set(), "industry_group_unmapped": set(),
             "primary_industry_other": set()}
    imap = industry_map()
    for r in rows:
        rng, how = employee_range(r.get("Employees"), r.get("Employee Range"))
        if rng or not r.get("Employee Range"):
            r["Employee Range"] = rng
        if "no exact count" in how:
            notes["employee_range_estimated"].add(f"{r.get('Company Name')}: {how}")
        elif how.startswith("can't"):
            notes["employee_range_unreadable"].add(f"{r.get('Company Name')}: {how}")
        top, sub = split_industry(r.get("Primary Industry"), r.get("Primary Sub-Industry"))
        if not top:
            continue
        # Re-runs see Primary Industry already turned into ZoomInfo's top level: keep the source value
        # (e.g. LinkedIn's "Food and Beverage Manufacturing") unless the industry really changed.
        prev = r.get("Industry Source", "")
        if prev and "|" in prev:
            ptop, psub = prev.split("|", 1)
            if top == (to_zi_top(ptop) or ptop) and sub == psub:
                top, sub = ptop, psub
        r["Industry Source"] = f"{top}|{sub}"
        zi_top = to_zi_top(top) or top
        r["Primary Industry"], r["Primary Sub-Industry"] = CONTACT_PRIMARY.get(zi_top, zi_top), sub
        r["Industry"] = r["Company Industry"] = industry_option(top, options)
        # Industry group = the team's sub-industry list (config industry_map), mapped from ZoomInfo / LinkedIn
        r["Industry Group"] = industry_group(top, sub, imap)
        if not r["Industry Group"]:
            notes["industry_group_unmapped"].add(f"{r.get('Company Name')}: '{top}{' / ' + sub if sub else ''}'")
        # recomputed whenever the industry changes; a correction is made at step 4 (after the last step 2)
        r["Didero Primary Industry"] = overrides.get(r.get("Company Name")) or didero_primary(
            top, sub, r.get("Company Name"), r["Industry Group"], imap)
        if r["Didero Primary Industry"] == "Other" and r.get("Company Name") not in overrides:
            notes["primary_industry_other"].add(f"{r.get('Company Name')} ({top}{' / ' + sub if sub else ''})")
    return {k: sorted(v) for k, v in notes.items() if v}
