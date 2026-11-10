"""Use real sockets, redirects and gzip rather than replacing HTTP transports."""

import gzip
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from apps.ingestion.clients.base import BaseClient
from apps.ingestion.fulltext import extract_pdf_text

FIXTURES = Path(__file__).parents[1] / "fixtures" / "compatibility"


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/json")
                self.end_headers()
                return
            if self.path == "/retry" and sum(path == "/retry" for path, _ in requests) == 1:
                self.send_response(503)
                self.send_header("Retry-After", "0")
                self.end_headers()
                return
            if self.path == "/pdf":
                body = (FIXTURES / "legislative-text.pdf").read_bytes()
                content_type = "application/pdf"
            else:
                body = (
                    b"{"
                    if self.path == "/broken"
                    else json.dumps(
                        {"ementa": "Saúde e proteção das mulheres"}, ensure_ascii=False
                    ).encode()
                )
                content_type = "application/json; charset=utf-8"
            body = gzip.compress(body)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_owned_ingestion_client_follows_redirect_and_decodes_gzip(upstream):
    url, requests = upstream
    with BaseClient() as client:
        assert client.get_json(f"{url}/redirect") == {"ementa": "Saúde e proteção das mulheres"}
    assert [path for path, _ in requests] == ["/redirect", "/json"]
    assert requests[-1][1]["Accept"] == "application/json"
    assert "elas-no-congresso-api" in requests[-1][1]["User-Agent"]


def test_owned_ingestion_client_retries_temporary_server_failure(upstream, monkeypatch):
    # Tenacity captures its wait callback when the function is decorated.
    monkeypatch.setattr(BaseClient.get_json.retry, "wait", lambda state: 0)
    url, requests = upstream
    with BaseClient() as client:
        assert client.get_json(f"{url}/retry")["ementa"] == "Saúde e proteção das mulheres"
    assert [path for path, _ in requests] == ["/retry", "/retry"]


def test_invalid_json_is_not_retried(upstream):
    url, requests = upstream
    with BaseClient() as client, pytest.raises(json.JSONDecodeError):
        client.get_json(f"{url}/broken")
    assert len(requests) == 1


def test_download_and_parse_compressed_pdf_with_real_client(upstream):
    url, _ = upstream
    assert extract_pdf_text(f"{url}/pdf") == (FIXTURES / "legislative-text.txt").read_text().strip()
