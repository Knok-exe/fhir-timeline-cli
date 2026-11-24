"""Exercise the real requests stack against a throwaway local FHIR-like server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from fhir_timeline.cli import main

PATIENT = {"resourceType": "Patient", "id": "p1", "birthDate": "1980-01-01",
           "name": [{"given": ["Test"], "family": "Person"}]}
OBS = [{"resourceType": "Observation", "id": f"o{i}", "effectiveDateTime": f"2024-0{i}-01",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}]},
        "valueQuantity": {"value": 6 + i, "unit": "%"},
        "referenceRange": [{"high": {"value": 5.6}}]} for i in (1, 2, 3)]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        base = f"http://127.0.0.1:{self.server.server_port}"
        if u.path == "/Patient/p1":
            return self._send(200, PATIENT)
        if u.path == "/Patient/missing":
            return self._send(404, {"resourceType": "OperationOutcome",
                                    "issue": [{"severity": "error", "code": "not-found",
                                               "diagnostics": "Patient missing not found"}]})
        if u.path == "/Patient":
            return self._send(200, {"resourceType": "Bundle", "entry": [{"resource": PATIENT}]})
        if u.path == "/Observation":
            start = int(q.get("page", ["0"])[0])
            chunk = OBS[start:start + 2]
            body = {"resourceType": "Bundle", "entry": [{"resource": r} for r in chunk]}
            if start + 2 < len(OBS):
                body["link"] = [{"relation": "next", "url": f"{base}/Observation?page={start + 2}"}]
            return self._send(200, body)
        return self._send(200, {"resourceType": "Bundle", "entry": []})


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_patient_timeline_over_real_http_with_pagination(server, capsys):
    assert main(["--server", server, "--patient", "p1"]) == 0
    out = capsys.readouterr().out
    assert out.count("HbA1c") == 3 and "Test Person" in out and " H" in out


def test_name_search_lists_ids(server, capsys):
    assert main(["--server", server, "--name", "Person"]) == 0
    assert "id=p1" in capsys.readouterr().out


def test_missing_patient_reports_operation_outcome(server, capsys):
    assert main(["--server", server, "--patient", "missing"]) == 1
    assert "not found" in capsys.readouterr().err


def test_unreachable_server_is_a_clean_error(capsys):
    assert main(["--server", "http://127.0.0.1:9", "--patient", "p1"]) == 1
    err = capsys.readouterr().err
    assert "could not connect to http://127.0.0.1:9" in err
    assert "HTTPConnectionPool" not in err  # no raw urllib3 dump
