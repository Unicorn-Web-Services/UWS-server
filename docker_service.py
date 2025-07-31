"""
Docker Service Module - Main API Interface

This module provides a unified interface to all Docker container and service management
functionality. It imports from specialized modules and exposes a clean public API.

Refactored structure:
- service_registry.py: Service registry management
- container_operations.py: Basic Docker container operations
- template_manager.py: Template-based service deployment
- service_manager.py: Service lifecycle management
- container_recovery.py: Startup recovery and cleanup
"""

# Import from specialized modules
from service_registry import registry, DOCKER_AVAILABLE
from container_operations import (
    launch_container,
    get_container_ports,
    get_container_status,
    list_containers,
    start_container,
    stop_container,
    get_free_port,
)
from template_manager import (
    get_available_templates,
    get_template_config,
    launch_template_container,
)
from service_manager import (
    list_running_services,
    stop_service,
    remove_service,
    restart_service,
    get_service_info,
    get_all_services_status,
)
from container_recovery import (
    startup_container_recovery,
    graceful_shutdown,
    cleanup_orphaned_containers,
    auto_cleanup_services,
    force_cleanup_all_services,
    get_cleanup_status,
    setup_signal_handlers,
)


# Re-export commonly used items for backward compatibility
def get_service_stats():
    """Get statistics about running services"""
    return registry.get_service_stats()


# Compatibility aliases for the old _get_free_port function
def _get_free_port(start_port=8000):
    """Compatibility wrapper for get_free_port"""
    return get_free_port(start_port)


# Initialize signal handlers when module is imported
if DOCKER_AVAILABLE:
    setup_signal_handlers()

# Public API exports - these are the functions that should be imported by other modules
__all__ = [
    # Registry access
    "registry",
    "DOCKER_AVAILABLE",
    # Container operations
    "launch_container",
    "get_container_ports",
    "get_container_status",
    "list_containers",
    "start_container",
    "stop_container",
    "get_free_port",
    # Template management
    "get_available_templates",
    "get_template_config",
    "launch_template_container",
    # Service management
    "list_running_services",
    "stop_service",
    "remove_service",
    "restart_service",
    "get_service_info",
    "get_all_services_status",
    "get_service_stats",
    # Recovery and cleanup
    "startup_container_recovery",
    "graceful_shutdown",
    "cleanup_orphaned_containers",
    "auto_cleanup_services",
    "force_cleanup_all_services",
    "get_cleanup_status",
    # Compatibility
    "_get_free_port",
]
