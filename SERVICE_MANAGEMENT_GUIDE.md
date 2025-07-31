# Intelligent Service Management System

## Overview

The updated `docker_service.py` now includes an intelligent service management system that automatically handles:

- **Automatic port assignment** - No more manual port configuration
- **Multiple service instances** - Run multiple instances of the same template
- **Unique project directories** - Each instance gets its own directory
- **Service registry** - Track all running services automatically
- **Lifecycle management** - Start, stop, restart, and remove services easily
- **Graceful shutdown** - Automatic cleanup of all containers on Ctrl+C or server termination

## Key Features

### 🛑 Graceful Shutdown System

The system now automatically cleans up all Docker containers when the server shuts down:

```python
# Automatic cleanup happens when:
# - Pressing Ctrl+C (SIGINT)
# - Server receives SIGTERM
# - Process exits normally (atexit handler)

# Manual cleanup functions:
from docker_service import (
    graceful_shutdown,
    force_cleanup_all_services,
    get_cleanup_status
)

# Check what would be cleaned up
status = get_cleanup_status()
print(f"Would clean up {status['registered_services']} services")

# Force cleanup everything immediately
result = force_cleanup_all_services()

# Manual graceful shutdown
graceful_shutdown()
```

**Shutdown Process:**

1. 🔍 Detects all registered services
2. ⏹️ Stops running containers (10s timeout)
3. 🗑️ Removes containers (force if needed)
4. 📝 Clears service registry
5. 🧹 Cleans up orphaned containers
6. ✅ Exits gracefully

### 🚀 Automatic Service Deployment

```python
from docker_service import launch_template_container

# Launch a service with auto-assigned port and unique directory
result = launch_template_container('buckets')

# Launch another instance of the same template
result = launch_template_container('buckets', 'production')

# The system automatically:
# - Assigns available ports (8000, 8001, 8002, etc.)
# - Creates unique directories (../templates/buckets/instance_1/, instance_2/, etc.)
# - Generates unique container names (buckets_instance_1, buckets_production)
# - Registers the service for tracking
```

### 📊 Service Monitoring

```python
from docker_service import (
    list_running_services,
    get_service_info,
    get_service_stats,
    get_all_services_status
)

# List all running services
services = list_running_services()

# Get detailed info about a specific service
info = get_service_info('buckets_instance_1')

# Get overall statistics
stats = get_service_stats()
print(f"Total services: {stats['total_services']}")
print(f"Used ports: {stats['used_ports']}")

# Get comprehensive status report
status = get_all_services_status()
```

### ⚙️ Service Management

```python
from docker_service import (
    stop_service,
    restart_service,
    remove_service,
    auto_cleanup_services
)

# Stop a service (keeps it in registry for restart)
stop_service('buckets_instance_1')

# Restart a stopped service
restart_service('buckets_instance_1')

# Completely remove a service and its container
remove_service('buckets_instance_1', remove_container=True)

# Clean up dead containers automatically
cleanup_report = auto_cleanup_services()
```

## Available Templates

The system comes with predefined templates:

| Template           | Description             | Preferred Port Range |
| ------------------ | ----------------------- | -------------------- |
| `buckets`          | Bucket service          | 8000+                |
| `db`               | Database service        | 8010+                |
| `auth_service`     | Authentication service  | 8020+                |
| `file_manager`     | File management service | 8030+                |
| `database_service` | Database service        | 8040+                |

## Service Registry

The service registry (`service_registry.json`) automatically tracks:

```json
{
  "buckets_instance_1": {
    "template": "buckets",
    "container_name": "buckets_instance_1",
    "container_id": "abc123...",
    "port": 8000,
    "instance_id": 1,
    "project_dir": "../templates/buckets/instance_1",
    "created_at": "2025-07-30T10:30:00",
    "status": "running"
  }
}
```

## Automatic Port Management

The system intelligently assigns ports by:

1. **Checking the service registry** for used ports
2. **Scanning Docker containers** for active port bindings
3. **Testing port availability** on the system
4. **Starting from template preferences** (e.g., buckets prefers 8000+)
5. **Incrementing until a free port is found**

## Directory Structure

Each service instance gets a unique directory:

```
../templates/
├── buckets/
│   ├── instance_1/    # First buckets instance
│   ├── instance_2/    # Second buckets instance
│   └── production/    # Named instance
├── db/
│   └── instance_1/    # First DB instance
└── auth_service/
    └── instance_1/    # First auth service instance
```

## API Usage Examples

### Launch Multiple Instances

```python
# Launch multiple instances of the same service
result1 = launch_template_container('buckets')  # Gets port 8000, instance_1
result2 = launch_template_container('buckets')  # Gets port 8001, instance_2
result3 = launch_template_container('buckets', 'staging')  # Gets port 8002, named 'staging'

print(f"Service 1: {result1['url']}")  # http://localhost:8000
print(f"Service 2: {result2['url']}")  # http://localhost:8001
print(f"Service 3: {result3['url']}")  # http://localhost:8002
```

### Monitor All Services

```python
# Get comprehensive overview
status = get_all_services_status()

print(f"Total services: {status['statistics']['total_services']}")
print(f"Running services: {status['statistics']['running_services']}")

for service_id, service in status['services'].items():
    print(f"{service_id}: {service['template']} on port {service['port']}")
```

### Batch Operations

```python
# Stop all buckets services
buckets_services = list_running_services('buckets')
for service_id in buckets_services:
    stop_service(service_id)

# Clean up everything
cleanup_report = auto_cleanup_services()
print(f"Removed {cleanup_report['containers_removed']} dead containers")
```

## Error Handling

The system includes comprehensive error handling:

```python
# Template validation
result = launch_template_container('invalid_template')
if 'error' in result:
    print(f"Error: {result['error']}")
    # Error: Template 'invalid_template' not found. Available templates: buckets, db, auth_service, file_manager, database_service

# Service not found
info = get_service_info('nonexistent_service')
if 'error' in info:
    print(f"Error: {info['error']}")
```

## Benefits

✅ **No more port conflicts** - Automatic port assignment prevents collisions
✅ **Multiple instances** - Run production, staging, development simultaneously  
✅ **Persistent tracking** - Services survive server restarts via registry
✅ **Easy management** - Simple start/stop/restart operations
✅ **Automatic cleanup** - Dead containers are detected and removed
✅ **Detailed monitoring** - Complete visibility into service status
✅ **Unique directories** - No file conflicts between instances

## Migration from Old System

The old hardcoded approach:

```python
# Old way - hardcoded port and directory
result = setup_fastapi_container(
    repo_url="https://github.com/Unicorn-Web-Services/UWS-tools",
    repo_folder="Buckets",
    container_name="bucket_cont",
    image_name="bucket_container",
    project_dir="../templates",
    app_module="buckets:app",
    base_port=8000
)
```

The new intelligent approach:

```python
# New way - automatic everything
result = launch_template_container('buckets')
```

The new system automatically handles all the configuration and prevents conflicts!
