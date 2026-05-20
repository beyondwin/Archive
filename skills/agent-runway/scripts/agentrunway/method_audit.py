from __future__ import annotations


class MethodAuditError(ValueError):
    pass


def verify_method_audit(audit: dict[str, object], *, code_change: bool) -> None:
    if audit.get("superpowers_used") is not True:
        raise MethodAuditError("missing using-superpowers evidence")
    if code_change and not (audit.get("tdd_red") and audit.get("tdd_green")):
        raise MethodAuditError("missing TDD red/green evidence")
