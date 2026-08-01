import uvicorn
from fastapi import FastAPI, HTTPException
from typing import Callable

from credit_agricole_uapi.fetch import call_ca_client_rest_api

from credit_agricole_uapi.globals import _reboot_lock

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
            if element.get("contrat").get("id") == "" and element.get("contrat").get("libelle") == "":
                element.pop("contrat", None)

        

def regular_get(endpoint: str, specific_key: str | None = None, cleaner: Callable | None = None):
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
        "https://hubdocumentaire.credit-agricole.fr/ca-finistere/bff/api/hub/documents?texte=",
        "listeDocument",
        document_attributes_cleaner,
    )


def start_api_server(port):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
