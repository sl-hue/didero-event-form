"""v2 start: everything the run needs, settled before any work — then the run is independent.

  start  --file <list> [--file <second file>] --run-dir <run_dir>
         Claude's own read of the file: list type and enrichment path (from the columns and
         filled values), contacts, companies and the maximum ZoomInfo credits. Prints what was
         determined and the start questions (asked together, in one multiple-choice call).
  set    --run-dir <run_dir> --event-name "<event>"   (determined from the file; not a question)
  save   --run-dir <run_dir> --answers '<json>'
         {"end_state": "upload" | "upload+bdr",
          "countries": "us_ca" | "na_english" | ["Country", ...],
          "bdr_pool": ["Noah", ...],               (upload+bdr only)
          "split": "even" | "<the user's own rule>", (upload+bdr only)
          "credits_ok": true | false,               (asked only when the path uses ZoomInfo)
          "event_name": "<event name>"}            (event lists, from the file / sources — not asked)
         Writes run_setup.json, which the later steps read (countries, credit cap, BDRs), and
         prints the plan: which steps run and where the run will stop for the user.

Paths: zoominfo (ZoomInfo export: no ZoomInfo calls), linkedin (Sales Nav / Evaboot: screening,
ZoomInfo pull for contacts + companies), contacts (names + companies, no ZoomInfo/LinkedIn data,
e.g. event attendees: HubSpot + web for companies, ZoomInfo search -> enrich picked people).
Company-only lists (no names) belong to didero-contact-sourcing.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from detect_list_type import COMPANY_COLS, LABEL, NAME_COLS, classify, table  # noqa: E402

CONFIG = json.loads((HERE.parent / "config.json").read_text())
PRESETS = CONFIG.get("country_presets", {})
PATH_OF = {"zoominfo": "zoominfo", "linkedin": "linkedin", "event-contacts": "contacts"}
PATH_LABEL = {"zoominfo": "ZoomInfo export path (steps 1–6, no ZoomInfo calls)",
              "linkedin": "LinkedIn path (screening → ZoomInfo pull for contacts and companies → merge)",
              "contacts": "named-contacts path (HubSpot + web for companies → screening → ZoomInfo direct "
                          "enrich, 10 people per call)"}
SETUP = "run_setup.json"


def load_setup(run_dir):
    """run_setup.json from the run folder or one of its parents (step folders sit inside the run)."""
    d = Path(run_dir).resolve()
    for p in [d] + list(d.parents)[:3]:
        if (p / SETUP).exists():
            return json.loads((p / SETUP).read_text())
    return {}


def countries_of(value):
    if isinstance(value, str) and value in PRESETS:
        return PRESETS[value]
    if isinstance(value, str):
        value = [c.strip() for c in value.replace(";", ",").split(",")]
    return [c for c in value if c]


def start(args):
    run = Path(args.run_dir)
    run.mkdir(parents=True, exist_ok=True)
    files = []
    for f in args.file:
        cols, rows = table(f, limit=100000)
        kind, conf, evidence = classify(cols, rows)
        files.append({"file": str(f), "kind": kind, "confidence": conf, "evidence": evidence,
                      "cols": cols, "rows": rows})
    main = files[0]
    kind = main["kind"]
    if kind.startswith("event-companies"):
        print(f"{Path(main['file']).name}: {LABEL[kind]}. This list names companies but no people: it belongs to "
              "the didero-contact-sourcing skill (it finds the contacts, then hands a contact file back here). "
              "Tell the user and switch skills.")
        return
    path = PATH_OF.get(kind)
    why = main["evidence"]
    if not path:  # not a known export: decide from what the columns hold
        low = {c.lower(): c for c in main["cols"]}
        filled = lambda c: sum(1 for r in main["rows"] if (r.get(c) or "").strip()) >= max(1, len(main["rows"]) // 5)
        names = [low[c] for c in low if c in NAME_COLS and filled(low[c])]
        company = [low[c] for c in low if c in COMPANY_COLS]
        linkedin = [c for c in main["cols"] if "linkedin" in c.lower() and filled(c)]
        zi = [c for c in main["cols"] if c.lower().startswith("zoominfo") and filled(c)]
        if zi:
            path, why = "zoominfo", {"columns": zi}
        elif linkedin and names:
            path, why = "linkedin", {"columns": linkedin + names}
        elif names and company:
            path, why = "contacts", {"columns": names + company}
        else:
            print(f"{Path(main['file']).name}: no contact names and company columns found "
                  f"({', '.join(main['cols'][:15])}…). This is the one case to ask the user: which columns hold "
                  "the people and their companies, or whether it's a company-only list (didero-contact-sourcing).")
            return
    comp_col = next((c for c in main["cols"] if c.lower() in COMPANY_COLS), None)
    n_contacts = len(main["rows"])
    n_companies = len({(r.get(comp_col) or "").strip().lower() for r in main["rows"]} - {""}) if comp_col else 0
    credits = {"zoominfo": 0, "linkedin": n_contacts + n_companies, "contacts": n_contacts}[path]
    draft = {"file": main["file"], "other_files": [f["file"] for f in files[1:]], "detected": kind,
             "event_column": "Event Name" in main["cols"],
             "path": path, "evidence": why, "contacts": n_contacts, "companies": n_companies, "max_credits": credits}
    (run / "setup_draft.json").write_text(json.dumps(draft, indent=1))
    pool = [p if isinstance(p, str) else p.get("name", "") for p in CONFIG.get("bdr_pool", [])]
    print(f"DETERMINED (say this in one line, no question): {Path(main['file']).name} is a "
          f"{LABEL.get(kind, 'list with ' + ', '.join(why.get('columns', [])))} → {PATH_LABEL[path]}. "
          f"{n_contacts} contacts at {n_companies} companies. Evidence: {json.dumps(why)}")
    na = ", ".join(PRESETS.get("na_english", []))
    qs = [
        {"header": "End state", "multiSelect": False,
         "question": "What's the end state? Both give you a company CSV and a contact CSV for the HubSpot import.",
         "options": [
             {"label": "Upload files only", "description": "Clean company + contact CSVs, HubSpot record IDs filled."},
             {"label": "+ BDR owners, even split", "description": "Same CSVs plus Contact Owner / Company Owner "
              "columns. Even split by contacts, and all contacts of one account go to one BDR first."},
             {"label": "+ BDR owners, other split", "description": "Same CSVs with owner columns; describe the "
              "split you want under Other."}]},
        {"header": "Countries", "multiSelect": False,
         "question": "Which countries? Companies are kept if they're headquartered or present there; then only "
                     "contacts in these countries at those companies.",
         "options": [
             {"label": "US + Canada", "description": ", ".join(PRESETS.get("us_ca", []))},
             {"label": "NA + English-speaking", "description": na},
             {"label": "Other countries", "description": "Type every country under Other."}]},
        {"header": "BDRs", "multiSelect": True,
         "question": "If assigning owners: who gets this list? (ignored for 'Upload files only')",
         "options": [{"label": p, "description": "BDR in the default pool"} for p in pool[:3]] +
                    [{"label": "No assignment", "description": "Upload files only"}]},
    ]
    if credits:
        qs.append({"header": "Credits", "multiSelect": False,
                   "question": f"Approve up to {credits} ZoomInfo Bulk Credits for this list? (one per contact"
                               + (" and per company" if path == "linkedin" else "") +
                               "; anyone enriched in the last year is free, so the real number is lower)",
                   "options": [{"label": f"Approve up to {credits}", "description": "The run never stops for credits."},
                               {"label": "Don't use ZoomInfo", "description": "Skip the ZoomInfo steps; the list "
                                "keeps its own data."}]})
    print("\nASK ALL OF THESE IN ONE multiple-choice call (AskUserQuestion), nothing else:")
    print(json.dumps(qs, indent=1, ensure_ascii=False))
    print(f"\nThen: setup.py save --run-dir {args.run_dir} --answers '<json>' (see --help for the keys).")


def save(args):
    run = Path(args.run_dir)
    draft = json.loads((run / "setup_draft.json").read_text())
    a = json.loads(args.answers)
    end = a.get("end_state", "upload")
    if end not in ("upload", "upload+bdr"):
        raise SystemExit("end_state must be 'upload' or 'upload+bdr'")
    countries = countries_of(a.get("countries") or "na_english")
    if not countries:
        raise SystemExit("no countries")
    pool, split = a.get("bdr_pool") or [], a.get("split") or "even"
    pool = [p for p in pool if p.lower() != "no assignment"]
    if end == "upload+bdr" and not pool:
        raise SystemExit("BDR owners chosen but no BDRs named — that answer is needed before starting")
    credits_ok = bool(a.get("credits_ok")) if draft["max_credits"] else False
    setup = dict(draft, end_state=end, countries=countries, bdr_pool=pool if end == "upload+bdr" else [],
                 split=split if end == "upload+bdr" else "", credit_cap=draft["max_credits"] if credits_ok else 0,
                 use_zoominfo=credits_ok, event_name=a.get("event_name", ""))
    (run / SETUP).write_text(json.dumps(setup, indent=1, ensure_ascii=False))
    print(f"saved {run / SETUP}")
    print(f"- path: {PATH_LABEL[setup['path']]}")
    print(f"- countries: {', '.join(countries)} (companies by HQ or presence, then contacts)")
    print(f"- end state: {'upload files + BDR owners (' + ', '.join(pool) + '; split: ' + split + ')' if end == 'upload+bdr' else 'upload files only'}")
    if draft["max_credits"]:
        print(f"- ZoomInfo: {'up to ' + str(draft['max_credits']) + ' credits approved' if credits_ok else 'not used'}")
    print("- the run now goes on its own. It stops only where the user acts: the HubSpot import, building the "
          "segment, Clay, and fixing anything in HubSpot the checks find.")
    print(f"Next: progress.py start --run-dir {args.run_dir}")


def set_(args):
    """Fill a value Claude determines later (the event name) without re-asking anything."""
    run = Path(args.run_dir)
    st = json.loads((run / SETUP).read_text())
    st["event_name"] = args.event_name
    (run / SETUP).write_text(json.dumps(st, indent=1, ensure_ascii=False))
    print(f"event name: {args.event_name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start"); p.add_argument("--file", action="append", required=True)
    p.add_argument("--run-dir", required=True); p.set_defaults(func=start)
    p = sub.add_parser("save"); p.add_argument("--run-dir", required=True); p.add_argument("--answers", required=True)
    p.set_defaults(func=save)
    p = sub.add_parser("set"); p.add_argument("--run-dir", required=True); p.add_argument("--event-name", required=True)
    p.set_defaults(func=set_)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
