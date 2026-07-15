from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/live")
async def live_feed(websocket: WebSocket) -> None:
    await websocket.accept()
    bus = websocket.app.state.event_bus
    queue = bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(queue)
