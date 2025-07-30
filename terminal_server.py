import asyncio
import websockets
from terminal_ws import handle_terminal

async def handle_connection(websocket):
    """Handler that extracts path from websocket and passes to terminal handler"""
    try:
        path = websocket.request.path

        await handle_terminal(websocket, path)
    except Exception as e:
        print(f"Connection handler error: {e}")
        await websocket.close()

async def start_terminal_server():
    print("Starting terminal WebSocket server on port 8765...")
    try:
        # Allow all origins to prevent 403 errors
        async with websockets.serve(
            handle_connection, 
            "0.0.0.0", 
            8765,
            origins=None  # Allow connections from any origin
        ):
            print("Terminal WebSocket server successfully started on port 8765")
            # Keep the server running until cancelled
            await asyncio.Future()
    except asyncio.CancelledError:
        print("Terminal WebSocket server cancelled")
        raise
    except Exception as e:
        print(f"Terminal WebSocket server error: {e}")
        import traceback
        traceback.print_exc()
        raise 
