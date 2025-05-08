"""
Test suite for authentication and access control functionality in NyaProxy.
Focuses on testing the AuthManager class in nya.server.auth.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from nya.server.auth import AuthManager, AuthMiddleware


class TestAuthManager:
    """Test suite for AuthManager class"""

    def setup_method(self):
        """Setup before each test"""
        # Create mock config manager
        self.mock_config = MagicMock()
        self.auth_manager = AuthManager(config=self.mock_config)

    @pytest.mark.parametrize(
        "configured_key,test_key,expected",
        [
            # Basic matching cases
            ("test_key", "test_key", True),
            ("test_key", "wrong_key", False),
            # Empty or special configured keys (meaning no auth required)
            ("", "any_key", True),
            ("none", "any_key", True),
            ("null", "any_key", True),
            (" null ", "any_key", True),  # With whitespace
            # Whitespace handling
            (" test_key ", "test_key", True),
            ("test_key", " test_key ", True),
            # None as configured key (no auth required)
            (None, "any_key", True),
            # List cases
            (["master_key", "secondary_key"], "master_key", True),
            (["master_key", "secondary_key"], "secondary_key", True),
            (["master_key", "secondary_key"], "wrong_key", False),
            ([], "any_key", True),  # Empty list means no auth
        ],
    )
    def test_verify_api_key(self, configured_key, test_key, expected):
        """Test API key verification with various key configurations"""
        self.mock_config.get_api_key.return_value = configured_key
        result = self.auth_manager.verify_api_key(test_key)
        assert result == expected

    @pytest.mark.parametrize(
        "configured_key,test_key,verify_master,expected",
        [
            # Master key verification (only first key in list is checked)
            (["master_key", "secondary_key"], "master_key", True, True),
            (["master_key", "secondary_key"], "secondary_key", True, False),
            (["master_key", "secondary_key"], "secondary_key", False, True),
            ([], "any_key", True, True),  # Empty list still means no auth
        ],
    )
    def test_verify_api_key_master_mode(
        self, configured_key, test_key, verify_master, expected
    ):
        """Test API key verification in master mode"""
        self.mock_config.get_api_key.return_value = configured_key
        result = self.auth_manager.verify_api_key(test_key, verify_master=verify_master)
        assert result == expected

    def test_verify_api_key_invalid_type(self):
        """Test verification with invalid key type"""
        with pytest.raises(ValueError, match="API key must be a string"):
            self.auth_manager.verify_api_key(123)

    @pytest.mark.asyncio
    async def test_verify_api_access_no_key_configured(self):
        """Test API access when no key is configured"""
        self.mock_config.get_api_key.return_value = ""
        result = await self.auth_manager.verify_api_access(api_key="")
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_api_access_key_required_not_provided(self):
        """Test API access when key is required but not provided"""
        self.mock_config.get_api_key.return_value = "test_key"
        with pytest.raises(HTTPException) as exc:
            await self.auth_manager.verify_api_access(api_key=None)
        assert exc.value.status_code == 401
        assert "API key required" in exc.value.detail

    @pytest.mark.asyncio
    async def test_verify_api_access_invalid_key(self):
        """Test API access with invalid key"""
        self.mock_config.get_api_key.return_value = "test_key"
        with pytest.raises(HTTPException) as exc:
            await self.auth_manager.verify_api_access(api_key="wrong_key")
        assert exc.value.status_code == 403
        assert "Insufficient Permissions" in exc.value.detail

    @pytest.mark.asyncio
    async def test_verify_api_access_valid_key(self):
        """Test API access with valid key"""
        self.mock_config.get_api_key.return_value = "test_key"
        result = await self.auth_manager.verify_api_access(api_key="test_key")
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_api_access_bearer_token(self):
        """Test API access with Bearer token format"""
        self.mock_config.get_api_key.return_value = "test_key"
        result = await self.auth_manager.verify_api_access(api_key="Bearer test_key")
        assert result is True

    def test_verify_session_cookie(self):
        """Test session cookie verification"""
        # Setup
        self.mock_config.get_api_key.return_value = ["master_key", "secondary_key"]
        mock_request = MagicMock()

        # Valid master key in cookie
        mock_request.cookies.get.return_value = "master_key"
        assert self.auth_manager.verify_session_cookie(mock_request) is True

        # Secondary key in cookie - should fail as verify_master=True
        mock_request.cookies.get.return_value = "secondary_key"
        assert self.auth_manager.verify_session_cookie(mock_request) is False

        # Invalid key in cookie
        mock_request.cookies.get.return_value = "wrong_key"
        assert self.auth_manager.verify_session_cookie(mock_request) is False

        # No cookie
        mock_request.cookies.get.return_value = ""
        assert self.auth_manager.verify_session_cookie(mock_request) is False

    def test_verify_api_key_header(self):
        """Test API key header verification"""
        # Setup
        self.mock_config.get_api_key.return_value = ["master_key", "secondary_key"]
        mock_request = MagicMock()

        # Valid keys in header
        mock_request.headers.get.return_value = "master_key"
        assert self.auth_manager.verify_api_key_header(mock_request) is True

        mock_request.headers.get.return_value = "secondary_key"
        assert self.auth_manager.verify_api_key_header(mock_request) is True

        # Bearer format
        mock_request.headers.get.return_value = "Bearer master_key"
        assert self.auth_manager.verify_api_key_header(mock_request) is True

        # Invalid key
        mock_request.headers.get.return_value = "wrong_key"
        assert self.auth_manager.verify_api_key_header(mock_request) is False


class TestAuthMiddleware:
    """Test suite for AuthMiddleware class"""

    def setup_method(self):
        """Setup before each test"""
        self.mock_auth = MagicMock(spec=AuthManager)
        self.mock_app = MagicMock()
        self.middleware = AuthMiddleware(self.mock_app, self.mock_auth)

    @pytest.mark.asyncio
    async def test_dispatch_excluded_paths(self):
        """Test bypassing auth for excluded paths"""
        mock_request = MagicMock()
        mock_request.url.path = "/docs"
        mock_call_next = AsyncMock()
        mock_call_next.return_value = MagicMock()

        await self.middleware.dispatch(mock_request, mock_call_next)

        # Verify that we didn't check auth for excluded paths
        assert not self.mock_auth.verify_session_cookie.called
        assert not self.mock_auth.verify_api_key_header.called
        mock_call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_dispatch_no_key_configured(self):
        """Test dispatch when no API key is configured"""
        # Setup
        mock_request = MagicMock()
        mock_request.url.path = "/api/something"
        mock_call_next = AsyncMock()
        mock_call_next.return_value = MagicMock()

        # Case 1: None as key
        self.mock_auth.get_api_key.return_value = None
        await self.middleware.dispatch(mock_request, mock_call_next)
        mock_call_next.assert_called_once_with(mock_request)
        mock_call_next.reset_mock()

        # Case 2: Empty string as key
        self.mock_auth.get_api_key.return_value = ""
        await self.middleware.dispatch(mock_request, mock_call_next)
        mock_call_next.assert_called_once_with(mock_request)
        mock_call_next.reset_mock()

        # Case 3: Empty list as key
        self.mock_auth.get_api_key.return_value = []
        await self.middleware.dispatch(mock_request, mock_call_next)
        mock_call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_dispatch_valid_session_cookie(self):
        """Test dispatch with valid session cookie"""
        # Setup
        mock_request = MagicMock()
        mock_request.url.path = "/api/something"
        mock_call_next = AsyncMock()
        mock_call_next.return_value = MagicMock()

        self.mock_auth.get_api_key.return_value = "test_key"
        self.mock_auth.verify_session_cookie.return_value = True

        await self.middleware.dispatch(mock_request, mock_call_next)

        # Verify that auth was checked and request was processed
        self.mock_auth.verify_session_cookie.assert_called_once_with(mock_request)
        mock_call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_dispatch_valid_api_key_header(self):
        """Test dispatch with valid API key header"""
        # Setup
        mock_request = MagicMock()
        mock_request.url.path = "/api/something"
        mock_call_next = AsyncMock()
        mock_call_next.return_value = MagicMock()

        self.mock_auth.get_api_key.return_value = "test_key"
        self.mock_auth.verify_session_cookie.return_value = False
        self.mock_auth.verify_api_key_header.return_value = True

        await self.middleware.dispatch(mock_request, mock_call_next)

        # Verify that both auth methods were checked and request was processed
        self.mock_auth.verify_session_cookie.assert_called_once_with(mock_request)
        self.mock_auth.verify_api_key_header.assert_called_once_with(mock_request)
        mock_call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    @patch("nya.server.auth.JSONResponse")
    async def test_dispatch_api_unauthorized(self, mock_json_response):
        """Test unauthorized access to API endpoints"""
        # Setup
        mock_request = MagicMock()
        mock_request.url.path = "/api/something"
        mock_call_next = AsyncMock()  # Changed to AsyncMock

        self.mock_auth.get_api_key.return_value = "test_key"
        self.mock_auth.verify_session_cookie.return_value = False
        self.mock_auth.verify_api_key_header.return_value = False

        await self.middleware.dispatch(mock_request, mock_call_next)

        # Verify that both auth methods were checked and error response returned
        self.mock_auth.verify_session_cookie.assert_called_once_with(mock_request)
        self.mock_auth.verify_api_key_header.assert_called_once_with(mock_request)
        mock_json_response.assert_called_once()
        assert mock_json_response.call_args[1]["status_code"] == 403
        assert "Unauthorized" in mock_json_response.call_args[1]["content"]["error"]

    @pytest.mark.asyncio
    @patch("importlib.resources.files")
    async def test_dispatch_dashboard_unauthorized(self, mock_resources_files):
        """Test unauthorized access to dashboard endpoints"""
        # Setup mocks for the _generate_login_page method
        mock_file_path = MagicMock()
        mock_file = MagicMock()
        mock_file.open.return_value.__enter__.return_value.read.return_value = (
            "{{ return_path }}"
        )
        mock_resources_files.return_value.__truediv__.return_value = mock_file_path
        mock_file_path.open.return_value.__enter__.return_value.read.return_value = (
            "{{ return_path }}"
        )

        # Setup request
        mock_request = MagicMock()
        mock_request.url.path = "/dashboard"
        mock_call_next = AsyncMock()  # Changed to AsyncMock

        self.mock_auth.get_api_key.return_value = "test_key"
        self.mock_auth.verify_session_cookie.return_value = False
        self.mock_auth.verify_api_key_header.return_value = False

        response = await self.middleware.dispatch(mock_request, mock_call_next)

        # Verify both auth methods were checked
        self.mock_auth.verify_session_cookie.assert_called_once_with(mock_request)
        self.mock_auth.verify_api_key_header.assert_called_once_with(mock_request)

        # Verify response is HTMLResponse with status code 401
        assert response.status_code == 401
        assert hasattr(response, "body")
