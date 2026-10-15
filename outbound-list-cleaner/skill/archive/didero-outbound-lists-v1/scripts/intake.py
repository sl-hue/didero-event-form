"""Event lists — build the one event file with the four essential fields.

  init   --input <file> [<file> ...] --event "<event name>" --out-dir <run_dir>
         Reads attendee / speaker / registration exports (CSV or Excel) into
         <run_dir>/event.csv: First Name, Last Name, Job Title, Company (the
         essentials) plus whatever else the files have (email, phone, LinkedIn
         URL, website, location) and Event Name / Source.
  add    --run-dir <run_dir> --file people.json --source "<where it came from>"
         Adds people Claude read off screenshots, PDFs or pasted pages:
         [{"first": "", "last": "", "full": "", "title": "", "company": "", "email": "",
           "linkedin": "", "website": ""}]. The same person (name + company) is
         merged, filling blanks only — never overwriting.
  gaps   --run-dir <run_dir>  People missing an essential field (ask the user or
         look for another source), and full names that couldn't be split safely.

The file holds personal data: keep it on the user's device; never publish it.
"""
import argparse
import csv
import json
import re
from pathlib import Path

COLUMNS = ["Row ID", "First Name", "Last Name", "Job Title", "Company", "Email", "Phone", "LinkedIn URL",
           "Company Website", "Company City", "Company State", "Company Country", "Event Name", "Source", "Note",
           "Company Employees", "Company Revenue", "HubSpot Company Record ID", "Company Data Source"]
ESSENTIAL = ["First Name", "Last Name", "Job Title", "Company"]
ALIASES = {
    "First Name": ["first name", "firstname", "first", "given name", "fname"],
    "Last Name": ["last name", "lastname", "last", "surname", "family name", "lname"],
    "full": ["full name", "name", "attendee name", "attendee", "speaker", "speaker name", "contact name", "contact"],
    "Job Title": ["job title", "title", "position", "role", "designation", "job"],
    "Company": ["company", "company name", "organization", "organisation", "employer", "account", "account name",
                "organization name", "exhibitor"],
    "Email": ["email", "email address", "e-mail", "work email", "business email"],
    "Phone": ["phone", "phone number", "mobile", "work phone", "direct phone"],
    "LinkedIn URL": ["linkedin", "linkedin url", "linkedin profile", "linkedin profile url", "profile url"],
    "Company Website": ["website", "company website", "url", "web", "domain", "company url"],
    "Company City": ["city", "company city"],
    "Company State": ["state", "province", "state/province", "company state", "region"],
    "Company Country": ["country", "company country"],
}


def path(run_dir):
    return Path(run_dir) / "event.csv"


def load(run_dir):
    p = path(run_dir)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(run_dir, rows):
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    tmp = path(run_dir).with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path(run_dir))


def read_table(p):
    if str(p).lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        ws = openpyxl.load_workbook(p, read_only=True, data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        fields = [str(h).strip() if h is not None else f"Column {i}" for i, h in enumerate(next(it), 1)]
        return fields, [{f: "" if v is None else str(v).strip() for f, v in zip(fields, r)} for r in it if any(r)]
    with open(p, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), [{k: (v or "").strip() for k, v in row.items()} for row in r]


def split_name(full):
    """'Mary Ann Smith' -> ('Mary Ann', 'Smith', note). Credentials/suffixes are left for step 2."""
    parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
    if not parts:
        return "", "", ""
    if "," in full:  # 'Smith, Mary'
        last, _, first = full.partition(",")
        return first.strip(), last.strip(), ""
    if len(parts) == 1:
        return parts[0], "", "only one name given"
    note = "name split guessed (more than two words)" if len(parts) > 2 else ""
    return " ".join(parts[:-1]), parts[-1], note


def key(r):
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return norm(r["First Name"])[:3] + "|" + norm(r["Last Name"]) + "|" + norm(r["Company"])


def merge_into(rows, new):
    """Same person (name + company) -> fill blanks; otherwise add. Returns 'added' / 'merged'."""
    k = key(new)
    for r in rows:
        if key(r) == k and k.strip("|"):
            for c in COLUMNS:
                if c not in ("Row ID", "Source") and not r.get(c) and new.get(c):
                    r[c] = new[c]
            if new.get("Source") and new["Source"] not in r.get("Source", ""):
                r["Source"] = (r["Source"] + "; " if r.get("Source") else "") + new["Source"]
            return "merged"
    new["Row ID"] = f"E{len(rows) + 1:04d}"
    rows.append(new)
    return "added"


def init(args):
    rows = load(args.out_dir)
    stats = {"added": 0, "merged": 0}
    for f in args.input:
        fields, data = read_table(f)
        low = {h.lower().strip(): h for h in fields}
        found = {k: next((low[a] for a in v if a in low), None) for k, v in ALIASES.items()}
        if not found["Company"] or not (found["First Name"] or found["full"]):
            raise SystemExit(f"{Path(f).name}: couldn't find the name and company columns. Columns: {fields}. "
                             "Ask the user which column holds each.")
        for d in data:
            r = {c: d.get(found[c], "") if found.get(c) else "" for c in COLUMNS if c in found}
            note = ""
            if not found["First Name"] or not d.get(found["First Name"]):
                r["First Name"], r["Last Name"], note = split_name(d.get(found["full"], "") if found["full"] else "")
            r.update({"Event Name": args.event, "Source": Path(f).name, "Note": note})
            if any(r.get(c) for c in ESSENTIAL):
                stats[merge_into(rows, r)] += 1
        print(f"{Path(f).name}: columns used " + ", ".join(f"{k}={v}" for k, v in found.items() if v))
    save(args.out_dir, rows)
    print(f"event.csv: {len(rows)} people ({stats['added']} added, {stats['merged']} merged with someone already in)")
    gaps(argparse.Namespace(run_dir=args.out_dir))


def add(args):
    rows = load(args.run_dir)
    event = rows[0]["Event Name"] if rows else ""
    people = json.loads(Path(args.file).read_text())
    stats = {"added": 0, "merged": 0}
    for p in people:
        first, last, note = (p.get("first", ""), p.get("last", ""), "")
        if not (first or last) and p.get("full"):
            first, last, note = split_name(p["full"])
        r = {"First Name": first.strip(), "Last Name": last.strip(), "Job Title": p.get("title", "").strip(),
             "Company": p.get("company", "").strip(), "Email": p.get("email", "").strip(),
             "LinkedIn URL": p.get("linkedin", "").strip(), "Company Website": p.get("website", "").strip(),
             "Event Name": event, "Source": args.source, "Note": note}
        stats[merge_into(rows, r)] += 1
    save(args.run_dir, rows)
    print(f"from {args.source}: {stats['added']} added, {stats['merged']} merged; event.csv now {len(rows)} people")
    gaps(args)


def gaps(args):
    rows = load(args.run_dir)
    missing = [(r["Row ID"], f"{r['First Name']} {r['Last Name']}".strip() or "(no name)", r["Company"],
                [c for c in ESSENTIAL if not r.get(c)]) for r in rows]
    missing = [m for m in missing if m[3]]
    notes = [(r["Row ID"], f"{r['First Name']} {r['Last Name']}", r["Note"]) for r in rows if r.get("Note")]
    by_field = {c: sum(1 for m in missing if c in m[3]) for c in ESSENTIAL}
    print(f"essential fields complete for {len(rows) - len(missing)} of {len(rows)} people; missing: {by_field}")
    for rid, who, co, cols in missing[:50]:
        print(f"  {rid} {who} @ {co or '?'}: missing {', '.join(cols)}")
    for rid, who, n in notes[:50]:
        print(f"  {rid} {who}: {n}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--input", nargs="+", required=True)
    p.add_argument("--event", required=True); p.add_argument("--out-dir", required=True); p.set_defaults(func=init)
    p = sub.add_parser("add"); p.add_argument("--run-dir", required=True); p.add_argument("--file", required=True)
    p.add_argument("--source", required=True); p.set_defaults(func=add)
    p = sub.add_parser("gaps"); p.add_argument("--run-dir", required=True); p.set_defaults(func=gaps)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
