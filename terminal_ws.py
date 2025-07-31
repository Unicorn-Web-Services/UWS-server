import docker
import asyncio
import websockets
import json

docker_client = docker.from_env()

async def handle_terminal(websocket, path):
    print(f"WebSocket connection initiated from path: {path}")
    try:
        # Parse the container ID from the path
        _, _, container_id = path.rsplit("/", 2)
        print(f"Extracted container ID: {container_id}")
        
        # Get the container
        print(f"Attempting to get container with ID: {container_id}")
        container = docker_client.containers.get(container_id)
        print(f"Container found: {container.name} (Status: {container.status})")
        
        # Check if container is running
        if container.status != 'running':
            error_msg = f"Cannot connect to terminal: Container '{container.name}' is {container.status}, not running"
            print(error_msg)
            await websocket.send_text(f"ERROR: {error_msg}\n")
            await websocket.send_text("Available options:\n")
            await websocket.send_text("1. Start the container first using: docker start <container_id>\n")
            await websocket.send_text("2. Launch a new container using the /launch endpoint\n")
            await websocket.close()
            return

        # Create exec session
        print("Creating exec session for interactive bash...")
        exec_id = docker_client.api.exec_create(
            container.id,
            cmd=["/bin/bash", "-i"],  # Interactive bash shell
            tty=True,
            stdin=True,
            stdout=True,
            stderr=True,
            workdir="/",
        )["Id"]
        print(f"Exec session created with ID: {exec_id}")

        # Start the exec session and get streams
        print("Starting exec session and establishing socket connection...")
        exec_socket = docker_client.api.exec_start(exec_id, tty=True, socket=True, stream=True)
        print("Socket connection established successfully")
        
        # Send initial setup info to the WebSocket client
        await websocket.send_text("=== Docker Terminal Session Started ===\n")
        await websocket.send_text(f"Container: {container.name} ({container.id[:12]})\n")
        await websocket.send_text(f"Status: {container.status}\n")
        await websocket.send_text(f"Image: {container.image.tags[0] if container.image.tags else 'unknown'}\n")
        await websocket.send_text("========================================\n")
        
        # Send a command to show environment setup
        exec_socket._sock.send(b"echo 'Terminal ready - $(whoami)@$(hostname):$(pwd)'\n")
        exec_socket._sock.send(b"echo 'Container uptime: $(uptime)'\n")
        exec_socket._sock.send(b"echo '========================================'\n")
        
        loop = asyncio.get_running_loop()
        print("Starting bidirectional communication tasks...")

        async def container_to_ws():
            print("Container-to-WebSocket task started")
            while True:
                try:
                    # Read data from the container
                    data = await loop.run_in_executor(None, exec_socket._sock.recv, 4096)
                    if not data:
                        print("No more data from container - connection closed")
                        break
                    decoded_data = data.decode(errors="ignore")
                    await websocket.send_text(decoded_data)
                    print(f"Sent data to WebSocket: {repr(decoded_data)}")
                except Exception as e:
                    print(f"Error in container_to_ws: {e}")
                    break
            print("Container-to-WebSocket task ended")

        async def ws_to_container():
            print("WebSocket-to-Container task started")
            while True:
                try:
                    data = await websocket.receive_text()
                    print(f"Received data from WebSocket: {repr(data)}")
                    # Send data to the container
                    await loop.run_in_executor(None, exec_socket._sock.send, data.encode())
                    print(f"Sent data to container: {repr(data)}")
                except Exception as e:
                    print(f"Error in ws_to_container: {e}")
                    break
            print("WebSocket-to-Container task ended")

        print("Starting async gather for both communication tasks...")
        await asyncio.gather(container_to_ws(), ws_to_container())
        print("Both communication tasks completed")

    except Exception as e:
        print(f"Terminal error during setup or execution: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.close()
            print("WebSocket connection closed due to error")
        except:
            print("Failed to close WebSocket connection")
