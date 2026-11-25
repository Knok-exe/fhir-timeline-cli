from datetime import timezone

import pytest
from test_timeline import FakeResponse, FakeSession, bundle

from fhir_timeline.client import FhirClient, FhirError
from fhir_timeline.timeline import Event, filter_events, parse_fhir_datetime


def events(*dates):
    return [Event(parse_fhir_datetime(d), "Observation", "LOINC", "x", "x") for d in dates]


def test_partial_until_covers_the_whole_period():
    ev = events("2024-01-01", "2024-06-15", "2024-12-31T23:30:00Z", "2025-01-01")
    assert [e.date_str for e in filter_events(ev, until="2024")] == [
        "2024-01-01", "2024-06-15", "2024-12-31"]
    assert [e.date_str for e in filter_events(ev, until="2024-06")] == [
        "2024-01-01", "2024-06-15"]
    assert [e.date_str for e in filter_events(ev, until="2024-06-15")] == [
        "2024-01-01", "2024-06-15"]


def test_until_month_handles_leap_february():
    ev = events("2024-02-29", "2024-03-01")
    assert [e.date_str for e in filter_events(ev, until="2024-02")] == ["2024-02-29"]


@pytest.mark.parametrize("value", ["2019-08-13T20:37:12.1+00:00",
                                   "2019-08-13T20:37:12.12Z",
                                   "2019-08-13T20:37:12.123456789Z"])
def test_any_number_of_fractional_digits_parses(value):
    dt = parse_fhir_datetime(value)
    assert dt is not None and dt.tzinfo == timezone.utc and dt.second == 12


def test_non_json_200_is_an_error_not_an_empty_timeline():
    class Html(FakeResponse):
        def json(self):
            raise ValueError("not json")

    client = FhirClient("http://x", session=FakeSession([Html(None)]))
    with pytest.raises(FhirError, match="did not return FHIR JSON"):
        list(client.search("Observation"))


def test_page_limit_is_recorded_as_truncation():
    pages = [bundle([str(i)], f"http://x/next{i}") for i in range(3)]
    client = FhirClient("http://x", session=FakeSession(pages))
    assert len(list(client.search("Observation", max_pages=3))) == 3
    assert client.truncated == ["http://x/Observation"]


def test_complete_paging_is_not_truncation():
    client = FhirClient("http://x", session=FakeSession([bundle(["a"], "http://x/n"),
                                                         bundle(["b"])]))
    list(client.search("Observation", max_pages=2))
    assert client.truncated == []
