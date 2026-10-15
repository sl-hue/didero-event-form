"""Lead source, as the team's lead source sheet categorizes it (config.json -> lead_sources).

  Lead Source  ->  Lead Channel  ->  Lead Source Detail
  Events          Dinner             ASCM Dinner - 2026 - Denver, CO
  Outbound        Manual - BDR Led   Noah

Asked at the start (setup.py). Only LEAD SOURCE and LEAD SOURCE DETAIL 1 go in the contact upload file —
the channel isn't in HubSpot yet, but it decides how the detail is written. The user doesn't know it ->
both columns are left out of the upload (nothing is overwritten in HubSpot).

  show                       the sheet: every source, its channels, the detail format and examples
  check --answer '<answer>'  normalizes an answer and prints the JSON setup.py save stores; exits non-zero
                             with what to fix when it doesn't fit the sheet.
     <answer>: "unknown" | "Source / Channel / Detail" | {"source": .., "channel": .., "detail": ..}
     detail "per owner" (Manual - BDR Led / Manual - AE Led with BDR assignment): each contact's own owner.
"""
import argparse
import json
import re
import sys
from pathlib import Path

CFG = Path(__file__).resolve().parent.parent / "config.json"
STATES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
          "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
          "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
          "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
          "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
          "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
          "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
          "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
          "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
          "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "ontario": "ON", "quebec": "QC",
          "british columbia": "BC", "alberta": "AB", "manitoba": "MB", "saskatchewan": "SK", "nova scotia": "NS",
          "new brunswick": "NB"}
EVENT = re.compile(r"^.+ - \d{4} - [^,]+, [^,]+$")
PER_OWNER = ("per owner", "per-owner", "each contact's owner", "each contact's bdr", "owner")


def sheet():
    return json.loads(CFG.read_text()).get("lead_sources", {})


def _find(name, options):
    n = re.sub(r"\s+", " ", (name or "").strip()).lower()
    return next((o for o in options if o.lower() == n), None) or next(
        (o for o in options if n and (n in o.lower() or o.lower() in n)), None)


def event_detail(detail):
    """'EDGE – 2026 – Nashville, Tennessee' -> 'EDGE - 2026 - Nashville, TN'."""
    d = re.sub(r"\s*[–—]\s*", " - ", detail.strip())
    d = re.sub(r"\s*-\s+(?=\d{4}\b)|(?<=\d{4})\s+-\s*", " - ", d)
    if "," in d:
        head, region = d.rsplit(",", 1)
        d = f"{head.strip()}, {STATES.get(region.strip().lower(), region.strip())}"
    return d


def normalize(answer):
    """-> {"unknown": True} | {"source", "channel", "detail"}; raises ValueError with what to fix."""
    tax = sheet().get("taxonomy", {})
    if isinstance(answer, str):
        a = answer.strip()
        if not a or a.lower() in ("unknown", "don't know", "dont know", "i don't know", "none", "no"):
            return {"unknown": True}
        parts = [x.strip() for x in a.split("/")]
        # "Partnerships / Referrals" contains a slash itself
        if len(parts) >= 2 and f"{parts[0]} / {parts[1]}".lower() == "partnerships / referrals":
            parts = ["Partnerships / Referrals"] + parts[2:]
        channels = {ch.lower() for chs in tax.values() for ch in chs}
        if parts[0].lower() in channels and parts[0].lower() not in {x.lower() for x in tax}:
            parts = [""] + parts  # "Manual - BDR Led / Noah": the source follows from the channel
        answer = dict(zip(("source", "channel", "detail"), parts + ["", "", ""]))
    if answer.get("unknown"):
        return {"unknown": True}
    channel_all = {ch: src for src, chs in tax.items() for ch in chs}
    src = _find(answer.get("source"), tax) if answer.get("source") else None
    ch = _find(answer.get("channel"), tax[src] if src else channel_all)
    if ch and not src:
        src = channel_all[ch]
    if not src:
        raise ValueError(f"lead source '{answer.get('source')}' isn't on the sheet: {', '.join(tax)}")
    if not ch:
        raise ValueError(f"lead channel '{answer.get('channel')}' isn't under {src}: {', '.join(tax[src])}")
    spec = tax[src][ch]
    detail = (answer.get("detail") or "").strip()
    if not detail:
        raise ValueError(f"{src} / {ch} needs a detail: {spec['detail']} (e.g. {', '.join(spec['examples'][:2]) or '—'})")
    if detail.lower() in PER_OWNER:
        if spec["kind"] != "person":
            raise ValueError(f"'per owner' only fits a Manual channel, not {ch}")
        detail = "per owner"
    elif spec["kind"] == "event" or (spec["kind"] == "campaign" and re.search(r"\b(19|20)\d{2}\b", detail)):
        detail = event_detail(detail)
        if spec["kind"] == "event" and not EVENT.match(detail):
            raise ValueError(f"write the {ch.lower()} as {spec['detail']} (e.g. {spec['examples'][0]}), not '{detail}'")
    elif spec["kind"] == "person":
        detail = detail.split()[0].capitalize()  # first name only
    return {"source": src, "channel": ch, "detail": detail}


def detail_for(row, ls):
    """The Lead Source Detail for one contact row (per owner -> the owner's first name)."""
    if ls.get("detail") != "per owner":
        return ls.get("detail", "")
    name = (row.get("Contact Owner Name") or "").strip()
    return name.split()[0] if name else ""


def hubspot_option(ls, options):
    """The sheet's source as one of HubSpot's current LEAD SOURCE options: exact when HubSpot has it, else the
    fallback in config (until HubSpot is updated)."""
    labels = {str(o).lower(): o for o in options}
    if ls["source"].lower() in labels:
        return labels[ls["source"].lower()]
    fb = sheet().get("hubspot_fallback", {})
    alt = fb.get(f"{ls['source']}|{ls['channel']}") or fb.get(ls["source"], "")
    return labels.get(alt.lower(), alt)


def show(_args):
    for src, chs in sheet().get("taxonomy", {}).items():
        print(src)
        for ch, spec in chs.items():
            ex = "; ".join(spec["examples"][:4])
            print(f"  {ch}: {spec['detail']}" + (f"  e.g. {ex}" if ex else ""))


def check(args):
    try:
        a = json.loads(args.answer)
    except ValueError:
        a = args.answer
    try:
        print(json.dumps(normalize(a), ensure_ascii=False))
    except ValueError as e:
        sys.exit(f"doesn't fit the lead source sheet: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").set_defaults(func=show)
    p = sub.add_parser("check"); p.add_argument("--answer", required=True); p.set_defaults(func=check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
