import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from store_operator.channels.douyin import (
    DOUYIN_REFRESH_URL,
    DOUYIN_TOKEN_URL,
    DOUYIN_USERINFO_URL,
    DOUYIN_VIDEO_CREATE_URL,
    DOUYIN_VIDEO_LIST_URL,
    DOUYIN_VIDEO_UPLOAD_URL,
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
        scopes=frozenset({"user_info", "video.create.bind"}),
    )
    query = parse_qs(urlsplit(url).query)
    assert query["client_key"] == ["test-client"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["user_info,video.create.bind"]
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


def test_exchange_code_uses_form_post_and_parses_token_response(credentials):
    async def run():
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
                        "scope": "user_info,video.create.bind",
                        "expires_in": 1296000,
                        "refresh_expires_in": 2592000,
                    }
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DouyinOAuthClient(credentials, http_client=http)
        tokens = await client.exchange_code("one-time-code")
        assert tokens.open_id == "open-123"
        assert tokens.scope == frozenset({"user_info", "video.create.bind"})
        assert tokens.expires_in == 1296000
        assert "access-secret" not in repr(tokens)
        await http.aclose()

    asyncio.run(run())


def test_refresh_uses_refresh_token_grant(credentials):
    async def run():
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

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DouyinOAuthClient(credentials, http_client=http)
        tokens = await client.refresh_access_token("old-refresh")
        assert tokens.access_token == "new-access"
        await http.aclose()

    asyncio.run(run())


def test_profile_and_video_list_use_user_access_token(credentials):
    async def run():
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url == DOUYIN_USERINFO_URL:
                return httpx.Response(
                    200,
                    json={"data": {"error_code": "0", "open_id": "open-123", "nickname": "Store"}},
                )
            assert request.url.path == "/video/list/"
            assert request.headers["access-token"] == "user-access"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "error_code": 0,
                        "list": [{"item_id": "item-1"}],
                        "cursor": 10,
                        "has_more": True,
                    }
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DouyinOAuthClient(credentials, http_client=http)
        profile = await client.get_account_profile("user-access")
        videos = await client.list_account_videos(access_token="user-access", open_id="open-123")
        assert profile["open_id"] == "open-123"
        assert videos["items"][0]["item_id"] == "item-1"
        assert len(calls) == 2
        await http.aclose()

    asyncio.run(run())


def test_upload_and_publish_requires_explicit_confirmation(credentials):
    async def run():
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/api/douyin/v1/video/upload_video/":
                assert request.method == "POST"
                assert request.headers["access-token"] == "user-access"
                assert b"name=\"video\"" in request.content
                return httpx.Response(
                    200,
                    json={"data": {"error_code": 0, "video": {"video_id": "encrypted-video-id"}}},
                )
            assert request.url.path == "/api/douyin/v1/video/create_video/"
            assert request.url.params["open_id"] == "open-123"
            assert request.headers["access-token"] == "user-access"
            assert b'"video_id":"encrypted-video-id"' in request.content
            return httpx.Response(
                200, json={"data": {"error_code": 0, "item_id": "external-item-id"}}
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DouyinOAuthClient(credentials, http_client=http)
        with pytest.raises(ValueError):
            await client.publish_video(
                access_token="user-access",
                open_id="open-123",
                video_id="encrypted-video-id",
                text="店庆活动",
                merchant_confirmed=False,
            )
        assert calls == []
        uploaded = await client.upload_video(
            access_token="user-access",
            open_id="open-123",
            filename="promo.mp4",
            content=b"video-bytes",
            content_type="video/mp4",
        )
        receipt = await client.publish_video(
            access_token="user-access",
            open_id="open-123",
            video_id=uploaded["video_id"],
            text="店庆活动",
            merchant_confirmed=True,
        )
        assert receipt.item_id == "external-item-id"
        assert receipt.normalized_status == "processing"
        await http.aclose()

    asyncio.run(run())


def test_publish_readback_verifies_external_item_id(credentials):
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/video/list/"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "error_code": 0,
                        "list": [{"item_id": "external-item-id", "is_reviewed": True}],
                        "cursor": 0,
                        "has_more": False,
                    }
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DouyinOAuthClient(credentials, http_client=http)
        item = await client.verify_published_item(
            access_token="user-access", open_id="open-123", item_id="external-item-id"
        )
        assert item is not None
        assert item["is_reviewed"] is True
        await http.aclose()

    asyncio.run(run())


def test_platform_error_is_sanitized(credentials):
    async def run():
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": {"error_code": 10013, "description": "client_secret=test-secret"}},
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DouyinOAuthClient(credentials, http_client=http)
        with pytest.raises(DouyinApiError) as error:
            await client.exchange_code("code")
        assert "test-secret" not in str(error.value)
        await http.aclose()

    asyncio.run(run())
