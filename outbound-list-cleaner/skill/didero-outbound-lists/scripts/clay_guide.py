"""Step 5 — the Clay walkthrough, printed from config.json so the links and steps are never left out.

  python3 clay_guide.py --run-dir <run_dir> --list-type zoominfo|linkedin|event-contacts|event-companies
                        [--segment "<HubSpot segment name or link>"]

Prints the checklist (both template links, how to copy and name the workbook,
which tabs to run, the button order) and saves it as <run_dir>/CLAY_STEPS.md.
Claude pastes it in the chat as it is, then walks the user through it one tab
at a time.
"""
import argparse
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--list-type", required=True,
                    choices=["zoominfo", "linkedin", "contacts"])
    ap.add_argument("--segment", default="", help="the HubSpot segment built in step 4")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())
    wb = cfg["clay_workbooks"]
    seg = args.segment or "the segment from step 4"
    name = f"{Path(args.run_dir).name}_{datetime.date.today():%Y-%m-%d}"
    # ZoomInfo lists were built in ZoomInfo: its tab adds nothing. Everything else runs it first.
    zi_tab = args.list_type != "zoominfo"
    tabs = []
    if zi_tab:
        tabs.append(("ZoomInfo", ["Import the segment (first column)", "Enrich Contact", "Update Object"]))
    tabs.append(("PDL", ["Import the segment again (first column)", "Verify Email", "Work Email", "Enrich Person",
                         "LinkedIn URL", "Update Object"]))
    tabs.append(("Import Objects from HubSpot", ["Import Object", "Mobile Phone", "Update Object"]))
    out = [f"# Clay enrichment — {Path(args.run_dir).name}", "",
           "Clay writes the results back to HubSpot itself: no files to import or export.", "",
           "## 1. Open a copy of the right template", ""]
    for key, label in (("americas_global", "Americas / global contacts"), ("europe", "European contacts")):
        out.append(f"- **{label}**: {wb[key]['url']} — {wb[key]['use_for']}")
    out += ["",
            "Pick the template that fits most of the list's contacts. **Duplicate** it (never run buttons in the "
            f"template itself) and rename the copy `{name}` (or a name you prefer: name_segment_date).", "",
            "## 2. Import the segment into a tab", "",
            f"In the tab's first column: **Import objects → Contacts → {seg}**, schedule **Manual / one-time "
            "import only** (so it doesn't keep updating in the background).", "",
            "## 3. Run the tabs in this order, one button at a time", "",
            "Wait for each column to finish before clicking the next one. Each run spends Clay credits.", ""]
    for i, (tab, buttons) in enumerate(tabs, 1):
        out.append(f"**Tab {i} — {tab}**")
        out += [f"{j}. {b}" for j, b in enumerate(buttons, 1)]
        out.append("")
    if not zi_tab:
        out += ["(Skip the ZoomInfo tab: this list was built in ZoomInfo.)", ""]
    out += ["## 4. When every tab's Update Object has run", "",
            "Tell Claude \"Clay is done\". Contacts Clay couldn't improve are fine as they are. Then step 6 "
            "(BDR assignment) starts."]
    text = "\n".join(out)
    (Path(args.run_dir) / "CLAY_STEPS.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"\n(saved as {Path(args.run_dir) / 'CLAY_STEPS.md'} — paste the steps above in the chat as they are)")


if __name__ == "__main__":
    main()
