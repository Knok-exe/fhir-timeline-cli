"""Minimal read-only FHIR R4 client: search, pagination, OperationOutcome errors."""

from __future__ import annotations

import time
from collections.abc import Iterator

import requests

from . import __version__

RETRY_STATUS = {429, 502, 503, 504}

DEFAULT_SERVER = "https://api.sondahub.com/fhir"


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
        # Searches that stopped at max_pages while the server still had more pages. Callers
        # should tell the user, because the results they show are incomplete.
        self.truncated: list[str] = []

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
            body = None
        if not isinstance(body, dict):
            if resp.status_code >= 400:
                raise FhirError(f"HTTP {resp.status_code} from {url}")
            # e.g. an HTML page from a wrong base URL: don't pretend it was an empty result
            raise FhirError(f"{url} did not return FHIR JSON. Is the --server URL a FHIR base?")
        if resp.status_code >= 400:
            if body.get("resourceType") == "OperationOutcome":
                raise FhirError(f"HTTP {resp.status_code}: {outcome_message(body)}")
            raise FhirError(f"HTTP {resp.status_code} from {url}")
        if body.get("resourceType") == "OperationOutcome":
            raise FhirError(outcome_message(body))
        return body

    def _paged(self, url: str, params: dict | None, max_pages: int,
               resource_type: str | None = None) -> Iterator[dict]:
        """Yield resources across Bundle pages, following link rel=next.

        Stops after max_pages; if the server still offered a next page, the starting URL is
        recorded in self.truncated so the caller can warn that results are incomplete.
        """
        first_url = url
        for page in range(max_pages):
            bundle = self._get(url, params)
            for entry in bundle.get("entry", []):
                resource = entry.get("resource")
                if not resource:
                    continue
                if resource_type is None or resource.get("resourceType") == resource_type:
                    yield resource
            nxt = next((link["url"] for link in bundle.get("link", [])
                        if link.get("relation") == "next"), None)
            if not nxt:
                return
            if page == max_pages - 1:
                self.truncated.append(first_url)
                return
            url, params = nxt, None  # next URL already carries its query string

    def search(self, resource_type: str, params: dict | None = None,
               max_pages: int = 20) -> Iterator[dict]:
        """Yield every resource of one type across all pages."""
        page_params = dict(params or {})
        page_params.setdefault("_count", 100)
        yield from self._paged(f"{self.base_url}/{resource_type}", page_params, max_pages,
                               resource_type)

    def everything(self, patient_id: str, max_pages: int = 50) -> Iterator[dict]:
        """Yield every resource in the patient's compartment via Patient/{id}/$everything.

        Raises FhirError if the server does not support the operation (caller can fall back).
        """
        url = f"{self.base_url}/Patient/{patient_id}/$everything"
        yield from self._paged(url, {"_count": 100}, max_pages)

    def find_patients(self, name: str, limit: int = 10) -> list[dict]:
        params = {"name": name, "_count": limit}
        return list(self.search("Patient", params, max_pages=1))[:limit]

    def read(self, resource_type: str, rid: str) -> dict:
        return self._get(f"{self.base_url}/{resource_type}/{rid}")
