"""Conservative, deterministic priority guardrails; not incident verification."""

import re

from app.schemas import Category, Classification, Priority

NEGATION = re.compile(
    r"\b(no|not|never|without|false|resolved|test|drill|hypothetical|simulat\w*)\b", re.I
)
OUTAGE = re.compile(
    r"(?:\b(?:all users|entire company|all customers|company-wide|global)\b.{0,100}"
    r"\b(?:cannot|unable|unavailable|down|outage|offline)\b|"
    r"\b(?:production|payment|checkout)\b.{0,60}\b(?:down|outage|unavailable)\b"
    r".{0,80}\b(?:all users|all customers|globally)\b)",
    re.I,
)
SECURITY = re.compile(
    r"\b(?:confirmed|active|ongoing)\b.{0,70}\b(?:breach|ransomware|exfiltration|compromise)\b",
    re.I,
)


def critical_impact(text: str) -> str | None:
    for sentence in re.split(r"[.!?\n]", text):
        if NEGATION.search(sentence):
            continue
        if SECURITY.search(sentence):
            return "security_incident"
        if OUTAGE.search(sentence):
            return "widespread_outage"
    return None


class BusinessRuleError(ValueError):
    pass


def validate_business_rules(result: Classification, title: str, description: str) -> None:
    source = f"{title}\n{description}"
    if result.evidence not in source:
        raise BusinessRuleError("Evidence must quote the submitted request")
    if result.priority == Priority.CRITICAL:
        observed = critical_impact(result.evidence)
        # Check the source context too: a model must not crop 'no' or 'resolved'
        # out of a sentence to manufacture affirmative evidence.
        start = source.find(result.evidence)
        end = start + len(result.evidence)
        left = max(source.rfind(mark, 0, start) for mark in ".!?\n") + 1
        right_marks = [source.find(mark, end) for mark in ".!?\n"]
        right = min((position for position in right_marks if position >= 0), default=len(source))
        context_impact = critical_impact(source[left:right])
        if observed is None or result.impact != observed or context_impact != observed:
            raise BusinessRuleError(
                "Critical priority requires explicit incident or outage evidence"
            )
        if observed == "security_incident" and result.category != Category.SECURITY:
            raise BusinessRuleError("A confirmed security incident must use the Security category")
        if result.confidence < 0.8:
            raise BusinessRuleError("Critical priority requires confidence of at least 0.8")
