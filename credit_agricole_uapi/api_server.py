import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from credit_agricole_uapi import __version__
from credit_agricole_uapi.fetch import call_ca_client_rest_api, post_ca_client_rest_api
from credit_agricole_uapi.globals import ApiError, reboot_lock

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
    version=__version__,
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


def login_subdomain(id: str, subdomain: str) -> str:
    try:
        encrypted_token = cast(
            dict[str, str | int],
            regular_post(
                "https://espace-client.credit-agricole.fr/bff/api/context/sso/v2",
                {"id_parcours": id},
                "context_token",
            ),
        )["encrypted_token"]
    except ApiError as e:
        raise HTTPException(
            status_code=e.code,
            detail="Failed to call Credit Agricole API, please try again later",
        )

    try:
        context_id = cast(
            dict[str, str],
            regular_post(
                f"{subdomain}/customer/login",
                {"token": encrypted_token},
            ),
        )["contextId"]
    except ApiError as e:
        raise HTTPException(
            status_code=e.code,
            detail="Failed to call Credit Agricole API, please try again later",
        )

    return context_id


def start_api_server(port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
