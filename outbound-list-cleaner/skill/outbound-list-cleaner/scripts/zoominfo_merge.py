"""LinkedIn lists, stages 7–10: ZoomInfo pull, source priority, consistency, prune.

Runs on working.csv after steps 1–2. ZoomInfo data is only ever added in
"ZI …" columns first; nothing in the list's own columns changes until `merge`.

  plan         Writes zi/plan.json: contact batches (10 per ZoomInfo call) and
               company batches (10 per call), plus the MAXIMUM credits (one per
               contact + one per company; anyone enriched in the last year is
               free, but that can't be known in advance). Tell the user the
               maximum and get their OK before any call. Re-running shows which
               batches are still to do (resumable).
  ingest       --kind contacts|companies --batch <n> --response <file>: saves one
               ZoomInfo result (enrich_contacts / enrich_companies, as returned)
               for that batch.
  attach       Adds the ZI columns to working.csv and judges each contact match:
               good (same person, same company) / outdated (same person, other
               company — the whole ZoomInfo record is then distrusted) / review /
               none.
  merge        Applies the source rules (below) to the list's own columns;
               ties are flagged for the user. Writes merge_report.json.
  consistency  Three levels: within each contact, across a company's contacts,
               contacts vs company data. Problems -> consistency_report.json;
               anything needing a tiebreak is flagged.
  prune        Removes the ZI and helper columns (a copy of them is kept in
               zi/zi_columns.csv) and lists every column removed.
  diff-review  --old <json> --new <json>: entries in a step's review file that
               are new since the first pass (for the second run of steps 1–2).

Source rules (agreed with the user):
  first/last name ......... ZoomInfo (LinkedIn often shortens the surname)
  job title ............... LinkedIn (more current; the company was confirmed in
                            the multiple-jobs step)
  contact LinkedIn URL .... LinkedIn (format only; ZoomInfo fills a blank)
  email ................... every email whose domain is the company's (LinkedIn's
                            and ZoomInfo's); others cleared; with two, the one on
                            the domain most of the company's contacts use is the
                            primary, the other goes in Additional Emails
  person city/state/country ZoomInfo when it has them, else the LinkedIn values
  website ................. ZoomInfo, else LinkedIn; then cleaned (no shorteners,
                            Linktree, careers pages, subpages)
  company name ............ ZoomInfo's when its company is the LinkedIn company
                            (cleaner); otherwise LinkedIn's
  company LinkedIn URL .... LinkedIn (format only; ZoomInfo fills a blank)
  company location, phone,
  industry, size, revenue . ZoomInfo when present
  management level, job
  function, phones ........ ZoomInfo
A contact whose ZoomInfo match is "outdated" or "none" keeps all its LinkedIn
values.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet as ws  # noqa: E402
from normalize import clean_website  # noqa: E402

CONTACT_ID, COMPANY_ID = ws.CONTACT_ID, ws.COMPANY_ID
BATCH = 10
CONTACT_FIELDS = ["firstName", "lastName", "email", "jobTitle", "companyName", "zoominfoCompanyId", "externalUrls",
                  "managementLevel", "jobFunction", "phone", "mobilePhone", "contactAccuracyScore",
                  "lastUpdatedDate"]
COMPANY_FIELDS_ZI = ["name", "website", "domainList", "street", "city", "state", "zipCode", "country", "phone",
                     "employeeCount", "employeeRange", "revenue", "revenueRange", "primaryIndustry",
                     "socialMediaUrls", "foundedYear"]
ZI_CONTACT_COLS = ["ZI Match", "ZI Match Note", "ZI First Name", "ZI Last Name", "ZI Email", "ZI Job Title",
                   "ZI Company Name", "ZI Company ID", "ZI LinkedIn URL", "ZI Management Level", "ZI Job Function",
                   "ZI Direct Phone", "ZI Mobile Phone", "ZI Accuracy Score", "ZI Person City", "ZI Person State",
                   "ZI Person Country"]
ZI_COMPANY_COLS = ["ZI Co Name", "ZI Co Website", "ZI Co Domains", "ZI Co Street", "ZI Co City", "ZI Co State",
                   "ZI Co Zip", "ZI Co Country", "ZI Co Phone", "ZI Co Employees", "ZI Co Employee Range",
                   "ZI Co Revenue", "ZI Co Revenue Range", "ZI Co Industry", "ZI Co LinkedIn", "ZI Co Founded"]
HELPER_COLS = ["LinkedIn Headline", "Jobs Check", "Source List Type"]
SUFFIX = re.compile(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|companies|group|holdings|"
                    r"the|plc|lp|llp)\b\.?", re.I)


# ---------- helpers ----------
def zi_dir(run):
    d = Path(run) / "zi"
    d.mkdir(exist_ok=True)
    return d


def company_domains(r):
    ds = {r.get("Company Domain", "").strip().lower()}
    ds |= {d.strip().lower() for d in (r.get("Additional Domains") or "").split(";")}
    return {d for d in ds if d}


EMAIL_OK = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}$", re.I)


def email_pattern(email, first, last):
    """Local-part format relative to the name: first.last / flast / first / firstl / first_last / other."""
    loc = email.split("@")[0].lower()
    f, l = re.sub(r"[^a-z]", "", (first or "").lower()), re.sub(r"[^a-z]", "", (last or "").lower())
    if not f or not l:
        return "other"
    for name, val in (("first.last", f"{f}.{l}"), ("first_last", f"{f}_{l}"), ("flast", f"{f[0]}{l}"),
                      ("firstl", f"{f}{l[0]}"), ("first", f), ("firstlast", f"{f}{l}"), ("last", l)):
        if loc == val:
            return name
    return "other"


def email_domain(e):
    return e.split("@")[-1].strip().lower() if e and "@" in e else ""


def norm_company(name):
    n = SUFFIX.sub(" ", (name or "").lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def same_company(a, b):
    na, nb = norm_company(a), norm_company(b)
    if not na or not nb:
        return False
    if na == nb or na.replace(" ", "") == nb.replace(" ", ""):
        return True
    ta, tb = set(na.split()), set(nb.split())
    return bool(ta and tb) and (ta <= tb or tb <= ta) and len(ta & tb) >= 1 and min(len(ta), len(tb)) >= 1 \
        and len(ta & tb) / max(len(ta), len(tb)) >= 0.5


def li_slug(url):
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", url or "", re.I)
    return m.group(1).lower().rstrip("/") if m else ""


def clean_li(url, kind="in"):
    m = re.search(rf"linkedin\.com/({kind})/([^/?#\s]+)", url or "", re.I)
    return f"https://www.linkedin.com/{kind}/{m.group(2).rstrip('/')}" if m else (url or "").strip()


SKIP_KEYS = {"input", "inputCriteria", "retryInfo", "warnings"}


def walk_records(obj, keys):
    """Every dict in a ZoomInfo response that has any of `keys` (the response shape varies).
    The echoed request ("input", "inputCriteria") is never a record."""
    out = []
    if isinstance(obj, dict):
        if any(k in obj for k in keys):
            out.append(obj)
        for k, v in obj.items():
            if k not in SKIP_KEYS:
                out += walk_records(v, keys)
    elif isinstance(obj, list):
        for v in obj:
            out += walk_records(v, keys)
    return out


def first_val(d, *names):
    for n in names:
        v = d.get(n)
        if isinstance(v, dict):
            v = v.get("name") or v.get("value") or ""
        if isinstance(v, list):
            v = "; ".join(str(x.get("url", x) if isinstance(x, dict) else x) for x in v)
        if v not in (None, ""):
            return str(v)
    return ""


# ---------- plan / ingest ----------
def plan(args):
    _, rows = ws.load(args.run_dir)
    d = zi_dir(args.run_dir)
    contacts, companies, seen = [], [], {}
    for r in rows:
        q = {"firstName": r.get("First Name", ""), "lastName": r.get("Last Name", ""),
             "companyName": r.get("Company Name", "")}
        if r.get("Email Address"):
            q["email"] = r["Email Address"]
        if r.get("LinkedIn Contact Profile URL"):
            q["externalURL"] = r["LinkedIn Contact Profile URL"]
        contacts.append({"row": r[CONTACT_ID], "query": q})
        if r[COMPANY_ID] not in seen:
            seen[r[COMPANY_ID]] = True
            cq = {"companyName": r.get("Company Name", "")}
            dom = r.get("Company Domain") or email_domain(r.get("Email Address", ""))
            if dom:
                cq["domain"] = dom
            companies.append({"company": r[COMPANY_ID], "query": cq})
    chunk = lambda xs: [xs[i:i + BATCH] for i in range(0, len(xs), BATCH)]
    p = {"contact_batches": chunk(contacts), "company_batches": chunk(companies),
         "contact_required_fields": CONTACT_FIELDS, "company_required_fields": COMPANY_FIELDS_ZI,
         "max_credits": len(contacts) + len(companies)}
    (d / "plan.json").write_text(json.dumps(p, indent=1, ensure_ascii=False))
    done = lambda kind, n: (d / f"{kind}_{n}.json").exists()
    todo_c = [i for i in range(len(p["contact_batches"])) if not done("contacts", i)]
    todo_k = [i for i in range(len(p["company_batches"])) if not done("companies", i)]
    print(f"ZoomInfo plan: {len(contacts)} contacts in {len(p['contact_batches'])} calls, {len(companies)} companies "
          f"in {len(p['company_batches'])} calls.")
    print(f"MAXIMUM credits: {p['max_credits']} ({len(contacts)} contacts + {len(companies)} companies; anyone "
          f"enriched in the last year is free, so the real number can be lower). Get the user's OK first.")
    print(f"still to run: contact batches {todo_c or 'none'}; company batches {todo_k or 'none'}")


def ingest(args):
    d = zi_dir(args.run_dir)
    data = json.loads(Path(args.response).read_text())
    (d / f"{args.kind}_{args.batch}.json").write_text(json.dumps(data, ensure_ascii=False))
    keys = ("firstName", "lastName") if args.kind == "contacts" else ("name", "website", "domainList")
    print(f"saved {args.kind} batch {args.batch}: {len(walk_records(data, keys))} records")


# ---------- attach ----------
def name_ok(first, last, zf, zl):
    f, l, zf, zl = (x.strip().lower().strip(".") for x in (first, last, zf, zl))
    if not zl:
        return "no"
    last_ok = l == zl or (len(l) == 1 and zl.startswith(l)) or l.replace("-", " ").split()[-1:] == zl.split()[-1:]
    first_ok = f == zf or f[:3] == zf[:3] or (len(f) == 1 and zf.startswith(f)) or not f
    return "yes" if last_ok and first_ok else ("partly" if last_ok or (first_ok and f) else "no")


def paired_records(data):
    """enrich_contacts returns {"contact_1": {"input": {...}, "data": {...}}, ...}: pair each
    answer with the request it answers (exact), instead of guessing by name."""
    pairs = []
    if isinstance(data, dict):
        for k, v in data.items():
            if re.match(r"(contact|company)_\d+$", k) and isinstance(v, dict) and isinstance(v.get("input"), dict):
                pairs.append((v["input"], v.get("data") if v.get("success", True) else None))
    return pairs


def same_query(a, b):
    keys = ("email", "firstName", "lastName", "companyName", "externalURL", "domain")
    return all((a.get(k) or "").lower() == (b.get(k) or "").lower() for k in keys if a.get(k) or b.get(k))


def best_contact(q, recs):
    best, score = None, -1
    for z in recs:
        s = 0
        if q.get("externalURL") and li_slug(q["externalURL"]) and li_slug(q["externalURL"]) in first_val(z, "externalUrls").lower():
            s += 3
        s += {"yes": 2, "partly": 1, "no": 0}[name_ok(q.get("firstName", ""), q.get("lastName", ""),
                                                     first_val(z, "firstName"), first_val(z, "lastName"))]
        if q.get("email") and q["email"].lower() == first_val(z, "email").lower():
            s += 3
        if s > score:
            best, score = z, s
    return best if score > 0 else None


def attach(args):
    run = Path(args.run_dir)
    fields, rows = ws.load(run)
    d = zi_dir(run)
    p = json.loads((d / "plan.json").read_text())
    by_row = {r[CONTACT_ID]: r for r in rows}
    for col in ZI_CONTACT_COLS + ZI_COMPANY_COLS:
        if col not in fields:
            fields.append(col)
    missing = []
    for i, batch in enumerate(p["contact_batches"]):
        f = d / f"contacts_{i}.json"
        if not f.exists():
            missing.append(f"contacts {i}")
            continue
        data = json.loads(f.read_text())
        pairs, recs = paired_records(data), walk_records(data, ("firstName", "lastName"))
        for item in batch:
            r, q = by_row[item["row"]], item["query"]
            if pairs:
                hit = [d for inp, d in pairs if same_query(inp, q)]
                if not hit:
                    continue  # this contact wasn't in the call (e.g. a partial test batch)
                z = hit[0] if hit[0] and hit[0].get("success", True) is not False else None
            else:
                z = best_contact(q, recs)
            if not z:
                r["ZI Match"], r["ZI Match Note"] = "none", "not found in ZoomInfo"
                continue
            vals = {"ZI First Name": first_val(z, "firstName"), "ZI Last Name": first_val(z, "lastName"),
                    "ZI Email": first_val(z, "email"), "ZI Job Title": first_val(z, "jobTitle"),
                    "ZI Company Name": first_val(z, "companyName"),
                    "ZI Company ID": first_val(z, "zoominfoCompanyId", "companyId"),
                    "ZI LinkedIn URL": next((u for u in first_val(z, "externalUrls").split("; ")
                                             if "linkedin.com/in/" in u.lower()), ""),
                    "ZI Management Level": first_val(z, "managementLevel"),
                    "ZI Job Function": first_val(z, "jobFunction"), # a number marked Do Not Call is never copied
                    "ZI Direct Phone": "" if z.get("directPhoneDoNotCall") is True else first_val(z, "phone"),
                    "ZI Mobile Phone": "" if z.get("mobilePhoneDoNotCall") is True else first_val(z, "mobilePhone"),
                    "ZI Accuracy Score": first_val(z, "contactAccuracyScore"),
                    "ZI Person City": first_val(z, "city", "personCity"),
                    "ZI Person State": first_val(z, "state", "personState"),
                    "ZI Person Country": first_val(z, "country", "personCountry")}
            r.update(vals)
            nm = name_ok(r.get("First Name", ""), r.get("Last Name", ""), vals["ZI First Name"], vals["ZI Last Name"])
            co = same_company(r.get("Company Name", ""), vals["ZI Company Name"]) or \
                (email_domain(vals["ZI Email"]) in company_domains(r) and email_domain(vals["ZI Email"]) != "")
            if nm == "yes" and co:
                r["ZI Match"], r["ZI Match Note"] = "good", ""
            elif nm == "yes":
                r["ZI Match"], r["ZI Match Note"] = "outdated", (f"ZoomInfo has them at {vals['ZI Company Name']} — "
                                                                 "ZoomInfo record not used")
            else:
                r["ZI Match"], r["ZI Match Note"] = "review", (f"name differs: {vals['ZI First Name']} "
                                                               f"{vals['ZI Last Name']} @ {vals['ZI Company Name']}")
    company_vals = {}
    for i, batch in enumerate(p["company_batches"]):
        f = d / f"companies_{i}.json"
        if not f.exists():
            missing.append(f"companies {i}")
            continue
        recs = walk_records(json.loads(f.read_text()), ("name", "website", "domainList"))
        for item in batch:
            q = item["query"]
            z = next((x for x in recs if q.get("domain") and q["domain"].lower() in
                      (first_val(x, "domainList") + " " + first_val(x, "website")).lower()), None) or \
                next((x for x in recs if same_company(q.get("companyName", ""), first_val(x, "name"))), None)
            if not z:
                continue
            company_vals[item["company"]] = {
                "ZI Co Name": first_val(z, "name"), "ZI Co Website": first_val(z, "website"),
                "ZI Co Domains": first_val(z, "domainList"), "ZI Co Street": first_val(z, "street"),
                "ZI Co City": first_val(z, "city"), "ZI Co State": first_val(z, "state"),
                "ZI Co Zip": first_val(z, "zipCode"), "ZI Co Country": first_val(z, "country"),
                "ZI Co Phone": first_val(z, "phone"), "ZI Co Employees": first_val(z, "employeeCount"),
                "ZI Co Employee Range": first_val(z, "employeeRange"), "ZI Co Revenue": first_val(z, "revenue"),
                "ZI Co Revenue Range": first_val(z, "revenueRange"),
                "ZI Co Industry": first_val(z, "primaryIndustry"),
                "ZI Co LinkedIn": next((u for u in first_val(z, "socialMediaUrls").split("; ")
                                        if "linkedin.com/company" in u.lower()), ""),
                "ZI Co Founded": first_val(z, "foundedYear")}
    for r in rows:
        r.update(company_vals.get(r[COMPANY_ID], {}))
    ws.save(run, fields, rows)
    ws.log(run, {"action": "zoominfo_attach", "contacts": Counter(r.get("ZI Match", "") for r in rows),
                 "companies_matched": len(company_vals)})
    ws.snapshot_copy(run, "05_zoominfo")
    c = Counter(r.get("ZI Match") or "not run" for r in rows)
    print(f"ZI columns added: contacts {dict(c)}; companies matched {len(company_vals)}"
          + (f"; MISSING batches: {', '.join(missing)}" if missing else ""))
    print("Show the user the 'review' and 'outdated' contacts (name, company, ZoomInfo's version) before merge.")


# ---------- merge ----------
def flag(r, reason):
    r["Flag"] = "yes"
    r["Flag Reason"] = (r.get("Flag Reason", "") + "; " if r.get("Flag Reason") else "") + reason


def merge(args):
    run = Path(args.run_dir)
    fields, rows = ws.load(run)
    for col in ("Additional Emails", "Management Level", "Job Function", "Direct Phone Number", "Mobile phone",
                "Company HQ Phone", "Company Street Address", "Flag", "Flag Reason"):
        if col not in fields:
            fields.append(col)
    changes, ties = [], []

    def put(r, col, new, why):
        new = (new or "").strip()
        if new and new != (r.get(col) or "").strip():
            changes.append({"row": r[CONTACT_ID], "contact": f"{r.get('First Name', '')} {r.get('Last Name', '')}",
                            "company": r.get("Company Name", ""), "field": col, "from": r.get(col, ""),
                            "to": new, "why": why})
            r[col] = new

    # domain and address-format usage across each company's contacts (both sources), for the primary email
    usage, patterns = defaultdict(Counter), defaultdict(Counter)
    for r in rows:
        for e in (r.get("Email Address"), r.get("ZI Email") if r.get("ZI Match") == "good" else ""):
            if e and EMAIL_OK.match(e.strip()) and email_domain(e) in company_domains(r):
                usage[r[COMPANY_ID]][email_domain(e)] += 1
                patterns[r[COMPANY_ID]][email_pattern(e, r.get("ZI First Name") or r.get("First Name"),
                                                      r.get("ZI Last Name") or r.get("Last Name"))] += 1

    for r in rows:
        good = r.get("ZI Match") == "good"
        if good:
            put(r, "First Name", r.get("ZI First Name"), "ZoomInfo name")
            put(r, "Last Name", r.get("ZI Last Name"), "ZoomInfo name")
            if r.get("ZI Person City") or r.get("ZI Person State") or r.get("ZI Person Country"):
                put(r, "Person City", r.get("ZI Person City"), "ZoomInfo location")
                put(r, "Person State", r.get("ZI Person State"), "ZoomInfo location")
                put(r, "Country", r.get("ZI Person Country"), "ZoomInfo location")
            put(r, "Management Level", r.get("ZI Management Level"), "ZoomInfo")
            put(r, "Job Function", r.get("ZI Job Function"), "ZoomInfo")
            put(r, "Direct Phone Number", r.get("ZI Direct Phone"), "ZoomInfo")
            put(r, "Mobile phone", r.get("ZI Mobile Phone"), "ZoomInfo")
        if not r.get("LinkedIn Contact Profile URL") and good and r.get("ZI LinkedIn URL"):
            put(r, "LinkedIn Contact Profile URL", clean_li(r["ZI LinkedIn URL"]), "LinkedIn blank, ZoomInfo's used")
        elif r.get("LinkedIn Contact Profile URL"):
            put(r, "LinkedIn Contact Profile URL", clean_li(r["LinkedIn Contact Profile URL"]), "format")
        # emails
        doms = company_domains(r)
        cands = [e.strip() for e in (r.get("Email Address", ""), r.get("ZI Email", "") if good else "") if e and e.strip()]
        cands = [c for c in dict.fromkeys(c.lower() for c in cands) if EMAIL_OK.match(c)]
        ok = [e for e in cands if email_domain(e) in doms]
        if not ok and cands:
            if r.get("Email Address"):
                changes.append({"row": r[CONTACT_ID], "contact": f"{r.get('First Name', '')} {r.get('Last Name', '')}",
                                "company": r.get("Company Name", ""), "field": "Email Address",
                                "from": r["Email Address"], "to": "", "why": "no email on the company's domain"})
            r["Email Address"], r["Additional Emails"] = "", ""
        elif ok:
            current = (r.get("Email Address") or "").lower()
            ok.sort(key=lambda e: (-usage[r[COMPANY_ID]][email_domain(e)],
                                   -patterns[r[COMPANY_ID]][email_pattern(e, r.get("First Name"), r.get("Last Name"))],
                                   0 if e == current else 1))
            put(r, "Email Address", ok[0], "on the company's domain" +
                (" — most-used domain/address format at this company" if len(ok) > 1 else ""))
            r["Additional Emails"] = ok[1] if len(ok) > 1 else ""
        if r.get("Email Address"):
            r["Email Domain"] = email_domain(r["Email Address"])

    # company-level values, decided once per company and written to all its rows
    by_co = defaultdict(list)
    for r in rows:
        by_co[r[COMPANY_ID]].append(r)
    for cid, rs in by_co.items():
        first = rs[0]
        zi_names = Counter(r["ZI Company Name"] for r in rs if r.get("ZI Match") == "good" and r.get("ZI Company Name"))
        if first.get("ZI Co Name") and same_company(first.get("Company Name", ""), first["ZI Co Name"]):
            new_name = first["ZI Co Name"]
        elif zi_names:
            new_name = zi_names.most_common(1)[0][0]
            if len(zi_names) > 1:
                ties.append({"company": first.get("Company Name"), "field": "Company Name",
                             "options": list(zi_names)})
                for r in rs:
                    flag(r, f"ZoomInfo gives several company names: {', '.join(zi_names)} — pick one")
        else:
            new_name = ""
        site_src = "ZoomInfo website, cleaned" if first.get("ZI Co Website") else "website cleaned"
        site, _ = clean_website(first.get("ZI Co Website") or first.get("Website", ""))
        co_vals = {
            "Company Name": new_name, "Website": site,
            "LinkedIn Company Profile URL": clean_li(first.get("LinkedIn Company Profile URL") or
                                                     first.get("ZI Co LinkedIn", ""), "company"),
            "Company Street Address": first.get("ZI Co Street"), "Company City": first.get("ZI Co City"),
            "Company State": first.get("ZI Co State"), "Company Zip Code": first.get("ZI Co Zip"),
            "Company Country": first.get("ZI Co Country"), "Company HQ Phone": first.get("ZI Co Phone"),
            "Employees": first.get("ZI Co Employees"), "Employee Range": first.get("ZI Co Employee Range"),
            "Revenue (in USD)": first.get("ZI Co Revenue"), "Revenue Range (in USD)": first.get("ZI Co Revenue Range"),
            "Primary Industry": first.get("ZI Co Industry"), "Founded Year": first.get("ZI Co Founded")}
        for r in rs:
            for col, v in co_vals.items():
                if col not in fields:
                    fields.append(col)
                why = {"LinkedIn Company Profile URL": "LinkedIn (format)", "Website": site_src,
                       "Company Name": "ZoomInfo's name for the same company"}.get(col, "company data: ZoomInfo")
                put(r, col, v, why)
    ws.save(run, fields, rows)
    (run / "merge_report.json").write_text(json.dumps({"changes": changes, "ties": ties}, indent=1, ensure_ascii=False))
    ws.log(run, {"action": "merge_sources", "changes": len(changes), "ties": len(ties)})
    ws.snapshot_copy(run, "06_merge")
    site_changes = [c for c in changes if c["field"] == "Website"]
    changes = [c for c in changes if c["field"] != "Website"] + list(
        {c["company"]: dict(c, contact="(company-wide)") for c in site_changes}.values())
    (run / "merge_report.json").write_text(json.dumps({"changes": changes, "ties": ties}, indent=1, ensure_ascii=False))
    by_field = Counter(c["field"] for c in changes)
    print(f"merged: {len(changes)} changes ({dict(by_field)}); {len(ties)} ties flagged -> merge_report.json")


# ---------- consistency ----------
def consistency(args):
    run = Path(args.run_dir)
    fields, rows = ws.load(run)
    us_states = {s.lower() for s in US_STATES}
    issues = {"contact": [], "company": [], "contacts_vs_company": []}
    by_co = defaultdict(list)
    for r in rows:
        by_co[r[COMPANY_ID]].append(r)
        who = f"{r.get('First Name', '')} {r.get('Last Name', '')} ({r.get('Company Name', '')})"
        # level 1 — within a contact
        if r.get("Email Address") and email_domain(r["Email Address"]) not in company_domains(r):
            issues["contact"].append({"row": r[CONTACT_ID], "who": who, "issue": "email not on the company's domain"})
        if (r.get("Person State") or "").lower() in us_states and r.get("Country") and r["Country"] != "United States":
            issues["contact"].append({"row": r[CONTACT_ID], "who": who,
                                      "issue": f"state {r['Person State']} but country {r['Country']}"})
        if not r.get("Job Title"):
            issues["contact"].append({"row": r[CONTACT_ID], "who": who, "issue": "no job title"})
        # (LinkedIn URL vs name is judged in step 2, which runs again after this)
    company_cols = [c for c in fields if c in ws.COMPANY_FIELDS]
    for cid, rs in by_co.items():
        name = rs[0].get("Company Name", "")
        # level 2 — across the company's contacts
        for col in company_cols:
            vals = {r.get(col, "") for r in rs}
            if len(vals) > 1:
                issues["company"].append({"company": name, "issue": f"contacts disagree on {col}: {sorted(vals)}"})
        used = Counter(email_domain(r.get("Email Address", "")) for r in rs if r.get("Email Address"))
        stray = [d for d in used if d not in company_domains(rs[0])]
        if stray:
            issues["company"].append({"company": name, "issue": f"email domains not in the company's domains: {stray}"})
        zi_ids = {r.get("ZI Company ID") for r in rs if r.get("ZI Match") == "good" and r.get("ZI Company ID")}
        if len(zi_ids) > 1:
            issues["company"].append({"company": name, "issue": "ZoomInfo puts these contacts at different "
                                                                "companies — same company or not?"})
            for r in rs:
                flag(r, "ZoomInfo puts this company's contacts at different companies — confirm")
        # level 3 — contacts vs the company record
        dom = rs[0].get("Company Domain", "")
        site = re.sub(r"^www\.", "", (rs[0].get("Website") or "").lower())
        if dom and site and not (site == dom or site.endswith("." + dom) or dom.endswith("." + site)):
            issues["contacts_vs_company"].append({"company": name, "issue": f"website {site} vs email domain {dom}"
                                                                           " (fine if the company uses both)"})
        hq = rs[0].get("Company Country", "")
        abroad = [r.get("Country") for r in rs if r.get("Country") and hq and r["Country"] != hq]
        if abroad:
            issues["contacts_vs_company"].append({"company": name, "issue": f"HQ in {hq}, contacts in "
                                                                           f"{sorted(set(abroad))} (info)"})
        if not name:
            issues["contacts_vs_company"].append({"company": cid, "issue": "company has no name"})
    ws.save(run, fields, rows)
    (run / "consistency_report.json").write_text(json.dumps(issues, indent=1, ensure_ascii=False))
    ws.snapshot_copy(run, "07_consistency")
    print("consistency: " + ", ".join(f"{k} {len(v)}" for k, v in issues.items()) + " -> consistency_report.json")


US_STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
             "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
             "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
             "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
             "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
             "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
             "West Virginia", "Wisconsin", "Wyoming", "District of Columbia"]


# ---------- prune ----------
def prune(args):
    run = Path(args.run_dir)
    fields, rows = ws.load(run)
    drop = [c for c in fields if c.startswith("ZI ") or c in HELPER_COLS]
    empty = [c for c in fields if c not in drop and c not in (CONTACT_ID, COMPANY_ID, "Flag", "Flag Reason")
             and not any((r.get(c) or "").strip() for r in rows)]
    if drop:
        with open(zi_dir(run) / "zi_columns.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[CONTACT_ID] + drop, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    keep = [c for c in fields if c not in drop and (c not in empty or not args.drop_empty)]
    for r in rows:
        for c in drop:
            r.pop(c, None)
    ws.save(run, keep, rows)
    ws.log(run, {"action": "prune", "removed": drop + (empty if args.drop_empty else [])})
    ws.snapshot_copy(run, "08_prune")
    print(f"removed {len(drop)} ZoomInfo/helper columns (copy in zi/zi_columns.csv): {drop}")
    if empty:
        print(f"{'removed' if args.drop_empty else 'empty (kept; --drop-empty removes them)'}: {empty}")


def diff_review(args):
    old, new = json.loads(Path(args.old).read_text()), json.loads(Path(args.new).read_text())

    def items(x, path=""):
        if isinstance(x, dict) and any(isinstance(v, list) for v in x.values()):
            for k, v in x.items():
                yield from items(v, f"{path}{k}.")
        elif isinstance(x, list):
            for e in x:
                yield path.rstrip("."), json.dumps(e, sort_keys=True, ensure_ascii=False)
    seen = set(items(old))
    fresh = [(p, e) for p, e in items(new) if (p, e) not in seen]
    print(f"{len(fresh)} entries new since the first pass (everything else was already decided):")
    for p, e in fresh:
        print(f"[{p}] {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, func in (("plan", plan), ("attach", attach), ("merge", merge), ("consistency", consistency)):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True); p.set_defaults(func=func)
    p = sub.add_parser("ingest"); p.add_argument("--run-dir", required=True)
    p.add_argument("--kind", choices=["contacts", "companies"], required=True)
    p.add_argument("--batch", type=int, required=True); p.add_argument("--response", required=True)
    p.set_defaults(func=ingest)
    p = sub.add_parser("prune"); p.add_argument("--run-dir", required=True)
    p.add_argument("--drop-empty", action="store_true"); p.set_defaults(func=prune)
    p = sub.add_parser("diff-review"); p.add_argument("--old", required=True); p.add_argument("--new", required=True)
    p.set_defaults(func=diff_review)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
