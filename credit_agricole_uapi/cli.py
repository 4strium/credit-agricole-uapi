import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import questionary
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel

from credit_agricole_uapi.api_server import get_accounts_data, start_api_server
from credit_agricole_uapi.auth import get_local_ip
from credit_agricole_uapi.fetch import init_client, keep_alive
from credit_agricole_uapi.preferences import (
    ask_preferences,
    check_preferences,
    load_preferences,
    CLI_COLOR_STYLE,
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
                    "[dim]Please run: python -m playwright install chromium[/dim]",
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


def stop_background_server():
    if not server_pid_path.exists():
        console.print(
            "[bold yellow]⚠️ No running background server found (no PID file).[/bold yellow]"
        )
        return

    pid = int(server_pid_path.read_text().strip())

    try:
        # start_new_session=True met le process dans son propre groupe :
        # on tue tout le groupe (process principal + thread API/Playwright).
        os.killpg(pid, signal.SIGTERM)
        console.print(f"[bold {CLI_COLOR_STYLE}]🛑 Server (PID {pid}) stopped.[/bold {CLI_COLOR_STYLE}]")
    except ProcessLookupError:
        console.print(
            "[bold yellow]⚠️  Server was not running (stale PID file removed).[/bold yellow]"
        )
    finally:
        server_pid_path.unlink(missing_ok=True)


def run_background_server(port: int):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            storage_state=auth_path,
        )
        page = context.new_page()
        page.goto(
            f"https://espace-client.credit-agricole.fr{load_preferences().get('regional_branch')}particulier"
        )

        # On attend la stabilisation complète du réseau (plus aucun appel
        # API en cours) avant de capturer les cookies et de construire
        # l'unique client HTTP persistant utilisé pour toute la durée de
        # vie de ce sous-processus (serveur API + keep-alive). C'est la
        # seule façon fiable de "retrouver" une session à jour au démarrage
        # du sous-processus, sans risquer de figer un jeton XSRF-TOKEN déjà
        # périmé par une rotation antérieure.
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            print(
                "⚠️  Le réseau ne s'est pas complètement stabilisé (connexions persistantes ?), poursuite après une marge de sécurité."
            )
        time.sleep(5)

        init_client(context.cookies())
        context.storage_state(path=auth_path)

        api_thread = threading.Thread(
            target=start_api_server, args=(port,), daemon=True
        )
        api_thread.start()

        keep_alive()


def main():
    ensure_chromium_installed()
    console.print(f"[bold {CLI_COLOR_STYLE}]{APP_LOGO}[/bold {CLI_COLOR_STYLE}]")
    console.print(
        "[italic white]Crédit Agricole UAPI is [bold]NOT[/bold] affiliated with Crédit Agricole S.A.\n[/italic white]"
    )

    data_folder = Path("data")
    data_folder.mkdir(parents=True, exist_ok=True)

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
            padding=(1, 2)
        )
    )

    console.print("")

    account_id = questionary.text(
        "Enter your banking ID (e.g., your account number) :",
        validate=lambda val: val.isdigit() or "Please enter a valid integer.",
    ).ask()
    account_id = int(account_id)

    password = questionary.password(
        "Enter your app password (6-digit integer) :",
        validate=lambda val: (
            val.isdigit() and len(val) == 6 or "Please enter a valid 6-digit integer."
        ),
    ).ask()
    password = int(password)
    console.print("")

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

            page.goto(
                f"https://espace-client.credit-agricole.fr{load_preferences().get('regional_branch')}particulier"
            )

            initial_url = page.url

        try:
            with console.status(
                "[bold yellow]Authentication with Crédit Agricole server...[/bold yellow]",
                spinner="dots",
                spinner_style="yellow",
            ):
                # Attendre l'input pour l'identifiant
                input_selector = 'input[name="identifiant"]'
                page.wait_for_selector(input_selector, timeout=20000)
    
                # Remplir l'identifiant
                page.fill(input_selector, str(account_id))
                page.press(input_selector, "Enter")
    
                # Attendre que le clavier virtuel apparaisse
                keypad_selector = "app-keypad"
                page.wait_for_selector(keypad_selector, timeout=20000)
    
                # Convertir le mot de passe en string pour accéder à chaque digit
                password_str = str(password).zfill(6)  # S'assurer que c'est 6 digits
    
                # Cliquer sur chaque bouton du clavier correspondant aux digits du password
                for digit in password_str:
                    # Localiser tous les boutons du clavier (sauf le bouton d'effacement qui a un id)
                    buttons = page.locator("app-keypad button[data-row]:not(#keypad-erase)")
                    clicked = False
    
                    # Parcourir tous les boutons pour trouver celui avec le digit
                    for i in range(buttons.count()):
                        button = buttons.nth(i)
                        text_content = (button.text_content() or "").strip()
    
                        if text_content == digit:
                            button.click()
                            clicked = True
                            time.sleep(0.25)
                            break
    
                    if not clicked:
                        raise ValueError(f"Could not find button for digit {digit}")
    
                # Attendre que le bouton submit soit disponible et cliquer dessus
                # Le bouton submit peut être soit un mds-button, soit un button normal
                submit_button = None
                try:
                    submit_button = page.wait_for_selector(
                        'mds-button[type="submit"]', timeout=5000
                    )
                except PlaywrightTimeoutError:
                    submit_button = page.wait_for_selector(
                        'button[type="submit"]', timeout=5000
                    )
    
                if submit_button is None:
                    raise ValueError("Submit button not found")
                submit_button.click()
                time.sleep(0.5)  # Laisser le formulaire traiter la soumission
    
                # Vérifier la redirection (attendre un changement d'URL ou un délai)
                page.wait_for_url(lambda url: url != initial_url, timeout=15000)
    
                # Authentification réussie : on attend maintenant la
                # stabilisation complète du réseau (plus aucun appel API en
                # cours) avant de capturer les cookies. Le serveur du Crédit
                # Agricole fait pivoter le jeton anti-CSRF (XSRF-TOKEN) à chaque
                # réponse : capturer les cookies trop tôt figerait un jeton déjà
                # obsolète.
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except PlaywrightTimeoutError:
                    console.print(
                        "[dim]⚠️  Le réseau ne s'est pas complètement stabilisé (connexions persistantes ?), poursuite après une marge de sécurité.[/dim]"
                    )
                time.sleep(3)
    
                # On sauvegarde l'état de la session (cookies + storage) sur
                # disque afin que le sous-processus de fond puisse démarrer sa
                # propre session Playwright à partir d'un état déjà authentifié.
                context.storage_state(path=auth_path)
    
                # Construction de l'unique client HTTP persistant de
                # l'application, à partir des cookies fraîchement stabilisés.
                init_client(context.cookies())
                browser.close()

            get_accounts_data()

            console.print(
                f"[bold {CLI_COLOR_STYLE}]\n🎉 Authentification successful 🎉[/bold {CLI_COLOR_STYLE}]"
            )
            
            port = load_preferences().get("api_port")

            local_ip = get_local_ip()
            console.print(
                Panel.fit(
                    f"[bold {CLI_COLOR_STYLE}]🚀 API Gateway server is running in background![/bold {CLI_COLOR_STYLE}]\n\n"
                    f"• [bold white]Local URL:[/bold white]    [link=http://127.0.0.1:{port}]http://127.0.0.1:{port}[/link]\n"
                    f"• [bold white]Network URL:[/bold white] [link=http://{local_ip}:{port}]http://{local_ip}:{port}[/link]\n\n"
                    f"[white][bold red][code]{get_launch_command()} --stop[/code][/bold red] to stop the server.[/white]",
                    border_style=f"{CLI_COLOR_STYLE}",
                    padding=(1, 2),
                )
            )

            time.sleep(2)
            console.print(
                f'[bold {CLI_COLOR_STYLE}]\n😉 Typing [code]curl -s -X GET "http://127.0.0.1:{port}/api/accounts"[/code] is a good way to test the API.[/bold {CLI_COLOR_STYLE}]'
            )
            console.print(
                f"[bold {CLI_COLOR_STYLE}]\n📚 All endpoints are documented at [link=http://{local_ip}:{port}/docs]http://{local_ip}:{port}/docs[/link].\n[/bold {CLI_COLOR_STYLE}]"
            )

            with open(server_log_path, "a") as logfile:
                process = subprocess.Popen(
                    [
                        sys.executable,
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
                )
                server_pid_path.write_text(str(process.pid))

            
            sys.exit(0)

        except PlaywrightTimeoutError:
            console.print(
                Panel(
                    "[bold white]Time limit exceeded: the form did not appear in time.[/bold white]\n"
                    "[dim]Please try again later.[/dim]",
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
                    "[dim]Please try again later.[/dim]",
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
    parser.add_argument(
        "--background",
        action="store_true",
        help="Internal option for background mode",
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Listening port for the API"
    )
    parser.add_argument(
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
