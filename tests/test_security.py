"""Security: ingestion must not be usable as an arbitrary-file-read primitive."""

from __future__ import annotations

from tests.conftest import DOCROOT, V1


def _ingest(client, path, name="x"):
    return client.post(
        "/documents/ingest", json={"path": path, "document_name": name}
    )


def test_absolute_path_outside_root_is_rejected(client):
    r = _ingest(client, "/etc/passwd")
    assert r.status_code == 400
    assert "outside the permitted document root" in r.json()["detail"]


def test_relative_traversal_is_rejected(client):
    r = _ingest(client, "../../etc/hosts")
    assert r.status_code == 400
    assert "outside" in r.json()["detail"]


def test_directory_is_rejected(client):
    r = _ingest(client, str(DOCROOT))
    assert r.status_code == 400


def test_non_pdf_inside_root_is_rejected(client):
    bad = DOCROOT / "notes.txt"
    bad.write_text("just text")
    r = _ingest(client, str(bad))
    assert r.status_code == 400
    assert "pdf" in r.json()["detail"].lower()


def test_pdf_inside_root_is_accepted(client):
    r = _ingest(client, V1, name="ok")
    assert r.status_code == 200, r.text


def test_empty_path_is_rejected(client):
    r = _ingest(client, "")
    assert r.status_code in (400, 422)
