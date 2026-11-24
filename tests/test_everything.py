import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from test_timeline import FakeResponse, FakeSession

from fhir_timeline.cli import fetch_resources, main
from fhir_timeline.client import FhirClient, FhirError


def mixed_bundle(items, next_url=None):
    body = {"resourceType": "Bundle", "entry": [{"resource": r} for r in items]}
    if next_url:
        body["link"] = [{"relation": "next", "url": next_url}]
    return FakeResponse(body)


OBS = {"resourceType": "Observation", "id": "o1", "effectiveDateTime": "2024-01-01",
       "code": {"coding": [{"system": "http://loinc.org", "code": "1", "display": "Thing"}]}}
COND = {"resourceType": "Condition", "id": "c1", "onsetDateTime": "2020-01-01",
        "code": {"text": "Cond"}}


def test_everything_returns_all_resource_types_and_paginates():
    session = FakeSession([mixed_bundle([OBS], "http://x/page2"), mixed_bundle([COND])])
    got = list(FhirClient("http://x", session=session).everything("p1"))
    assert [r["resourceType"] for r in got] == ["Observation", "Condition"]
    assert session.calls[0][0] == "http://x/Patient/p1/$everything"
    assert session.calls[1] == ("http://x/page2", None)


def test_unsupported_everything_falls_back_to_per_type_searches(capsys):
    outcome = {"resourceType": "OperationOutcome",
               "issue": [{"severity": "error", "code": "not-supported", "diagnostics": "nope"}]}
    empty = mixed_bundle([])
    # 1 failing $everything call, then one search per resource type (6)
    session = FakeSession([FakeResponse(outcome, 501)] + [empty] * 6)
    client = FhirClient("http://x", session=session)
    assert fetch_resources(client, "p1", None, use_everything=True) == []
    assert "per-type searches" in capsys.readouterr().err
    assert len(session.calls) == 7


def test_without_flag_everything_is_not_called():
    session = FakeSession([mixed_bundle([])] * 6)
    fetch_resources(FhirClient("http://x", session=session), "p1", None, use_everything=False)
    assert all("$everything" not in url for url, _ in session.calls)


def test_everything_error_propagates_from_client():
    outcome = {"resourceType": "OperationOutcome", "issue": [{"code": "x", "diagnostics": "bad"}]}
    session = FakeSession([FakeResponse(outcome, 400)])
    with pytest.raises(FhirError):
        list(FhirClient("http://x", session=session).everything("p1"))


def test_cli_everything_flag_over_real_http(capsys):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/Patient/p1/$everything"):
                body = {"resourceType": "Bundle", "entry": [{"resource": OBS}, {"resource": COND}]}
            else:
                body = {"resourceType": "Patient", "id": "p1", "birthDate": "1980-01-01"}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert main(["--server", f"http://127.0.0.1:{srv.server_port}", "--patient", "p1",
                     "--everything"]) == 0
    finally:
        srv.shutdown()
    out = capsys.readouterr().out
    assert "Thing" in out and "Cond" in out
