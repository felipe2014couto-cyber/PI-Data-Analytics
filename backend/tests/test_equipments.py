"""Equipment endpoint tests."""
from fastapi.testclient import TestClient


def _create_equipment(client: TestClient, code: str = "RB3", name: str = "Equipamento RB3") -> dict:
    response = client.post(
        "/api/equipments",
        json={"code": code, "name": name, "description": "Descricao", "active": True},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_equipment(client: TestClient) -> None:
    data = _create_equipment(client)
    assert data["code"] == "RB3"
    assert data["name"] == "Equipamento RB3"
    assert data["active"] is True
    assert "id" in data


def test_duplicate_equipment_code(client: TestClient) -> None:
    _create_equipment(client, code="RB3")
    response = client.post(
        "/api/equipments",
        json={"code": "RB3", "name": "Outro"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "DUPLICATE_CODE"


def test_code_is_normalized_to_uppercase(client: TestClient) -> None:
    data = _create_equipment(client, code="  rb3  ", name="Equipamento RB3")
    assert data["code"] == "RB3"


def test_update_equipment(client: TestClient) -> None:
    data = _create_equipment(client)
    equipment_id = data["id"]
    response = client.put(
        f"/api/equipments/{equipment_id}",
        json={"name": "Novo nome", "active": False},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Novo nome"
    assert updated["active"] is False


def test_cannot_delete_equipment_with_section(client: TestClient) -> None:
    data = _create_equipment(client)
    equipment_id = data["id"]
    client.post(
        "/api/sections",
        json={"equipment_id": equipment_id, "code": "FORNO", "name": "Forno"},
    )
    response = client.delete(f"/api/equipments/{equipment_id}")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_EXISTS"


def test_list_equipment_filters(client: TestClient) -> None:
    _create_equipment(client, code="RB3")
    _create_equipment(client, code="RC4", name="Outro")
    response = client.get("/api/equipments", params={"search": "rb3"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "RB3"

    response = client.get("/api/equipments", params={"active": "false"})
    body = response.json()
    assert body["total"] == 0


def test_pagination(client: TestClient) -> None:
    for i in range(5):
        _create_equipment(client, code=f"EQ{i:02d}", name=f"Equipamento {i}")
    response = client.get("/api/equipments", params={"page": 2, "page_size": 2})
    body = response.json()
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2
