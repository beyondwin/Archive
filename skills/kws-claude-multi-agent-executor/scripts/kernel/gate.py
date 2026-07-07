"""gate.py — Risk assignment, wave partitioning, and preflight dispatch decisions.

CME v3.0 T11. Ported from CPE and ADAPTED for CME guardrails.

Public API
----------
assign_risk(tasks, override) -> dict[task_id, "low"|"mid"|"high"]
    Assign per-task risk levels per phase-0-setup.md Step 4.
    Includes shared-file LOW → MID promotion.

partition_waves(tasks, risk, parallel) -> list[list[str]]
    Dependency topo-sort + serial/resource_key singleton rules.
    Returns EXACTLY list[list[str]] — the shape transitions.decide already consumes.

preflight(task, packet, state) -> dict
    Per-task dispatch decision (D001 split):
      "delegate_parallel" | "delegate_serial" | "block"
    See D001: decisions/D001-local-fallback-adaptation.md

executability_audit(parsed_plan, packets) -> dict
    Per-task classification + dual blocking-issue counts.
    operator_reviewed_blocking_issues / operator_decision: T15 seam.

ADR Reference
-------------
D001: local_fallback adaptation — see decisions/D001-local-fallback-adaptation.md

Port sources (read-only, NOT modified)
--------------------------------------
- skills/kws-codex-plan-executor/scripts/preflight_dispatch.py
- skills/kws-codex-plan-executor/scripts/audit_plan_executability.py

CME rule oracle
---------------
- references/phases/phase-0-setup.md Steps 4 and 6
"""

from __future__ import annotations

import fnmatch
from typing import Any


# ── constants ─────────────────────────────────────────────────────────────────

# Risk keywords (phase-0-setup.md Step 4)
_HIGH_RISK_KEYWORDS = frozenset(
    ["high-risk", "schema migration", "database", "api surface", "breaking change"]
)

# Write-scope patterns that are "too broad" (port from CPE audit_common)
_TOO_BROAD_PATTERNS = ("**", "**/*", "**/*.py", "**/*.ts", "**/*.js", "**/*.go",
                       "**/*.java", "**/*.rs", "**/*.cpp", "**/*.c", "**/*.h",
                       "*.py", "*.ts", "*.js")


# ── helpers ───────────────────────────────────────────────────────────────────

def _contains_high_risk_keyword(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _HIGH_RISK_KEYWORDS)


def _write_scope_too_broad(pattern: str) -> bool:
    """Return True if pattern is too broad for safe delegated execution."""
    stripped = pattern.strip()
    return stripped in _TOO_BROAD_PATTERNS or stripped.startswith("**/")


def _has_risk_markers(packet: dict) -> bool:
    """Return True if packet declares explicit risk markers."""
    markers = packet.get("risk_markers") if isinstance(packet, dict) else None
    if isinstance(markers, list) and markers:
        return True
    return False


def _budget_status(packet: dict) -> str:
    """Extract context_budget status from packet (green/yellow/red/unknown)."""
    # packets.py stores budget directly, CPE stores under context_budget
    budget = packet.get("budget") or packet.get("context_budget")
    if isinstance(budget, dict):
        status = budget.get("status", "unknown")
        return status if isinstance(status, str) else "unknown"
    return "unknown"


def _allowed_write_globs(packet: dict) -> list[str]:
    policy = packet.get("write_policy") if isinstance(packet, dict) else {}
    if isinstance(policy, dict):
        globs = policy.get("allowed_write_globs", [])
        return [g for g in globs if isinstance(g, str)]
    return []


def _task_id(task: dict) -> str:
    return str(task.get("id", task.get("task_id", "unknown")))


def _task_files(task: dict) -> list[str]:
    return [f for f in task.get("files", []) if isinstance(f, str)]


def _task_acceptance(task: dict) -> str | None:
    return task.get("acceptance")


def _task_body(task: dict) -> str:
    return task.get("body", "") or ""


# ── assign_risk ───────────────────────────────────────────────────────────────

def assign_risk(tasks: list[dict], override: str | None) -> dict[str, str]:
    """Assign per-task risk levels.

    Rules (phase-0-setup.md Step 4):
    - low  — isolated change, single file or module, no shared state, no API surface
    - mid  — touches 2+ modules, shared state, moderate coupling, or config changes
    - high — cross-cutting, schema/API surface, or explicitly marked high-risk in plan

    After initial assignment: if a LOW task touches any file already touched by an
    earlier LOW task → upgrade the LATER task to MID (prevents batch-verifier file
    conflicts).

    If override is set: apply it to all tasks (override wins).

    Returns dict[task_id → "low"|"mid"|"high"].
    """
    if override is not None:
        override_level = override.strip().lower()
        if override_level not in ("low", "mid", "high"):
            override_level = "mid"
        # Phase-0 Step 4: warn when a risk override silently downgrades a task whose
        # body/title contains high-risk keywords (e.g. "database", "schema migration",
        # "breaking change").  The warning is emitted here to stdout so the orchestrator
        # log captures it.  The orchestrator layer (SKILL.md Step 4 escalate_to_user)
        # is responsible for surfacing this to the operator when running interactively.
        # T15 seam: in headless -p mode there is no escalate channel; the WARN line
        # is the only signal until T15 wires the interactive review path.
        if override_level in ("low", "mid"):
            for t in tasks:
                body_text = (_task_body(t) + " " + (t.get("title") or "")).lower()
                if _contains_high_risk_keyword(body_text):
                    print(
                        f"WARN: assign_risk override={override_level!r} applied to task "
                        f"{_task_id(t)!r} which contains high-risk keywords; "
                        f"do not silently downgrade dangerous tasks"
                    )
        return {_task_id(t): override_level for t in tasks}

    risk: dict[str, str] = {}
    for task in tasks:
        tid = _task_id(task)
        files = _task_files(task)
        body = _task_body(task)
        title = task.get("title", "") or ""
        text = (title + " " + body).lower()

        # HIGH: explicit keywords in body/title
        if _contains_high_risk_keyword(text):
            risk[tid] = "high"
        # MID: 2+ files or config-like path references
        elif len(files) >= 2:
            risk[tid] = "mid"
        elif any(".config." in f or "config/" in f or "settings" in f for f in files):
            risk[tid] = "mid"
        else:
            risk[tid] = "low"

    # Phase-0 Step 4: shared-file LOW → later task promoted to MID
    # Build: file → first LOW task that claims it
    claimed_by_low: dict[str, str] = {}
    ordered_ids = [_task_id(t) for t in tasks]
    for tid in ordered_ids:
        if risk.get(tid) == "low":
            task_files = []
            for t in tasks:
                if _task_id(t) == tid:
                    task_files = _task_files(t)
                    break
            for f in task_files:
                if f in claimed_by_low:
                    # This LOW task shares a file with an EARLIER LOW task → promote
                    risk[tid] = "mid"
                    break
                # First claim
            # Register files only if still low
            if risk.get(tid) == "low":
                for t in tasks:
                    if _task_id(t) == tid:
                        for f in _task_files(t):
                            if f not in claimed_by_low:
                                claimed_by_low[f] = tid
                        break

    return risk


# ── partition_waves ───────────────────────────────────────────────────────────

def partition_waves(
    tasks: list[dict],
    risk: dict[str, str],
    parallel: bool,
) -> list[list[str]]:
    """Partition tasks into execution waves.

    Returns EXACTLY list[list[str]] — the shape transitions.decide consumes.
    Each inner list is one execution group; a single-element list is sequential
    execution; multi-element list triggers parallel sub-flow (T15 seam).

    Phase-0 Step 6 rules:
    1. Wave N = tasks whose all deps are in waves 0..N-1 (topo-sort).
    2. Within a wave: tasks with overlapping files stay in their own singletons.
    3. serial:true tasks are always singletons (never merged).
    4. resource_key collision within a wave → both become singletons.

    parallel=False → degenerate [[t1],[t2],...] preserving plan order.
    """
    if parallel is False:
        return [[_task_id(t)] for t in tasks]

    # Build lookup maps
    id_to_task = {_task_id(t): t for t in tasks}
    ordered_ids = [_task_id(t) for t in tasks]

    # Build dependency map: task_id → set of task_ids it depends on
    # planparse stores dependencies as list[int] (task numbers, 1-based)
    num_to_id = {}
    for t in tasks:
        num = t.get("number")
        if num is not None:
            num_to_id[num] = _task_id(t)

    deps: dict[str, set[str]] = {}
    for t in tasks:
        tid = _task_id(t)
        dep_nums = t.get("dependencies", [])
        dep_ids = set()
        for dn in dep_nums:
            dep_tid = num_to_id.get(dn)
            if dep_tid:
                dep_ids.add(dep_tid)
        deps[tid] = dep_ids

    # Topo-sort into waves (greedy Kahn-style)
    placed: set[str] = set()
    waves: list[list[str]] = []

    remaining = list(ordered_ids)
    while remaining:
        # Tasks ready in this wave: all deps already placed
        wave_candidates = [
            tid for tid in remaining
            if deps.get(tid, set()).issubset(placed)
        ]
        if not wave_candidates:
            # Cycle or bad deps — treat rest as one final wave (safety fallback)
            wave_candidates = list(remaining)

        # Within wave: partition into parallel groups by file-disjointness
        # and resource_key/serial singleton rules.
        wave_groups = _partition_wave_groups(wave_candidates, id_to_task)

        waves.extend(wave_groups)
        for tid in wave_candidates:
            placed.add(tid)
        remaining = [t for t in remaining if t not in placed]

    return waves


def _partition_wave_groups(
    wave_ids: list[str],
    id_to_task: dict[str, dict],
) -> list[list[str]]:
    """Partition wave_ids into file-disjoint parallel groups.

    Rules:
    - serial:true → always singleton
    - resource_key collision → each colliding task becomes singleton
    - file overlap within a group → keep as singletons (cannot merge)

    Returns list[list[str]] where each inner list is one parallel group.
    """
    if not wave_ids:
        return []

    # Identify resource_key collisions within this wave
    rk_map: dict[str, list[str]] = {}
    for tid in wave_ids:
        task = id_to_task.get(tid, {})
        rk = task.get("resource_key")
        if rk:
            rk = rk.strip().lower()
            rk_map.setdefault(rk, []).append(tid)

    # resource_key singletons: any key with ≥ 2 tasks → all those tasks become singletons
    rk_singletons: set[str] = set()
    for rk, tids in rk_map.items():
        if len(tids) >= 2:
            rk_singletons.update(tids)

    groups: list[list[str]] = []
    # Assigned tracks which task_ids already got placed in a group
    assigned: set[str] = set()

    for tid in wave_ids:
        if tid in assigned:
            continue

        task = id_to_task.get(tid, {})
        files = set(_task_files(task))
        serial = task.get("serial", False)

        # Always singleton: serial flag or resource_key collision
        if serial or tid in rk_singletons:
            groups.append([tid])
            assigned.add(tid)
            continue

        # Try to merge with an existing compatible group
        merged = False
        for group in groups:
            # Skip groups that are singletons by rule (serial/resource_key)
            if len(group) == 1:
                existing_task = id_to_task.get(group[0], {})
                if existing_task.get("serial") or group[0] in rk_singletons:
                    continue
            # Check file overlap with entire group
            group_files: set[str] = set()
            for g_tid in group:
                group_files.update(_task_files(id_to_task.get(g_tid, {})))

            if not files.intersection(group_files):
                # No overlap → merge
                group.append(tid)
                assigned.add(tid)
                merged = True
                break

        if not merged:
            groups.append([tid])
            assigned.add(tid)

    return groups


# ── preflight ─────────────────────────────────────────────────────────────────

def preflight(task: dict, packet: dict, state: dict) -> dict:
    """Per-task dispatch preflight decision.

    Returns:
        {
            "decision": "delegate_parallel" | "delegate_serial" | "block",
            "reason": str,
            "would_have": {"decision": str, "reason": str} | None,
        }

    D001 split (see decisions/D001-local-fallback-adaptation.md):
    - Contention triggers (file overlap in wave, shared resource_key) → delegate_serial
    - Trust/risk triggers (risk_markers, spec fallback not reviewed) → block
    - Safety gates (file-claim collision, write-scope overflow, packet red) → block

    # T15 seam: delegate_parallel — multi-task parallel group dispatch.
    # The LLM orchestrator will launch parallel sub-worktrees per SKILL.md Phase 1
    # Parallel Sub-Flow. No sequential consumer exists in the T9 cycle.
    # delegate_parallel is produced when: no contention/serialization, clean packet,
    # task is part of a multi-task parallel group (state.parallel_group_size >= 2).
    """
    tid = _task_id(task)
    packet = packet or {}
    state = state or {}

    # ── Safety gates (always block) ──────────────────────────────────────────

    # 1. Parallel file-claim collision (another task in the same group already claims)
    parallel_claims = state.get("parallel_file_claims", {})
    if isinstance(parallel_claims, dict):
        task_files = set(_task_files(task))
        for f in task_files:
            if f in parallel_claims and parallel_claims[f] != tid:
                return {
                    "decision": "block",
                    "reason": f"parallel_file_claim_collision:{f} (already claimed by {parallel_claims[f]})",
                    "would_have": None,
                }

    # 2. Packet context budget red
    budget_status = _budget_status(packet)
    if budget_status == "red":
        return {
            "decision": "block",
            "reason": "packet_context_budget_red",
            "would_have": {"decision": "delegate_parallel", "reason": "all_prerequisites_passed"},
        }

    # 3. Write scope too broad
    allowed_globs = _allowed_write_globs(packet)
    if allowed_globs and any(_write_scope_too_broad(g) for g in allowed_globs):
        return {
            "decision": "block",
            "reason": "write_scope_too_broad",
            "would_have": {"decision": "delegate_parallel", "reason": "all_prerequisites_passed"},
        }

    # ── Trust/risk triggers (D001: block → escalate_to_user) ─────────────────
    # CPE mapped these to local_fallback (main agent implements with full context).
    # CME has NO main-agent-implements path → conservative floor is block.

    # 4. Explicit risk markers on packet
    if _has_risk_markers(packet):
        return {
            "decision": "block",
            "reason": "risk_marker_requires_operator_review",
            "would_have": {"decision": "delegate_serial", "reason": "contention_fallback"},
        }

    # 5. Spec fallback used and NOT operator-reviewed (trust/risk: ambiguity)
    spec = packet.get("spec") if isinstance(packet, dict) else None
    if isinstance(spec, dict) and spec.get("fallback_used") is True:
        mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
        if mapping.get("operator_reviewed") is not True:
            return {
                "decision": "block",
                "reason": "spec_fallback_not_operator_reviewed",
                "would_have": {"decision": "delegate_serial", "reason": "serialized_fallback"},
            }

    # ── Contention triggers (D001: delegate_serial) ───────────────────────────
    # These are the faithful substitute for CPE's local_fallback on contention:
    # still a subagent, just serialized within the wave.

    # 6. Explicit serialization_reason from orchestrator (wave partitioning injected)
    serialization_reason = state.get("serialization_reason")
    if serialization_reason in ("file_contention", "resource_key", "serial_flag"):
        return {
            "decision": "delegate_serial",
            "reason": f"serialized_by_{serialization_reason}",
            "would_have": {"decision": "delegate_parallel", "reason": "all_prerequisites_passed"},
        }

    # ── Determine parallel vs serial based on group context ──────────────────
    # T15 seam: delegate_parallel — the LLM orchestrator launches parallel sub-worktrees
    # per SKILL.md Phase 1 Parallel Sub-Flow. No sequential consumer exists in T9 cycle.
    # This path is reachable but has no downstream parallel launcher until T15.
    parallel_group_size = state.get("parallel_group_size", 1)
    if isinstance(parallel_group_size, int) and parallel_group_size >= 2:
        return {
            "decision": "delegate_parallel",  # T15 seam: no parallel launcher yet
            "reason": "multi_task_parallel_group",
            "would_have": None,
        }

    # Default: clean single-task group → serial subagent
    return {
        "decision": "delegate_serial",
        "reason": "all_prerequisites_passed",
        "would_have": None,
    }


# ── executability_audit ───────────────────────────────────────────────────────

def executability_audit(parsed_plan: dict, packets: dict[str, dict]) -> dict:
    """Per-plan executability audit.

    Args:
        parsed_plan: planparse.parse() output dict (has "tasks" list).
        packets:     dict[task_id → packet dict] (from packets.build_packet / load_packet).

    Returns:
        {
            "passed": bool,
            "grade": "green" | "yellow" | "red",
            "raw_blocking_issue_count": int,   # all blocking issues
            "blocking_issue_count": int,        # effective (after operator review waiver)
            "tasks": {
                task_id: {
                    "blocking_issues": [...],
                    "fixable_issues": [...],
                    "raw_blocking_issue_count": int,
                    "blocking_issue_count": int,
                    # T15 seam: operator_reviewed_blocking_issues / operator_decision
                    # Operator review happens via the SKILL.md escalate path (batch question).
                    # These fields are populated when the packet carries
                    # spec.mapping.operator_reviewed=True. No interactive operator
                    # review path exists in headless -p mode; T15 will wire the
                    # escalate_to_user batch-question path.
                    "operator_reviewed_blocking_issues": [...],
                    "operator_decision": None,
                }
            }
        }
    """
    task_results: dict[str, dict] = {}
    tasks = parsed_plan.get("tasks", []) if isinstance(parsed_plan, dict) else []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = _task_id(task)
        packet = packets.get(tid) if isinstance(packets, dict) else None
        task_results[tid] = _audit_task(task, packet)

    # Aggregate counts
    raw_total = sum(r["raw_blocking_issue_count"] for r in task_results.values())
    effective_total = sum(r["blocking_issue_count"] for r in task_results.values())
    fixable_total = sum(len(r.get("fixable_issues", [])) for r in task_results.values())

    grade = "red" if raw_total > 0 else ("yellow" if fixable_total > 0 else "green")

    return {
        "passed": effective_total == 0,
        "grade": grade,
        "raw_blocking_issue_count": raw_total,
        "blocking_issue_count": effective_total,
        "tasks": task_results,
    }


def _audit_task(task: dict, packet: dict | None) -> dict:
    """Audit a single task for executability issues.

    Returns per-task audit dict.

    # T15 seam: operator_reviewed_blocking_issues / operator_decision
    # These slots are populated when spec.mapping.operator_reviewed is True in the packet.
    # In headless -p mode there is no interactive operator; T15 will wire the
    # escalate_to_user batch-question path from SKILL.md for pre-run operator review.
    """
    blocking: list[str] = []
    fixable: list[str] = []

    files = _task_files(task)
    acceptance = _task_acceptance(task)

    # (d) Acceptance criteria missing — blocking for non-docs tasks
    acceptance_missing = not isinstance(acceptance, str) or not acceptance.strip()
    if acceptance_missing:
        # Check packet acceptance override
        if isinstance(packet, dict):
            pkt_acceptance = packet.get("acceptance")
            if isinstance(pkt_acceptance, dict):
                cmd = pkt_acceptance.get("command")
                if isinstance(cmd, str) and cmd.strip():
                    acceptance_missing = False
        if acceptance_missing:
            # docs-only tasks: fixable; others: blocking
            docs_only = files and all(
                f.endswith(".md") or f.endswith(".rst") or f.endswith(".txt")
                for f in files
            )
            if docs_only:
                fixable.append("acceptance_command_missing")
            else:
                blocking.append("acceptance_command_missing")

    # No files declared
    if not files:
        blocking.append("files_missing")

    # Write policy checks from packet
    if isinstance(packet, dict):
        policy = packet.get("write_policy") if isinstance(packet.get("write_policy"), dict) else {}
        allowed = [g for g in policy.get("allowed_write_globs", []) if isinstance(g, str)]

        if not allowed:
            blocking.append("allowed_write_globs_empty")

        if any(_write_scope_too_broad(g) for g in allowed):
            blocking.append("write_scope_too_broad")

        # Risk markers on packet
        if _has_risk_markers(packet):
            blocking.append("risk_marker_requires_operator_review")

        # Spec fallback not reviewed — always record as blocking; operator review waives it below.
        # Recording unconditionally lets raw_blocking_issue_count reflect the true risk,
        # even when the operator has already reviewed (raw > effective when waived).
        spec = packet.get("spec") if isinstance(packet.get("spec"), dict) else {}
        if spec.get("fallback_used") is True:
            blocking.append("full_spec_fallback_not_reviewed")

    # Deduplicate
    blocking = list(dict.fromkeys(blocking))
    fixable = list(dict.fromkeys(f for f in fixable if f not in blocking))

    # Operator review waiver: if packet has spec.mapping.operator_reviewed=True,
    # the risk_marker and spec_fallback issues are considered reviewed.
    # T15 seam: operator_decision is populated by the escalate_to_user path in T15.
    operator_reviewed_issues: list[str] = []
    operator_decision = None  # T15 seam: set via escalate_to_user batch-question path

    if isinstance(packet, dict):
        spec = packet.get("spec") if isinstance(packet.get("spec"), dict) else {}
        mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
        if mapping.get("operator_reviewed") is True:
            # Waive risk_marker and full_spec_fallback blocking issues
            for issue in ("risk_marker_requires_operator_review",
                          "full_spec_fallback", "full_spec_fallback_not_reviewed"):
                if issue in blocking:
                    operator_reviewed_issues.append(issue)
                    blocking.remove(issue)

    raw_blocking_count = len(blocking) + len(operator_reviewed_issues)
    effective_blocking_count = len(blocking)

    return {
        "blocking_issues": blocking,
        "fixable_issues": fixable,
        "raw_blocking_issue_count": raw_blocking_count,
        "blocking_issue_count": effective_blocking_count,
        # T15 seam: operator_reviewed_blocking_issues / operator_decision
        # Operator review waivers happen via the SKILL.md escalate_to_user batch-question path.
        # T15 will wire this interactive path; until then, populated from packet data only.
        "operator_reviewed_blocking_issues": operator_reviewed_issues,
        "operator_decision": operator_decision,
    }
