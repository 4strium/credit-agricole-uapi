from typing import Any, cast

from credit_agricole_uapi.api_server import app, regular_get
from credit_agricole_uapi.preferences import load_preferences
from credit_agricole_uapi.utils.cleaners import document_attributes_cleaner
from credit_agricole_uapi.utils.models import (
    DocumentDownloadResult,
    DocumentRequest,
    DocumentResponse,
    DocumentsDownloadList,
    DocumentTypeRequest,
)
from credit_agricole_uapi.utils.parsers_fetchers import document_fetcher


@app.get(
    "/api/documents-list",
    tags=["Documents"],
    summary="Get documents list",
    description=("Returns the list of the customer's documents."),
    response_description="List of documents.",
    response_model=list[DocumentResponse],
)
def get_documents_list():
    if any(
        url.endswith("mes-documents")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ):
        return regular_get(
            f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/documents?texte=",
            "listeDocument",
            document_attributes_cleaner,
        )
    else:
        return {"error": "❌ Documents submodule not enabled"}


@app.post(
    "/api/document-by-id",
    tags=["Documents"],
    summary="Download document by its ID.",
    description=("Download a document by its ID."),
    response_description="",
    response_model=DocumentDownloadResult,
)
def download_document_by_id(params: DocumentRequest) -> dict[str, str]:
    if any(
        url.endswith("mes-documents")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ):
        documents_list = cast(
            list[dict[str, Any]],
            regular_get(
                f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/documents?texte=",
                "listeDocument",
            ),
        )

        for document in documents_list:
            if document["id"] == params.id:
                return {"url": document_fetcher(document)}
        return {}
    else:
        return {"error": "❌ Documents submodule not enabled"}


@app.post(
    "/api/documents-by-type",
    tags=["Documents"],
    summary="Download several documents by their type.",
    description=("Download several documents by their type."),
    response_description="",
    response_model=DocumentsDownloadList,
)
def download_document_by_type(
    params: DocumentTypeRequest,
) -> list[dict[str, str]] | dict[str, str]:
    if any(
        url.endswith("mes-documents")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ):
        documents_list = cast(
            list[dict[str, Any]],
            regular_get(
                f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/documents?texte=",
                "listeDocument",
            ),
        )

        result: list[dict[str, Any]] = []

        for document in documents_list:
            if document["libelleTypeDocument"] == params.type:
                result.append({document["libelle"]: document_fetcher(document)})
        return result
    else:
        return {"error": "❌ Documents submodule not enabled"}
