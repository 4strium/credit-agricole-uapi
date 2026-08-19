import csv
import io
import os
import re
import secrets
import time
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from credit_agricole_uapi.auth import get_local_ip
from credit_agricole_uapi.fetch import call_ca_client_rest_api, post_ca_client_rest_api
from credit_agricole_uapi.globals import reboot_lock
from credit_agricole_uapi.models import (
    AddBeneficiaryRequest,
    DocumentDownloadResult,
    DocumentRequest,
    DocumentResponse,
    DocumentsDownloadList,
    DocumentTypeRequest,
    GenericAccountResponse,
    TransactionParams,
)
from credit_agricole_uapi.preferences import load_preferences

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def verify_api_key(api_key: str = Depends(api_key_header)) -> str:
    expected_key = os.getenv("CA_UAPI_KEY")

    if not expected_key or not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing or invalid",
        )

    if not secrets.compare_digest(api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing or invalid",
        )

    return api_key


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
    version="0.1.1",
    contact={"name": "credit-agricole-uapi"},
    dependencies=[Depends(verify_api_key)],
)
app.mount("/exports", StaticFiles(directory=EXPORTS_DIR), name="exports")


def fix_string(text: str) -> str:
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def fix_struct(
    data: dict[str, Any] | list[Any] | str | None,
) -> dict[str, Any] | list[Any] | str | None:
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


def _to_float(value: str | None) -> float | None:
    if not value or not value.strip():
        return None
    return float(value.replace("\xa0", " ").replace(" ", "").replace(",", "."))


def _clean_libelle(libelle: str) -> str:
    lines = [l.strip() for l in libelle.split("\n") if l.strip()]
    return " - ".join(lines)


def parse_releve(raw: bytes, encoding: str = "cp1252") -> dict[str, Any]:
    text = raw.decode(encoding)
    result: dict[str, Any] = {"titulaire": None, "date_extraction": None, "comptes": []}
    compte_courant: dict[str, Any] | None = None
    pending_nom_carte = None

    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if not row or all(not f.strip() for f in row):
            continue
        first = row[0].strip()

        if m := re.match(r"Téléchargement du (\d{2}/\d{2}/\d{4})", first):
            result["date_extraction"] = m.group(1)
        elif re.match(r"^M\.?\s+", first) and "carte" not in first.lower():
            result["titulaire"] = re.sub(r"\s+", " ", first).strip()
        elif m := re.match(r"(.+?)\s*carte\s*n[°o]\s*(\d+)", first):
            pending_nom_carte = (m.group(1).strip(), m.group(2).strip())
        elif m := re.match(r"Solde au (\d{2}/\d{2}/\d{4})\s+([\d\s]+,\d{2})", first):
            nom, carte = pending_nom_carte or (None, None)
            compte_courant = {
                "nom": nom,
                "numero_carte": carte,
                "solde_date": m.group(1),
                "solde": _to_float(m.group(2)),
                "operations": [],
            }
            result["comptes"].append(compte_courant)
        elif re.match(r"^\d{2}/\d{2}/\d{4}$", first) and compte_courant:
            compte_courant["operations"].append(
                {
                    "date": first,
                    "libelle": _clean_libelle(row[1]) if len(row) > 1 else "",
                    "debit": _to_float(row[2]) if len(row) > 2 else None,
                    "credit": _to_float(row[3]) if len(row) > 3 else None,
                }
            )

    return result


def bank_product_cleaner(data: list[dict[str, Any]]) -> None:
    for element in data:
        element.pop("libelle_role_intervenant_contrat", None)
        element.pop("id_parcours", None)
        element.pop("motif_non_valorisation", None)
        element.pop("solde_valeur", None)
        element.pop("code_role_intervenant_contrat", None)
        element.pop("categorie_etablissement", None)
        element.pop("position", None)


def document_attributes_cleaner(data: list[dict[str, Any]]) -> None:
    for element in data:
        element.pop("organisme", None)
        element.pop("origine", None)
        element.pop("documentSize", None)
        element.pop("key", None)
        element.pop("idCategorie", None)
        element.pop("idTypeDocument", None)
        element.pop("titulaire", None)

        contrat = cast(dict[str, Any] | None, element.get("contrat"))

        if (
            contrat is not None
            and contrat.get("id") == ""
            and contrat.get("libelle") == ""
        ):
            element.pop("contrat", None)


def beneficiary_cleaner(data: list[dict[str, Any]]) -> None:
    for element in data:
        element.pop("delay", None)
        element.pop("custom_label", None)


def regular_get(
    endpoint: str,
    specific_key: str | None = None,
    cleaner: Callable[[Any], Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | list[Any] | str:
    reboot_lock.disable_reboot()

    data = call_ca_client_rest_api(endpoint, extra_headers)
    if data is None:
        raise HTTPException(status_code=500, detail="Failed to call CA client REST API")

    if data == {}:
        return []

    if specific_key is not None:
        data = data[specific_key]

    if cleaner is not None:
        cleaner(data)

    reboot_lock.enable_reboot()
    return data


def regular_post(
    endpoint: str,
    json_data: dict[str, Any] | list[Any] | None = None,
    specific_key: str | None = None,
    cleaner: Callable[[Any], Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | list[Any] | str | int | bytes:
    reboot_lock.disable_reboot()

    data = post_ca_client_rest_api(endpoint, json_data, extra_headers)
    if data is None:
        raise HTTPException(status_code=500, detail="Failed to call CA client REST API")

    if data == {}:
        return []

    if specific_key is not None:
        data = data[specific_key]

    if cleaner is not None:
        cleaner(data)

    reboot_lock.enable_reboot()
    return data


def document_fetcher(document: dict[str, Any]) -> str:
    Path(f"data/exports/{document['libelleTypeDocument']}").mkdir(
        parents=True, exist_ok=True
    )

    if document["formatDocument"] == "application/pdf":
        file_path = Path(
            f"data/exports/{document['libelleTypeDocument']}/{document['id']}.pdf"
        )

        if not file_path.is_file():
            if document["libelleTypeDocument"] == "Relevés":
                fixed_libelle = (
                    urllib.parse.quote(
                        document["libelle"]
                        + "_"
                        + document["contrat"]["id"].replace(".", "")
                    ).replace("/", "-")
                    + ".pdf"
                )
            else:
                fixed_libelle = urllib.parse.quote(document["libelle"])
            pdf_bytes = regular_get(
                f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/download_document/{fixed_libelle}?document_id={urllib.parse.quote(document['id'])}&key_id={document['key']}&origine={document['origine']}&format={document['formatDocument']}&categorie_id={document['idCategorie']}",
                "data",
            )

            if isinstance(pdf_bytes, bytes):
                with open(file_path, "wb") as fichier:
                    _ = fichier.write(pdf_bytes)

        return f"http://{get_local_ip()}:{load_preferences().get('api_port')}/exports/{document['libelleTypeDocument']}/{document['id']}.pdf"

    return ""


def _login_subdomain(id: str, subdomain: str) -> str:
    encrypted_token = cast(
        dict[str, str | int],
        regular_post(
            "https://espace-client.credit-agricole.fr/bff/api/context/sso/v2",
            {"id_parcours": id},
            "context_token",
        ),
    )["encrypted_token"]

    context_id = cast(
        dict[str, str],
        regular_post(
            f"{subdomain}/customer/login",
            {"token": encrypted_token},
        ),
    )["contextId"]

    return context_id


@app.get(
    "/api/accounts",
    tags=["Account"],
    summary="Get accounts data",
    description=("Returns the list of the customer's accounts (cash and securities)."),
    response_description="List of accounts.",
    response_model=list[GenericAccountResponse],
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
    response_model=list[GenericAccountResponse],
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
    "/api/transaction-accounts",
    tags=["Transactions"],
    summary="Get transaction accounts",
    description=("Returns the list of the customer's transaction accounts."),
    response_description="",
)
def get_transaction_enabled_accounts() -> dict[str, Any]:
    if any(
        url.endswith("virement-unitaire")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ):
        _ = _login_subdomain(
            "VIREMENT-UNITAIRE",
            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir",
        )

        res: dict[str, Any] = {}

        res["internal"] = cast(
            list[dict[str, Any]],
            regular_get(
                f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/comptes",
                "my_accounts",
            ),
        )[0]["accounts"]

        res["external"] = regular_get(
            f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries",
            "beneficiaries",
            beneficiary_cleaner,
        )

        return res
    else:
        return {"error": "❌ Transaction submodule not enabled"}


@app.post(
    "/api/transaction",
    tags=["Transactions"],
    summary="Carry out transaction",
    description=("Perform a transaction."),
    response_description="",
)
def carry_out_transaction(params: TransactionParams) -> dict[str, str]:
    if any(
        url.endswith("virement-unitaire")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ) and cast(bool, load_preferences().get("active_commands", [])):
        if params.source_account_iban == params.recipient_account_iban:
            raise HTTPException(
                status_code=400,
                detail="Source and recipient account cannot be the same",
            )

        context_id = _login_subdomain(
            "VIREMENT-UNITAIRE",
            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir",
        )

        transfer_infos = cast(
            dict[str, Any],
            regular_get(
                f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/comptes",
            ),
        )

        transfer_flow_id = cast(str, transfer_infos["transfer_flow_id"])
        internal_accounts = cast(
            list[dict[str, Any]], transfer_infos["my_accounts"][0]["accounts"]
        )
        external_accounts = cast(
            list[dict[str, Any]],
            regular_get(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries",
                "beneficiaries",
            ),
        )

        source_account_data = {}
        recipient_account_data = {}

        for internal_account in internal_accounts:
            if internal_account["iban"] == params.source_account_iban:
                source_account_data = internal_account
            elif internal_account["iban"] == params.recipient_account_iban:
                recipient_account_data = {"internal": internal_account}

        for external_account in external_accounts:
            if external_account["iban"] == params.recipient_account_iban:
                recipient_account_data = {"external": external_account}

        if source_account_data == {} or recipient_account_data == {}:
            raise HTTPException(
                status_code=404, detail="Source or recipient account not found"
            )

        transaction_package = {
            "virement": {
                "transfer_flow_id": transfer_flow_id,
                "source_account": source_account_data,
                "recipient_account": recipient_account_data,
                "date": time.time_ns() // 1_000_000,
                "amount": str(round(params.amount, 2)),
                "motif": params.motif,
                "additional_motif": params.additional_motif,
                "transfer_frequency_code": "U",
                "end_due_date": 0,
            }
        }

        confirm_transfer_flow_id = cast(
            str,
            regular_post(
                f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/controle-virement?contextId={context_id}",
                transaction_package,
                "transfer_flow_id",
            ),
        )

        _ = regular_post(
            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/creation-virement",
            {"transfer_flow_id": confirm_transfer_flow_id},
        )

        return {"Result": "✅ Transaction carried out successfully"}
    else:
        return {"error": "❌ Transaction submodule not enabled"}


@app.post(
    "/api/add-beneficiary",
    tags=["Beneficiaries"],
    summary="Add a beneficiary.",
    description=("Add a beneficiary to the user's account."),
    response_description="",
)
def add_beneficiary(params: AddBeneficiaryRequest) -> dict[str, str]:
    if any(
        url.endswith("gestion-beneficiaires")
        for url in cast(str, load_preferences().get("active_subdomains_urls", []))
    ):
        context_id = _login_subdomain(
            "GESTION-BENEFICIAIRES",
            f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf",
        )

        benef_bank_infos = cast(
            dict[str, Any],
            regular_post(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries/check?contextId={context_id}",
                {"iban": params.iban},
            ),
        )

        vop_infos = cast(
            dict[str, Any],
            regular_post(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/vop",
                {
                    "bic_entity": benef_bank_infos.get("bic"),
                    "iban_payee": params.iban,
                    "identifier_value": params.name,
                    "type_of_use": "AUTR",
                },
            ),
        )

        if vop_infos.get("vop_result") != "MTCH":
            raise HTTPException(
                status_code=400,
                detail="We did not find the account corresponding to the provided IBAN and name.",
            )

        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        auth_by_factor_id = cast(
            dict[str, str],
            regular_post(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/customer/authentication/factors/settings",  # Trigger SecuriPass
                {
                    "templateSecuripass": {
                        "donnees_usage": {
                            "titre": "AF_AJ_BNF",
                            "sous_titre": "Confirmer l'ajout du bénéficiaire",
                            "detail_operation": [
                                {"libelle": "beneficiary_name", "texte": params.name},
                                {
                                    "libelle": "beneficiary_custom_label",
                                    "texte": params.identifier,
                                },
                                {
                                    "libelle": "beneficiary_account",
                                    "texte": params.iban,
                                },
                                {
                                    "libelle": "beneficiary_bank",
                                    "texte": benef_bank_infos.get("bank_label"),
                                },
                                {"libelle": "beneficiary_country", "texte": ""},
                                {"libelle": "Date_ISO_8601", "texte": date},
                                {"libelle": "vop_result", "texte": "MTCH"},
                            ],
                        }
                    },
                    "authUsage": "U001",
                    "champDescriptionLibreSecuripass": f"IBAN : {params.iban} / Nom réglementaire : {params.name} / Libellé personnalisé : {params.identifier} /  Résultat vop : Le nom correspond à l’IBAN",
                },
            ),
        )

        auth_method = cast(
            str,
            regular_get(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/customer/authentication/factors/active",
                "method",
                extra_headers=auth_by_factor_id,
            ),
        )

        _ = regular_get(
            f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/customer/authentication/factors/{auth_method}/request",
            extra_headers=auth_by_factor_id,
        )

        fst_ask_time = time.time()
        while True:
            if time.time() - fst_ask_time > 60:
                raise HTTPException(
                    status_code=504,
                    detail="The authentication request via your phone has expired.",
                )

            status_code = cast(
                int,
                regular_post(
                    f"https://beneficiaire-npc-unitaire.credit-agricole.fr/{load_preferences().get('regional_branch')}/bffgbnf/customer/authentication/factors/{auth_method}/validation",
                    specific_key="status",
                    extra_headers=auth_by_factor_id,
                ),
            )

            if status_code == 200:
                break

            time.sleep(4)

        new_beneficiary = cast(
            dict[str, Any],
            regular_post(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries",
                {
                    "name": params.name,
                    "beneficiary_flow_id": benef_bank_infos.get("beneficiary_flow_id"),
                    "custom_label": params.identifier,
                    "id_vop": vop_infos.get("vop_entity_id"),
                },
                extra_headers=auth_by_factor_id,
            ),
        )

        activation_date_utc = datetime.fromtimestamp(
            cast(int, new_beneficiary.get("activationDate")) / 1000, tz=timezone.utc
        ).astimezone()
        return {
            "result": f"The new beneficiary ({new_beneficiary.get('name')} / {new_beneficiary.get('custom_label')}) has been created, it will be available at {activation_date_utc.strftime('%d/%m/%Y %H:%M:%S')}"
        }
    else:
        return {"error": "❌ Beneficiaries submodule not enabled"}


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
        context_id = _login_subdomain(
            "TELECHARGER-OPERATIONS",
            f"https://telechargement-operations.credit-agricole.fr{load_preferences().get('regional_branch')}bff",
        )

        contracts = cast(
            list[dict[str, str]],
            regular_get(
                f"https://telechargement-operations.credit-agricole.fr/ca-finistere/bff/contrats?contextId={context_id}",
                specific_key="contractElements",
            ),
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

        data = cast(
            bytes,
            regular_post(
                f"https://telechargement-operations.credit-agricole.fr/ca-finistere/bff/generer_document?contextId={context_id}",
                payload,
                specific_key="data",
            ),
        )

        parsed_data = parse_releve(data)

        return parsed_data.get("comptes", [])
    else:
        return {"error": "❌ Details of debits/credits submodule not enabled"}


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


def start_api_server(port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
