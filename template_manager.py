"""
Template Manager Module

Manages template configurations and template-based container launching.
Handles the predefined service templates and their deployment.
"""

from pathlib import Path
from autoNewservice import setup_fastapi_container
from service_registry import registry
from container_operations import get_free_port
from utils import logger

# Template configurations for different services
TEMPLATE_CONFIGS = {
    "buckets": {
        "repo_url": "https://github.com/Unicorn-Web-Services/UWS-tools",
        "repo_folder": "Buckets",
        "app_module": "buckets:app",
        "base_port_preference": 8000,  # Preferred starting port
        "show_logs": True,
        "description": "S3-like file storage service with upload, download, and file management",
        "endpoints": [
            "/data/upload",
            "/data/files",
            "/data/download/{filename}",
            "/data/delete/{filename}",
        ],
    },
    "db": {
        "repo_url": "https://github.com/Unicorn-Web-Services/UWS-tools",
        "repo_folder": "DB",
        "app_module": "dbEndPoint:app",
        "base_port_preference": 8010,
        "show_logs": True,
        "description": "SQL database service with file storage and metadata management",
        "endpoints": [
            "/upload/{table_name}",
            "/files/{table_name}",
            "/download/{table_name}/{entity_id}",
            "/delete/{table_name}/{entity_id}",
        ],
    },
    "nosql_db": {
        "repo_url": "https://github.com/Unicorn-Web-Services/UWS-tools",
        "repo_folder": "DB_NoSQL",
        "app_module": "NoSQL_dbEndPoint:app",
        "base_port_preference": 8020,
        "show_logs": True,
        "description": "MongoDB NoSQL database service with document storage and querying",
        "endpoints": [
            "/nosql/create_collection/{collection_name}",
            "/nosql/{collection_name}/save",
            "/nosql/{collection_name}/query",
            "/nosql/{collection_name}/scan",
            "/nosql/{collection_name}/get/{entity_id}",
            "/nosql/{collection_name}/delete/{entity_id}",
        ],
    },
    "queue": {
        "repo_url": "https://github.com/Unicorn-Web-Services/UWS-tools",
        "repo_folder": "Queue",
        "app_module": "QueueEndpoints:App",
        "base_port_preference": 8030,
        "show_logs": True,
        "description": "In-memory message queue service for asynchronous processing",
        "endpoints": ["/queue", "/queue/{message_id}"],
    },
    "secrets": {
        "repo_url": "https://github.com/Unicorn-Web-Services/UWS-tools",
        "repo_folder": "Secrets",
        "app_module": "SecretsEndpoint:app",
        "base_port_preference": 8040,
        "show_logs": True,
        "description": "Secrets management service with encryption",
        "endpoints": [
            "/secrets/{name}",
            "/secrets",
        ],
    },
}


def get_available_templates():
    """Get list of available template names"""
    return list(TEMPLATE_CONFIGS.keys())


def get_template_config(template: str):
    """Get configuration for a specific template

    Args:
        template (str): Template name

    Returns:
        dict: Template configuration or error message
    """
    if template not in TEMPLATE_CONFIGS:
        available = ", ".join(get_available_templates())
        return {
            "error": f"Template '{template}' not found. Available templates: {available}"
        }

    return {"config": TEMPLATE_CONFIGS[template]}


def launch_template_container(template: str, instance_name: str = None):
    """Launch a container based on a predefined template configuration with automatic instance management

    Args:
        template (str): Template name (e.g., 'buckets', 'db', etc.)
        instance_name (str, optional): Custom instance name. If not provided, auto-generated.

    Returns:
        dict: Result from setup_fastapi_container with success status and details
    """
    if template not in TEMPLATE_CONFIGS:
        available = ", ".join(get_available_templates())
        return {
            "error": f"Template '{template}' not found. Available templates: {available}"
        }

    # Clean up any dead services first
    registry.cleanup_dead_services()

    config = TEMPLATE_CONFIGS[template].copy()

    # Get next instance ID for this template
    instance_id = registry.get_next_instance_id(template)

    # Generate unique names and directories
    if instance_name:
        # Use custom instance name
        safe_instance_name = instance_name.replace(" ", "_").lower()
        container_name = f"{template}_{safe_instance_name}"
        image_name = f"{template}_{safe_instance_name}_image"
        service_id = f"{template}_{safe_instance_name}"
    else:
        # Use auto-generated instance ID
        container_name = f"{template}_instance_{instance_id}"
        image_name = f"{template}_instance_{instance_id}_image"
        service_id = f"{template}_instance_{instance_id}"

    # Create unique project directory
    base_templates_dir = Path("../templates")
    project_dir = base_templates_dir / template / f"instance_{instance_id}"
    project_dir_str = str(project_dir)

    # Get an available port
    preferred_port = config.get("base_port_preference", 8000)
    assigned_port = get_free_port(preferred_port)

    # Prepare configuration for setup_fastapi_container
    setup_config = {
        "repo_url": config["repo_url"],
        "repo_folder": config["repo_folder"],
        "container_name": container_name,
        "image_name": image_name,
        "project_dir": project_dir_str,
        "app_module": config["app_module"],
        "base_port": assigned_port,
        "show_logs": config.get("show_logs", True),
    }

    logger.info(
        "Launching template container",
        template=template,
        service_id=service_id,
        instance_id=instance_id,
        repo_url=config["repo_url"],
        repo_folder=config["repo_folder"],
        container_name=container_name,
        project_dir=project_dir_str,
        assigned_port=assigned_port,
    )

    # Launch the container
    result = setup_fastapi_container(**setup_config)

    if result["success"]:
        # Register the service
        registry.register_service(
            service_id=service_id,
            template=template,
            container_name=container_name,
            port=assigned_port,
            instance_id=instance_id,
            project_dir=project_dir_str,
            container_id=result.get(
                "container_id"
            ),  # Will be updated when we can get it
        )

        # Try to get container ID and update registry
        from service_registry import DOCKER_AVAILABLE

        if DOCKER_AVAILABLE:
            try:
                import docker

                client = docker.from_env()
                container = client.containers.get(container_name)
                # Update the container_id in the registry
                registry.update_service(service_id, container_id=container.id)
            except Exception as e:
                logger.warning("Could not get container ID", error=str(e))

        logger.info(
            "Template launched successfully",
            template=template,
            service_id=service_id,
            service_url=result["url"],
            docs_url=result["docs_url"],
            container_name=result["container_name"],
            port=result["port"],
        )

        # Add service tracking info to result
        result["service_id"] = service_id
        result["instance_id"] = instance_id
        result["template"] = template

    else:
        logger.error("Failed to launch template", template=template)

    return result
