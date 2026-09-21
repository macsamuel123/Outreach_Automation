"""Pure validators for eval layer. No I/O, no external imports beyond stdlib."""

from dataclasses import dataclass, field
from typing import Literal

RecommendedAction = Literal["pass", "retry", "self_heal", "escalate"]
Severity = Literal["info", "warning", "critical"]


@dataclass
class EvalResult:
    passed: bool
    severity: Severity
    issues: list[str]
    recommended_action: RecommendedAction
    context: dict = field(default_factory=dict)


def validate_discover_item(
    item: dict, *, placeholder_values: list[str]
) -> EvalResult:
    """Validate a discover item before insert. No retry path exists."""
    issues = []

    company_name = (item.get("name") or item.get("company_name") or "").strip()
    if not company_name:
        return EvalResult(
            passed=False,
            severity="critical",
            issues=["missing_company_name: no company_name or name field"],
            recommended_action="escalate",
        )

    description = (item.get("description") or "").strip().lower()
    if description in placeholder_values or not description:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=["placeholder_description: description is a placeholder or empty"],
            recommended_action="self_heal",
        )

    return EvalResult(
        passed=True,
        severity="info",
        issues=[],
        recommended_action="pass",
    )


def validate_qualify(
    decision: str,
    reasoning: str,
    raw_decision: str,
    *,
    min_reasoning_length: int = 15,
) -> EvalResult:
    """Validate a qualify decision and reasoning."""
    issues = []

    if decision not in ("qualify", "reject"):
        return EvalResult(
            passed=False,
            severity="critical",
            issues=[f"invalid_decision: LLM returned {raw_decision!r}, normalized to {decision!r}"],
            recommended_action="self_heal",
        )

    if reasoning == "No reasoning provided":
        return EvalResult(
            passed=False,
            severity="warning",
            issues=["missing_reasoning_field: LLM omitted reasoning key"],
            recommended_action="retry",
        )

    if len(reasoning.strip()) < min_reasoning_length:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=[f"thin_reasoning: {len(reasoning.strip())} chars (min {min_reasoning_length})"],
            recommended_action="self_heal",
        )

    return EvalResult(
        passed=True,
        severity="info",
        issues=[],
        recommended_action="pass",
    )


def validate_enrich(
    candidates: list[dict],
    selected: dict,
    *,
    company_domain: str,
    min_confidence: int = 50,
) -> EvalResult:
    """Validate an enrich candidate selection."""
    issues = []

    if not candidates:
        return EvalResult(
            passed=True,
            severity="info",
            issues=[],
            recommended_action="pass",
        )

    max_confidence_candidate = max(candidates, key=lambda c: c.get("confidence", 0))
    if selected.get("confidence", 0) < max_confidence_candidate.get("confidence", 0):
        issues.append(
            f"not_highest_confidence_selected: selected {selected.get('confidence', 0)}, "
            f"max available {max_confidence_candidate.get('confidence', 0)}"
        )
        return EvalResult(
            passed=False,
            severity="warning",
            issues=issues,
            recommended_action="self_heal",
        )

    selected_confidence = selected.get("confidence", 0)
    if selected_confidence < min_confidence:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=[f"low_confidence_contact: {selected_confidence} (min {min_confidence})"],
            recommended_action="escalate",
        )

    return EvalResult(
        passed=True,
        severity="info",
        issues=[],
        recommended_action="pass",
    )


def validate_verify(result: dict) -> EvalResult:
    """Validate a verify result."""
    status = result.get("status", "unknown")

    if status == "risky":
        return EvalResult(
            passed=False,
            severity="warning",
            issues=["risky_result: Hunter classified as risky"],
            recommended_action="escalate",
        )

    if status == "unknown":
        return EvalResult(
            passed=False,
            severity="warning",
            issues=["unknown_result: Hunter cannot determine validity"],
            recommended_action="escalate",
        )

    if result.get("score") is None:
        return EvalResult(
            passed=False,
            severity="info",
            issues=["verify_api_score_missing: Hunter result lacks score field"],
            recommended_action="retry",
        )

    return EvalResult(
        passed=True,
        severity="info",
        issues=[],
        recommended_action="pass",
    )


def validate_draft(
    subject: str,
    body: str,
    *,
    require_subject_line: bool,
    min_body_length: int,
    max_body_length: int,
    placeholder_markers: list[str],
) -> EvalResult:
    """Validate a draft subject and body."""
    issues = []

    if require_subject_line and not subject.strip():
        return EvalResult(
            passed=False,
            severity="critical",
            issues=["missing_subject: subject is empty"],
            recommended_action="retry",
        )

    if not body.strip():
        return EvalResult(
            passed=False,
            severity="critical",
            issues=["missing_body: body is empty"],
            recommended_action="retry",
        )

    body_lower = body.lower()
    for marker in placeholder_markers:
        if marker.lower() in body_lower:
            issues.append(f"placeholder_leftover: contains '{marker}'")
            break

    if issues:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=issues,
            recommended_action="self_heal",
        )

    body_len = len(body)
    if body_len > max_body_length:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=[f"body_too_long: {body_len} chars (max {max_body_length})"],
            recommended_action="self_heal",
        )

    if body_len < min_body_length:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=[f"body_too_short: {body_len} chars (min {min_body_length})"],
            recommended_action="self_heal",
        )

    return EvalResult(
        passed=True,
        severity="info",
        issues=[],
        recommended_action="pass",
    )


def validate_followup(
    subject: str,
    body: str,
    *,
    min_body_length: int,
    max_body_length: int,
    placeholder_markers: list[str],
) -> EvalResult:
    """Validate a followup subject and body."""
    issues = []

    if not body.strip():
        return EvalResult(
            passed=False,
            severity="critical",
            issues=["missing_body: body is empty"],
            recommended_action="retry",
        )

    body_lower = body.lower()
    for marker in placeholder_markers:
        if marker.lower() in body_lower:
            issues.append(f"placeholder_leftover: contains '{marker}'")
            break

    if issues:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=issues,
            recommended_action="self_heal",
        )

    body_len = len(body)
    if body_len > max_body_length:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=[f"body_too_long: {body_len} chars (max {max_body_length})"],
            recommended_action="self_heal",
        )

    if body_len < min_body_length:
        return EvalResult(
            passed=False,
            severity="warning",
            issues=[f"body_too_short: {body_len} chars (min {min_body_length})"],
            recommended_action="self_heal",
        )

    if not subject.strip().lower().startswith("re:"):
        return EvalResult(
            passed=False,
            severity="info",
            issues=["subject_missing_re_prefix: subject should start with 'Re:'"],
            recommended_action="self_heal",
        )

    return EvalResult(
        passed=True,
        severity="info",
        issues=[],
        recommended_action="pass",
    )
