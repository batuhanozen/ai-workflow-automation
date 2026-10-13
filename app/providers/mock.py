import re

from app.rules import critical_impact
from app.schemas import Category, Classification, Priority


class MockProvider:
    """Deterministic demo fixture logic, not an LLM or a quality benchmark."""

    name = "mock"
    model = "deterministic-v1"

    def classify(self, title: str, description: str) -> str:
        text = f"{title}\n{description}".lower()
        category = Category.GENERAL
        for candidate, pattern in [
            (
                Category.SECURITY,
                r"\b(phishing|malware|breach|ransomware|suspicious|exfiltration)\b",
            ),
            (Category.ACCOUNT, r"\b(password|login|log in|sign in|account|mfa|permission)\b"),
            (Category.INFRASTRUCTURE, r"\b(server|network|dns|database|outage|latency|cluster)\b"),
            (Category.SOFTWARE, r"\b(bug|crash\w*|application|software|export|error)\b"),
            (Category.IT, r"\b(laptop|printer|monitor|keyboard|headset|wifi)\b"),
        ]:
            if re.search(pattern, text):
                category = candidate
                break
        evidence = description[:600]
        impact = critical_impact(evidence)
        priority = Priority.MEDIUM
        if impact:
            priority = Priority.CRITICAL
            if impact == "security_incident":
                category = Category.SECURITY
        elif re.search(
            r"\b(cannot work|blocked|unable to work|cannot sign in|can't sign in)\b", text
        ):
            impact, priority = "individual_blocked", Priority.HIGH
        elif category == Category.SECURITY:
            priority = Priority.HIGH
        elif category == Category.GENERAL or re.search(r"\b(cosmetic|how to|new monitor)\b", text):
            priority = Priority.LOW
        return Classification(
            category=category,
            priority=priority,
            summary=f"Request: {title}",
            suggested_action=(
                f"Route to {category.value}; verify the reported impact with the requester."
            ),
            confidence=0.85 if impact else 0.72,
            evidence=evidence,
            impact=impact or "routine",
        ).model_dump_json()
