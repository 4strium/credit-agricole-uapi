import json
import sys
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from credit_agricole_uapi.preferences import load_preferences

_clients: dict[str, httpx.Client] = {}
_raw_cookies: list[Mapping[str, Any]] = []
_client_lock = threading.Lock()


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr,fr-FR;q=0.9",
        "Referer": f"https://espace-client.credit-agricole.fr{load_preferences().get('regional_branch')}particulier/synthese",
    }


def build_cookie_jar(raw_cookies: Iterable[Mapping[str, Any]]) -> httpx.Cookies:
    """Construit un jar httpx à partir de cookies bruts (ex: `context.cookies()`
    ou `storage_state()["cookies"]` de Playwright), en conservant domaine et path."""
    jar = httpx.Cookies()
    for cookie in raw_cookies:
        jar.set(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
    return jar


def init_client(raw_cookies: Iterable[Mapping[str, Any]]) -> None:
    """
    Initialise les clients HTTP par domaine avec les cookies fournis.
    """
    global _raw_cookies, _clients
    with _client_lock:
        for client in _clients.values():
            client.close()
        _clients.clear()
        _raw_cookies = list(raw_cookies)


def _get_or_create_client_for(url: str) -> httpx.Client:
    """
    Retourne le client HTTP pour le domaine de l'URL, le crée s'il n'existe pas.
    Doit être appelée sous _client_lock pour éviter les races.
    """
    host = urlparse(url).netloc

    if host not in _clients:
        domain_cookies = [c for c in _raw_cookies if _cookie_matches_host(c, host)]
        _clients[host] = httpx.Client(
            cookies=build_cookie_jar(domain_cookies),
            headers=_default_headers(),
            timeout=30.0,
        )
    return _clients[host]


def _cookie_matches_host(cookie: Mapping[str, Any], host: str) -> bool:
    """
    Vérifie si un cookie s'applique à un host donné.
    """
    cookie_domain = cast(str, cookie.get("domain", "").rstrip("/"))

    if not cookie_domain:
        return True
    if cookie_domain == host:
        return True
    if cookie_domain.startswith(".") and host.endswith(cookie_domain):
        return True
    return cookie_domain.lstrip(".") == host


def is_client_ready() -> bool:
    return bool(_raw_cookies)


def _current_xsrf_token(client: httpx.Client) -> str:
    """
    Relit le jeton XSRF-TOKEN courant depuis le cookie jar du client.
    """
    for cookie in client.cookies.jar:
        if cookie.name == "XSRF-TOKEN":
            return cookie.value or ""
    return ""


def call_ca_client_rest_api(
    url: str, extra_headers: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """
    Appelle l'API REST du Crédit Agricole via un client HTTP dédié par domaine.
    """
    with _client_lock:
        if not _raw_cookies:
            raise RuntimeError(
                "Le client HTTP n'a pas encore été initialisé. "
                "Appelez fetch.init_client(...) une fois la session stabilisée."
            )

        client = _get_or_create_client_for(url)

        headers = {"X-XSRF-TOKEN": _current_xsrf_token(client)}
        if extra_headers:
            headers.update(extra_headers)

        response = client.get(url, headers=headers)

        if response.status_code in (200, 204):
            if not response.content or not response.content.strip():
                return {}

            try:
                return response.json()
            except (json.JSONDecodeError, httpx.DecodingError, ValueError):
                try:
                    return {"data": response.content}
                except Exception:
                    return {}
        elif response.status_code == 401:
            print(f"Échec ({response.status_code}) : {response.text}")
            sys.exit(1)
        else:
            print(f"Échec ({response.status_code}) : {response.text}")
            return None


def post_ca_client_rest_api(
    url: str,
    json_data: dict[str, Any] | list[Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Appelle l'API REST du Crédit Agricole via un client HTTP dédié par domaine (Méthode POST).
    """
    with _client_lock:
        if not _raw_cookies:
            raise RuntimeError(
                "Le client HTTP n'a pas encore été initialisé. "
                "Appelez fetch.init_client(...) une fois la session stabilisée."
            )

        client = _get_or_create_client_for(url)

        headers = {"X-XSRF-TOKEN": _current_xsrf_token(client)}
        if extra_headers:
            headers.update(extra_headers)

        response = client.post(url, json=json_data, headers=headers)

        if response.status_code in (200, 201, 202, 204):
            if not response.content or not response.content.strip():
                return {}

            try:
                return response.json()
            except (json.JSONDecodeError, httpx.DecodingError, ValueError):
                try:
                    return {"data": response.content}
                except Exception:
                    return {}
        elif response.status_code == 401:
            print(f"Échec ({response.status_code}) : {response.text}")
            sys.exit(1)
        else:
            print(f"Échec ({response.status_code}) : {response.text}")
            return None


def keep_alive_sso():
    for _ in range(2):
        time.sleep(180)
        if (
            call_ca_client_rest_api(
                "https://client.ca-connect.credit-agricole.fr/keepalive"
            )
            is None
        ):
            break


def keep_alive_bff():
    time.sleep(30)
    if (
        call_ca_client_rest_api(
            "https://espace-client.credit-agricole.fr/bff/api/security/ping",
            {"correlationId": str(uuid.uuid4())},
        )
        is None
    ):
        return
    time.sleep(240)
    if (
        call_ca_client_rest_api(
            "https://espace-client.credit-agricole.fr/bff/api/security/ping",
            {"correlationId": str(uuid.uuid4())},
        )
        is None
    ):
        return
    time.sleep(10)
    if (
        call_ca_client_rest_api(
            "https://espace-client.credit-agricole.fr/bff/api/security/refresh",
            {"correlationId": str(uuid.uuid4())},
        )
        is None
    ):
        return
    time.sleep(229)
