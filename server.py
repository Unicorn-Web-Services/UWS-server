from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Header,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from terminal_server import start_terminal_server
from models import ContainerConfig
from docker_service import (
    launch_container,
    get_container_status,
    list_containers,
    start_container,
    stop_container,
    get_container_ports,
    launch_template_container,
    startup_container_recovery,
    get_available_templates,
    get_template_config,
)
import httpx
from utils import (
    get_local_ip,
    logger,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    ACTIVE_CONTAINERS,
    verify_orchestrator_token,
    log_request,
    log_container_operation,
    get_metrics,
    health_check,
    handle_exceptions,
    UWSException,
    ContainerException,
)
from dotenv import load_dotenv
import os
import asyncio
import time

# from terminal_server import start_terminal_server  # No longer needed
from typing import Optional
from prometheus_client import CONTENT_TYPE_LATEST

load_dotenv()

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="UWS Server",
    description="Unicorn Web Services Server API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Note: Rate limiting is not applied to WebSocket endpoints by default

# Security middleware
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["*"]  # Configure properly for production
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variable to track the terminal server task (no longer needed)
# terminal_server_task = None


# Authentication dependency
async def verify_orchestrator_token(authorization: Optional[str] = Header(None)):
    """Verify that the request comes from the orchestrator"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    expected_token = os.getenv("ORCHESTRATOR_TOKEN", "default-secret-token")
    if authorization != f"Bearer {expected_token}":
        raise HTTPException(status_code=403, detail="Invalid orchestrator token")

    return True


# Request/Response middleware for logging and metrics
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Skip WebSocket upgrade requests
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    start_time = time.time()

    # Process request
    response = await call_next(request)

    # Calculate response time
    response_time = time.time() - start_time

    # Log request
    log_request(request, response_time, response.status_code)

    # Update metrics
    REQUEST_COUNT.labels(
        method=request.method, endpoint=request.url.path, status=response.status_code
    ).inc()
    REQUEST_LATENCY.observe(response_time)

    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error", errors=exc.errors(), body=exc.body)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
            "body": exc.body,
        },
    )


@app.exception_handler(UWSException)
async def uws_exception_handler(request: Request, exc: UWSException):
    logger.error(
        "UWS exception",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "error_code": exc.error_code},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unexpected error", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
    )


@handle_exceptions
@app.post("/launch")
@limiter.limit("10/minute")
def launch(
    config: ContainerConfig,
    request: Request,
    _: bool = Depends(verify_orchestrator_token),
):
    """Launch a new container with enhanced logging and error handling"""
    logger.info("Launching container", config=config.dict())

    try:
        result = launch_container(config)
        log_container_operation("launch", config.name or "unknown", "success", result)
        ACTIVE_CONTAINERS.inc()
        return result
    except Exception as e:
        log_container_operation(
            "launch", config.name or "unknown", "failed", {"error": str(e)}
        )
        raise ContainerException(f"Failed to launch container: {str(e)}")


@handle_exceptions
@app.post("/launchBucket")
@limiter.limit("5/minute")
def launch_bucket(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Launch bucket service with enhanced logging"""
    logger.info("Launching bucket service")

    try:
        result = launch_template_container("buckets")
        log_container_operation("launch_bucket", "buckets", "success", result)
        return result
    except Exception as e:
        log_container_operation("launch_bucket", "buckets", "failed", {"error": str(e)})
        raise ContainerException(f"Failed to launch bucket service: {str(e)}")


@handle_exceptions
@app.post("/launchDB")
@limiter.limit("5/minute")
def launch_db(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Launch SQL database service with enhanced logging"""
    logger.info("Launching SQL database service")

    try:
        result = launch_template_container("db")
        log_container_operation("launch_db", "db", "success", result)
        return result
    except Exception as e:
        log_container_operation("launch_db", "db", "failed", {"error": str(e)})
        raise ContainerException(f"Failed to launch SQL database service: {str(e)}")


@handle_exceptions
@app.post("/launchNoSQL")
@limiter.limit("5/minute")
def launch_nosql(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Launch NoSQL database service with enhanced logging"""
    logger.info("Launching NoSQL database service")

    try:
        result = launch_template_container("nosql_db")
        log_container_operation("launch_nosql", "nosql_db", "success", result)
        return result
    except Exception as e:
        log_container_operation("launch_nosql", "nosql_db", "failed", {"error": str(e)})
        raise ContainerException(f"Failed to launch NoSQL database service: {str(e)}")


@handle_exceptions
@app.post("/launchQueue")
@limiter.limit("5/minute")
def launch_queue(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Launch queue service with enhanced logging"""
    logger.info("Launching queue service")

    try:
        result = launch_template_container("queue")
        log_container_operation("launch_queue", "queue", "success", result)
        return result
    except Exception as e:
        log_container_operation("launch_queue", "queue", "failed", {"error": str(e)})
        raise ContainerException(f"Failed to launch queue service: {str(e)}")


@handle_exceptions
@app.post("/launchSecrets")
@limiter.limit("5/minute")
def launch_secrets(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Launch secrets service with enhanced logging"""
    logger.info("Launching secrets service")

    try:
        result = launch_template_container("secrets")
        log_container_operation("launch_secrets", "secrets", "success", result)
        return result
    except Exception as e:
        log_container_operation(
            "launch_secrets", "secrets", "failed", {"error": str(e)}
        )
        raise ContainerException(f"Failed to launch secrets service: {str(e)}")


@handle_exceptions
@app.get("/templates")
def get_templates(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Get available template configurations"""
    logger.info("Getting available templates")

    try:
        templates = get_available_templates()
        template_configs = {}
        for template in templates:
            config = get_template_config(template)
            if "config" in config:
                template_configs[template] = config["config"]

        return {"templates": template_configs, "available": templates}
    except Exception as e:
        logger.error("Failed to get templates", error=str(e))
        raise ContainerException(f"Failed to get templates: {str(e)}")


@handle_exceptions
@app.get("/containers/{container_id}/status")
@limiter.limit("30/minute")
def get_status(
    container_id: str, request: Request, _: bool = Depends(verify_orchestrator_token)
):
    """Get container status with enhanced logging"""
    logger.info("Getting container status", container_id=container_id)

    try:
        result = get_container_status(container_id)
        log_container_operation("get_status", container_id, "success")
        return result
    except Exception as e:
        log_container_operation("get_status", container_id, "failed", {"error": str(e)})
        raise ContainerException(f"Failed to get container status: {str(e)}")


@handle_exceptions
@app.get("/containers/{container_id}/ports")
# @limiter.limit("30/minute")
# _: bool = Depends(verify_orchestrator_token)
def get_ports(
    container_id: str,
    request: Request,
):
    """Get container ports with enhanced logging"""
    logger.info("Getting container ports", container_id=container_id)

    try:
        result = get_container_ports(container_id)
        log_container_operation("get_ports", container_id, "success")
        return result
    except Exception as e:
        log_container_operation("get_ports", container_id, "failed", {"error": str(e)})
        raise ContainerException(f"Failed to get container ports: {str(e)}")


@handle_exceptions
@app.get("/containers/{container_id}/logs")
@limiter.limit("30/minute")
def get_container_logs(
    container_id: str, request: Request, _: bool = Depends(verify_orchestrator_token)
):
    """Get container logs with enhanced logging"""
    logger.info("Getting container logs", container_id=container_id)

    try:
        import subprocess

        result = subprocess.run(
            ["docker", "logs", "--tail", "50", container_id],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            logs = result.stdout
        else:
            logs = f"Error getting logs: {result.stderr}"

        log_container_operation("get_logs", container_id, "success")
        return {"logs": logs}
    except Exception as e:
        log_container_operation("get_logs", container_id, "failed", {"error": str(e)})
        raise ContainerException(f"Failed to get container logs: {str(e)}")


@handle_exceptions
@app.get("/containers")
@limiter.limit("20/minute")
def list_all_containers(
    request: Request, _: bool = Depends(verify_orchestrator_token), all: bool = False
):
    """List all containers with enhanced logging"""
    logger.info("Listing containers", all_containers=all)

    try:
        result = list_containers(all_containers=all)
        log_container_operation(
            "list_containers", "all", "success", {"count": len(result)}
        )
        return result
    except Exception as e:
        log_container_operation("list_containers", "all", "failed", {"error": str(e)})
        raise ContainerException(f"Failed to list containers: {str(e)}")


@handle_exceptions
@app.post("/containers/{container_id}/start")
@limiter.limit("10/minute")
def start_existing_container(
    container_id: str, request: Request, _: bool = Depends(verify_orchestrator_token)
):
    """Start an existing container with enhanced logging"""
    logger.info("Starting container", container_id=container_id)

    try:
        result = start_container(container_id)
        log_container_operation("start", container_id, "success")
        ACTIVE_CONTAINERS.inc()
        return result
    except Exception as e:
        log_container_operation("start", container_id, "failed", {"error": str(e)})
        raise ContainerException(f"Failed to start container: {str(e)}")


@handle_exceptions
@app.post("/containers/{container_id}/stop")
@limiter.limit("10/minute")
def stop_existing_container(
    container_id: str, request: Request, _: bool = Depends(verify_orchestrator_token)
):
    """Stop an existing container with enhanced logging"""
    logger.info("Stopping container", container_id=container_id)

    try:
        result = stop_container(container_id)
        log_container_operation("stop", container_id, "success")
        ACTIVE_CONTAINERS.dec()
        return result
    except Exception as e:
        log_container_operation("stop", container_id, "failed", {"error": str(e)})
        raise ContainerException(f"Failed to stop container: {str(e)}")


@handle_exceptions
@app.post("/containers/recover")
@limiter.limit("5/minute")
def recover_containers(request: Request, _: bool = Depends(verify_orchestrator_token)):
    """Manually trigger container recovery process"""
    logger.info("Manual container recovery triggered")

    try:
        result = startup_container_recovery()
        logger.info("Manual container recovery completed", result=result)
        return result
    except Exception as e:
        logger.error("Manual container recovery failed", error=str(e))
        raise ContainerException(f"Container recovery failed: {str(e)}")


@app.get("/health", status_code=200)
async def health_endpoint():
    """Enhanced health check endpoint"""
    return health_check()


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint"""
    return Response(content=get_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "UWS Server",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


@app.websocket("/ws/terminal/{container_id}")
async def terminal_websocket(websocket: WebSocket, container_id: str):
    """WebSocket endpoint for terminal connections"""

    # TODO: Re-enable authentication once WebSocket header passing is working
    # For now, accept all connections to test the terminal functionality
    await websocket.accept()
    logger.info("WebSocket connection accepted", container_id=container_id)

    try:
        # Import the terminal handler
        from terminal_ws import handle_terminal

        # Call the terminal handler with the WebSocket and path
        path = f"/ws/terminal/{container_id}"
        await handle_terminal(websocket, path)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", container_id=container_id)
    except Exception as e:
        logger.error("WebSocket error", error=str(e), container_id=container_id)
        try:
            await websocket.close()
        except:
            pass


@app.on_event("startup")
async def startup_tasks():
    logger.info("Starting UWS Server")

    # Recover registered Docker containers
    logger.info("Starting container recovery process")
    try:
        recovery_result = startup_container_recovery()
        logger.info("Container recovery completed", result=recovery_result)
    except Exception as e:
        logger.error("Container recovery failed", error=str(e))
        print(e)

    # Register with orchestrator
    node_ip = get_local_ip()
    node_base_url = f"http://{node_ip}:{os.getenv('PORT')}"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{os.getenv('ORCHESTRATOR_URL')}/register_node/{os.getenv('NODE_ID')}",
                params={"url": node_base_url},
            )
            logger.info("Registered with orchestrator", response=resp.json())
        except Exception as e:
            logger.error("Failed to register with orchestrator", error=str(e))

    logger.info("UWS Server started with WebSocket support")
    asyncio.create_task(
        start_terminal_server()  # Start the terminal server in the background
    )


@app.on_event("shutdown")
async def shutdown_tasks():
    logger.info("Shutting down UWS Server")
    logger.info("UWS Server shutdown complete")
