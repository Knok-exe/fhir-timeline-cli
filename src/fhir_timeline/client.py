"""Minimal read-only FHIR R4 client: search, pagination, OperationOutcome errors."""

from __future__ import annotations

import time
from typing import Iterator

import requests

from . import __version__

RETRY_STATUS = {429, 502, 503, 504}

DEFAULT_SERVER = "https://api.sondahub.com/fhir"
FALLBACK_SERVER = "http://hapi.fhir.org/baseR4"


class FhirError(Exception):
    """Raised when the server returns an error or an OperationOutcome."""


def outcome_message(body: dict) -> str:
    """Pull a readable message out of an OperationOutcome resource."""
    issues = body.get("issue", [])
    parts = []
    for issue in issues:
        text = issue.get("diagnostics") or (issue.get("details") or {}).get("text") or ""
        parts.append(f"{issue.get('severity', 'error')}: {issue.get('code', '')} {text}".strip())
    return "; ".join(parts) or "unknown FHIR error"


class FhirClient:
    def __init__(self, base_url: str = DEFAULT_SERVER, session: requests.Session | None = None,
                 timeout: float = 20.0, max_retries: int = 3, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/fhir+json",
                                     "User-Agent": f"fhir-timeline-cli/{__version__}"})
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep

    def _get_with_retry(self, url: str, params: dict | None):
        """GET, retrying 429/5xx with Retry-After or exponential backoff (1s, 2s, 4s)."""
        for attempt in range(self.max_retries + 1):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code not in RETRY_STATUS or attempt == self.max_retries:
                return resp
            retry_after = (getattr(resp, "headers", None) or {}).get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2 ** attempt
            self._sleep(min(delay, 30))
        return resp  # pragma: no cover

    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = self._get_with_retry(url, params)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            if body.get("resourceType") == "OperationOutcome":
                raise FhirError(f"HTTP {resp.status_code}: {outcome_message(body)}")
            raise FhirError(f"HTTP {resp.status_code} from {url}")
        if body.get("resourceType") == "OperationOutcome":
            raise FhirError(outcome_message(body))
        return body

    def search(self, resource_type: str, params: dict | None = None,
               max_pages: int = 20) -> Iterator[dict]:
        """Yield every resource across all pages (follows Bundle.link rel=next)."""
        url = f"{self.base_url}/{resource_type}"
        page_params = dict(params or {})
        page_params.setdefault("_count", 100)
        for _ in range(max_pages):
            bundle = self._get(url, page_params)
            for entry in bundle.get("entry", []):
                resource = entry.get("resource")
                if resource and resource.get("resourceType") == resource_type:
                    yield resource
            nxt = next((l["url"] for l in bundle.get("link", []) if l.get("relation") == "next"),
                       None)
            if not nxt:
                return
            url, page_params = nxt, None  # next URL already carries its query string

    def find_patients(self, name: str, limit: int = 10) -> list[dict]:
        out = []
        for patient in self.search("Patient", {"name": name, "_count": limit}, max_pages=1):
            out.append(patient)
        return out[:limit]

    def read(self, resource_type: str, rid: str) -> dict:
        return self._get(f"{self.base_url}/{resource_type}/{rid}")
