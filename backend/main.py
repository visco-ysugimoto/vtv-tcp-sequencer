from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import __version__
from .bit_edges import BitEdgeLog
from .catalog import load_catalog
from .engine import DeviceClient, SequenceEngine, create_client
from .field_network import FieldNetworkClient, parse_eds_text
from .field_network.layout import build_layout
from .field_network.monitor import read_assembly_items
from .local_io import apply_local_io
from .models import (
    LocalIoRequest,
    MemoryReadRequest,
    MemoryWatchItem,
    ProtocolSettings,
    SequenceRequest,
)
from .network import connect_targets
from .paths import frontend_dir
from .plc_link import PlcLinkClient
from .plc_link.commands import command_metadata
from .plc_link.monitor import read_memory_items
from .protocol import ProtocolError
from .watch_stream import format_bit_edges, run_watch_loop

_plclink_client: PlcLinkClient | None = None
_field_network_client: FieldNetworkClient | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await _close_plclink_client()
    await _close_field_network_client()


app = FastAPI(
    title="VTV Network Sequencer",
    version=__version__,
    lifespan=lifespan,
)
FRONTEND = frontend_dir()


@app.middleware("http")
async def disable_frontend_cache(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


class EdsImportResult(BaseModel):
    eds: dict[str, object]
    suggested: dict[str, object]


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
        old_settings = client.settings.model_copy(deep=True)
        await _close_plclink_client()
        try:
            created = create_client(settings)
            await created.start()
            _plclink_client = created
            return created
        except Exception:
            rollback = create_client(old_settings)
            await rollback.start()
            _plclink_client = rollback
            raise

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


def _fn_settings_key(settings: ProtocolSettings) -> str:
    return ":".join(
        [
            settings.host,
            str(settings.port),
            str(settings.fn_input_size),
            str(settings.fn_output_size),
            str(settings.fn_rpi_us),
            settings.fn_connection_path,
            str(settings.fn_esi_ports),
            str(settings.fn_eso_ports),
            str(settings.command_size),
            str(settings.response_size),
            str(settings.result_data_size),
        ]
    )


async def _ensure_field_network_connected(
    settings: ProtocolSettings,
) -> FieldNetworkClient:
    global _field_network_client

    client = _field_network_client
    if client is not None and client.is_connected:
        if _fn_settings_key(client.settings) == _fn_settings_key(settings):
            client.settings = settings
            client.layout = FieldNetworkClient._build_layout(settings)
            return client
        await _close_field_network_client()

    created = FieldNetworkClient(settings)
    await created.connect()
    _field_network_client = created
    return created


async def _close_field_network_client() -> None:
    global _field_network_client

    client, _field_network_client = _field_network_client, None
    if client is not None:
        await client.close()


@app.get("/api/health")
async def health() -> dict[str, bool]:
    """起動プロセスの死活確認用。カタログ読込など重い処理はしない。"""
    return {"ok": True}


@app.get("/api/catalog")
async def get_catalog() -> list[dict]:
    catalog = load_catalog()
    for item in catalog:
        meta = command_metadata(item["code"])
        item.update(meta)
        # 旧メタデータに FN キーが無い場合のみ PLCLINK と同型として補完
        item.setdefault("field_network_supported", meta.get("plclink_supported"))
        item.setdefault("field_network_code", meta.get("plclink_code"))
        item.setdefault("field_network_reason", meta.get("plclink_reason"))
        item.setdefault("local_io", False)
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


@app.post("/api/field-network/connect")
async def connect_field_network(settings: ProtocolSettings) -> dict[str, object]:
    if settings.transport != "field_network":
        raise HTTPException(status_code=400, detail="Field Network モード専用です")
    try:
        client = await _ensure_field_network_connected(settings)
        await client.wait_for_communication()
    except (ProtocolError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    stats = client.scanner.buffers.stats
    return {
        "status": "connected",
        "host": settings.host,
        "port": settings.port,
        "input_size": settings.fn_input_size,
        "output_size": settings.fn_output_size,
        "rpi_us": settings.fn_rpi_us,
        "layout": client.layout.to_dict(),
        "stats": stats,
        "message": (
            f"EtherNet/IP Class 1 接続済み（{settings.host}:{settings.port}）"
        ),
    }


@app.get("/api/field-network/status")
async def field_network_status() -> dict[str, object]:
    client = _field_network_client
    if client is None or not client.is_connected:
        return {
            "status": "disconnected",
            "message": "Field Network は未接続です",
            "stats": {},
        }
    return {
        "status": "connected",
        "host": client.settings.host,
        "port": client.settings.port,
        "layout": client.layout.to_dict(),
        "stats": client.scanner.buffers.stats,
        "message": "Field Network 接続中",
        "error": client.scanner.last_error,
    }


@app.post("/api/field-network/disconnect")
async def disconnect_field_network() -> dict[str, str]:
    await _close_field_network_client()
    return {"status": "disconnected", "message": "Field Network を切断しました"}


@app.post("/api/field-network/eds/import")
async def import_eds(file: UploadFile = File(...)) -> EdsImportResult:
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=400, detail="EDS ファイルが大きすぎます")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp932", errors="replace")
    info = parse_eds_text(text, source_name=file.filename or "import.eds")
    suggested: dict[str, object] = {
        "fn_input_size": info.input_size,
        "fn_output_size": info.output_size,
        "fn_rpi_us": info.rpi_us,
        "fn_connection_path": info.connection_path,
        "fn_o_to_t_header_bytes": info.o_to_t_header_bytes,
        "fn_eds_name": info.catalog or info.product_name or info.source_name,
        "port": 44818,
    }
    try:
        from .field_network.layout import suggest_layout_from_sizes

        suggested.update(
            suggest_layout_from_sizes(
                input_bytes=info.input_size,
                output_bytes=info.output_size,
            )
        )
    except ProtocolError as exc:
        # サイズから割付を推定できない場合は従来の粗い推定に落とす
        out_words = info.output_size // 2
        if out_words >= 6:
            suggested["command_size"] = out_words - 2
            suggested["fn_esi_ports"] = 0
        in_words = info.input_size // 2
        if in_words >= 6:
            remain = in_words - 2
            response = 64 if remain > 64 else max(4, remain // 2)
            response -= response % 2
            result = remain - response
            result -= result % 2
            if result < 0:
                result = 0
                response = remain - (remain % 2)
            suggested["response_size"] = response
            suggested["result_data_size"] = result
            suggested["fn_eso_ports"] = 0
        info.warnings.append(str(exc))
    return EdsImportResult(eds=info.to_dict(), suggested=suggested)


@app.post("/api/field-network/layout/preview")
async def preview_layout(settings: ProtocolSettings) -> dict[str, object]:
    if settings.transport != "field_network":
        raise HTTPException(status_code=400, detail="Field Network モード専用です")
    try:
        layout = build_layout(
            esi_ports=settings.fn_esi_ports,
            eso_ports=settings.fn_eso_ports,
            command_words=settings.command_size,
            response_words=settings.response_size,
            result_words=settings.result_data_size,
        )
    except ProtocolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "layout": layout.to_dict(),
        "match_input": layout.input_bytes == settings.fn_input_size,
        "match_output": layout.output_bytes == settings.fn_output_size,
        "fn_input_size": settings.fn_input_size,
        "fn_output_size": settings.fn_output_size,
    }


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
        if settings.transport == "field_network":
            client = await _ensure_field_network_connected(settings)
            await client.wait_for_communication()
            return {
                "status": "connected",
                "message": (
                    f"EtherNet/IP Implicit I/O を確認しました"
                    f"（{settings.host}:{settings.port}）"
                ),
            }
        async with create_client(settings):
            return {"status": "connected"}
    except ProtocolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/local-io")
async def apply_local_io_endpoint(request: LocalIoRequest) -> dict[str, object]:
    """PLI/ESI ポートを ON/OFF する（シーケンス実行中でも可）。"""
    settings = request.settings
    code = request.code.upper()
    try:
        if code == "PLI":
            if settings.transport != "plclink":
                raise ProtocolError("PLI は PLCLINK 接続時のみ使用できます")
            client = await _get_plclink_client(settings)
        elif code == "ESI":
            if settings.transport != "field_network":
                raise ProtocolError("ESI は Field Network 接続時のみ使用できます")
            client = await _ensure_field_network_connected(settings)
        else:
            raise ProtocolError(f"未対応のローカル I/O です: {code}")
        result = await apply_local_io(
            client,
            code=code,
            arguments={"state": request.state, "ports": request.ports},
        )
    except ProtocolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": result.status,
        "display": result.command,
        "responses": result.responses,
    }


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


@app.post("/api/field-network/memory/read")
async def read_field_network_memory(request: MemoryReadRequest) -> dict[str, object]:
    client = _field_network_client
    if client is None or not client.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Field Network 未接続です。先に接続テストを行ってください。",
        )
    values = read_assembly_items(
        client.read_input(),
        client.read_output(),
        request.items,
        encoding=client.settings.encoding,
        byte_order=client.settings.byte_order,
    )
    return {"values": values, "stats": client.scanner.buffers.stats}


def _watch_edge_log(transport: str) -> BitEdgeLog | None:
    if transport == "plclink":
        client = _plclink_client
        if client is None:
            return None
        return client.memory.edges
    if transport == "field_network":
        client = _field_network_client
        if client is None:
            return None
        return client.scanner.buffers.edges
    return None


def _watch_edge_keys(
    transport: str,
    items: list[MemoryWatchItem],
) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for item in items:
        if item.format != "bit":
            continue
        if transport == "plclink" and item.device == "M":
            keys.add(("M", item.address))
        elif transport == "field_network" and item.device in {"IN", "OUT"}:
            keys.add((item.device, item.address))
    return keys


@app.websocket("/ws/watch")
async def watch_websocket(websocket: WebSocket) -> None:
    """高速監視ストリーム。items を登録後、interval_ms でサンプルを push する。"""
    await websocket.accept()
    stop_event = asyncio.Event()
    loop_task: asyncio.Task[None] | None = None
    armed_edges: BitEdgeLog | None = None

    def disarm_edges() -> None:
        nonlocal armed_edges
        log = armed_edges
        armed_edges = None
        if log is not None:
            log.disarm()

    async def stop_loop() -> None:
        stop_event.set()
        nonlocal loop_task
        if loop_task and not loop_task.done():
            loop_task.cancel()
            await asyncio.gather(loop_task, return_exceptions=True)
        loop_task = None
        disarm_edges()
        stop_event.clear()

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "stop":
                await stop_loop()
                await websocket.send_json({"type": "stopped"})
                continue
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "t": message.get("t")})
                continue
            if msg_type != "start":
                await websocket.send_json({"type": "error", "message": "不明な操作です"})
                continue

            await stop_loop()
            transport = message.get("transport")
            if transport not in {"plclink", "field_network"}:
                await websocket.send_json(
                    {"type": "error", "message": "transport は plclink / field_network のみです"}
                )
                continue
            try:
                items = [
                    MemoryWatchItem.model_validate(item)
                    for item in (message.get("items") or [])
                ]
            except ValidationError as exc:
                await websocket.send_json(
                    {"type": "error", "message": _validation_message(exc)}
                )
                continue
            if not items:
                await websocket.send_json(
                    {"type": "error", "message": "監視アドレスがありません"}
                )
                continue

            interval_ms = float(message.get("interval_ms") or 1)
            interval_ms = min(10_000.0, max(0.5, interval_ms))

            def make_reader(selected_transport: str, selected_items: list[MemoryWatchItem]):
                def read_once() -> list[dict[str, object]]:
                    if selected_transport == "plclink":
                        client = _plclink_client
                        if client is None or not client.server.is_running:
                            raise RuntimeError("疑似PLCが起動していません")
                        return read_memory_items(
                            client.memory,
                            selected_items,
                            encoding=client.settings.encoding,
                            byte_order=client.settings.byte_order,
                        )
                    client = _field_network_client
                    if client is None or not client.is_connected:
                        raise RuntimeError("Field Network 未接続です")
                    return read_assembly_items(
                        client.read_input(),
                        client.read_output(),
                        selected_items,
                        encoding=client.settings.encoding,
                        byte_order=client.settings.byte_order,
                    )

                return read_once

            stop_event.clear()
            disarm_edges()
            edge_log = _watch_edge_log(transport)
            edge_cursor = {"seq": 0}
            if edge_log is not None:
                edge_cursor["seq"] = edge_log.arm(_watch_edge_keys(transport, items))
                armed_edges = edge_log

            def take_edges(
                selected_transport: str = transport,
                cursor: dict[str, int] = edge_cursor,
                selected_items: list[MemoryWatchItem] = items,
            ) -> list[dict[str, object]]:
                active = _watch_edge_log(selected_transport)
                if active is None:
                    return []
                seq, edges = active.take(cursor["seq"])
                cursor["seq"] = seq
                return format_bit_edges(edges, selected_items)

            async def send_json(payload: dict[str, object]) -> None:
                await websocket.send_json(payload)

            loop_task = asyncio.create_task(
                run_watch_loop(
                    transport=transport,  # type: ignore[arg-type]
                    items=items,
                    interval_ms=interval_ms,
                    read_once=make_reader(transport, items),
                    send_json=send_json,
                    should_stop=stop_event.is_set,
                    take_edges=take_edges,
                )
            )
            await websocket.send_json(
                {
                    "type": "ready",
                    "transport": transport,
                    "interval_ms": interval_ms,
                    "item_count": len(items),
                    "mode": "websocket",
                }
            )
    except WebSocketDisconnect:
        await stop_loop()
    except Exception:
        await stop_loop()
        raise


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
                        "duration_ms": 0,
                        "last_response": "",
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
    started = time.perf_counter()
    meta: dict[str, object] = {
        "last_response": "",
        "position": None,
        "total": None,
        "label": "",
    }

    async def send_event(event: dict) -> None:
        if event.get("type") == "rx":
            meta["last_response"] = str(event.get("response") or "")
        elif event.get("type") == "step_started":
            meta["position"] = event.get("position")
            meta["total"] = event.get("total")
            meta["label"] = event.get("label") or ""
        await websocket.send_json(event)

    def failed(message: str) -> dict[str, object]:
        return {
            "type": "sequence_failed",
            "message": message,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "last_response": meta["last_response"],
            "position": meta["position"],
            "total": meta["total"],
            "label": meta["label"],
        }

    settings = request.settings
    if settings.transport == "plclink":
        target = f"PLCLINK SoftPLC {settings.host}:{settings.port}"
    elif settings.transport == "field_network":
        target = f"Field Network {settings.host}:{settings.port}"
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
        elif settings.transport == "field_network":
            await run_with_client(await _ensure_field_network_connected(settings))
        else:
            async with create_client(settings) as client:
                await run_with_client(client)
    except ProtocolError as exc:
        await send_event(failed(str(exc)))
    except Exception as exc:
        await send_event(failed(f"予期しないエラー: {exc}"))
    finally:
        if settings.transport not in {"plclink", "field_network"}:
            await send_event({"type": "connection", "state": "disconnected"})


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "入力内容が不正です"
    return str(errors[0].get("msg", "入力内容が不正です"))


@app.get("/api/version")
async def version() -> dict[str, str]:
    return {"name": "VTV Network Sequencer", "version": __version__}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        FRONTEND / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
