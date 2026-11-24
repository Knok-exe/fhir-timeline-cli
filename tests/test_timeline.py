from fhir_timeline.cli import load_demo_resources, main
from fhir_timeline.client import FhirClient, FhirError
from fhir_timeline.timeline import (
    abnormal_flag,
    build_timeline,
    first_coding,
    observation_value,
    parse_fhir_datetime,
)


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


class FakeSession:
    """Serves queued responses in order; records requested URLs. Never touches the network."""

    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def bundle(ids, next_url=None):
    b = {"resourceType": "Bundle",
         "entry": [{"resource": {"resourceType": "Observation", "id": i}} for i in ids]}
    if next_url:
        b["link"] = [{"relation": "next", "url": next_url}]
    return FakeResponse(b)


def test_pagination_follows_next_links():
    session = FakeSession([bundle(["a", "b"], "http://x/next1"), bundle(["c"])])
    got = list(FhirClient("http://x", session=session).search("Observation", {"patient": "1"}))
    assert [r["id"] for r in got] == ["a", "b", "c"]
    assert session.calls[1] == ("http://x/next1", None)


def test_operation_outcome_raises():
    outcome = {"resourceType": "OperationOutcome",
               "issue": [{"severity": "error", "code": "not-found", "diagnostics": "no such patient"}]}
    session = FakeSession([FakeResponse(outcome, 404)])
    try:
        FhirClient("http://x", session=session).read("Patient", "nope")
        assert False, "expected FhirError"
    except FhirError as exc:
        assert "404" in str(exc) and "no such patient" in str(exc)


def test_loinc_parsing_prefers_known_system():
    concept = {"coding": [{"system": "http://example.org/local", "code": "zz"},
                          {"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}]}
    assert first_coding(concept) == ("LOINC", "4548-4", "HbA1c")


def test_abnormal_flag_from_range_and_missing_data_is_not_a_flag():
    high = {"valueQuantity": {"value": 8.1}, "referenceRange": [{"high": {"value": 5.6}}]}
    low = {"valueQuantity": {"value": 0.2}, "referenceRange": [{"low": {"value": 0.6}}]}
    normal = {"valueQuantity": {"value": 0.9}, "referenceRange": [{"low": {"value": 0.6}, "high": {"value": 1.2}}]}
    assert abnormal_flag(high) == "H"
    assert abnormal_flag(low) == "L"
    assert abnormal_flag(normal) == ""
    assert abnormal_flag({"valueQuantity": {"value": 9}}) == ""      # no range
    assert abnormal_flag({"referenceRange": [{"high": {"value": 1}}]}) == ""  # no value


def test_interpretation_code_wins():
    obs = {"interpretation": [{"coding": [{"code": "HH"}]}], "valueQuantity": {"value": 1}}
    assert abnormal_flag(obs) == "HH"


def test_partial_dates_and_sorting_puts_undated_last():
    assert parse_fhir_datetime("2020").year == 2020
    assert parse_fhir_datetime("2020-05").month == 5
    assert parse_fhir_datetime("garbage") is None
    res = [{"resourceType": "Condition", "id": "u", "code": {"text": "undated"}},
           {"resourceType": "Condition", "id": "b", "code": {"text": "b"}, "onsetDateTime": "2022-01-01"},
           {"resourceType": "Condition", "id": "a", "code": {"text": "a"}, "onsetDateTime": "2021-01-01"}]
    assert [e.resource_id for e in build_timeline(res)] == ["a", "b", "u"]


def test_blood_pressure_component_value():
    obs = {"component": [{"valueQuantity": {"value": 142, "unit": "mmHg"}},
                         {"valueQuantity": {"value": 88, "unit": "mmHg"}}]}
    assert observation_value(obs) == "142/88 mmHg"


def test_demo_timeline_is_chronological_and_flags_hba1c():
    events = build_timeline(r for r in load_demo_resources() if r["resourceType"] != "Patient")
    dates = [e.when for e in events if e.when]
    assert dates == sorted(dates)
    a1c = [e for e in events if e.code == "4548-4"]
    assert len(a1c) == 2 and all(e.flag == "H" for e in a1c)


def test_cli_demo_outputs(capsys, tmp_path):
    assert main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC TEST DATA ONLY" in out and "metformin" in out
    target = tmp_path / "t.csv"
    assert main(["--demo", "--format", "csv", "-o", str(target)]) == 0
    assert target.read_text().splitlines()[0].startswith("Date,Type")


def test_cli_requires_a_patient_source(capsys):
    assert main([]) == 2
