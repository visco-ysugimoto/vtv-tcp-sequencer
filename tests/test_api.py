from fastapi.testclient import TestClient

from backend.main import app

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
    assert "VTV TCP Sequencer" in response.text


def test_empty_host_is_rejected() -> None:
    response = client.post(
        "/api/test-connection",
        json={"host": "", "port": 55555, "timeout": 5},
    )
    assert response.status_code == 422
