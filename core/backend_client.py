"""HTTP client for the MediNote Spring Boot backend (port 8081)."""
from __future__ import annotations

import requests
from typing import Any

import config


class BackendClient:
    def __init__(self):
        self.base = config.BACKEND_URL.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._schema_cache: dict | None = None

    # ── Auth ──────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> str:
        """Login and store JWT. Returns the role."""
        r = self.session.post(
            f"{self.base}/api/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        self._access_token = data["accessToken"]
        self._refresh_token = data.get("refreshToken")
        self._set_auth_header()
        return data.get("role", "UNKNOWN")

    def refresh(self) -> None:
        if not self._refresh_token:
            raise RuntimeError("No refresh token available.")
        r = self.session.post(
            f"{self.base}/api/auth/refresh",
            json={"refreshToken": self._refresh_token},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        self._access_token = data["accessToken"]
        self._refresh_token = data.get("refreshToken", self._refresh_token)
        self._set_auth_header()

    def _set_auth_header(self) -> None:
        if self._access_token:
            self.session.headers["Authorization"] = f"Bearer {self._access_token}"

    # ── Schema & discovery ────────────────────────────────────────────

    def get_schema(self, force_refresh: bool = False) -> dict:
        """Fetch full schema once and cache it. Returns {MODULE: {table: [cols]}}."""
        if self._schema_cache is not None and not force_refresh:
            return self._schema_cache
        r = self._get("/api/data/schema")
        self._schema_cache = r
        return r

    def get_modules(self) -> dict:
        return self._get("/api/data/modules")

    def get_tables(self) -> list[str]:
        return self._get("/api/data/tables")

    def get_module_tables(self, module: str) -> list[str]:
        return self._get(f"/api/data/module/{module}/tables")

    def get_columns(self, table: str) -> list[dict]:
        return self._get(f"/api/meta/columns/{table}")

    # ── Data ──────────────────────────────────────────────────────────

    def browse_table(self, table: str, page: int = 0, size: int = 20) -> dict:
        return self._get(f"/api/data/table/{table}", params={"page": page, "size": size})

    def query_table(self, table: str, body: dict) -> dict:
        return self._post(f"/api/data/query/{table}", body)

    def aggregate_table(self, table: str, body: dict) -> dict:
        return self._post(f"/api/data/aggregate/{table}", body)

    # ── HTTP helpers ──────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self.session.get(f"{self.base}{path}", params=params, timeout=30)
        self._check(r)
        return r.json()

    def _post(self, path: str, body: dict) -> Any:
        r = self.session.post(f"{self.base}{path}", json=body, timeout=30)
        self._check(r)
        return r.json()

    def _check(self, r: requests.Response) -> None:
        if r.status_code == 401 and self._refresh_token:
            self.refresh()
            raise _RetryRequest()
        if not r.ok:
            try:
                msg = r.json().get("error", r.text)
            except Exception:
                msg = r.text
            raise requests.HTTPError(f"HTTP {r.status_code}: {msg}", response=r)


class _RetryRequest(Exception):
    """Signal that a request should be retried after token refresh."""
