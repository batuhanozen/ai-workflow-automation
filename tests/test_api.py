from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import AIResult, SupportRequest
from app.providers.mock import MockProvider
from tests.test_pipeline import SequenceProvider


def create(client, payload):
    response = client.post("/api/requests", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"
    return client.get(f"/api/requests/{response.json()['id']}").json()


def review_payload(request):
    return {
        "category": "IT Support",
        "priority": "High",
        "reviewer": "Demo reviewer",
        "note": "Confirmed impact with the requester.",
        "suggested_action": "Inspect the device.",
        "action_approved": True,
        "expected_version": request["version"],
    }


def test_creation_persistence_and_endpoints(client, payload):
    request = create(client, payload)
    assert request["status"] == "completed"
    assert request["results"][0]["provider"] == "mock"
    assert request["classification"]["category"] == "Account Access"
    with client.app.state.sessions() as db:
        assert db.get(SupportRequest, request["id"]).title == payload["title"]
        assert len(db.scalars(select(AIResult)).all()) == 1
    assert client.get("/api/requests?category=Account%20Access").json()["total"] == 1
    assert client.get("/api/requests?q=%25").json()["total"] == 0
    assert client.get("/api/requests?priority=Critical").json()["total"] == 0
    assert client.get("/api/requests?limit=0").status_code == 422
    assert client.get("/api/stats").json()["processed"] == 1
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/config").json()["provider"] == "mock"
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_review_immutable_history_and_conflict(client, payload):
    request = create(client, payload)
    url = f"/api/requests/{request['id']}/reviews"
    response = client.post(url, json=review_payload(request))
    assert response.status_code == 201
    reviewed = response.json()
    assert reviewed["classification"]["category"] == "IT Support"
    assert reviewed["results"] == request["results"]
    assert reviewed["reviews"][0]["category"] == "IT Support"
    assert reviewed["action_approved"] and reviewed["reviewed"]
    assert client.post(url, json=review_payload(request)).status_code == 409
    second = review_payload(reviewed)
    second.update(priority="Low", action_approved=False)
    again = client.post(url, json=second).json()
    assert len(again["reviews"]) == 2
    assert not again["action_approved"]
    assert client.get("/api/requests?reviewed=true&priority=Low").json()["total"] == 1
    assert client.get("/api/stats").json()["needs_review"] == 0
    assert client.post(f"/api/requests/{request['id']}/retry").status_code == 409


def test_failed_processing_review_retains_failure(settings, payload):
    with TestClient(create_app(settings, SequenceProvider(['{"secret":"sensitive"}']))) as client:
        request = create(client, payload)
        assert request["status"] == "failed" and request["is_fallback"]
        assert request["errors"][0]["code"] == "schema_validation"
        assert "sensitive" not in str(request["errors"])
        response = client.post(
            f"/api/requests/{request['id']}/reviews", json=review_payload(request)
        )
        assert response.json()["status"] == "failed"
        assert response.json()["reviewed"]
        assert client.get("/api/stats").json()["failed"] == 1


def test_retry_preserves_previous_results(settings, payload):
    provider = SequenceProvider(["bad json", MockProvider().classify(**payload)])
    with TestClient(create_app(settings, provider)) as client:
        request = create(client, payload)
        assert client.post(f"/api/requests/{request['id']}/retry").status_code == 202
        final = client.get(f"/api/requests/{request['id']}").json()
        assert final["status"] == "completed" and not final["is_fallback"]
        assert len(final["results"]) == 2 and len(final["errors"]) == 1
        assert final["results"][0]["is_fallback"]


def test_restart_recovery(settings, payload):
    app = create_app(settings)
    with TestClient(app):
        with app.state.sessions.begin() as db:
            request = SupportRequest(**payload, status="processing")
            db.add(request)
            db.flush()
            request_id = request.id
    with TestClient(create_app(settings)) as restarted:
        request = restarted.get(f"/api/requests/{request_id}").json()
        assert request["status"] == "failed"
        assert request["errors"][0]["code"] == "interrupted"
        assert request["results"][0]["is_fallback"]
        assert restarted.post(f"/api/requests/{request_id}/retry").status_code == 202


def test_atomic_processing_claim(client, payload):
    with client.app.state.sessions.begin() as db:
        request = SupportRequest(**payload)
        db.add(request)
        db.flush()
        request_id = request.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(client.app.state.processor.process, [request_id, request_id]))
    assert sorted(outcomes) == [False, True]
    assert len(client.get(f"/api/requests/{request_id}").json()["results"]) == 1


def test_validation_and_safe_errors(client, payload):
    for invalid in [
        {},
        {"title": "  ", "description": "secret"},
        {**payload, "extra": "secret"},
        {**payload, "description": "x" * 10001},
    ]:
        response = client.post("/api/requests", json=invalid)
        assert response.status_code == 422
        assert "secret" not in response.text
    assert client.post("/api/requests", content="x" * 70000).status_code == 413
    assert client.get("/api/requests/not-a-uuid").status_code == 422
    assert client.get("/api/requests/00000000-0000-0000-0000-000000000000").status_code == 404


def test_auth_protects_reads_and_writes(settings, payload):
    from pydantic import SecretStr

    settings.api_key = SecretStr("test-key")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/stats").status_code == 401
        assert client.post("/api/requests", json=payload).status_code == 401
        assert client.get("/api/config", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/api/stats", headers={"X-API-Key": "test-key"}).status_code == 200
        assert client.get("/").headers["x-content-type-options"] == "nosniff"
        assert "script-src 'self'" in client.get("/").headers["content-security-policy"]


def test_pending_review_and_review_queue(client, payload):
    with client.app.state.sessions.begin() as db:
        request = SupportRequest(**payload)
        db.add(request)
        db.flush()
        request_id = request.id
    pending = client.get(f"/api/requests/{request_id}").json()
    assert (
        client.post(f"/api/requests/{request_id}/reviews", json=review_payload(pending)).status_code
        == 409
    )
    assert client.get("/api/requests?needs_review=true").json()["total"] == 0
    assert client.get("/api/stats").json()["pending"] == 1


def test_activity_includes_review(client, payload):
    request = create(client, payload)
    client.post(f"/api/requests/{request['id']}/reviews", json=review_payload(request))
    activity = client.get("/api/activity").json()
    assert activity[0]["event"] == "Human review saved"
    assert activity[0]["request_id"] == request["id"]
    assert activity[1]["event"] == "Classification recorded"
