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


def _create_classification_tag(client: TestClient, name: str) -> dict:
    response = client.post("/api/classification-tags", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _create_section_with_attributes(client: TestClient, equipment_id: int, code: str, **attrs) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "code": code,
        "name": f"Secao {code}",
        **attrs,
    }
    response = client.post("/api/sections", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_section_with_new_attributes(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_a = _create_classification_tag(client, "304")
    body = _create_section_with_attributes(
        client,
        equipment["id"],
        "A",
        process_type="COM_FORNO",
        group_code="BQ",
        classification_tag_ids=[tag_a["id"]],
    )
    assert body["process_type"] == "COM_FORNO"
    assert body["group_code"] == "BQ"
    assert body["classification_tag_ids"] == [tag_a["id"]]


def test_update_section_attributes(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_430 = _create_classification_tag(client, "430")
    body = _create_section_with_attributes(client, equipment["id"], "B", process_type="SEM_FORNO")
    response = client.put(
        f"/api/sections/{body['id']}",
        json={"process_type": "COM_FORNO", "group_code": "BF", "classification_tag_ids": [tag_430["id"]]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["process_type"] == "COM_FORNO"
    assert updated["group_code"] == "BF"
    assert updated["classification_tag_ids"] == [tag_430["id"]]


def test_section_legacy_null_attributes(client: TestClient) -> None:
    equipment = _create_equipment(client)
    body = _create_section_with_attributes(client, equipment["id"], "C")
    assert body["process_type"] is None
    assert body["group_code"] is None
    assert body["classification_tag_ids"] == []


def test_reject_invalid_process_type(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "X", "name": "X", "process_type": "FORNO"},
    )
    assert response.status_code == 422


def test_reject_invalid_group_code(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "X", "name": "X", "group_code": "BX"},
    )
    assert response.status_code == 422


def test_classification_tag_create_normalizes_and_dedupes(client: TestClient) -> None:
    body = _create_classification_tag(client, "  abc  ")
    assert body["name"] == "ABC"
    response = client.post("/api/classification-tags", json={"name": "abc"})
    assert response.status_code == 409


def test_section_associates_multiple_tags_and_remove_keeps_global_tag(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_304 = _create_classification_tag(client, "304")
    tag_430 = _create_classification_tag(client, "430")
    body = _create_section_with_attributes(
        client, equipment["id"], "D", classification_tag_ids=[tag_304["id"], tag_430["id"]]
    )
    assert sorted(body["classification_tag_ids"]) == sorted([tag_304["id"], tag_430["id"]])
    # Remove one association; the global tag still exists.
    response = client.put(
        f"/api/sections/{body['id']}",
        json={"classification_tag_ids": [tag_430["id"]]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["classification_tag_ids"] == [tag_430["id"]]
    tag_response = client.get(f"/api/classification-tags/{tag_304['id']}")
    assert tag_response.status_code == 200
    assert tag_response.json()["name"] == "304"


def test_delete_classification_tag_blocked_when_in_use(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag = _create_classification_tag(client, "304")
    _create_section_with_attributes(
        client, equipment["id"], "E", classification_tag_ids=[tag["id"]]
    )
    response = client.delete(f"/api/classification-tags/{tag['id']}")
    assert response.status_code == 409


def test_section_rejects_unknown_classification_tag(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "F",
            "name": "F",
            "classification_tag_ids": [9999],
        },
    )
    assert response.status_code == 422


def test_section_filters_process_group_steel(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_304 = _create_classification_tag(client, "304")
    tag_430 = _create_classification_tag(client, "430")
    _create_section_with_attributes(
        client, equipment["id"], "SA", process_type="COM_FORNO", group_code="BQ",
        classification_tag_ids=[tag_304["id"]]
    )
    _create_section_with_attributes(
        client, equipment["id"], "SB", process_type="COM_FORNO", group_code="BF",
        classification_tag_ids=[tag_430["id"]]
    )
    _create_section_with_attributes(
        client, equipment["id"], "SC", process_type="SEM_FORNO", group_code="BQ",
        classification_tag_ids=[tag_304["id"]]
    )
    _create_section_with_attributes(client, equipment["id"], "LEG")  # nulls

    def codes(**params):
        resp = client.get("/api/sections", params=params)
        assert resp.status_code == 200, resp.text
        return sorted(item["code"] for item in resp.json()["items"])

    assert codes(process_type="COM_FORNO") == ["SA", "SB"]
    assert codes(group_code="BQ") == ["SA", "SC"]
    assert codes(classification_tag_id=tag_304["id"]) == ["SA", "SC"]
    assert codes(process_type="COM_FORNO", group_code="BQ", classification_tag_id=tag_304["id"]) == ["SA"]
    # null sections visible without filter, excluded with any incompatible value
    assert codes() == ["LEG", "SA", "SB", "SC"]
    assert "LEG" not in codes(process_type="SEM_FORNO", group_code="BF")
    # empty string does not filter
    assert codes(process_type="", group_code="") == ["LEG", "SA", "SB", "SC"]


def test_section_list_unchanged_without_new_filters(client: TestClient) -> None:
    equipment = _create_equipment(client)
    _create_section_with_attributes(client, equipment["id"], "NA", process_type="SEM_FORNO")
    resp = client.get("/api/sections", params={"equipment_id": equipment["id"]})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


def _create_classification_tag(client: TestClient, name: str) -> dict:
    response = client.post("/api/classification-tags", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _create_section_with_attributes(client: TestClient, equipment_id: int, code: str, **attrs) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "code": code,
        "name": f"Secao {code}",
        **attrs,
    }
    response = client.post("/api/sections", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_section_with_new_attributes(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_a = _create_classification_tag(client, "304")
    body = _create_section_with_attributes(
        client,
        equipment["id"],
        "A",
        process_type="COM_FORNO",
        group_code="BQ",
        classification_tag_ids=[tag_a["id"]],
    )
    assert body["process_type"] == "COM_FORNO"
    assert body["group_code"] == "BQ"
    assert body["classification_tag_ids"] == [tag_a["id"]]


def test_update_section_attributes(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_430 = _create_classification_tag(client, "430")
    body = _create_section_with_attributes(client, equipment["id"], "B", process_type="SEM_FORNO")
    response = client.put(
        f"/api/sections/{body['id']}",
        json={"process_type": "COM_FORNO", "group_code": "BF", "classification_tag_ids": [tag_430["id"]]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["process_type"] == "COM_FORNO"
    assert updated["group_code"] == "BF"
    assert updated["classification_tag_ids"] == [tag_430["id"]]


def test_section_legacy_null_attributes(client: TestClient) -> None:
    equipment = _create_equipment(client)
    body = _create_section_with_attributes(client, equipment["id"], "C")
    assert body["process_type"] is None
    assert body["group_code"] is None
    assert body["classification_tag_ids"] == []


def test_reject_invalid_process_type(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "X", "name": "X", "process_type": "FORNO"},
    )
    assert response.status_code == 422


def test_reject_invalid_group_code(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "X", "name": "X", "group_code": "BX"},
    )
    assert response.status_code == 422


def test_classification_tag_create_normalizes_and_dedupes(client: TestClient) -> None:
    body = _create_classification_tag(client, "  abc  ")
    assert body["name"] == "ABC"
    response = client.post("/api/classification-tags", json={"name": "abc"})
    assert response.status_code == 409


def test_section_associates_multiple_tags_and_remove_keeps_global_tag(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_304 = _create_classification_tag(client, "304")
    tag_430 = _create_classification_tag(client, "430")
    body = _create_section_with_attributes(
        client, equipment["id"], "D", classification_tag_ids=[tag_304["id"], tag_430["id"]]
    )
    assert sorted(body["classification_tag_ids"]) == sorted([tag_304["id"], tag_430["id"]])
    # Remove one association; the global tag still exists.
    response = client.put(
        f"/api/sections/{body['id']}",
        json={"classification_tag_ids": [tag_430["id"]]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["classification_tag_ids"] == [tag_430["id"]]
    tag_response = client.get(f"/api/classification-tags/{tag_304['id']}")
    assert tag_response.status_code == 200
    assert tag_response.json()["name"] == "304"


def test_delete_classification_tag_blocked_when_in_use(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag = _create_classification_tag(client, "304")
    _create_section_with_attributes(
        client, equipment["id"], "E", classification_tag_ids=[tag["id"]]
    )
    response = client.delete(f"/api/classification-tags/{tag['id']}")
    assert response.status_code == 409


def test_section_rejects_unknown_classification_tag(client: TestClient) -> None:
    equipment = _create_equipment(client)
    response = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "F",
            "name": "F",
            "classification_tag_ids": [9999],
        },
    )
    assert response.status_code == 422


def test_section_filters_process_group_and_classification_tag(client: TestClient) -> None:
    equipment = _create_equipment(client)
    tag_304 = _create_classification_tag(client, "304")
    tag_430 = _create_classification_tag(client, "430")
    _create_section_with_attributes(
        client, equipment["id"], "SA", process_type="COM_FORNO", group_code="BQ",
        classification_tag_ids=[tag_304["id"]],
    )
    _create_section_with_attributes(
        client, equipment["id"], "SB", process_type="COM_FORNO", group_code="BF",
        classification_tag_ids=[tag_430["id"]],
    )
    _create_section_with_attributes(
        client, equipment["id"], "SC", process_type="SEM_FORNO", group_code="BQ",
        classification_tag_ids=[tag_304["id"]],
    )
    _create_section_with_attributes(client, equipment["id"], "LEG")  # no tags

    def codes(**params):
        resp = client.get("/api/sections", params=params)
        assert resp.status_code == 200, resp.text
        return sorted(item["code"] for item in resp.json()["items"])

    assert codes(process_type="COM_FORNO") == ["SA", "SB"]
    assert codes(group_code="BQ") == ["SA", "SC"]
    assert codes(classification_tag_id=tag_304["id"]) == ["SA", "SC"]
    assert codes(
        process_type="COM_FORNO", group_code="BQ", classification_tag_id=tag_304["id"]
    ) == ["SA"]
    assert codes() == ["LEG", "SA", "SB", "SC"]
    assert "LEG" not in codes(process_type="SEM_FORNO", group_code="BF")
    assert codes(process_type="", group_code="") == ["LEG", "SA", "SB", "SC"]


def test_section_list_unchanged_without_new_filters(client: TestClient) -> None:
    equipment = _create_equipment(client)
    _create_section_with_attributes(client, equipment["id"], "NA", process_type="SEM_FORNO")
    resp = client.get("/api/sections", params={"equipment_id": equipment["id"]})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
