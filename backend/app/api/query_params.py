"""Common query parameters."""
from fastapi import Query


def pagination_params(
    page: int = Query(1, ge=1, description="Numero da pagina."),
    page_size: int = Query(20, ge=1, le=200, description="Tamanho da pagina."),
):
    return {"page": page, "page_size": page_size}
