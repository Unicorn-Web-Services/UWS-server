"""
Service Manager Module

High-level service lifecycle management: start, stop, restart, remove services.
Manages services registered in the service registry.
"""

import docker
from docker.errors import DockerException
from service_registry import registry, DOCKER_AVAILABLE
from container_operations import stop_container
from utils import logger

if DOCKER_AVAILABLE:
    client = docker.from_env()
else:
    client = None


def list_running_services(template: str = None):
    """List all running services, optionally filtered by template

    Args:
        template (str, optional): Filter by template name

    Returns:
        dict: Dictionary of running services
    """
    registry.cleanup_dead_services()
    return registry.list_services(template)


def stop_service(service_id: str):
    """Stop a service by service ID

    Args:
        service_id (str): Service ID from the registry

    Returns:
        dict: Result of the stop operation
    """
    service = registry.get_service(service_id)
    if not service:
        return {"error": f"Service '{service_id}' not found in registry"}

    container_id = service.get("container_id")
    if not container_id:
        container_name = service.get("container_name")
        if container_name and DOCKER_AVAILABLE:
            try:
                container = client.containers.get(container_name)
                container_id = container.id
            except docker.errors.NotFound:
                registry.unregister_service(service_id)
                return {"error": f"Container for service '{service_id}' not found"}

    if container_id:
        result = stop_container(container_id)
        if "error" not in result:
            # Update service status but keep in registry for potential restart
            registry.update_service(service_id, status="stopped")
        return result

    return {"error": f"No container information available for service '{service_id}'"}


def remove_service(service_id: str, remove_container: bool = True):
    """Completely remove a service and optionally its container

    Args:
        service_id (str): Service ID from the registry
        remove_container (bool): Whether to remove the Docker container

    Returns:
        dict: Result of the removal operation
    """
    service = registry.get_service(service_id)
    if not service:
        return {"error": f"Service '{service_id}' not found in registry"}

    results = {"service_removed": False, "container_removed": False}

    if remove_container:
        container_id = service.get("container_id")
        container_name = service.get("container_name")

        if container_id or container_name:
            try:
                if DOCKER_AVAILABLE:
                    if container_id:
                        container = client.containers.get(container_id)
                    else:
                        container = client.containers.get(container_name)

                    # Stop if running
                    if container.status == "running":
                        container.stop()

                    # Remove container
                    container.remove()
                    results["container_removed"] = True
                    results["message"] = (
                        f"Container for service '{service_id}' removed successfully"
                    )

            except docker.errors.NotFound:
                results["message"] = (
                    f"Container for service '{service_id}' was already removed"
                )
                results["container_removed"] = True
            except Exception as e:
                results["container_error"] = str(e)

    # Remove from registry
    registry.unregister_service(service_id)
    results["service_removed"] = True

    if not results.get("message"):
        results["message"] = f"Service '{service_id}' removed from registry"

    return results


def restart_service(service_id: str):
    """Restart a service by service ID

    Args:
        service_id (str): Service ID from the registry

    Returns:
        dict: Result of the restart operation
    """
    service = registry.get_service(service_id)
    if not service:
        return {"error": f"Service '{service_id}' not found in registry"}

    container_id = service.get("container_id")
    container_name = service.get("container_name")

    if not container_id and container_name and DOCKER_AVAILABLE:
        try:
            container = client.containers.get(container_name)
            container_id = container.id
        except docker.errors.NotFound:
            return {"error": f"Container for service '{service_id}' not found"}

    if container_id:
        # Try to restart the container
        try:
            if DOCKER_AVAILABLE:
                container = client.containers.get(container_id)
                container.restart()
                container.reload()

                # Update service status
                registry.update_service(service_id, status=container.status)

                return {
                    "message": f"Service '{service_id}' restarted successfully",
                    "status": container.status,
                    "service_id": service_id,
                }
        except Exception as e:
            return {"error": f"Failed to restart service '{service_id}': {str(e)}"}

    return {"error": f"No container information available for service '{service_id}'"}


def get_service_info(service_id: str):
    """Get detailed information about a service

    Args:
        service_id (str): Service ID from the registry

    Returns:
        dict: Service information including live container status
    """
    registry.cleanup_dead_services()
    service = registry.get_service(service_id)
    if not service:
        return {"error": f"Service '{service_id}' not found in registry"}

    # Get live container information if available
    container_id = service.get("container_id")
    container_name = service.get("container_name")

    # Always work with a copy to avoid modifying the original
    service = service.copy()

    if DOCKER_AVAILABLE and (container_id or container_name):
        try:
            if container_id:
                container = client.containers.get(container_id)
            else:
                container = client.containers.get(container_name)

            # Update service with live information
            service["live_status"] = container.status
            service["container_id"] = container.id

            # Get port information
            ports = container.ports
            if ports:
                service["port_mappings"] = ports

        except docker.errors.NotFound:
            service["live_status"] = "container_not_found"
        except Exception as e:
            service["live_status"] = f"error: {str(e)}"

    return service


def get_all_services_status():
    """Get status of all registered services

    Returns:
        dict: Complete status report of all services
    """
    registry.cleanup_dead_services()

    services = registry.list_services()
    stats = registry.get_service_stats()

    return {
        "statistics": stats,
        "services": {
            service_id: get_service_info(service_id) for service_id in services.keys()
        },
    }
