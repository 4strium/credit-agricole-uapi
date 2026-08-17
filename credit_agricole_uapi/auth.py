import random
import socket
import time
from typing import cast

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def get_local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = cast(str, s.getsockname()[0])
        except OSError:
            local_ip = "127.0.0.1"
    return local_ip


def ca_login(page: Page, account_id: int, password: int, initial_url: str) -> None:
    # Attendre l'input pour l'identifiant
    input_selector = 'input[name="identifiant"]'
    _ = page.wait_for_selector(input_selector, timeout=20000)

    # Remplir l'identifiant
    page.fill(input_selector, str(account_id))
    page.press(input_selector, "Enter")

    # Attendre que le clavier virtuel apparaisse
    keypad_selector = "app-keypad"
    _ = page.wait_for_selector(keypad_selector, timeout=20000)

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
    submit_button = None
    try:
        submit_button = page.wait_for_selector(
            'mds-button[type="submit"]', timeout=5000
        )
    except PlaywrightTimeoutError:
        submit_button = page.wait_for_selector('button[type="submit"]', timeout=5000)

    if submit_button is None:
        raise ValueError("Submit button not found")
    submit_button.click()
    time.sleep(0.5)

    # Vérifier la redirection (attendre un changement d'URL ou un délai)
    page.wait_for_url(lambda url: url != initial_url, timeout=15000)

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightTimeoutError:
        pass
    time.sleep(2)


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def simulate_human(page: Page) -> None:
    start_time = time.time()
    while True:
        if time.time() - start_time > 3300:
            break

        try:
            viewport = page.viewport_size
            width = viewport["width"] if viewport else 1280
            height = viewport["height"] if viewport else 720

            target_x = random.randint(100, width - 100)
            target_y = random.randint(100, height - 100)

            # Mouvement de souris en version synchrone
            page.mouse.move(target_x, target_y, steps=random.randint(10, 20))

            time.sleep(random.uniform(20, 40))
        except PlaywrightTimeoutError:
            break


