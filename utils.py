import os
import socket
import structlog
import time
from functools import wraps
from typing import Optional, Dict, Any
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi import HTTPException, Request, Header
import jwt
from datetime import datetime, timedelta
import hashlib
import secrets

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency")
ACTIVE_CONTAINERS = Gauge("active_containers", "Number of active containers")
CONTAINER_OPERATIONS = Counter(
    "container_operations_total", "Container operations", ["operation", "status"]
)

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def get_local_ip() -> str:
    """Get the local IP address of the machine"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """Verify and decode a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return hash_password(plain_password) == hashed_password


def verify_orchestrator_token(authorization: str = Header(None)) -> bool:
    """FastAPI dependency to verify orchestrator token from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    try:
        # Extract token from "Bearer <token>" format
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization

        # Verify the token using existing verify_token function
        payload = verify_token(token)

        # Check if token has orchestrator permissions
        if (
            payload.get("role") == "orchestrator"
            or payload.get("sub") == "orchestrator"
        ):
            return True
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


def rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """Rate limiting decorator"""

    def decorator(func):
        request_counts = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Simple in-memory rate limiting (use Redis in production)
            current_time = time.time()
            client_ip = "default"  # In production, get from request

            # Clean old entries
            request_counts = {
                k: v
                for k, v in request_counts.items()
                if current_time - v["timestamp"] < window_seconds
            }

            if client_ip in request_counts:
                if request_counts[client_ip]["count"] >= max_requests:
                    raise HTTPException(status_code=429, detail="Rate limit exceeded")
                request_counts[client_ip]["count"] += 1
            else:
                request_counts[client_ip] = {"count": 1, "timestamp": current_time}

            return func(*args, **kwargs)

        return wrapper

    return decorator


def log_request(request: Request, response_time: float, status_code: int):
    """Log request details with structured logging"""
    logger.info(
        "HTTP request",
        method=request.method,
        url=str(request.url),
        status_code=status_code,
        response_time=response_time,
        user_agent=request.headers.get("user-agent"),
        client_ip=request.client.host if request.client else None,
    )


def log_container_operation(
    operation: str, container_id: str, status: str, details: Dict[str, Any] = None
):
    """Log container operations with structured logging"""
    logger.info(
        "Container operation",
        operation=operation,
        container_id=container_id,
        status=status,
        details=details or {},
    )
    CONTAINER_OPERATIONS.labels(operation=operation, status=status).inc()


def get_metrics():
    """Get Prometheus metrics"""
    return generate_latest()


def health_check() -> Dict[str, Any]:
    """Comprehensive health check"""
    try:
        # Check disk space
        disk_usage = os.statvfs("/")
        free_space_gb = (disk_usage.f_frsize * disk_usage.f_bavail) / (1024**3)

        # Check memory usage
        with open("/proc/meminfo", "r") as f:
            meminfo = dict(
                line.split(":") for line in f.read().split("\n") if ":" in line
            )
            total_mem = int(meminfo["MemTotal"].split()[0])
            free_mem = int(meminfo["MemAvailable"].split()[0])
            memory_usage_percent = ((total_mem - free_mem) / total_mem) * 100

        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "docker": "healthy",  # Add actual Docker health check
                "database": "healthy",  # Add actual database health check
            },
            "system": {
                "free_disk_gb": round(free_space_gb, 2),
                "memory_usage_percent": round(memory_usage_percent, 2),
                "uptime_seconds": time.time() - os.path.getctime("/proc/1"),
            },
        }
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }


# Error handling utilities
class UWSException(Exception):
    """Base exception for UWS application"""

    def __init__(self, message: str, error_code: str = None, status_code: int = 500):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(self.message)


class ContainerException(UWSException):
    """Exception for container-related errors"""

    pass


class AuthenticationException(UWSException):
    """Exception for authentication errors"""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTH_ERROR", 401)


class AuthorizationException(UWSException):
    """Exception for authorization errors"""

    def __init__(self, message: str = "Access denied"):
        super().__init__(message, "FORBIDDEN", 403)


def handle_exceptions(func):
    """Decorator to handle exceptions and log them properly"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UWSException as e:
            logger.error(
                "UWS exception",
                error_code=e.error_code,
                message=e.message,
                status_code=e.status_code,
            )
            raise HTTPException(status_code=e.status_code, detail=e.message)
        except Exception as e:
            logger.error("Unexpected error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    return wrapper
