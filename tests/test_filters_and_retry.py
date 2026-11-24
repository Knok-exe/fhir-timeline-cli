import pytest
from test_timeline import FakeResponse, FakeSession, bundle

from fhir_timeline.cli import load_demo_resources
from fhir_timeline.client import FhirClient, FhirError
from fhir_timeline.render import to_table
from fhir_timeline.timeline import build_timeline, filter_events, latest_per_code


def demo_events():
    return build_timeline(r for r in load_demo_resources() if r["resourceType"] != "Patient")


class R(FakeResponse):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body, status)
        self.headers = headers or {}


def test_retries_429_then_succeeds_and_honours_retry_after():
    sleeps = []
    session = FakeSession([R({}, 429, {"Retry-After": "3"}), R({}, 503), bundle(["a"])])
    client = FhirClient("http://x", session=session, sleep=sleeps.append)
    assert [r["id"] for r in client.search("Observation")] == ["a"]
    assert sleeps == [3.0, 2 ** 1]


def test_gives_up_after_max_retries():
    session = FakeSession([R({}, 503)] * 4)
    client = FhirClient("http://x", session=session, sleep=lambda s: None, max_retries=3)
    with pytest.raises(FhirError, match="503"):
        list(client.search("Observation"))
    assert len(session.calls) == 4


def test_404_is_not_retried():
    session = FakeSession([R({}, 404)])
    with pytest.raises(FhirError):
        FhirClient("http://x", session=session, sleep=lambda s: None).read("Patient", "1")
    assert len(session.calls) == 1


def test_since_until_code_filters():
    ev = demo_events()
    assert {e.date_str[:4] for e in filter_events(ev, since="2024")} == {"2024"}
    assert all(e.date_str <= "2019-12-31" for e in filter_events(ev, until="2019-12-31"))
    assert {e.code for e in filter_events(ev, codes=["4548-4"])} == {"4548-4"}
    with pytest.raises(ValueError):
        filter_events(ev, since="last week")


def test_latest_keeps_newest_hba1c_only():
    a1c = [e for e in latest_per_code(demo_events()) if e.code == "4548-4"]
    assert len(a1c) == 1 and a1c[0].date_str == "2024-01-15"


def test_long_text_is_clipped_with_ellipsis():
    assert "…" in to_table(demo_events())
