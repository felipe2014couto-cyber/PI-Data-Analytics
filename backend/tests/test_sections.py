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
            json={"code": "LARGURA", "name": "Largura", "default_unit": "mm", "filter_data_type": "REAL"},
        ).json(),
        client.post(
            "/api/variable-types",
            json={"code": "UM", "name": "UM", "default_unit": None, "filter_data_type": "STRING"},
        ).json(),
        client.post(
            "/api/variable-types",
            json={"code": "ESPESSURA", "name": "Espessura", "default_unit": "mm", "filter_data_type": "REAL"},
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
        json={"code": "TEMPERATURA", "name": "Temperatura", "default_unit": "C", "filter_data_type": "REAL"},
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


def test_dynamic_analysis_tags_lifecycle_and_validation(client: TestClient) -> None:
    equipment = _create_equipment(client, code="RB9")
    eq_other = _create_equipment(client, code="RB8")

    var_current = client.post(
        "/api/variable-types",
        json={"code": "CURRENT", "name": "Corrente", "default_unit": "A", "filter_data_type": "REAL"},
    ).json()
    var_pressure = client.post(
        "/api/variable-types",
        json={"code": "PRESSURE", "name": "Pressao", "default_unit": "bar", "filter_data_type": "REAL"},
    ).json()
    var_temperature = client.post(
        "/api/variable-types",
        json={"code": "TEMPERATURE", "name": "Temperatura", "default_unit": "C", "filter_data_type": "REAL"},
    ).json()

    tag_current_1 = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "variable_type_id": var_current["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "RB9.CURRENT.1",
            "display_name": "Corrente 1",
        },
    ).json()
    tag_current_2 = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "variable_type_id": var_current["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "RB9.CURRENT.2",
            "display_name": "Corrente 2",
        },
    ).json()
    tag_pressure_1 = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "variable_type_id": var_pressure["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "RB9.PRESSURE.1",
            "display_name": "Pressao 1",
        },
    ).json()
    tag_temp_wrong_eq = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": eq_other["id"],
            "variable_type_id": var_temperature["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "RB8.TEMP.1",
            "display_name": "Temperatura RB8",
        },
    ).json()

    # 1. Criação com analysis_tags válidas
    create_resp = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "SEC1",
            "name": "Secao 1",
            "analysis_tags": [
                {"variable_type_id": var_current["id"], "pi_tag_id": tag_current_1["id"]},
                {"variable_type_id": var_pressure["id"], "pi_tag_id": tag_pressure_1["id"]},
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    sec1 = create_resp.json()
    assert len(sec1["analysis_tags"]) == 2
    tags_by_code = {t["variable_type_code"]: t for t in sec1["analysis_tags"]}
    assert tags_by_code["CURRENT"]["pi_tag_name"] == "RB9.CURRENT.1"
    assert tags_by_code["CURRENT"]["variable_type_name"] == "Corrente"
    assert tags_by_code["PRESSURE"]["pi_tag_name"] == "RB9.PRESSURE.1"

    # 2. Rejeição de duplicidade de variable_type_id na mesma seção
    dup_resp = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "SEC_DUP",
            "name": "Secao Dup",
            "analysis_tags": [
                {"variable_type_id": var_current["id"], "pi_tag_id": tag_current_1["id"]},
                {"variable_type_id": var_current["id"], "pi_tag_id": tag_current_2["id"]},
            ],
        },
    )
    assert dup_resp.status_code == 422

    # 3. Permitir mesmo variable_type_id em seções diferentes
    sec2_resp = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "SEC2",
            "name": "Secao 2",
            "analysis_tags": [
                {"variable_type_id": var_current["id"], "pi_tag_id": tag_current_2["id"]},
            ],
        },
    )
    assert sec2_resp.status_code == 201

    # 4. Rejeitar PI Tag com VariableType divergente
    mismatch_resp = client.put(
        f"/api/sections/{sec1['id']}",
        json={
            "analysis_tags": [
                {"variable_type_id": var_current["id"], "pi_tag_id": tag_pressure_1["id"]},
            ],
        },
    )
    assert mismatch_resp.status_code == 422

    # 5. Rejeitar PI Tag de outro equipamento
    eq_mismatch_resp = client.put(
        f"/api/sections/{sec1['id']}",
        json={
            "analysis_tags": [
                {"variable_type_id": var_temperature["id"], "pi_tag_id": tag_temp_wrong_eq["id"]},
            ],
        },
    )
    assert eq_mismatch_resp.status_code == 422

    # 6. Atualização não-destrutiva: alterar pi_tag de CURRENT e remover PRESSURE
    update_sync_resp = client.put(
        f"/api/sections/{sec1['id']}",
        json={
            "analysis_tags": [
                {"variable_type_id": var_current["id"], "pi_tag_id": tag_current_2["id"]},
            ],
        },
    )
    assert update_sync_resp.status_code == 200
    sec1_updated = update_sync_resp.json()
    assert len(sec1_updated["analysis_tags"]) == 1
    assert sec1_updated["analysis_tags"][0]["pi_tag_id"] == tag_current_2["id"]

    # 7. PATCH / update de outro campo preserva analysis_tags existentes
    patch_resp = client.put(
        f"/api/sections/{sec1['id']}",
        json={"name": "Novo nome Secao 1"},
    )
    assert patch_resp.status_code == 200
    patch_body = patch_resp.json()
    assert patch_body["name"] == "Novo nome Secao 1"
    assert len(patch_body["analysis_tags"]) == 1
    assert patch_body["analysis_tags"][0]["pi_tag_id"] == tag_current_2["id"]

    # 8. analysis_tags=[] remove todas as tags dinâmicas sem afetar campos fixos
    clean_resp = client.put(
        f"/api/sections/{sec1['id']}",
        json={"analysis_tags": []},
    )
    assert clean_resp.status_code == 200
    assert len(clean_resp.json()["analysis_tags"]) == 0


def test_legacy_section_with_fixed_tags_and_empty_analysis_tags(client: TestClient) -> None:
    """Confirma que seção antiga com width/um/thickness mas sem tags dinâmicas é listada normalmente."""
    equipment = _create_equipment(client, code="LEGACY_EQ")
    var_width = client.post(
        "/api/variable-types",
        json={"code": "LARGURA", "name": "Largura", "default_unit": "mm", "filter_data_type": "REAL"},
    ).json()
    var_um = client.post(
        "/api/variable-types",
        json={"code": "UM", "name": "UM", "default_unit": None, "filter_data_type": "STRING"},
    ).json()
    var_thickness = client.post(
        "/api/variable-types",
        json={"code": "ESPESSURA", "name": "Espessura", "default_unit": "mm", "filter_data_type": "REAL"},
    ).json()

    tag_width = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "variable_type_id": var_width["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "LEGACY.LARGURA",
            "display_name": "Largura Legacy",
        },
    ).json()
    tag_um = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "variable_type_id": var_um["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "LEGACY.UM",
            "display_name": "UM Legacy",
            "data_type": "NON_NUMERIC",
        },
    ).json()
    tag_thickness = client.post(
        "/api/pi-tags",
        json={
            "equipment_id": equipment["id"],
            "variable_type_id": var_thickness["id"],
            "pi_server": "PIMS",
            "pi_tag_name": "LEGACY.ESPESSURA",
            "display_name": "Espessura Legacy",
        },
    ).json()

    sec_resp = client.post(
        "/api/sections",
        json={
            "equipment_id": equipment["id"],
            "code": "LEGACY_SEC",
            "name": "Secao Antiga",
            "width_tag_id": tag_width["id"],
            "um_tag_id": tag_um["id"],
            "thickness_tag_id": tag_thickness["id"],
        },
    )
    assert sec_resp.status_code == 201
    created_sec = sec_resp.json()
    assert created_sec["width_tag_id"] == tag_width["id"]
    assert created_sec["um_tag_id"] == tag_um["id"]
    assert created_sec["thickness_tag_id"] == tag_thickness["id"]
    assert created_sec["analysis_tags"] == []

    list_resp = client.get("/api/sections", params={"equipment_id": equipment["id"]})
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert len(list_data["items"]) == 1
    item = list_data["items"][0]
    assert item["id"] == created_sec["id"]
    assert item["width_tag_id"] == tag_width["id"]
    assert item["um_tag_id"] == tag_um["id"]
    assert item["thickness_tag_id"] == tag_thickness["id"]
    assert item["analysis_tags"] == []


def test_section_analysis_tag_filter_type_lifecycle(client: TestClient) -> None:
    eq = client.post("/api/equipments", json={"code": "EQ-FT", "name": "Equip FilterType"}).json()
    vt_real = client.post("/api/variable-types", json={"code": "CURR_FT", "name": "Corrente", "filter_data_type": "REAL"}).json()
    vt_text = client.post("/api/variable-types", json={"code": "PROD_FT", "name": "Produto", "filter_data_type": "STRING"}).json()
    vt_disc = client.post("/api/variable-types", json={"code": "STATUS_FT", "name": "Status", "filter_data_type": "DIGITAL"}).json()

    tag_curr = client.post("/api/pi-tags", json={"equipment_id": eq["id"], "variable_type_id": vt_real["id"], "pi_server": "P", "pi_tag_name": "T.CURR", "display_name": "Corrente", "data_type": "NUMERIC"}).json()
    tag_prod = client.post("/api/pi-tags", json={"equipment_id": eq["id"], "variable_type_id": vt_text["id"], "pi_server": "P", "pi_tag_name": "T.PROD", "display_name": "Produto", "data_type": "NON_NUMERIC"}).json()
    tag_status = client.post("/api/pi-tags", json={"equipment_id": eq["id"], "variable_type_id": vt_disc["id"], "pi_server": "P", "pi_tag_name": "T.STAT", "display_name": "Status", "data_type": "NON_NUMERIC"}).json()

    # Create section with all 3 filter types
    resp = client.post(
        "/api/sections",
        json={
            "equipment_id": eq["id"],
            "code": "SEC-FT1",
            "name": "Secao Filtro Tipos",
            "analysis_tags": [
                {"variable_type_id": vt_real["id"], "pi_tag_id": tag_curr["id"], "filter_type": "MIN_MAX"},
                {"variable_type_id": vt_text["id"], "pi_tag_id": tag_prod["id"], "filter_type": "TEXT"},
                {"variable_type_id": vt_disc["id"], "pi_tag_id": tag_status["id"], "filter_type": "SELECTION"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    sec = resp.json()
    tags_by_vt = {t["variable_type_id"]: t for t in sec["analysis_tags"]}
    assert tags_by_vt[vt_real["id"]]["filter_type"] == "MIN_MAX"
    assert tags_by_vt[vt_text["id"]]["filter_type"] == "TEXT"
    assert tags_by_vt[vt_disc["id"]]["filter_type"] == "SELECTION"

    # Verify GET by ID
    get_resp = client.get(f"/api/sections/{sec['id']}")
    assert get_resp.status_code == 200
    get_tags_by_vt = {t["variable_type_id"]: t for t in get_resp.json()["analysis_tags"]}
    assert get_tags_by_vt[vt_real["id"]]["filter_type"] == "MIN_MAX"
    assert get_tags_by_vt[vt_text["id"]]["filter_type"] == "TEXT"
    assert get_tags_by_vt[vt_disc["id"]]["filter_type"] == "SELECTION"

    # Update section changing filter_type on one tag and keeping others
    update_resp = client.put(
        f"/api/sections/{sec['id']}",
        json={
            "analysis_tags": [
                {"variable_type_id": vt_real["id"], "pi_tag_id": tag_curr["id"], "filter_type": "SELECTION"},
                {"variable_type_id": vt_text["id"], "pi_tag_id": tag_prod["id"], "filter_type": "TEXT"},
            ],
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    updated_tags = {t["variable_type_id"]: t for t in update_resp.json()["analysis_tags"]}
    assert len(updated_tags) == 2
    assert updated_tags[vt_real["id"]]["filter_type"] == "SELECTION"
    assert updated_tags[vt_text["id"]]["filter_type"] == "TEXT"


def test_section_analysis_tag_min_max_rejects_non_numeric(client: TestClient) -> None:
    eq = client.post("/api/equipments", json={"code": "EQ-REJ", "name": "Equip Reject"}).json()
    vt_text = client.post("/api/variable-types", json={"code": "TXT_VAR", "name": "Variavel Texto", "filter_data_type": "STRING"}).json()
    tag_prod = client.post("/api/pi-tags", json={"equipment_id": eq["id"], "variable_type_id": vt_text["id"], "pi_server": "P", "pi_tag_name": "T.PROD2", "display_name": "Produto 2", "data_type": "NON_NUMERIC"}).json()

    # Attempt to assign MIN_MAX to a text tag/variable
    resp = client.post(
        "/api/sections",
        json={
            "equipment_id": eq["id"],
            "code": "SEC-REJ",
            "name": "Secao Rejeitada",
            "analysis_tags": [
                {"variable_type_id": vt_text["id"], "pi_tag_id": tag_prod["id"], "filter_type": "MIN_MAX"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "MIN_MAX" in resp.json()["error"]["message"]


def test_pi_tag_distinct_values_endpoint(client: TestClient, db_session) -> None:
    from datetime import datetime, timedelta, timezone
    from app.models.postgres import PiSample

    eq = client.post("/api/equipments", json={"code": "EQ-DIST", "name": "Equip Distinct"}).json()
    vt_str = client.post("/api/variable-types", json={"code": "BATCH_VT", "name": "Lote", "filter_data_type": "STRING"}).json()
    tag = client.post("/api/pi-tags", json={"equipment_id": eq["id"], "variable_type_id": vt_str["id"], "pi_server": "P", "pi_tag_name": "BATCH.TAG", "display_name": "Tag Lote", "data_type": "NON_NUMERIC"}).json()

    # Insert sample points with distinct timestamps
    now = datetime.now(timezone.utc)
    for i, val in enumerate(["LOTE-A", "LOTE-B", "LOTE-A", "LOTE-C"]):
        db_session.add(PiSample(
            tag_id=tag["id"],
            ts=now + timedelta(minutes=i),
            value_type="string",
            value_text=val,
            good=True,
        ))
    db_session.commit()

    resp = client.get(f"/api/pi-tags/{tag['id']}/distinct-values")
    assert resp.status_code == 200
    values = resp.json()
    assert sorted(values) == ["LOTE-A", "LOTE-B", "LOTE-C"]





def test_section_steel_type_fixed_tag_lifecycle(client: TestClient, db_session) -> None:
    equipment = _create_equipment(client, code="STEEL-EQ")
    section = client.post(
        "/api/sections",
        json={"equipment_id": equipment["id"], "code": "STEEL-SEC", "name": "Steel section"},
    ).json()
    steel_type = client.post(
        "/api/variable-types",
        json={"code": "TIPO_DE_ACO", "name": "Tipo de Aço", "filter_data_type": "STRING"},
    ).json()

    def create_tag(tag_name: str) -> dict:
        response = client.post("/api/pi-tags", json={
            "equipment_id": equipment["id"], "section_id": section["id"],
            "variable_type_id": steel_type["id"], "pi_server": "PIMS",
            "pi_tag_name": tag_name, "display_name": tag_name,
            "data_type": "NON_NUMERIC",
        })
        assert response.status_code == 201, response.text
        return response.json()

    first_tag = create_tag("STEEL.MODEL.1")
    second_tag = create_tag("STEEL.MODEL.2")
    from datetime import datetime, timedelta, timezone
    from app.models.postgres import PiSample

    now = datetime.now(timezone.utc)
    for index, (tag_id, value) in enumerate([
        (first_tag["id"], "P304A"),
        (first_tag["id"], "P430A"),
        (second_tag["id"], "P399B"),
    ]):
        db_session.add(PiSample(
            tag_id=tag_id,
            ts=now + timedelta(minutes=index),
            value_type="string",
            value_text=value,
            good=True,
        ))
    db_session.commit()

    global_tag_response = client.post("/api/pi-tags", json={
        "equipment_id": equipment["id"], "section_id": None,
        "variable_type_id": steel_type["id"], "pi_server": "PIMS",
        "pi_tag_name": "STEEL.MODEL.GLOBAL", "display_name": "Global steel model",
        "data_type": "NON_NUMERIC",
    })
    assert global_tag_response.status_code == 201, global_tag_response.text
    created = client.post("/api/sections", json={
        "equipment_id": equipment["id"], "code": "STEEL-NEW", "name": "Steel new",
        "steel_type_tag_id": global_tag_response.json()["id"],
    })
    assert created.status_code == 201, created.text
    assert created.json()["steel_type_tag_id"] == global_tag_response.json()["id"]

    # A tag scoped to another section is rejected, just like the existing fixed slots.
    other_section = client.post("/api/sections", json={
        "equipment_id": equipment["id"], "code": "STEEL-OTHER", "name": "Other",
    }).json()
    invalid_scope = client.put(f"/api/sections/{other_section['id']}", json={
        "steel_type_tag_id": first_tag["id"],
    })
    assert invalid_scope.status_code == 422

    assigned = client.put(f"/api/sections/{section['id']}", json={
        "steel_type_tag_id": first_tag["id"],
    })
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["steel_type_tag_id"] == first_tag["id"]
    first_values = client.get(f"/api/pi-tags/{assigned.json()['steel_type_tag_id']}/distinct-values")
    assert first_values.status_code == 200, first_values.text
    assert first_values.json() == ["P304A", "P430A"]

    changed = client.put(f"/api/sections/{section['id']}", json={
        "steel_type_tag_id": second_tag["id"],
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["steel_type_tag_id"] == second_tag["id"]
    second_values = client.get(f"/api/pi-tags/{changed.json()['steel_type_tag_id']}/distinct-values")
    assert second_values.status_code == 200, second_values.text
    assert second_values.json() == ["P399B"]

    reopened = client.get(f"/api/sections/{section['id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["steel_type_tag_id"] == second_tag["id"]
    listed = client.get("/api/sections", params={"equipment_id": equipment["id"]})
    assert listed.status_code == 200, listed.text
    listed_section = next(item for item in listed.json()["items"] if item["id"] == section["id"])
    assert listed_section["steel_type_tag_id"] == second_tag["id"]

    cleared = client.put(f"/api/sections/{section['id']}", json={"steel_type_tag_id": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["steel_type_tag_id"] is None
    assert client.get(f"/api/sections/{section['id']}").json()["steel_type_tag_id"] is None

    legacy = client.post("/api/sections", json={
        "equipment_id": equipment["id"], "code": "STEEL-LEGACY", "name": "Legacy",
    })
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["steel_type_tag_id"] is None


def test_section_accepts_aco_variable_type_as_fixed_steel_tag(client: TestClient) -> None:
    equipment = _create_equipment(client, code="ACO-EQ")
    section = client.post("/api/sections", json={
        "equipment_id": equipment["id"], "code": "FORNO", "name": "Forno",
    }).json()
    variable_type = client.post("/api/variable-types", json={
        "code": "AÇO", "name": "AÇO", "filter_data_type": "STRING",
    }).json()
    tag = client.post("/api/pi-tags", json={
        "equipment_id": equipment["id"], "section_id": None,
        "variable_type_id": variable_type["id"], "pi_server": "PIMS",
        "pi_tag_name": "LFI_RB1_TIPO_ACO", "display_name": "AÇO",
        "data_type": "NON_NUMERIC",
    }).json()

    response = client.put(f"/api/sections/{section['id']}", json={"steel_type_tag_id": tag["id"]})
    assert response.status_code == 200, response.text
    assert response.json()["steel_type_tag_id"] == tag["id"]
    assert client.get(f"/api/sections/{section['id']}").json()["steel_type_tag_id"] == tag["id"]


def test_section_steel_type_tag_rejects_unrelated_variable_type(client: TestClient) -> None:
    equipment = _create_equipment(client, code="STEEL-VALIDATION")
    section = client.post("/api/sections", json={
        "equipment_id": equipment["id"], "code": "SEC", "name": "Section",
    }).json()
    variable_type = client.post("/api/variable-types", json={
        "code": "TEMPERATURE", "name": "Temperatura", "filter_data_type": "REAL",
    }).json()
    tag = client.post("/api/pi-tags", json={
        "equipment_id": equipment["id"], "section_id": section["id"],
        "variable_type_id": variable_type["id"], "pi_server": "PIMS",
        "pi_tag_name": "STEEL.INVALID", "display_name": "Not a steel type",
    }).json()
    response = client.put(f"/api/sections/{section['id']}", json={"steel_type_tag_id": tag["id"]})
    assert response.status_code == 422
