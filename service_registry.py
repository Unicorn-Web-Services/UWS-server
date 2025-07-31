"""
Service Registry Module

Manages the registry of running services and their configurations.
Handles persistence of service state to JSON file.
"""

import json
import os
from datetime import datetime
from utils import logger
import docker
from docker.errors import DockerException

try:
    client = docker.from_env()
    DOCKER_AVAILABLE = True
except DockerException as e:
    logger.warning("Docker is not available", error=str(e))
    client = None
    DOCKER_AVAILABLE = False

# Service registry file path
SERVICE_REGISTRY_FILE = "service_registry.json"


class ServiceRegistry:
    """Manages the registry of running services and their configurations"""

    def __init__(self, registry_file=SERVICE_REGISTRY_FILE):
        self.registry_file = registry_file
        self.services = self._load_registry()

    def _load_registry(self):
        """Load service registry from file"""
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(
                    "Could not load service registry", registry_file=self.registry_file
                )
        return {}

    def _save_registry(self):
        """Save service registry to file"""
        try:
            with open(self.registry_file, "w") as f:
                json.dump(self.services, f, indent=2)
        except IOError as e:
            logger.warning("Could not save service registry", error=str(e))

    def register_service(
        self,
        service_id,
        template,
        container_name,
        port,
        instance_id=None,
        project_dir=None,
        container_id=None,
        created_at=None,
    ):
        """Register a new service"""
        self.services[service_id] = {
            "template": template,
            "container_name": container_name,
            "container_id": container_id,
            "port": port,
            "instance_id": instance_id,
            "project_dir": project_dir,
            "created_at": created_at or datetime.now().isoformat(),
            "status": "running",
        }
        self._save_registry()

    def unregister_service(self, service_id):
        """Remove a service from registry"""
        if service_id in self.services:
            del self.services[service_id]
            self._save_registry()

    def update_service(self, service_id, **kwargs):
        """Update specific fields of a service"""
        if service_id in self.services:
            self.services[service_id].update(kwargs)
            self._save_registry()
            return True
        return False

    def get_service(self, service_id):
        """Get service information"""
        return self.services.get(service_id)

    def list_services(self, template=None):
        """List all services, optionally filtered by template"""
        if template:
            return {
                k: v for k, v in self.services.items() if v.get("template") == template
            }
        return self.services.copy()

    def get_used_ports(self):
        """Get list of ports currently in use"""
        return [
            service["port"] for service in self.services.values() if service.get("port")
        ]

    def get_next_instance_id(self, template):
        """Get next available instance ID for a template"""
        template_services = self.list_services(template)
        if not template_services:
            return 1

        max_instance = 0
        for service in template_services.values():
            instance_id = service.get("instance_id", 0)
            if isinstance(instance_id, int):
                max_instance = max(max_instance, instance_id)

        return max_instance + 1

    def cleanup_dead_services(self):
        """Remove services for containers that no longer exist"""
        if not DOCKER_AVAILABLE:
            return

        dead_services = []
        for service_id, service in self.services.items():
            container_id = service.get("container_id")
            if container_id:
                try:
                    container = client.containers.get(container_id)
                    # Update status using the proper method
                    self.update_service(service_id, status=container.status)
                except docker.errors.NotFound:
                    # Container no longer exists
                    dead_services.append(service_id)

        for service_id in dead_services:
            logger.info("Removing dead service", service_id=service_id)
            self.unregister_service(service_id)

    def get_service_stats(self):
        """Get statistics about running services"""
        self.cleanup_dead_services()

        stats = {
            "total_services": len(self.services),
            "running_services": 0,
            "templates": {},
            "used_ports": self.get_used_ports(),
        }

        for service in self.services.values():
            template = service.get("template", "unknown")
            if template not in stats["templates"]:
                stats["templates"][template] = 0
            stats["templates"][template] += 1

            if service.get("status") == "running":
                stats["running_services"] += 1

        return stats

    def clear_all(self):
        """Clear the entire registry (use with caution)"""
        self.services = {}
        self._save_registry()


# Global service registry instance
registry = ServiceRegistry()
