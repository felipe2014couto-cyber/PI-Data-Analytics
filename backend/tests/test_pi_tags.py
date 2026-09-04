"""PiTag endpoint tests."""
from fastapi.testclient import TestClient


def _setup_dependencies(client: TestClient) -> dict:
    equipment = client.post(
        "/api/equipments",
        json={"code": "RB3", "name": "Equipamento RB3"},
    ).json()
    section = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "FORNO", "name": "Forno"},
    ).json()
    variable_type = client.post(
        "/api/variable-types",
        json={"code": "TEMPERATURE", "name": "Temperatura", "default_unit": "C"},
    ).json()
    return {"equipment": equipment, "section": section, "variable_type": variable_type}


def test_create_pi_tag_starts_pending_without_webid(client: TestClient) -> None:
    deps = _setup_dependencies(client)
    response = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": deps["equipment"]["id"],
            "section_id": deps["section"]["id"],
            "variable_type_id": deps["variable_type"]["id"],
            "pi_server": "PISRV01",
            "pi_tag_name": "RB3.FURNO.TEMP",
            "display_name": "Temperatura do forno",
            "engineering_unit": "C",
            "data_type": "NUMERIC",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["validation_status"] == "PENDING"
    assert body["pi_web_id"] is None
    assert body["validated_at"] is None


def test_pi_tag_can_be_assigned_to_entire_equipment(client: TestClient) -> None:
    deps = _setup_dependencies(client)
    response = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": deps["equipment"]["id"],
            "section_id": None,
            "variable_type_id": deps["variable_type"]["id"],
            "pi_server": "PISRV01",
            "pi_tag_name": "RB3.GLOBAL.UM",
            "display_name": "UM do equipamento",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["section_id"] is None

    update = client.put(
        f"/api/pi-tags/{response.json()['id']}",
        json={"section_id": deps["section"]["id"]},
    )
    assert update.status_code == 200, update.text
    assert update.json()["section_id"] == deps["section"]["id"]

    update = client.put(
        f"/api/pi-tags/{response.json()['id']}",
        json={"section_id": None},
    )
    assert update.status_code == 200, update.text
    assert update.json()["section_id"] is None


def test_duplicate_pi_tag_in_same_server(client: TestClient) -> None:
    deps = _setup_dependencies(client)
    payload = {
        "equipment_id": deps["equipment"]["id"],
        "section_id": deps["section"]["id"],
        "variable_type_id": deps["variable_type"]["id"],
        "pi_server": "PISRV01",
        "pi_tag_name": "RB3.FURNO.TEMP",
        "display_name": "Temperatura",
    }
    client.post("/api/pi-tags", json=payload)
    response = client.post("/api/pi-tags", json=payload)
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "DUPLICATE_TAG"


def test_section_must_belong_to_equipment(client: TestClient) -> None:
    equipment_a = client.post(
        "/api/equipments",
        json={"code": "RB3", "name": "Equipamento RB3"},
    ).json()
    equipment_b = client.post(
        "/api/equipments",
        json={"code": "RC4", "name": "Equipamento RC4"},
    ).json()
    section_b = client.post(
        "/api/sections",
        json={"equipment_id": equipment_b["id"], "code": "FORNO", "name": "Forno"},
    ).json()
    variable_type = client.post(
        "/api/variable-types",
        json={"code": "TEMPERATURE", "name": "Temperatura"},
    ).json()

    response = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment_a["id"],
            "section_id": section_b["id"],
            "variable_type_id": variable_type["id"],
            "pi_server": "PISRV01",
            "pi_tag_name": "RB3.FURNO.TEMP",
            "display_name": "Temp",
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "SECTION_NOT_BELONGS_TO_EQUIPMENT"


def test_pi_tag_filters(client: TestClient) -> None:
    deps = _setup_dependencies(client)
    second_section = client.post(
        "/api/sections",
        json={"equipment_id": deps["equipment"]["id"], "code": "ENTRADA", "name": "Entrada"},
    ).json()
    speed = client.post(
        "/api/variable-types",
        json={"code": "SPEED", "name": "Velocidade"},
    ).json()
    base_payload = {
        "equipment_id": deps["equipment"]["id"],
        "section_id": deps["section"]["id"],
        "variable_type_id": deps["variable_type"]["id"],
        "pi_server": "PISRV01",
        "pi_tag_name": "RB3.FURNO.TEMP",
        "display_name": "Temperatura",
    }
    client.post("/api/pi-tags", json=base_payload)
    client.post(
        "/api/pi-tags",
        json={**base_payload, "section_id": second_section["id"], "pi_tag_name": "RB3.ENTRADA.TEMP"},
    )
    client.post(
        "/api/pi-tags",
        json={
            "equipment_id": deps["equipment"]["id"],
            "section_id": deps["section"]["id"],
            "variable_type_id": speed["id"],
            "pi_server": "PISRV01",
            "pi_tag_name": "RB3.FURNO.SPEED",
            "display_name": "Velocidade",
        },
    )

    response = client.get(
        "/api/pi-tags",
        params={"section_id": second_section["id"]},
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["pi_tag_name"] == "RB3.ENTRADA.TEMP"

    response = client.get(
        "/api/pi-tags",
        params={"variable_type_id": speed["id"]},
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["pi_tag_name"] == "RB3.FURNO.SPEED"

    response = client.get(
        "/api/pi-tags",
        params={"validation_status": "PENDING"},
    )
    body = response.json()
    assert body["total"] == 3
