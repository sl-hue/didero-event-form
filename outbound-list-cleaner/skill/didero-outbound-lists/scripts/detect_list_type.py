"""Which kind of list is this? ZoomInfo / LinkedIn (Sales Nav or Evaboot) / event list.

  python3 detect_list_type.py <file> [<file> ...]

Reads the header row (CSV or Excel), scores it against each type's tell-tale
columns and prints the best guess, the evidence and a confidence:
  high → Claude says what the list is and carries on (the user can correct it)
  low  → Claude asks the user.
Event lists are split into: event contact list (people named), event company
list (no names; "with titles" when a job-title column has values).
"""
import csv
import json
import sys
from pathlib import Path

SIGNS = {
    "zoominfo": ["ZoomInfo Contact ID", "ZoomInfo Company ID", "Contact Accuracy Score", "Management Level",
                 "Revenue (in 000s USD)", "Employees", "Primary Industry", "Person Zip Code",
                 "ZoomInfo Contact Profile URL", "LinkedIn Contact Profile URL", "Direct Phone Number"],
    "linkedin": ["Linkedin URL Public", "Linkedin URL Unique ID", "Sales Navigator URL", "Current Jobs Number",
                 "Profile Headline", "Company Linkedin URL Unique ID", "Total Positions Count", "Is Open Profile",
                 "Is Premium", "Connections", "Years in Position", "Has New Position", "Matches Filters"],
    "event": ["Registration", "Registration Date", "Registered", "Attendee", "Attendee Type", "Badge",
              "Badge Type", "Ticket", "Ticket Type", "Booth", "Session", "Check-in", "Checked In", "Event",
              "Event Name", "Exhibitor", "Sponsor", "RSVP"],
}
LABEL = {"zoominfo": "ZoomInfo export", "linkedin": "LinkedIn (Sales Nav / Evaboot) export", "event": "event list",
         "event-contacts": "event contact list (people named)",
         "event-companies": "event company list (no contact names, no job titles)",
         "event-companies-titles": "event company list with job titles (no contact names)"}
NAME_COLS = {"first name", "firstname", "first", "last name", "lastname", "surname", "full name", "name of attendee",
             "attendee name", "contact name", "speaker", "speaker name", "attendee"}
COMPANY_COLS = {"company", "company name", "organization", "organisation", "exhibitor", "exhibitor name", "sponsor",
                "sponsor name", "account", "account name", "employer"}
TITLE_COLS = {"job title", "title", "titles", "position", "role", "contact title"}
FLOW = {
    "zoominfo": "references/zoominfo-lists.md, steps 1–6",
    "linkedin": "references/screening.md (multiple jobs → companies → contacts → title/company cleaning), "
                "then references/zoominfo-lists.md steps 1–2, ZoomInfo pull, source priority, consistency, prune, "
                "steps 1–2 again, then steps 3–6",
    "event": "references/event-lists.md — contact list (people named) or company-only list (branch A: ZoomInfo "
             "list build; branch B: job titles without names)",
    "event-contacts": "references/event-lists.md — event contact list, steps 1–5",
    "event-companies": "references/event-lists.md — company-only list, branch A (ZoomInfo list build)",
    "event-companies-titles": "references/event-lists.md — company-only list, branch B (find the people for the titles)",
}


def table(path, limit=200):
    """Header row plus up to `limit` data rows."""
    p = str(path).lower()
    if p.endswith((".xlsx", ".xlsm")):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        cols = [str(h).strip() if h is not None else "" for h in next(it)]
        rows = [dict(zip(cols, ["" if v is None else str(v) for v in r])) for _, r in zip(range(limit), it)]
        return [c for c in cols if c], rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return [h.strip() for h in r.fieldnames], [row for _, row in zip(range(limit), r)]


def headers(path):
    return table(path, 0)[0]


def detect(cols):
    low = {c.lower() for c in cols}
    hits = {t: [s for s in signs if s.lower() in low] for t, signs in SIGNS.items()}
    # Partial event cues ("Registration Status", "Attendee Email") count too.
    hits["event"] += [c for c in cols if any(w in c.lower() for w in ("registr", "attendee", "badge", "ticket",
                                                                       "booth", "exhibitor", "rsvp"))
                      and c not in hits["event"] and "seeker" not in c.lower()]
    best = max(hits, key=lambda t: len(hits[t]))
    if not hits[best]:
        best = "unknown"
    return best, hits


def classify(cols, rows):
    """-> (type, confidence, evidence)"""
    best, hits = detect(cols)
    low = {c.lower().strip(): c for c in cols}
    names = [low[c] for c in low if c in NAME_COLS]
    company = [low[c] for c in low if c in COMPANY_COLS]
    titles = [low[c] for c in low if c in TITLE_COLS]
    filled = lambda col: sum(1 for r in rows if (r.get(col) or "").strip())
    evidence = {LABEL[t]: h for t, h in hits.items() if h}
    if best in ("zoominfo", "linkedin") and len(hits[best]) >= 3:
        return best, "high", evidence
    if best in ("zoominfo", "linkedin"):
        return best, "low", evidence
    # Not ZoomInfo/LinkedIn: an event list (or something we ask about).
    named = any(filled(c) for c in names)
    if company and not named:
        t = "event-companies-titles" if any(filled(c) for c in titles) else "event-companies"
        evidence["structure"] = [f"company column: {company[0]}", "no contact-name column with values"] + \
            ([f"job titles in: {titles[0]}"] if t.endswith("titles") else ["no job titles"])
        return t, "high", evidence
    if company and named:
        evidence["structure"] = [f"company column: {company[0]}", f"names in: {', '.join(names)}"]
        return "event-contacts", ("high" if hits["event"] else "low"), evidence
    return "unknown", "low", evidence


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = []
    for f in sys.argv[1:]:
        cols, rows = table(f)
        kind, conf, evidence = classify(cols, rows)
        out.append({"file": Path(f).name, "guess": LABEL.get(kind, "unknown — ask the user"), "type": kind,
                    "confidence": conf,
                    "do": ("say what it is and carry on (the user can correct it)" if conf == "high"
                           else "ask the user what kind of list this is"),
                    "evidence": evidence, "next": FLOW.get(kind, "ask the user"), "columns": len(cols)})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
