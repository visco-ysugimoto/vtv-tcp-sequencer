from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .catalog import load_catalog
from .engine import DeviceClient, SequenceEngine, create_client
from .models import MemoryReadRequest, ProtocolSettings, SequenceRequest
from .paths import frontend_dir
from .plc_link import PlcLinkClient
from .plc_link.commands import command_metadata
from .plc_link.monitor import read_memory_items
from .protocol import ProtocolError

_plclink_client: PlcLinkClient | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await _close_plclink_client()


app = FastAPI(
    title="VTV TCP Sequencer",
    version="0.1.0",
    lifespan=lifespan,
)
FRONTEND = frontend_dir()


async def _get_plclink_client(settings: ProtocolSettings) -> PlcLinkClient:
    """設定が同じ間は疑似 PLC と VTV の接続を再利用する。"""
    global _plclink_client

    client = _plclink_client
    if (
        client is not None
        and client.settings == settings
        and client.server.is_running
    ):
        if client.server.client_count == 0:
            await client.wait_for_client()
        return client

    await _close_plclink_client()
    created = create_client(settings)
    assert isinstance(created, PlcLinkClient)
    await created.connect()
    _plclink_client = created
    return created


async def _close_plclink_client() -> None:
    global _plclink_client

    client, _plclink_client = _plclink_client, None
    if client is not None:
        await client.close()


@app.get("/api/catalog")
async def get_catalog() -> list[dict]:
    catalog = load_catalog()
    for item in catalog:
        item.update(command_metadata(item["code"]))
    return catalog


@app.post("/api/test-connection")
async def test_connection(settings: ProtocolSettings) -> dict[str, str]:
    try:
        if settings.transport == "plclink":
            client = await _get_plclink_client(settings)
            await client.wait_for_communication()
            return {
                "status": "connected",
                "message": "VTV との MC 3E 通信を確認しました",
            }
        async with create_client(settings):
            return {"status": "connected"}
    except ProtocolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/plclink/memory/read")
async def read_plclink_memory(request: MemoryReadRequest) -> dict[str, object]:
    client = _plclink_client
    if (
        client is None
        or not client.server.is_running
        or client.server.client_count == 0
    ):
        raise HTTPException(
            status_code=503,
            detail="VTVとのPLCLINK接続がありません",
        )
    values = read_memory_items(
        client.memory,
        request.items,
        encoding=client.settings.encoding,
        byte_order=client.settings.byte_order,
    )
    return {"values": values}


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

    settings = request.settings
    if settings.transport == "plclink":
        target = f"PLCLINK SoftPLC {settings.host}:{settings.port}"
    else:
        target = f"{settings.host}:{settings.port}"

    try:
        await send_event(
            {
                "type": "connection",
                "state": "connecting",
                "message": target,
            }
        )
        async def run_with_client(client: DeviceClient) -> None:
            await send_event(
                {"type": "connection", "state": "connected"}
            )
            engine = SequenceEngine(client, send_event, stop_event)
            await engine.run(request.steps)

        if settings.transport == "plclink":
            await run_with_client(await _get_plclink_client(settings))
        else:
            async with create_client(settings) as client:
                await run_with_client(client)
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
        if settings.transport != "plclink":
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
