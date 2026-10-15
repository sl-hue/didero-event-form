"""v2 start: everything the run needs, settled before any work — then the run is independent.

  start  --file <list> [--file <second file>] --run-dir <run_dir>
         Claude's own read of the file: list type and enrichment path (from the columns and
         filled values), contacts, companies and the maximum ZoomInfo credits. Prints what was
         determined and the start questions (asked together, in one multiple-choice call).
  set    --run-dir <run_dir> [--event-name "<event>"] [--lead-source '<answer>']
         values Claude works out later (the event name; the lead source detail from the file)
  save   --run-dir <run_dir> --answers '<json>'
         {"end_state": "upload" | "upload+bdr",
          "countries": "us_ca" | "na_english" | ["Country", ...],
          "bdr_pool": ["Noah", ...],               (upload+bdr only)
          "split": "even" | "<the user's own rule>", (upload+bdr only)
          "credits_ok": true | false,               (asked only when the path uses ZoomInfo)
          "lead_source": "unknown" | "Source / Channel / Detail" | {"source","channel","detail"}
                         (leadsource.py: the team's sheet; detail may be left for Claude to fill)
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
              "contacts": "named-contacts path (HubSpot + web for companies → screening → ZoomInfo enrich "
                          "for contacts and companies, 10 per call)"}
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
    credits = {"zoominfo": 0, "linkedin": n_contacts + n_companies, "contacts": n_contacts + n_companies}[path]
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
    eventish = kind == "event-contacts" or draft["event_column"] or any(
        w in Path(main["file"]).name.lower() for w in ("event", "attendee", "conference", "summit", "expo", "dinner"))
    ls_opts = ([{"label": "Events — Conference", "description": "Detail = the event, written 'Name - YYYY - City, ST' "
                 "(e.g. EDGE - 2026 - Nashville, TN). Claude fills it from the file / event name."},
                {"label": "Events — Dinner", "description": "Detail = 'Host Dinner - YYYY - City, ST' (e.g. ASCM Dinner - "
                 "2026 - Denver, CO). Claude fills it from the file / event name."}] if eventish else []) + [
        {"label": "Outbound — Manual - BDR Led", "description": "Detail = each contact's BDR first name (e.g. Noah); "
         "needs BDR owners, or type one name under Other."},
        {"label": "I don't know", "description": "Lead Source and Lead Source Detail are left out of the upload "
         "(nothing overwritten in HubSpot)."}]
    if not eventish:
        ls_opts.insert(0, {"label": "Events — Conference", "description": "Detail = 'Name - YYYY - City, ST' (e.g. EDGE - "
                           "2026 - Nashville, TN); type the event under Other if Claude can't tell it from the file."})
    lead_q = {"header": "Lead source", "multiSelect": False,
              "question": "What's the lead source for these contacts? (the lead source sheet: Lead Source → Channel → "
                          "Detail). Something else: type 'Source / Channel / Detail' under Other, e.g. 'Outbound / "
                          "Automated AE Campaign / Target Accounts - Jory'.",
              "options": ls_opts[:4]}
    if credits:
        qs.append({"header": "Credits", "multiSelect": False,
                   "question": f"Approve up to {credits} ZoomInfo Bulk Credits for this list? (one per contact"
                               + (" and per company" if path in ("linkedin", "contacts") else "") +
                               "; anyone enriched in the last year is free, so the real number is lower)",
                   "options": [{"label": f"Approve up to {credits}", "description": "The run never stops for credits."},
                               {"label": "Don't use ZoomInfo", "description": "Skip the ZoomInfo steps; the list "
                                "keeps its own data."}]})
    qs.append(lead_q)
    calls = [qs[i:i + 4] for i in range(0, len(qs), 4)]  # AskUserQuestion takes at most 4 questions per call
    if len(calls) == 1:
        print("\nASK ALL OF THESE IN ONE multiple-choice call (AskUserQuestion), nothing else:")
        print(json.dumps(qs, indent=1, ensure_ascii=False))
    else:
        print(f"\nASK THESE IN {len(calls)} multiple-choice calls (AskUserQuestion) RIGHT AFTER EACH OTHER — no work and "
              "no other message in between (the tool takes at most 4 questions per call):")
        for i, c in enumerate(calls, 1):
            print(f"--- call {i} ---")
            print(json.dumps(c, indent=1, ensure_ascii=False))
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
    ls = lead_source_of(a.get("lead_source", "unknown"), end == "upload+bdr")
    setup = dict(draft, end_state=end, countries=countries, bdr_pool=pool if end == "upload+bdr" else [],
                 split=split if end == "upload+bdr" else "", credit_cap=draft["max_credits"] if credits_ok else 0,
                 use_zoominfo=credits_ok, event_name=a.get("event_name", ""), lead_source=ls)
    (run / SETUP).write_text(json.dumps(setup, indent=1, ensure_ascii=False))
    print(f"saved {run / SETUP}")
    print(f"- path: {PATH_LABEL[setup['path']]}")
    print(f"- countries: {', '.join(countries)} (companies by HQ or presence, then contacts)")
    print(f"- end state: {'upload files + BDR owners (' + ', '.join(pool) + '; split: ' + split + ')' if end == 'upload+bdr' else 'upload files only'}")
    print(f"- lead source: {lead_source_text(ls)}")
    if draft["max_credits"]:
        print(f"- ZoomInfo: {'up to ' + str(draft['max_credits']) + ' credits approved' if credits_ok else 'not used'}")
    print("- the run now goes on its own. It stops only where the user acts: the HubSpot import, building the "
          "segment, Clay, and fixing anything in HubSpot the checks find.")
    print(f"Next: progress.py start --run-dir {args.run_dir}")


def lead_source_of(answer, bdr):
    """The start answer -> run_setup lead_source. Events with no detail yet -> detail left for Claude to fill
    from the file (setup.py set --lead-source); Manual - BDR Led with BDR owners -> each contact's own BDR."""
    import leadsource
    if isinstance(answer, str):
        a = answer.replace("—", "/").replace(" – ", " / ")
        if a.strip().lower() in ("i don't know", "unknown", ""):
            return {"unknown": True}
        answer = a
    try:
        return leadsource.normalize(answer)
    except ValueError as e:
        if "needs a detail" not in str(e):
            raise SystemExit(f"lead source: {e}")
    parts = answer if isinstance(answer, dict) else dict(zip(("source", "channel"), [x.strip() for x in answer.split("/")]))
    ch = parts.get("channel", "")
    if bdr and ch.lower().startswith("manual - bdr"):
        return leadsource.normalize(dict(parts, detail="per owner"))
    src = leadsource.normalize(dict(parts, detail="Placeholder - 2000 - City, ST"))
    return dict(src, detail="", detail_pending=True)


def lead_source_text(ls):
    if not ls or ls.get("unknown"):
        return "not known — left out of the upload"
    d = "each contact's own owner" if ls["detail"] == "per owner" else (ls["detail"] or "TO FILL from the file "
                                                                       "(setup.py set --lead-source)")
    return f"{ls['source']} / {ls['channel']} / {d}"


def set_(args):
    """Fill values Claude determines later (the event name, the lead source detail) without re-asking anything."""
    import leadsource
    run = Path(args.run_dir)
    st = json.loads((run / SETUP).read_text())
    if args.event_name:
        st["event_name"] = args.event_name
        print(f"event name: {args.event_name}")
    if args.lead_source:
        try:
            a = json.loads(args.lead_source)
        except ValueError:
            a = args.lead_source
        try:
            st["lead_source"] = leadsource.normalize(a)
        except ValueError as e:
            raise SystemExit(f"lead source: {e}")
        print(f"lead source: {lead_source_text(st['lead_source'])}")
    (run / SETUP).write_text(json.dumps(st, indent=1, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start"); p.add_argument("--file", action="append", required=True)
    p.add_argument("--run-dir", required=True); p.set_defaults(func=start)
    p = sub.add_parser("save"); p.add_argument("--run-dir", required=True); p.add_argument("--answers", required=True)
    p.set_defaults(func=save)
    p = sub.add_parser("set"); p.add_argument("--run-dir", required=True); p.add_argument("--event-name")
    p.add_argument("--lead-source")
    p.set_defaults(func=set_)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
