"""Render a self-contained HTML forensics report for a multi-agent run archive.

Single-file Python, stdlib only. Reads:
  <archive_dir>/artifacts/archive_meta.json   (presence indicates archive succeeded)
  <archive_dir>/artifacts/state.final.json    (primary data source)
  <archive_dir>/meta.json                     (run metadata)
  <archive_dir>/events.jsonl                  (notable events)

Writes a single HTML file with 9 sections. No external CSS/JS/CDN.

Exit code is ALWAYS 0; on error a placeholder HTML is written.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# -----------------------------------------------------------------------------
# Color palette (per spec)
# -----------------------------------------------------------------------------
TIER_COLORS: dict[str, str] = {
    "PASS": "#10a37f",
    "WARN": "#d97706",
    "FAIL": "#dc2626",
    "SKIPPED": "#6b7280",
}
DEFAULT_COLOR = "#3b82f6"

DAG_NODE_LIMIT = 50


# -----------------------------------------------------------------------------
# IO helpers
# -----------------------------------------------------------------------------
def _read_json(path: Path) -> dict | list | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return out
    return out


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):.4f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(v: Any, ndigits: int = 2) -> str:
    try:
        return f"{float(v):.{ndigits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_duration(start: Any, end: Any) -> str:
    try:
        s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        secs = (e - s).total_seconds()
        if secs < 60:
            return f"{secs:.1f}s"
        if secs < 3600:
            return f"{secs / 60:.1f}m"
        return f"{secs / 3600:.2f}h"
    except Exception:
        return "—"


# -----------------------------------------------------------------------------
# SVG chart helpers (named exactly per spec)
# -----------------------------------------------------------------------------
def render_bar_chart(data: list[tuple[str, float]], title: str) -> str:
    """Horizontal bar chart as inline SVG."""
    if not data:
        return f'<div class="empty">No data for {_esc(title)}</div>'
    width = 480
    bar_h = 22
    gap = 8
    label_w = 140
    pad_top = 28
    pad_bottom = 16
    pad_right = 60
    n = len(data)
    height = pad_top + pad_bottom + n * (bar_h + gap)
    max_v = max((v for _, v in data), default=0.0) or 1.0
    chart_w = width - label_w - pad_right
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{_esc(title)}" xmlns="http://www.w3.org/2000/svg">',
        f'<text x="8" y="18" class="chart-title">{_esc(title)}</text>',
    ]
    for i, (label, value) in enumerate(data):
        y = pad_top + i * (bar_h + gap)
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        w = (v / max_v) * chart_w if max_v else 0
        parts.append(
            f'<text x="{label_w - 6}" y="{y + bar_h * 0.7:.0f}" '
            f'class="chart-label" text-anchor="end">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" '
            f'fill="{DEFAULT_COLOR}" rx="2"/>'
        )
        parts.append(
            f'<text x="{label_w + w + 4:.1f}" y="{y + bar_h * 0.7:.0f}" '
            f'class="chart-value">{_esc(_fmt_num(v, 4))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_line_chart(
    series: dict[str, list[float]], x_labels: list[str], title: str
) -> str:
    """Multi-series line chart as inline SVG."""
    if not series or not any(series.values()):
        return f'<div class="empty">No data for {_esc(title)}</div>'
    width = 640
    height = 280
    pad_left = 44
    pad_right = 16
    pad_top = 32
    pad_bottom = 36
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    # Determine global x count
    n_x = max((len(v) for v in series.values()), default=0)
    n_x = max(n_x, len(x_labels))
    if n_x < 1:
        return f'<div class="empty">No data for {_esc(title)}</div>'
    all_vals = [v for vals in series.values() for v in vals if isinstance(v, (int, float))]
    if not all_vals:
        return f'<div class="empty">No data for {_esc(title)}</div>'
    y_min = min(all_vals)
    y_max = max(all_vals)
    if math.isclose(y_min, y_max):
        y_min -= 0.5
        y_max += 0.5
    span = y_max - y_min
    palette = ["#2563eb", "#10a37f", "#d97706", "#dc2626", "#7c3aed", "#0891b2"]

    def x_pos(i: int) -> float:
        if n_x == 1:
            return pad_left + plot_w / 2
        return pad_left + (i / (n_x - 1)) * plot_w

    def y_pos(v: float) -> float:
        return pad_top + (1 - (v - y_min) / span) * plot_h

    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{_esc(title)}" xmlns="http://www.w3.org/2000/svg">',
        f'<text x="8" y="18" class="chart-title">{_esc(title)}</text>',
        # axes
        f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" '
        f'y2="{pad_top + plot_h}" class="axis"/>',
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" '
        f'x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" class="axis"/>',
        # y-axis ticks (3)
        f'<text x="{pad_left - 4}" y="{pad_top + 4}" class="axis-label" '
        f'text-anchor="end">{_esc(_fmt_num(y_max, 2))}</text>',
        f'<text x="{pad_left - 4}" y="{pad_top + plot_h / 2 + 4:.0f}" '
        f'class="axis-label" text-anchor="end">'
        f'{_esc(_fmt_num((y_min + y_max) / 2, 2))}</text>',
        f'<text x="{pad_left - 4}" y="{pad_top + plot_h + 4}" '
        f'class="axis-label" text-anchor="end">{_esc(_fmt_num(y_min, 2))}</text>',
    ]
    # x-labels (sample)
    sample_n = min(n_x, 6)
    for i in range(sample_n):
        idx = round(i * (n_x - 1) / (sample_n - 1)) if sample_n > 1 else 0
        lbl = x_labels[idx] if idx < len(x_labels) else str(idx)
        parts.append(
            f'<text x="{x_pos(idx):.1f}" y="{pad_top + plot_h + 18}" '
            f'class="axis-label" text-anchor="middle">{_esc(lbl)}</text>'
        )
    # series
    for s_idx, (name, vals) in enumerate(series.items()):
        color = palette[s_idx % len(palette)]
        pts = []
        for i, v in enumerate(vals):
            if not isinstance(v, (int, float)):
                continue
            pts.append(f"{x_pos(i):.1f},{y_pos(v):.1f}")
        if not pts:
            continue
        parts.append(
            f'<polyline points="{" ".join(pts)}" fill="none" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        for pt in pts:
            x, y = pt.split(",")
            parts.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="{color}"/>')
        # legend
        ly = pad_top + s_idx * 16
        parts.append(
            f'<rect x="{pad_left + plot_w - 110}" y="{ly}" width="10" '
            f'height="10" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{pad_left + plot_w - 96}" y="{ly + 9}" '
            f'class="legend">{_esc(name)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_dag(
    nodes: list[dict], edges: list[tuple[str, str]], colors: dict[str, str]
) -> str:
    """Greedy layered DAG. If >50 nodes, returns empty string (caller falls back)."""
    if len(nodes) > DAG_NODE_LIMIT:
        return ""
    if not nodes:
        return '<div class="empty">No tasks to graph.</div>'

    by_id = {n["id"]: n for n in nodes}
    adj_in: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    adj_out: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    for a, b in edges:
        if a in by_id and b in by_id:
            adj_out[a].add(b)
            adj_in[b].add(a)

    # Greedy topological layering
    levels: dict[str, int] = {}
    remaining = set(by_id.keys())
    layer = 0
    safety = 0
    while remaining and safety < 1000:
        safety += 1
        layer_nodes = [
            nid for nid in remaining
            if all(p in levels for p in adj_in[nid])
        ]
        if not layer_nodes:
            # Cycle — assign all remaining to current layer
            layer_nodes = list(remaining)
        for nid in layer_nodes:
            levels[nid] = layer
        remaining -= set(layer_nodes)
        layer += 1

    by_layer: dict[int, list[str]] = defaultdict(list)
    for nid, lvl in levels.items():
        by_layer[lvl].append(nid)

    node_w = 140
    node_h = 40
    h_gap = 50
    v_gap = 20
    pad = 20
    n_layers = max(by_layer) + 1 if by_layer else 1
    max_per_layer = max((len(v) for v in by_layer.values()), default=1)
    width = pad * 2 + n_layers * node_w + (n_layers - 1) * h_gap
    height = pad * 2 + max_per_layer * node_h + (max_per_layer - 1) * v_gap

    positions: dict[str, tuple[float, float]] = {}
    for lvl in range(n_layers):
        col = by_layer.get(lvl, [])
        col.sort()
        col_h = len(col) * node_h + (len(col) - 1) * v_gap if col else 0
        y0 = pad + (height - 2 * pad - col_h) / 2
        for i, nid in enumerate(col):
            x = pad + lvl * (node_w + h_gap)
            y = y0 + i * (node_h + v_gap)
            positions[nid] = (x, y)

    parts = [
        f'<svg class="dag" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Dependency DAG">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af"/></marker></defs>',
    ]
    # edges first
    for a, b in edges:
        if a not in positions or b not in positions:
            continue
        ax, ay = positions[a]
        bx, by = positions[b]
        x1 = ax + node_w
        y1 = ay + node_h / 2
        x2 = bx
        y2 = by + node_h / 2
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>'
        )
    # nodes
    for nid, (x, y) in positions.items():
        tier = by_id[nid].get("tier", "SKIPPED")
        color = colors.get(tier, DEFAULT_COLOR)
        label = by_id[nid].get("label", nid)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w}" height="{node_h}" '
            f'rx="6" fill="{color}" stroke="#1f2937" stroke-width="0.5"/>'
        )
        parts.append(
            f'<text x="{x + node_w / 2:.1f}" y="{y + node_h / 2 + 4:.1f}" '
            f'class="dag-label" text-anchor="middle">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# -----------------------------------------------------------------------------
# Data extraction
# -----------------------------------------------------------------------------
def _collect_tasks(state: dict) -> list[dict]:
    """Flatten tasks from state + plan_chain into list of normalized dicts."""
    rows: list[dict] = []

    def _push(plan_name: str, tid: str, t: dict) -> None:
        rows.append(
            {
                "plan": plan_name,
                "id": tid,
                "status": t.get("status", ""),
                "risk": t.get("risk", ""),
                "complexity": t.get("complexity", ""),
                "spec_score": t.get("spec_score", ""),
                "quality_score": t.get("quality_score", ""),
                "tier": t.get("review_tier", ""),
                "retries": t.get("retries", 0),
                "escalations": t.get("escalations", 0),
                "duration": t.get("duration_seconds", t.get("duration", "")),
                "cost": t.get("cost_usd", t.get("cost", "")),
                "raw": t,
            }
        )

    top_tasks = state.get("tasks") or {}
    if isinstance(top_tasks, dict):
        for tid, t in top_tasks.items():
            if isinstance(t, dict):
                _push("primary", tid, t)
    plan_chain = state.get("plan_chain") or []
    if isinstance(plan_chain, list):
        for entry in plan_chain:
            if not isinstance(entry, dict):
                continue
            pname = entry.get("plan_path") or entry.get("name") or "plan"
            tasks = entry.get("tasks") or {}
            if isinstance(tasks, dict):
                for tid, t in tasks.items():
                    if isinstance(t, dict):
                        _push(str(pname), tid, t)
    return rows


def _cost_data(state: dict) -> tuple[list[tuple[str, float]], list[tuple[str, float]], float]:
    ledger = state.get("cost_ledger") or {}
    by_role_raw = ledger.get("by_role") or {}
    by_model_raw = ledger.get("by_model") or {}
    total = float(ledger.get("total_usd") or ledger.get("total") or 0.0) if ledger else 0.0

    def _flat(d: Any) -> list[tuple[str, float]]:
        if not isinstance(d, dict):
            return []
        out: list[tuple[str, float]] = []
        for k, v in d.items():
            try:
                if isinstance(v, dict):
                    # Try common keys
                    val = v.get("cost_usd") or v.get("total_usd") or v.get("usd") or 0.0
                else:
                    val = v
                out.append((str(k), float(val)))
            except (TypeError, ValueError):
                continue
        out.sort(key=lambda kv: kv[1], reverse=True)
        return out

    return _flat(by_role_raw), _flat(by_model_raw), total


def _quality_series(state: dict) -> tuple[dict[str, list[float]], list[str]]:
    series: dict[str, list[float]] = {}
    max_len = 0
    plan_chain = state.get("plan_chain") or []
    if isinstance(plan_chain, list) and plan_chain:
        for entry in plan_chain:
            if not isinstance(entry, dict):
                continue
            qt = entry.get("quality_trend") or []
            if isinstance(qt, list) and qt:
                vals = [float(x) for x in qt if isinstance(x, (int, float))]
                if vals:
                    name = entry.get("plan_path") or entry.get("name") or f"plan{len(series)}"
                    series[str(name)] = vals
                    max_len = max(max_len, len(vals))
    if not series:
        qt = state.get("quality_trend") or []
        if isinstance(qt, list) and qt:
            vals = [float(x) for x in qt if isinstance(x, (int, float))]
            if vals:
                series["primary"] = vals
                max_len = len(vals)
    x_labels = [f"t{i + 1}" for i in range(max_len)]
    return series, x_labels


def _dag_inputs(state: dict, tasks_rows: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []
    plan = state.get("execution_plan") or {}
    by_id = {r["id"]: r for r in tasks_rows}
    seen_ids: set[str] = set()

    if isinstance(plan, dict):
        tasks_def = plan.get("tasks") or plan.get("nodes") or []
        if isinstance(tasks_def, list):
            for tdef in tasks_def:
                if not isinstance(tdef, dict):
                    continue
                tid = str(tdef.get("id", ""))
                if not tid:
                    continue
                seen_ids.add(tid)
                tier = (by_id.get(tid) or {}).get("tier") or "SKIPPED"
                label = tdef.get("label") or tid
                nodes.append({"id": tid, "label": label, "tier": tier})
                deps = tdef.get("deps") or tdef.get("depends_on") or []
                if isinstance(deps, list):
                    for d in deps:
                        edges.append((str(d), tid))

    # Fallback: synthesize from tasks_rows if no execution_plan
    if not nodes:
        for r in tasks_rows:
            tid = r["id"]
            if tid in seen_ids:
                continue
            tier = r.get("tier") or "SKIPPED"
            nodes.append({"id": tid, "label": tid, "tier": tier})

    return nodes, edges


# -----------------------------------------------------------------------------
# Section renderers
# -----------------------------------------------------------------------------
def _section(idx: int, title: str, body_html: str, *, collapsible_id: str | None = None) -> str:
    sid = collapsible_id or f"sec-{idx}"
    return (
        f'<section class="section" id="{sid}">'
        f'<h2 class="section-h"><span class="section-num">{idx}.</span> {_esc(title)}</h2>'
        f'<div class="section-body">{body_html}</div>'
        f"</section>"
    )


def _run_summary(state: dict, meta: dict, tasks_rows: list[dict], total_cost: float) -> str:
    plan = meta.get("plan_path") or state.get("plan_path") or "—"
    spec = meta.get("spec_path") or state.get("spec_path") or "—"
    branch = meta.get("branch") or state.get("branch") or "—"
    run_id = meta.get("run_id") or "—"
    outcome = meta.get("outcome") or state.get("outcome") or "—"
    duration = _fmt_duration(meta.get("started_at"), meta.get("completed_at"))
    dispatch_count = (
        state.get("dispatch_count")
        or len(state.get("dispatch_log") or [])
        or len(tasks_rows)
    )
    cards = [
        ("Plan", plan),
        ("Spec", spec),
        ("Branch", branch),
        ("Run ID", run_id),
        ("Outcome", outcome),
        ("Duration", duration),
        ("Total cost", _fmt_money(total_cost)),
        ("Dispatches", str(dispatch_count)),
    ]
    items = "".join(
        f'<div class="card"><div class="card-k">{_esc(k)}</div>'
        f'<div class="card-v">{_esc(v)}</div></div>'
        for k, v in cards
    )
    return f'<div class="cards">{items}</div>'


def _task_table(tasks_rows: list[dict]) -> str:
    if not tasks_rows:
        return '<div class="empty">No tasks recorded.</div>'
    cols = [
        ("plan", "Plan"),
        ("id", "ID"),
        ("status", "Status"),
        ("risk", "Risk"),
        ("complexity", "Complexity"),
        ("spec_score", "Spec score"),
        ("quality_score", "Quality"),
        ("tier", "Tier"),
        ("retries", "Retries"),
        ("escalations", "Escalations"),
        ("duration", "Duration"),
        ("cost", "Cost"),
    ]
    head = "".join(
        f'<th data-key="{_esc(k)}" class="sortable">{_esc(label)} <span class="sort-ind"></span></th>'
        for k, label in cols
    )
    rows = []
    for r in tasks_rows:
        cells = []
        for k, _label in cols:
            v = r.get(k, "")
            if k == "cost":
                txt = _fmt_money(v) if v not in ("", None) else "—"
            elif k in ("spec_score", "quality_score") and v not in ("", None):
                txt = _fmt_num(v, 3)
            elif k == "duration" and isinstance(v, (int, float)):
                txt = f"{float(v):.1f}s"
            else:
                txt = _esc(v) if v not in ("", None) else "—"
            extra = ""
            if k == "tier" and v in TIER_COLORS:
                extra = f' style="color:{TIER_COLORS[v]};font-weight:600"'
            cells.append(f"<td{extra}>{txt}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="task-table">'
        f"<thead><tr>{head}</tr></thead>"
        f'<tbody>{"".join(rows)}</tbody>'
        "</table></div>"
    )


def _cost_section(by_role: list[tuple[str, float]], by_model: list[tuple[str, float]], total: float) -> str:
    if not by_role and not by_model:
        return '<div class="empty">No cost ledger present.</div>'
    return (
        f'<div class="cost-total">Total: <strong>{_fmt_money(total)}</strong></div>'
        '<div class="charts-row">'
        f'<div class="chart-wrap">{render_bar_chart(by_role, "Cost by role (USD)")}</div>'
        f'<div class="chart-wrap">{render_bar_chart(by_model, "Cost by model (USD)")}</div>'
        "</div>"
    )


def _quality_section(series: dict[str, list[float]], x_labels: list[str]) -> str:
    if not series:
        return '<div class="empty">No quality trend data.</div>'
    return render_line_chart(series, x_labels, "Quality trend")


def _dag_section(state: dict, tasks_rows: list[dict]) -> str:
    nodes, edges = _dag_inputs(state, tasks_rows)
    if not nodes:
        return '<div class="empty">No execution graph available.</div>'
    if len(nodes) > DAG_NODE_LIMIT:
        rows = []
        for n in nodes:
            tier = n.get("tier", "")
            color = TIER_COLORS.get(tier, "")
            style = f' style="color:{color};font-weight:600"' if color else ""
            rows.append(
                f"<tr><td>{_esc(n.get('label', n['id']))}</td>"
                f"<td>{_esc(n['id'])}</td>"
                f"<td{style}>{_esc(tier)}</td></tr>"
            )
        return (
            '<div class="empty">Graph has more than '
            f"{DAG_NODE_LIMIT} nodes — showing table fallback.</div>"
            '<div class="table-wrap"><table class="task-table">'
            "<thead><tr><th>Label</th><th>ID</th><th>Tier</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>'
        )
    return render_dag(nodes, edges, TIER_COLORS)


def _warn_section(tasks_rows: list[dict]) -> str:
    warn = [r for r in tasks_rows if r.get("tier") == "WARN"]
    if not warn:
        return '<div class="empty">No WARN tasks.</div>'
    blocks = []
    for r in warn:
        raw = r.get("raw") or {}
        ts = raw.get("task_summaries") or {}
        warnings = ts.get("warnings") or raw.get("warnings") or []
        if isinstance(warnings, str):
            warnings = [warnings]
        if not isinstance(warnings, list):
            warnings = []
        items = "".join(f"<li>{_esc(w)}</li>" for w in warnings) or "<li>(no warning text)</li>"
        blocks.append(
            f'<details class="warn-block"><summary><strong>{_esc(r["id"])}</strong> '
            f'<span class="muted">({_esc(r.get("plan", ""))})</span></summary>'
            f"<ul>{items}</ul></details>"
        )
    return "".join(blocks)


def _method_audit_section(tasks_rows: list[dict]) -> str:
    if not tasks_rows:
        return '<div class="empty">No tasks recorded.</div>'
    rows = []
    any_evidence = False
    for r in tasks_rows:
        raw = r.get("raw") or {}
        ma = raw.get("method_audit") or {}
        applied = ma.get("applied") or []
        missing = ma.get("missing") or []
        waived = ma.get("waived") or []
        if not (applied or missing or waived):
            continue
        any_evidence = True
        rows.append(
            f"<tr><td>{_esc(r['id'])}</td>"
            f"<td>{_esc(', '.join(map(str, applied)) or '—')}</td>"
            f"<td>{_esc(', '.join(map(str, missing)) or '—')}</td>"
            f"<td>{_esc(', '.join(map(str, waived)) or '—')}</td></tr>"
        )
    if not any_evidence:
        return '<div class="empty">No method audit entries recorded.</div>'
    return (
        '<div class="table-wrap"><table class="task-table">'
        "<thead><tr><th>Task</th><th>Applied</th><th>Missing</th><th>Waived</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _spec_edits_section(state: dict) -> str:
    edits = state.get("spec_edits") or []
    if not isinstance(edits, list) or not edits:
        return '<div class="empty">No spec edits recorded.</div>'
    items = []
    for e in edits:
        if not isinstance(e, dict):
            continue
        ts = e.get("timestamp") or e.get("ts") or ""
        who = e.get("agent") or e.get("who") or ""
        desc = e.get("description") or e.get("note") or e.get("change") or ""
        items.append(
            f'<li><span class="muted">{_esc(ts)}</span> '
            f'<strong>{_esc(who)}</strong> — {_esc(desc)}</li>'
        )
    if not items:
        return '<div class="empty">No spec edits recorded.</div>'
    return f'<ol class="timeline">{"".join(items)}</ol>'


def _events_section(events: list[dict]) -> str:
    if not events:
        return '<div class="empty">No notable events.</div>'
    counter: Counter[str] = Counter()
    for e in events:
        counter[str(e.get("event_type") or e.get("type") or "unknown")] += 1
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        key = str(e.get("event_type") or e.get("type") or "unknown")
        grouped[key].append(e)
    blocks = []
    for kind, count in counter.most_common():
        sample = grouped[kind][:50]
        items = "".join(
            f"<li><code>{_esc(json.dumps(s, default=str))[:240]}</code></li>"
            for s in sample
        )
        blocks.append(
            f'<details class="event-block"><summary>'
            f'<strong>{_esc(kind)}</strong> <span class="muted">×{count}</span>'
            f"</summary><ul>{items}</ul></details>"
        )
    return "".join(blocks)


# -----------------------------------------------------------------------------
# Top-level rendering
# -----------------------------------------------------------------------------
CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  margin:0;padding:24px;background:#f9fafb;color:#111827;line-height:1.45;font-size:14px}
h1{font-size:22px;margin:0 0 4px}
h2.section-h{font-size:17px;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid #e5e7eb}
.section-num{color:#6b7280;font-weight:400;margin-right:6px}
.section{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px 20px;margin:14px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.card{background:#f3f4f6;border-radius:6px;padding:10px 12px}
.card-k{font-size:11px;text-transform:uppercase;color:#6b7280;letter-spacing:0.04em}
.card-v{font-size:14px;font-weight:600;word-break:break-word}
.table-wrap{overflow-x:auto}
.task-table{width:100%;border-collapse:collapse;font-size:13px}
.task-table th,.task-table td{padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}
.task-table th{background:#f3f4f6;font-weight:600;cursor:pointer;user-select:none}
.task-table th.sortable:hover{background:#e5e7eb}
.sort-ind{font-size:10px;color:#9ca3af;margin-left:2px}
.chart{max-width:100%;height:auto}
.chart-title{font-size:13px;font-weight:600;fill:#111827}
.chart-label{font-size:11px;fill:#374151}
.chart-value{font-size:11px;fill:#6b7280}
.axis{stroke:#9ca3af;stroke-width:1}
.axis-label{font-size:10px;fill:#6b7280}
.legend{font-size:11px;fill:#374151}
.dag{max-width:100%;height:auto;background:#fff}
.dag-label{font-size:11px;fill:#fff;font-weight:600}
.charts-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px}
.chart-wrap{background:#fafafa;border-radius:6px;padding:8px}
.cost-total{margin-bottom:8px;font-size:13px}
.empty{color:#6b7280;font-style:italic;padding:6px 0}
.muted{color:#6b7280}
.warn-block,.event-block{margin:6px 0;border:1px solid #e5e7eb;border-radius:6px;padding:8px 10px;background:#fafafa}
.warn-block summary,.event-block summary{cursor:pointer;font-weight:500}
.timeline{margin:0;padding-left:18px}
.timeline li{margin-bottom:4px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;background:#f3f4f6;padding:1px 4px;border-radius:3px;word-break:break-all}
header.run-header{margin-bottom:8px}
.subtitle{color:#6b7280;font-size:12px}
@media print{
  body{background:#fff;padding:0}
  .section{break-inside:avoid;border:none;padding:8px 0}
  .section:nth-of-type(n+3){page-break-before:always}
  details{}
  details>summary{list-style:none;cursor:default}
  details[open]>summary, details>summary{pointer-events:none}
  /* Force expansion of collapsibles */
  details>*:not(summary){display:block !important}
  .task-table th{cursor:default}
  .sort-ind{display:none}
}
"""

JS = """
(function(){
  // Sort task tables
  function cmp(a,b){
    var na=parseFloat(a), nb=parseFloat(b);
    if(!isNaN(na)&&!isNaN(nb)) return na-nb;
    return (a||'').localeCompare(b||'');
  }
  document.querySelectorAll('.task-table').forEach(function(tbl){
    var thead=tbl.querySelector('thead');
    if(!thead) return;
    var ths=thead.querySelectorAll('th.sortable');
    ths.forEach(function(th,i){
      th.addEventListener('click',function(){
        var tbody=tbl.querySelector('tbody');
        if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll('tr'));
        var dir=th.dataset.dir==='asc'?'desc':'asc';
        ths.forEach(function(o){o.dataset.dir='';o.querySelector('.sort-ind').textContent='';});
        th.dataset.dir=dir;
        th.querySelector('.sort-ind').textContent=dir==='asc'?'▲':'▼';
        rows.sort(function(r1,r2){
          var c=cmp(r1.children[i].textContent.trim(),r2.children[i].textContent.trim());
          return dir==='asc'?c:-c;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      });
    });
  });
})();
"""


def render_report(archive_dir: Path) -> str:
    state = _read_json(archive_dir / "artifacts" / "state.final.json")
    if not isinstance(state, dict):
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Report unavailable</title></head>"
            "<body><h1>Report unavailable — state.final.json missing</h1></body></html>"
        )
    meta = _read_json(archive_dir / "meta.json") or {}
    if not isinstance(meta, dict):
        meta = {}
    events = _read_jsonl(archive_dir / "events.jsonl")

    tasks_rows = _collect_tasks(state)
    by_role, by_model, total_cost = _cost_data(state)
    q_series, q_x = _quality_series(state)

    title = f"Run report — {_esc(meta.get('run_id') or 'unknown')}"
    sections = [
        _section(1, "Run summary", _run_summary(state, meta, tasks_rows, total_cost)),
        _section(2, "Task table", _task_table(tasks_rows)),
        _section(3, "Cost breakdown", _cost_section(by_role, by_model, total_cost)),
        _section(4, "Quality trend", _quality_section(q_series, q_x)),
        _section(5, "Dependency DAG", _dag_section(state, tasks_rows)),
        _section(6, "WARN tasks", _warn_section(tasks_rows)),
        _section(7, "Method audit", _method_audit_section(tasks_rows)),
        _section(8, "Spec edits", _spec_edits_section(state)),
        _section(9, "Events summary", _events_section(events)),
    ]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title>"
        f"<style>{CSS}</style></head><body>"
        f'<header class="run-header"><h1>{title}</h1>'
        f'<div class="subtitle">Generated {_esc(generated_at)}</div></header>'
        + "".join(sections)
        + f"<script>{JS}</script>"
        "</body></html>"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Render forensics HTML report.")
    p.add_argument("--archive-dir", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    archive_dir = Path(args.archive_dir)
    output = Path(args.output)
    try:
        html_text = render_report(archive_dir)
    except Exception as e:  # pragma: no cover - safety net
        html_text = (
            "<!doctype html><html><body>"
            f"<h1>Report unavailable — {html.escape(str(e))}</h1>"
            "</body></html>"
        )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html_text, encoding="utf-8")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
