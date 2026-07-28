from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app
from backend.models import ProtocolSettings
from backend.plc_link.memory import DeviceMemory

client = TestClient(app)


def test_catalog_endpoint() -> None:
    response = client.get("/api/catalog")
    assert response.status_code == 200
    catalog = response.json()
    assert len(catalog) == 65
    assert any(
        item["code"] == "ICA" and item["tool_id"] == "T001"
        for item in catalog
    )
    rra = next(item for item in catalog if item["code"] == "RRA")
    poa = next(item for item in catalog if item["code"] == "POA")
    assert rra["plclink_supported"] is True
    assert rra["plclink_code"] == 9
    assert poa["plclink_supported"] is False
    assert {item["tool_id"] for item in catalog if item["category"] == "tool"} == {
        "T001",
        "T004",
        "T016",
        "T018",
        "T026",
        "T030",
        "T034",
        "T056/T058",
        "T075",
    }


def test_index_is_served() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "VTV Network Sequencer" in response.text
    assert "/app.js?v=20260727-2" in response.text


def test_empty_host_is_rejected() -> None:
    response = client.post(
        "/api/test-connection",
        json={"host": "", "port": 55555, "timeout": 5},
    )
    assert response.status_code == 422


def test_plclink_connection_persists_and_is_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeServer:
        is_running = True
        client_count = 1

    class FakePlcLinkClient:
        def __init__(self, settings: object) -> None:
            self.settings = settings
            self.server = FakeServer()
            self.connected = 0
            self.waited = 0
            self.closed = False

        async def connect(self) -> None:
            self.connected += 1

        async def wait_for_communication(self) -> None:
            self.waited += 1

        async def close(self) -> None:
            self.closed = True

    created: list[FakePlcLinkClient] = []

    def create_fake(settings: object) -> FakePlcLinkClient:
        fake = FakePlcLinkClient(settings)
        created.append(fake)
        return fake

    monkeypatch.setattr(main_module, "_plclink_client", None)
    monkeypatch.setattr(main_module, "PlcLinkClient", FakePlcLinkClient)
    monkeypatch.setattr(main_module, "create_client", create_fake)
    payload = {
        "transport": "plclink",
        "host": "0.0.0.0",
        "port": 5000,
        "timeout": 5,
    }

    first = client.post("/api/test-connection", json=payload)
    second = client.post("/api/test-connection", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(created) == 1
    assert created[0].connected == 1
    assert created[0].waited == 2
    assert not created[0].closed
    assert first.json()["message"] == "VTV との MC 3E 通信を確認しました"
    main_module._plclink_client = None


def test_plclink_memory_read(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = DeviceMemory()
    memory.write_dword(100, -2500)
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        port=5000,
    )
    fake = SimpleNamespace(
        memory=memory,
        settings=settings,
        server=SimpleNamespace(is_running=True, client_count=1),
    )
    monkeypatch.setattr(main_module, "_plclink_client", fake)

    response = client.post(
        "/api/plclink/memory/read",
        json={
            "items": [
                {
                    "id": "result",
                    "label": "結果",
                    "device": "D",
                    "address": 100,
                    "format": "fixed",
                    "decimals": 3,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["values"][0]["value"] == -2.5


def test_plclink_memory_read_requires_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_module, "_plclink_client", None)

    response = client.post(
        "/api/plclink/memory/read",
        json={
            "items": [
                {
                    "id": "busy",
                    "device": "M",
                    "address": 1024,
                    "format": "bit",
                }
            ]
        },
    )

    assert response.status_code == 503
