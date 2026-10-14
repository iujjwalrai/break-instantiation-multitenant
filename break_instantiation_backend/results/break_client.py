"""HTTP call into BREAK's scoring service.

The path and the `responses` body match the generate-report call BVI's
preview-result view already makes. This client does not interpret the
body and does not substitute a score when BREAK does not answer.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from django.conf import settings

_SUCCESS_MIN = 200
_SUCCESS_MAX = 300


class BreakScoringError(Exception):
    """BREAK did not return a score. Callers must not invent one."""


def score_responses(responses: dict[str, str]) -> tuple[int, object]:
    """POST answers to BREAK. Return `(status, body)` only on HTTP 2xx.

    `body` is the decoded JSON, or `{}` when the response is empty.
    """
    base = settings.BREAK_BACKEND_BASE_URL.rstrip("/")
    token = settings.BREAK_SCORING_TOKEN
    path = settings.BREAK_SCORING_PATH.lstrip("/")
    if not base or not token:
        msg = "BREAK scoring is not configured."
        raise BreakScoringError(msg)

    url = f"{base}/{path}"
    if urlparse(url).scheme not in {"http", "https"}:
        msg = "BREAK scoring URL must be http or https."
        raise BreakScoringError(msg)

    payload = json.dumps({"responses": responses}).encode()
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        data=payload,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - scheme checked above
            request,
            timeout=settings.BREAK_SCORING_TIMEOUT_SECONDS,
        ) as response:
            status_code = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        msg = f"BREAK refused scoring ({exc.code})."
        raise BreakScoringError(msg) from exc
    except urllib.error.URLError as exc:
        msg = "BREAK scoring is unavailable."
        raise BreakScoringError(msg) from exc

    if not _SUCCESS_MIN <= status_code < _SUCCESS_MAX:
        msg = f"BREAK refused scoring ({status_code})."
        raise BreakScoringError(msg)
    if not raw:
        return status_code, {}
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = "BREAK scoring returned a body that is not JSON."
        raise BreakScoringError(msg) from exc
    return status_code, body
