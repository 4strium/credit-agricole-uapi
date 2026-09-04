from collections.abc import Callable
from typing import Any, cast

from fastapi import HTTPException

from credit_agricole_uapi.fetch import call_ca_client_rest_api, post_ca_client_rest_api
from credit_agricole_uapi.globals import ApiError, reboot_lock


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


def to_float(value: str | None) -> float | None:
    if not value or not value.strip():
        return None
    return float(value.replace("\xa0", " ").replace(" ", "").replace(",", "."))


def clean_libelle(libelle: str) -> str:
    lines = [l.strip() for l in libelle.split("\n") if l.strip()]
    return " - ".join(lines)


def regular_get(
    endpoint: str,
    specific_key: str | None = None,
    cleaner: Callable[[Any], Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | list[Any] | str:
    reboot_lock.disable_reboot()

    data = call_ca_client_rest_api(endpoint, extra_headers)
    if isinstance(data, int):
        raise ApiError(data)
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
    if isinstance(data, int):
        raise ApiError(data)

    if data == {}:
        return []

    if specific_key is not None:
        data = data[specific_key]

    if cleaner is not None:
        cleaner(data)

    reboot_lock.enable_reboot()
    return data


def login_subdomain(id: str, subdomain: str, context_trigger: bool = False) -> str:
    try:
        token_data = cast(
            dict[str, str | int],
            regular_post(
                "https://espace-client.credit-agricole.fr/bff/api/context/sso/v2",
                {"id_parcours": id},
                "context_token",
            ),
        )
        encrypted_token = token_data["encrypted_token"]

        if context_trigger:
            context_data = cast(dict[str, str], regular_get(f"{subdomain}/context"))
            context_id = context_data["contextId"]

            # Effectue le login sans écraser `context_id`
            _ = regular_post(
                f"{subdomain}/customer/login",
                {"token": encrypted_token},
            )
            return context_id
        else:
            login_data = cast(
                dict[str, str],
                regular_post(
                    f"{subdomain}/customer/login",
                    {"token": encrypted_token},
                ),
            )
            return login_data["contextId"]

    except ApiError as e:
        raise HTTPException(
            status_code=e.code,
            detail="Failed to call Credit Agricole API, please try again later",
        )
