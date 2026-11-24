# fhir-timeline-cli

Read-only command-line tool that prints a chronological timeline (encounters, vitals, labs with LOINC codes and abnormal flags, problems, meds, allergies, immunizations) for a patient on a FHIR R4 server.

> **Synthetic test data only.** Never point this at a real patient record or a work system. Not a medical device.

## Quick start

```bash
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"

fhir-timeline --demo                       # offline, bundled synthetic patient
fhir-timeline --name Smith                 # search the public server, list matching patient ids
fhir-timeline --patient <id> --types Observation Condition --format markdown
fhir-timeline --patient <id> --format csv -o timeline.csv
fhir-timeline --server http://hapi.fhir.org/baseR4 --name Smith   # any FHIR R4 base URL

# filters
fhir-timeline --demo --since 2023 --until 2024-06-30        # date window
fhir-timeline --demo --code 4548-4 2160-0                   # only these LOINC/SNOMED/RxNorm codes
fhir-timeline --demo --latest                               # newest result per code
```

Default server: SondaHub public synthetic FHIR (`https://api.sondahub.com/fhir`, no auth). Check the server's docs before relying on it — public test servers move.

## What it demonstrates

- FHIR search with `patient=` scoping and `Bundle.link[next]` pagination
- `OperationOutcome` error handling
- LOINC / SNOMED / RxNorm / CVX display from `CodeableConcept`
- Abnormal-flag logic from `interpretation` or `referenceRange` (missing data is never a flag)
- Retry with backoff on 429/502/503/504 (honours `Retry-After`)
- Date, code and latest-per-code filters
- Tests that never touch the internet: a fake session, plus a local throwaway HTTP server for the real `requests` path

## Layout

```
src/fhir_timeline/   client.py  timeline.py  render.py  cli.py  demo_bundle.json
tests/               test_timeline.py
```

## Limitations / next steps

- Plain-text table; swap in `rich` for colour once comfortable
- No `Patient/$everything` yet (per-type searches instead)
- Add `fhir.resources` validation of each resource
- Run against the Cerner open sandbox via `--server`
