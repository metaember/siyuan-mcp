"""Thin HTTP client for the SiYuan kernel API.

Wraps ``requests`` and turns transport / auth / API failures into
``SiyuanError`` with clear, actionable English messages.
"""

from __future__ import annotations

import os
from typing import Any

import requests

_DEFAULT_API_URL = "http://127.0.0.1:6806"


class SiyuanError(RuntimeError):
    """Raised when the SiYuan kernel cannot be reached or returns an error."""


class SiyuanClient:
    """A minimal wrapper around the SiYuan kernel's JSON HTTP API."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
            }
        )

    @classmethod
    def from_env(cls) -> "SiyuanClient":
        """Build a client from ``SIYUAN_API_URL`` / ``SIYUAN_API_TOKEN``."""
        token = os.getenv("SIYUAN_API_TOKEN")
        if not token:
            raise SiyuanError(
                "SIYUAN_API_TOKEN is not set. Set it to your SiYuan API token "
                "(SiYuan: Settings -> About -> API token) so the server can "
                "authenticate to the kernel."
            )
        base_url = os.getenv("SIYUAN_API_URL", _DEFAULT_API_URL)
        return cls(base_url=base_url, token=token)

    def post(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        """POST to a kernel endpoint and return the unwrapped ``data`` field.

        Raises ``SiyuanError`` (never a bare requests exception) so tools surface
        a clean message to the caller.
        """
        response = self._raw_post(endpoint, payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise SiyuanError(
                f"SiYuan returned a non-JSON response from {endpoint} "
                f"(HTTP {response.status_code}). Is SIYUAN_API_URL pointing at the "
                "kernel API (e.g. http://siyuan:6806)?"
            ) from exc

        code = body.get("code")
        if code != 0:
            msg = body.get("msg") or "unknown error"
            raise SiyuanError(f"SiYuan API error on {endpoint}: {msg} (code {code}).")
        return body.get("data")

    def post_raw_bytes(self, endpoint: str, payload: dict[str, Any] | None = None) -> bytes:
        """POST and return the raw response body (used by file-reading endpoints)."""
        response = self._raw_post(endpoint, payload)
        return response.content

    def _raw_post(self, endpoint: str, payload: dict[str, Any] | None) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._session.post(url, json=payload or {}, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise SiyuanError(
                f"Could not reach the SiYuan kernel at {self.base_url} ({exc}). "
                "Check that SiYuan is running and SIYUAN_API_URL is correct."
            ) from exc

        if response.status_code in (401, 403):
            raise SiyuanError(
                f"SiYuan rejected the API token (HTTP {response.status_code}). "
                "Check SIYUAN_API_TOKEN matches the token in SiYuan Settings -> "
                "About -> API token."
            )
        if response.status_code >= 500:
            raise SiyuanError(
                f"SiYuan kernel error (HTTP {response.status_code}) on {endpoint}. "
                "Check the SiYuan logs for details."
            )
        return response
