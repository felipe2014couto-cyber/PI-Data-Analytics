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


def test_section_analysis_tags_are_saved_and_accept_equipment_wide_tags(client: TestClient) -> None:
    equipment = _create_equipment(client)
    section = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "ENTRADA", "name": "Entrada"},
    ).json()
    variable_types = [
        client.post(
            "/api/variable-types",
            json={"code": "LARGURA", "name": "Largura", "default_unit": "mm"},
        ).json(),
        client.post(
            "/api/variable-types",
            json={"code": "UM", "name": "UM", "default_unit": None},
        ).json(),
        client.post(
            "/api/variable-types",
            json={"code": "ESPESSURA", "name": "Espessura", "default_unit": "mm"},
        ).json(),
    ]

    def create_tag(name: str, variable_type: dict, data_type: str = "NUMERIC") -> dict:
        return client.post(
            "/api/pi-tags",
            json={
                "equipment_id": equipment["id"],
                "section_id": section["id"],
                "variable_type_id": variable_type["id"],
                "pi_server": "PIMS",
                "pi_tag_name": f"ENTRADA.{name}",
                "display_name": name,
                "data_type": data_type,
            },
        ).json()

    width = create_tag("Largura", variable_types[0])
    um = create_tag("UM", variable_types[1], "NON_NUMERIC")
    thickness = create_tag("Espessura", variable_types[2])
    response = client.put(
        f"/api/sections/{section['id']}",
        json={
            "width_tag_id": width["id"],
            "um_tag_id": um["id"],
            "thickness_tag_id": thickness["id"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["width_tag_id"] == width["id"]
    assert body["um_tag_id"] == um["id"]
    assert body["thickness_tag_id"] == thickness["id"]

    other_section = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "SAIDA", "name": "Saida"},
    ).json()
    invalid = client.put(
        f"/api/sections/{other_section['id']}",
        json={"width_tag_id": width["id"]},
    )
    assert invalid.status_code == 422

    global_width = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "section_id": None,
            "variable_type_id": variable_types[0]["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "GLOBAL.LARGURA",
            "display_name": "Largura global",
        },
    ).json()
    valid_global = client.put(
        f"/api/sections/{other_section['id']}",
        json={"width_tag_id": global_width["id"]},
    )
    assert valid_global.status_code == 200, valid_global.text
    assert valid_global.json()["width_tag_id"] == global_width["id"]


def test_section_analysis_tags_reject_wrong_variable_type(client: TestClient) -> None:
    equipment = _create_equipment(client)
    section = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "ENTRADA", "name": "Entrada"},
    ).json()
    variable_type = client.post(
        "/api/variable-types",
        json={"code": "TEMPERATURA", "name": "Temperatura", "default_unit": "C"},
    ).json()
    tag = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "section_id": section["id"],
            "variable_type_id": variable_type["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "ENTRADA.TEMP",
            "display_name": "Temperatura",
        },
    ).json()
    response = client.put(f"/api/sections/{section['id']}", json={"width_tag_id": tag["id"]})
    assert response.status_code == 422
