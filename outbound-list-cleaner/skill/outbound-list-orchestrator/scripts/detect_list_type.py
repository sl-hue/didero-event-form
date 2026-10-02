"""Which kind of list is this? ZoomInfo / LinkedIn (Sales Nav or Evaboot) / event list.

  python3 detect_list_type.py <file> [<file> ...]

Reads only the header row (CSV or Excel), scores it against each type's
tell-tale columns and prints the best guess with the evidence. It's a guess:
Claude always confirms the type with the user before starting.
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
LABEL = {"zoominfo": "ZoomInfo export", "linkedin": "LinkedIn (Sales Nav / Evaboot) export", "event": "event list"}
FLOW = {
    "zoominfo": "outbound-list-cleaner, steps 1–6",
    "linkedin": "linkedin-list-screening (multiple jobs → companies → contacts → title/company cleaning), "
                "then outbound-list-cleaner steps 1–2, ZoomInfo pull, source priority, consistency, prune, "
                "steps 1–2 again, then steps 3–6",
    "event": "event-list-intake (people already named) — company-only event lists aren't built yet",
}


def headers(path):
    p = str(path).lower()
    if p.endswith((".xlsx", ".xlsm")):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
        return [str(h).strip() for h in next(ws.iter_rows(values_only=True)) if h is not None]
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [h.strip() for h in next(csv.reader(f))]


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


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = []
    for f in sys.argv[1:]:
        cols = headers(f)
        best, hits = detect(cols)
        out.append({"file": Path(f).name, "guess": LABEL.get(best, "unknown — ask the user"),
                    "type": best, "evidence": {LABEL[t]: h for t, h in hits.items() if h},
                    "next": FLOW.get(best, "ask the user what kind of list this is"), "columns": len(cols)})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
