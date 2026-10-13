import json

import pytest
from pydantic import ValidationError

from app.pipeline import Pipeline
from app.providers.base import ProviderError
from app.providers.mock import MockProvider
from app.rules import BusinessRuleError, validate_business_rules
from app.schemas import Classification


class SequenceProvider:
    name = "mock"
    model = "sequence-test"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def classify(self, title, description):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def valid_output(payload):
    return MockProvider().classify(**payload)


def test_valid_pipeline(settings, payload):
    result = Pipeline(MockProvider(), settings).run(**payload)
    assert not result.is_fallback
    assert result.classification.category == "Account Access"
    assert result.schema_valid


@pytest.mark.parametrize("raw", ["not JSON", "{}", "```json\n{}\n```", "null", "[]"])
def test_invalid_json_and_shape_fall_back(settings, payload, raw):
    result = Pipeline(SequenceProvider([raw]), settings).run(**payload)
    assert result.is_fallback and not result.schema_valid
    assert result.classification.confidence == 0
    assert result.errors[0].code == "schema_validation"
    assert result.attempts == 1


@pytest.mark.parametrize(
    "change",
    [
        {"confidence": "0.9"},
        {"confidence": True},
        {"confidence": 2.0},
        {"confidence": -0.2},
        {"category": "Anything"},
        {"priority": "Urgent"},
        {"extra": 1},
        {"summary": " "},
        {"suggested_action": None},
        {"impact": "catastrophic"},
    ],
)
def test_strict_schema(payload, change):
    raw = json.loads(valid_output(payload))
    raw.update(change)
    with pytest.raises(ValidationError):
        Classification.model_validate_json(json.dumps(raw))


def test_retry_exponential_backoff(settings, payload):
    settings.llm_backoff_seconds = 0.25
    provider = SequenceProvider(
        [
            ProviderError("timeout", "Timed out", True),
            ProviderError("upstream_transient", "Unavailable", True),
            valid_output(payload),
        ]
    )
    delays = []
    result = Pipeline(provider, settings, sleep=delays.append).run(**payload)
    assert delays == [0.25, 0.5]
    assert provider.calls == result.attempts == 3
    assert not result.is_fallback
    assert len(result.errors) == 2


def test_retry_exhaustion(settings, payload):
    provider = SequenceProvider([ProviderError("timeout", "Timed out", True)] * 3)
    result = Pipeline(provider, settings).run(**payload)
    assert result.is_fallback and result.attempts == 3
    assert len(result.errors) == 3


def test_permanent_failure_is_not_retried(settings, payload):
    provider = SequenceProvider([ProviderError("upstream_rejected", "Rejected")])
    result = Pipeline(provider, settings).run(**payload)
    assert result.is_fallback and provider.calls == 1


def test_unexpected_exception_is_redacted(settings, payload):
    result = Pipeline(SequenceProvider([RuntimeError("secret token")]), settings).run(**payload)
    assert result.errors[0].code == "internal_provider"
    assert "secret" not in result.errors[0].message


@pytest.mark.parametrize(
    "description",
    [
        "URGENT! I need the office opening hours immediately.",
        "There is no confirmed ransomware incident on this server.",
        "A simulated confirmed ransomware attack is part of a drill.",
        "The global network outage is resolved and all users can work.",
    ],
)
def test_no_critical_from_urgency_or_negation(settings, description):
    result = Pipeline(MockProvider(), settings).run("Please assist", description)
    assert result.classification.priority != "Critical"


def test_real_critical_requires_evidence(settings):
    result = Pipeline(MockProvider(), settings).run(
        "Network outage", "All users cannot access the production network."
    )
    assert not result.is_fallback and result.classification.priority == "Critical"


def test_invented_evidence_and_unjustified_critical(settings, payload):
    raw = json.loads(valid_output(payload))
    raw.update(priority="Critical", impact="security_incident", confidence=0.99)
    result = Pipeline(SequenceProvider([json.dumps(raw)]), settings).run(**payload)
    assert result.is_fallback and result.schema_valid
    assert result.errors[0].code == "business_rule"
    raw.update(priority="Medium", evidence="This is not in the request")
    with pytest.raises(BusinessRuleError):
        validate_business_rules(Classification.model_validate(raw), **payload)


def test_evidence_cannot_crop_negation(settings):
    source = "There is no confirmed ransomware on this server."
    raw = json.loads(MockProvider().classify("Security report", source))
    raw.update(
        priority="Critical",
        confidence=0.95,
        impact="security_incident",
        evidence="confirmed ransomware on this server",
    )
    result = Pipeline(SequenceProvider([json.dumps(raw)]), settings).run("Security report", source)
    assert result.is_fallback
    assert result.errors[0].code == "business_rule"


def test_short_valid_title(settings):
    result = Pipeline(MockProvider(), settings).run("VPN", "The network connection is slow.")
    assert not result.is_fallback


def test_untrusted_field_names_are_not_stored(settings, payload):
    raw = json.loads(valid_output(payload))
    raw["confidential-key-name"] = "confidential-value"
    result = Pipeline(SequenceProvider([json.dumps(raw)]), settings).run(**payload)
    assert result.is_fallback
    assert "confidential" not in str(result.errors)
    assert result.errors[0].details == [{"field": "unknown", "type": "extra_forbidden"}]


def test_unicode_prefix_cannot_shift_evidence_context(settings):
    source = "ß" * 100 + ". There is no confirmed ransomware on this server."
    raw = json.loads(MockProvider().classify("Security report", source))
    raw.update(
        priority="Critical",
        confidence=0.95,
        impact="security_incident",
        evidence="confirmed ransomware on this server",
    )
    result = Pipeline(SequenceProvider([json.dumps(raw)]), settings).run("Security report", source)
    assert result.is_fallback
    assert result.errors[0].code == "business_rule"


def test_unicode_prefix_preserves_valid_evidence_offsets(settings):
    evidence = "Confirmed ransomware is encrypting files."
    source = "ß" * 100 + ". " + evidence
    raw = json.loads(MockProvider().classify("Security report", source))
    raw["evidence"] = evidence
    result = Pipeline(SequenceProvider([json.dumps(raw)]), settings).run("Security report", source)
    assert not result.is_fallback
    assert result.classification.priority == "Critical"
