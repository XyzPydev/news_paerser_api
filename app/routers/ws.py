import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """
    Manages active WebSocket connections with non-blocking async fan-out.

    Architecture note (per plan section 4.C):
    - Messages are broadcast via asyncio.gather(..., return_exceptions=True) so that
      a slow / disconnected client never blocks delivery to faster clients.
    - Disconnected clients are removed on send failure to avoid wasting CPU on dead sockets.
    """

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._active.add(websocket)
        logger.info("WebSocket client connected. Total: %d", len(self._active))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active.discard(websocket)
        logger.info("WebSocket client disconnected. Total: %d", len(self._active))

    async def broadcast(self, message: str) -> None:
        """Send message to all connected clients without blocking on slow clients."""
        async with self._lock:
            clients = set(self._active)

        if not clients:
            return

        results = await asyncio.gather(
            *[client.send_text(message) for client in clients],
            return_exceptions=True,
        )

        # Remove clients that raised exceptions (disconnected / timed out)
        dead: set[WebSocket] = set()
        for client, result in zip(clients, results, strict=False):
            if isinstance(result, Exception):
                logger.debug("Removing dead WebSocket client: %s", result)
                dead.add(client)

        if dead:
            async with self._lock:
                self._active -= dead

    @property
    def client_count(self) -> int:
        return len(self._active)


# Singleton shared across all FastAPI replicas within a single process.
# In a multi-process deployment, each replica has its own ConnectionManager,
# which is the intended Redis Pub/Sub fan-out architecture.
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time news streaming.

    Clients connect here and receive JSON-encoded news events as they are
    published to the Redis Pub/Sub channel by the ingestion workers.
    """
    await manager.connect(websocket)
    try:
        # Keep the connection alive; the server pushes events, client just listens.
        # We still await incoming messages so we can detect a clean close.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
