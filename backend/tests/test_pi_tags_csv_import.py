import csv
import io
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.pi_tag_import import PiTagCsvValidationResponse
from app.services.pi_tag_import_service import csv_template, import_csv


def setup_refs(client: TestClient):
    equipment = client.post("/api/equipments", json={"code": "CSV_EQ", "name": "CSV Equipment"}).json()
    section = client.post("/api/sections", json={"equipment_id": equipment["id"], "code": "S1", "name": "Section"}).json()
    variable = client.post("/api/variable-types", json={"code": "CSV_VAR", "name": "Variable", "filter_data_type": "REAL"}).json()
    return equipment, section, variable


def upload(client, content: bytes, path="/api/pi-tags/import-csv/validate"):
    return client.post(path, files={"file": ("tags.csv", content, "text/csv")})


def test_template_has_utf8_bom_and_expected_delimiter(client):
    response = client.get("/api/pi-tags/csv-template")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert b";" in response.content
    assert b"LFI_RB3_TPR_PRMT2" in response.content
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert 'filename="pi_tags_template.csv"' in response.headers["content-disposition"]


def test_exact_downloaded_template_roundtrips_as_ignored_example(client):
    downloaded = client.get("/api/pi-tags/csv-template")
    raw = downloaded.content

    assert downloaded.status_code == 200
    assert raw == csv_template()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\xef\xbb\xbf") == 1
    assert "Pirometro 2" in raw.decode("utf-8-sig")
    assert "\u2063" in raw.decode("utf-8-sig")
    assert "\u2063".encode("utf-8") in raw
    assert raw.decode("utf-8").startswith("\ufeff")
    assert ";" in raw.decode("utf-8-sig").splitlines()[0]

    # Upload the exact response bytes; do not regenerate or re-encode the file.
    checked = upload(client, raw)
    assert checked.status_code == 200, checked.text
    result = checked.json()
    assert result["valid"] is True
    assert result["total_rows"] == 1
    assert result["valid_count"] == 0
    assert result["invalid_count"] == 0
    assert result["ignored_example_rows"] == 1
    assert result["errors"] == []
    assert result["preview"] == []
    assert result["detected_encoding"] == "UTF-8 BOM"
    assert result["detected_delimiter"] == "semicolon"
    assert result["had_bom"] is True


def test_template_row_is_ignored_alongside_a_valid_utf8_row(client):
    equipment, _, variable = setup_refs(client)
    template = client.get("/api/pi-tags/csv-template").content
    extra = (
        "CSV_EQ;;CSV_VAR;CSV.VALID;Caldeirão;PIMS;;;;NUMERIC;Descrição com acento;true\r\n"
    ).encode("utf-8")
    checked = upload(client, template + extra)

    assert checked.status_code == 200, checked.text
    assert checked.json()["valid"] is True
    assert checked.json()["valid_count"] == 1
    assert checked.json()["invalid_count"] == 0
    assert checked.json()["ignored_example_rows"] == 1
    assert checked.json()["preview"][0]["values"]["display_name"] == "Caldeirão"


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_utf8_with_and_without_bom_is_accepted(client, bom):
    equipment, _, variable = setup_refs(client)
    data = (
        "equipment_code;variable_type_code;pi_tag_name;display_name\r\n"
        f"{equipment['code']};{variable['code']};UTF8.TAG;Pressão\r\n"
    ).encode("utf-8")
    checked = upload(client, bom + data)
    assert checked.status_code == 200
    assert checked.json()["valid"] is True
    assert checked.json()["preview"][0]["values"]["display_name"] == "Pressão"
    assert checked.json()["detected_encoding"] == ("UTF-8 BOM" if bom else "UTF-8")


def test_cp1252_is_accepted_without_replacement_when_utf8_is_invalid(client):
    equipment, _, variable = setup_refs(client)
    data = f"equipment_code;variable_type_code;pi_tag_name;display_name\n{equipment['code']};{variable['code']};CP1252.TAG;bad-ÿ\n".encode("cp1252")
    checked = upload(client, data)
    assert checked.status_code == 200
    assert checked.json()["valid"] is True
    assert checked.json()["detected_encoding"] == "Windows-1252"
    assert checked.json()["preview"][0]["values"]["display_name"] == "bad-ÿ"
    assert "�" not in str(checked.json())


def test_template_example_tag_is_rejected(client):
    equipment, _, variable = setup_refs(client)
    data = (
        "equipment_code;variable_type_code;pi_tag_name;display_name\n"
        f"{equipment['code']};{variable['code']};EXEMPLO_SUBSTITUA_TAG_PI;Exemplo\n"
    ).encode()
    response = upload(client, data)
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert any("EXEMPLO_SUBSTITUA_TAG_PI" in issue["message"] for issue in response.json()["errors"])

def test_validate_accepts_comma_and_semicolon_and_imports_multiple_rows(client):
    equipment, _, variable = setup_refs(client)
    for delimiter, tag in [(";", "CSV.TAG.1"), (",", "CSV.TAG.2")]:
        data = (f"equipment_code{delimiter}variable_type_code{delimiter}pi_tag_name{delimiter}display_name\n"
                f"{equipment['code']}{delimiter}{variable['code']}{delimiter}{tag}{delimiter}Tag\n").encode()
        checked = upload(client, data)
        assert checked.status_code == 200, checked.text
        assert checked.json()["valid"] is True
        imported = upload(client, data, "/api/pi-tags/import-csv")
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_count"] == 1
    assert client.get("/api/pi-tags", params={"search": "CSV.TAG"}).json()["total"] == 2


def test_empty_file_bad_headers_relations_enum_and_atomicity(client):
    equipment, _, variable = setup_refs(client)
    assert upload(client, b"").json()["valid"] is False
    assert upload(client, b"unknown\nvalue\n").json()["valid"] is False
    data = ("equipment_code;variable_type_code;pi_tag_name;display_name;section_code;data_type\n"
            f"{equipment['code']};{variable['code']};ATOMIC.OK;OK;;NUMERIC\n"
            f"{equipment['code']};{variable['code']};ATOMIC.BAD;BAD;MISSING;NOPE\n").encode()
    checked = upload(client, data)
    assert checked.status_code == 200
    assert checked.json()["valid"] is False
    result = upload(client, data, "/api/pi-tags/import-csv")
    assert result.status_code == 422
    assert client.get("/api/pi-tags", params={"search": "ATOMIC"}).json()["total"] == 0


def test_duplicate_database_and_internal_rows_are_reported(client):
    equipment, _, variable = setup_refs(client)
    initial = ("equipment_code;variable_type_code;pi_tag_name;display_name\n"
               f"{equipment['code']};{variable['code']};DUP.TAG;Duplicate\n").encode()
    assert upload(client, initial, "/api/pi-tags/import-csv").status_code == 200
    existing = upload(client, initial).json()
    assert any("existe" in issue["message"] for issue in existing["errors"])
    repeated = ("equipment_code;variable_type_code;pi_tag_name;display_name\n"
                f"{equipment['code']};{variable['code']};INTERNAL.DUP;A\n"
                f"{equipment['code']};{variable['code']};INTERNAL.DUP;B\n").encode()
    checked = upload(client, repeated).json()
    assert any("internamente" in issue["message"] for issue in checked["errors"])


def test_missing_required_column_in_header(client):
    response = upload(client, b"equipment_code;variable_type_code;pi_tag_name\nEQ;VAR;TAG\n")
    assert response.json()["valid"] is False
    assert response.json()["invalid_count"] == 1
    assert any("Colunas obrigatórias ausentes" in error["message"] for error in response.json()["errors"])


def test_row_with_extra_columns_is_rejected(client):
    equipment, _, variable = setup_refs(client)
    data = ("equipment_code;variable_type_code;pi_tag_name;display_name\n"
            f"{equipment['code']};{variable['code']};TAG.EXTRA;Display;EXTRA_FIELD\n").encode()
    response = upload(client, data)
    assert response.json()["valid"] is False
    assert any("mais colunas" in error["message"] for error in response.json()["errors"])


def test_multiple_valid_rows_imported_in_single_call(client):
    equipment, _, variable = setup_refs(client)
    data = ("equipment_code;variable_type_code;pi_tag_name;display_name\n"
            f"{equipment['code']};{variable['code']};MULTI.1;Multi 1\n"
            f"{equipment['code']};{variable['code']};MULTI.2;Multi 2\n"
            f"{equipment['code']};{variable['code']};MULTI.3;Multi 3\n").encode()
    response = upload(client, data, "/api/pi-tags/import-csv")
    assert response.status_code == 200
    assert response.json()["imported_count"] == 3
    assert client.get("/api/pi-tags", params={"search": "MULTI"}).json()["total"] == 3


def test_import_csv_rolls_back_on_unexpected_commit_error():
    db = Mock()
    db.commit.side_effect = RuntimeError("Simulated DB Crash")
    valid = PiTagCsvValidationResponse(
        valid=True, total_rows=1, valid_count=1, invalid_count=0, errors=[], preview=[]
    )
    normalized = [{"payload": {
        "equipment_id": 1, "section_id": None, "variable_type_id": 1,
        "pi_server": "PIMS", "pi_tag_name": "ROLLBACK.TAG", "display_name": "Rollback",
        "lower_limit_tag": None, "upper_limit_tag": None, "engineering_unit": None,
        "description": None, "data_type": "NUMERIC", "active": True,
    }}]
    with patch("app.services.pi_tag_import_service.validate_csv", return_value=(valid, normalized)):
        try:
            import_csv(db, b"header")
        except RuntimeError as exc:
            assert str(exc) == "Simulated DB Crash"
        else:
            raise AssertionError("Expected commit failure")
    db.rollback.assert_called_once_with()


def test_file_size_limit_and_extension_rejected(client):
    extension_response = client.post(
        "/api/pi-tags/import-csv/validate",
        files={"file": ("tags.xlsx", b"dummy", "application/octet-stream")},
    )
    assert extension_response.status_code == 400

    oversized = b"a" * (5 * 1024 * 1024 + 10)
    size_response = upload(client, oversized)
    assert size_response.status_code == 413


@pytest.mark.parametrize("encoding,delimiter,expected_encoding,expected_delimiter", [
    ("utf-8", "\t", "UTF-8", "tab"),
    ("utf-8", ",", "UTF-8", "comma"),
    ("cp1252", ";", "Windows-1252", "semicolon"),
    ("cp1252", "\t", "Windows-1252", "tab"),
    ("cp1252", ",", "Windows-1252", "comma"),
    ("iso-8859-1", ";", "Windows-1252", "semicolon"),
])
def test_detects_supported_encodings_and_delimiters(client, encoding, delimiter, expected_encoding, expected_delimiter):
    equipment, _, variable = setup_refs(client)
    content = (
        f"equipment_code{delimiter}variable_type_code{delimiter}pi_tag_name{delimiter}display_name{delimiter}description\r\n"
        f"{equipment['code']}{delimiter}{variable['code']}{delimiter}FORMAT.TAG{delimiter}Ação ÇÃ É{delimiter}Descrição\r\n"
    ).encode(encoding)
    result = upload(client, content).json()
    assert result["valid"] is True, result
    assert result["valid_count"] == 1
    assert result["preview"][0]["values"]["display_name"] == "Ação ÇÃ É"
    assert result["preview"][0]["values"]["description"] == "Descrição"
    assert result["detected_encoding"] == expected_encoding
    assert result["detected_delimiter"] == expected_delimiter


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_detects_excel_unicode_text_utf16_with_tab(client, encoding):
    equipment, _, variable = setup_refs(client)
    text = (
        "equipment_code\tvariable_type_code\tpi_tag_name\tdisplay_name\r\n"
        f"{equipment['code']}\t{variable['code']}\tUTF16.TAG\tPressão Ç\r\n"
    )
    bom = b"\xff\xfe" if encoding.endswith("le") else b"\xfe\xff"
    result = upload(client, bom + text.encode(encoding)).json()
    assert result["valid"] is True, result
    assert result["preview"][0]["values"]["display_name"] == "Pressão Ç"
    assert result["detected_encoding"] == ("UTF-16 LE" if encoding.endswith("le") else "UTF-16 BE")
    assert result["detected_delimiter"] == "tab"
    assert result["had_bom"] is True


def test_quoted_delimiters_are_parsed_without_splitting_fields(client):
    equipment, _, variable = setup_refs(client)
    text = (
        'equipment_code;variable_type_code;pi_tag_name;display_name;description\n'
        f'{equipment["code"]};{variable["code"]};QUOTE.SEMI;"Tag; com separador";"Texto com, vírgula e ""aspas"""\n'
    )
    result = upload(client, text.encode("utf-8")).json()
    assert result["valid"] is True, result
    assert result["preview"][0]["values"]["display_name"] == "Tag; com separador"
    assert result["preview"][0]["values"]["description"] == 'Texto com, vírgula e "aspas"'

    comma_text = (
        'equipment_code,variable_type_code,pi_tag_name,display_name,description\n'
        f'{equipment["code"]},{variable["code"]},QUOTE.COMMA,"Tag, com vírgula","Texto; com ponto e vírgula"\n'
    )
    comma_result = upload(client, comma_text.encode("utf-8")).json()
    assert comma_result["valid"] is True, comma_result
    assert comma_result["detected_delimiter"] == "comma"
    assert comma_result["preview"][0]["values"]["display_name"] == "Tag, com vírgula"
    assert comma_result["preview"][0]["values"]["description"] == "Texto; com ponto e vírgula"


def test_invalid_binary_and_bad_header_return_structural_errors(client):
    binary = upload(client, b"\x00\x01\x02\xff\x00")
    assert "codificação" in binary.json()["errors"][0]["message"] or "colunas" in binary.json()["errors"][0]["message"]
    header = upload(client, b"coluna_errada;outra\nvalor;valor\n")
    assert "cabeçalho" in header.json()["errors"][0]["message"]
    delimiter = upload(client, b"equipment_code:variable_type_code:pi_tag_name:display_name\nEQ:VAR:TAG:Nome\n")
    assert "identificar as colunas" in delimiter.json()["errors"][0]["message"]


def test_txt_extension_and_unusual_mime_are_accepted(client):
    equipment, _, variable = setup_refs(client)
    content = f"equipment_code\tvariable_type_code\tpi_tag_name\tdisplay_name\n{equipment['code']}\t{variable['code']}\tTXT.TAG\tTexto\n".encode()
    response = client.post("/api/pi-tags/import-csv/validate", files={"file": ("tags.txt", content, "application/octet-stream")})
    assert response.status_code == 200, response.text
    assert response.json()["valid_count"] == 1


def test_utf16_template_roundtrip_keeps_example_marker(client):
    raw = csv_template().decode("utf-8-sig").encode("utf-16-le")
    result = upload(client, b"\xff\xfe" + raw).json()
    assert result["valid"] is True, result
    assert result["ignored_example_rows"] == 1
    assert result["valid_count"] == 0
    assert result["invalid_count"] == 0


def test_pipe_delimiter_is_accepted_only_when_structure_is_clear(client):
    equipment, _, variable = setup_refs(client)
    content = f"equipment_code|variable_type_code|pi_tag_name|display_name\n{equipment['code']}|{variable['code']}|PIPE.TAG|Pipe\n".encode()
    result = upload(client, content).json()
    assert result["valid"] is True, result
    assert result["detected_delimiter"] == "pipe"


def test_cp1252_tab_template_without_marker_is_rejected_as_real_duplicate(client):
    equipment = client.post("/api/equipments", json={"code": "RB3", "name": "RB3"}).json()
    section = client.post("/api/sections", json={"equipment_id": equipment["id"], "code": "FORNO", "name": "Forno"}).json()
    variable = client.post("/api/variable-types", json={"code": "TEMPERATURE", "name": "Temperature", "filter_data_type": "REAL"}).json()
    created = client.post("/api/pi-tags", json={
        "equipment_id": equipment["id"], "section_id": section["id"], "variable_type_id": variable["id"],
        "pi_server": "PIMS", "pi_tag_name": "LFI_RB3_TPR_PRMT2", "display_name": "TEMPERATURA TIRA * (PIRÔMETRO 2) - RB3",
        "description": "Pirometro 2", "engineering_unit": "ºC", "data_type": "NUMERIC", "active": True,
    })
    assert created.status_code == 201, created.text

    template_rows = list(csv.reader(io.StringIO(client.get("/api/pi-tags/csv-template").content.decode("utf-8-sig")), delimiter=";"))
    template_rows[1][10] = template_rows[1][10].replace("\u2063", "")
    text = io.StringIO(newline="")
    csv.writer(text, delimiter="\t", lineterminator="\r\n").writerows(template_rows)
    excel_bytes = text.getvalue().encode("cp1252")
    result = upload(client, excel_bytes).json()
    assert result["detected_encoding"] == "Windows-1252"
    assert result["detected_delimiter"] == "tab"
    assert result["ignored_example_rows"] == 0
    assert result["valid_count"] == 0
    assert result["invalid_count"] == 1
    assert any("existe" in item["message"] for item in result["errors"])
