import uvicorn
from fastapi import FastAPI, HTTPException

from credit_agricole_uapi.fetch import call_ca_client_rest_api


app = FastAPI(
    title="Trade Republic Unofficial API",
    description=(
        "Lightweight and fast unofficial REST/WebSocket-backed API for Trade "
        "Republic. It authenticates through the official Trade Republic app "
        "session and exposes convenient REST "
        "endpoints on top of Trade Republic's private REST and WebSocket APIs.\n\n"
        "All endpoints require that the underlying Trade Republic session is "
        "already authenticated (cookies/session established by this server at "
        "startup). No API key is needed to call this local server, but the "
        "server itself must be logged in to Trade Republic to answer requests."
    ),
    version="1.0.0",
    contact={"name": "trade-republic-uapi"},
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

def clean_response(data):
    for element in data:
        element.pop("libelle_role_intervenant_contrat", None)
        element.pop("id_parcours", None)
        element.pop("motif_non_valorisation", None)
        element.pop("solde_valeur", None)

@app.get(
    "/api/accounts",
    tags=["Account"],
    summary="Get accounts data",
    description=("Returns the list of the customer's accounts (cash and securities)."),
    response_description="List of accounts.",
)
def get_accounts_data():
    accounts = call_ca_client_rest_api(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=COMPTES"
    )
    if accounts is None:
        raise HTTPException(status_code=500, detail="Failed to fetch accounts details")

    if accounts == {}:
        return []

    clean_response(accounts["COMPTES"])

    return accounts["COMPTES"]


@app.get(
    "/api/insurances",
    tags=["Insurance"],
    summary="Get insurance data",
    description=("Returns the list of the customer's insurance data."),
    response_description="List of insurance.",
)
def get_insurance_data():
    insurance = call_ca_client_rest_api(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=ASSURANCES"
    )
    if insurance is None:
        raise HTTPException(status_code=500, detail="Failed to fetch insurance details")

    if insurance == {}:
        return []

    clean_response(insurance["ASSURANCES"])

    return insurance["ASSURANCES"]


@app.get(
    "/api/savings",
    tags=["Savings"],
    summary="Get savings data",
    description=("Returns the list of the customer's savings data."),
    response_description="List of savings.",
)
def get_savings_data():
    savings = call_ca_client_rest_api(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=EPARGNE"
    )
    if savings is None:
        raise HTTPException(status_code=500, detail="Failed to fetch savings details")

    if savings == {}:
        return []

    clean_response(savings["EPARGNE"])

    return savings["EPARGNE"]


@app.get(
    "/api/loans",
    tags=["Loans"],
    summary="Get loans data",
    description=("Returns the list of the customer's loans data."),
    response_description="List of loans.",
)
def get_loans_data():
    loans = call_ca_client_rest_api(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=CREDITS"
    )
    if loans is None:
        raise HTTPException(status_code=500, detail="Failed to fetch loans details")

    if loans == {}:
        return []

    clean_response(loans["CREDITS"])

    return loans["CREDITS"]


@app.get(
    "/api/investments",
    tags=["Investments"],
    summary="Get investments data",
    description=("Returns the list of the customer's investments data."),
    response_description="List of investments.",
)
def get_investments_data():
    investments = call_ca_client_rest_api(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=PLACEMENTS"
    )
    if investments is None:
        raise HTTPException(
            status_code=500, detail="Failed to fetch investments details"
        )

    if investments == {}:
        return []

    clean_response(investments["PLACEMENTS"])

    return investments["PLACEMENTS"]


def start_api_server(port):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
