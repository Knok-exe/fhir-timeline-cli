"""Command-line entry point: fhir-timeline."""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources

import requests

from .client import DEFAULT_SERVER, FhirClient, FhirError
from .render import FORMATTERS
from .timeline import RESOURCE_TYPES, build_timeline, filter_events, latest_per_code

BANNER = "SYNTHETIC TEST DATA ONLY - not for clinical use.\n"


def load_demo_resources() -> list[dict]:
    text = resources.files("fhir_timeline").joinpath("demo_bundle.json").read_text("utf-8")
    return [e["resource"] for e in json.loads(text)["entry"]]


def fetch_resources(client: FhirClient, patient_id: str, types: list[str] | None,
                    use_everything: bool) -> list[dict]:
    """Get a patient's resources, preferring $everything when asked, else per-type searches."""
    if use_everything:
        try:
            return list(client.everything(patient_id))
        except FhirError as exc:
            print(f"note: $everything unavailable ({exc}); using per-type searches.",
                  file=sys.stderr)
    raw: list[dict] = []
    for rtype in types or RESOURCE_TYPES:
        raw.extend(client.search(rtype, {"patient": patient_id}))
    return raw


def patient_label(p: dict) -> str:
    name = (p.get("name") or [{}])[0]
    full = " ".join(name.get("given", []) + [name.get("family", "")]).strip()
    return f"{full or '(no name)'}  id={p.get('id', '?')}  born={p.get('birthDate', '?')}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fhir-timeline", description=__doc__)
    who = p.add_mutually_exclusive_group()
    who.add_argument("--patient", help="Patient resource id")
    who.add_argument("--name", help="Search patients by name and list matches")
    who.add_argument("--demo", action="store_true", help="Use bundled synthetic data, no network")
    p.add_argument("--server", default=DEFAULT_SERVER, help=f"FHIR base URL (default {DEFAULT_SERVER})")
    p.add_argument("--everything", action="store_true",
                   help="Fetch via Patient/$everything (one request chain); falls back to "
                        "per-type searches if the server does not support it")
    p.add_argument("--types", nargs="+", choices=RESOURCE_TYPES, help="Limit to these resource types")
    p.add_argument("--since", help="Only events on/after this date (YYYY, YYYY-MM or YYYY-MM-DD)")
    p.add_argument("--until", help="Only events on/before this date")
    p.add_argument("--code", nargs="+", help="Only these codes, e.g. --code 4548-4 2160-0")
    p.add_argument("--latest", action="store_true", help="Newest result per code only")
    p.add_argument("--format", choices=sorted(FORMATTERS), default="table")
    p.add_argument("--output", "-o", help="Write to this file instead of stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.patient or args.name or args.demo):
        build_parser().print_usage(sys.stderr)
        print("error: give --demo, --patient ID, or --name NAME", file=sys.stderr)
        return 2
    try:
        if args.demo:
            raw = [r for r in load_demo_resources() if r["resourceType"] != "Patient"]
            header = "Demo patient (synthetic)"
        else:
            client = FhirClient(args.server)
            if args.name:
                matches = client.find_patients(args.name)
                if not matches:
                    print(f"No patients found for name '{args.name}'.", file=sys.stderr)
                    return 1
                for m in matches:
                    print(patient_label(m))
                print("\nRe-run with --patient <id> to see a timeline.")
                return 0
            header = patient_label(client.read("Patient", args.patient))
            raw = fetch_resources(client, args.patient, args.types, args.everything)
    except FhirError as exc:
        print(f"FHIR error: {exc}", file=sys.stderr)
        return 1
    except requests.exceptions.Timeout:
        print(f"Network error: timed out talking to {args.server}.", file=sys.stderr)
        return 1
    except requests.exceptions.ConnectionError:
        print(f"Network error: could not connect to {args.server}. "
              "Check the URL and that the server is up.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1

    events = build_timeline(raw, set(args.types) if args.types else None)
    try:
        events = filter_events(events, args.since, args.until, args.code)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.latest:
        events = latest_per_code(events)
    body = FORMATTERS[args.format](events)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
        print(f"Wrote {len(events)} events to {args.output}", file=sys.stderr)
    else:
        print(BANNER + header + "\n")
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
