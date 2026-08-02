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
from .network import connect_targets
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


def _plclink_listen_info(settings: ProtocolSettings, client: PlcLinkClient) -> dict[str, object]:
    targets = connect_targets(settings.port)
    preferred = next(
        (t for t in targets if t.startswith("192.168.")),
        targets[0] if targets else f"このPCのIP:{settings.port}",
    )
    return {
        "status": "listening",
        "bind": f"0.0.0.0:{settings.port}",
        "port": settings.port,
        "connect_targets": targets,
        "preferred_target": preferred,
        "client_count": client.server.client_count,
        "message": (
            f"疑似 PLC 待受中（{preferred}）。"
            f" VTV の PLCLINK 接続先を {preferred} に設定してください"
        ),
    }


async def _ensure_plclink_started(settings: ProtocolSettings) -> PlcLinkClient:
    """疑似 PLC を起動する。接続待ちはしない。

    待受ポートが同じなら TCP 接続を維持したまま設定だけ更新する。
    （設定保存のたびに SoftPLC を再起動すると VTV が切断されるため。）
    """
    global _plclink_client

    client = _plclink_client
    if client is not None and client.server.is_running:
        if client.settings.port == settings.port:
            client.settings = settings
            return client
        await _close_plclink_client()

    created = create_client(settings)
    await created.start()
    _plclink_client = created
    return created


async def _get_plclink_client(settings: ProtocolSettings) -> PlcLinkClient:
    """設定が同じ間は疑似 PLC と VTV の接続を再利用する。"""
    client = await _ensure_plclink_started(settings)
    if client.server.client_count == 0:
        await client.wait_for_client()
    return client


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


@app.post("/api/plclink/start")
async def start_plclink(settings: ProtocolSettings) -> dict[str, object]:
    """疑似 PLC の待受だけ開始する（VTV 接続待ちなし）。"""
    if settings.transport != "plclink":
        raise HTTPException(status_code=400, detail="PLCLINK モード専用です")
    try:
        client = await _ensure_plclink_started(settings)
    except ProtocolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _plclink_listen_info(settings, client)


@app.get("/api/plclink/status")
async def plclink_status() -> dict[str, object]:
    client = _plclink_client
    if client is None or not client.server.is_running:
        return {
            "status": "stopped",
            "bind": None,
            "connect_targets": connect_targets(5000),
            "client_count": 0,
            "message": "疑似 PLC は停止しています",
        }
    return _plclink_listen_info(client.settings, client)


@app.post("/api/test-connection")
async def test_connection(settings: ProtocolSettings) -> dict[str, str]:
    try:
        if settings.transport == "plclink":
            client = await _get_plclink_client(settings)
            await client.wait_for_communication()
            preferred = _plclink_listen_info(settings, client)["preferred_target"]
            return {
                "status": "connected",
                "message": f"VTV との MC 3E 通信を確認しました（{preferred}）",
            }
        async with create_client(settings):
            return {"status": "connected"}
    except ProtocolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/plclink/memory/read")
async def read_plclink_memory(request: MemoryReadRequest) -> dict[str, object]:
    client = _plclink_client
    if client is None or not client.server.is_running:
        raise HTTPException(
            status_code=503,
            detail="疑似PLCが起動していません。先に接続テストを行ってください。",
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
