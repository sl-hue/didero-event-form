"""Stage 5 — hand the screened list to the working file (references/zoominfo-lists.md).

  python3 handoff.py --run-dir <screening run> --out <file.csv>

Writes the contacts that stay (Decision = keep) as one CSV in the column
names the working file uses (ZoomInfo's), with company
columns on every row. Then:
  python3 scripts/worksheet.py init --contacts <file.csv> --out-dir <cleaner run>

IDs: LinkedIn has no ZoomInfo IDs, so each contact gets "LI-<Row ID>" and each
company "LIC-<n>" (stable within the run). They are never imported to HubSpot.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from location import parse_location  # noqa: E402
from screen import COUNTRY_ALIASES, load, pick  # noqa: E402

OUT_COLUMNS = [
    "ZoomInfo Contact ID", "First Name", "Last Name", "Job Title", "Email Address", "Email Domain",
    "LinkedIn Contact Profile URL", "Person City", "Person State", "Country",
    "ZoomInfo Company ID", "Company Name", "Website", "LinkedIn Company Profile URL", "Founded Year",
    "Revenue Range (in USD)", "Employees", "Employee Range", "Primary Industry",
    "Company City", "Company State", "Company Zip Code", "Company Country", "Full Address",
    "Source List Type", "LinkedIn Headline", "Jobs Check", "Event Name",
]
FIRST, LAST = ["First Name", "first_name", "firstName"], ["Last Name", "last_name", "lastName"]


def first_of(r, names):
    return next((r[n].strip() for n in names if r.get(n, "").strip()), "")


def clean_li(url):
    """Any LinkedIn profile URL -> https://www.linkedin.com/in/<slug> (format only, no live check)."""
    u = (url or "").strip()
    m = re.search(r"linkedin\.com/(in|company)/([^/?#\s]+)", u, re.I)
    return f"https://www.linkedin.com/{m.group(1).lower()}/{m.group(2).rstrip('/')}" if m else u


def revenue_range(lo, hi):
    """LinkedIn min/max (millions USD) -> ZoomInfo-style range text."""
    def money(m):
        m = float(m)
        return f"${m / 1000:g} bil." if m >= 1000 else f"${m:g} mil."
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return ""
    if hi_f >= 1_000_000 or hi_f <= lo_f:
        return f"Over {money(lo_f)}"
    return f"{money(lo_f)} - {money(hi_f)}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--list-type", default="LinkedIn", choices=["LinkedIn", "Event"])
    args = ap.parse_args()
    _, rows = load(args.run_dir)
    keep = [r for r in rows if r.get("Decision") == "keep"]
    if not keep:
        raise SystemExit("no contacts with Decision = keep — finish the screening review first")
    open_ = sum(1 for r in rows if not r.get("Decision"))
    company_ids = {}
    out = []
    for r in keep:
        key = r["Company"].strip().lower()
        company_ids.setdefault(key, f"LIC-{len(company_ids) + 1:04d}")
        first, last = first_of(r, FIRST), first_of(r, LAST)
        if not (first or last):
            first, _, last = r["Contact"].partition(" ")
        email = first_of(r, ["Email", "Email Address", "email"])
        hq = parse_location(first_of(r, ["Company Location"]), COUNTRY_ALIASES)
        full = first_of(r, ["Company Headquarters (Full Address)", "Company Headquarters"])
        zip_m = re.search(r",\s*([0-9]{5}(?:-[0-9]{4})?|[A-Z][0-9][A-Z] ?[0-9][A-Z][0-9])\s*,", full)
        founded = first_of(r, ["Company Year Founded", "Founded Year"])
        out.append({
            "ZoomInfo Contact ID": f"{'EV' if args.list_type == 'Event' else 'LI'}-{r['Row ID']}",
            "First Name": first, "Last Name": last, "Job Title": r["Title"],
            "Email Address": email, "Email Domain": email.split("@")[-1].lower() if "@" in email else "",
            "LinkedIn Contact Profile URL": clean_li(pick(r, "linkedin")),
            "Person City": r.get("Contact City", ""), "Person State": r.get("Contact State", ""),
            "Country": r.get("Contact Country", ""),
            "ZoomInfo Company ID": company_ids[key], "Company Name": r["Company"],
            "Website": first_of(r, ["Company Website URL", "Website", "Company Website"]),
            "LinkedIn Company Profile URL": clean_li(first_of(r, ["Company Linkedin URL Unique ID",
                                                                  "Company LinkedIn URL", "Company Linkedin URL"])),
            "Founded Year": "" if founded in ("", "0") else founded,
            "Revenue Range (in USD)": revenue_range(first_of(r, ["Company Revenue Min (Millions USD)"]),
                                                    first_of(r, ["Company Revenue Max (Millions USD)"])),
            "Employees": "" if first_of(r, ["Company Employee Exact Count"]) in ("", "0")
                         else first_of(r, ["Company Employee Exact Count"]),
            "Employee Range": first_of(r, ["Company Employee Range"]),
            "Primary Industry": first_of(r, ["Company Industry"]),
            "Company City": hq["city"], "Company State": hq["state"],
            "Company Zip Code": zip_m.group(1) if zip_m else "",
            "Company Country": r.get("Company Country") or hq["country"], "Full Address": full,
            "Source List Type": args.list_type, "LinkedIn Headline": first_of(r, ["Profile Headline", "Headline"]),
            "Event Name": first_of(r, ["Event Name"]),
            "Jobs Check": r.get("Jobs Check", ""),
        })
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(out)
    print(f"{args.out}: {len(out)} contacts at {len(company_ids)} companies"
          + (f" ({open_} contacts had no decision and were left out — check with the user)" if open_ else ""))
    print(f"next: python3 scripts/worksheet.py init --contacts {args.out} --out-dir <run_dir>")


if __name__ == "__main__":
    main()
