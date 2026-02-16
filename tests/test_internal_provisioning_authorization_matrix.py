from fastapi.testclient import TestClient

from src.main import app


def test_internal_provisioning_endpoints_require_super_admin():
    client = TestClient(app)

    provision_resp = client.post("/api/internal/provisioning/email-outreach/c-1", json={})
    status_resp = client.get("/api/internal/provisioning/email-outreach/c-1/status")
    sync_resp = client.post("/api/internal/provisioning/email-outreach/c-1/sync-inboxes")

    assert provision_resp.status_code == 401
    assert status_resp.status_code == 401
    assert sync_resp.status_code == 401
