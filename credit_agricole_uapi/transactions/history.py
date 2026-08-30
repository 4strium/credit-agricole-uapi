from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from credit_agricole_uapi.api_server import (
    app,
    login_subdomain,
    regular_get,
    regular_post,
)
from credit_agricole_uapi.globals import ApiError
from credit_agricole_uapi.preferences import load_preferences
from credit_agricole_uapi.utils.parsers_fetchers import parse_releve


@app.get(
    "/api/past-transactions",
    tags=["Transactions"],
    summary="Retrieve the list of the last year's transactions",
    description=(""),
    response_description="",
)
def get_transactions() -> list[dict[str, Any]] | dict[str, str]:
    if any(
        url.endswith("telechargement-operations")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ):
        context_id = login_subdomain(
            "TELECHARGER-OPERATIONS",
            f"https://telechargement-operations.credit-agricole.fr{load_preferences().get('regional_branch')}bff",
        )

        try:
            contracts = cast(
                list[dict[str, str]],
                regular_get(
                    f"https://telechargement-operations.credit-agricole.fr/ca-finistere/bff/contrats?contextId={context_id}",
                    specific_key="contractElements",
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        accounts_number = [contract.get("accountNumber") for contract in contracts]

        today = datetime.now(tz=ZoneInfo("UTC")).date()

        # Date d'il y a un an
        # Remplacement de l'année pour gérer correctement la même date 1 ans plus tôt
        try:
            one_year_ago = today.replace(year=today.year - 1)
        except ValueError:
            # Gère le cas particulier du 29 février lors d'une année bissextile -> bascule au 28 février
            one_year_ago = today.replace(year=today.year - 1, day=28)

        payload = {
            "contractElements": [
                {
                    "numero_contrat": account,
                    "date_debut_telechargement": one_year_ago.strftime("%Y-%m-%d"),
                    "date_fin_telechargement": today.strftime("%Y-%m-%d"),
                }
                for account in accounts_number
            ],
            "format": "CSV",
            "showValueDate": False,
        }

        try:
            data = cast(
                bytes,
                regular_post(
                    f"https://telechargement-operations.credit-agricole.fr/ca-finistere/bff/generer_document?contextId={context_id}",
                    payload,
                    specific_key="data",
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        parsed_data = parse_releve(data)

        return parsed_data.get("comptes", [])
    else:
        return {"error": "❌ Details of debits/credits submodule not enabled"}
