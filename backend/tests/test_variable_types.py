"""VariableType endpoint tests."""
from fastapi.testclient import TestClient


def _create_variable_type(client: TestClient, code: str = "TEMPERATURE", name: str = "Temperatura") -> dict:
    response = client.post(
        "/api/variable-types",
        json={"code": code, "name": name, "default_unit": "C"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_variable_type(client: TestClient) -> None:
    data = _create_variable_type(client)
    assert data["code"] == "TEMPERATURE"
    assert data["default_unit"] == "C"


def test_duplicate_variable_type_code(client: TestClient) -> None:
    _create_variable_type(client, code="TEMPERATURE")
    response = client.post(
        "/api/variable-types",
        json={"code": "TEMPERATURE", "name": "Outra"},
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
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2
