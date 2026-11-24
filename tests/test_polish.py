import os

from fhir_timeline.cli import load_demo_resources
from fhir_timeline.render import to_table
from fhir_timeline.timeline import build_timeline


def events_with_long_value():
    res = [r for r in load_demo_resources() if r["resourceType"] != "Patient"]
    res.append({"resourceType": "Observation", "id": "long", "effectiveDateTime": "2025-01-01",
                "code": {"coding": [{"system": "http://loinc.org", "code": "72166-2",
                                     "display": "Tobacco smoking status"}]},
                "valueCodeableConcept": {"coding": [{"display": "Never smoked tobacco (finding)"
                                                     " and then some extra long words here"}]}})
    return build_timeline(res)


def test_table_fits_narrow_terminal_including_long_values(monkeypatch):
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(120, 24): os.terminal_size((100, 24)))
    lines = to_table(events_with_long_value()).splitlines()
    assert max(len(line) for line in lines) <= 100
    assert lines[0].split()[-1] == "Flag"  # header never wraps


def test_wide_terminal_does_not_truncate_short_values(monkeypatch):
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=(120, 24): os.terminal_size((200, 24)))
    assert "Type 2 diabetes mellitus" in to_table(events_with_long_value())
