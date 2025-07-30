from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from models import ContainerConfig
from docker_service import launch_container, get_container_status, list_containers, start_container, stop_container, get_container_ports, launch_template_container
import httpx
from utils import get_local_ip
from dotenv import load_dotenv
import os
import asyncio
from terminal_server import start_terminal_server
from typing import Optional

load_dotenv()

app = FastAPI()

# Global variable to track the terminal server task
terminal_server_task = None

# Authentication dependency
async def verify_orchestrator_token(authorization: Optional[str] = Header(None)):
    """Verify that the request comes from the orchestrator"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    expected_token = os.getenv('ORCHESTRATOR_TOKEN', 'default-secret-token')
    if authorization != f"Bearer {expected_token}":
        raise HTTPException(status_code=403, detail="Invalid orchestrator token")
    
    return True

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body}
    )

@app.post("/launch")
def launch(config: ContainerConfig, _: bool = Depends(verify_orchestrator_token)):
    print("Received config:", config)
    return launch_container(config)

@app.post("/launchBucket")
def launch_bucket( _: bool = Depends(verify_orchestrator_token)):
    """Launch a new bucket service container"""
    return launch_template_container("")

@app.get("/containers/{container_id}/status")
def get_status(container_id: str, _: bool = Depends(verify_orchestrator_token)):
    return get_container_status(container_id)

@app.get("/containers/{container_id}/ports")
def get_ports(container_id: str, _: bool = Depends(verify_orchestrator_token)):
    return get_container_ports(container_id)

@app.get("/containers")
def list_all_containers(all: bool = False, _: bool = Depends(verify_orchestrator_token)):
    return list_containers(all_containers=all)

@app.post("/containers/{container_id}/start")
def start_existing_container(container_id: str, _: bool = Depends(verify_orchestrator_token)):
    return start_container(container_id)

@app.post("/containers/{container_id}/stop")
def stop_existing_container(container_id: str, _: bool = Depends(verify_orchestrator_token)):
    return stop_container(container_id)

@app.on_event("startup")
async def startup_tasks():
    global terminal_server_task
    
    node_ip = get_local_ip()
    node_base_url = f"http://{node_ip}:{os.getenv('PORT')}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{os.getenv('ORCHESTRATOR_URL')}/register_node/{os.getenv('NODE_ID')}", params={"url": node_base_url})
            print("Registered with orchestrator:", resp.json())
        except Exception as e:
            print("Failed to register with orchestrator:", e)
    
    # Start the terminal server task
    terminal_server_task = asyncio.create_task(start_terminal_server())

@app.on_event("shutdown")
async def shutdown_tasks():
    global terminal_server_task
    
    if terminal_server_task and not terminal_server_task.done():
        print("Shutting down terminal WebSocket server...")
        terminal_server_task.cancel()
        try:
            await terminal_server_task
        except asyncio.CancelledError:
            print("Terminal server shutdown complete.")

@app.get("/health", status_code=200)
def health_check(_: bool = Depends(verify_orchestrator_token)):
    return {"status": "ok"}