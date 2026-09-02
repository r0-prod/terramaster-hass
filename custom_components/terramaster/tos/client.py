"""Async client for the TerraMaster TOS 6 web API.

Deliberately free of Home Assistant imports so it can be exercised straight from
a shell against a real NAS -- see ``tools/probe_tos.py``.

Reads (GET) go out in the clear; only bodies are encrypted. See :mod:`.crypto`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import aiohttp

from . import crypto

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8181
DEFAULT_TIMEOUT = 20

# code_num values that mean "your session is gone". Once a CSRF token is being
# sent, TOS stops answering 403 and instead returns HTTP 200 with one of these,
# so they must be detected from the body rather than the status code.
#   41  logged out       97  no permission / session invalid
#  117  "please login"   14/27/28  session errors handled by the frontend
_REAUTH_CODES = {14, 27, 28, 41, 97, 117}

# The account is valid but lacks the rights for this call -- re-logging in as the
# same user cannot fix it, so this must not be treated as a session problem.
_PERMISSION_DENIED = 90


class TosError(Exception):
    """Base error for TOS API failures."""


class TosAuthError(TosError):
    """Credentials rejected, or the session could not be re-established."""


class TosPermissionError(TosError):
    """The account is valid but not permitted to perform this call.

    A non-administrator TOS account can read every sensor but cannot change
    hardware settings such as the fan mode.
    """


class TosClient:
    """Session-cookie client for the ``/v2`` API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = DEFAULT_PORT,
        session: aiohttp.ClientSession | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._external_session = session is not None
        self._session = session
        self._lock = asyncio.Lock()

        # Refreshed from the headers of every response.
        self._pem: str | None = None
        self._date: str | None = None
        self._csrf: str | None = None
        self._logged_in = False

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # unsafe=True is required: the default jar silently drops cookies
            # set by a bare IP address, which is how this NAS is addressed.
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=self._timeout
            )
            self._external_session = False
        return self._session

    async def close(self) -> None:
        if self._session and not self._external_session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> TosClient:
        await self._ensure_session()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _absorb(self, response: aiohttp.ClientResponse) -> None:
        """Harvest the rolling crypto material every response carries."""
        if (token := response.headers.get("x-rsa-token")) is not None:
            self._pem = base64.b64decode(token).decode()
        if (date := response.headers.get("Date")) is not None:
            self._date = date
        for cookie in response.cookies.values():
            if cookie.key == "X-Csrf-Token":
                self._csrf = cookie.value

    async def bootstrap(self) -> None:
        """Prime the PEM/CSRF/Date triple.

        Any endpoint works -- ``/v2/login/state`` answers 403 when logged out and
        still returns all three headers.
        """
        session = await self._ensure_session()
        async with session.get(f"{self.base_url}/v2/login/state") as resp:
            self._absorb(resp)
        if not self._pem or not self._date:
            raise TosError("TOS did not return X-Rsa-Token/Date; is this really TOS 6?")

    async def login(self) -> dict[str, Any]:
        await self.bootstrap()
        assert self._pem is not None
        payload = {
            "username": self._username,
            "password": crypto.rsa_encrypt(self._pem, self._password),
        }
        result = await self._post("/v2/login", payload, _retry=False)
        if not result.get("code"):
            raise TosAuthError(
                f"login rejected: code_num={result.get('code_num')} "
                f"msg={result.get('msg')!r}"
            )
        self._logged_in = True
        return result

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        session = await self._ensure_session()
        if not path.startswith("/v2"):
            path = "/v2" + path

        # The frontend attaches the CSRF token to *every* request, GETs included;
        # without it TOS answers 403 even with a valid session cookie.
        headers = dict(kwargs.pop("headers", {}) or {})
        if self._csrf:
            headers.setdefault("X-Csrf-Token", self._csrf)
        headers.setdefault("Referer", f"{self.base_url}/tos/")

        async with session.request(
            method, f"{self.base_url}{path}", headers=headers, **kwargs
        ) as resp:
            self._absorb(resp)
            body = await resp.text()
            if not body:
                return resp.status, {}
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError as err:
                raise TosError(f"{path}: non-JSON response {body[:120]!r}") from err

    async def get(self, path: str, _retry: bool = True) -> dict[str, Any]:
        """GET a plaintext endpoint, re-authenticating once if the session lapsed."""
        status, data = await self._request("GET", path)
        if self._needs_reauth(status, data):
            if not _retry:
                raise TosAuthError(f"{path}: not authenticated")
            await self.login()
            return await self.get(path, _retry=False)
        self._raise_for_envelope(path, data)
        return data

    async def _post(
        self, path: str, payload: dict[str, Any], _retry: bool = True
    ) -> dict[str, Any]:
        if not self._pem or not self._date:
            await self.bootstrap()
        assert self._pem is not None and self._date is not None

        # The salt and X-Security-Code must derive from the SAME Date string, or
        # the server cannot reconstruct the key.
        date = self._date
        key = crypto.derive_key(self._pem, date)
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "X-Security-Code": crypto.security_code(date),
        }
        body = {"enc": crypto.encrypt_body(json.dumps(payload), key)}
        status, data = await self._request("POST", path, json=body, headers=headers)
        if self._needs_reauth(status, data):
            if not _retry:
                raise TosAuthError(f"{path}: not authenticated")
            await self.login()
            return await self._post(path, payload, _retry=False)
        if path != "/v2/login":
            self._raise_for_envelope(path, data)
        return data

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST an encrypted body. Serialised: the envelope is time-sensitive."""
        async with self._lock:
            return await self._post(path, payload)

    @staticmethod
    def _needs_reauth(status: int, data: dict[str, Any]) -> bool:
        if status == 403:
            return True
        return data.get("code_num") in _REAUTH_CODES

    @staticmethod
    def _raise_for_envelope(path: str, data: dict[str, Any]) -> None:
        """Turn ``{"code": false, ...}`` into an exception.

        TOS reports most failures as HTTP 200 with ``code: false`` and a null
        ``data``. Without this the coordinator would quietly publish empty
        values instead of surfacing the problem.
        """
        if not isinstance(data, dict) or data.get("code", True):
            return
        message = data.get("code_msg") or data.get("msg") or "unknown error"
        if data.get("code_num") == _PERMISSION_DENIED:
            raise TosPermissionError(f"{path}: {message}")
        raise TosError(f"{path}: {message} (code_num={data.get('code_num')})")

    # ---- endpoint wrappers -------------------------------------------------

    async def hardware(self) -> dict[str, Any]:
        """``{fan: {is_auto, level}, stand_by, ...}``"""
        return await self.get("/hardware/")

    async def set_hardware(self, hardware: dict[str, Any]) -> dict[str, Any]:
        """Read-modify-write: TOS expects the whole hardware object back."""
        return await self.post("/hardware/set", hardware)

    async def temperature(self) -> dict[str, Any]:
        return await self.get("/resource/temperature")

    async def disks(self) -> dict[str, Any]:
        return await self.get("/disk/GetDiskListData")

    async def disk_health(self) -> dict[str, Any]:
        return await self.get("/disk/IhmInfoList")

    async def disk_monitor(self) -> dict[str, Any]:
        return await self.get("/systemStatus/DiskListMonitor")

    async def processor(self) -> dict[str, Any]:
        return await self.get("/systemStatus/NasProcessorInfo")

    async def pools(self) -> dict[str, Any]:
        return await self.get("/storage/list/pool")

    async def volumes(self) -> dict[str, Any]:
        return await self.get("/storage/list/volume")
