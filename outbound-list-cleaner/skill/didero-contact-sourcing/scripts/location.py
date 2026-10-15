"""Split a LinkedIn location into Person City / Person State / Country.

Only what is certain is filled in:
  "Austin, Texas, United States"     -> Austin / Texas / United States
  "Charlotte, NC"                    -> Charlotte / North Carolina / United States
  "Greater Chicago Area"             -> (blank) / Illinois / United States
  "Columbus, Ohio Metropolitan Area" -> (blank) / Ohio / United States
  "United States"                    -> (blank) / (blank) / United States
A metro area gives its main (first-named) city ("Columbus, Ohio Metropolitan
Area" -> Columbus / Ohio, "Greater Houston" -> Houston / Texas,
"Dallas-Fort Worth Metroplex" -> Dallas / Texas). A metro that spans several
states takes its main city's state (Washington DC-Baltimore -> Washington /
District of Columbia, Kansas City -> Missouri).
Anything not recognised comes back with certain=False so Claude resolves it
(or asks the user) instead of guessing.
"""
import re

US_STATE_CODES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia", "PR": "Puerto Rico"}
CA_PROVINCE_CODES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "ON": "Ontario", "PE": "Prince Edward Island",
    "QC": "Quebec", "SK": "Saskatchewan", "NT": "Northwest Territories", "NU": "Nunavut", "YT": "Yukon"}
UK_NATIONS = {"england": "England", "scotland": "Scotland", "wales": "Wales", "northern ireland": "Northern Ireland"}
US_STATES = {v.lower(): v for v in US_STATE_CODES.values()}
CA_PROVINCES = {v.lower(): v for v in CA_PROVINCE_CODES.values()} | {"québec": "Quebec"}

# Main city of a metro area -> (state/region, country). LinkedIn names metros after their main city.
METRO_CITIES = {
    # United States
    "new york": ("New York", "United States"), "new york city": ("New York", "United States"),
    "los angeles": ("California", "United States"), "chicago": ("Illinois", "United States"),
    "dallas": ("Texas", "United States"), "fort worth": ("Texas", "United States"),
    "houston": ("Texas", "United States"), "washington dc": ("District of Columbia", "United States"),
    "washington d.c.": ("District of Columbia", "United States"),
    "miami": ("Florida", "United States"), "philadelphia": ("Pennsylvania", "United States"),
    "atlanta": ("Georgia", "United States"), "boston": ("Massachusetts", "United States"),
    "phoenix": ("Arizona", "United States"), "san francisco": ("California", "United States"),
    "san francisco bay": ("California", "United States"), "bay": None,
    "riverside": ("California", "United States"), "detroit": ("Michigan", "United States"),
    "seattle": ("Washington", "United States"), "minneapolis": ("Minnesota", "United States"),
    "san diego": ("California", "United States"), "tampa": ("Florida", "United States"),
    "denver": ("Colorado", "United States"), "baltimore": ("Maryland", "United States"),
    "st. louis": ("Missouri", "United States"), "st louis": ("Missouri", "United States"),
    "saint louis": ("Missouri", "United States"), "orlando": ("Florida", "United States"),
    "charlotte": ("North Carolina", "United States"), "san antonio": ("Texas", "United States"),
    "portland": ("Oregon", "United States"), "sacramento": ("California", "United States"),
    "pittsburgh": ("Pennsylvania", "United States"), "austin": ("Texas", "United States"),
    "las vegas": ("Nevada", "United States"), "cincinnati": ("Ohio", "United States"),
    "kansas city": ("Missouri", "United States"), "columbus": ("Ohio", "United States"),
    "indianapolis": ("Indiana", "United States"), "cleveland": ("Ohio", "United States"),
    "san jose": ("California", "United States"), "nashville": ("Tennessee", "United States"),
    "virginia beach": ("Virginia", "United States"), "norfolk": ("Virginia", "United States"),
    "providence": ("Rhode Island", "United States"), "jacksonville": ("Florida", "United States"),
    "milwaukee": ("Wisconsin", "United States"), "raleigh": ("North Carolina", "United States"),
    "durham": ("North Carolina", "United States"), "oklahoma city": ("Oklahoma", "United States"),
    "memphis": ("Tennessee", "United States"), "richmond": ("Virginia", "United States"),
    "louisville": ("Kentucky", "United States"), "new orleans": ("Louisiana", "United States"),
    "salt lake city": ("Utah", "United States"), "hartford": ("Connecticut", "United States"),
    "buffalo": ("New York", "United States"), "birmingham": ("Alabama", "United States"),
    "grand rapids": ("Michigan", "United States"), "rochester": None,
    "tucson": ("Arizona", "United States"), "honolulu": ("Hawaii", "United States"),
    "tulsa": ("Oklahoma", "United States"), "fresno": ("California", "United States"),
    "worcester": ("Massachusetts", "United States"), "omaha": ("Nebraska", "United States"),
    "albany": ("New York", "United States"), "albuquerque": ("New Mexico", "United States"),
    "knoxville": ("Tennessee", "United States"), "el paso": ("Texas", "United States"),
    "baton rouge": ("Louisiana", "United States"), "dayton": ("Ohio", "United States"),
    "greenville": ("South Carolina", "United States"), "allentown": ("Pennsylvania", "United States"),
    "boise": ("Idaho", "United States"), "toledo": ("Ohio", "United States"),
    "akron": ("Ohio", "United States"), "des moines": ("Iowa", "United States"),
    "madison": ("Wisconsin", "United States"), "little rock": ("Arkansas", "United States"),
    "harrisburg": ("Pennsylvania", "United States"), "lansing": ("Michigan", "United States"),
    "spokane": ("Washington", "United States"), "kennewick": ("Washington", "United States"),
    "chattanooga": ("Tennessee", "United States"), "wichita": ("Kansas", "United States"),
    "greensboro": ("North Carolina", "United States"), "winston-salem": ("North Carolina", "United States"),
    "lexington": ("Kentucky", "United States"), "huntsville": ("Alabama", "United States"),
    "savannah": ("Georgia", "United States"), "fort wayne": ("Indiana", "United States"),
    "south bend": ("Indiana", "United States"), "green bay": ("Wisconsin", "United States"),
    "appleton": ("Wisconsin", "United States"), "reno": ("Nevada", "United States"),
    "anchorage": ("Alaska", "United States"), "sioux falls": ("South Dakota", "United States"),
    "fargo": ("North Dakota", "United States"), "lincoln": ("Nebraska", "United States"),
    "syracuse": ("New York", "United States"), "scranton": ("Pennsylvania", "United States"),
    "lancaster": ("Pennsylvania", "United States"), "reading": ("Pennsylvania", "United States"),
    "york": ("Pennsylvania", "United States"), "peoria": ("Illinois", "United States"),
    "rockford": ("Illinois", "United States"), "evansville": ("Indiana", "United States"),
    "charleston": None, "springfield": None, "columbia": None, "portland maine": ("Maine", "United States"),
    # Canada
    "toronto": ("Ontario", "Canada"), "montreal": ("Quebec", "Canada"), "montréal": ("Quebec", "Canada"),
    "vancouver": ("British Columbia", "Canada"), "calgary": ("Alberta", "Canada"),
    "edmonton": ("Alberta", "Canada"), "ottawa": ("Ontario", "Canada"), "winnipeg": ("Manitoba", "Canada"),
    "quebec city": ("Quebec", "Canada"), "hamilton": None, "kitchener": ("Ontario", "Canada"),
    "halifax": ("Nova Scotia", "Canada"), "london ontario": ("Ontario", "Canada"),
    # UK / Ireland
    "london": ("England", "United Kingdom"), "manchester": ("England", "United Kingdom"),
    "birmingham uk": ("England", "United Kingdom"), "leeds": ("England", "United Kingdom"),
    "glasgow": ("Scotland", "United Kingdom"), "edinburgh": ("Scotland", "United Kingdom"),
    "bristol": ("England", "United Kingdom"), "liverpool": ("England", "United Kingdom"),
    "cardiff": ("Wales", "United Kingdom"), "belfast": ("Northern Ireland", "United Kingdom"),
    "dublin": ("", "Ireland"), "cork": ("", "Ireland"),
    # elsewhere (country only; state left blank)
    "hamburg": ("", "Germany"), "munich": ("", "Germany"), "berlin": ("", "Germany"),
    "frankfurt": ("", "Germany"), "paris": ("", "France"), "amsterdam": ("", "Netherlands"),
    "zurich": ("", "Switzerland"), "mexico city": ("", "Mexico"), "monterrey": ("", "Mexico"),
    "sydney": ("", "Australia"), "melbourne": ("", "Australia"),
}
METRO_WORDS = re.compile(r"^(greater|metro)\s+|\s+(metropolitan area|metroplex|metro area|metro|area|region|"
                         r"bay area)$", re.I)


def _country(text, aliases):
    t = text.strip().lower()
    return aliases.get(t, "")


def _state(text):
    """('Texas'|'TX'|'Ontario'|'England') -> (state, country) or ('', '')."""
    t = text.strip()
    if t.upper() in US_STATE_CODES and (t.isupper() or len(t) == 2):
        return US_STATE_CODES[t.upper()], "United States"
    if t.upper() in CA_PROVINCE_CODES and (t.isupper() or len(t) == 2):
        return CA_PROVINCE_CODES[t.upper()], "Canada"
    low = t.lower()
    if low in US_STATES:
        return US_STATES[low], "United States"
    if low in CA_PROVINCES:
        return CA_PROVINCES[low], "Canada"
    if low in UK_NATIONS:
        return UK_NATIONS[low], "United Kingdom"
    return "", ""


CITY_NAMES = {"new york city": "New York", "washington dc": "Washington", "washington d.c.": "Washington",
              "st louis": "St. Louis", "saint louis": "St. Louis", "san francisco bay": "San Francisco"}


def main_city(name):
    """'Minneapolis-St. Paul' -> 'Minneapolis'; 'New York City' -> 'New York'."""
    first = re.split(r"\s*-\s*|\s+/\s+", name.strip())[0].strip()
    return CITY_NAMES.get(first.lower(), first)


def _metro(core):
    """'Minneapolis-St. Paul' / 'Columbus, Ohio' / 'Washington DC-Baltimore' -> (state, country) or None."""
    parts = [p.strip() for p in core.split(",")]
    if len(parts) == 2:  # 'Columbus, Ohio' / 'Rochester-Austin, Minnesota'
        st, co = _state(parts[1])
        if st:
            return st, co, main_city(parts[0])
    main = re.split(r"\s*-\s*|\s+/\s+", parts[0])[0].strip().lower()
    hit = METRO_CITIES.get(main) or METRO_CITIES.get(parts[0].lower())
    if not hit:
        return None
    return hit + (main_city(parts[0]),)


def parse_location(text, aliases):
    """-> {"city", "state", "country", "certain": bool, "note"}; aliases = screen.COUNTRY_ALIASES."""
    out = {"city": "", "state": "", "country": "", "certain": True, "note": ""}
    raw = (text or "").strip()
    if not raw:
        out.update(certain=False, note="no location")
        return out
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    # trailing country
    if parts and _country(parts[-1], aliases) and not _state(parts[-1])[0]:
        out["country"] = _country(parts[-1], aliases)
        parts = parts[:-1]
    if not parts:
        return out
    joined = ", ".join(parts)
    core = METRO_WORDS.sub("", METRO_WORDS.sub("", joined)).strip()
    is_metro = core != joined or bool(re.search(r"\b(area|metro|greater|region|metroplex)\b", joined, re.I))
    if is_metro:
        hit = _metro(core)
        if hit:
            out["state"], c, out["city"] = hit
            out["country"] = out["country"] or c
        else:
            out.update(certain=False, note=f"metro area '{raw}' not recognised")
        return out
    if len(parts) == 1:
        st, c = _state(parts[0])
        if st:
            out["state"], out["country"] = st, out["country"] or c
            return out
        if out["country"] and out["country"] not in ("United States", "Canada", "United Kingdom"):
            out["city"] = parts[0]   # 'Zurich, Switzerland': no state level needed
            return out
        out.update(certain=False, note=f"'{parts[0]}' — a city or region without its state")
        return out
    # 'City, State' (country maybe already taken off)
    st, c = _state(parts[-1])
    if st:
        out["city"], out["state"] = ", ".join(parts[:-1]), st
        out["country"] = out["country"] or c
        return out
    if out["country"] and out["country"] not in ("United States", "Canada", "United Kingdom"):
        out["city"] = parts[0]   # e.g. 'Hamburg, Germany' style with region in between
        out["state"] = ", ".join(parts[1:]) if len(parts) > 1 else ""
        return out
    out.update(certain=False, note=f"couldn't tell the state in '{raw}'")
    return out
