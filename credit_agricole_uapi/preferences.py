import json
import sys
from pathlib import Path
from typing import cast

import questionary
from prompt_toolkit.shortcuts import yes_no_dialog
from prompt_toolkit.styles import Style
from rich.console import Console

CLI_COLOR_STYLE: str = "#046e4c"


def validate_integer(val: str) -> bool | str:
    return val.isdigit() or "Please enter a valid integer."


def validate_6digit_integer(val: str) -> bool | str:
    return val.isdigit() and len(val) == 6 or "Please enter a valid 6-digit integer."


def save_preferences(
    user_agreement: bool,
    active_commands: bool,
    regional_branch: str,
    active_subdomains: list[str],
    api_port: int,
):
    path = Path("data/preferences.json")
    with path.open("w") as f:
        json.dump(
            {
                "user_agreement": user_agreement,
                "active_commands": active_commands,
                "active_subdomains_urls": active_subdomains,
                "regional_branch": regional_branch,
                "api_port": api_port,
            },
            f,
            indent=4,
            ensure_ascii=False,
        )


def load_preferences() -> dict[str, str | int | bool]:
    path = Path("data/preferences.json")
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def check_preferences() -> bool:
    if Path("data/preferences.json").exists():
        data = load_preferences()
        port = data.get("api_port")

        if (
            data.get("user_agreement") is True
            and data.get("regional_branch") is not None
            and port is not None
        ):
            return True
    return False


def ask_preferences(console: Console):
    user_agreement_style = Style.from_dict(
        {
            # Fond et texte du dialogue
            "dialog": f"bg:{CLI_COLOR_STYLE}",
            "dialog frame.label": "fg:#1a1a2e bold",
            "dialog.body": "fg:#1a1a2e",
            # 1. BOUTONS INACTIFS
            "button": "bg:#1a1a2e",
            "button.text": "fg:#888888",
            "button.arrow": "fg:#1a1a2e",  # Cache les flèches inactives
            # 2. BOUTON SÉLECTIONNÉ (Ciblage des éléments texte/flèches internes)
            "button.focused": "bg:#0f3460",
            "button.focused button.text": "fg:#ffffff bold",
            "button.focused button.arrow": f"fg:{CLI_COLOR_STYLE} bold",
        }
    )

    user_agreement = yes_no_dialog(
        title="User Agreement",
        text="""
            Setting up and using the Crédit Agricole UAPI requires an understanding of the associated risks.
            Since the server's IP address is public, anyone could gain TOTAL control over your bank accounts.
            It is imperative to use a private server (I recommend using tools such as Tailscale).\n
            Likewise, ensure you do not grant uncontrolled access to agents such as OpenClaw or Hermes.\n
            The devs of this project and Crédit Agricole are not responsible for any security breaches or unauthorized access.\n
            Are you certain of your network's security, and do you wish to proceed?
      """,
        style=user_agreement_style,
    ).run()
    if not user_agreement:
        sys.exit()

    console.print(
        f"[bold {CLI_COLOR_STYLE}]☑️  The user has been made aware of the potential risks.\n[/bold {CLI_COLOR_STYLE}]"
    )

    active_commands = questionary.confirm(
        "Enable actions commands (e.g. transactions, beneficiaries management)?"
    ).ask()

    caisses_regionales = {
        "Alpes Provence": "/ca-alpesprovence/",
        "Alsace Vosges": "/ca-alsace-vosges/",
        "Anjou Maine": "/ca-anjou-maine/",
        "Aquitaine": "/ca-aquitaine/",
        "Atlantique Vendée": "/ca-atlantique-vendee/",
        "Brie Picardie": "/ca-briepicardie/",
        "Centre Est": "/ca-centrest/",
        "Centre France": "/ca-centrefrance/",
        "Centre Loire": "/ca-centreloire/",
        "Centre Ouest": "/ca-centreouest/",
        "Champagne Bourgogne": "/ca-cb/",
        "Charente Périgord": "/ca-charente-perigord/",
        "Charente-Maritime Deux-Sèvres": "/ca-cmds/",
        "Corse": "/ca-corse/",
        "Côtes d'Armor": "/ca-cotesdarmor/",
        "Des Savoie": "/ca-des-savoie/",
        "Finistère": "/ca-finistere/",
        "Franche Comté": "/ca-franchecomte/",
        "Guadeloupe": "/ca-guadeloupe/",
        "Ile et Vilaine": "/ca-illeetvilaine/",
        "Languedoc": "/ca-languedoc/",
        "Loire Haute-Loire": "/ca-loirehauteloire/",
        "Lorraine": "/ca-lorraine/",
        "Martinique Guyane": "/ca-martinique/",
        "Morbihan": "/ca-morbihan/",
        "Nord De France": "/ca-norddefrance/",
        "Nord Est": "/ca-nord-est/",
        "Nord Midi Pyrénées": "/ca-nmp/",
        "Normandie": "/ca-normandie/",
        "Normandie Seine": "/ca-normandie-seine/",
        "Paris et Île de France": "/ca-paris/",
        "Provence Côte d'Azur": "/ca-pca/",
        "Pyrénées Gascogne": "/ca-pyrenees-gascogne/",
        "Réunion - Mayotte": "/ca-reunion/",
        "Sud Méditerranée": "/ca-sudmed/",
        "Sud Rhône Alpes": "/ca-sudrhonealpes/",
        "Toulouse 31": "/ca-toulouse31/",
        "Touraine Poitou": "/ca-tourainepoitou/",
        "Val De France": "/ca-valdefrance/",
    }

    regional_branch = cast(
        str,
        questionary.select(
            "Select your regional branch 🏡",
            choices=list(caisses_regionales.keys()),
            style=questionary.Style(
                [
                    ("selected", f"fg:{CLI_COLOR_STYLE} bold"),
                    ("pointer", f"fg:{CLI_COLOR_STYLE} bold"),
                ]
            ),
        ).ask(),
    )

    available_subdomains: dict[str, str] = {
        "🔁 Details of debits/credits across all your accounts (checking, savings, etc.)": f"https://espace-client.credit-agricole.fr{caisses_regionales[regional_branch]}particulier/operations-courantes/telechargement-operations",
        "📄 Official documents (bank statements, etc.)": f"https://espace-client.credit-agricole.fr{caisses_regionales[regional_branch]}particulier/documents/mes-documents",
        "💸 Transactions": f"https://espace-client.credit-agricole.fr{caisses_regionales[regional_branch]}particulier/virement/virement-unitaire",
        "👥 Management of external beneficiaries": f"https://espace-client.credit-agricole.fr{caisses_regionales[regional_branch]}particulier/virement/gestion-beneficiaires",
    }

    active_subdomains = questionary.checkbox(
        "Select the optional modules you want to enable (less modules active = faster API)",
        choices=list(available_subdomains.keys()),
    ).ask()

    active_subdomains_urls = [
        available_subdomains[subdomain] for subdomain in active_subdomains
    ]

    if (
        "💸 Transactions" in active_subdomains
        and not "👥 Management of external beneficiaries" in active_subdomains
    ):
        active_subdomains_urls.append(
            available_subdomains["👥 Management of external beneficiaries"]
        )  # Required for external transactions

    active_subdomains_urls.insert(
        0,
        f"https://espace-client.credit-agricole.fr{caisses_regionales[regional_branch]}particulier",
    )

    api_port = int(
        questionary.text(
            "On which port of your server do you want to make the API available? (make sure the port is available and not blocked by the firewall)",
            validate=validate_integer,
            default="8000",
        ).ask()
    )

    save_preferences(
        user_agreement,
        active_commands,
        caisses_regionales[regional_branch],
        active_subdomains_urls,
        api_port,
    )
