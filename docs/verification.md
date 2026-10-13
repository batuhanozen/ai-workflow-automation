# Verification record

Local verification date: 2026-10-13. Runtime: Python 3.13.3 on macOS.

- Pytest: **61 passed**, **99% statement coverage**. Automated coverage includes API, database, classification, retries, timeouts, fallback, concurrent claims, human review, and recovery. Executed with `pytest --cov=app --cov-report=term-missing`.
- Ruff: `ruff check .` passed.
- Node: `node --check app/static/app.js` passed; no frontend build required.
- Dependencies: `pip check` reported no broken requirements.
- Evaluation: 18 synthetic cases; mock category accuracy 88.89%, priority accuracy 83.33%, schema success 100%, processing success 100%.
- Browser: submitted a synthetic request, observed completed processing, changed priority, approved a suggested action, and verified the saved human review. Desktop and mobile screenshots are saved under `docs/screenshots/`.
- Paid live LLM: not called. HTTP integration exercised with mocked responses, including status errors, timeout, refusal, incomplete output, and malformed envelopes.
- Docker: provided but not built locally; Docker is unavailable in this environment.
- CI: configured for Python 3.11–3.13; remote GitHub Actions has not been run as part of this local implementation.

A dependency deprecation warning from Starlette's TestClient/httpx compatibility layer may appear; it does not indicate a failed application test. The application uses HTTPX for provider transport.
