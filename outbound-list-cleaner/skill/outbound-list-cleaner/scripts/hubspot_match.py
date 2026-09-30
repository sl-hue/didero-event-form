"""Step 3 — HubSpot duplicate matching.

The script never talks to HubSpot itself: Claude runs the searches through the
HubSpot connector, saves each raw response as a JSON file in a folder, and the
script scores the results. Companies first (they are the anchor records), then
contacts.

  setup-token       Authorize the HubSpot private app on this device. Three ways:
                      (no flags)       interactive, in the user's own terminal:
                                       consent prompt + hidden token input
                      --open-terminal  open a new terminal window on the user's
                                       computer running the interactive setup
                      --from-file F    for Cowork / no terminal: the user saved
                                       the token in file F; with --authorized
                                       (the user said yes in chat) it is
                                       checked, moved to the private token
                                       file, and F is deleted
                    Claude never reads or prints the token.
  check-token       Confirm the saved token works (never prints it).
  run-plan          Run a search plan directly against the HubSpot API with the
                    private app token, saving responses in the same format the
                    connector returns. Much faster than running the plan
                    through the connector; use the connector only as fallback.
  ingest            Connector mode: normalize a saved connector result (a
                    search_crm_objects / get_crm_objects JSON, or a
                    query_crm_data result with its "Dataset TSV") into the
                    raw-dir format the match commands read. Claude never has
                    to retype results by hand.
  plan-companies    Write the HubSpot searches to run for the company file.
  match-companies   Score saved HubSpot company results against the company
                    file -> company_matches.json.
  apply-companies   Add "HubSpot Company Record ID" to the company file (from
                    company_decisions.json) and sync company fields into the
                    contact file.
  plan-contacts     Write the HubSpot searches to run for the contact file.
  match-contacts    Score saved HubSpot contact results -> contact_matches.json.
  apply-contacts    Add "HubSpot Contact Record ID" to the contact file.

Decision files map the list record to the surviving HubSpot record, or null
when it is not in HubSpot:
  company_decisions.json  {"<ZoomInfo Company ID>": {"record_id": "123" | null, "note": "..."}}
  contact_decisions.json  {"<ZoomInfo Contact ID>": {"record_id": "456" | null, "note": "..."}}
"""
import argparse
import csv
import getpass
import platform
import shlex
import shutil
import sys
import subprocess
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request


from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet as ws  # noqa: E402

COMPANY_ID = "ZoomInfo Company ID"
CONTACT_ID = "ZoomInfo Contact ID"
COMPANY_RECORD = "HubSpot Company Record ID"
CONTACT_RECORD = "HubSpot Contact Record ID"
NOT_IN_HUBSPOT = "Not in HubSpot"
HUBSPOT_LINKEDIN = "lgm_linkedinurl"  # "Linkedin Url (Default)"
CHUNK = 100

COMPANY_PROPERTIES = [
    "name", "domain", "website", "city", "state", "country", "location", "zoominfo_company_id",
    "linkedin_company_page", "numberofemployees", "annualrevenue", "industry",
    "num_associated_contacts", "type", "createdate",
]
CONTACT_PROPERTIES = [
    "firstname", "lastname", "email", "jobtitle", "company", "city", "state", "country",
    HUBSPOT_LINKEDIN, "associatedcompanyid", "zoominfo_contact_id", "createdate",
]

NICKNAMES = {
    "william": {"bill", "billy", "will", "willy", "liam"}, "robert": {"bob", "bobby", "rob", "robbie", "bert"},
    "richard": {"rick", "ricky", "rich", "dick"}, "michael": {"mike", "mikey", "mick"},
    "james": {"jim", "jimmy", "jamie"}, "joseph": {"joe", "joey"}, "thomas": {"tom", "tommy"},
    "christopher": {"chris", "topher"}, "daniel": {"dan", "danny"}, "matthew": {"matt"},
    "anthony": {"tony"}, "andrew": {"andy", "drew", "aj"}, "joshua": {"josh"},
    "jeffrey": {"jeff"}, "steven": {"steve"}, "stephen": {"steve"}, "timothy": {"tim"},
    "patrick": {"pat"}, "peter": {"pete"}, "ronald": {"ron", "ronnie"}, "donald": {"don", "donnie"},
    "samuel": {"sam", "sammy"}, "benjamin": {"ben", "benny"}, "edward": {"ed", "eddie", "ted"},
    "gregory": {"greg"}, "kenneth": {"ken", "kenny"}, "nicholas": {"nick"}, "jonathan": {"jon"},
    "bradley": {"brad"}, "arthur": {"art"}, "charles": {"charlie", "chuck"}, "david": {"dave"},
    "douglas": {"doug"}, "gerald": {"jerry"}, "lawrence": {"larry"}, "raymond": {"ray"},
    "elizabeth": {"liz", "beth", "betsy", "eliza"}, "katherine": {"kate", "katie", "kathy"},
    "catherine": {"cathy", "kate", "katie"}, "jennifer": {"jen", "jenny"}, "rebecca": {"becky"},
    "susan": {"sue", "susie"}, "margaret": {"maggie", "peggy", "meg"}, "sandra": {"sandy"},
    "patricia": {"pat", "patty", "trish"}, "deborah": {"deb", "debbie"}, "kimberly": {"kim"},
    "christine": {"chris", "chrissy"}, "jacob": {"jake"}, "zachary": {"zach"}, "alexander": {"alex"},
    "frederick": {"fred"}, "phillip": {"phil"}, "philip": {"phil"}, "leonard": {"len", "lenny"},
}


def letters(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_domain(value):
    v = (value or "").strip().lower()
    v = re.sub(r"^[a-z]+://", "", v)
    v = v.split("/")[0].split("?")[0]
    return v[4:] if v.startswith("www.") else v


def linkedin_slug(url, kind):
    m = re.search(rf"linkedin\.com/{kind}/([^/?#]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


COMPANY_STOPWORDS = {"the", "inc", "llc", "co", "corp", "corporation", "company", "ltd", "lp", "plc", "and"}


def norm_company_name(name):
    words = re.sub(r"[^a-z0-9 ]", " ", re.sub(r"['’.]", "", (name or "").lower()).replace("&", " and ")).split()
    return " ".join(w for w in words if w not in COMPANY_STOPWORDS)


# Words too common in company names to signal a duplicate on their own.
GENERIC_WORDS = {"supply", "supplies", "industries", "industry", "group", "distribution", "products",
                 "materials", "building", "solutions", "services", "international", "holdings",
                 "manufacturing", "mfg", "systems", "enterprises", "partners", "global", "usa", "america"}


def name_similarity(a, b):
    a, b = norm_company_name(a), norm_company_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta = [w for w in a.split() if w not in GENERIC_WORDS] or a.split()
    tb = [w for w in b.split() if w not in GENERIC_WORDS] or b.split()
    da, db = " ".join(ta), " ".join(tb)
    ratio = SequenceMatcher(None, da, db).ratio()
    # Whole-word containment ("Kodiak" in "Kodiak Building Partners"); weaker
    # for short acronyms, which collide with unrelated names ("EMS").
    small, big = (set(ta), set(tb)) if len(ta) <= len(tb) else (set(tb), set(ta))
    if small <= big:
        ratio = max(ratio, 0.85 if len("".join(small)) >= 5 else 0.7)
    return ratio


STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa", "ks": "kansas",
    "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland", "ma": "massachusetts",
    "mi": "michigan", "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico",
    "ny": "new york", "nc": "north carolina", "nd": "north dakota", "oh": "ohio", "ok": "oklahoma",
    "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont",
    "va": "virginia", "wa": "washington", "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
    "dc": "district of columbia", "pr": "puerto rico",
    # Canada
    "ab": "alberta", "bc": "british columbia", "mb": "manitoba", "nb": "new brunswick",
    "nl": "newfoundland and labrador", "ns": "nova scotia", "on": "ontario", "pe": "prince edward island",
    "qc": "quebec", "sk": "saskatchewan", "nt": "northwest territories", "nu": "nunavut", "yt": "yukon",
}
COUNTRIES = {"us": "united states", "usa": "united states", "united states of america": "united states",
             "ca": "canada", "uk": "united kingdom", "gb": "united kingdom", "great britain": "united kingdom"}


def norm_state(value):
    v = re.sub(r"[^a-z ]", "", unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()).strip()
    return STATES.get(v, v)


def norm_country(value):
    v = re.sub(r"[^a-z ]", "", (value or "").lower()).strip()
    return COUNTRIES.get(v, v)


def parse_location(value):
    """HubSpot's `location`: "Salinas, CA, USA" / "Frankfurt, Germany" -> city/state/country."""
    parts = [p.strip() for p in (value or "").split(",") if p.strip()]
    if len(parts) >= 3:
        return {"city": parts[0], "state": parts[-2], "country": parts[-1]}
    if len(parts) == 2:
        return {"city": parts[0], "country": parts[1]}
    return {}


def with_location(record):
    """City/state/country are the main source; `location` only fills gaps."""
    parsed = parse_location(record.get("location"))
    if not parsed:
        return record
    filled = dict(record)
    for k, v in parsed.items():
        filled[k] = record.get(k) or v
    return filled


def same_location(a, b, keys=(("city", "city"), ("state", "state"), ("country", "country"))):
    """Which of city/state/country two records share, tolerant of state codes
    ("TX" = "Texas") and country spellings. Returns e.g. "state/country"."""
    a, b = with_location(a), with_location(b)
    shared = []
    for ka, kb in keys:
        va, vb = a.get(ka), b.get(kb)
        if not va or not vb:
            continue
        norm = norm_state if "state" in ka.lower() else norm_country if "country" in ka.lower() else \
            (lambda s: re.sub(r"[^a-z]", "", s.lower()))
        if norm(va) == norm(vb):
            shared.append(kb if kb in ("city", "state", "country") else ka.split()[-1].lower())
    return "/".join(shared)


def load_records(raw_dir):
    """Every record in every saved HubSpot response, de-duplicated by id."""
    records, url_template = {}, ""
    for path in sorted(Path(raw_dir).glob("*.json")):
        data = json.loads(path.read_text())
        for resp in data if isinstance(data, list) else [data]:
            url_template = resp.get("urlTemplate") or url_template
            for rec in resp.get("results", []):
                records[str(rec["id"])] = rec.get("properties", {})
    return records, url_template


def record_url(template, record_id):
    return template.replace("{id}", str(record_id)).split("?")[0] if template else ""


def chunks(values, size=CHUNK):
    values = sorted(set(v for v in values if v))
    return [values[i:i + size] for i in range(0, len(values), size)]


def in_searches(object_type, prop, values, properties):
    return [{"objectType": object_type, "properties": properties,
             "filterGroups": [{"filters": [{"propertyName": prop, "operator": "IN", "values": chunk}]}],
             "limit": 200} for chunk in chunks(values)]


# ---------------------------------------------------------------- HubSpot API

API = "https://api.hubapi.com"
TOKEN_VAR = "HUBSPOT_PRIVATE_APP_TOKEN"
OBJECT_PATHS = {"COMPANY": "companies", "CONTACT": "contacts"}
OBJECT_TYPE_IDS = {"COMPANY": "0-2", "CONTACT": "0-1"}


TOKEN_FILE = Path(os.environ.get("HUBSPOT_TOKEN_FILE",
                                  Path.home() / ".config" / "outbound-list-cleaner" / "hubspot_token"))
SCOPES = ["crm.objects.companies.read", "crm.objects.contacts.read", "crm.lists.read"]
SETUP_COMMAND = "python3 scripts/hubspot_match.py setup-token"


def load_token():
    """Environment variable first, then the private token file from setup-token."""
    token = os.environ.get(TOKEN_VAR, "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
    return token


def api(method, path, body=None, token=None):
    token = token or load_token()
    if not token:
        raise SystemExit(f"No HubSpot private app token on this device. Run `{SETUP_COMMAND}` in your "
                         f"own terminal to authorize it, or set {TOKEN_VAR}.")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(6):
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:  # rate limit / transient: back off
                time.sleep(2 ** attempt)
                continue
            if e.code in (401, 403):
                raise SystemExit("HubSpot rejected the private app token (wrong or expired token, or "
                                 f"missing scopes: {', '.join(SCOPES)}). Nothing was saved; "
                                 f"re-run `{SETUP_COMMAND}` with the right token.")
            raise SystemExit(f"HubSpot API {method} {path} failed: {e.code} {e.read()[:300]!r}")
    raise SystemExit(f"HubSpot API {method} {path}: still rate-limited after retries")


def verify(token=None):
    info = api("GET", "/account-info/v3/details", token=token)
    api("POST", "/crm/v3/objects/companies/search", {"limit": 1}, token=token)
    api("POST", "/crm/v3/objects/contacts/search", {"limit": 1}, token=token)
    return info.get("portalId")


def check_token(args):
    source = "environment variable" if os.environ.get(TOKEN_VAR) else f"token file {TOKEN_FILE}"
    portal = verify()
    print(f"token OK ({source}) for HubSpot portal {portal}: can read companies and contacts")


def save_token(token):
    portal = verify(token)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.touch(mode=0o600)
    TOKEN_FILE.chmod(0o600)
    TOKEN_FILE.write_text(token)
    print(f"Authorized for HubSpot portal {portal}; token saved to {TOKEN_FILE} (only you can read it). "
          f"To revoke, delete that file or rotate the token in HubSpot.")


def open_terminal():
    """Open a terminal window on the user's computer running the interactive setup."""
    script = Path(__file__).resolve()
    cmd = f"cd {shlex.quote(str(script.parent.parent))} && python3 {shlex.quote(str(script))} setup-token"
    system = platform.system()
    if system == "Darwin":
        apple = cmd.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{apple}"',
                        "-e", 'tell application "Terminal" to activate'], check=True)
    elif system == "Windows":
        subprocess.run(["cmd", "/c", "start", "cmd", "/k",
                        f'python "{script}" setup-token'], check=True)
    else:
        for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
            if shutil.which(term):
                args = [term, "--", "bash", "-c", cmd + "; exec bash"] if term == "gnome-terminal" \
                    else [term, "-e", f"bash -c {shlex.quote(cmd + '; exec bash')}"]
                subprocess.Popen(args)
                break
        else:
            raise SystemExit(f"No terminal app found. Open a terminal yourself and run: {SETUP_COMMAND}")
    print("Opened a terminal window with the HubSpot setup. Finish it there, then tell Claude you're done.")


def setup_token(args):
    if args.open_terminal:
        return open_terminal()
    if args.from_file:
        if not args.authorized:
            raise SystemExit("Ask the user to authorize reading HubSpot companies and contacts with the "
                             "private app, then re-run with --authorized.")
        src = Path(args.from_file).expanduser()
        if not src.exists():
            raise SystemExit(f"{src} not found. Ask the user to save the token there (the file should "
                             "contain only the token).")
        token = src.read_text().strip()
        save_token(token)
        src.unlink()
        print(f"Removed {src} so the token doesn't sit in the project folder.")
        return
    if not os.isatty(0):
        raise SystemExit(f"setup-token needs your own terminal (it reads the token as hidden input). "
                         f"Open a terminal in the skill folder and run: {SETUP_COMMAND}")
    print(__doc__.split("\n")[0])
    print(f"""
This script searches HubSpot directly with a private app token. The token
stays on this device, in {TOKEN_FILE} (readable only by you). It is never
sent anywhere except HubSpot, and never shown in the chat.

1. In HubSpot, open Settings and find Private Apps (under Integrations; in
   newer portals it can sit under Development). Create a private app, or open
   the one your team already uses.
2. Give it these read-only scopes: {", ".join(SCOPES)}
3. Copy its access token.
""")
    if input("Authorize this script to read your HubSpot companies and contacts with that "
             "private app? [y/N] ").strip().lower() not in ("y", "yes"):
        raise SystemExit("Not authorized; nothing saved. Step 3 will fall back to the HubSpot connector.")
    token = getpass.getpass("Paste the access token (input is hidden): ").strip()
    if not token:
        raise SystemExit("No token entered; nothing saved.")
    save_token(token)


def run_plan(args):
    searches = json.loads(Path(args.plan).read_text())
    out = Path(args.raw_dir)
    out.mkdir(parents=True, exist_ok=True)
    portal = api("GET", "/account-info/v3/details").get("portalId")
    total = 0
    for i, spec in enumerate(searches):
        obj = spec["objectType"]
        template = f"https://app.hubspot.com/contacts/{portal}/record/{OBJECT_TYPE_IDS[obj]}/{{id}}"
        groups = spec.get("filterGroups") or []
        assoc = groups[0].get("associatedWith") if groups else None
        if assoc:
            results = associated_records(assoc[0], spec["properties"])
        else:
            body = {"limit": min(spec.get("limit", 100), 200), "properties": spec["properties"]}
            if groups:
                body["filterGroups"] = groups
            if spec.get("query"):
                body["query"] = spec["query"]
            results, after = [], None
            while True:
                if after:
                    body["after"] = after
                resp = api("POST", f"/crm/v3/objects/{OBJECT_PATHS[obj]}/search", body)
                results += resp.get("results", [])
                after = (resp.get("paging") or {}).get("next", {}).get("after")
                # Free-text name searches only need the first page.
                if not after or spec.get("query"):
                    break
                time.sleep(0.25)
        recs = [{"id": r["id"], "properties": r.get("properties", {})} for r in results]
        (out / f"{i:03d}.json").write_text(json.dumps({"results": recs, "total": len(recs),
                                                        "urlTemplate": template}))
        total += len(recs)
        time.sleep(0.25)  # stay under the search API's per-second limit
    print(f"ran {len(searches)} searches, {total} records -> {out}")


def associated_records(assoc, properties):
    """Contacts associated with any of the given companies (REST search can't filter on this)."""
    ids = []
    for company_id in assoc["objectIdValues"]:
        after = None
        while True:
            path = f"/crm/v4/objects/companies/{company_id}/associations/contacts?limit=500"
            resp = api("GET", path + (f"&after={after}" if after else ""))
            ids += [str(r["toObjectId"]) for r in resp.get("results", [])]
            after = (resp.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break
    results, unique = [], sorted(set(ids))
    for k in range(0, len(unique), 100):
        resp = api("POST", "/crm/v3/objects/contacts/batch/read",
                   {"properties": properties, "inputs": [{"id": x} for x in unique[k:k + 100]]})
        results += resp.get("results", [])
    return results


# ---------------------------------------------------------------- connector mode

def parse_connector_tsv(text):
    """Rows from a query_crm_data "Dataset TSV" block, keyed by internal name.

    Headers look like "First Name [firstname]". When the same internal name
    appears twice (a cross-object SELECT: "Contact [hs_object_id]" and
    "Company [hs_object_id]"), the key is prefixed with the label's first word,
    lowercased: "contact.hs_object_id", "company.hs_object_id".
    """
    block = text.split("Dataset TSV:", 1)[-1].strip().split("\n\nShowing")[0]
    lines = [l for l in block.splitlines() if l.strip()]
    if not lines:
        return []
    headers = lines[0].split("\t")
    names = [re.search(r"\[([^\]]+)\]", h).group(1) if "[" in h else h.strip() for h in headers]
    keys = []
    for h, n in zip(headers, names):
        keys.append(f"{h.split()[0].lower()}.{n}" if names.count(n) > 1 else n)
    rows = []
    for line in lines[1:]:
        vals = line.split("\t")
        rows.append({k: (v if v != "Unassigned" else "") for k, v in zip(keys, vals + [""] * (len(keys) - len(vals)))})
    return rows


def read_connector_result(path):
    """Any saved connector result -> list of {"id", "properties"} records, plus urlTemplate."""
    text = Path(path).read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    records, template = [], ""
    if isinstance(data, dict) and "results" in data and data["results"] and "content" in data["results"][0]:
        # query_crm_data wrapper: JSON rows or a TSV dataset inside "content".
        for r in data["results"]:
            content = r["content"]
            if "Dataset TSV:" in content:
                for row in parse_connector_tsv(content):
                    rid = row.get("hs_object_id") or row.get("contact.hs_object_id") or row.get("company.hs_object_id")
                    records.append({"id": rid, "properties": row})
            else:
                props = json.loads(content).get("properties", {})
                records.append({"id": props.get("hs_object_id"), "properties": props})
    elif isinstance(data, dict):
        template = data.get("urlTemplate", "")
        for r in data.get("results", data.get("objects", [])):
            records.append({"id": str(r.get("id")), "properties": r.get("properties", {})})
    elif "Dataset TSV:" in text:
        for row in parse_connector_tsv(text):
            records.append({"id": row.get("hs_object_id"), "properties": row})
    else:
        raise SystemExit(f"{path}: not a recognised connector result")
    return records, template


def ingest(args):
    records, template = read_connector_result(args.response)
    out = Path(args.raw_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or f"{len(list(out.glob('*.json'))):03d}"
    (out / f"{name}.json").write_text(json.dumps({"results": records, "total": len(records),
                                                  "urlTemplate": template or args.url_template or ""}))
    print(f"{len(records)} records -> {out / (name + '.json')}")


# ---------------------------------------------------------------- companies

def working_companies(run_dir):
    """One row per company from working.csv (company fields agree across its rows)."""
    _, rows = ws.load(run_dir)
    seen = {}
    for r in rows:
        seen.setdefault(r[COMPANY_ID], r)
    return list(seen.values())


def company_domains(row):
    extra = [d.strip() for d in (row.get("Additional Domains") or "").split(";")]
    return [d for d in [row.get("Company Domain", "").strip()] + extra if d]


def plan_companies(args):
    companies = working_companies(args.run_dir)
    domains, websites, zi_ids, linkedin = [], [], [], []
    for c in companies:
        domains += company_domains(c)
        site = norm_domain(c.get("Website"))
        if site:
            websites += [site, "www." + site]
        zi_ids.append(c.get(COMPANY_ID, ""))
        slug = linkedin_slug(c.get("LinkedIn Company Profile URL"), "company")
        if slug:
            linkedin += [f"{p}www.linkedin.com/company/{slug}{t}" for p in ("http://", "https://") for t in ("", "/")]
    searches = (in_searches("COMPANY", "domain", domains, COMPANY_PROPERTIES)
                + in_searches("COMPANY", "website", websites, COMPANY_PROPERTIES)
                + in_searches("COMPANY", "zoominfo_company_id", zi_ids, COMPANY_PROPERTIES)
                + in_searches("COMPANY", "linkedin_company_page", linkedin, COMPANY_PROPERTIES))
    # Free-text name search per company catches duplicates filed under another domain.
    for c in companies:
        query = norm_company_name(c["Company Name"]) or c["Company Name"]
        searches.append({"objectType": "COMPANY", "query": query[:200], "properties": COMPANY_PROPERTIES,
                         "limit": 20, "for": c[COMPANY_ID]})
    write_plan(args.run_dir, "company_search_plan.json", searches)


def write_plan(out_dir, name, searches):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(searches, indent=2))
    print(f"{len(searches)} HubSpot searches -> {out / name}")


def match_companies(args):
    companies = working_companies(args.run_dir)
    records, template = load_records(args.raw_dir)
    matches = []
    for c in companies:
        domains = {d.lower() for d in company_domains(c)}
        site = norm_domain(c.get("Website"))
        li = linkedin_slug(c.get("LinkedIn Company Profile URL"), "company")
        cands = []
        for rid, p in records.items():
            reasons = []
            if norm_domain(p.get("domain")) in domains:
                reasons.append(f"domain {norm_domain(p.get('domain'))}")
            if site and norm_domain(p.get("website")) == site:
                reasons.append("same website")
            elif norm_domain(p.get("website")) in domains:
                reasons.append(f"website on {norm_domain(p.get('website'))}")
            if p.get("zoominfo_company_id") and str(p["zoominfo_company_id"]).split(".")[0] == c[COMPANY_ID]:
                reasons.append("same ZoomInfo Company ID")
            if li and linkedin_slug(p.get("linkedin_company_page"), "company") == li:
                reasons.append("same LinkedIn company page")
            sim = name_similarity(c["Company Name"], p.get("name"))
            place = same_location(c, p, (("Company City", "city"), ("Company State", "state"),
                                         ("Company Country", "country")))
            if sim >= 0.85:
                reasons.append(f"similar name ({p.get('name')})" + (f", same {place}" if place else ""))
            elif sim >= 0.7 and place.count("/") >= 1:
                reasons.append(f"partly similar name ({p.get('name')}) in same {place}")
            if not reasons:
                continue
            strong = any(r.startswith(("domain", "same website", "website on", "same ZoomInfo", "same LinkedIn")) for r in reasons)
            cands.append({"record_id": rid, "url": record_url(template, rid), "strength": "strong" if strong else "possible",
                          "reasons": reasons, "name": p.get("name"), "domain": p.get("domain"),
                          "website": p.get("website"), "location": ", ".join(x for x in (p.get("city"), p.get("state"), p.get("country")) if x) or p.get("location") or "",
                          "employees": p.get("numberofemployees"), "revenue": p.get("annualrevenue"),
                          "contacts": p.get("num_associated_contacts"), "type": p.get("type"),
                          "created": (p.get("createdate") or "")[:10]})
        cands.sort(key=lambda x: (x["strength"] != "strong", -len(x["reasons"])))
        matches.append({COMPANY_ID: c[COMPANY_ID], "company": c["Company Name"], "company_domain": c.get("Company Domain"),
                        "additional_domains": c.get("Additional Domains"), "website": c.get("Website"),
                        "location": ", ".join(x for x in (c.get("Company City"), c.get("Company State"), c.get("Company Country")) if x),
                        "employees": c.get("Employees"), "revenue": c.get("Revenue (in USD)"), "candidates": cands})
    write_matches(args.run_dir, "company_matches.json", matches)


def write_matches(out_dir, name, matches):
    out = Path(out_dir)
    (out / name).write_text(json.dumps(matches, indent=2))
    none = sum(1 for m in matches if not m["candidates"])
    single = sum(1 for m in matches if len(m["candidates"]) == 1 and m["candidates"][0]["strength"] == "strong")
    review = len(matches) - none - single
    print(f"{len(matches)} records: {none} not in HubSpot, {single} single strong match, "
          f"{review} need review (several candidates or only possible matches) -> {out / name}")


def apply_companies(args):
    fields, rows = ws.load(args.run_dir)
    decisions = json.loads(Path(args.decisions).read_text())
    ids = {r[COMPANY_ID] for r in rows}
    missing = sorted(ids - set(decisions))
    if missing:
        raise SystemExit(f"company_decisions.json has no decision for: {missing}")
    for cid in ids:
        ws.set_company_field(rows, cid, COMPANY_RECORD, decisions[cid].get("record_id") or NOT_IN_HUBSPOT)
    ws.save(args.run_dir, fields, rows)
    ws.log(args.run_dir, {"action": "step3_companies", "decisions": decisions})
    found = sum(1 for cid in ids if decisions[cid].get("record_id"))
    print(f"working.csv: HubSpot Company Record ID set — {found} companies in HubSpot, {len(ids) - found} not")


# ---------------------------------------------------------------- contacts

def first_name_forms(first):
    f = letters(first)
    forms = {f}
    for full, nicks in NICKNAMES.items():
        if f == full or f in nicks:
            forms |= {full} | nicks
    return forms


def plan_contacts(args):
    _, contacts = ws.load(args.run_dir)
    companies = working_companies(args.run_dir)
    urls, emails, last_names = [], [], []
    for r in contacts:
        slug = linkedin_slug(r.get("LinkedIn Contact Profile URL"), "in")
        if slug:
            urls += [f"{p}{slug}{t}" for p in ("https://www.linkedin.com/in/", "http://www.linkedin.com/in/",
                                               "https://linkedin.com/in/") for t in ("", "/")]
        if r.get("Email Address"):
            emails.append(r["Email Address"].lower())
        if r.get("Last Name"):
            last_names.append(r["Last Name"])
    searches = (in_searches("CONTACT", HUBSPOT_LINKEDIN, urls, CONTACT_PROPERTIES)
                + in_searches("CONTACT", "email", emails, CONTACT_PROPERTIES)
                + in_searches("CONTACT", "lastname", last_names, CONTACT_PROPERTIES))
    # Everyone already at the list's companies: catches short names and
    # same-title, different-name records.
    record_ids = [c[COMPANY_RECORD] for c in companies if c.get(COMPANY_RECORD) not in ("", None, NOT_IN_HUBSPOT)]
    for chunk in chunks(record_ids):
        searches.append({"objectType": "CONTACT", "properties": CONTACT_PROPERTIES, "limit": 200,
                         "filterGroups": [{"associatedWith": [{"objectType": "companies", "operator": "IN",
                                                               "objectIdValues": [int(i) for i in chunk]}]}],
                         "note": "page through with offset until all results are saved"})
    write_plan(args.run_dir, "contact_search_plan.json", searches)


def match_contacts(args):
    _, contacts = ws.load(args.run_dir)
    company_of = {r[CONTACT_ID]: r[COMPANY_ID] for r in contacts}
    record_of = {r[COMPANY_ID]: r.get(COMPANY_RECORD) for r in contacts}
    records, template = load_records(args.raw_dir)
    matches = []
    for r in contacts:
        slug = linkedin_slug(r.get("LinkedIn Contact Profile URL"), "in")
        email = (r.get("Email Address") or "").lower()
        first, last = letters(r["First Name"]), letters(r["Last Name"])
        forms = first_name_forms(r["First Name"])
        company_record = record_of.get(company_of.get(r[CONTACT_ID]))
        title = (r.get("Job Title") or "").strip().lower()
        cands = []
        for rid, p in records.items():
            reasons = []
            if slug and linkedin_slug(p.get(HUBSPOT_LINKEDIN), "in") == slug:
                reasons.append("same LinkedIn URL")
            if email and (p.get("email") or "").lower() == email:
                reasons.append("same email")
            pf, pl = letters(p.get("firstname")), letters(p.get("lastname"))
            same_company = company_record and str(p.get("associatedcompanyid") or "") == str(company_record)
            if pl == last and pf == first:
                where = [x for x, h in (("state", "Person State"), ("country", "Country"))
                         if r.get(h) and (p.get(x) or "").lower() == r[h].lower()]
                reasons.append("same name" + (", same " + "/".join(where) if where else "")
                               + (", same company" if same_company else ""))
            elif pl == last and (pf in forms or (pf and first and pf[0] == first[0] and same_company)):
                reasons.append(f"short/alternate first name ({p.get('firstname')} {p.get('lastname')})"
                               + (", same company" if same_company else ""))
            if same_company and title and (p.get("jobtitle") or "").strip().lower() == title and pl != last:
                reasons.append(f"same job title at same company, different name ({p.get('firstname')} {p.get('lastname')})")
            if not reasons:
                continue
            strong = any(x.startswith(("same LinkedIn", "same email")) for x in reasons)
            # Same person, but HubSpot has them at another company? That decides
            # whether the list row (and maybe its company) belongs in the upload,
            # so it goes to the user instead of counting as a clean match.
            mismatch = None
            hs_company = str(p.get("associatedcompanyid") or "")
            has_record = company_record and company_record != NOT_IN_HUBSPOT
            if strong and hs_company and has_record and hs_company != str(company_record):
                mismatch = "HubSpot's primary company for this contact is a different record"
            elif strong and p.get("company") and (not hs_company or not has_record) \
                    and name_similarity(r["Company Name"], p.get("company")) < 0.85:
                mismatch = f"HubSpot has them at {p.get('company')!r}, the list at {r['Company Name']!r}"
            cands.append({"record_id": rid, "url": record_url(template, rid),
                          "strength": "review" if mismatch else ("strong" if strong else "possible"),
                          "company_mismatch": mismatch, "hubspot_company_id": hs_company or None,
                          "hubspot_company_url": record_url(template.replace("0-1", "0-2"), hs_company) if hs_company and template else None,
                          "list_company": r["Company Name"], "list_job_title": r.get("Job Title"),
                          "reasons": reasons, "name": f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip(),
                          "email": p.get("email"), "job_title": p.get("jobtitle"), "company": p.get("company"),
                          "location": ", ".join(x for x in (p.get("city"), p.get("state"), p.get("country")) if x),
                          "linkedin": p.get(HUBSPOT_LINKEDIN), "created": (p.get("createdate") or "")[:10]})
        cands.sort(key=lambda x: (x["strength"] != "strong", -len(x["reasons"])))
        matches.append({CONTACT_ID: r[CONTACT_ID], "name": f"{r['First Name']} {r['Last Name']}",
                        "company": r["Company Name"], "job_title": r.get("Job Title"), "email": r.get("Email Address"),
                        "linkedin": r.get("LinkedIn Contact Profile URL"),
                        "location": ", ".join(x for x in (r.get("Person City"), r.get("Person State"), r.get("Country")) if x),
                        "candidates": cands})
    write_matches(args.run_dir, "contact_matches.json", matches)


def apply_contacts(args):
    """contact_decisions.json: {"<ZoomInfo Contact ID>": {"record_id": "..." | null,
    "flag": "<reason>" (optional: the row needs the user's review, e.g. HubSpot has
    this person at another company)}}. Rows are flagged, never dropped."""
    fields, contacts = ws.load(args.run_dir)
    decisions = json.loads(Path(args.decisions).read_text())
    missing = [r[CONTACT_ID] for r in contacts if r[CONTACT_ID] not in decisions]
    if missing:
        raise SystemExit(f"contact_decisions.json has no decision for: {missing}")
    flagged = 0
    for r in contacts:
        d = decisions[r[CONTACT_ID]]
        r[CONTACT_RECORD] = d.get("record_id") or NOT_IN_HUBSPOT
        if d.get("flag"):
            r[ws.FLAG], r[ws.FLAG_REASON] = "REVIEW", d["flag"]
            flagged += 1
    ws.save(args.run_dir, fields, contacts)
    ws.log(args.run_dir, {"action": "step3_contacts", "flagged": flagged})
    ws.snapshot_copy(args.run_dir, "03_hubspot_duplicates")
    found = sum(1 for r in contacts if r[CONTACT_RECORD] != NOT_IN_HUBSPOT)
    print(f"working.csv: HubSpot Contact Record ID set — {found} in HubSpot, {len(contacts) - found} not; "
          f"{flagged} rows flagged for review")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, func, *opts):
        p = sub.add_parser(name)
        for o in opts:
            p.add_argument(f"--{o}", required=True)
        p.set_defaults(func=func)

    st = sub.add_parser("setup-token")
    st.add_argument("--open-terminal", action="store_true")
    st.add_argument("--from-file")
    st.add_argument("--authorized", action="store_true")
    st.set_defaults(func=setup_token)
    ing = sub.add_parser("ingest")
    ing.add_argument("--response", required=True, help="saved connector result (file)")
    ing.add_argument("--raw-dir", required=True)
    ing.add_argument("--name", help="file name in raw-dir (default: next number)")
    ing.add_argument("--url-template", help="record link template if the result has none")
    ing.set_defaults(func=ingest)
    add("check-token", check_token)
    add("run-plan", run_plan, "plan", "raw-dir")
    add("plan-companies", plan_companies, "run-dir")
    add("match-companies", match_companies, "run-dir", "raw-dir")
    add("apply-companies", apply_companies, "run-dir", "decisions")
    add("plan-contacts", plan_contacts, "run-dir")
    add("match-contacts", match_contacts, "run-dir", "raw-dir")
    add("apply-contacts", apply_contacts, "run-dir", "decisions")
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
