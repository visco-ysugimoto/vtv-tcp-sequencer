from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .catalog import load_catalog
from .engine import SequenceEngine
from .models import ProtocolSettings, SequenceRequest
from .paths import frontend_dir
from .protocol import ProtocolError, VtvTcpClient

app = FastAPI(title="VTV TCP Sequencer", version="0.1.0")
FRONTEND = frontend_dir()


@app.get("/api/catalog")
async def get_catalog() -> list[dict]:
    return load_catalog()


@app.post("/api/test-connection")
async def test_connection(settings: ProtocolSettings) -> dict[str, str]:
    try:
        async with VtvTcpClient(settings):
            return {"status": "connected"}
    except ProtocolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    stop_event = asyncio.Event()
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "execute":
                await websocket.send_json(
                    {"type": "error", "message": "不明な操作です"}
                )
                continue
            try:
                request = SequenceRequest.model_validate(message.get("payload"))
            except ValidationError as exc:
                await websocket.send_json(
                    {
                        "type": "sequence_failed",
                        "message": _validation_message(exc),
                    }
                )
                continue

            stop_event.clear()
            run_task = asyncio.create_task(
                _execute_sequence(websocket, request, stop_event)
            )
            while not run_task.done():
                receive_task = asyncio.create_task(websocket.receive_json())
                done, _ = await asyncio.wait(
                    {run_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receive_task in done:
                    incoming = receive_task.result()
                    if incoming.get("type") == "stop":
                        stop_event.set()
                else:
                    receive_task.cancel()
                    await asyncio.gather(receive_task, return_exceptions=True)
            await run_task
    except WebSocketDisconnect:
        stop_event.set()


async def _execute_sequence(
    websocket: WebSocket,
    request: SequenceRequest,
    stop_event: asyncio.Event,
) -> None:
    async def send_event(event: dict) -> None:
        await websocket.send_json(event)

    try:
        await send_event(
            {
                "type": "connection",
                "state": "connecting",
                "message": f"{request.settings.host}:{request.settings.port}",
            }
        )
        async with VtvTcpClient(request.settings) as client:
            await send_event(
                {"type": "connection", "state": "connected"}
            )
            engine = SequenceEngine(client, send_event, stop_event)
            await engine.run(request.steps)
    except ProtocolError as exc:
        await send_event(
            {"type": "sequence_failed", "message": str(exc)}
        )
    except Exception as exc:
        await send_event(
            {
                "type": "sequence_failed",
                "message": f"予期しないエラー: {exc}",
            }
        )
    finally:
        await send_event({"type": "connection", "state": "disconnected"})


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "入力内容が不正です"
    return str(errors[0].get("msg", "入力内容が不正です"))


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
