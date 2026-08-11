"""Comprehensive tests for haier/http_client.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.haier_home.haier.http_client import HaierAPIError, HaierHttpClient


class TestHaierHttpClientInitialization:
    """Test client initialization."""

    def test_default_server(self):
        """Test default cloud server is cn."""
        client = HaierHttpClient(
            hass=MagicMock(),
        )
        assert client._region == "cn"
        assert client._host == "ha.haier.net"


class TestHaierHttpClientSigning:
    """Test signature generation."""

    def test_generate_sign(self):
        """Test sign generation includes required components."""
        client = HaierHttpClient(
            hass=MagicMock(),
        )
        client._app_key = "test_key"
        sign, timestamp = client._generate_signature("/test/path", '{"test": "data"}')

        assert len(sign) == 64
        assert isinstance(timestamp, str)
        assert len(timestamp) >= 13


class TestHaierHttpClientEnsureSession:
    """Test _ensure_session method."""

    @pytest.mark.asyncio
    async def test_ensure_session_creates_new_session(self):
        """Test creating a new session."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        await client._ensure_session()
        assert client._session is not None

    @pytest.mark.asyncio
    async def test_ensure_session_raises_when_closed(self):
        """Test _ensure_session raises when client is closed."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        client._closed = True
        with pytest.raises(RuntimeError, match="HaierHttpClient has been closed"):
            await client._ensure_session()


class TestHaierHttpClientProperties:
    """Test properties."""

    def test_token_provider_resolves_current_token(self):
        """The client holds no token; it reads the current one via token_provider."""
        token_holder = {"value": "test_token"}
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: token_holder["value"])
        assert client.token_provider() == "test_token"

        # A later provider result (e.g. after a coordinator refresh) is seen live.
        token_holder["value"] = "new_token"
        assert client.token_provider() == "new_token"


class TestHaierHttpClientAPIMethods:
    """Test public API methods."""

    @pytest.mark.asyncio
    async def test_get_homes(self):
        """Test get_homes method."""
        mock_response = {"createfamilies": []}

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.get_homes()
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_get_scenes(self):
        """Test get_scenes method."""
        mock_response = {}

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.get_scenes(["family_001"])
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_get_devices(self):
        """Test get_devices method."""
        mock_response = {
            "deviceInfos": [
                {"deviceId": "device_001", "familyId": "family_001"},
                {"deviceId": "device_002", "familyId": "family_002"},
            ]
        }

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.get_devices(["family_001"])
            assert len(result["deviceInfos"]) == 1
            assert result["deviceInfos"][0]["deviceId"] == "device_001"

    @pytest.mark.asyncio
    async def test_get_devices_no_filter(self):
        """Test get_devices without filter."""
        mock_response = {
            "deviceInfos": [
                {"deviceId": "device_001", "familyId": "family_001"},
            ]
        }

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.get_devices()
            assert len(result["deviceInfos"]) == 1

    @pytest.mark.asyncio
    async def test_get_device_digital_model(self):
        """Test get_device_digital_model method."""
        mock_response = {"attributes": []}

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.get_device_digital_model("device_001")
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_execute_scene(self):
        """Test execute_scene method."""
        mock_response = {}

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.execute_scene("family_001", "scene_001")
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_get_account_info(self):
        """Test get_account_info method."""
        mock_response = {}

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.get_account_info()
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_logout(self):
        """Test logout method."""
        mock_response = {}

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        with patch.object(client, "_make_request", AsyncMock(return_value=mock_response)):
            result = await client.logout()
            assert result == mock_response


class TestHaierHttpClientClose:
    """Test close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method drops session without closing the shared global one."""
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session.closed = False

        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        client._session = mock_session

        await client.close()

        assert client._closed is True
        # The session is HA's shared global session, so close must NOT close it,
        # it only drops the reference.
        mock_session.close.assert_not_called()
        assert client._session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self):
        """Test close method when no session exists."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")

        # Should not raise
        await client.close()


class TestHaierHttpClientRiskNotice:
    """Test get_risk_notice method."""

    @pytest.mark.asyncio
    async def test_get_risk_notice_success(self):
        """Test get_risk_notice success."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")

        # Create mock response that is both awaitable and async context manager
        class MockResponse:
            def raise_for_status(self):
                pass

            async def json(self):
                return {"retCode": "00000", "data": {"content": "Risk notice content"}}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __await__(self):
                async def _awaiter():
                    return self

                return _awaiter().__await__()

        # Create mock session with closed attribute
        class MockSession:
            closed = False

            def get(self, *args, **kwargs):
                return MockResponse()

        client._session = MockSession()

        result = await client.get_risk_notice()
        assert result == "Risk notice content"

    @pytest.mark.asyncio
    async def test_get_risk_notice_api_error(self):
        """Test get_risk_notice when API returns error."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")

        class MockResponse:
            def raise_for_status(self):
                pass

            async def json(self):
                return {"retCode": "E0001"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __await__(self):
                async def _awaiter():
                    return self

                return _awaiter().__await__()

        class MockSession:
            closed = False

            def get(self, *args, **kwargs):
                return MockResponse()

        client._session = MockSession()

        result = await client.get_risk_notice()
        assert result is None


class TestHaierAPIError:
    """Test HaierAPIError class."""

    def test_error_with_code_and_message(self):
        """Test HaierAPIError with code and message."""
        error = HaierAPIError("E0001", "Error message")
        assert error.error_code == "E0001"
        assert error.error_message == "Error message"
        assert "E0001" in str(error)
        assert "Error message" in str(error)

    def test_error_with_code_only(self):
        """Test HaierAPIError with code only."""
        error = HaierAPIError("E0001")
        assert error.error_code == "E0001"
        assert error.error_message is None
        assert "E0001" in str(error)

    def test_error_without_code(self):
        """Test HaierAPIError without code."""
        error = HaierAPIError()
        assert error.error_code is None
        assert error.error_message is None


class TestHaierHttpClientMakeRequest:
    """Test _make_request method branches."""

    def _make_mock_response(self, status=200, json_data=None, raise_error=False):
        """Create a mock aiohttp response that works as an async context manager."""
        response = MagicMock()
        response.status = status
        if raise_error:
            response.raise_for_status.side_effect = Exception("HTTP error")
        else:
            response.raise_for_status.return_value = None
        response.json = AsyncMock(return_value=json_data or {"retCode": "00000", "data": {}})
        return response

    def _make_client(self, access_token="test_token", app_key=None):
        """Create a client with a mocked session.

        ``access_token`` is exposed as the client's token via a ``token_provider``
        (the client never stores a token itself). ``None`` yields a provider that
        returns no token, exercising the missing-token path.
        """
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: access_token)
        if app_key is not None:
            client._app_key = app_key
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.request = MagicMock()
        client._session = mock_session
        return client

    @pytest.mark.asyncio
    async def test_make_request_no_provider(self):
        """Test _make_request raises RuntimeError when no token_provider is set."""
        client = self._make_client()
        client.token_provider = None
        with pytest.raises(RuntimeError, match="No token_provider configured"):
            await client._make_request("GET", "/test")

    @pytest.mark.asyncio
    async def test_make_request_uses_token_provider(self):
        """_make_request resolves the token fresh via the provider on each call."""

        def provider():
            return "fresh_token"

        client = HaierHttpClient(
            hass=MagicMock(),
            token_provider=provider,
        )
        response = self._make_mock_response()
        session = MagicMock()
        session.closed = False
        session.request = MagicMock()
        session.request.return_value.__aenter__.return_value = response
        client._session = session

        await client._make_request("GET", "/test")

        # The header the request was actually called with carries the provider
        # token, not the locally-cached one.
        _args, kwargs = session.request.call_args
        assert kwargs["headers"]["accessToken"] == "fresh_token"

    @pytest.mark.asyncio
    async def test_make_request_provider_returns_none(self):
        """Test _make_request raises when the provider yields no token."""

        def provider():
            return None

        client = HaierHttpClient(
            hass=MagicMock(),
            token_provider=provider,
        )
        session = MagicMock()
        session.closed = False
        client._session = session

        with pytest.raises(RuntimeError, match="token_provider returned no token"):
            await client._make_request("GET", "/test")

    @pytest.mark.asyncio
    async def test_make_request_body_dict(self):
        """Test _make_request with dict body (goes through json.dumps)."""
        client = self._make_client()
        response = self._make_mock_response()
        client._session.request.return_value.__aenter__.return_value = response

        result = await client._make_request("POST", "/test", data={"key": "value"})

        _, _, kwargs = client._session.request.mock_calls[0]
        assert kwargs["data"] == '{"key": "value"}'
        assert result == {}

    @pytest.mark.asyncio
    async def test_make_request_body_str(self):
        """Test _make_request with non-dict body."""
        client = self._make_client()
        response = self._make_mock_response()
        client._session.request.return_value.__aenter__.return_value = response

        result = await client._make_request("POST", "/test", data="plain_string")

        _, _, kwargs = client._session.request.mock_calls[0]
        assert kwargs["data"] == "plain_string"
        assert result == {}

    @pytest.mark.asyncio
    async def test_make_request_json_body_serialized_to_data(self):
        """``json=`` body is serialized into ``data`` and never forwarded as both.

        Regression: get_scenes passed ``json={...}``, but _build_auth_kwargs
        forwarded the original ``json`` alongside a new ``data`` key, and
        aiohttp raised "data and json parameters can not be used at the same
        time". The forwarded kwargs must contain ``data`` only.
        """
        client = self._make_client()
        response = self._make_mock_response()
        client._session.request.return_value.__aenter__.return_value = response

        result = await client._make_request("POST", "/test", json={"key": "value"})

        _, _, kwargs = client._session.request.mock_calls[0]
        assert kwargs["data"] == '{"key": "value"}'
        assert "json" not in kwargs
        assert result == {}

    @pytest.mark.asyncio
    async def test_make_request_body_empty(self):
        """Test _make_request with empty body."""
        client = self._make_client()
        response = self._make_mock_response()
        client._session.request.return_value.__aenter__.return_value = response

        result = await client._make_request("GET", "/test")

        _, _, kwargs = client._session.request.mock_calls[0]
        assert kwargs["data"] == ""
        assert result == {}

    @pytest.mark.asyncio
    async def test_make_request_skip_signature_when_no_app_key(self):
        """Test _make_request skips signature when app_key is empty."""
        client = self._make_client(app_key="")
        response = self._make_mock_response()
        client._session.request.return_value.__aenter__.return_value = response

        result = await client._make_request("GET", "/test", signature_required=True)

        _, _, kwargs = client._session.request.mock_calls[0]
        headers = kwargs["headers"]
        assert "sign" not in headers
        assert result == {}

    @pytest.mark.asyncio
    async def test_make_request_http_error(self):
        """Test _make_request when HTTP request fails."""
        client = self._make_client()
        response = self._make_mock_response(status=500, raise_error=True)
        client._session.request.return_value.__aenter__.return_value = response

        with pytest.raises(Exception, match="HTTP error"):
            await client._make_request("GET", "/test")

    @pytest.mark.asyncio
    async def test_make_request_auth_failure_retries_once(self):
        """A 401 triggers refresh + retries once with a freshly rebuilt header (new token)."""
        token_holder = {"value": "stale_token", "calls": 0}

        def provider():
            return token_holder["value"]

        client = HaierHttpClient(
            hass=MagicMock(),
            token_provider=provider,
        )
        client._session = MagicMock()
        client._session.closed = False

        async def handler():
            # Simulate the coordinator force-refresh: the token becomes valid again.
            token_holder["value"] = "refreshed_token"
            token_holder["calls"] += 1

        client.auth_failure_handler = handler

        err_resp = MagicMock()
        err_resp.status = 401
        err_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=401, message="Unauthorized"
        )
        ok_resp = self._make_mock_response()
        client._session.request.return_value.__aenter__.side_effect = [err_resp, ok_resp]

        result = await client._make_request("GET", "/test")

        # Handler invoked once, the request replayed with a rebuilt header.
        assert token_holder["calls"] == 1
        assert client._session.request.call_count == 2
        assert result == {}

        calls = [
            call.kwargs
            for call in client._session.request.call_args_list
            if call.args or call.kwargs
        ]
        access_tokens = [kw["headers"]["accessToken"] for kw in calls]
        assert access_tokens[0] == "stale_token"
        assert access_tokens[1] == "refreshed_token"

    @pytest.mark.asyncio
    async def test_make_request_auth_handler_failure_reports_original(self):
        """If the auth handler itself raises, the original 401 is re-raised."""
        client = self._make_client()

        async def handler():
            raise RuntimeError("refresh boom")

        client.auth_failure_handler = handler

        err_resp = MagicMock()
        err_resp.status = 401
        err_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=401, message="Unauthorized"
        )
        client._session.request.return_value.__aenter__.return_value = err_resp

        with pytest.raises(aiohttp.ClientResponseError) as exc:
            await client._make_request("GET", "/test")
        # The original 401 (not the handler error) is surfaced as the root cause.
        assert exc.value.status == 401
        # The handler failure short-circuits the retry; only the first attempt ran.
        assert client._session.request.call_count == 1

    @pytest.mark.asyncio
    async def test_make_request_auth_failure_no_handler_no_retry(self):
        """A 401 with no auth handler re-raises without retrying."""
        client = self._make_client()
        client.auth_failure_handler = None

        response = self._make_mock_response(status=401, raise_error=True)
        client._session.request.return_value.__aenter__.return_value = response

        with pytest.raises(Exception, match="HTTP error"):
            await client._make_request("GET", "/test")
        assert client._session.request.call_count == 1

    @pytest.mark.asyncio
    async def test_make_request_auth_failure_no_handler_uses_401_clienterror(self):
        """A 401 raises the specific ClientResponseError when no handler is set."""
        client = self._make_client()
        client.auth_failure_handler = None

        err_resp = MagicMock()
        err_resp.status = 401
        err_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=401, message="Unauthorized"
        )
        client._session.request.return_value.__aenter__.return_value = err_resp

        with pytest.raises(aiohttp.ClientResponseError):
            await client._make_request("GET", "/test")
        assert client._session.request.call_count == 1

    @pytest.mark.asyncio
    async def test_make_request_json_decode_error(self):
        """Test _make_request when JSON decoding fails."""
        client = self._make_client()
        response = self._make_mock_response()
        response.json.side_effect = ValueError("Expecting value")
        client._session.request.return_value.__aenter__.return_value = response

        with pytest.raises(ValueError, match="Expecting value"):
            await client._make_request("GET", "/test")

    @pytest.mark.asyncio
    async def test_make_request_api_error(self):
        """Test _make_request when API returns non-zero retCode."""
        client = self._make_client()
        response = self._make_mock_response(json_data={"retCode": "E0001", "retInfo": "Error"})
        client._session.request.return_value.__aenter__.return_value = response

        with pytest.raises(HaierAPIError) as exc_info:
            await client._make_request("GET", "/test")
        assert exc_info.value.error_code == "E0001"
        assert exc_info.value.error_message == "Error"


class TestHaierHttpClientRiskNoticeErrors:
    """Test get_risk_notice error paths."""

    @pytest.mark.asyncio
    async def test_get_risk_notice_client_error(self):
        """Test get_risk_notice handles aiohttp.ClientError."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = MagicMock()
        mock_session.get.side_effect = aiohttp.ClientError("connection failed")
        client._session = mock_session

        result = await client.get_risk_notice()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_risk_notice_timeout_error(self):
        """Test get_risk_notice handles asyncio.TimeoutError."""
        client = HaierHttpClient(hass=MagicMock(), token_provider=lambda: "test_token")
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = MagicMock()
        mock_session.get.side_effect = TimeoutError()
        client._session = mock_session

        result = await client.get_risk_notice()
        assert result is None
