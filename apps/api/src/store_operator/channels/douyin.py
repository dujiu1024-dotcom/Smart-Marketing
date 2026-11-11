from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx


DOUYIN_API_BASE = "https://open.douyin.com"
DOUYIN_AUTHORIZE_URL = f"{DOUYIN_API_BASE}/platform/oauth/connect/"
DOUYIN_TOKEN_URL = f"{DOUYIN_API_BASE}/oauth/access_token/"
DOUYIN_REFRESH_URL = f"{DOUYIN_API_BASE}/oauth/refresh_token/"
DOUYIN_USERINFO_URL = f"{DOUYIN_API_BASE}/oauth/userinfo/"
DOUYIN_VIDEO_LIST_URL = f"{DOUYIN_API_BASE}/video/list/"


class DouyinApiError(RuntimeError):
    """Sanitized platform error; never includes request headers or credentials."""

    def __init__(self, code: int | str, message: str = "Douyin API request failed") -> None:
        self.code = str(code)
        super().__init__(f"{message} (code={self.code})")


@dataclass(frozen=True, slots=True)
class DouyinAppCredentials:
    client_key: str
    client_secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DouyinTokenSet:
    open_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    scope: frozenset[str]
    expires_in: int
    refresh_expires_in: int


class DouyinOAuthClient:
    """Server-side Douyin website OAuth/OpenAPI client.

    This class deliberately does not persist tokens. Callers must store returned
    credentials through the approved Secret Manager adapter, never in browser
    storage, ordinary logs, Outbox payloads, or plaintext database columns.
    """

    def __init__(
        self,
        credentials: DouyinAppCredentials,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not credentials.client_key.strip() or not credentials.client_secret.strip():
            raise ValueError("Douyin app credentials must not be empty")
        self._credentials = credentials
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    def build_authorization_url(
        self, *, redirect_uri: str, state: str, scopes: frozenset[str]
    ) -> str:
        if not redirect_uri.startswith("https://"):
            raise ValueError("Douyin OAuth redirect_uri must use HTTPS")
        if not state or len(state) < 32:
            raise ValueError("OAuth state must be a cryptographically random value")
        if not scopes:
            raise ValueError("At least one approved OAuth scope is required")
        query = urlencode(
            {
                "client_key": self._credentials.client_key,
                "response_type": "code",
                "scope": ",".join(sorted(scopes)),
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{DOUYIN_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> DouyinTokenSet:
        if not code:
            raise ValueError("OAuth authorization code is required")
        payload = await self._post_form(
            DOUYIN_TOKEN_URL,
            {
                "client_key": self._credentials.client_key,
                "client_secret": self._credentials.client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        return self._parse_token_set(payload)

    async def refresh_access_token(self, refresh_token: str) -> DouyinTokenSet:
        if not refresh_token:
            raise ValueError("Refresh token is required")
        payload = await self._post_form(
            DOUYIN_REFRESH_URL,
            {
                "client_key": self._credentials.client_key,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        return self._parse_token_set(payload)

    async def get_account_profile(self, access_token: str) -> dict[str, Any]:
        payload = await self._post_json(DOUYIN_USERINFO_URL, access_token, {})
        data = self._data(payload)
        if not data.get("open_id"):
            raise DouyinApiError("MISSING_OPEN_ID", "Douyin profile response is incomplete")
        return {
            "open_id": str(data["open_id"]),
            "nickname": data.get("nickname"),
            "avatar": data.get("avatar"),
            "scope_evidence": "user_info",
        }

    async def list_account_videos(
        self, *, access_token: str, open_id: str, cursor: int = 0, count: int = 10
    ) -> dict[str, Any]:
        if cursor < 0 or not 1 <= count <= 20:
            raise ValueError("Invalid Douyin video-list pagination")
        response = await self._http.get(
            DOUYIN_VIDEO_LIST_URL,
            params={"open_id": open_id, "cursor": cursor, "count": count},
            headers={"access-token": access_token, "Content-Type": "application/json"},
        )
        payload = self._decode_response(response)
        data = self._data(payload)
        return {
            "items": data.get("list", []),
            "cursor": data.get("cursor", cursor),
            "has_more": bool(data.get("has_more", False)),
        }

    async def _post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        response = await self._http.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return self._decode_response(response)

    async def _post_json(
        self, url: str, access_token: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._http.post(
            url,
            json=body,
            headers={"access-token": access_token, "Content-Type": "application/json"},
        )
        return self._decode_response(response)

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Do not propagate response text: provider errors can echo sensitive values.
            raise DouyinApiError(response.status_code, "Douyin transport failed") from exc
        if not isinstance(payload, dict):
            raise DouyinApiError("INVALID_RESPONSE", "Douyin returned an invalid response")
        return payload

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise DouyinApiError("INVALID_RESPONSE", "Douyin returned an invalid response")
        error_code = data.get("error_code", 0)
        if str(error_code) not in {"0", "None"}:
            raise DouyinApiError(error_code, "Douyin rejected the request")
        return data

    @classmethod
    def _parse_token_set(cls, payload: dict[str, Any]) -> DouyinTokenSet:
        data = cls._data(payload)
        required = ("open_id", "access_token", "refresh_token")
        if any(not data.get(key) for key in required):
            raise DouyinApiError("INCOMPLETE_TOKEN", "Douyin token response is incomplete")
        scopes = frozenset(str(data.get("scope", "")).split())
        return DouyinTokenSet(
            open_id=str(data["open_id"]),
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            scope=scopes,
            expires_in=int(data.get("expires_in", 0)),
            refresh_expires_in=int(data.get("refresh_expires_in", 0)),
        )
