"""VariableType endpoint tests."""
from fastapi.testclient import TestClient


def _create_variable_type(
    client: TestClient,
    code: str = "TEMPERATURE",
    name: str = "Temperatura",
    filter_data_type: str = "REAL",
) -> dict:
    response = client.post(
        "/api/variable-types",
        json={"code": code, "name": name, "default_unit": "C", "filter_data_type": filter_data_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_variable_type(client: TestClient) -> None:
    data = _create_variable_type(client)
    assert data["code"] == "TEMPERATURE"
    assert data["default_unit"] == "C"
    assert data["filter_data_type"] == "REAL"


def test_create_variable_type_all_valid_filter_types(client: TestClient) -> None:
    real = _create_variable_type(client, code="CURRENT", name="Corrente", filter_data_type="REAL")
    assert real["filter_data_type"] == "REAL"

    string = _create_variable_type(client, code="STEEL_MODEL", name="Modelo", filter_data_type="STRING")
    assert string["filter_data_type"] == "STRING"

    digital = _create_variable_type(client, code="MOTOR_ON", name="Motor", filter_data_type="DIGITAL")
    assert digital["filter_data_type"] == "DIGITAL"


def test_create_variable_type_rejects_invalid_filter_type(client: TestClient) -> None:
    response = client.post(
        "/api/variable-types",
        json={"code": "INVALID_TYPE", "name": "Invalido", "filter_data_type": "UNKNOWN"},
    )
    assert response.status_code == 422


def test_update_variable_type_filter_data_type(client: TestClient) -> None:
    data = _create_variable_type(client, code="TEST_UPDATE", name="Original", filter_data_type="REAL")
    assert data["filter_data_type"] == "REAL"

    response = client.put(
        f"/api/variable-types/{data['id']}",
        json={"filter_data_type": "STRING"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["filter_data_type"] == "STRING"


def test_duplicate_variable_type_code(client: TestClient) -> None:
    _create_variable_type(client, code="TEMPERATURE_DUP")
    response = client.post(
        "/api/variable-types",
        json={"code": "TEMPERATURE_DUP", "name": "Outra", "filter_data_type": "REAL"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "DUPLICATE_CODE"


def test_variable_type_code_normalization(client: TestClient) -> None:
    data = _create_variable_type(client, code="  speed  ", name="Velocidade")
    assert data["code"] == "SPEED"


def test_list_variable_types_pagination(client: TestClient) -> None:
    for i in range(3):
        _create_variable_type(client, code=f"VT{i}", name=f"VT {i}")
    response = client.get("/api/variable-types", params={"page": 1, "page_size": 2})
    body = response.json()
    assert body["total"] >= 3
    assert body["pages"] >= 2
    assert len(body["items"]) == 2
    assert "filter_data_type" in body["items"][0]
