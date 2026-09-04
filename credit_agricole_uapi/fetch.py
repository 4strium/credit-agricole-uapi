import json
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
    global _raw_cookies
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
) -> dict[str, Any] | int:
    """
    Appelle l'API REST du Crédit Agricole via un client HTTP dédié par domaine.
    """
    with _client_lock:
        if not _raw_cookies:
            raise RuntimeError(
                "Le client HTTP n'a pas encore été initialisé. "
                + "Appelez fetch.init_client(...) une fois la session stabilisée."
            )

        client = _get_or_create_client_for(url)

        headers = {"X-XSRF-TOKEN": _current_xsrf_token(client)}
        if extra_headers:
            headers.update(extra_headers)

        response = client.get(url, headers=headers)

        if response.status_code in (200, 204, 404):
            if not response.content or not response.content.strip():
                return {}

            try:
                return response.json()
            except (json.JSONDecodeError, httpx.DecodingError, ValueError):
                try:
                    return {"data": response.content}
                except AttributeError:
                    return {}
        else:
            print(f"Error ({response.status_code}) - GET @ {url} : {response.text}")
            return response.status_code


def post_ca_client_rest_api(
    url: str,
    json_data: dict[str, Any] | list[Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | int:
    """
    Appelle l'API REST du Crédit Agricole via un client HTTP dédié par domaine (Méthode POST).
    """
    with _client_lock:
        if not _raw_cookies:
            raise RuntimeError(
                "Le client HTTP n'a pas encore été initialisé. "
                + "Appelez fetch.init_client(...) une fois la session stabilisée."
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
                except AttributeError:
                    return {}
        else:
            print(
                f"Error ({response.status_code}) - Post @ {url} with {json_data} : {response.text}"
            )
            return response.status_code


def _wait_for_keep_alive(delay: float, stop_event: threading.Event | None) -> bool:
    """Attend une durée, sauf si un autre keep-alive demande l'arrêt."""
    if stop_event is None:
        time.sleep(delay)
        return False
    return stop_event.wait(delay)


def _call_keep_alive(
    url: str,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any] | int | None:
    """Exécute un keep-alive sans laisser une erreur réseau tuer son thread."""
    try:
        return call_ca_client_rest_api(url, extra_headers)
    except Exception as error:  # noqa: BLE001 - thread boundary must be resilient
        print(
            f"Keep-alive request failed - GET @ {url}: {type(error).__name__}: {error}",
            flush=True,
        )
        return None


def keep_alive_sso(stop_event: threading.Event | None = None) -> None:
    try:
        for _ in range(19):
            if _wait_for_keep_alive(180, stop_event):
                return

            result = _call_keep_alive(
                "https://client.ca-connect.credit-agricole.fr/keepalive"
            )
            if isinstance(result, int):
                break
    except Exception as error:  # noqa: BLE001 - thread boundary must be resilient
        # Protection de dernier niveau : une exception inattendue ne doit
        # jamais remonter jusqu'au gestionnaire de thread de Python.
        print(
            f"SSO keep-alive thread stopped: {type(error).__name__}: {error}",
            flush=True,
        )


def keep_alive_bff(
    stop_event: threading.Event | None = None,
    reboot_requested: threading.Event | None = None,
) -> None:
    def request_reboot_if_needed(result: dict[str, Any] | int | None) -> bool:
        if result != 401:
            return False
        if reboot_requested is not None:
            reboot_requested.set()
        if stop_event is not None:
            stop_event.set()
        return True

    try:
        if _wait_for_keep_alive(30, stop_event):
            return

        for _ in range(7):
            result = _call_keep_alive(
                "https://espace-client.credit-agricole.fr/bff/api/security/ping",
                {"correlationId": str(uuid.uuid4())},
            )
            if request_reboot_if_needed(result):
                return
            if isinstance(result, int):
                break

            if _wait_for_keep_alive(240, stop_event):
                return

            result = _call_keep_alive(
                "https://espace-client.credit-agricole.fr/bff/api/security/ping",
                {"correlationId": str(uuid.uuid4())},
            )
            if request_reboot_if_needed(result):
                return
            if isinstance(result, int):
                return

            if _wait_for_keep_alive(10, stop_event):
                return

            result = _call_keep_alive(
                "https://espace-client.credit-agricole.fr/bff/api/security/refresh",
                {"correlationId": str(uuid.uuid4())},
            )
            if isinstance(result, int):
                return

            if _wait_for_keep_alive(229, stop_event):
                return
    except Exception as error:  # noqa: BLE001 - thread boundary must be resilient
        # Protection de dernier niveau : une exception inattendue ne doit
        # jamais produire de traceback « Exception in thread ».
        print(
            f"BFF keep-alive thread stopped: {type(error).__name__}: {error}",
            flush=True,
        )
