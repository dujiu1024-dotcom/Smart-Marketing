from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from store_operator.channels.douyin import (
    DOUYIN_REFRESH_URL,
    DOUYIN_TOKEN_URL,
    DOUYIN_USERINFO_URL,
    DOUYIN_VIDEO_LIST_URL,
    DouyinApiError,
    DouyinAppCredentials,
    DouyinOAuthClient,
)


@pytest.fixture
def credentials():
    return DouyinAppCredentials(client_key="test-client", client_secret="test-secret")


def test_authorization_url_encodes_scopes_state_and_redirect(credentials):
    client = DouyinOAuthClient(credentials, http_client=httpx.AsyncClient())
    url = client.build_authorization_url(
        redirect_uri="https://app.example.com/api/v1/channel-oauth/douyin/callback",
        state="s" * 48,
        scopes=frozenset({"user_info", "video.create"}),
    )
    query = parse_qs(urlsplit(url).query)
    assert query["client_key"] == ["test-client"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["user_info,video.create"]
    assert query["state"] == ["s" * 48]


def test_authorization_url_requires_https_and_random_state(credentials):
    client = DouyinOAuthClient(credentials, http_client=httpx.AsyncClient())
    with pytest.raises(ValueError):
        client.build_authorization_url(
            redirect_uri="http://app.example.com/callback",
            state="s" * 48,
            scopes=frozenset({"user_info"}),
        )
    with pytest.raises(ValueError):
        client.build_authorization_url(
            redirect_uri="https://app.example.com/callback",
            state="short",
            scopes=frozenset({"user_info"}),
        )


@pytest.mark.asyncio
async def test_exchange_code_uses_form_post_and_parses_token_response(credentials):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == DOUYIN_TOKEN_URL
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
        assert b"grant_type=authorization_code" in request.content
        assert b"client_secret=test-secret" in request.content
        return httpx.Response(
            200,
            json={
                "data": {
                    "error_code": 0,
                    "open_id": "open-123",
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "scope": "user_info video.create",
                    "expires_in": 1296000,
                    "refresh_expires_in": 2592000,
                }
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DouyinOAuthClient(credentials, http_client=http)
    tokens = await client.exchange_code("one-time-code")
    assert tokens.open_id == "open-123"
    assert tokens.scope == frozenset({"user_info", "video.create"})
    assert tokens.expires_in == 1296000
    assert "access-secret" not in repr(tokens)


@pytest.mark.asyncio
async def test_refresh_uses_refresh_token_grant(credentials):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == DOUYIN_REFRESH_URL
        assert b"grant_type=refresh_token" in request.content
        assert b"refresh_token=old-refresh" in request.content
        return httpx.Response(
            200,
            json={
                "data": {
                    "error_code": 0,
                    "open_id": "open-123",
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "scope": "user_info",
                    "expires_in": 86400,
                    "refresh_expires_in": 86400,
                }
            },
        )

    client = DouyinOAuthClient(
        credentials, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    tokens = await client.refresh_access_token("old-refresh")
    assert tokens.access_token == "new-access"


@pytest.mark.asyncio
async def test_profile_and_video_list_use_user_access_token(credentials):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url == DOUYIN_USERINFO_URL:
            return httpx.Response(
                200, json={"data": {"error_code": "0", "open_id": "open-123", "nickname": "Store"}}
            )
        assert request.url == DOUYIN_VIDEO_LIST_URL
        assert request.headers["access-token"] == "user-access"
        return httpx.Response(
            200,
            json={"data": {"error_code": 0, "list": [{"item_id": "item-1"}], "cursor": 10, "has_more": True}},
        )

    client = DouyinOAuthClient(
        credentials, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    profile = await client.get_account_profile("user-access")
    videos = await client.list_account_videos(access_token="user-access", open_id="open-123")
    assert profile["open_id"] == "open-123"
    assert videos["items"][0]["item_id"] == "item-1"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_platform_error_is_sanitized(credentials):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"error_code": 10013, "description": "client_secret=test-secret"}},
        )

    client = DouyinOAuthClient(
        credentials, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(DouyinApiError) as error:
        await client.exchange_code("code")
    assert "test-secret" not in str(error.value)
