"""
V10 - Structural checks on the PBIR report definition.

Power BI Desktop is the only full renderer, and Microsoft's JSON schemas lag
the versions Desktop writes. So this validator checks what can break silently
when report JSON is edited by hand or by a script, with no dependency beyond
the standard library:

  * every JSON file of the report and the semantic model parses;
  * pages.json lists exactly the page folders, each visual folder holds a
    visual.json whose name matches the folder;
  * every field a visual binds or filters on (Entity + Property) exists in the
    semantic model as a column or measure;
  * every visual sits inside its page, and no two visuals overlap - on the
    canvas and in the phone layout;
  * every report-page tooltip a visual points to exists and is a tooltip page;
  * each analysis page has exactly one "Key insight" box, and its text fits on
    one line (measured with the Segoe UI font metrics when the font is
    installed; skipped otherwise).
"""

from __future__ import annotations

import glob
import json
import os
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import ROOT, Checks  # noqa: E402

REPORT = ROOT / "VoltrixSupplyChain.Report"
MODEL = ROOT / "VoltrixSupplyChain.SemanticModel" / "definition"
PAGES = REPORT / "definition" / "pages"
PHONE_WIDTH = 320
INSIGHT_PREFIX = "Key insight: "


# --------------------------------------------------------------------------- model
def model_fields() -> dict[str, set[str]]:
    """Table -> names of its columns (incl. calculated) and measures."""
    out: dict[str, set[str]] = {}
    for p in (MODEL / "tables").glob("*.tmdl"):
        text = p.read_text(encoding="utf-8")
        table = re.match(r"table '?([^'\n]+?)'?\s*$", text.splitlines()[0]).group(1)
        names = re.findall(r"^\t(?:column|measure) (?:'([^']+)'|([^\s=]+))", text, re.M)
        out[table] = {a or b for a, b in names}
    return out


# --------------------------------------------------------------------------- report
def load(p: str | Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def field_refs(obj, aliases: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Every (Entity, Property) in a query / filter / object tree; resolves 'Source' aliases."""
    aliases = dict(aliases or {})
    refs: list[tuple[str, str]] = []

    def walk(o, al):
        if isinstance(o, dict):
            if isinstance(o.get("From"), list):
                al = dict(al)
                for f in o["From"]:
                    if isinstance(f, dict) and "Name" in f and "Entity" in f:
                        al[f["Name"]] = f["Entity"]
            if "Property" in o and isinstance(o.get("Expression"), dict) and "SourceRef" in o["Expression"]:
                sr = o["Expression"]["SourceRef"]
                ent = sr.get("Entity") or al.get(sr.get("Source"), f"?{sr.get('Source')}")
                refs.append((ent, o["Property"]))
            for v in o.values():
                walk(v, al)
        elif isinstance(o, list):
            for v in o:
                walk(v, al)

    walk(obj, aliases)
    return refs


def overlaps(rects: list[tuple[str, dict]]) -> list[str]:
    bad = []
    for i, (a, p) in enumerate(rects):
        for b, q in rects[i + 1:]:
            if (p["x"] < q["x"] + q["width"] and q["x"] < p["x"] + p["width"]
                    and p["y"] < q["y"] + q["height"] and q["y"] < p["y"] + p["height"]):
                bad.append(f"{a}×{b}")
    return bad


def text_width():
    """Advance-width measurer for Segoe UI 11pt at 96 dpi, or None if the font is absent."""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

    def font(path: Path):
        b = path.read_bytes()
        n = struct.unpack(">H", b[4:6])[0]
        t = {}
        for i in range(n):
            tag, _cs, off, ln = struct.unpack(">4sIII", b[12 + 16 * i:28 + 16 * i])
            t[tag.decode("latin-1")] = off
        upem = struct.unpack(">H", b[t["head"] + 18:t["head"] + 20])[0]
        nh = struct.unpack(">H", b[t["hhea"] + 34:t["hhea"] + 36])[0]
        adv = [struct.unpack(">H", b[t["hmtx"] + 4 * i:t["hmtx"] + 4 * i + 2])[0] for i in range(nh)]
        co = t["cmap"]
        sub = next(co + struct.unpack(">I", b[co + 8 + 8 * i:co + 12 + 8 * i])[0]
                   for i in range(struct.unpack(">H", b[co + 2:co + 4])[0])
                   if struct.unpack(">HH", b[co + 4 + 8 * i:co + 8 + 8 * i]) == (3, 1))
        seg = struct.unpack(">H", b[sub + 6:sub + 8])[0] // 2
        arr = lambda off, fmt="H": struct.unpack(f">{seg}{fmt}", b[off:off + 2 * seg])  # noqa: E731
        ends, starts = arr(sub + 14), arr(sub + 16 + 2 * seg)
        deltas, r0 = arr(sub + 16 + 4 * seg, "h"), sub + 16 + 6 * seg
        ro = arr(r0)

        def gid(c):
            for i in range(seg):
                if starts[i] <= c <= ends[i]:
                    if ro[i] == 0:
                        return (c + deltas[i]) & 0xFFFF
                    a = r0 + 2 * i + ro[i] + 2 * (c - starts[i])
                    g = struct.unpack(">H", b[a:a + 2])[0]
                    return (g + deltas[i]) & 0xFFFF if g else 0
            return 0
        return lambda s: sum(adv[min(gid(ord(ch)), nh - 1)] for ch in s) * (11 * 96 / 72) / upem

    try:
        reg, bold = font(fonts / "segoeui.ttf"), font(fonts / "segoeuib.ttf")
    except (OSError, KeyError, StopIteration, struct.error):
        return None
    return lambda s: bold(INSIGHT_PREFIX) + reg(s)


def main() -> int:
    c = Checks("V10 - report definition structure")

    # ---- 1 JSON parses -------------------------------------------------------
    files = [p for p in glob.glob(str(REPORT / "**" / "*"), recursive=True)
             + glob.glob(str(MODEL.parent / "**" / "*"), recursive=True)
             + [str(ROOT / "VoltrixSupplyChain.pbip")]
             if os.path.isfile(p) and p.endswith((".json", ".pbir", ".pbism", ".pbip", ".platform"))
             and f"{os.sep}.pbi{os.sep}" not in p]
    bad_json = []
    for p in files:
        try:
            load(p)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            bad_json.append(f"{os.path.relpath(p, ROOT)}: {e}")
    c.add("1", "Every report / model JSON file parses", not bad_json,
          "; ".join(bad_json) if bad_json else f"{len(files)} files")

    # ---- 2 pages and visual folders consistent ---------------------------------
    meta = load(PAGES / "pages.json")
    folders = sorted(d.name for d in PAGES.iterdir() if d.is_dir())
    pages = {pid: load(PAGES / pid / "page.json") for pid in folders}
    name_bad = [pid for pid, pj in pages.items() if pj.get("name") != pid]
    visuals: dict[str, dict[str, dict]] = {}
    vis_bad = []
    for pid in folders:
        visuals[pid] = {}
        for vd in sorted((PAGES / pid / "visuals").iterdir()) if (PAGES / pid / "visuals").exists() else []:
            vf = vd / "visual.json"
            if not vf.exists():
                vis_bad.append(f"{pid}/{vd.name}: no visual.json")
                continue
            v = load(vf)
            if v.get("name") != vd.name:
                vis_bad.append(f"{pid}/{vd.name}: name {v.get('name')}")
            visuals[pid][vd.name] = v
    order_ok = sorted(meta["pageOrder"]) == folders and meta.get("activePageName") in meta["pageOrder"]
    c.add("2", "pages.json lists exactly the page folders; page and visual names match their folders",
          order_ok and not name_bad and not vis_bad,
          f"{len(folders)} pages, {sum(len(v) for v in visuals.values())} visuals"
          + (f"; order_ok={order_ok} page_names={name_bad} visuals={vis_bad}" if not (order_ok and not name_bad and not vis_bad) else ""))

    # ---- 3 every bound field exists in the model -------------------------------
    fields = model_fields()
    unresolved = set()
    n_refs = 0
    for pid, vs in visuals.items():
        for vid, v in vs.items():
            refs = field_refs(v.get("visual", {})) + field_refs(v.get("filterConfig", {}))
            n_refs += len(refs)
            for ent, prop in refs:
                if prop not in fields.get(ent, set()):
                    unresolved.add(f"{pages[pid]['displayName']}/{vid}: {ent}[{prop}]")
        refs = field_refs(pages[pid].get("filterConfig", {})) + field_refs(pages[pid].get("pageBinding", {}))
        n_refs += len(refs)
        unresolved |= {f"{pages[pid]['displayName']} (page): {e}[{p}]" for e, p in refs if p not in fields.get(e, set())}
    c.add("3", "Every field a visual or page binds or filters on exists in the semantic model", not unresolved,
          "; ".join(sorted(unresolved)[:8]) if unresolved else f"{n_refs} references resolve")

    # ---- 4/5 geometry ------------------------------------------------------------
    outside, overlap, m_outside, m_overlap = [], [], [], []
    for pid, vs in visuals.items():
        W, H = pages[pid]["width"], pages[pid]["height"]
        rects = [(vid[:8], v["position"]) for vid, v in vs.items()]
        outside += [f"{pages[pid]['displayName']}/{a}" for a, p in rects
                    if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > W or p["y"] + p["height"] > H]
        overlap += [f"{pages[pid]['displayName']}: {o}" for o in overlaps(rects)]
        mob = []
        for vid in vs:
            mf = PAGES / pid / "visuals" / vid / "mobile.json"
            if mf.exists():
                mob.append((vid[:8], load(mf)["position"]))
        m_outside += [f"{pages[pid]['displayName']}/{a}" for a, p in mob if p["x"] < 0 or p["x"] + p["width"] > PHONE_WIDTH]
        m_overlap += [f"{pages[pid]['displayName']}: {o}" for o in overlaps(mob)]
    c.add("4", "Every visual inside its page; no two visuals overlap on the canvas", not outside and not overlap,
          f"outside={outside} overlaps={overlap}" if outside or overlap else "0 outside, 0 overlaps")
    c.add("5", "Phone layout: every placed visual inside the 320 px column; no overlaps", not m_outside and not m_overlap,
          f"outside={m_outside} overlaps={m_overlap}" if m_outside or m_overlap else "0 outside, 0 overlaps")

    # ---- 6 tooltip / drill-through targets -----------------------------------
    tooltip_pages = {pid for pid, pj in pages.items() if pj.get("pageBinding", {}).get("type") == "Tooltip"}
    bad_tt = []
    for pid, vs in visuals.items():
        for vid, v in vs.items():
            for t in v.get("visual", {}).get("visualContainerObjects", {}).get("visualTooltip", []):
                sec = t["properties"].get("section", {}).get("expr", {}).get("Literal", {}).get("Value")
                if sec and sec.strip("'") not in tooltip_pages:
                    bad_tt.append(f"{pages[pid]['displayName']}/{vid[:8]} -> {sec}")
    c.add("6", "Every report-page tooltip a visual points to exists and is a tooltip page", not bad_tt,
          str(bad_tt) if bad_tt else f"{len(tooltip_pages)} tooltip pages")

    # ---- 7 insight boxes -------------------------------------------------------
    measure = text_width()
    analysis = [pid for pid, pj in pages.items() if not pj.get("pageBinding") and pj.get("visibility") != "HiddenInViewMode"]
    ins_bad, widest = [], 0.0
    for pid in analysis:
        boxes = []
        for vid, v in visuals[pid].items():
            if v.get("visual", {}).get("visualType") != "textbox":
                continue
            for para in v["visual"].get("objects", {}).get("general", [{}])[0].get("properties", {}).get("paragraphs", []):
                runs = para.get("textRuns", [])
                if runs and runs[0].get("value") == INSIGHT_PREFIX:
                    boxes.append((v, "".join(r["value"] for r in runs[1:])))
        if len(boxes) != 1:
            ins_bad.append(f"{pages[pid]['displayName']}: {len(boxes)} insight boxes")
            continue
        v, text = boxes[0]
        if not text.strip():
            ins_bad.append(f"{pages[pid]['displayName']}: empty insight")
        if measure:
            w = measure(text)
            widest = max(widest, w)
            if w > v["position"]["width"] - 20:
                ins_bad.append(f"{pages[pid]['displayName']}: {w:.0f}px > {v['position']['width'] - 20}px")
    c.add("7", "One insight box per analysis page, non-empty, fits one line", not ins_bad,
          "; ".join(ins_bad) if ins_bad else (f"{len(analysis)} pages, widest {widest:.0f}px"
                                              if measure else f"{len(analysis)} pages (font metrics unavailable: width not checked)"))

    return c.report("v10_report_report.txt")


if __name__ == "__main__":
    sys.exit(main())
