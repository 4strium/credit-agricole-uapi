import threading
import time
from typing import Any, cast

from fastapi import APIRouter, HTTPException

from credit_agricole_uapi.utils.api_helpers import (
    login_subdomain,
    regular_get,
    regular_post,
)

router = APIRouter()
from credit_agricole_uapi.fetch import post_ca_client_rest_api
from credit_agricole_uapi.globals import ApiError
from credit_agricole_uapi.preferences import load_preferences
from credit_agricole_uapi.utils.cleaners import beneficiary_cleaner
from credit_agricole_uapi.utils.data_packet import gen_transfer_packet
from credit_agricole_uapi.utils.models import TransactionParams


def conclude_transaction(
    auth_method: str,
    auth_by_factor_id: dict[str, str],
    context_id: str,
    transfer_flow_id: str,
    source_account_data: dict[str, str],
    holder: str,
    params: TransactionParams,
    external_account: dict[str, str],
    vop_entity_id: str,
):
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
                    f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/customer/authentication/factors/{auth_method}/validation",
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
        _ = regular_post(
            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/check-ip?contextId={context_id}",
            {
                "check": {
                    "transfer_flow_id": transfer_flow_id,
                    "source_account_number": params.source_account_iban,
                    "source_bic": source_account_data.get("bic_code"),
                    "source_name": holder,
                    "date": int(time.time() * 1000),
                    "amount": params.amount,
                    "currency": "EUR",
                    "recipient_account_number": params.recipient_account_iban,
                    "recipient_name": external_account.get("name"),
                    "recipient_bic": external_account.get("bic_code"),
                    "remittance_information": params.motif,
                    "additional_remittance_information": params.additional_motif,
                },
                "vop_entity_id": vop_entity_id,
            },
        )
    except ApiError as e:
        raise HTTPException(
            status_code=e.code,
            detail="Failed to call Credit Agricole API, please try again later",
        )

    try:
        _order_id = cast(
            str,
            regular_post(
                f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/send-ip",
                {"virementId": transfer_flow_id},
                specific_key="order_id",
            ),
        )
    except ApiError as e:
        raise HTTPException(
            status_code=e.code,
            detail="Failed to call Credit Agricole API, please try again later",
        )


@router.get(
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
        _ = login_subdomain(
            "VIREMENT-UNITAIRE",
            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir",
        )

        res: dict[str, Any] = {}

        try:
            res["internal"] = cast(
                list[dict[str, Any]],
                regular_get(
                    f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/comptes",
                    "my_accounts",
                ),
            )[0]["accounts"]
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        try:
            res["external"] = regular_get(
                f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries",
                "beneficiaries",
                beneficiary_cleaner,
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        return res
    else:
        return {"error": "❌ Transaction submodule not enabled"}


@router.post(
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

        context_id = login_subdomain(
            "VIREMENT-UNITAIRE",
            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir",
        )

        try:
            transfer_infos = cast(
                dict[str, Any],
                regular_get(
                    f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/comptes",
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        transfer_flow_id = cast(str, transfer_infos["transfer_flow_id"])
        holder = cast(str, transfer_infos["my_accounts"][0]["holder"])
        internal_accounts = cast(
            list[dict[str, Any]], transfer_infos["my_accounts"][0]["accounts"]
        )
        try:
            external_accounts = cast(
                list[dict[str, Any]],
                regular_get(
                    f"https://beneficiaire-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffgbnf/beneficiaries",
                    "beneficiaries",
                ),
            )
        except ApiError as e:
            raise HTTPException(
                status_code=e.code,
                detail="Failed to call Credit Agricole API, please try again later",
            )

        source_account_data = {}
        recipient_account_data = {}
        cash_account_iban = ""

        for internal_account in internal_accounts:
            if internal_account["is_saving"] == False and cash_account_iban == "":
                cash_account_iban = internal_account["iban"]
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

        if (
            source_account_data.get("is_saving") == True
            and recipient_account_data.get("external") is not None
        ):
            intermediate_p1_params = TransactionParams(
                amount=params.amount,
                source_account_iban=params.source_account_iban,
                recipient_account_iban=cash_account_iban,
                motif=params.motif,
                additional_motif=params.additional_motif,
            )
            _ = carry_out_transaction(intermediate_p1_params)
            time.sleep(5)
            intermediate_p2_params = TransactionParams(
                amount=params.amount,
                source_account_iban=cash_account_iban,
                recipient_account_iban=params.recipient_account_iban,
                motif=params.motif,
                additional_motif=params.additional_motif,
            )
            _ = carry_out_transaction(intermediate_p2_params)
            return {"Result": "✅ Transaction carried out successfully"}

        if recipient_account_data and (
            external_account := recipient_account_data.get("external")
        ):
            try:
                vop_entity_id = cast(
                    str,
                    regular_post(
                        f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/vop",
                        {
                            "channel_from": "IN",
                            "type_of_use": "VIRT",
                            "iban_payee": params.recipient_account_iban,
                            "bic_entity": external_account.get("bic_code"),
                            "identifier_value": external_account.get("name"),
                        },
                        specific_key="vop_entity_id",
                    ),
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            try:
                _ = regular_post(
                    f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/control-ip",
                    {
                        "fraisIp": gen_transfer_packet(
                            transfer_flow_id,
                            params.source_account_iban,
                            cast(str, source_account_data.get("bic_code")),
                            holder,
                            params.amount,
                            params.recipient_account_iban,
                            cast(str, external_account.get("name")),
                            cast(str, external_account.get("bic_code")),
                            params.motif,
                            params.additional_motif,
                            "",
                        )
                    },
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            try:
                _ = regular_post(
                    f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/check-ip?contextId={context_id}",
                    {
                        "check": gen_transfer_packet(
                            transfer_flow_id,
                            params.source_account_iban,
                            cast(str, source_account_data.get("bic_code")),
                            holder,
                            params.amount,
                            params.recipient_account_iban,
                            cast(str, external_account.get("name")),
                            cast(str, external_account.get("bic_code")),
                            params.motif,
                            params.additional_motif,
                        ),
                        "vop_entity_id": vop_entity_id,
                    },
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            try_send_ip = post_ca_client_rest_api(
                f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/send-ip",
                {"virementId": transfer_flow_id},
            )

            if try_send_ip == 401:
                try:
                    auth_by_factor_id = cast(
                        dict[str, str],
                        regular_post(
                            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/customer/authentication/factors/settings",  # Trigger SecuriPass
                            {"authUsage": "U031"},
                        ),
                    )
                except ApiError as e:
                    raise HTTPException(
                        status_code=e.code,
                        detail="Failed to call Credit Agricole API, please try again later",
                    )

                headers = auth_by_factor_id | {
                    "Referer": f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}fevir/authent-forte"
                }

                try:
                    auth_method = cast(
                        str,
                        regular_get(
                            f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/customer/authentication/factors/active",
                            specific_key="method",
                            extra_headers=headers,
                        ),
                    )
                except ApiError as e:
                    raise HTTPException(
                        status_code=e.code,
                        detail="Failed to call Credit Agricole API, please try again later",
                    )

                try:
                    _ = regular_get(
                        f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/customer/authentication/factors/D010/request",
                        extra_headers=headers,
                    )
                except ApiError as e:
                    raise HTTPException(
                        status_code=e.code,
                        detail="Failed to call Credit Agricole API, please try again later",
                    )

                threading.Thread(
                    target=conclude_transaction,
                    args=(
                        auth_method,
                        auth_by_factor_id,
                        context_id,
                        transfer_flow_id,
                        source_account_data,
                        holder,
                        params,
                        external_account,
                        vop_entity_id,
                    ),
                ).start()
                return {
                    "✅ Transaction initiated": "Confirm using your Credit Agricole smartphone app to finalize the transaction."
                }
            else:
                raise HTTPException(status_code=500, detail="❌ Transaction failed")
        else:
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

            try:
                confirm_transfer_flow_id = cast(
                    str,
                    regular_post(
                        f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/controle-virement?contextId={context_id}",
                        transaction_package,
                        "transfer_flow_id",
                    ),
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            try:
                _ = regular_post(
                    f"https://virement-npc-unitaire.credit-agricole.fr{load_preferences().get('regional_branch')}bffvir/creation-virement",
                    {"transfer_flow_id": confirm_transfer_flow_id},
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            return {"Result": "✅ Transaction carried out successfully"}
    else:
        return {"error": "❌ Transaction submodule not enabled"}
