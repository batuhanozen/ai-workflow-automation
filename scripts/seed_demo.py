"""Insert synthetic examples using the mock provider; safe to rerun without duplicates."""

import json

from sqlalchemy import select

from app.config import Settings
from app.db import Base, build_database
from app.models import SupportRequest
from app.pipeline import Pipeline, Processor
from app.providers.mock import MockProvider
from app.schemas import RequestCreate
from scripts.evaluate import DATASET


def main() -> None:
    settings = Settings(ai_provider="mock")
    engine, sessions = build_database(settings.database_url)
    Base.metadata.create_all(engine)
    processor = Processor(sessions, Pipeline(MockProvider(), settings))
    inserted = 0
    for case in json.loads(DATASET.read_text())[:12]:
        payload = RequestCreate(title=case["title"], description=case["description"])
        with sessions.begin() as db:
            if db.scalar(select(SupportRequest.id).where(SupportRequest.title == payload.title)):
                continue
            request = SupportRequest(**payload.model_dump())
            db.add(request)
            db.flush()
            request_id = request.id
        processor.process(request_id)
        inserted += 1
    engine.dispose()
    print(f"Inserted {inserted} synthetic requests using the mock provider.")


if __name__ == "__main__":
    main()
