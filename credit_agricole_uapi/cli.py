#!/usr/bin/env python3
import argparse
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

import questionary
from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from rich.console import Console
from rich.panel import Panel

from credit_agricole_uapi.api_server import get_accounts_data, start_api_server
from credit_agricole_uapi.auth import (
    ca_login,
    get_local_ip,
    is_port_in_use,
    simulate_human,
)
from credit_agricole_uapi.fetch import init_client, keep_alive_bff, keep_alive_sso
from credit_agricole_uapi.globals import reboot_lock
from credit_agricole_uapi.preferences import (
    CLI_COLOR_STYLE,
    ask_preferences,
    check_preferences,
    load_preferences,
    validate_6digit_integer,
    validate_integer,
)

APP_LOGO = """
 ██████ ██████  ███████ ██████  ██ ████████      █████   ██████  ██████  ██  ██████  ██████  ██      ███████     ██    ██  █████  ██████  ██
██      ██   ██ ██      ██   ██ ██    ██        ██   ██ ██       ██   ██ ██ ██      ██    ██ ██      ██          ██    ██ ██   ██ ██   ██ ██
██      ██████  █████   ██   ██ ██    ██        ███████ ██   ███ ██████  ██ ██      ██    ██ ██      █████       ██    ██ ███████ ██████  ██
██      ██   ██ ██      ██   ██ ██    ██        ██   ██ ██    ██ ██   ██ ██ ██      ██    ██ ██      ██          ██    ██ ██   ██ ██      ██
 ██████ ██   ██ ███████ ██████  ██    ██        ██   ██  ██████  ██   ██ ██  ██████  ██████  ███████ ███████      ██████  ██   ██ ██      ██
"""

console = Console()
auth_path = Path("data/auth.json")
server_log_path = Path("data/server.log")
server_pid_path = Path("data/server.pid")


def ensure_chromium_installed() -> None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except PlaywrightError as e:
        msg = str(e).lower()
        if "executable doesn't exist" not in msg and "browser" not in msg:
            raise

        console.print(
            "[bold yellow]⚠️ Chromium is missing. Installing Playwright Chromium now...[/bold yellow]"
        )
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            console.print(
                Panel(
                    "[bold white]Failed to install Chromium automatically.[/bold white]\n"
                    + "[dim]Please run: python -m playwright install chromium[/dim]",
                    title="[bold white on red] ERROR [/bold white on red]",
                    border_style="red",
                    expand=False,
                )
            )
            sys.exit(1)


def get_launch_command() -> str:
    """Reconstruit la commande utilisée pour lancer ce CLI, afin que les
    messages affichés (ex: commande d'arrêt) correspondent réellement à la
    façon dont l'utilisateur a lancé le programme.
    """
    if Path(sys.argv[0]).name == "cli.py":
        return f"{sys.executable} -m credit_agricole_uapi.cli"
    return "credit-agricole-uapi"


def stop_background_server(silent: bool = False):
    if not server_pid_path.exists():
        if not silent:
            console.print(
                "[bold yellow]⚠️  No running background server found (no PID file).[/bold yellow]"
            )
        return

    pid = int(server_pid_path.read_text().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        if not silent:
            console.print(
                f"[bold {CLI_COLOR_STYLE}]🛑  Server (PID {pid}) stopped.[/bold {CLI_COLOR_STYLE}]"
            )
    except ProcessLookupError:
        if not silent:
            console.print(
                "[bold yellow]⚠️  Server was not running (stale PID file removed).[/bold yellow]"
            )
    finally:
        server_pid_path.unlink(missing_ok=True)


def load_cookies_in_context(context: BrowserContext, page: Page):
    urls = cast(list[str], load_preferences().get("active_subdomains_urls", []))

    for i in range(len(urls)):
        _ = page.goto(urls[i])

        # On attend la stabilisation complète du réseau
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            time.sleep(5)

    init_client(context.cookies())
    _ = context.storage_state(path=auth_path)


def run_background_server(port: int):
    account_id = int(cast(str, os.getenv("CA_UAPI_ACCOUNT_ID")))
    password = int(cast(str, os.getenv("CA_UAPI_ACCOUNT_PSW")))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            storage_state=auth_path,
        )
        page = context.new_page()

        load_cookies_in_context(context, page)

        api_thread = threading.Thread(
            target=start_api_server, args=(port,), daemon=True
        )
        api_thread.start()

        global_keep_alive(page, context, account_id, password)


def global_keep_alive(
    page: Page, context: BrowserContext, account_id: int, password: int
):
    """
    Maintiens la session active avec le site du Crédit Agricole.
    Le rafraîchissement de l'API interne pendant 57 minutes est réalisé via des requêtes HTTP.
    Puis une reconnexion complète est effectuée (non bloquante).
    Le serveur API n'est démarré qu'une fois la première session stabilisée.
    """
    while True:
        reboot_lock.enable_reboot()

        ka_sso_thread = threading.Thread(target=keep_alive_sso, daemon=True)
        ka_bff_thread = threading.Thread(target=keep_alive_bff, daemon=True)
        ka_sso_thread.start()
        ka_bff_thread.start()
        simulate_human(page)
        ka_sso_thread.join()
        ka_bff_thread.join()

        while not reboot_lock.reboot_is_available():
            time.sleep(0.1)

        reboot_lock.set_rebooting()
        print("Rebooting...", flush=True)

        page.evaluate("""
        () => {
            localStorage.clear();
            sessionStorage.clear();
        }
        """)

        context.clear_cookies()
        _ = page.reload()
        ca_login(page, account_id, password, page.url)
        load_cookies_in_context(context, page)


def main():
    ensure_chromium_installed()
    console.print(f"[bold {CLI_COLOR_STYLE}]{APP_LOGO}[/bold {CLI_COLOR_STYLE}]")
    console.print(
        "[italic white]Crédit Agricole UAPI is [bold]NOT[/bold] affiliated with Crédit Agricole S.A.\n[/italic white]"
    )

    time.sleep(2)

    if not check_preferences():
        console.print(
            "[bold red]👤 No user preferences found. You will have to answer a few questions.\n[/bold red]"
        )

        time.sleep(2)
        ask_preferences(console)
        console.print("\n")

    console.print(
        Panel(
            """
            [italic white]The authentication process will now take place.[/italic white]
            [white]The system will ask for your login credentials. Keep in mind that this [bold]data will not be stored on your computer or shared with any server other than the official Crédit Agricole server.[/bold]
            The security level is identical to that of a standard connection via their login page. Once authentication is validated, the gateway will start automatically.
            It will ensure the connection is maintained continuously in the background (as long as you do not shut down your server).[/white]
            """,
            title=f"[bold black on {CLI_COLOR_STYLE}] AUTHENTIFICATION PROCESS [/bold black on {CLI_COLOR_STYLE}]",
            border_style=f"{CLI_COLOR_STYLE}",
            expand=False,
            padding=(1, 2),
        )
    )

    console.print("")

    account_id = cast(
        int,
        questionary.text(
            "Enter your banking ID (e.g., your account number) :",
            validate=validate_integer,
        ).ask(),
    )

    password = cast(
        int,
        questionary.password(
            "Enter your app password (6-digit integer) :",
            validate=validate_6digit_integer,
        ).ask(),
    )
    console.print("")

    stop_background_server(silent=True)

    with sync_playwright() as p:
        with console.status(
            "[bold yellow]Connecting to Crédit Agricole server...[/bold yellow]",
            spinner="dots",
            spinner_style="yellow",
        ):
            browser = p.chromium.launch(headless=True)

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            page = context.new_page()

            _ = page.goto(
                f"https://espace-client.credit-agricole.fr{load_preferences().get('regional_branch')}particulier"
            )

            initial_url = page.url

        try:
            with console.status(
                "[bold yellow]Authentication with Crédit Agricole server...[/bold yellow]",
                spinner="dots",
                spinner_style="yellow",
            ):
                ca_login(page, account_id, password, initial_url)

                # On sauvegarde l'état de la session (cookies + storage) sur
                # disque afin que le sous-processus de fond puisse démarrer sa
                # propre session Playwright à partir d'un état déjà authentifié.
                _ = context.storage_state(path=auth_path)

                # Construction de l'unique client HTTP persistant de
                # l'application, à partir des cookies fraîchement stabilisés.
                init_client(context.cookies())
                browser.close()

            _ = get_accounts_data()

            port = cast(int | None, load_preferences().get("api_port"))
            if not port:
                console.print(
                    "[bold red]⚠️  Port is not set. The background server will not be started.[/bold red]"
                )
                return

            if is_port_in_use(port):
                console.print(
                    f"[bold red]⚠️  Port {port} is already in use. The background server will not be started.[/bold red]"
                )
                return

            console.print(
                f"[bold {CLI_COLOR_STYLE}]🎉 Authentification successful 🎉[/bold {CLI_COLOR_STYLE}]"
            )

            # Generate API key
            api_key = secrets.token_urlsafe(32)

            console.print(
                f"[bold {CLI_COLOR_STYLE}]\n🔑 API key:[/bold {CLI_COLOR_STYLE}] [code]{api_key}[/code] [italic](make sure to save it, it will not be shown again)[/italic]"
            )

            # Put credentials in environment
            srv_env = os.environ.copy()
            srv_env["CA_UAPI_KEY"] = str(api_key)
            srv_env["CA_UAPI_ACCOUNT_ID"] = str(account_id)
            srv_env["CA_UAPI_ACCOUNT_PSW"] = str(password)

            local_ip = get_local_ip()
            console.print(
                Panel.fit(
                    f"[bold {CLI_COLOR_STYLE}]🚀 API Gateway server is running in background![/bold {CLI_COLOR_STYLE}]\n\n"
                    + f"• [bold white]Local URL:[/bold white]    [link=http://127.0.0.1:{port}]http://127.0.0.1:{port}[/link]\n"
                    + f"• [bold white]Network URL:[/bold white] [link=http://{local_ip}:{port}]http://{local_ip}:{port}[/link]\n\n"
                    + f"[white][bold red][code]{get_launch_command()} --stop[/code][/bold red] to stop the server.[/white]",
                    border_style=f"{CLI_COLOR_STYLE}",
                    padding=(1, 2),
                )
            )

            with open(server_log_path, "a") as logfile:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        "-m",
                        "credit_agricole_uapi.cli",
                        "--background",
                        "--port",
                        str(port),
                    ],
                    stdout=logfile,
                    stderr=logfile,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env=srv_env,
                )
                _ = server_pid_path.write_text(str(process.pid))

            time.sleep(2)
            console.print(
                f'[bold {CLI_COLOR_STYLE}]\n😉 Typing [code]curl -s -X GET "http://127.0.0.1:{port}/api/accounts" -H "X-API-Key: <api_key>"[/code] is a good way to test the API.[/bold {CLI_COLOR_STYLE}]'
            )
            console.print(
                f"[bold {CLI_COLOR_STYLE}]\n📚 All endpoints are documented at [link=http://{local_ip}:{port}/docs]http://{local_ip}:{port}/docs[/link].\n[/bold {CLI_COLOR_STYLE}]"
            )

            return

        except PlaywrightTimeoutError:
            console.print(
                Panel(
                    "[bold white]Time limit exceeded: the form did not appear in time.[/bold white]\n"
                    + "[dim]Please try again later.[/dim]",
                    title="[bold white on red] ERROR [/bold white on red]",
                    border_style="red",
                    expand=False,
                )
            )
            context.close()
            return
        except (PlaywrightError, ValueError, TypeError) as e:
            console.print(
                Panel(
                    f"[bold white]Authentication error: {e}[/bold white]\n"
                    + "[dim]Please try again later.[/dim]",
                    title="[bold white on red] ERROR [/bold white on red]",
                    border_style="red",
                    expand=False,
                )
            )
            context.close()
            return


def run():
    ensure_chromium_installed()
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--background",
        action="store_true",
        help="Internal option for background mode",
    )
    _ = parser.add_argument(
        "--port", type=int, default=8000, help="Listening port for the API"
    )
    _ = parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the background server started previously",
    )
    args = parser.parse_args()
    if args.stop:
        stop_background_server()
    elif "--background" in sys.argv:
        run_background_server(args.port)
    else:
        main()


if __name__ == "__main__":
    run()
