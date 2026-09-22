# app/report_renderer.py
from __future__ import annotations

import html
import json
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# =========================
# Utils
# =========================

def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)

def pct(v: Any) -> str:
    try:
        f = float(v)
    except Exception:
        return "—"
    f = max(0.0, min(1.0, f))
    return f"{round(f * 100.0, 2):.2f}%"

def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE | re.MULTILINE)

def _first(pattern: str, text: str, group: int | str = 1) -> Optional[str]:
    m = _rx(pattern).search(text)
    if not m:
        return None
    try:
        return m.group(group)
    except Exception:
        return m.group(0)

def _all(pattern: str, text: str) -> List[re.Match]:
    return list(_rx(pattern).finditer(text))

def _safe_int(s: Optional[str], d: int = 0) -> int:
    try:
        return int(s) if s is not None else d
    except Exception:
        return d

# =========================
# Tiny SVGs (themed)
# =========================

SVG_BASE  = "#1A1D40"
SVG_PRI   = "#6B34FC"
SVG_GOOD  = "#64BC4B"
SVG_PART  = "#FFD480"
SVG_BAD   = "#FF5C77"

def donut_svg(frac: float | None, size: int = 150, label: str = "", bad_threshold: float = 0.97) -> str:
    """Render a coverage donut. Turns red if frac < bad_threshold (default 97%)."""
    if frac is None:
        return "<div class='muted'>—</div>"
    try:
        p = max(0.0, min(1.0, float(frac)))
    except Exception:
        return "<div class='muted'>—</div>"

    stroke_color = SVG_PRI if p >= bad_threshold else SVG_BAD
    R = round(size * 0.39)
    SW = round(size * 0.13)
    W = H = size
    CX = CY = size / 2.0
    circ = 2.0 * math.pi * R
    off = circ * (1.0 - p)
    return (
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' role='img' aria-label='{esc(label)}: {round(p*100)}%'>"
        f"<circle cx='{CX}' cy='{CY}' r='{R}' fill='none' stroke='{SVG_BASE}' stroke-width='{SW}'/>"
        f"<circle cx='{CX}' cy='{CY}' r='{R}' fill='none' stroke='{stroke_color}' stroke-width='{SW}' "
        f"stroke-dasharray='{circ}' stroke-dashoffset='{off}' stroke-linecap='round'/>"
        f"<text x='{CX}' y='{CY + size*0.06}' text-anchor='middle' fill='#E8EAF6' "
        f"font-size='{round(size*0.22)}' font-weight='800'>{round(p*100)}%</text>"
        f"</svg>"
    )

def pie_svg(parts: List[Dict[str, Any]], size: int = 150) -> str:
    if not parts:
        return "<div class='muted'>—</div>"
    total = sum(float(p.get("v", 0)) for p in parts)
    if total <= 0:
        return "<div class='muted'>—</div>"
    W = H = size
    R = round(size * 0.365)
    cx = W / 2.0
    cy = H / 2.0
    a0 = 0.0
    svg = [f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' role='img'>"]
    for p in parts:
        v = float(p.get("v", 0.0))
        if v <= 0:
            continue
        fr = v / total
        a1 = a0 + fr * 2.0 * math.pi
        x0 = cx + R * math.cos(a0)
        y0 = cy + R * math.sin(a0)
        x1 = cx + R * math.cos(a1)
        y1 = cy + R * math.sin(a1)
        large = 1 if fr > 0.5 else 0
        color = p.get("c") or SVG_PRI
        svg.append(
            f"<path d='M{cx} {cy} L{x0} {y0} A{R} {R} 0 {large} 1 {x1} {y1} Z' fill='{color}'/>"
        )
        a0 = a1
    svg.append("</svg>")
    return "".join(svg)

def stacked_bar3(good: int, partial: int, bad: int, W: int = 380, H: int = 12) -> str:
    total = max(1, int(good) + int(partial) + int(bad))
    gW = round(W * (int(good) / total))
    pW = round(W * (int(partial) / total))
    bW = max(0, W - gW - pW)
    return (
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' role='img'>"
        f"<rect x='0' y='0' width='{gW}' height='{H}' fill='{SVG_GOOD}'/>"
        f"<rect x='{gW}' y='0' width='{pW}' height='{H}' fill='{SVG_PART}'/>"
        f"<rect x='{gW + pW}' y='0' width='{bW}' height='{H}' fill='{SVG_BAD}'/>"
        f"</svg>"
    )

# =========================
# Parsers (per your spec)
# =========================

def _parse_pairs(line: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    if not line:
        return out
    tokens = re.split(r"[,\s]+", line.strip())
    for tok in tokens:
        if not tok or "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        v = re.sub(r"[^\d].*$", "", v.strip())
        try:
            out.append((k.strip(), int(v)))
        except Exception:
            pass
    return out

def _aggregate_pairs(lines: List[str]) -> Dict[str, int]:
    agg: Dict[str, int] = defaultdict(int)
    for ln in lines:
        for k, v in _parse_pairs(ln):
            agg[k] += v
    return dict(agg)

def extract_scan_info(text: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"scanId": "", "project": "", "branch": "", "createdAt": ""}
    m = _rx(r"\bScanId\s*[:=]\s*([A-Za-z0-9-]{6,})").search(text)
    if m:
        info["scanId"] = m.group(1)
    return info

def extract_language_mode_block(text: str) -> Dict[str, Any]:
    mode_line = _first(r"^MULTI_LANGUAGE_MODE.+$", text, group=0)
    mode = ""
    if mode_line:
        mode = "primary" if "one primary" in mode_line.lower() else "multi"

    ident_lines = [m.group(1).strip() for m in _all(r"^All languages identified but not scanned:\s*(.+)$", text)]
    scanned_lines = [m.group(1).strip() for m in _all(r"^Languages that will be scanned:\s*(.+)$", text)]
    total_ident_lines = [m.group(1).strip() for m in _all(r"^The following source files were identified:\s*(.+)$", text)]

    ident_not_scanned_map = _aggregate_pairs(ident_lines)
    scanned_map = _aggregate_pairs(scanned_lines)
    total_ident_map = _aggregate_pairs(total_ident_lines)

    display_ident = " | ".join(ident_lines) if ident_lines else ""
    display_scanned = " | ".join(scanned_lines) if scanned_lines else ""

    return {
        "scanMode": mode or "",
        "identified_line": display_ident,
        "scanned_line": display_scanned,
        "identified_not_scanned_map": ident_not_scanned_map,
        "scanned_map": scanned_map,
        "identified_total_map": total_ident_map,
    }

def extract_coverage_summary(text: str) -> Dict[str, Any]:
    blk = _first(r"Scan Accuracy\s*[-\s]*\n((?:.+\n){3,}?)\n(?:\S|\Z)", text, 1) or ""
    def grab(label: str) -> int:
        return _safe_int(_first(rf"^{re.escape(label)}\s*[:\t]+\s*([0-9]+)", blk))
    def grab_pct(label: str) -> Optional[float]:
        s = _first(rf"^{re.escape(label)}\s*[:\t]+\s*([0-9]+(?:\.[0-9]+)?)%", blk)
        return float(s) / 100.0 if s else None
    return {
        "totalFiles": grab("Total files"),
        "goodFiles": grab("Good files"),
        "partialFiles": grab("Partially good files"),
        "badFiles": grab("Bad files"),
        "parsedLOC": grab("Parsed LOC"),
        "goodLOC": grab("Good LOC"),
        "badLOC": grab("Bad LOC"),
        "domObjects": grab("Number of DOM Objects"),
        "coverageFiles": grab_pct("Scan coverage"),
        "coverageLOC": grab_pct("Scan coverage LOC"),
    }

def extract_vulnerabilities(text: str) -> Dict[str, Any]:
    """
    Parse "*** Results Summary ***" section.
    - Keep only Critical/High/Medium
    - Build severity totals from findings with results > 0
    - Top list: if >=10 findings with results > 0 -> top 10; else only those with results > 0
    """
    start = _rx(r"\*\*\* Results Summary \*\*\*").search(text)
    if not start:
        return {"vulnParts": [], "vulnTop": []}

    after = text[start.end():]
    line_rx = _rx(
        r"^Query\s*-\s*(?P<q>.+?)\s+Severity:\s*(?P<sev>\w+)\s+.*?Results:\s*(?P<res>\d+)\s+.*?Duration\s*=\s*(?P<dur>\d{2}:\d{2}:\d{2}\.\d+).*?(?:CWE\s*(?P<cwe>\d+))?.*?(?:SHA1:\s*(?P<sha>[0-9a-fA-F]+))?.*$"
    )

    rows_all: List[Dict[str, Any]] = []
    for m in _all(line_rx.pattern, after):
        sev = m.group("sev").strip().capitalize()
        if sev not in {"Critical", "High", "Medium"}:
            continue
        count = _safe_int(m.group("res"))
        rows_all.append({
            "displayName": m.group("q").split("/")[-1].split(".")[-1].strip(),
            "fullQuery": m.group("q").strip(),
            "severity": sev,
            "count": count,
            "duration": m.group("dur"),
            "cwe": (m.group("cwe") or "") or None,
            "sha1": (m.group("sha") or "") or None,
        })

    rows_pos = [r for r in rows_all if int(r["count"]) > 0]

    totals = Counter()
    for r in rows_pos:
        totals[r["severity"]] += int(r["count"])

    color = {"Critical": SVG_BAD, "High": "#FFB64D", "Medium": SVG_PART}
    parts = [{"label": k, "v": v, "c": color[k]} for k, v in totals.items() if v > 0]

    if len(rows_pos) >= 10:
        top = sorted(rows_pos, key=lambda r: r["count"], reverse=True)[:10]
    else:
        top = sorted(rows_pos, key=lambda r: r["count"], reverse=True)

    return {"vulnParts": parts, "vulnTop": top}

def _choose_base_language(text: str) -> Optional[str]:
    lang_block = extract_language_mode_block(text)
    scanned = lang_block.get("scanned_map") or {}
    if scanned:
        return max(scanned.items(), key=lambda kv: (kv[1], kv[0]))[0]
    total_ident = lang_block.get("identified_total_map") or {}
    if total_ident:
        return max(total_ident.items(), key=lambda kv: (kv[1], kv[0]))[0]
    ident_ns = lang_block.get("identified_not_scanned_map") or {}
    if ident_ns:
        return max(ident_ns.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return None

# --- Grouped sanity parsing (top 3 per category) ---

def extract_sanity_groups(text: str) -> Dict[str, Any]:
    lang = _choose_base_language(text)
    start = _rx(r"General Queries Summary").search(text)
    groups = {"inputs": [], "outputs": [], "sanitize": []}
    if not start or not lang:
        return {"language": lang, "groups": groups}

    tail = text[start.end():]
    row_rx = _rx(r"^(?P<q>[A-Za-z0-9_.-]+)\s+(?P<st>success|failed|warning)\s+(?P<res>\d+)\s+(?P<dur>\d{2}:\d{2}:\d{2}\.\d+).*$")

    bucket: Dict[str, List[Dict[str, Any]]] = {"inputs": [], "outputs": [], "sanitize": []}
    for m in _all(row_rx.pattern, tail):
        q = m.group("q")
        if not q.startswith(f"{lang}."):
            continue
        name = q.split(".", 1)[-1]
        res = _safe_int(m.group("res"))
        rec = {"name": name, "count": res, "status": m.group("st"), "duration": m.group("dur")}
        if re.search(r"sanit", name, re.IGNORECASE):
            bucket["sanitize"].append(rec)
        elif re.search(r"inputs?", name, re.IGNORECASE):
            bucket["inputs"].append(rec)
        elif re.search(r"outputs?", name, re.IGNORECASE):
            bucket["outputs"].append(rec)

    for k in bucket:
        bucket[k].sort(key=lambda r: r["count"], reverse=True)
        groups[k] = bucket[k][:3]

    return {"language": lang, "groups": groups}

def extract_exclusions(text: str) -> Dict[str, Any]:
    # Support both legacy and new exclusion formats
    files_count = _safe_int(_first(r"Number of excluded files:\s*(\d+)", text))
    if files_count == 0:
        files_count = _safe_int(_first(r"Number of exclude files\s*=\s*(\d+)", text))

    by_folder_lines = [m.group(0).strip() for m in _all(r"^.*Excluded by folder name:.*$", text)]
    by_fname_lines  = [m.group(0).strip() for m in _all(r"^.*Excluded by filename:.*$", text)]

    # Newer engine logs sometimes print a plain list after an "Exclude Files" header.
    lines = text.splitlines()
    extra_paths: List[str] = []
    for i, ln in enumerate(lines):
        if "Exclude Files" in ln:
            j = i + 1
            while j < len(lines) and lines[j].strip():
                cand = lines[j].strip()
                if re.match(r'^(?:/|[A-Za-z]:\\)', cand):
                    extra_paths.append(cand)
                j += 1
            # assume first block is enough
            break

    # If we discovered explicit file paths, prefer showing them in byFilename
    if extra_paths:
        by_fname_lines = extra_paths
        if not files_count:
            files_count = len(extra_paths)

    folders_count = len(by_folder_lines)
    return {
        "exclFiles": files_count,
        "exclFolders": folders_count,
        "exclTotal": files_count + folders_count,
        "byFolder": by_folder_lines,
        "byFilename": by_fname_lines,
    }

# --- NEW: Per-Language Parse Statistics -> table rows ---
def extract_language_stats_rows(text: str) -> List[Dict[str, Any]]:
    """
    Read CSV-like 'per-language-parse-statistics,...' lines and convert into table rows:
      Language | Files Identified (total-files) | Files Scanned (good-files) | Coverage (file-coverage%)
    Ignores the '_total' line. Sorted by Files Scanned desc.
    """
    # ensure we are after the "Per-Language Parse Statistics" marker; but also parse globally as fallback
    block_start = _rx(r"Per-Language Parse Statistics").search(text)
    search_area = text[block_start.start():] if block_start else text

    rows: List[Dict[str, Any]] = []
    for m in _all(r"^per-language-parse-statistics,([^\r\n]+)$", search_area):
        parts = [p.strip() for p in m.group(1).split(",")]
        # Expect: language,total,good,partial,bad,filecov,parsedloc,goodloc,badloc,loccov,dom
        if not parts or parts[0].lower() == "language":
            continue
        if parts[0] == "_total":
            continue
        try:
            language = parts[0]
            total = int(parts[1])
            good = int(parts[2])
            # partial = int(parts[3])  # available if needed later
            file_cov = float(parts[5]) / 100.0 if parts[5] else None
        except Exception:
            continue
        rows.append({"lang": language, "ident": total, "scanned": good, "coverage": file_cov})

    rows.sort(key=lambda r: (r["scanned"], r["ident"], r["lang"]), reverse=True)
    return rows

def _build_language_rows_from_maps(scanned_map: Dict[str,int], ident_ns_map: Dict[str,int], ident_total_map: Dict[str,int]) -> List[Dict[str, Any]]:
    # fallback when CSV stats are not present
    langs = set(scanned_map) | set(ident_ns_map) | set(ident_total_map)
    rows: List[Dict[str, Any]] = []
    for lang in sorted(langs):
        scanned = int(scanned_map.get(lang, 0))
        if ident_total_map:
            ident = int(ident_total_map.get(lang, scanned or ident_ns_map.get(lang, 0)))
        else:
            ident = int(scanned + ident_ns_map.get(lang, 0))
            if ident == 0 and scanned > 0:
                ident = scanned
        coverage = (scanned / ident) if ident else None
        rows.append({"lang": lang, "ident": ident, "scanned": scanned, "coverage": coverage})
    rows.sort(key=lambda r: (r["scanned"], r["ident"], r["lang"]), reverse=True)
    return rows

# --- NEW: Files with parsing issues ---

_PARSE_KEYWORDS = (
    "failed to parse", "unable to parse", "parse error", "parsing error",
    "partially good file", "partially good files", "partially parsed",
    "bad file", "bad files", "file parsing error", "lexer error", "parser error",
    # Add engine-specific signals often seen with SQL/PLSQL parsing
    "recognitionexception", "no plsql statements found"
)

_PATH_RXES = [
    re.compile(r'"(?P<p>[^"]+/[^"]+\.[A-Za-z0-9][^"]*)"', re.I),  # quoted unix-like
    re.compile(r'"(?P<p>[A-Za-z]:\\[^"]+)"', re.I),               # quoted windows
    re.compile(r'(?P<p>(?:/|[A-Za-z]:\\)[^,;\)\]\r\n]+?\.[A-Za-z0-9][^,;\)\]\r\n]*)', re.I),  # unquoted
]

def extract_parsing_issue_files(text: str) -> List[Dict[str, Any]]:
    counts: Counter[str] = Counter()
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        low = line.lower()
        # Heuristic: capture explicit SQL parsing warnings that mention file on same or next line
        triggered = any(k in low for k in _PARSE_KEYWORDS)
        candidate_lines = [line]
        if triggered and idx + 1 < len(lines):
            candidate_lines.append(lines[idx + 1])
        for cand_line in candidate_lines:
            for rx in _PATH_RXES:
                for m in rx.finditer(cand_line):
                    p = (m.group("p") or "").strip().rstrip('".,);]')
                    if p and ("/" in p or "\\" in p) and "." in p:
                        counts[p] += 1
    return [{"path": p, "count": c} for p, c in counts.most_common()]

# =========================
# Public: build_model + render_html
# =========================

def build_model(raw_log: str, meta_from_event: Dict[str, Any] | None = None) -> Dict[str, Any]:
    text = raw_log or ""
    info = extract_scan_info(text)

    cov = extract_coverage_summary(text)
    lang_mode = extract_language_mode_block(text)
    vulns = extract_vulnerabilities(text)
    sanity_groups = extract_sanity_groups(text)
    excl = extract_exclusions(text)
    parse_issue_rows = extract_parsing_issue_files(text)

    # Preferred source: per-language CSV stats
    lang_rows = extract_language_stats_rows(text)
    if not lang_rows:
        # Fallback to earlier heuristic
        lang_rows = _build_language_rows_from_maps(
            lang_mode.get("scanned_map", {}) or {},
            lang_mode.get("identified_not_scanned_map", {}) or {},
            lang_mode.get("identified_total_map", {}) or {}
        )

    # Flatten top-3 per category into single table rows
    cat_label = {"inputs": "Inputs", "outputs": "Outputs", "sanitize": "Sanitize"}
    sanity_top_rows: List[Dict[str, Any]] = []
    for key in ("inputs", "outputs", "sanitize"):
        for r in sanity_groups["groups"].get(key, []):
            sanity_top_rows.append({"name": r["name"], "type": cat_label[key], "count": int(r["count"])})

    if meta_from_event:
        info["project"] = meta_from_event.get("projectName") or info.get("project")
        info["branch"] = meta_from_event.get("branch") or info.get("branch")
        info["createdAt"] = meta_from_event.get("createdAt") or info.get("createdAt")
        info["scanId"] = meta_from_event.get("scanId") or info.get("scanId")

    model = {
        "info": info,
        "summary": cov,
        "langs": lang_mode,
        "vulns": vulns,
        "sanity_groups": sanity_groups,
        "sanity_top_rows": sanity_top_rows,
        "excl": {
            "exclFolders": excl["exclFolders"],
            "exclFiles": excl["exclFiles"],
            "exclTotal": excl["exclTotal"],
            "byFolder": excl["byFolder"],
            "byFilename": excl["byFilename"],
        },
        "parseIssues": parse_issue_rows,
        "lang_rows": lang_rows,
        "raw": text,
    }
    return model

# -------------------------
# Themed HTML (suite look)
# -------------------------

def render_html(meta: Dict[str, Any], model: Dict[str, Any]) -> str:
    info = model.get("info", {})
    summary = model.get("summary", {})
    langs = model.get("langs", {})
    excl = model.get("excl", {})
    vulns = model.get("vulns", {})
    lang_rows = model.get("lang_rows", [])
    sanity_groups = model.get("sanity_groups", {"language": None, "groups": {"inputs": [], "outputs": [], "sanitize": []}})
    sanity_rows = model.get("sanity_top_rows", [])
    parse_issues = model.get("parseIssues", [])
    # Pre-serialize parsing issues for safe injection into JS (avoid undefined)
    try:
        parse_issues_json = json.dumps(parse_issues, ensure_ascii=False)
    except Exception:
        parse_issues_json = "[]"
    raw_log = model.get("raw", "")

    cov_files = pct(summary.get("coverageFiles"))
    cov_loc   = pct(summary.get("coverageLOC"))
    gf = int(summary.get("goodFiles") or 0)
    pf = int(summary.get("partialFiles") or 0)
    bf = int(summary.get("badFiles") or 0)
    total_files = int(summary.get("totalFiles") or 0)

    donut_files = donut_svg(summary.get("coverageFiles"), 150, "Scan coverage")
    donut_loc   = donut_svg(summary.get("coverageLOC"),   120, "LOC coverage")
    stacked     = stacked_bar3(gf, pf, bf, 380, 12)

    # Build language lines from per-language CSV stats (preferred source)
    scanned_langs = [r for r in (lang_rows or []) if int(r.get("scanned") or 0) > 0]
    scanned_count = len(scanned_langs)
    scanned_line_csv = " | ".join(f"{esc(r.get('lang',''))}={int(r.get('scanned',0))}" for r in scanned_langs)
    ident_line_csv = " | ".join(f"{esc(r.get('lang',''))}={int(r.get('ident',0))}" for r in (lang_rows or []))

    # Vulnerabilities list (no pie chart to maximize space)
    parts = vulns.get("vulnParts", [])
    sev_line = " · ".join(f"{esc(p['label'])} ({int(p['v'])})" for p in parts) or "None"

    top_rows = vulns.get("vulnTop", []) or []
    top_count = len(top_rows)
    top_title = "Top 10 by results (Critical/High/Medium)" if top_count == 10 else "By results (Critical/High/Medium)"
    if top_rows:
        top_html = (
            "<ol class='olist'>" +
            "".join(
                f"<li><span class='vname' title='{esc(v.get('fullQuery',''))}'>"
                f"<span class='sev {esc(v.get('severity','').lower())}'>{esc(v.get('severity',''))}</span>"
                f"{esc(v.get('displayName',''))}</span>"
                f"<b>{int(v.get('count',0))}</b></li>"
                for v in top_rows
            ) +
            "</ol>"
        )
    else:
        top_html = "<div class='muted'>No Critical/High/Medium vulnerabilities</div>"

    excl_table = (
        "<table class='table small'><thead><tr><th>Reason</th><th class='num'>Count</th></tr></thead>"
        "<tbody>"
        f"<tr><td>Folders</td><td class='num'>{int(excl.get('exclFolders') or 0)}</td></tr>"
        f"<tr><td>Files</td><td class='num'>{int(excl.get('exclFiles') or 0)}</td></tr>"
        f"<tr><td><strong>Total</strong></td><td class='num'><strong>{int(excl.get('exclTotal') or 0)}</strong></td></tr>"
        "</tbody></table>"
        if int(excl.get("exclFolders") or 0) + int(excl.get("exclFiles") or 0) > 0
        else "<div class='muted'>No files/folders excluded.</div>"
    )

    excl_lines = []
    for line in excl.get("byFolder", []):
        excl_lines.append(f"<div class='mono tiny'>{esc(line)}</div>")
    for line in excl.get("byFilename", []):
        excl_lines.append(f"<div class='mono tiny'>{esc(line)}</div>")
    excl_lines_html = "".join(excl_lines) if excl_lines else "<div class='muted'>No files/folders excluded.</div>"

    def _lang_stats_table(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "<div class='muted'>—</div>"
        body = "".join(
            "<tr>"
            f"<td>{esc(r.get('lang',''))}</td>"
            f"<td class='num'>{int(r.get('ident',0))}</td>"
            f"<td class='num'>{int(r.get('scanned',0))}</td>"
            f"<td class='num'>{pct(r.get('coverage')) if r.get('coverage') is not None else '—'}</td>"
            "</tr>"
            for r in rows
        )
        return (
            "<div class='table-wrap'>"
            "<table class='table small'>"
            "<thead><tr><th>Language</th><th class='num'>Files Identified</th>"
            "<th class='num'>Files Scanned</th><th class='num'>Coverage</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
        )

    def _sanity_table(rows: List[Dict[str, Any]], lang_label: str) -> str:
        if not rows:
            return "<div class='muted'>No query results found.</div>"
        order = {"Inputs": 0, "Outputs": 1, "Sanitize": 2}
        rows_sorted = sorted(rows, key=lambda r: (order.get(r["type"], 9), -int(r["count"]), r["name"]))
        body = "".join(
            "<tr>"
            f"<td>{esc(r['name'])}</td>"
            f"<td>{esc(r['type'])}</td>"
            f"<td class='num'>{int(r['count'])}</td>"
            "</tr>"
            for r in rows_sorted
        )
        return (
            f"<div class='muted tiny' style='margin:0 0 8px'>Language: {esc(lang_label or '—')}</div>"
            "<div class='table-wrap'>"
            "<table class='table small'>"
            "<thead><tr><th>Query</th><th>Type</th><th class='num'>Results</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
            "<small class='muted tiny'>Top 3 in each category for the dominant language.</small>"
        )

    def _parse_issues_table(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "<div class='muted'>No parsing issues detected.</div>"
        body = "".join(
            "<tr>"
            f"<td class='mono'>{esc(r['path'])}</td>"
            f"<td class='num'>{int(r['count'])}</td>"
            "</tr>"
            for r in rows
        )
        return (
            "<div class='table-wrap'>"
            "<table class='table small'>"
            "<thead><tr><th>File path</th><th class='num'>Mentions</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
            "<small class='muted tiny'>Heuristic extraction from parsing-error lines in the log.</small>"
        )

    title = "Log Analysis"
    project_name = meta.get("projectName") or info.get("project") or ""
    if project_name:
        title += f" — {esc(project_name)}"

    sast_start = esc(meta.get('sastStart') or '—')
    sast_end   = esc(meta.get('sastEnd') or '—')
    sast_loc   = meta.get('sastLOC')
    sast_loc_s = f"{int(sast_loc):,}" if isinstance(sast_loc, (int, float)) else (esc(str(sast_loc)) if sast_loc else '—')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{esc(title)}</title>
<style>
:root{{
  --cx-primary:#6B34FC; --cx-primary-600:#5827E1; --cx-primary-700:#4A1FC1;
  --cx-accent:#64BC4B; --cx-accent-700:#4AA233;
  --cx-bg:#0F1122; --cx-surface:#151736; --cx-elev:#1A1D40; --cx-border:rgba(255,255,255,.08);
  --cx-text:#E8EAF6; --cx-muted:#A7ABC4; --cx-danger:#ff5c77; --cx-success:#27d17f;
  --cx-shadow:0 10px 30px rgba(23,18,63,.35);
}}
*{{box-sizing:border-box}}
html,body{{height:100%}}
body.cx-bg{{
  margin:0; color:var(--cx-text);
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(107,52,252,.25), transparent 70%),
    radial-gradient(1000px 600px at 120% 0%, rgba(100,188,75,.15), transparent 60%),
    var(--cx-bg);
  font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
}}
.container{{max-width:1200px;margin:0 auto;padding:16px 20px}}
.header{{position:sticky;top:0;z-index:50;background:linear-gradient(180deg, rgba(16,18,41,.9), rgba(16,18,41,.75));backdrop-filter:blur(10px);border-bottom:1px solid var(--cx-border)}}
.header-inner{{display:flex;align-items:center;justify-content:space-between;min-height:64px}}
.brand{{display:flex;align-items:center;gap:12px}}
.brand-mark{{width:10px;height:10px;border-radius:50%;background:{SVG_GOOD};box-shadow:0 0 10px rgba(100,188,75,.35)}}
.brand-text{{font-weight:700;letter-spacing:.2px}}
.sub{{font-size:.8rem;color:var(--cx-muted)}}
.row{{display:grid;gap:14px}}
.row-3{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.row-2cols{{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:980px){{.row-3,.row-2cols{{grid-template-columns:1fr}}}}
.card{{background:linear-gradient(180deg, rgba(255,255,255,.025), rgba(255,255,255,.01));border:1px solid var(--cx-border);border-radius:16px;padding:18px 20px;box-shadow:var(--cx-shadow)}}
.card h2{{margin:0 0 10px;font-size:1.05rem;color:#E3E6FF}}
.kpi-title{{font-size:.85rem;color:#D8DAFF}}
.kpi-val{{font-size:1.6rem;font-weight:800;color:#E3E6FF}}
.kpi-sub{{font-size:.85rem;color:var(--cx-muted)}}
.psGrid{{display:grid;grid-template-columns:150px 120px 1fr;gap:18px;align-items:center}}
.legend{{display:flex;gap:10px;margin-top:8px;align-items:center;font-size:.85rem;color:#cbd1ee}}
.chip{{width:10px;height:10px;background:#fff;display:inline-block;border-radius:2px;border:1px solid var(--cx-border)}}
.olist{{margin:6px 0 0;padding-left:18px}}
.olist li{{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:2px 0}}
.olist li .vname{{display:inline-flex;align-items:center;gap:8px;max-width:min(52vw, 440px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sev{{padding:2px 8px;border-radius:999px;border:1px solid var(--cx-border);margin-right:6px;font-size:.75rem}}
.sev.critical{{background:rgba(255,92,119,.14);color:#FFD8E0;border-color:rgba(255,92,119,.35)}}
.sev.high{{background:rgba(255,145,0,.20);color:#FFE7C2;border-color:rgba(255,145,0,.45)}}
.sev.medium{{background:rgba(255,235,59,.22);color:#FFFDE7;border-color:rgba(255,235,59,.45)}}
.table-wrap{{overflow:auto;border-radius:12px;border:1px solid var(--cx-border)}}
.table{{width:100%;border-collapse:separate;border-spacing:0}}
.table thead th{{position:sticky;top:0;background:var(--cx-elev);color:#E3E6FF;text-align:left;font-weight:600;padding:10px 12px;border-bottom:1px solid var(--cx-border)}}
.table tbody td{{padding:10px 12px;border-bottom:1px solid var(--cx-border)}}
.table tbody tr:hover{{background:rgba(255,255,255,.02)}}
.table th.num,.table td.num{{text-align:right;width:120px}}
.muted{{color:var(--cx-muted)}} .tiny{{font-size:.8rem}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}}
pre{{white-space:pre-wrap;background:rgba(255,255,255,.03);border:1px solid var(--cx-border);border-radius:12px;padding:12px;overflow:auto}}
/* Pager */
.pager{{display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-top:12px}}
.pager-status{{color:var(--cx-muted);padding:0 4px}}
/* Buttons */
  .btn{{
    --bg:transparent; --fg:var(--cx-text); --bd:var(--cx-border);
    display:inline-flex;align-items:center;gap:8px;
    padding:10px 14px;border-radius:12px;border:1px solid var(--bd);
    background:var(--bg); color:var(--fg); text-decoration:none; cursor:pointer;
    transition:all .18s ease;
  }}
  .btn:hover{{transform:translateY(-1px)}}
  .btn.small{{padding:6px 10px;border-radius:10px;font-size:.85rem}}
  .btn.ghost{{--bd:var(--cx-border); --fg:#DDE1FF; --bg:rgba(255,255,255,.03)}}
  .btn.ghost:hover{{background:rgba(255,255,255,.06)}}
  .btn.primary{{
    --bg:linear-gradient(135deg, var(--cx-primary) 0%, #8B5CF6 50%, #6B34FC 100%);
    --bd:transparent; --fg:#fff; box-shadow:var(--cx-shadow);
  }}
  .btn.primary:hover{{filter:brightness(1.05)}}
  .btn:active{{transform:translateY(0) scale(.98)}}

</style>
</head>
<body class="cx-bg">
<div class="header">
  <div class="container header-inner">
    <div class="brand">
      <div class="brand-mark"></div>
      <div class="brand-text">Checkmarx One</div>
      <div class="sub">· Log Analysis</div>
    </div>
     <div class="nav-actions">
        <a class="btn ghost small" href="/">Home</a>
        <a class="btn primary small" href="https://docs.checkmarx.com/en/34965-67042-checkmarx-one.html" target="_blank" rel="noreferrer">Docs</a>
      </div>
  </div>
</div>

<div class="container">
  <!-- Meta -->
  <div class="muted tiny" style="margin:10px 0 14px">
    Project: {esc(meta.get('projectName') or info.get('project') or '—')} &nbsp; | &nbsp;
    Scan ID: {esc(meta.get('scanId') or info.get('scanId') or '—')} &nbsp; | &nbsp;
    Branch: {esc(meta.get('branch') or info.get('branch') or '—')} &nbsp; | &nbsp;
    SAST: {sast_start} → {sast_end} &nbsp;
  </div>

  <!-- KPIs -->
  <div class="row row-3">
    <div class="card">
      <div class="kpi-title">Coverage (Files)</div>
      <div class="kpi-val">{cov_files}</div>
      <div class="kpi-sub">Good: {gf} · Partial: {pf} · Bad: {bf} (of {total_files or '—'})</div>
    </div>
    <div class="card">
      <div class="kpi-title">Coverage (LOC)</div>
      <div class="kpi-val">{cov_loc}</div>
      <div class="kpi-sub">Good LOC: {esc(summary.get('goodLOC') or '—')} · Bad LOC: {esc(summary.get('badLOC') or '—')} (Parsed: {esc(summary.get('parsedLOC') or '—')})</div>
    </div>
    <div class="card">
      <div class="kpi-title">Exclusions</div>
      <div class="kpi-val">{int(excl.get('exclTotal') or 0)}</div>
      <div class="kpi-sub">Folders: {int(excl.get('exclFolders') or 0)} · Files: {int(excl.get('exclFiles') or 0)}</div>
    </div>
  </div>

  <!-- Parsing Summary + Mode -->
  <div class="row row-2cols" style="margin-top:14px">
    <div class="card">
      <h2>Parsing Summary</h2>
      <div class="psGrid">
        <div>{donut_svg(summary.get('coverageFiles'), 150, 'Scan coverage')}<div class="muted tiny">Scan coverage</div></div>
        <div>{donut_svg(summary.get('coverageLOC'), 120, 'LOC coverage')}<div class="muted tiny">Coverage (LOC)</div></div>
        <div>
          {stacked}
          <div class="legend">
            <span class="chip" style="background:{SVG_GOOD}"></span>Good
            <span class="chip" style="background:{SVG_PART}"></span>Partial
            <span class="chip" style="background:{SVG_BAD}"></span>Bad
          </div>
          <div class="muted tiny" style="margin-top:6px">
            Files: {gf} good · {pf} partial · {bf} bad<br/>
            LOC: {esc(summary.get('goodLOC') or '—')} good · {esc(summary.get('badLOC') or '—')} bad
          </div>
          <div class="muted tiny" style="margin-top:6px">DOM objects: {esc(summary.get('domObjects') or '—')}</div>
          <div class="muted tiny" style="margin-top:10px">
            <b>Language Mode:</b> {esc(langs.get('scanMode') or '—')}
            <br/><b>Identified Languages:</b> {ident_line_csv or '—'}
            <br/><b>Languages Scanned (count):</b> {scanned_count}
            <br/><b>Languages Scanned:</b> {scanned_line_csv or '—'}
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Vulnerabilities</h2>
      <div class="muted tiny" style="margin:0 0 8px">{esc(sev_line)}</div>
      <div class="muted tiny">{esc(top_title)}</div>
      {top_html}
    </div>
  </div>

  <!-- Sanity (single table) + Language stats -->
  <div class="row row-2cols" style="margin-top:14px">
    <div class="card">
      <h2>Sanity Check (Top 3 per category)</h2>
      <div class="muted tiny" style="margin:0 0 8px">Language: {esc(sanity_groups.get('language') or '—')}</div>
      <div class="table-wrap">
        <table class="table small">
          <thead><tr><th>Query</th><th>Type</th><th class='num'>Results</th></tr></thead>
          <tbody>
            { "".join(
              "<tr>"
              f"<td>{esc(r['name'])}</td>"
              f"<td>{esc(r['type'])}</td>"
              f"<td class='num'>{int(r['count'])}</td>"
              "</tr>"
              for r in sorted(
                sanity_rows,
                key=lambda rr: ({"Inputs":0,"Outputs":1,"Sanitize":2}.get(rr['type'],9), -int(rr['count']), rr['name'])
              )
            ) or "<tr><td colspan='3' class='muted'>No query results found.</td></tr>" }
          </tbody>
        </table>
      </div>
      <small class='muted tiny'>Top 3 in each category for the dominant language.</small>
    </div>

    <div class="card">
      <h2>Statistics per Language</h2>
      { (lambda rows:
        ("<div class='table-wrap'><table class='table small'>"
         "<thead><tr><th>Language</th><th class='num'>Files Identified</th>"
         "<th class='num'>Files Scanned</th><th class='num'>Coverage</th></tr></thead>"
         "<tbody>" + ''.join('<tr><td>'+esc(r.get('lang',''))+'</td><td class="num">'+str(int(r.get('ident',0)))+'</td><td class="num">'+str(int(r.get('scanned',0)))+'</td><td class="num">'+(pct(r.get('coverage')) if r.get('coverage') is not None else '—')+'</td></tr>' for r in rows) + "</tbody>"
         "</table></div>") if rows else "<div class='muted'>—</div>"
        )(lang_rows)
      }
    </div>
  </div>

  <!-- Files with Parsing Issues (collapsible + paginated) -->
  <div class="row row-2" style="margin-top:14px">
    <div class="card">
      <h2>Files with Parsing Issues</h2>
      { (lambda rows:
        (
          "<details open><summary>"+str(len(rows))+" files (click to toggle)</summary>"
          + "<div id='pi-wrap'></div>"
          + "<div class='pager'><button id='pi-prev' class='btn small ghost' disabled>Prev</button>"
          + "<span class='pager-status' id='pi-status'></span>"
          + "<button id='pi-next' class='btn small ghost'>Next</button></div>"
          + "<small class='muted tiny'>Heuristic extraction from parsing-error lines in the log.</small>"
          + "</details>"
          + "<script>(function(){const data = " + parse_issues_json + ";"
          + "const pageSize=20; let page=1; const total=data.length;"
          + "const wrap=document.getElementById('pi-wrap'); const prev=document.getElementById('pi-prev'); const next=document.getElementById('pi-next'); const status=document.getElementById('pi-status');"
          + "function render(){const start=(page-1)*pageSize; const end=Math.min(start+pageSize,total);"
          + "let html=`<div class='table-wrap'><table class='table small'><thead><tr><th>File path</th><th class='num'>Mentions</th></tr></thead><tbody>`;"
          + "for(let i=start;i<end;i++){const r=data[i]; html+=`<tr><td class='mono'>${r.path}</td><td class='num'>${r.count}</td></tr>`;}"
          + "html+=`</tbody></table></div>`; wrap.innerHTML=html; status.textContent=`Page ${page} of ${Math.max(1,Math.ceil(total/pageSize))} (${total} files)`; prev.disabled=(page<=1); next.disabled=(page>=Math.ceil(total/pageSize));}"
          + "prev.addEventListener('click',()=>{if(page>1){page--;render();}}); next.addEventListener('click',()=>{if(page<Math.ceil(total/pageSize)){page++;render();}}); render();})();</script>"
        ) if rows else "<div class='muted'>No parsing issues detected.</div>"
      )(parse_issues)}
    </div>
  </div>

  <!-- Excluded Files/Folders -->
  <div class="row row-2">
    <div class="card">
      <h2>Excluded Files/Folders</h2>
      {excl_table}
      <div style="margin-top:10px">{excl_lines_html}</div>
    </div>
  </div>

  <!-- Raw -->
  <div class="row row-2">
    <div class="card">
      <h2>Raw Log</h2>
      <pre>{esc(raw_log[:500000])}</pre>
    </div>
  </div>
</div>
</body></html>
"""
