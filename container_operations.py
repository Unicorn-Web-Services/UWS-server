"""
Container Operations Module

Basic Docker container operations: launch, start, stop, status, list, etc.
Low-level container management functions.
"""

import socket
import docker
from docker.errors import DockerException
from models import ContainerConfig
from utils import get_local_ip, logger
from service_registry import registry, DOCKER_AVAILABLE

if DOCKER_AVAILABLE:
    client = docker.from_env()
else:
    client = None


def launch_container(config: ContainerConfig):
    """Launch a new container with the given configuration"""
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available on this system"}

    try:
        # Get host IP for external access
        host_ip = get_local_ip()

        # For interactive containers (like ubuntu), we need to keep them running
        # by adding a command that doesn't exit
        run_kwargs = {
            "image": config.image,
            "name": config.name,
            "detach": True,
            "mem_limit": config.memory,
            "nano_cpus": int(config.cpu * 1e9),  # e.g., 0.2 CPUs
            "environment": config.env,
        }

        # Handle port mapping with automatic assignment
        exposed_ports = {}
        port_mappings = {}

        if config.ports:
            for container_port, host_port in config.ports.items():
                if host_port == 0:  # Auto-assign port
                    host_port = get_free_port()
                exposed_ports[container_port] = host_port
                port_mappings[container_port] = host_port

        run_kwargs["ports"] = port_mappings

        # Check if this is likely a base OS image that needs a keep-alive command
        base_images = ["ubuntu", "debian", "alpine", "centos", "fedora", "busybox"]
        if any(base in config.image.lower() for base in base_images):
            # Add a command to keep the container running
            run_kwargs["command"] = ["tail", "-f", "/dev/null"]
            logger.info("Added keep-alive command for base image", image=config.image)

        container = client.containers.run(**run_kwargs)

        # Generate access URLs for exposed ports
        access_urls = {}
        for container_port, host_port in exposed_ports.items():
            port_num = container_port.split("/")[0]  # Remove /tcp or /udp
            access_urls[f"port_{port_num}"] = f"http://{host_ip}:{host_port}"

        return {
            "id": container.id,
            "status": container.status,
            "name": container.name,
            "ports": exposed_ports,
            "access_urls": access_urls,
            "host_ip": host_ip,
        }
    except DockerException as e:
        return {"error": str(e)}


def get_container_ports(container_id: str):
    """Get port mappings and access URLs for a container"""
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available on this system"}

    try:
        container = client.containers.get(container_id)
        container.reload()

        host_ip = get_local_ip()
        ports = container.ports
        access_urls = {}

        for container_port, host_bindings in ports.items():
            if host_bindings:
                for binding in host_bindings:
                    host_port = binding["HostPort"]
                    port_num = container_port.split("/")[0]
                    access_urls[f"port_{port_num}"] = f"http://{host_ip}:{host_port}"

        return {
            "container_id": container.id,
            "name": container.name,
            "ports": ports,
            "access_urls": access_urls,
            "host_ip": host_ip,
        }
    except docker.errors.NotFound:
        return {"error": "Container not found"}
    except DockerException as e:
        return {"error": str(e)}


def get_container_status(container_id: str):
    """Check if a container is running and return its status"""
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available on this system"}

    try:
        container = client.containers.get(container_id)
        container.reload()  # Refresh container info
        return {
            "id": container.id,
            "name": container.name,
            "status": container.status,
            "state": container.attrs["State"]["Status"],
            "running": container.status == "running",
        }
    except docker.errors.NotFound:
        return {"error": "Container not found"}
    except DockerException as e:
        return {"error": str(e)}


def list_containers(all_containers: bool = False):
    """List all containers or just running ones"""
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available on this system"}

    try:
        containers = client.containers.list(all=all_containers)
        return [
            {
                "id": container.id,
                "name": container.name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else "unknown",
            }
            for container in containers
        ]
    except DockerException as e:
        return {"error": str(e)}


def start_container(container_id: str):
    """Start a stopped container"""
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available on this system"}

    try:
        container = client.containers.get(container_id)
        if container.status == "running":
            return {"message": f"Container {container.name} is already running"}

        container.start()
        container.reload()
        return {
            "message": f"Container {container.name} started successfully",
            "status": container.status,
        }
    except docker.errors.NotFound:
        return {"error": "Container not found"}
    except DockerException as e:
        return {"error": str(e)}


def stop_container(container_id: str):
    """Stop a running container"""
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available on this system"}

    try:
        container = client.containers.get(container_id)
        if container.status == "exited":
            return {"message": f"Container {container.name} is already stopped"}

        container.stop()
        container.reload()
        return {
            "message": f"Container {container.name} stopped successfully",
            "status": container.status,
        }
    except docker.errors.NotFound:
        return {"error": "Container not found"}
    except DockerException as e:
        return {"error": str(e)}


def get_free_port(start_port=8000):
    """Get a free port, avoiding ports already in use by registered services"""
    # Clean up dead services first
    registry.cleanup_dead_services()

    # Get ports in use by registered services
    used_ports = set(registry.get_used_ports())

    # Also check Docker containers directly
    if DOCKER_AVAILABLE:
        try:
            containers = client.containers.list()
            for container in containers:
                for port_info in container.ports.values():
                    if port_info:
                        for binding in port_info:
                            used_ports.add(int(binding["HostPort"]))
        except Exception as e:
            logger.warning("Could not check Docker container ports", error=str(e))

    # Find a free port starting from start_port
    port = start_port
    while port in used_ports or not _is_port_available(port):
        port += 1
        if port > 65535:  # Port range limit
            # Fall back to random port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                s.listen(1)
                return s.getsockname()[1]

    return port


def _is_port_available(port):
    """Check if a port is actually available"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", port))
            return True
    except OSError:
        return False
