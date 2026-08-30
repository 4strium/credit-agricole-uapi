import time
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter, HTTPException

from credit_agricole_uapi.utils.api_helpers import (
    login_subdomain,
    regular_get,
    regular_post,
)

router = APIRouter()
from credit_agricole_uapi.globals import ApiError
from credit_agricole_uapi.preferences import load_preferences
from credit_agricole_uapi.utils.models import AddBeneficiaryRequest


@router.post(
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
        context_id = login_subdomain(
            "GESTION-BENEFICIAIRES",
            f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf",
        )

        try:
            benef_bank_infos = cast(
                dict[str, Any],
                regular_post(
                    f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries/check?contextId={context_id}",
                    {"iban": params.iban},
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        try:
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
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        if vop_infos.get("vop_result") != "MTCH":
            raise HTTPException(
                status_code=400,
                detail="We did not find the account corresponding to the provided IBAN and name.",
            )

        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        try:
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
                                    {
                                        "libelle": "beneficiary_name",
                                        "texte": params.name,
                                    },
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
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        try:
            auth_method = cast(
                str,
                regular_get(
                    f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/customer/authentication/factors/active",
                    "method",
                    extra_headers=auth_by_factor_id,
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        try:
            _ = regular_get(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/customer/authentication/factors/{auth_method}/request",
                extra_headers=auth_by_factor_id,
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        fst_ask_time = time.time()
        while True:
            if time.time() - fst_ask_time > 60:
                raise HTTPException(
                    status_code=504,
                    detail="The authentication request via your phone has expired.",
                )
            try:
                status_code = cast(
                    int,
                    regular_post(
                        f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/customer/authentication/factors/{auth_method}/validation",
                        specific_key="status",
                        extra_headers=auth_by_factor_id,
                    ),
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            if status_code == 200:
                break

            time.sleep(4)

        try:
            new_beneficiary = cast(
                dict[str, Any],
                regular_post(
                    f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries",
                    {
                        "name": params.name,
                        "beneficiary_flow_id": benef_bank_infos.get(
                            "beneficiary_flow_id"
                        ),
                        "custom_label": params.identifier,
                        "id_vop": vop_infos.get("vop_entity_id"),
                    },
                    extra_headers=auth_by_factor_id,
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        activation_date_utc = datetime.fromtimestamp(
            cast(int, new_beneficiary.get("activationDate")) / 1000, tz=timezone.utc
        ).astimezone()
        return {
            "result": f"The new beneficiary ({new_beneficiary.get('name')} / {new_beneficiary.get('custom_label')}) has been created, it will be available at {activation_date_utc.strftime('%d/%m/%Y %H:%M:%S')}"
        }
    else:
        return {"error": "❌ Beneficiaries submodule not enabled"}
