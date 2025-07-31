import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
import json
from server import app
from utils import UWSException, ContainerException

client = TestClient(app)

class TestServerEndpoints:
    """Test cases for server endpoints"""
    
    def setup_method(self):
        """Setup method for each test"""
        self.auth_headers = {"Authorization": "Bearer default-secret-token"}
    
    def test_root_endpoint(self):
        """Test the root endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "UWS Server"
        assert data["version"] == "1.0.0"
        assert data["status"] == "running"
    
    def test_health_endpoint(self):
        """Test the health endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
    
    def test_metrics_endpoint(self):
        """Test the metrics endpoint"""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
    
    def test_launch_container_success(self):
        """Test successful container launch"""
        config = {
            "image": "nginx:latest",
            "name": "test-container",
            "env": {"TEST": "value"},
            "cpu": 0.5,
            "memory": "512m",
            "ports": {"80/tcp": 8080}
        }
        
        with patch('server.launch_container') as mock_launch:
            mock_launch.return_value = {"container_id": "test-123", "status": "running"}
            
            response = client.post("/launch", json=config, headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["container_id"] == "test-123"
            mock_launch.assert_called_once()
    
    def test_launch_container_failure(self):
        """Test container launch failure"""
        config = {
            "image": "invalid-image",
            "name": "test-container",
            "env": {},
            "cpu": 0.5,
            "memory": "512m",
            "ports": {}
        }
        
        with patch('server.launch_container') as mock_launch:
            mock_launch.side_effect = Exception("Docker error")
            
            response = client.post("/launch", json=config, headers=self.auth_headers)
            assert response.status_code == 500
            data = response.json()
            assert "Failed to launch container" in data["detail"]
    
    def test_launch_bucket_success(self):
        """Test successful bucket service launch"""
        with patch('server.launch_template_container') as mock_launch:
            mock_launch.return_value = {"container_id": "bucket-123", "status": "running"}
            
            response = client.post("/launchBucket", headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["container_id"] == "bucket-123"
            mock_launch.assert_called_once()
    
    def test_get_container_status(self):
        """Test getting container status"""
        with patch('server.get_container_status') as mock_status:
            mock_status.return_value = {"status": "running", "uptime": "1h"}
            
            response = client.get("/containers/test-123/status", headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "running"
            mock_status.assert_called_once_with("test-123")
    
    def test_get_container_ports(self):
        """Test getting container ports"""
        with patch('server.get_container_ports') as mock_ports:
            mock_ports.return_value = {"80/tcp": 8080, "443/tcp": 8443}
            
            response = client.get("/containers/test-123/ports", headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["80/tcp"] == 8080
            mock_ports.assert_called_once_with("test-123")
    
    def test_list_containers(self):
        """Test listing containers"""
        with patch('server.list_containers') as mock_list:
            mock_list.return_value = [
                {"id": "container-1", "name": "test1", "status": "running"},
                {"id": "container-2", "name": "test2", "status": "stopped"}
            ]
            
            response = client.get("/containers", headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            mock_list.assert_called_once_with(all_containers=False)
    
    def test_start_container(self):
        """Test starting a container"""
        with patch('server.start_container') as mock_start:
            mock_start.return_value = {"status": "started"}
            
            response = client.post("/containers/test-123/start", headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            mock_start.assert_called_once_with("test-123")
    
    def test_stop_container(self):
        """Test stopping a container"""
        with patch('server.stop_container') as mock_stop:
            mock_stop.return_value = {"status": "stopped"}
            
            response = client.post("/containers/test-123/stop", headers=self.auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "stopped"
            mock_stop.assert_called_once_with("test-123")

class TestAuthentication:
    """Test cases for authentication"""
    
    def test_missing_auth_header(self):
        """Test missing authorization header"""
        response = client.post("/launch", json={})
        assert response.status_code == 401
        assert "Authorization header required" in response.json()["detail"]
    
    def test_invalid_auth_token(self):
        """Test invalid authorization token"""
        headers = {"Authorization": "Bearer invalid-token"}
        response = client.post("/launch", json={}, headers=headers)
        assert response.status_code == 403
        assert "Invalid orchestrator token" in response.json()["detail"]
    
    def test_valid_auth_token(self):
        """Test valid authorization token"""
        headers = {"Authorization": "Bearer default-secret-token"}
        with patch('server.launch_container') as mock_launch:
            mock_launch.return_value = {"container_id": "test-123"}
            
            response = client.post("/launch", json={
                "image": "nginx:latest",
                "name": "test",
                "env": {},
                "cpu": 0.5,
                "memory": "512m",
                "ports": {}
            }, headers=headers)
            assert response.status_code == 200

class TestRateLimiting:
    """Test cases for rate limiting"""
    
    def test_rate_limiting(self):
        """Test rate limiting functionality"""
        # Make multiple requests to trigger rate limiting
        for i in range(15):  # Exceed the 10/minute limit
            response = client.post("/launch", json={
                "image": "nginx:latest",
                "name": f"test-{i}",
                "env": {},
                "cpu": 0.5,
                "memory": "512m",
                "ports": {}
            }, headers={"Authorization": "Bearer default-secret-token"})
            
            if i >= 10:
                assert response.status_code == 429
                break

class TestErrorHandling:
    """Test cases for error handling"""
    
    def test_validation_error(self):
        """Test validation error handling"""
        # Send invalid config (missing required fields)
        response = client.post("/launch", json={
            "image": "nginx:latest"
            # Missing required fields
        }, headers={"Authorization": "Bearer default-secret-token"})
        
        assert response.status_code == 422
        data = response.json()
        assert "Validation error" in data["detail"]
    
    def test_container_exception(self):
        """Test container exception handling"""
        with patch('server.launch_container') as mock_launch:
            mock_launch.side_effect = ContainerException("Container launch failed")
            
            response = client.post("/launch", json={
                "image": "nginx:latest",
                "name": "test",
                "env": {},
                "cpu": 0.5,
                "memory": "512m",
                "ports": {}
            }, headers={"Authorization": "Bearer default-secret-token"})
            
            assert response.status_code == 500
            data = response.json()
            assert "Container launch failed" in data["detail"]
    
    def test_general_exception(self):
        """Test general exception handling"""
        with patch('server.launch_container') as mock_launch:
            mock_launch.side_effect = Exception("Unexpected error")
            
            response = client.post("/launch", json={
                "image": "nginx:latest",
                "name": "test",
                "env": {},
                "cpu": 0.5,
                "memory": "512m",
                "ports": {}
            }, headers={"Authorization": "Bearer default-secret-token"})
            
            assert response.status_code == 500
            data = response.json()
            assert "Internal server error" in data["detail"]

class TestCORS:
    """Test cases for CORS"""
    
    def test_cors_headers(self):
        """Test CORS headers are present"""
        response = client.options("/launch", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type"
        })
        
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert "access-control-allow-methods" in response.headers

if __name__ == "__main__":
    pytest.main([__file__]) 