import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from credit_agricole_uapi import __version__

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

# Register routers — imported here after `app` is defined to avoid circular imports.
# Sub-modules depend only on `utils.api_helpers`, not on this module.
from credit_agricole_uapi.transactions import (
    benefs_mng,
    history,
    transaction,
)
from credit_agricole_uapi.user_data import accounts_synthesis, documents

app.include_router(transaction.router)
app.include_router(benefs_mng.router)
app.include_router(history.router)
app.include_router(accounts_synthesis.router)
app.include_router(documents.router)


def start_api_server(port: int) -> None:
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
