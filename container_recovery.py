"""
Container Recovery Module

Handles startup recovery, cleanup operations, and graceful shutdown.
Manages container lifecycle during server startup and shutdown.
"""

import signal
import sys
import atexit
import docker
from docker.errors import DockerException
from service_registry import registry, DOCKER_AVAILABLE
from utils import logger

if DOCKER_AVAILABLE:
    client = docker.from_env()
else:
    client = None


def startup_container_recovery():
    """Restart all registered services on server startup"""
    if not DOCKER_AVAILABLE:
        logger.warning("Docker not available, skipping container recovery")
        return {"error": "Docker is not available"}

    logger.info("Starting container recovery process")

    # Clean up dead services first
    registry.cleanup_dead_services()

    services = registry.list_services()
    if not services:
        logger.info("No registered services to recover")
        return {"message": "No services to recover", "recovered": 0, "failed": 0}

    recovered_count = 0
    failed_count = 0
    recovery_results = {}

    for service_id, service in services.items():
        logger.info("Attempting to recover service", service_id=service_id)

        container_id = service.get("container_id")
        container_name = service.get("container_name")

        if not container_id and not container_name:
            logger.warning(
                "No container information for service", service_id=service_id
            )
            failed_count += 1
            recovery_results[service_id] = {
                "status": "failed",
                "reason": "no_container_info",
            }
            continue

        try:
            # Try to get the container
            container = None
            if container_id:
                try:
                    container = client.containers.get(container_id)
                except docker.errors.NotFound:
                    logger.info(
                        "Container not found by ID, trying by name",
                        container_id=container_id,
                        container_name=container_name,
                    )

            if not container and container_name:
                try:
                    container = client.containers.get(container_name)
                    # Update the container_id in registry if we found it by name
                    registry.update_service(service_id, container_id=container.id)
                except docker.errors.NotFound:
                    logger.warning(
                        "Container not found",
                        service_id=service_id,
                        container_name=container_name,
                    )

            if not container:
                # Container doesn't exist, mark as failed and remove from registry
                logger.warning("Container no longer exists", service_id=service_id)
                registry.unregister_service(service_id)
                failed_count += 1
                recovery_results[service_id] = {
                    "status": "failed",
                    "reason": "container_not_found",
                }
                continue

            # Check container status and start if needed
            container.reload()
            current_status = container.status

            if current_status == "running":
                logger.info("Container already running", service_id=service_id)
                registry.update_service(service_id, status="running")
                recovered_count += 1
                recovery_results[service_id] = {"status": "already_running"}

            elif current_status in ["exited", "stopped"]:
                logger.info("Starting stopped container", service_id=service_id)
                container.start()
                container.reload()
                registry.update_service(service_id, status=container.status)
                recovered_count += 1
                recovery_results[service_id] = {
                    "status": "restarted",
                    "new_status": container.status,
                }

            else:
                logger.warning(
                    "Container in unexpected state",
                    service_id=service_id,
                    status=current_status,
                )
                registry.update_service(service_id, status=current_status)
                failed_count += 1
                recovery_results[service_id] = {
                    "status": "failed",
                    "reason": f"unexpected_state_{current_status}",
                }

        except Exception as e:
            logger.error(
                "Error recovering service", service_id=service_id, error=str(e)
            )
            failed_count += 1
            recovery_results[service_id] = {
                "status": "failed",
                "reason": f"error_{str(e)}",
            }

    logger.info(
        "Container recovery completed",
        total_services=len(services),
        recovered=recovered_count,
        failed=failed_count,
    )

    return {
        "message": "Container recovery completed",
        "total_services": len(services),
        "recovered": recovered_count,
        "failed": failed_count,
        "results": recovery_results,
    }


def graceful_shutdown(signum=None, frame=None):
    """Gracefully shutdown all managed services and containers"""
    # Prevent multiple calls
    if hasattr(graceful_shutdown, "_called"):
        return
    graceful_shutdown._called = True

    logger.info("Graceful shutdown initiated")

    if not DOCKER_AVAILABLE:
        logger.warning("Docker not available, skipping container cleanup")
        if signum is not None:  # Only exit if called from signal handler
            sys.exit(0)
        return

    try:
        # Get all registered services
        services = registry.list_services()

        if not services:
            logger.info("No registered services to clean up")
        else:
            logger.info(
                "Found registered services to clean up", service_count=len(services)
            )

            # Stop and remove all managed containers
            removed_count = 0
            error_count = 0

            for service_id, service in services.items():
                logger.info("Cleaning up service", service_id=service_id)

                try:
                    container_id = service.get("container_id")
                    container_name = service.get("container_name")

                    if container_id or container_name:
                        try:
                            if container_id:
                                container = client.containers.get(container_id)
                            else:
                                container = client.containers.get(container_name)

                            # Stop the container if running
                            if container.status == "running":
                                logger.info(
                                    "Stopping container", container_name=container.name
                                )
                                container.stop(timeout=10)

                            # Remove the container
                            logger.info(
                                "Removing container", container_name=container.name
                            )
                            container.remove(force=True)
                            removed_count += 1

                        except docker.errors.NotFound:
                            logger.info(
                                "Container already removed",
                                container_name=container_name or container_id,
                            )
                        except Exception as e:
                            logger.error("Error removing container", error=str(e))
                            error_count += 1

                    # Remove from registry
                    registry.unregister_service(service_id)

                except Exception as e:
                    logger.error(
                        "Error cleaning up service", service_id=service_id, error=str(e)
                    )
                    error_count += 1

            logger.info(
                "Cleanup completed",
                containers_removed=removed_count,
                errors=error_count,
            )

        # Also clean up any other containers that might be managed by autoNewservice
        cleanup_orphaned_containers()

    except Exception as e:
        logger.error("Error during graceful shutdown", error=str(e))

    logger.info("Server shutdown complete")
    if signum is not None:  # Only exit if called from signal handler
        sys.exit(0)


def cleanup_orphaned_containers():
    """Clean up any containers that might be managed by the system but not in registry"""
    if not DOCKER_AVAILABLE:
        return

    try:
        logger.info("Checking for orphaned containers")

        # Get all containers
        all_containers = client.containers.list(all=True)

        # Look for containers that match our naming patterns
        our_containers = []
        naming_patterns = [
            "_instance_",  # template_instance_N
            "_cont",  # old naming pattern
            "bucket_cont",
            "db_cont",
            "auth_service_cont",  # specific containers
            "file_manager_cont",
            "database_service_cont",
        ]

        for container in all_containers:
            container_name = container.name
            if any(pattern in container_name for pattern in naming_patterns):
                our_containers.append(container)

        if our_containers:
            logger.info(
                "Found potentially managed containers",
                container_count=len(our_containers),
            )

            for container in our_containers:
                try:
                    logger.info(
                        "Removing orphaned container", container_name=container.name
                    )
                    if container.status == "running":
                        container.stop(timeout=5)
                    container.remove(force=True)
                except Exception as e:
                    logger.error(
                        "Error removing orphaned container",
                        container_name=container.name,
                        error=str(e),
                    )
        else:
            logger.info("No orphaned containers found")

    except Exception as e:
        logger.error("Error during orphaned container cleanup", error=str(e))


def auto_cleanup_services():
    """Automatically clean up services and containers that are no longer running

    Returns:
        dict: Report of cleanup actions taken
    """
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available"}

    registry.cleanup_dead_services()

    report = {"services_cleaned": 0, "containers_removed": 0, "errors": []}

    # Get list of containers that are managed by our service registry
    managed_containers = set()
    for service in registry.services.values():
        container_name = service.get("container_name")
        if container_name:
            managed_containers.add(container_name)

    try:
        # List all containers (including stopped ones)
        all_containers = client.containers.list(all=True)

        for container in all_containers:
            # Check if this is one of our managed containers
            if container.name in managed_containers:
                if container.status in ["exited", "dead"]:
                    try:
                        container.remove()
                        report["containers_removed"] += 1
                        logger.info(
                            "Removed dead container", container_name=container.name
                        )
                    except Exception as e:
                        report["errors"].append(
                            f"Failed to remove container {container.name}: {str(e)}"
                        )

    except Exception as e:
        report["errors"].append(f"Failed to list containers: {str(e)}")

    return report


def force_cleanup_all_services():
    """Force cleanup of all services and containers (can be called manually)

    Returns:
        dict: Report of cleanup actions taken
    """
    logger.info("Force cleanup of all services initiated")

    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available"}

    from service_manager import remove_service

    report = {
        "services_cleaned": 0,
        "containers_removed": 0,
        "registry_cleared": False,
        "errors": [],
    }

    try:
        # Get all registered services
        services = registry.list_services()

        # Remove all services
        for service_id in list(services.keys()):
            try:
                result = remove_service(service_id, remove_container=True)
                if result.get("service_removed"):
                    report["services_cleaned"] += 1
                if result.get("container_removed"):
                    report["containers_removed"] += 1
                if result.get("container_error"):
                    report["errors"].append(
                        f"Service {service_id}: {result['container_error']}"
                    )
            except Exception as e:
                report["errors"].append(
                    f"Error removing service {service_id}: {str(e)}"
                )

        # Clear the entire registry
        registry.clear_all()
        report["registry_cleared"] = True

        # Also clean up orphaned containers
        cleanup_orphaned_containers()

        logger.info(
            "Force cleanup completed",
            services_cleaned=report["services_cleaned"],
            containers_removed=report["containers_removed"],
        )

    except Exception as e:
        error_msg = f"Error during force cleanup: {str(e)}"
        report["errors"].append(error_msg)
        logger.error("Force cleanup error", error=str(e))

    return report


def get_cleanup_status():
    """Get status of what would be cleaned up during shutdown

    Returns:
        dict: Information about services and containers that would be affected
    """
    if not DOCKER_AVAILABLE:
        return {"error": "Docker is not available"}

    status = {
        "registered_services": len(registry.services),
        "services": list(registry.services.keys()),
        "would_remove": [],
        "orphaned_containers": [],
    }

    # Check registered services
    for service_id, service in registry.services.items():
        container_name = service.get("container_name")
        container_id = service.get("container_id")

        container_exists = False
        container_status = "unknown"

        if DOCKER_AVAILABLE:
            try:
                if container_id:
                    container = client.containers.get(container_id)
                elif container_name:
                    container = client.containers.get(container_name)
                else:
                    container = None

                if container:
                    container_exists = True
                    container_status = container.status

            except docker.errors.NotFound:
                container_exists = False
                container_status = "not_found"
            except Exception as e:
                container_status = f"error: {str(e)}"

        status["would_remove"].append(
            {
                "service_id": service_id,
                "container_name": container_name,
                "container_exists": container_exists,
                "container_status": container_status,
            }
        )

    # Check for orphaned containers
    try:
        all_containers = client.containers.list(all=True)
        naming_patterns = [
            "_instance_",
            "_cont",
            "bucket_cont",
            "db_cont",
            "auth_service_cont",
            "file_manager_cont",
            "database_service_cont",
        ]

        for container in all_containers:
            if any(pattern in container.name for pattern in naming_patterns):
                # Check if this container is in our registry
                in_registry = any(
                    service.get("container_name") == container.name
                    or service.get("container_id") == container.id
                    for service in registry.services.values()
                )

                if not in_registry:
                    status["orphaned_containers"].append(
                        {
                            "name": container.name,
                            "id": container.id[:12],
                            "status": container.status,
                        }
                    )

    except Exception as e:
        status["orphaned_check_error"] = str(e)

    return status


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    # Handle Ctrl+C (SIGINT) and SIGTERM
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # Also register atexit handler as a backup (but don't exit from it)
    def atexit_cleanup():
        graceful_shutdown(signum=None, frame=None)

    atexit.register(atexit_cleanup)

    logger.info("Signal handlers registered for graceful shutdown")


# Setup signal handlers when module is imported
if DOCKER_AVAILABLE:
    setup_signal_handlers()
