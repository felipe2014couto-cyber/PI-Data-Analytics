"""CSV template, validation, and transactional import for PI tags."""
import csv
import io
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType, PiTagKind, PiTagValidationStatus
from app.models.section import Section
from app.models.variable_type import VariableType
from app.schemas.pi_tag import PiTagCreate
from app.schemas.pi_tag_import import (
    PiTagCsvImportResponse, PiTagCsvRowError, PiTagCsvRowPreview,
    PiTagCsvValidationResponse,
)

COLUMN_MAP = {
    "codigo_equipamento": "equipment_code", "equipment_code": "equipment_code",
    "codigo_secao": "section_code", "section_code": "section_code",
    "codigo_tipo_variavel": "variable_type_code", "variable_type_code": "variable_type_code",
    "tag_pi": "pi_tag_name", "pi_tag_name": "pi_tag_name",
    "nome_amigavel": "display_name", "display_name": "display_name",
    "pi_server": "pi_server", "servidor_pi": "pi_server",
    "tag_limite_inferior": "lower_limit_tag", "lower_limit_tag": "lower_limit_tag",
    "tag_limite_superior": "upper_limit_tag", "upper_limit_tag": "upper_limit_tag",
    "unidade_engenharia": "engineering_unit", "engineering_unit": "engineering_unit",
    "tipo_dado": "data_type", "data_type": "data_type",
    "descricao": "description", "description": "description",
    "ativo": "active", "active": "active",
}
REQUIRED_CANONICAL_COLUMNS = {"equipment_code", "variable_type_code", "pi_tag_name", "display_name"}
PREVIEW_LIMIT = 20
CSV_TEMPLATE_EXAMPLE_MARKER = "\u2063"
DELIMITERS = ((";", "semicolon"), ("\t", "tab"), (",", "comma"), ("|", "pipe"))
ENCODINGS = (("utf-8", "UTF-8"), ("cp1252", "Windows-1252"), ("iso-8859-1", "ISO-8859-1"))


@dataclass
class ParsedCsv:
    headers: list[str]
    rows: list[tuple[int, dict[str, str]]]
    error: str | None
    ignored_example_rows: int = 0
    detected_encoding: str | None = None
    detected_delimiter: str | None = None
    had_bom: bool = False


def is_csv_template_example_row(cells: list[str]) -> bool:
    """Detect the invisible template marker before trimming cell content."""
    return any(CSV_TEMPLATE_EXAMPLE_MARKER in cell for cell in cells)


def csv_template() -> bytes:
    headers = ["codigo_equipamento", "codigo_secao", "codigo_tipo_variavel", "tag_pi", "nome_amigavel", "pi_server", "tag_limite_inferior", "tag_limite_superior", "unidade_engenharia", "tipo_dado", "descricao", "ativo"]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
    writer.writerow(headers)
    # This is a real, already registered development tag. If an editor drops
    # U+2063, normal duplicate validation still prevents importing it.
    writer.writerow([
        "RB3", "FORNO", "TEMPERATURE", "LFI_RB3_TPR_PRMT2",
        "TEMPERATURA TIRA * (PIRÔMETRO 2) - RB3", "PIMS", "", "", "ºC",
        "NUMERIC", f"Pirometro 2{CSV_TEMPLATE_EXAMPLE_MARKER}", "true",
    ])
    return stream.getvalue().encode("utf-8-sig")


def _normalized_header(value: str) -> str:
    return value.strip().lstrip("\ufeff").strip().lower()


def _decode_candidates(content: bytes) -> tuple[list[tuple[str, str]], bool, str | None]:
    if content.startswith(b"\xef\xbb\xbf"):
        try:
            return [("UTF-8 BOM", content.decode("utf-8-sig", errors="strict"))], True, None
        except UnicodeDecodeError:
            return [], True, "Não foi possível identificar a codificação do arquivo."
    if content.startswith(b"\xff\xfe"):
        try:
            return [("UTF-16 LE", content[2:].decode("utf-16-le", errors="strict"))], True, None
        except UnicodeDecodeError:
            return [], True, "Não foi possível identificar a codificação do arquivo."
    if content.startswith(b"\xfe\xff"):
        try:
            return [("UTF-16 BE", content[2:].decode("utf-16-be", errors="strict"))], True, None
        except UnicodeDecodeError:
            return [], True, "Não foi possível identificar a codificação do arquivo."

    decoded: list[tuple[str, str]] = []
    for codec, label in ENCODINGS:
        try:
            text = content.decode(codec, errors="strict")
        except UnicodeDecodeError:
            continue
        # Reject binary/control-heavy payloads for every candidate. Text files
        # may contain horizontal tabs and line endings, which remain permitted.
        if any(
            (ord(char) < 32 and char not in "\r\n\t\f") or 0x7F <= ord(char) <= 0x9F
            for char in text
        ):
            continue
        decoded.append((label, text))
    return decoded, False, None


def _parse_candidate(text: str, delimiter: str) -> tuple[list[str], list[tuple[int, list[str]]], int, str | None]:
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        raw_headers = next(reader, [])
        if not raw_headers:
            return [], [], 0, "header_empty"
        headers = [COLUMN_MAP.get(_normalized_header(value)) for value in raw_headers]
        if any(header is None for header in headers):
            return [], [], 0, "header_unknown"
        duplicates = [name for name, count in Counter(headers).items() if count > 1]
        if duplicates:
            return [], [], 0, "header_duplicate"
        if not REQUIRED_CANONICAL_COLUMNS.issubset(set(headers)):
            return [], [], 0, "header_missing"

        rows: list[tuple[int, list[str]]] = []
        ignored = 0
        for line_number, values in enumerate(reader, start=2):
            if is_csv_template_example_row(values):
                ignored += 1
                continue
            if not any(value.strip() for value in values):
                continue
            if len(values) != len(headers):
                return [], [], ignored, "column_count_more" if len(values) > len(headers) else "column_count_less"
            rows.append((line_number, values))
        return headers, rows, ignored, None
    except csv.Error:
        return [], [], 0, "csv_malformed"


def _parse(content: bytes) -> ParsedCsv:
    if not content or not content.strip():
        return ParsedCsv([], [], "O arquivo está vazio.")
    texts, had_bom, decode_error = _decode_candidates(content)
    if decode_error:
        return ParsedCsv([], [], decode_error, had_bom=had_bom)
    if not texts:
        return ParsedCsv([], [], "Não foi possível identificar a codificação do arquivo.", had_bom=had_bom)

    valid: list[tuple[str, str, list[str], list[tuple[int, list[str]]], int]] = []
    errors: list[str] = []
    for encoding, text in texts:
        for delimiter, delimiter_name in DELIMITERS:
            headers, rows, ignored, error = _parse_candidate(text, delimiter)
            if error is None:
                valid.append((encoding, delimiter_name, headers, rows, ignored))
            else:
                errors.append(error)

    # Encoding candidates are ordered by the documented preference. For the
    # selected encoding, differing structurally valid delimiter parses are unsafe.
    if valid:
        first_encoding = valid[0][0]
        preferred = [candidate for candidate in valid if candidate[0] == first_encoding]
        structures = {(item[1], tuple(item[2]), tuple((n, tuple(v)) for n, v in item[3])) for item in preferred}
        if len(structures) > 1:
            return ParsedCsv([], [], "Não foi possível determinar com segurança o formato do arquivo.", had_bom=had_bom)
        encoding, delimiter, headers, raw_rows, ignored = preferred[0]
        rows = [(line, dict(zip(headers, [value.strip() for value in values]))) for line, values in raw_rows]
        return ParsedCsv(headers, rows, None, ignored, encoding, delimiter, had_bom)

    if "header_duplicate" in errors:
        message = "O cabeçalho contém nomes de colunas duplicados."
    elif "header_missing" in errors:
        message = "Colunas obrigatórias ausentes; o cabeçalho não corresponde ao modelo de importação."
    elif "column_count_more" in errors:
        message = "A linha possui mais colunas do que o cabeçalho. Confira o delimitador e os campos entre aspas."
    elif "column_count_less" in errors:
        message = "Não foi possível identificar as colunas do arquivo. São aceitos CSV separado por ';', ',' ou TAB."
    elif "csv_malformed" in errors:
        message = "O arquivo contém aspas ou campos CSV malformados."
    elif "header_unknown" in errors:
        first_line = texts[0][1].splitlines()[0].lower() if texts[0][1].splitlines() else ""
        recognized_names = sum(1 for name in COLUMN_MAP if name in first_line)
        if recognized_names >= 2:
            message = "Não foi possível identificar as colunas do arquivo. São aceitos CSV separado por ';', ',' ou TAB."
        else:
            message = "O arquivo foi lido corretamente, mas o cabeçalho não corresponde ao modelo de importação."
    else:
        message = "Não foi possível identificar as colunas do arquivo. São aceitos CSV separado por ';', ',' ou TAB."
    return ParsedCsv([], [], message, had_bom=had_bom)


def validate_csv(db: Session, content: bytes) -> tuple[PiTagCsvValidationResponse, list[dict[str, Any]]]:
    parsed = _parse(content)
    if parsed.error:
        error = PiTagCsvRowError(row=1, message=parsed.error)
        return PiTagCsvValidationResponse(valid=False, total_rows=0, valid_count=0, invalid_count=1, ignored_example_rows=0, detected_encoding=parsed.detected_encoding, detected_delimiter=parsed.detected_delimiter, had_bom=parsed.had_bom, errors=[error], preview=[]), []
    rows, ignored_example_rows = parsed.rows, parsed.ignored_example_rows
    if not rows and not ignored_example_rows:
        error = PiTagCsvRowError(row=1, message="O arquivo não contém linhas de dados.")
        return PiTagCsvValidationResponse(valid=False, total_rows=0, valid_count=0, invalid_count=1, ignored_example_rows=0, detected_encoding=parsed.detected_encoding, detected_delimiter=parsed.detected_delimiter, had_bom=parsed.had_bom, errors=[error], preview=[]), []
    equipment_codes = {r.get("equipment_code", "") for _, r in rows if r.get("equipment_code")}
    section_codes = {r.get("section_code", "") for _, r in rows if r.get("section_code")}
    variable_codes = {r.get("variable_type_code", "") for _, r in rows if r.get("variable_type_code")}
    equipments = {x.code: x for x in db.query(Equipment).filter(Equipment.code.in_(equipment_codes)).all()} if equipment_codes else {}
    variables = {x.code: x for x in db.query(VariableType).filter(VariableType.code.in_(variable_codes)).all()} if variable_codes else {}
    sections = db.query(Section).filter(Section.code.in_(section_codes)).all() if section_codes else []
    section_lookup = {(x.equipment_id, x.code): x for x in sections}
    sections_by_code = {x.code for x in sections}
    normalized: list[dict[str, Any]] = []
    errors: list[PiTagCsvRowError] = []
    previews: list[PiTagCsvRowPreview] = []
    seen: dict[tuple[str, str], int] = {}
    for line, raw in rows:
        row_errors: list[PiTagCsvRowError] = []
        def error(column: str, value: str | None, message: str):
            row_errors.append(PiTagCsvRowError(row=line, column=column, value=value, message=message))
        for col in REQUIRED_CANONICAL_COLUMNS:
            if not raw.get(col, "").strip(): error(col, raw.get(col), "Campo obrigatório.")
        if "EXEMPLO_SUBSTITUA_TAG_PI" in raw.get("pi_tag_name", "").upper():
            error("pi_tag_name", raw["pi_tag_name"], "A tag fictícia EXEMPLO_SUBSTITUA_TAG_PI não pode ser importada.")
        equip = equipments.get(raw.get("equipment_code", ""))
        if raw.get("equipment_code") and equip is None: error("equipment_code", raw["equipment_code"], "Equipamento não encontrado.")
        var_type = variables.get(raw.get("variable_type_code", ""))
        if raw.get("variable_type_code") and var_type is None: error("variable_type_code", raw["variable_type_code"], "Tipo de variável não encontrado.")
        section_id = None
        if raw.get("section_code"):
            section_code = raw["section_code"]
            if equip is None:
                error("section_code", section_code, "Seção não pode ser associada sem um equipamento válido.")
            else:
                section = section_lookup.get((equip.id, section_code))
                if section is None:
                    message = "Seção pertence a outro equipamento." if section_code in sections_by_code else "Seção não encontrada para o equipamento informado."
                    error("section_code", section_code, message)
                else:
                    section_id = section.id
        data_type = raw.get("data_type") or PiTagDataType.NUMERIC.value
        if data_type not in {member.value for member in PiTagDataType}: error("data_type", data_type, "Tipo de dado inválido.")
        active_raw = raw.get("active") or "true"
        active_map = {"true": True, "1": True, "sim": True, "yes": True, "false": False, "0": False, "nao": False, "não": False, "no": False}
        if active_raw.lower() not in active_map: error("active", active_raw, "Valor ativo inválido; use true ou false.")
        payload = {
            "equipment_id": equip.id if equip else 1, "section_id": section_id, "variable_type_id": var_type.id if var_type else 1,
            "pi_server": raw.get("pi_server") or "PIMS", "pi_tag_name": raw.get("pi_tag_name", ""),
            "display_name": raw.get("display_name", ""), "lower_limit_tag": raw.get("lower_limit_tag") or None,
            "upper_limit_tag": raw.get("upper_limit_tag") or None, "engineering_unit": raw.get("engineering_unit") or None,
            "description": raw.get("description") or None, "data_type": data_type, "active": active_map.get(active_raw.lower(), True),
        }
        try: PiTagCreate.model_validate(payload)
        except Exception as exc:
            for issue in getattr(exc, "errors", lambda: [])():
                col = issue["loc"][0] if issue.get("loc") else ""
                if col not in {"equipment_id", "variable_type_id", "section_id"}: error(str(col), str(raw.get(str(col), "")), issue["msg"])
        pair = (payload["pi_server"].strip(), payload["pi_tag_name"].strip())
        if payload["pi_tag_name"]:
            if pair in seen: error("pi_tag_name", payload["pi_tag_name"], f"Tag duplicada internamente com a linha {seen[pair]}.")
            else: seen[pair] = line
        normalized.append({"line": line, "payload": payload, "pair": pair})
        errors.extend(row_errors)
        previews.append(PiTagCsvRowPreview(row=line, values=raw, valid=not row_errors))
    pairs = {item["pair"] for item in normalized if item["payload"]["pi_tag_name"]}
    if pairs:
        existing = set(db.query(PiTag.pi_server, PiTag.pi_tag_name).filter(tuple_(PiTag.pi_server, PiTag.pi_tag_name).in_(pairs)).all())
        for item in normalized:
            if item["pair"] in existing:
                errors.append(PiTagCsvRowError(row=item["line"], column="pi_tag_name", value=item["payload"]["pi_tag_name"], message="Já existe uma tag com este nome neste PI Server."))
                for idx, preview in enumerate(previews):
                    if preview.row == item["line"]:
                        previews[idx] = preview.model_copy(update={"valid": False})
                        break
    valid_count = sum(1 for item in normalized if not any(e.row == item["line"] for e in errors))
    response = PiTagCsvValidationResponse(
        valid=not errors, total_rows=len(rows) + ignored_example_rows, valid_count=valid_count,
        invalid_count=len(rows) - valid_count, ignored_example_rows=ignored_example_rows,
        detected_encoding=parsed.detected_encoding, detected_delimiter=parsed.detected_delimiter, had_bom=parsed.had_bom,
        errors=errors, preview=previews[:PREVIEW_LIMIT],
    )
    return response, normalized


def import_csv(db: Session, content: bytes) -> PiTagCsvImportResponse:
    result, normalized = validate_csv(db, content)
    if not result.valid:
        raise ValueError("CSV inválido; corrija todos os erros antes de importar.")
    if not normalized:
        return PiTagCsvImportResponse(imported_count=0, message="Nenhuma tag nova para importar.")
    try:
        for entry in normalized:
            data = PiTagCreate.model_validate(entry["payload"])
            db.add(PiTag(equipment_id=data.equipment_id, section_id=data.section_id, variable_type_id=data.variable_type_id, pi_server=data.pi_server, pi_tag_name=data.pi_tag_name, tag_kind=PiTagKind.PRIMARY, lower_limit_tag=data.lower_limit_tag, upper_limit_tag=data.upper_limit_tag, display_name=data.display_name, description=data.description, engineering_unit=data.engineering_unit, data_type=data.data_type, active=data.active, validation_status=PiTagValidationStatus.PENDING))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return PiTagCsvImportResponse(imported_count=len(normalized), message=f"{len(normalized)} tags PI importadas com sucesso.")
