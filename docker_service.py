import docker
from docker.errors import DockerException
from models import ContainerConfig
import random
from utils import get_local_ip

try:
    client = docker.from_env()
    DOCKER_AVAILABLE = True
except DockerException as e:
    print(f"Warning: Docker is not available - {e}")
    client = None
    DOCKER_AVAILABLE = False

def launch_container(config: ContainerConfig):
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
            "environment": config.env
        }
        
        # Handle port mapping with automatic assignment
        exposed_ports = {}
        port_mappings = {}
        
        if config.ports:
            for container_port, host_port in config.ports.items():
                if host_port == 0:  # Auto-assign port
                    host_port = _get_free_port()
                exposed_ports[container_port] = host_port
                port_mappings[container_port] = host_port
        
        run_kwargs["ports"] = port_mappings
        
        # Check if this is likely a base OS image that needs a keep-alive command
        base_images = ['ubuntu', 'debian', 'alpine', 'centos', 'fedora', 'busybox']
        if any(base in config.image.lower() for base in base_images):
            # Add a command to keep the container running
            run_kwargs["command"] = ["tail", "-f", "/dev/null"]
            print(f"Added keep-alive command for base image: {config.image}")
        
        container = client.containers.run(**run_kwargs)
        
        # Generate access URLs for exposed ports
        access_urls = {}
        for container_port, host_port in exposed_ports.items():
            port_num = container_port.split('/')[0]  # Remove /tcp or /udp
            access_urls[f"port_{port_num}"] = f"http://{host_ip}:{host_port}"
        
        return {
            "id": container.id,
            "status": container.status,
            "name": container.name,
            "ports": exposed_ports,
            "access_urls": access_urls,
            "host_ip": host_ip
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
                    host_port = binding['HostPort']
                    port_num = container_port.split('/')[0]
                    access_urls[f"port_{port_num}"] = f"http://{host_ip}:{host_port}"
        
        return {
            "container_id": container.id,
            "name": container.name,
            "ports": ports,
            "access_urls": access_urls,
            "host_ip": host_ip
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
            "state": container.attrs['State']['Status'],
            "running": container.status == 'running'
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
                "image": container.image.tags[0] if container.image.tags else "unknown"
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
        if container.status == 'running':
            return {"message": f"Container {container.name} is already running"}
        
        container.start()
        container.reload()
        return {
            "message": f"Container {container.name} started successfully",
            "status": container.status
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
        if container.status == 'exited':
            return {"message": f"Container {container.name} is already stopped"}
        
        container.stop()
        container.reload()
        return {
            "message": f"Container {container.name} stopped successfully",
            "status": container.status
        }
    except docker.errors.NotFound:
        return {"error": "Container not found"}
    except DockerException as e:
        return {"error": str(e)}


def _get_free_port():
    """Get a random free port"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port
