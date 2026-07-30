import secrets
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
import json
import sys

from credit_agricole_uapi.preferences import load_preferences

# Unique client HTTP partagé par toute l'application (authentification,
# serveur API et tâche de keep-alive). Il est construit une seule fois -
# une fois la session Playwright stabilisée - puis réutilisé pour tous les
# appels ultérieurs.
#
# Le serveur du Crédit Agricole pratique une rotation systématique du
# jeton anti-CSRF : chaque réponse renvoie, via `Set-Cookie`, un nouveau
# `XSRF-TOKEN` qui doit être utilisé pour la requête suivante. En gardant
# un unique `httpx.Client`, son cookie jar est automatiquement mis à jour
# par httpx à chaque réponse, exactement comme le ferait un navigateur.
# Il suffit donc de relire le cookie courant juste avant chaque requête
# pour toujours envoyer le jeton le plus récent.
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def generate_traceparent() -> str:
    trace_id = secrets.token_hex(16)
    parent_id = secrets.token_hex(8)
    return f"00-{trace_id}-{parent_id}-01"


def _default_headers() -> dict:
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


def init_client(raw_cookies: Iterable[Mapping[str, Any]]) -> httpx.Client:
    """(Ré)initialise l'unique client HTTP persistant de l'application.

    IMPORTANT : `raw_cookies` doit impérativement être capturé APRÈS
    stabilisation complète du réseau côté navigateur (plus aucun appel API
    en cours - typiquement `page.wait_for_load_state("networkidle")` suivi
    d'une marge de sécurité). Capturer les cookies trop tôt figerait un
    jeton XSRF-TOKEN déjà obsolète, invalidé par une rotation ultérieure
    côté serveur.
    """
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
        _client = httpx.Client(
            cookies=build_cookie_jar(raw_cookies),
            headers=_default_headers(),
            timeout=30.0,
        )
    return _client


def get_client() -> httpx.Client:
    if _client is None:
        raise RuntimeError(
            "Le client HTTP n'a pas encore été initialisé. "
            "Appelez fetch.init_client(...) une fois la session stabilisée."
        )
    return _client


def is_client_ready() -> bool:
    return _client is not None


def _current_xsrf_token(client: httpx.Client, target_url: str) -> str:
    """Relit le jeton XSRF-TOKEN courant depuis le cookie jar du client.

    C'est cette relecture systématique - juste avant chaque requête - qui
    permet de suivre la rotation de jeton effectuée par le serveur : le
    nouveau jeton arrive via `Set-Cookie` dans chaque réponse et est
    absorbé automatiquement dans `client.cookies` par httpx.
    """
    target_domain = urlparse(target_url).netloc
    for cookie in client.cookies.jar:
        if (
            "XSRF-TOKEN" in cookie.name
            and cookie.domain.endswith("credit-agricole.fr")
            and cookie.domain.lstrip(".") in target_domain
        ):
            return cookie.value or ""
    return ""


def call_ca_client_rest_api(url: str):
    """Appelle l'API REST du Crédit Agricole via l'unique client HTTP
    persistant de l'application.

    Les appels sont sérialisés via un verrou afin d'éviter toute course
    entre deux requêtes concurrentes (ex: un appel API utilisateur et le
    keep-alive périodique) pendant une rotation du jeton anti-CSRF.
    """
    with _client_lock:
        client = get_client()
        headers = {"X-XSRF-TOKEN": _current_xsrf_token(client, url)}
        response = client.get(url, headers=headers)

        if response.status_code in (200, 204):
            # 1. Gestion des réponses vides (keepalive, absence de crédits/prêts, etc.)
            if not response.content or not response.content.strip():
                return {}

            # 2. Parsing du JSON avec secours si le contenu n'est pas au format JSON
            try:
                return response.json()
            except (json.JSONDecodeError, httpx.DecodingError, ValueError):
                return {}
        elif response.status_code == 401:
            print("🛑 The credentials you provided are invalid; please check them and try again.")
            sys.exit(1)
        else:
            print(f"Échec ({response.status_code}) : {response.text}")
            return None


def keep_alive():
    while True:
        time.sleep(240)
        if (
            call_ca_client_rest_api(
                "https://client.ca-connect.credit-agricole.fr/keepalive"
            )
            is not None
        ):
            print("Session prolongée avec succès !")
        else:
            print("Échec du keepalive — La session a probablement expiré.")
            break
