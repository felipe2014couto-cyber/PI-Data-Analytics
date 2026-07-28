"""Section endpoint tests."""
from fastapi.testclient import TestClient


def _create_equipment(client: TestClient, code: str = "RB3") -> dict:
    response = client.post(
        "/api/equipments",
        json={"code": code, "name": f"Equipamento {code}"},
    )
    return response.json()


def test_create_section(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "FORNO",
            "name": "Forno",
            "description": "Secao principal",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["code"] == "FORNO"
    assert body["equipment_id"] == equipment["id"]


def test_duplicate_section_code_in_same_equipment(client: TestClient) -> None:
    equipment = _create_equipment(client)
    client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "FORNO", "name": "Forno"},
    )
    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "FORNO", "name": "Outro"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "DUPLICATE_CODE"


def test_section_code_normalization(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "  forno  ", "name": "Forno"},
    )
    assert response.status_code == 201
    assert response.json()["code"] == "FORNO"


def test_section_must_belong_to_equipment_on_create(client: TestClient) -> None:
    equipment_a = _create_equipment(client, code="RB3")
    equipment_b = _create_equipment(client, code="RC4")
    section_response = client.post(
        "/api/sections",
        json={"equipment_id": equipment_b["id"], "code": "FORNO", "name": "Forno"},
    )
    assert section_response.status_code == 201
    section = section_response.json()

    response = client.put(
        f"/api/sections/{section['id']}",
        json={"equipment_id": equipment_a["id"]},
    )
    assert response.status_code == 200

    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment_b["id"], "code": "ENTRADA", "name": "Entrada"},
    )
    assert response.status_code == 201

    response = client.put(
        f"/api/sections/{section['id']}",
        json={"equipment_id": 9999},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_EQUIPMENT"


def test_section_list_filtered_by_equipment(client: TestClient) -> None:
    eq_a = _create_equipment(client, code="RB3")
    eq_b = _create_equipment(client, code="RC4")
    client.post(
        "/api/sections",
        json={"equipment_id": eq_a["id"], "code": "FORNO", "name": "Forno A"},
    )
    client.post(
        "/api/sections",
        json={"equipment_id": eq_b["id"], "code": "FORNO", "name": "Forno B"},
    )
    response = client.get("/api/sections", params={"equipment_id": eq_a["id"]})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["equipment_id"] == eq_a["id"]
