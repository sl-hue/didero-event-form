"""Build the flashcard review page from screening.csv.

  build   Writes <run_dir>/cards.json and <run_dir>/review.html — a single,
          self-contained page (no internet needed) that shows one contact per
          card with the title / company / geography verdicts and Claude's
          recommendation. The user answers Keep / Exclude / Back (buttons or
          keys Y, N, ←). At the end the page shows a short code to paste back
          into the chat; `screen.py apply-decisions --code …` applies it.

The page holds personal data: it stays on the user's device (shown in the
Cowork/Claude Code window) and is never published.
"""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path


def build(args):
    run = Path(args.run_dir)
    with open(run / "screening.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    li_cols = ["LinkedIn Contact Profile URL", "Profile URL", "LinkedIn URL", "Person Linkedin Url", "linkedinUrl"]
    cards = []
    for n, r in enumerate(rows, 1):
        cards.append({
            "n": n, "row_id": r["Row ID"], "name": r["Contact"], "title": r["Title"], "company": r["Company"],
            "contact_country": r["Contact Country"], "company_country": r["Company Country"],
            "linkedin": next((r[c] for c in li_cols if r.get(c)), ""),
            "verdicts": [
                {"label": "Title", "fit": r.get("Title Fit") or "unclear", "reason": r.get("Title Reason", "")},
                {"label": "Company", "fit": r.get("Company Fit") or "unclear",
                 "reason": r.get("Company Reason") or "not researched yet"},
                {"label": "Geography", "fit": r.get("Geo Fit") or "unclear", "reason": r.get("Geo Reason", "")},
            ],
            "recommendation": r.get("Recommendation") or "review",
            "decision": r.get("Decision", ""),
        })
    (run / "cards.json").write_text(json.dumps(cards, indent=1, ensure_ascii=False))
    review_id = hashlib.sha1(json.dumps([c["row_id"] for c in cards]).encode()).hexdigest()[:10]
    data = json.dumps(cards, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__TITLE__", html.escape(args.title or "List review")) \
                   .replace("__REVIEW_ID__", review_id).replace("__CARDS__", data)
    (run / "review.html").write_text(page, encoding="utf-8")
    counts = {k: sum(1 for c in cards if c["recommendation"] == k) for k in ("keep", "review", "exclude")}
    print(f"review.html: {len(cards)} cards ({counts['keep']} recommended keep, {counts['review']} to review, "
          f"{counts['exclude']} recommended exclude)")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1b18;--mut:#6f6a62;--line:#e4e1da;--fit:#1f7a4d;--fitbg:#e3f3ea;
--unc:#8a5a00;--uncbg:#fbf0d9;--no:#b3261e;--nobg:#fbe4e2;--acc:#2f5bd3;--shadow:0 6px 24px rgba(0,0,0,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161513;--card:#22201d;--fg:#f1eee8;--mut:#a39d93;
--line:#3a3631;--fit:#6fd3a0;--fitbg:#163527;--unc:#f0c46a;--uncbg:#3a2e14;--no:#ff8a80;--nobg:#3d1a17;--acc:#8fb0ff;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:640px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:18px;margin:0 0 4px}.mut{color:var(--mut)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:14px 0 18px}.bar i{display:block;height:100%;background:var(--acc);width:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:var(--shadow)}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}.num{color:var(--mut);font-size:13px;white-space:nowrap}
.name{font-size:22px;font-weight:650;margin:2px 0}.name a{color:inherit}
.title{font-size:16px}.co{margin-top:6px}.loc{font-size:13px;color:var(--mut);margin-top:2px}
.vs{margin:16px 0 4px;display:grid;gap:8px}
.v{display:grid;grid-template-columns:96px 1fr;gap:10px;align-items:start;padding:8px 10px;border-radius:9px}
.v b{font-size:12px;letter-spacing:.02em;text-transform:uppercase}.v span{font-size:14px}
.fit{background:var(--fitbg)}.fit b{color:var(--fit)}.unclear{background:var(--uncbg)}.unclear b{color:var(--unc)}
.no{background:var(--nobg)}.no b{color:var(--no)}
.rec{margin-top:12px;font-size:14px}.rec strong{text-transform:capitalize}
.cur{margin-top:6px;font-size:13px;color:var(--mut)}
.btns{display:grid;grid-template-columns:1fr 1.3fr 1.3fr;gap:10px;margin-top:16px}
button{font:inherit;font-weight:600;border-radius:10px;border:1px solid var(--line);padding:12px 10px;cursor:pointer;background:var(--card);color:var(--fg)}
button.k{background:var(--fit);border-color:var(--fit);color:#fff}button.x{background:var(--no);border-color:var(--no);color:#fff}
button:disabled{opacity:.4;cursor:default}button.link{border:0;background:none;color:var(--acc);padding:6px 0;font-weight:500}
.keys{font-size:12px;color:var(--mut);text-align:center;margin-top:10px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.stat b{display:block;font-size:20px}
textarea{width:100%;font:13px ui-monospace,Menlo,monospace;padding:10px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--fg);min-height:70px}
ul{padding-left:18px}li{margin:3px 0}.choice{display:grid;gap:10px;margin-top:14px}
</style></head><body><div class="wrap" id="app"></div>
<script>
const CARDS = __CARDS__;
const KEY = "ls-review-__REVIEW_ID__";
let state = {mode: null, i: 0, d: {}};
try { const s = JSON.parse(localStorage.getItem(KEY)); if (s && s.d) state = s; } catch (e) {}
CARDS.forEach(c => { if (c.decision && !state.d[c.n]) state.d[c.n] = c.decision; });
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} };
const esc = s => String(s ?? "").replace(/[&<>"]/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
const deck = () => state.mode === "flagged" ? CARDS.filter(c => c.recommendation !== "keep") : CARDS;
const app = document.getElementById("app");

function start() {
  const n = k => CARDS.filter(c => c.recommendation === k).length;
  app.innerHTML = `<h1>__TITLE__</h1><div class="mut">${CARDS.length} contacts to screen. For each card, keep or exclude the contact.</div>
  <div class="stats"><div class="stat"><b>${n("keep")}</b>recommended keep</div><div class="stat"><b>${n("review")}</b>need a look</div>
  <div class="stat"><b>${n("exclude")}</b>recommended exclude</div></div>
  <div class="choice"><button class="k" id="all">Review all ${CARDS.length} cards</button>
  <button id="flag">Review only the ${n("review") + n("exclude")} that need a look or would be excluded<br><span class="mut" style="font-weight:400">the ${n("keep")} clear passes are kept</span></button></div>`;
  document.getElementById("all").onclick = () => { state.mode = "all"; state.i = 0; save(); card(); };
  document.getElementById("flag").onclick = () => { state.mode = "flagged"; state.i = 0; save(); card(); };
}

function card() {
  const D = deck();
  if (state.i >= D.length) return done();
  const c = D[state.i], pct = Math.round(100 * state.i / D.length), cur = state.d[c.n];
  const name = c.linkedin ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">${esc(c.name)}</a>` : esc(c.name);
  app.innerHTML = `<div class="top"><h1>__TITLE__</h1><span class="num">${state.i + 1} / ${D.length}</span></div>
  <div class="bar"><i style="width:${pct}%"></i></div>
  <div class="card"><div class="num">#${c.n}</div><div class="name">${name}</div>
  <div class="title">${esc(c.title) || '<span class="mut">no title</span>'}</div>
  <div class="co"><strong>${esc(c.company)}</strong></div>
  <div class="loc">Contact: ${esc(c.contact_country) || "unknown"} · Company: ${esc(c.company_country) || "unknown"}</div>
  <div class="vs">${c.verdicts.map(v => `<div class="v ${esc(v.fit)}"><b>${esc(v.label)} · ${v.fit === "no" ? "not a fit" : esc(v.fit)}</b><span>${esc(v.reason)}</span></div>`).join("")}</div>
  <div class="rec">Claude recommends: <strong>${esc(c.recommendation)}</strong></div>
  ${cur ? `<div class="cur">Your answer so far: ${esc(cur)}</div>` : ""}
  <div class="btns"><button id="b" ${state.i === 0 ? "disabled" : ""}>← Back</button>
  <button class="x" id="x">✗ Exclude</button><button class="k" id="k">✓ Keep</button></div>
  <div class="keys">Keys: Y keep · N exclude · ← back</div></div>
  <button class="link" id="home">Start over / change mode</button>`;
  document.getElementById("k").onclick = () => answer(c, "keep");
  document.getElementById("x").onclick = () => answer(c, "exclude");
  document.getElementById("b").onclick = back;
  document.getElementById("home").onclick = () => { state.mode = null; save(); start(); };
}
function answer(c, v) { state.d[c.n] = v; state.i++; save(); card(); }
function back() { if (state.i > 0) { state.i--; save(); card(); } }

function finalDecisions() {
  const out = {};
  CARDS.forEach(c => {
    if (state.d[c.n]) out[c.n] = state.d[c.n];
    else if (state.mode === "flagged" && c.recommendation === "keep") out[c.n] = "keep";
  });
  return out;
}
function done() {
  const f = finalDecisions(), X = [], K = [];
  Object.entries(f).forEach(([n, v]) => (v === "exclude" ? X : K).push(+n));
  X.sort((a, b) => a - b); K.sort((a, b) => a - b);
  const ranges = a => { const out = []; for (let i = 0; i < a.length; i++) { let j = i;
      while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++; out.push(j > i ? `${a[i]}-${a[j]}` : `${a[i]}`); i = j; }
    return out.join(","); };
  const code = `LS1;${CARDS.length};X:${ranges(X)};K:${ranges(K)}`;
  const open = CARDS.length - X.length - K.length;
  const ex = CARDS.filter(c => f[c.n] === "exclude");
  app.innerHTML = `<h1>Review finished</h1>
  <div class="stats"><div class="stat"><b>${K.length}</b>keep</div><div class="stat"><b>${X.length}</b>exclude</div><div class="stat"><b>${open}</b>not answered</div></div>
  <p><strong>Copy this code and paste it into the chat</strong> so Claude can apply your answers:</p>
  <textarea id="code" readonly>${code}</textarea>
  <div class="choice"><button class="k" id="copy">Copy code</button><button id="dl">Download answers (.json)</button></div>
  ${ex.length ? `<p class="mut" style="margin-top:18px">Excluded (${ex.length}):</p><ul>${ex.map(c => `<li>#${c.n} ${esc(c.name)} — ${esc(c.title)}, ${esc(c.company)}</li>`).join("")}</ul>` : ""}
  <button class="link" id="again">← Go back to the cards</button>`;
  const ta = document.getElementById("code");
  document.getElementById("copy").onclick = async () => {
    try { await navigator.clipboard.writeText(code); document.getElementById("copy").textContent = "Copied ✓"; }
    catch (e) { ta.focus(); ta.select(); document.getElementById("copy").textContent = "Select-all done — press Ctrl/Cmd+C"; }
  };
  document.getElementById("dl").onclick = () => {
    const blob = new Blob([JSON.stringify({code, decisions: f}, null, 1)], {type: "application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "screening_answers.json"; a.click();
  };
  document.getElementById("again").onclick = () => { state.i = Math.max(0, deck().length - 1); save(); card(); };
}
document.addEventListener("keydown", e => {
  if (!state.mode || e.target.tagName === "TEXTAREA") return;
  const D = deck(); if (state.i >= D.length) return;
  if (e.key === "y" || e.key === "Y") answer(D[state.i], "keep");
  else if (e.key === "n" || e.key === "N") answer(D[state.i], "exclude");
  else if (e.key === "ArrowLeft" || e.key === "b") back();
});
state.mode ? card() : start();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--title", help="page title, e.g. the list name")
    p.set_defaults(func=build)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
