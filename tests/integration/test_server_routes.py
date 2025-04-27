import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock

# Assuming refactored structure, adjust imports as necessary
# We need the main app instance created in app.py
# We might need to mock dependencies during app creation for isolated testing
from nya_proxy.server.app import NyaProxyApp
from nya_proxy.server.config import ConfigManager

from fastapi.responses import JSONResponse


# --- Fixtures ---


@pytest.fixture(scope="module")
def test_app_no_auth():
    """
    Provides a TestClient instance for NyaProxyApp where no API key is configured.
    Mocks ConfigManager to simulate this scenario.
    """
    # Mock ConfigManager methods used during NyaProxyApp initialization and by AuthManager
    mock_config_manager = MagicMock(spec=ConfigManager)
    mock_config_manager.get_api_key.return_value = ""  # Simulate no API key
    mock_config_manager.get_logging_config.return_value = {
        "level": "ERROR"
    }  # Minimal logging
    mock_config_manager.get_apis.return_value = {
        "mock_api": {"name": "Mock API"}
    }  # Minimal API config
    mock_config_manager.get_dashboard_enabled.return_value = (
        False  # Disable dashboard for simplicity
    )
    mock_config_manager.get_host.return_value = "127.0.0.1"
    mock_config_manager.get_port.return_value = 8080
    # Add mocks for other config calls if NyaProxyApp init requires them

    # Patch the ConfigManager instance within the NyaProxyApp scope during init
    # and the AuthManager's use of it.
    # This is tricky because the app and auth_manager are created early.
    # A cleaner way might involve a factory fixture for NyaProxyApp.
    # For now, let's try patching where it's used.

    with patch(
        "nya_proxy.server.app.ConfigManager", return_value=mock_config_manager
    ), patch(
        "nya_proxy.server.auth.AuthManager.get_api_key", return_value=""
    ):  # Patch AuthManager directly

        # We need to re-instantiate NyaProxyApp to use the mocked config
        # This assumes nya_proxy_app = NyaProxyApp() happens at module level in app.py
        # If app creation is complex, this fixture needs refinement.
        # A better approach might be a fixture that *builds* the app with mocks.

        # Let's try creating a new instance for the test client
        nya_app_instance = NyaProxyApp()
        client = TestClient(nya_app_instance.app)
        yield client
        # Cleanup if needed


# --- Test Cases ---


def test_root_endpoint(test_app_no_auth):
    """Test the root '/' endpoint."""
    response = test_app_no_auth.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to NyaProxy!"}


def test_info_endpoint_no_auth(test_app_no_auth):
    """Test the '/info' endpoint when no API key is required."""
    response = test_app_no_auth.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "version" in data
    assert "apis" in data
    # Check based on the mocked config
    assert "mock_api" in data["apis"]
    assert data["apis"]["mock_api"]["name"] == "Mock API"


def test_docs_accessible_no_auth(test_app_no_auth):
    """Test that OpenAPI docs are accessible without auth."""
    response = test_app_no_auth.get("/docs")
    # TestClient might not render the HTML fully, but 200 OK means accessible
    assert response.status_code == 200

    response = test_app_no_auth.get("/redoc")
    assert response.status_code == 200

    response = test_app_no_auth.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()


def test_proxy_route_accessible_no_auth(test_app_no_auth):
    """
    Test a generic proxy route when no auth is configured.
    We expect a 503 here because the core services aren't fully initialized
    in this simplified test setup, but the route should be reachable past auth.
    Alternatively, mock the core handler. For now, let's check it's not 401/403.
    """
    # Mock the core handler to avoid 503 if possible, or check for non-auth error
    with patch.object(
        NyaProxyApp, "generic_proxy_request", new_callable=AsyncMock
    ) as mock_handler:
        mock_handler.return_value = JSONResponse(
            content={"mock": "response"}, status_code=200
        )

        # Recreate client with patched handler if necessary, or assume patch works on existing instance
        # This highlights complexity - maybe app fixture should handle patching?
        # Let's assume the patch applies to the instance used by test_app_no_auth

        response = test_app_no_auth.get("/api/some/path")
        # Status code depends on whether core is mocked or not.
        # If mocked (as above):
        # assert response.status_code == 200
        # assert response.json() == {"mock": "response"}
        # If not mocked, we expect 503, but crucially NOT 401 or 403
        assert response.status_code != 401
        assert response.status_code != 403
        # assert response.status_code == 503 # If core isn't mocked/running


@pytest.fixture(scope="module")
def test_app_with_auth():
    """
    Provides a TestClient instance for NyaProxyApp where an API key is configured.
    """
    TEST_API_KEY = "test-secret-key"

    # Mock ConfigManager methods
    mock_config_manager = MagicMock(spec=ConfigManager)
    mock_config_manager.get_api_key.return_value = TEST_API_KEY
    mock_config_manager.get_logging_config.return_value = {"level": "ERROR"}
    mock_config_manager.get_apis.return_value = {"mock_api": {"name": "Mock API"}}
    mock_config_manager.get_dashboard_enabled.return_value = True  # Enable dashboard
    mock_config_manager.get_host.return_value = "127.0.0.1"
    mock_config_manager.get_port.return_value = 8080
    # Mock config server attributes needed for mounting
    mock_config_manager.server = MagicMock()
    mock_config_manager.server.app = MagicMock()
    mock_config_manager.server.app.add_middleware = (
        MagicMock()
    )  # Mock add_middleware on the sub-app

    # Patch ConfigManager and AuthManager's get_api_key
    with patch(
        "nya_proxy.server.app.ConfigManager", return_value=mock_config_manager
    ), patch(
        "nya_proxy.server.auth.AuthManager.get_api_key", return_value=TEST_API_KEY
    ), patch(
        "nya_proxy.dashboard.api.DashboardAPI"
    ) as MockDashboardAPI, patch(
        "builtins.open", MagicMock()
    ):  # Mock open for login.html

        # Mock the dashboard instance and its app
        mock_dashboard_instance = MockDashboardAPI.return_value
        mock_dashboard_instance.app = MagicMock()
        mock_dashboard_instance.app.add_middleware = (
            MagicMock()
        )  # Mock add_middleware on the sub-app

        nya_app_instance = NyaProxyApp()
        # Manually set dependencies that might be missed due to mocking
        # If dashboard init relies on core, we might need more mocks here
        if nya_app_instance.dashboard:
            nya_app_instance.dashboard.set_config_manager(mock_config_manager)
            # Mock core components if needed for dashboard setup
            mock_core = MagicMock()
            mock_core.metrics_collector = MagicMock()
            mock_core.request_queue = MagicMock()
            nya_app_instance.core = mock_core  # Assign mock core if needed
            nya_app_instance.dashboard.set_metrics_collector(
                mock_core.metrics_collector
            )
            nya_app_instance.dashboard.set_request_queue(mock_core.request_queue)

        client = TestClient(nya_app_instance.app)
        client.auth_key = TEST_API_KEY  # Store key for convenience
        yield client
        # Cleanup


# --- Auth Required Tests ---


def test_info_endpoint_with_auth_missing_key(test_app_with_auth):
    """Test /info requires auth when key is configured."""
    response = test_app_with_auth.get("/info")
    # Should be forbidden as no key provided
    assert response.status_code == 403  # Or 401 depending on exact middleware logic
    assert "Unauthorized" in response.json().get(
        "detail", ""
    ) or "Invalid API key" in response.json().get("error", "")


def test_info_endpoint_with_auth_wrong_key(test_app_with_auth):
    """Test /info fails with wrong auth key."""
    response = test_app_with_auth.get(
        "/info", headers={"Authorization": "Bearer wrong-key"}
    )
    assert response.status_code == 403
    assert "Insufficient Permissions" in response.json().get(
        "detail", ""
    ) or "Invalid API key" in response.json().get("error", "")


def test_info_endpoint_with_auth_correct_key(test_app_with_auth):
    """Test /info succeeds with correct auth key."""
    response = test_app_with_auth.get(
        "/info", headers={"Authorization": f"Bearer {test_app_with_auth.auth_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "mock_api" in data["apis"]


def test_proxy_route_with_auth_missing_key(test_app_with_auth):
    """Test proxy route requires auth."""
    response = test_app_with_auth.get("/api/some/path")
    assert response.status_code == 403  # Or 401
    assert "Unauthorized" in response.json().get(
        "detail", ""
    ) or "Invalid API key" in response.json().get("error", "")


def test_proxy_route_with_auth_wrong_key(test_app_with_auth):
    """Test proxy route fails with wrong key."""
    response = test_app_with_auth.get(
        "/api/some/path", headers={"Authorization": "Bearer wrong-key"}
    )
    assert response.status_code == 403
    assert "Insufficient Permissions" in response.json().get(
        "detail", ""
    ) or "Invalid API key" in response.json().get("error", "")


def test_proxy_route_with_auth_correct_key(test_app_with_auth):
    """Test proxy route succeeds with correct key (core logic might still fail)."""
    response = test_app_with_auth.get(
        "/api/some/path",
        headers={"Authorization": f"Bearer {test_app_with_auth.auth_key}"},
    )
    # Expect non-auth error (e.g., 503) or mocked success
    assert response.status_code != 401
    assert response.status_code != 403
    # assert response.status_code == 503 # Or 200 if core is mocked


def test_docs_accessible_with_auth(test_app_with_auth):
    """Test that OpenAPI docs are still accessible even when auth is configured."""
    response = test_app_with_auth.get("/docs")
    assert response.status_code == 200

    response = test_app_with_auth.get("/redoc")
    assert response.status_code == 200

    response = test_app_with_auth.get("/openapi.json")
    assert response.status_code == 200


def test_dashboard_redirects_to_login_with_auth(test_app_with_auth):
    """Test /dashboard redirects to login page when auth is required and no cookie/key."""
    # TestClient doesn't handle redirects automatically by default
    response = test_app_with_auth.get("/dashboard")
    # Expect a 401 response containing the login HTML
    assert response.status_code == 401
    assert "Enter your API key to access the service" in response.text


def test_config_redirects_to_login_with_auth(test_app_with_auth):
    """Test /config redirects to login page when auth is required."""
    response = test_app_with_auth.get("/config")
    assert response.status_code == 401
    assert "Enter your API key to access the service" in response.text
