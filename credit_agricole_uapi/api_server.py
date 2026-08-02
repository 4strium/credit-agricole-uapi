import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from typing import Callable, Literal

from credit_agricole_uapi.fetch import call_ca_client_rest_api

from credit_agricole_uapi.preferences import load_preferences

from credit_agricole_uapi.globals import _reboot_lock

from credit_agricole_uapi.auth import get_local_ip

from pydantic import BaseModel, Field

import urllib.parse

from pathlib import Path

APPROVED_DOC_TYPES = Literal["Relevés", "Contrats", "Autres"]

app = FastAPI(
    title="Crédit Agricole Unofficial API",
    description=(
        "Lightweight and fast unofficial REST/WebSocket-backed API for Crédit Agricole. "
        "It authenticates through the official Crédit Agricole app "
        "session and exposes convenient REST "
        "endpoints on top of Crédit Agricole's private REST and WebSocket APIs.\n\n"
        "All endpoints require that the underlying Crédit Agricole session is "
        "already authenticated (cookies/session established by this server at "
        "startup). No API key is needed to call this local server, but the "
        "server itself must be logged in to Crédit Agricole to answer requests."
    ),
    version="1.0.0",
    contact={"name": "credit-agricole-uapi"},
)

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(exist_ok=True)
app.mount("/exports", StaticFiles(directory=EXPORTS_DIR), name="exports")

class DocumentRequest(BaseModel):
    """Request model for downloading a document by its ID."""

    id: str = Field(
        ...,
        description="The ID of the document to retrieve",
        examples=["12345678"],
    )

class DocumentTypeRequest(BaseModel):
    """Request model for downloading a document by its type."""

    type: APPROVED_DOC_TYPES = Field(
        ...,
        description="The type of the document to retrieve",
        examples=["Relevés"],
    )


def fix_string(text: str) -> str:
    if text is None:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def fix_struct(data):
    if isinstance(data, dict):
        for k, v in data.items():
            data[k] = fix_struct(v)
        return data
    elif isinstance(data, list):
        return [fix_struct(item) for item in data]
    elif isinstance(data, str):
        return fix_string(data)
    else:
        return data


def bank_product_cleaner(data):
    for element in data:
        element.pop("libelle_role_intervenant_contrat", None)
        element.pop("id_parcours", None)
        element.pop("motif_non_valorisation", None)
        element.pop("solde_valeur", None)


def document_attributes_cleaner(data):
    for element in data:
        element.pop("organisme", None)
        element.pop("origine", None)
        element.pop("documentSize", None)
        element.pop("key", None)
        element.pop("idCategorie", None)
        element.pop("idTypeDocument", None)
        element.pop("titulaire", None)

        if element.get("contrat") is not None:
            if (
                element.get("contrat").get("id") == ""
                and element.get("contrat").get("libelle") == ""
            ):
                element.pop("contrat", None)


def regular_get(
    endpoint: str, specific_key: str | None = None, cleaner: Callable | None = None
):
    _reboot_lock.disable_reboot()

    data = call_ca_client_rest_api(endpoint)
    if data is None:
        raise HTTPException(status_code=500, detail="Failed to fetch accounts details")

    if data == {}:
        return []

    if specific_key is not None:
        data = data[specific_key]

    if cleaner is not None:
        cleaner(data)

    _reboot_lock.enable_reboot()
    return data

def document_fetcher(document) :
    Path(f"data/exports/{document['libelleTypeDocument']}").mkdir(parents=True, exist_ok=True)
    
    if document["formatDocument"] == "application/pdf" :
        file_path = Path(f"data/exports/{document['libelleTypeDocument']}/{document['id']}.pdf")
    
        if not file_path.is_file():
            if document['libelleTypeDocument'] == "Relevés":
                fixed_libelle = urllib.parse.quote(document['libelle'] + "_" + document["contrat"]["id"].replace(".", "")).replace("/", "-") + ".pdf"
            else:
                fixed_libelle = urllib.parse.quote(document['libelle'])
            pdf_bytes = regular_get(
                f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/download_document/{fixed_libelle}?document_id={urllib.parse.quote(document['id'])}&key_id={document['key']}&origine={document['origine']}&format={document['formatDocument']}&categorie_id={document['idCategorie']}",
                "data",
            )
    
            if isinstance(
                pdf_bytes, bytes
            ):
                with open(file_path, "wb") as fichier:
                    fichier.write(pdf_bytes)

        return f"http://{get_local_ip()}:{load_preferences().get('api_port')}/exports/{document['libelleTypeDocument']}/{document['id']}.pdf"

@app.get(
    "/api/accounts",
    tags=["Account"],
    summary="Get accounts data",
    description=("Returns the list of the customer's accounts (cash and securities)."),
    response_description="List of accounts.",
)
def get_accounts_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=COMPTES",
        "COMPTES",
        bank_product_cleaner,
    )


@app.get(
    "/api/insurances",
    tags=["Insurance"],
    summary="Get insurance data",
    description=("Returns the list of the customer's insurance data."),
    response_description="List of insurance.",
)
def get_insurance_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=ASSURANCES",
        "ASSURANCES",
        bank_product_cleaner,
    )


@app.get(
    "/api/savings",
    tags=["Savings"],
    summary="Get savings data",
    description=("Returns the list of the customer's savings data."),
    response_description="List of savings.",
)
def get_savings_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=EPARGNE",
        "EPARGNE",
        bank_product_cleaner,
    )


@app.get(
    "/api/loans",
    tags=["Loans"],
    summary="Get loans data",
    description=("Returns the list of the customer's loans data."),
    response_description="List of loans.",
)
def get_loans_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=CREDITS",
        "CREDITS",
        bank_product_cleaner,
    )


@app.get(
    "/api/investments",
    tags=["Investments"],
    summary="Get investments data",
    description=("Returns the list of the customer's investments data."),
    response_description="List of investments.",
)
def get_investments_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=PLACEMENTS",
        "PLACEMENTS",
        bank_product_cleaner,
    )


@app.get(
    "/api/documents-list",
    tags=["Documents"],
    summary="Get documents list",
    description=("Returns the list of the customer's documents."),
    response_description="List of documents.",
)
def get_documents_list():
    return regular_get(
        f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/documents?texte=",
        "listeDocument",
        document_attributes_cleaner,
    )


@app.post(
    "/api/document-by-id",
    tags=["Documents"],
    summary="Download document by its ID.",
    description=("Download a document by its ID."),
    response_description="",
)
def download_document_by_id(params: DocumentRequest):
    documents_list = regular_get(
        f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/documents?texte=",
        "listeDocument",
    )

    for document in documents_list:
        if document["id"] == params.id:
            return {"url": document_fetcher(document)}
    return {}


@app.post(
    "/api/document-by-type",
    tags=["Documents"],
    summary="Download document by its type.",
    description=("Download a document by its type."),
    response_description="",
)
def download_document_by_type(params: DocumentTypeRequest):
    documents_list = regular_get(
        f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/documents?texte=",
        "listeDocument",
    )

    result = []

    for document in documents_list:
        if document["libelleTypeDocument"] == params.type:
            result.append({document["libelle"]: document_fetcher(document)})
    return result


def start_api_server(port):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
