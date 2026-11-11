from __future__ import annotations

# ruff: noqa: I001

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
DOUYIN_VIDEO_UPLOAD_URL = f"{DOUYIN_API_BASE}/video/upload/"
DOUYIN_VIDEO_CREATE_URL = f"{DOUYIN_API_BASE}/video/create/"
DOUYIN_IMAGE_UPLOAD_URL = f"{DOUYIN_API_BASE}/image/upload/"
DOUYIN_IMAGE_CREATE_URL = f"{DOUYIN_API_BASE}/image_text/create/"
MAX_SINGLE_VIDEO_UPLOAD_BYTES = 128 * 1024 * 1024
MAX_DOUYIN_IMAGE_BYTES = 20 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class DouyinPublishReceipt:
    item_id: str
    normalized_status: str = "processing"
    # Douyin performs review after content creation. The item is not necessarily
    # publicly visible when this receipt is returned.
    public_url: str | None = None


class DouyinOAuthClient:
    """Server-side Douyin website OAuth and content publishing OpenAPI client.

    This adapter deliberately does not persist tokens. Callers must store returned
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
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))

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
        }

    async def list_account_videos(
        self, *, access_token: str, open_id: str, cursor: int = 0, count: int = 10
    ) -> dict[str, Any]:
        if cursor < 0 or count <= 0:
            raise ValueError("Invalid Douyin video-list pagination")
        response = await self._http.get(
            DOUYIN_VIDEO_LIST_URL,
            params={"open_id": open_id, "cursor": cursor, "count": count},
            headers={"access-token": access_token, "Content-Type": "application/json"},
        )
        data = self._data(self._decode_response(response))
        return {
            "items": data.get("list", []),
            "cursor": data.get("cursor", cursor),
            "has_more": bool(data.get("has_more", False)),
        }

    async def upload_video(
        self,
        *,
        access_token: str,
        open_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("Video content is required")
        if len(content) > MAX_SINGLE_VIDEO_UPLOAD_BYTES:
            raise ValueError("Videos above 128 MiB require the official multipart upload flow")
        if content_type not in {"video/mp4", "video/webm"}:
            raise ValueError("Only MP4 and WebM video uploads are enabled for the pilot")
        response = await self._http.post(
            DOUYIN_VIDEO_UPLOAD_URL,
            params={"open_id": open_id},
            headers={"access-token": access_token},
            files={"video": (filename, content, content_type)},
        )
        data = self._data(self._decode_response(response))
        video = data.get("video")
        if not isinstance(video, dict) or not video.get("video_id"):
            raise DouyinApiError("MISSING_VIDEO_ID", "Douyin upload response is incomplete")
        return {
            "video_id": str(video["video_id"]),
            "width": video.get("width"),
            "height": video.get("height"),
        }

    async def upload_image(
        self,
        *,
        access_token: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("Image content is required")
        if len(content) > MAX_DOUYIN_IMAGE_BYTES:
            raise ValueError("Each image in a Douyin image-text post must not exceed 20 MiB")
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Only JPEG, PNG and WebP images are enabled for the pilot")
        response = await self._http.post(
            DOUYIN_IMAGE_UPLOAD_URL,
            headers={"access-token": access_token},
            files={"image": (filename, content, content_type)},
        )
        data = self._data(self._decode_response(response))
        image = data.get("image")
        if not isinstance(image, dict) or not image.get("image_id"):
            raise DouyinApiError("MISSING_IMAGE_ID", "Douyin image upload response is incomplete")
        return {
            "image_id": str(image["image_id"]),
            "width": image.get("width"),
            "height": image.get("height"),
        }

    async def publish_images(
        self,
        *,
        access_token: str,
        open_id: str,
        image_ids: list[str],
        text: str,
        merchant_confirmed: bool,
    ) -> DouyinPublishReceipt:
        if not merchant_confirmed:
            raise ValueError("Explicit merchant confirmation is required before publishing")
        if not 1 <= len(image_ids) <= 30 or any(not item for item in image_ids):
            raise ValueError("Douyin image-text posts require between 1 and 30 uploaded images")
        if not text.strip() or len(text) > 1000:
            raise ValueError("Douyin image-text post text must contain 1-1000 characters")
        response = await self._http.post(
            DOUYIN_IMAGE_CREATE_URL,
            params={"open_id": open_id},
            headers={"access-token": access_token, "Content-Type": "application/json"},
            json={"image_list": image_ids, "text": text},
        )
        data = self._data(self._decode_response(response))
        if not data.get("item_id"):
            raise DouyinApiError("MISSING_ITEM_ID", "Douyin image-text response is incomplete")
        return DouyinPublishReceipt(item_id=str(data["item_id"]))

    async def publish_video(
        self,
        *,
        access_token: str,
        open_id: str,
        video_id: str,
        text: str,
        merchant_confirmed: bool,
    ) -> DouyinPublishReceipt:
        if not merchant_confirmed:
            raise ValueError("Explicit merchant confirmation is required before publishing")
        if not video_id or not text.strip():
            raise ValueError("Uploaded video_id and non-empty post text are required")
        if len(text) > 1000:
            raise ValueError("Douyin post text must not exceed 1000 characters")
        response = await self._http.post(
            DOUYIN_VIDEO_CREATE_URL,
            params={"open_id": open_id},
            headers={"access-token": access_token, "Content-Type": "application/json"},
            json={"video_id": video_id, "text": text},
        )
        data = self._data(self._decode_response(response))
        if not data.get("item_id"):
            raise DouyinApiError("MISSING_ITEM_ID", "Douyin publish response is incomplete")
        return DouyinPublishReceipt(item_id=str(data["item_id"]))

    async def verify_published_item(
        self, *, access_token: str, open_id: str, item_id: str
    ) -> dict[str, Any] | None:
        """Read back the account video list; None means not yet observable, not failure."""
        cursor = 0
        for _ in range(4):  # Official API currently documents a maximum of four pages.
            page = await self.list_account_videos(
                access_token=access_token, open_id=open_id, cursor=cursor, count=20
            )
            for item in page["items"]:
                if isinstance(item, dict) and str(item.get("item_id", "")) == item_id:
                    return {str(key): value for key, value in item.items()}
            if not page["has_more"]:
                break
            next_cursor = int(page["cursor"])
            if next_cursor <= cursor:
                break
            cursor = next_cursor
        return None

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
        raw_scope = str(data.get("scope", ""))
        scopes = frozenset(raw_scope.replace(",", " ").split())
        return DouyinTokenSet(
            open_id=str(data["open_id"]),
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            scope=scopes,
            expires_in=int(data.get("expires_in", 0)),
            refresh_expires_in=int(data.get("refresh_expires_in", 0)),
        )
