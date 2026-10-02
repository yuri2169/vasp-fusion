"""What is served outside /api: the built interface, or the console that stands in."""
import pytest
from fastapi.testclient import TestClient

from vaspfusion.api import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_without_a_build_the_console_is_served(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UI_DIST", tmp_path / "no-dist")
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "VASP-FUSION" in r.text and "/api/auth/login" in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/anything/else").status_code == 404


def test_the_console_loads_nothing_from_another_host(client, tmp_path, monkeypatch):
    """It has to work on a machine with no network."""
    monkeypatch.setattr(main, "UI_DIST", tmp_path / "no-dist")
    html = client.get("/").text
    assert "http://" not in html and "https://" not in html and "//cdn" not in html


def test_a_build_is_served_as_a_single_page_app(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>built</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("not for serving")
    monkeypatch.setattr(main, "UI_DIST", dist)
    assert "built" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "built" in client.get("/cases/c-123").text              # a client-side route
    for sneaky in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        assert "not for serving" not in client.get(sneaky).text


def test_unknown_api_paths_stay_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "not found"}
    assert client.get("/openapi.json").status_code == 200


def test_the_interface_is_not_in_the_audit_log(client, tmp_path, monkeypatch):
    from vaspfusion.store.audit import AuditLog
    monkeypatch.setattr(main, "UI_DIST", tmp_path / "no-dist")
    client.get("/")
    assert AuditLog(main.AUDIT_DB).list()[0] == 0
