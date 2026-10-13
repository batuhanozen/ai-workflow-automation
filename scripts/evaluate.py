"""Run offline by default; --live explicitly opts into configured, potentially paid calls."""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.pipeline import Pipeline
from app.providers.mock import MockProvider
from app.providers.openai import OpenAIProvider

DATASET = Path(__file__).resolve().parents[1] / "evaluation" / "requests.json"


def evaluate(pipeline: Pipeline, cases: list[dict]) -> dict:
    if not cases:
        raise ValueError("Evaluation dataset cannot be empty")
    rows = []
    for case in cases:
        outcome = pipeline.run(case["title"], case["description"])
        result = outcome.classification
        rows.append(
            {
                "title": case["title"],
                "expected_category": case["category"],
                "actual_category": result.category.value,
                "expected_priority": case["priority"],
                "actual_priority": result.priority.value,
                "category_correct": not outcome.is_fallback and result.category == case["category"],
                "priority_correct": not outcome.is_fallback and result.priority == case["priority"],
                "schema_valid": outcome.schema_valid,
                "processing_success": not outcome.is_fallback,
            }
        )

    def rate(key: str) -> float:
        return round(sum(row[key] for row in rows) / len(rows), 4)

    return {
        "provider": pipeline.provider.name,
        "model": pipeline.provider.model,
        "dataset_size": len(rows),
        "category_accuracy": rate("category_correct"),
        "priority_accuracy": rate("priority_correct"),
        "schema_validation_success_rate": rate("schema_valid"),
        "processing_success_rate": rate("processing_success"),
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings(ai_provider="openai" if args.live else "mock")
    provider = OpenAIProvider(settings) if args.live else MockProvider()
    report = evaluate(Pipeline(provider, settings), json.loads(DATASET.read_text()))
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
