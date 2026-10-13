import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.mock import MockProvider


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        app_env="test",
        ai_provider="mock",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        api_key="",
        llm_backoff_seconds=0,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, MockProvider())) as client:
        yield client


@pytest.fixture
def payload():
    return {"title": "Password reset request", "description": "I forgot my demo account password."}
