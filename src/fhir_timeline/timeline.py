"""Turn raw FHIR resources into a flat, sortable list of timeline events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
CVX = "http://hl7.org/fhir/sid/cvx"

SHORT_SYSTEM = {LOINC: "LOINC", SNOMED: "SNOMED", RXNORM: "RxNorm", CVX: "CVX",
                "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10-CM"}

# Resource types the timeline pulls, with the search param that scopes to one patient.
RESOURCE_TYPES = ["Encounter", "Observation", "Condition", "MedicationRequest",
                  "AllergyIntolerance", "Immunization"]


@dataclass(frozen=True)
class Event:
    when: datetime | None
    kind: str          # Observation, Condition, ...
    code_system: str   # short name, e.g. LOINC
    code: str
    display: str
    value: str = ""
    flag: str = ""     # H, L, HH, LL, A or ""
    resource_id: str = ""

    @property
    def date_str(self) -> str:
        return self.when.strftime("%Y-%m-%d") if self.when else "unknown"


def parse_fhir_datetime(value: str | None) -> datetime | None:
    """Parse FHIR date/dateTime, including partial dates (YYYY, YYYY-MM). Returns UTC-aware."""
    if not value:
        return None
    try:
        if len(value) == 4:
            return datetime(int(value), 1, 1, tzinfo=timezone.utc)
        if len(value) == 7:
            return datetime(int(value[:4]), int(value[5:7]), 1, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def first_coding(concept: dict | None) -> tuple[str, str, str]:
    """Return (short_system, code, display) from a CodeableConcept, preferring LOINC/SNOMED/RxNorm."""
    if not concept:
        return "", "", ""
    codings = concept.get("coding", [])
    preferred = [c for c in codings if c.get("system") in SHORT_SYSTEM] or codings
    if preferred:
        c = preferred[0]
        system = SHORT_SYSTEM.get(c.get("system", ""), c.get("system", ""))
        return system, c.get("code", ""), c.get("display") or concept.get("text", "")
    return "", "", concept.get("text", "")


def abnormal_flag(observation: dict) -> str:
    """Flag from interpretation if present, else from referenceRange vs valueQuantity.

    Missing data is never a flag: no value or no range returns "".
    """
    for interp in observation.get("interpretation", []):
        for c in interp.get("coding", []):
            code = c.get("code", "")
            if code in {"H", "L", "HH", "LL", "A", "AA"}:
                return code
    qty = observation.get("valueQuantity")
    ranges = observation.get("referenceRange") or []
    if not qty or qty.get("value") is None or not ranges:
        return ""
    value = qty["value"]
    rng = ranges[0]
    low = (rng.get("low") or {}).get("value")
    high = (rng.get("high") or {}).get("value")
    if high is not None and value > high:
        return "H"
    if low is not None and value < low:
        return "L"
    return ""


def observation_value(obs: dict) -> str:
    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        if q.get("value") is None:
            return ""
        return f"{q['value']:g} {q.get('unit', '')}".strip()
    if "valueCodeableConcept" in obs:
        return first_coding(obs["valueCodeableConcept"])[2]
    if "valueString" in obs:
        return obs["valueString"]
    if obs.get("component"):  # e.g. blood pressure panel
        parts = []
        for comp in obs["component"]:
            q = comp.get("valueQuantity")
            if q and q.get("value") is not None:
                parts.append(f"{q['value']:g}")
        unit = (obs["component"][0].get("valueQuantity") or {}).get("unit", "")
        return ("/".join(parts) + f" {unit}").strip() if parts else ""
    return ""


def to_event(resource: dict) -> Event | None:
    rtype = resource.get("resourceType")
    rid = resource.get("id", "")
    if rtype == "Observation":
        system, code, display = first_coding(resource.get("code"))
        when = parse_fhir_datetime(resource.get("effectiveDateTime")
                                   or (resource.get("effectivePeriod") or {}).get("start")
                                   or resource.get("issued"))
        return Event(when, rtype, system, code, display, observation_value(resource),
                     abnormal_flag(resource), rid)
    if rtype == "Condition":
        system, code, display = first_coding(resource.get("code"))
        status = first_coding(resource.get("clinicalStatus"))[1]
        when = parse_fhir_datetime(resource.get("onsetDateTime") or resource.get("recordedDate"))
        return Event(when, rtype, system, code, display, status, "", rid)
    if rtype == "MedicationRequest":
        system, code, display = first_coding(resource.get("medicationCodeableConcept"))
        when = parse_fhir_datetime(resource.get("authoredOn"))
        return Event(when, rtype, system, code, display, resource.get("status", ""), "", rid)
    if rtype == "AllergyIntolerance":
        system, code, display = first_coding(resource.get("code"))
        when = parse_fhir_datetime(resource.get("onsetDateTime") or resource.get("recordedDate"))
        return Event(when, rtype, system, code, display, "", "", rid)
    if rtype == "Immunization":
        system, code, display = first_coding(resource.get("vaccineCode"))
        when = parse_fhir_datetime(resource.get("occurrenceDateTime"))
        return Event(when, rtype, system, code, display, resource.get("status", ""), "", rid)
    if rtype == "Encounter":
        system, code, display = first_coding((resource.get("type") or [None])[0])
        when = parse_fhir_datetime((resource.get("period") or {}).get("start"))
        cls = (resource.get("class") or {}).get("code", "")
        return Event(when, rtype, system, code, display or "Encounter", cls, "", rid)
    return None


_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _sort_key(e: Event):
    return (e.when or _FAR_FUTURE, e.kind, e.display)


def build_timeline(resources, kinds: set[str] | None = None) -> list[Event]:
    """Normalise, optionally filter by resource kind, sort oldest-first (undated last)."""
    events = [e for r in resources if (e := to_event(r)) and (not kinds or e.kind in kinds)]
    return sorted(events, key=_sort_key)


def filter_events(events: list[Event], since: str | None = None, until: str | None = None,
                  codes: list[str] | None = None) -> list[Event]:
    """Keep events inside [since, until] (inclusive, YYYY-MM-DD) and matching any given code.

    Undated events are dropped when a date bound is given: we can't prove they are in range.
    """
    lo = parse_fhir_datetime(since) if since else None
    hi = parse_fhir_datetime(until) if until else None
    if since and lo is None or until and hi is None:
        raise ValueError("dates must look like YYYY, YYYY-MM or YYYY-MM-DD")
    wanted = {c.strip() for c in codes or []}
    out = []
    for e in events:
        if (lo or hi) and e.when is None:
            continue
        if lo and e.when < lo:
            continue
        if hi and e.when.date() > hi.date():
            continue
        if wanted and e.code not in wanted:
            continue
        out.append(e)
    return out


def latest_per_code(events: list[Event]) -> list[Event]:
    """Keep only the most recent dated event for each (kind, code); undated events are kept."""
    best: dict[tuple[str, str, str], Event] = {}
    rest = []
    for e in events:
        if e.when is None or not e.code:
            rest.append(e)
            continue
        key = (e.kind, e.code_system, e.code)
        if key not in best or e.when >= best[key].when:
            best[key] = e
    return sorted(list(best.values()) + rest, key=_sort_key)
