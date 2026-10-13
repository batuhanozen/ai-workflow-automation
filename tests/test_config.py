import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_env": "production", "api_key": "short"},
        {"ai_provider": "openai", "openai_api_key": ""},
        {"database_url": "postgresql://localhost/workflow"},
        {"openai_base_url": "http://localhost.attacker.example/v1"},
        {"openai_base_url": "http://127.0.0.1.attacker.example/v1"},
        {"openai_base_url": "https://user:password@example.com/v1"},
        {"llm_max_attempts": 6},
    ],
)
def test_invalid_configuration(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_local_compatible_endpoint():
    assert Settings(_env_file=None, openai_base_url="http://localhost:1234/v1")
