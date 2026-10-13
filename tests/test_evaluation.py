from app.pipeline import Pipeline
from app.providers.mock import MockProvider
from scripts.evaluate import evaluate
from tests.test_pipeline import SequenceProvider


def test_evaluation_denominators_and_fallbacks(settings, payload):
    cases = [{**payload, "category": "Account Access", "priority": "Medium"}]
    report = evaluate(Pipeline(MockProvider(), settings), cases)
    assert report["category_accuracy"] == report["priority_accuracy"] == 1.0
    failed = evaluate(Pipeline(SequenceProvider(["invalid"]), settings), cases)
    assert failed["schema_validation_success_rate"] == 0
    assert failed["processing_success_rate"] == 0
    assert failed["category_accuracy"] == 0
