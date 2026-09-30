"""The run's single working file: one row per contact, company columns on the row.

Every step reads and updates `<run_dir>/working.csv` in place; nothing else
holds list data. The two upload files are generated from it at the end
(`export`) and never edited. Company-level values are always written to every
row of that company, so rows can't disagree. Every change goes through this
script (no hand edits) and is logged in `<run_dir>/changes.jsonl`; after each
step a read-only copy is saved in `<run_dir>/history/`.

  init       Build working.csv from the list's contact export (ZoomInfo
             contact exports carry every company column). If a company export
             is given, its company values win; otherwise, where a company's
             rows disagree (ZoomInfo sometimes varies per contact), the most
             common value is used. Everything harmonized is listed in
             init_report.json for the chat.
  show       Print rows (or selected columns) as a markdown table for the chat.
  set        Change fields on a row, as the user asked in chat. Company fields
             are applied to every row of that company. Prints before -> after.
  flag       Flag a row for the user's review (Flag + Flag Reason columns).
  resolve    Clear a row's flag after the user decided it stays as it is.
  remove     Remove a row — only when the user asked for it. Logged, and
             listed at export so whoever sourced the list can see it.
  flags      List open flags.
  snapshot   Save a read-only copy into history/ after a step.
  export     Write upload/contacts_upload.csv and upload/companies_upload.csv
             (upload columns only, import-ready: blank Record ID = create).
             Refuses while any row is still flagged. They are regenerated on
             every export and never edited.
"""
import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTACT_ID = "ZoomInfo Contact ID"
COMPANY_ID = "ZoomInfo Company ID"
FLAG, FLAG_REASON = "Flag", "Flag Reason"

# Columns that describe the company, not the person: they must be identical on
# every row of the same company. (Contact-file columns like "Company Name" and
# "Website" are company data too.)
COMPANY_FIELDS = {
    COMPANY_ID, "Company Name", "Website", "Founded Year", "Company HQ Phone", "Fax", "Ticker",
    "Revenue (in 000s USD)", "Revenue (in USD)", "Revenue Range (in USD)", "Employees", "Employee Range",
    "SIC Code 1", "SIC Code 2", "SIC Codes", "NAICS Code 1", "NAICS Code 2", "NAICS Codes",
    "Primary Industry", "Primary Sub-Industry", "All Industries", "All Sub-Industries",
    "Industry Hierarchical Category", "Secondary Industry Hierarchical Category", "Alexa Rank",
    "ZoomInfo Company Profile URL", "LinkedIn Company Profile URL", "Facebook Company Profile URL",
    "Twitter Company Profile URL", "Ownership Type", "Business Model", "Certified Active Company",
    "Certification Date", "Total Funding Amount (in 000s USD)", "Recent Funding Amount (in 000s USD)",
    "Recent Funding Round", "Recent Funding Date", "Recent Investors", "All Investors",
    "Company Street Address", "Company City", "Company State", "Company Zip Code", "Company Country",
    "Full Address", "Number of Locations", "Company Domain", "Additional Domains",
    "HubSpot Company Record ID", "Type", "Outbound Personalization Token",
}
ADDED_COLUMNS = ["Company Domain", "Additional Domains", "Type", "HubSpot Company Record ID",
                 "HubSpot Contact Record ID", FLAG, FLAG_REASON]

CONTACT_EXPORT = [
    CONTACT_ID, "First Name", "Last Name", "Job Title", "Management Level", "Job Function",
    "Department", "Direct Phone Number", "Email Address", "Email Domain", "Mobile phone",
    "ZoomInfo Contact Profile URL", "LinkedIn Contact Profile URL", "Person Street", "Person City",
    "Person State", "Person Zip Code", "Country", "Company Name", "Website", "Company HQ Phone",
    "HubSpot Contact Record ID", "New Contact Outbound Personalization",
]
COMPANY_EXPORT = [
    COMPANY_ID, "Company Name", "Website", "Founded Year", "Company HQ Phone",
    "Revenue (in USD)", "Revenue Range (in USD)", "Employees", "Employee Range",
    "SIC Code 1", "SIC Code 2", "NAICS Code 1", "NAICS Code 2", "Primary Industry",
    "ZoomInfo Company Profile URL", "LinkedIn Company Profile URL",
    "Facebook Company Profile URL", "Twitter Company Profile URL", "Company City",
    "Company State", "Company Zip Code", "Company Country", "Full Address",
    "Company Domain", "Additional Domains", "Type", "Outbound Personalization Token",
    "HubSpot Company Record ID",
]


# ---------------------------------------------------------------- file access

def working_path(run_dir):
    return Path(run_dir) / "working.csv"


def load(run_dir):
    path = working_path(run_dir)
    if not path.exists():
        raise SystemExit(f"{path} not found — run `worksheet.py init` first")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames), list(reader)


def save(run_dir, fields, rows):
    path = working_path(run_dir)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def log(run_dir, entry):
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with open(Path(run_dir) / "changes.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ensure_columns(fields, names, after=None):
    for n in names:
        if n not in fields:
            if after and after in fields:
                fields.insert(fields.index(after) + 1, n)
                after = n
            else:
                fields.append(n)
    return fields


def by_id(rows, row_id):
    for r in rows:
        if r.get(CONTACT_ID) == str(row_id):
            return r
    raise SystemExit(f"no row with {CONTACT_ID} {row_id}")


def company_rows(rows, row):
    cid = row.get(COMPANY_ID)
    return [r for r in rows if cid and r.get(COMPANY_ID) == cid] or [row]


def set_company_field(rows, company_id, field, value):
    """Write a company-level value to every row of that company."""
    for r in rows:
        if r.get(COMPANY_ID) == company_id:
            r[field] = value


def markdown(rows, columns):
    esc = lambda v: str(v or "").replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(esc(r.get(c)) for c in columns) + " |" for r in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def init(args):
    with open(args.contacts, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields, rows = list(reader.fieldnames), list(reader)
    if CONTACT_ID not in fields:
        raise SystemExit(f"{args.contacts}: no '{CONTACT_ID}' column — not a ZoomInfo contact export. "
                         "Map the columns to the ZoomInfo names first (ask the user).")
    from collections import Counter, defaultdict
    harmonized = []
    if args.companies:
        with open(args.companies, newline="", encoding="utf-8-sig") as f:
            creader = csv.DictReader(f)
            companies = {c[COMPANY_ID]: c for c in creader}
            for col in creader.fieldnames:
                if col not in fields and col in COMPANY_FIELDS:
                    fields.append(col)
        for r in rows:
            c = companies.get(r.get(COMPANY_ID))
            if not c:
                continue
            for col, val in c.items():
                if col in COMPANY_FIELDS and col != COMPANY_ID and (r.get(col) or "") != (val or ""):
                    harmonized.append({"company": r.get("Company Name"), "field": col,
                                       "row_value": r.get(col) or "", "used": val or "", "why": "company export"})
                    r[col] = val
    # Any remaining disagreement between a company's rows: most common value wins.
    groups = defaultdict(list)
    for r in rows:
        groups[r.get(COMPANY_ID)].append(r)
    for cid, members in groups.items():
        for col in fields:
            if col not in COMPANY_FIELDS or len(members) < 2:
                continue
            counts = Counter((m.get(col) or "") for m in members)
            if len(counts) > 1:
                value = counts.most_common(1)[0][0]
                tie = len(counts) > 1 and list(counts.values()).count(counts[value]) > 1
                harmonized.append({"company": members[0].get("Company Name"), "field": col,
                                   "values": dict(counts), "used": value,
                                   "why": "tie — first most common value" if tie else "most common across its contacts"})
                for m in members:
                    m[col] = value
    unique = []
    for h in harmonized:
        if h not in unique:
            unique.append(h)
    harmonized = unique
    filled = len(harmonized)
    fields = ensure_columns(fields, ADDED_COLUMNS)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if working_path(out).exists() and not args.force:
        raise SystemExit(f"{working_path(out)} already exists — this run was started already (use --force to restart)")
    save(out, fields, rows)
    (out / "init_report.json").write_text(json.dumps({"harmonized": harmonized}, indent=2, ensure_ascii=False))
    log(out, {"action": "init", "source": str(args.contacts), "companies_source": args.companies,
              "rows": len(rows), "company_values_harmonized": filled})
    snapshot_copy(out, "00_init")
    n_companies = len({r.get(COMPANY_ID) for r in rows})
    print(f"working.csv: {len(rows)} contacts at {n_companies} companies; "
          f"{filled} company values harmonized across rows (init_report.json)")


def show(args):
    fields, rows = load(args.run_dir)
    picked = [by_id(rows, i) for i in args.row] if args.row else \
        [r for r in rows if r.get(FLAG)] if args.flagged else rows
    columns = args.columns.split(",") if args.columns else \
        [c for c in ([CONTACT_ID, "First Name", "Last Name", "Job Title", "Email Address", "Company Name",
                      "Company Domain", "LinkedIn Contact Profile URL", FLAG, FLAG_REASON]) if c in fields]
    print(markdown(picked, columns))


def set_fields(args):
    fields, rows = load(args.run_dir)
    row = by_id(rows, args.row)
    changes = []
    for item in args.field:
        name, _, value = item.partition("=")
        if name not in fields:
            raise SystemExit(f"unknown column {name!r}")
        targets = company_rows(rows, row) if name in COMPANY_FIELDS else [row]
        before = row.get(name, "")
        for t in targets:
            t[name] = value
        changes.append({"field": name, "before": before, "after": value, "rows": len(targets)})
    save(args.run_dir, fields, rows)
    log(args.run_dir, {"action": "set", "row": args.row, "changes": changes, "reason": args.reason})
    print(markdown(changes, ["field", "before", "after", "rows"]))
    company_changes = [c for c in changes if c["rows"] > 1]
    if company_changes:
        print(f"(company fields applied to all {company_changes[0]['rows']} rows of this company)")


def flag(args):
    fields, rows = load(args.run_dir)
    row = by_id(rows, args.row)
    row[FLAG], row[FLAG_REASON] = "REVIEW", args.reason
    save(args.run_dir, fields, rows)
    log(args.run_dir, {"action": "flag", "row": args.row, "reason": args.reason})
    print(f"flagged {args.row}: {args.reason}")


def resolve(args):
    fields, rows = load(args.run_dir)
    row = by_id(rows, args.row)
    before = row.get(FLAG_REASON, "")
    row[FLAG], row[FLAG_REASON] = "", ""
    save(args.run_dir, fields, rows)
    log(args.run_dir, {"action": "resolve", "row": args.row, "was": before, "note": args.note})
    print(f"cleared flag on {args.row} ({before}) — {args.note}")


def remove(args):
    fields, rows = load(args.run_dir)
    row = by_id(rows, args.row)
    rows.remove(row)
    save(args.run_dir, fields, rows)
    log(args.run_dir, {"action": "remove", "row": args.row, "reason": args.reason, "removed": row})
    left = sum(1 for r in rows if r.get(COMPANY_ID) == row.get(COMPANY_ID))
    print(f"removed {args.row} ({row.get('First Name')} {row.get('Last Name')}, {row.get('Company Name')}) — "
          f"{args.reason}. {left} other contact(s) left at that company"
          + ("; the company will not be exported" if not left else ""))


def flags(args):
    fields, rows = load(args.run_dir)
    open_rows = [r for r in rows if r.get(FLAG)]
    print(markdown(open_rows, [CONTACT_ID, "First Name", "Last Name", "Company Name", FLAG_REASON]) if open_rows
          else "no open flags")


def snapshot_copy(run_dir, label):
    hist = Path(run_dir) / "history"
    hist.mkdir(exist_ok=True)
    shutil.copyfile(working_path(run_dir), hist / f"{label}.csv")


def snapshot(args):
    snapshot_copy(args.run_dir, args.label)
    print(f"saved history/{args.label}.csv")


def export(args):
    export_files(args.run_dir, args.out_dir)


def export_files(run_dir, out_dir=None):
    fields, rows = load(run_dir)
    open_rows = [r for r in rows if r.get(FLAG)]
    if open_rows:
        raise SystemExit(f"{len(open_rows)} row(s) still flagged — resolve them with the user first "
                         f"(`worksheet.py flags`)")
    # Company-level values must agree across a company's rows.
    conflicts = []
    companies = {}
    for r in rows:
        cid = r.get(COMPANY_ID)
        if cid not in companies:
            companies[cid] = r
            continue
        for col in COMPANY_EXPORT:
            if col in fields and (companies[cid].get(col) or "") != (r.get(col) or ""):
                conflicts.append(f"{companies[cid].get('Company Name')}: {col}")
    if conflicts:
        raise SystemExit("company rows disagree (fix with `set`): " + "; ".join(sorted(set(conflicts))))
    out = Path(out_dir or Path(run_dir) / "upload")
    out.mkdir(parents=True, exist_ok=True)
    # Import-ready: HubSpot needs a blank Record ID (not "Not in HubSpot") to create a record.
    blank = lambda r: {k: ("" if k.startswith("HubSpot") and k.endswith("Record ID") and v == "Not in HubSpot" else v)
                       for k, v in r.items()}
    rows = [blank(r) for r in rows]
    companies = {k: blank(v) for k, v in companies.items()}
    contact_cols = [c for c in CONTACT_EXPORT if c in fields]
    company_cols = [c for c in COMPANY_EXPORT if c in fields]
    for name, cols, data in (("contacts_upload.csv", contact_cols, rows),
                             ("companies_upload.csv", company_cols, list(companies.values()))):
        with open(out / name, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)
    removed = []
    log_path = Path(run_dir) / "changes.jsonl"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e["action"] == "remove":
                r = e["removed"]
                removed.append(f"{r.get('First Name')} {r.get('Last Name')} ({r.get('Company Name')}): {e['reason']}")
    log(run_dir, {"action": "export", "contacts": len(rows), "companies": len(companies)})
    print(f"contacts_upload.csv: {len(rows)} rows, {len(contact_cols)} columns; "
          f"companies_upload.csv: {len(companies)} rows, {len(company_cols)} columns")
    if removed:
        print("rows removed during the run (tell the list's owner):")
        for r in removed:
            print("  -", r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--contacts", required=True)
    p.add_argument("--companies")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=init)
    p = sub.add_parser("show")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--row", nargs="*")
    p.add_argument("--flagged", action="store_true")
    p.add_argument("--columns", help="comma-separated column names")
    p.set_defaults(func=show)
    p = sub.add_parser("set")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--row", required=True)
    p.add_argument("--field", required=True, nargs="+", help='"Column=value"')
    p.add_argument("--reason", required=True)
    p.set_defaults(func=set_fields)
    for name, func, extra in (("flag", flag, "reason"), ("resolve", resolve, "note"), ("remove", remove, "reason")):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True)
        p.add_argument("--row", required=True)
        p.add_argument(f"--{extra}", required=True)
        p.set_defaults(func=func)
    p = sub.add_parser("flags")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=flags)
    p = sub.add_parser("snapshot")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--label", required=True)
    p.set_defaults(func=snapshot)
    p = sub.add_parser("export")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out-dir")
    p.set_defaults(func=export)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
