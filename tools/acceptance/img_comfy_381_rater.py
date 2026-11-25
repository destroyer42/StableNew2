"""IMG-COMFY-381: a self-contained blind A/B rating page for the Forge-vs-ComfyUI comparison.

``write_rater`` turns a harness ``review/`` directory (``review.csv`` plus ``images/*_A.png`` and ``*_B.png``) into one
``rater.html`` beside it. Open that file straight from disk in a browser: no server, no script or font from anywhere else,
nothing leaves the machine. Each pair shows A and B side by side, with 1-5 scores for fidelity to the prompt, detail and
artifacts, a preference (A, B or tie) and a note. Progress is autosaved in this browser, and **Download review.csv**
writes the same columns the harness produced, ready to be unblinded against ``review_key.json``.

The page never reads or embeds the A/B key, and the images are the harness's metadata-free copies, so nothing on the page
says which backend made which image. The prompt text, which both arms share, comes from ``plan.json`` when it is found.

    python -m tools.acceptance.img_comfy_381_rater <run dir>/review [--plan <run dir>/plan.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import sys
from pathlib import Path
from typing import Any

RATER_NAME = "rater.html"
SCORE_FIELDS = ("fidelity", "detail", "artifacts")
SCORE_LABELS = {
    "fidelity": ("Fidelity to the prompt", "1 = ignores it, 5 = matches it fully"),
    "detail": ("Detail", "1 = flat or mushy, 5 = rich and crisp"),
    "artifacts": ("Artifacts", "1 = severe (hands, faces, tearing), 5 = none"),
}
PREFERENCES = ("A", "B", "tie")


class RaterError(RuntimeError):
    """The review directory cannot be turned into a rating page."""


def _read_rows(review: Path) -> tuple[list[str], list[dict[str, str]]]:
    path = review / "review.csv"
    if not path.is_file():
        raise RaterError(f"{path} not found; point at the harness's review directory")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    needed = {"pair_id", "image_a", "image_b", "preference_a_b_tie"}
    if not needed <= set(header):
        raise RaterError(f"{path} lacks the columns {sorted(needed - set(header))}")
    if not rows:
        raise RaterError(f"{path} has no pairs to rate")
    return header, rows


def _prompts(plan: Path | None) -> dict[str, str]:
    if plan is None or not plan.is_file():
        return {}
    try:
        pairs = json.loads(plan.read_text(encoding="utf-8")).get("pairs", [])
        return {str(p["pair_id"]): str(p.get("prompt", "")) for p in pairs if "pair_id" in p}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _content_key(review: Path, rows: list[dict[str, str]]) -> str:
    """Browser-storage key bound to the actual images, so another run with the same pair ids never inherits scores."""

    digest = hashlib.sha256()
    for row in rows:
        digest.update(row["pair_id"].encode("utf-8"))
        for column in ("image_a", "image_b"):
            digest.update((review / row[column].replace("\\", "/")).read_bytes())
    return digest.hexdigest()[:20]


def _page_data(
    review: Path, header: list[str], rows: list[dict[str, str]], plan: Path | None
) -> dict[str, Any]:
    prompts = _prompts(plan)
    for row in rows:
        for column in ("image_a", "image_b"):
            image = review / row[column].replace("\\", "/")
            if not image.is_file():
                raise RaterError(f"{image} is missing for pair {row['pair_id']}")
    return {
        "header": header,
        "rows": rows,
        "prompts": prompts,
        "scores": list(SCORE_FIELDS),
        "labels": {k: list(v) for k, v in SCORE_LABELS.items()},
        "preferences": list(PREFERENCES),
        "storage_key": "img-comfy-381-rater:" + _content_key(review, rows),
    }


def render(data: dict[str, Any]) -> str:
    # ASCII-only JSON with ``<`` escaped cannot end the script block early or open an HTML comment inside it.
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    return _TEMPLATE.replace("__TITLE__", html.escape("A/B image rating")).replace(
        "__DATA__", payload
    )


def write_rater(
    review: Path | str, plan: Path | str | None = None, *, overwrite: bool = False
) -> Path:
    review = Path(review).resolve()
    if plan is None:
        candidate = review.parent / "plan.json"
        plan = candidate if candidate.is_file() else None
    header, rows = _read_rows(review)
    target = review / RATER_NAME
    if target.exists() and not overwrite:
        raise RaterError(
            f"{target} already exists (pass --overwrite to replace the page; ratings live in the browser)"
        )
    page = render(_page_data(review, header, rows, Path(plan) if plan else None))
    target.write_text(page, encoding="utf-8", newline="\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "review", type=Path, help="the harness's review/ directory (review.csv and images/)"
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="plan.json for the prompt text (default: ../plan.json)",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace an existing rater.html")
    args = parser.parse_args(argv)
    try:
        target = write_rater(args.review, args.plan, overwrite=args.overwrite)
    except RaterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(target)
    return 0


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f6f4;--fg:#1d1d1b;--mut:#66665f;--card:#fff;--line:#d8d8d2;--acc:#1b5fd1;--ok:#1a7f4b}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--mut:#9a9a92;--card:#212120;--line:#3a3a37;--acc:#6aa3ff;--ok:#4fc58a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
header h1{font-size:16px;margin:0}
.bar{flex:1 1 160px;min-width:120px;height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--ok);width:0}
button,select{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:5px 11px;cursor:pointer}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff}
button:disabled{opacity:.45;cursor:default}
main{max-width:1500px;margin:0 auto;padding:14px 16px 60px}
.prompt{color:var(--mut);margin:0 0 10px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.cell{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}
.cell h2{margin:0 0 8px;font-size:15px}
.cell img{display:block;width:100%;height:auto;max-height:68vh;object-fit:contain;cursor:zoom-in;background:#0002;border-radius:4px}
.cell img.full{max-height:none;cursor:zoom-out}
.scores{margin-top:10px;display:grid;gap:8px}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.row .lab{min-width:150px}
.row .lab small{display:block;color:var(--mut);font-size:12px}
.chips{display:flex;gap:4px}
.chips label{display:inline-block}
.chips input{position:absolute;opacity:0;pointer-events:none}
.chips span{display:inline-block;min-width:34px;text-align:center;padding:5px 0;border:1px solid var(--line);border-radius:6px;cursor:pointer;background:var(--card)}
.chips input:checked+span{background:var(--acc);border-color:var(--acc);color:#fff}
.chips input:focus-visible+span{outline:2px solid var(--acc);outline-offset:2px}
.pref{margin-top:14px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}
textarea{width:100%;min-height:54px;margin-top:8px;font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px}
.nav{display:flex;gap:8px;margin-top:14px;align-items:center;flex-wrap:wrap}
.hint{color:var(--mut);font-size:13px;margin-top:12px}
.flick{position:relative}
.pair.single{grid-template-columns:1fr}
.status{font-size:13px;color:var(--mut)}
.done{color:var(--ok)}
@media (max-width:760px){.pair{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>A/B image rating</h1>
  <div class="bar" aria-hidden="true"><i id="barfill"></i></div>
  <span class="status" id="progress"></span>
  <select id="jump" aria-label="Jump to pair"></select>
  <button id="download" class="primary" type="button">Download review.csv</button>
</header>
<main>
  <p class="prompt" id="prompt"></p>
  <div class="pair" id="pair"></div>
  <div class="pref">
    <div class="row"><span class="lab"><strong>Overall preference</strong><small>Which image would you keep?</small></span>
      <span class="chips" id="pref"></span></div>
    <textarea id="notes" placeholder="Notes (optional)"></textarea>
  </div>
  <div class="nav">
    <button id="prev" type="button">&larr; Previous</button>
    <button id="next" type="button">Next &rarr;</button>
    <button id="nextopen" type="button">Next unrated</button>
    <button id="flick" type="button" title="Show one image at a time to flip between them (Space)">Flip A/B (Space)</button>
    <span class="status" id="saved"></span>
  </div>
  <p class="hint">Keys: &larr; &rarr; move between pairs, Space flips between A and B in one big view, click an image to toggle full size.
  Your scores save in this browser as you go. <strong>Download review.csv</strong> when you are done (any time works; it keeps blanks).
  Which engine made A or B is not on this page.</p>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("data").textContent);
var rows = D.rows, scores = D.scores, prefs = D.preferences, header = D.header;
var state = {}, idx = 0, single = null;
function load(){try{var s=localStorage.getItem(D.storage_key);if(s)state=JSON.parse(s)||{};}catch(e){state={};}}
function persist(){try{localStorage.setItem(D.storage_key,JSON.stringify(state));document.getElementById("saved").textContent="Saved in this browser";}catch(e){document.getElementById("saved").textContent="Could not autosave here; download the CSV before closing";}}
function rec(i){var id=rows[i].pair_id;if(!state[id])state[id]={};return state[id];}
function val(i,col){var s=state[rows[i].pair_id];if(s&&Object.prototype.hasOwnProperty.call(s,col))return s[col];return rows[i][col]||"";}
function complete(i){
  if(!val(i,"preference_a_b_tie"))return false;
  for(var k=0;k<scores.length;k++){for(var s=0;s<2;s++){if(!val(i,scores[k]+"_"+(s?"b":"a")))return false;}}
  return true;
}
function el(tag,attrs,kids){var e=document.createElement(tag);for(var a in (attrs||{})){if(a==="text")e.textContent=attrs[a];else e.setAttribute(a,attrs[a]);}(kids||[]).forEach(function(k){e.appendChild(k);});return e;}
function src(path){return path.split("\\").join("/").split("/").map(encodeURIComponent).join("/");}
function chips(name,values,current,onpick){
  var box=el("span",{"class":"chips",role:"radiogroup"});
  values.forEach(function(v){
    var input=el("input",{type:"radio",name:name,value:String(v)});
    if(String(current)===String(v))input.checked=true;
    input.addEventListener("change",function(){onpick(String(v));});
    box.appendChild(el("label",{},[input,el("span",{text:String(v)})]));
  });
  return box;
}
function buildJump(){
  var j=document.getElementById("jump");j.innerHTML="";
  rows.forEach(function(r,i){var o=el("option",{value:String(i),text:(i+1)+". "+r.pair_id+(complete(i)?"  \u2713":"")});j.appendChild(o);});
  j.value=String(idx);
}
function show(){
  var r=rows[idx], pair=document.getElementById("pair");
  document.getElementById("prompt").textContent=(D.prompts[r.pair_id]?"Prompt: "+D.prompts[r.pair_id]:"")+(r.seed?"   (seed "+r.seed+")":"");
  pair.innerHTML="";pair.className="pair"+(single?" single":"");
  ["a","b"].forEach(function(side){
    var label=side.toUpperCase();
    if(single&&single!==side)return;
    var img=el("img",{src:src(r["image_"+side]),alt:"Image "+label+" of pair "+r.pair_id});
    img.addEventListener("click",function(){img.classList.toggle("full");});
    var cell=el("div",{"class":"cell"},[el("h2",{text:"Image "+label}),img]);
    var box=el("div",{"class":"scores"});
    scores.forEach(function(k){
      var lab=D.labels[k];
      var col=k+"_"+side;
      var row=el("div",{"class":"row"},[
        el("span",{"class":"lab"},[el("span",{text:lab[0]}),el("small",{text:lab[1]})]),
        chips(col+"-"+idx,[1,2,3,4,5],val(idx,col),function(v){rec(idx)[col]=v;persist();refresh();})
      ]);
      box.appendChild(row);
    });
    cell.appendChild(box);pair.appendChild(cell);
  });
  var pref=document.getElementById("pref");pref.innerHTML="";
  pref.appendChild(chips("pref-"+idx,prefs,val(idx,"preference_a_b_tie"),function(v){rec(idx)["preference_a_b_tie"]=v;persist();refresh();}));
  var notes=document.getElementById("notes");notes.value=val(idx,"notes");
  notes.oninput=function(){rec(idx).notes=notes.value;persist();};
  document.getElementById("prev").disabled=idx===0;
  document.getElementById("next").disabled=idx===rows.length-1;
  document.getElementById("flick").textContent=single?"Show both (Space)":"Flip A/B (Space)";
  refresh();
}
function refresh(){
  var done=0;rows.forEach(function(_,i){if(complete(i))done++;});
  document.getElementById("progress").textContent="Pair "+(idx+1)+" of "+rows.length+" \u00b7 "+done+" complete";
  document.getElementById("progress").className="status"+(done===rows.length?" done":"");
  document.getElementById("barfill").style.width=(100*done/rows.length)+"%";
  buildJump();
}
function go(i){if(i<0||i>=rows.length)return;idx=i;single=null;show();window.scrollTo(0,0);}
function csvCell(v){v=String(v==null?"":v);return /[",\r\n]/.test(v)?'"'+v.split('"').join('""')+'"':v;}
function download(){
  var lines=[header.map(csvCell).join(",")];
  rows.forEach(function(r,i){lines.push(header.map(function(c){return csvCell(val(i,c));}).join(","));});
  var blob=new Blob(["\ufeff"+lines.join("\r\n")+"\r\n"],{type:"text/csv;charset=utf-8"});
  var a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="review.csv";
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  setTimeout(function(){URL.revokeObjectURL(a.href);},2000);
}
document.getElementById("prev").onclick=function(){go(idx-1);};
document.getElementById("next").onclick=function(){go(idx+1);};
document.getElementById("nextopen").onclick=function(){
  for(var n=1;n<=rows.length;n++){var i=(idx+n)%rows.length;if(!complete(i)){go(i);return;}}
};
document.getElementById("jump").onchange=function(e){go(parseInt(e.target.value,10));};
document.getElementById("download").onclick=download;
function flip(){single=single==="a"?"b":(single==="b"?"a":"a");show();}
document.getElementById("flick").onclick=function(){if(single){single=null;show();}else flip();};
document.addEventListener("keydown",function(e){
  var t=e.target&&e.target.tagName;if(t==="TEXTAREA"||t==="SELECT")return;
  if(e.key==="ArrowRight"){go(idx+1);}else if(e.key==="ArrowLeft"){go(idx-1);}
  else if(e.key===" "){e.preventDefault();flip();}
});
load();
for(var i=0;i<rows.length;i++){if(!complete(i)){idx=i;break;}}
show();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
