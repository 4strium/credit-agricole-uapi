import csv
import io
import re
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from credit_agricole_uapi.auth import get_local_ip
from credit_agricole_uapi.globals import ApiError
from credit_agricole_uapi.preferences import load_preferences
from credit_agricole_uapi.utils.api_helpers import clean_libelle, regular_get, to_float


def parse_releve(raw: bytes, encoding: str = "cp1252") -> dict[str, Any]:
    text = raw.decode(encoding)
    result: dict[str, Any] = {"titulaire": None, "date_extraction": None, "comptes": []}
    compte_courant: dict[str, Any] | None = None
    pending_nom_carte = None

    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if not row or all(not f.strip() for f in row):
            continue
        first = row[0].strip()

        if m := re.match(r"Téléchargement du (\d{2}/\d{2}/\d{4})", first):
            result["date_extraction"] = m.group(1)
        elif re.match(r"^M\.?\s+", first) and "carte" not in first.lower():
            result["titulaire"] = re.sub(r"\s+", " ", first).strip()
        elif m := re.match(r"(.+?)\s*carte\s*n[°o]\s*(\d+)", first):
            pending_nom_carte = (m.group(1).strip(), m.group(2).strip())
        elif m := re.match(r"Solde au (\d{2}/\d{2}/\d{4})\s+([\d\s]+,\d{2})", first):
            nom, carte = pending_nom_carte or (None, None)
            compte_courant = {
                "nom": nom,
                "numero_carte": carte,
                "solde_date": m.group(1),
                "solde": to_float(m.group(2)),
                "operations": [],
            }
            result["comptes"].append(compte_courant)
        elif re.match(r"^\d{2}/\d{2}/\d{4}$", first) and compte_courant:
            compte_courant["operations"].append(
                {
                    "date": first,
                    "libelle": clean_libelle(row[1]) if len(row) > 1 else "",
                    "debit": to_float(row[2]) if len(row) > 2 else None,
                    "credit": to_float(row[3]) if len(row) > 3 else None,
                }
            )

    return result


def document_fetcher(document: dict[str, Any]) -> str:
    Path(f"data/exports/{document['libelleTypeDocument']}").mkdir(
        parents=True, exist_ok=True
    )

    if document["formatDocument"] == "application/pdf":
        file_path = Path(
            f"data/exports/{document['libelleTypeDocument']}/{document['id']}.pdf"
        )

        if not file_path.is_file():
            if document["libelleTypeDocument"] == "Relevés":
                fixed_libelle = (
                    urllib.parse.quote(
                        document["libelle"]
                        + "_"
                        + document["contrat"]["id"].replace(".", "")
                    ).replace("/", "-")
                    + ".pdf"
                )
            else:
                fixed_libelle = urllib.parse.quote(document["libelle"])
            try:
                pdf_bytes = regular_get(
                    f"https://hubdocumentaire.credit-agricole.fr{load_preferences().get('regional_branch')}bff/api/hub/download_document/{fixed_libelle}?document_id={urllib.parse.quote(document['id'])}&key_id={document['key']}&origine={document['origine']}&format={document['formatDocument']}&categorie_id={document['idCategorie']}",
                    "data",
                )
            except ApiError as e:
                raise HTTPException(
                    status_code=e.code,
                    detail="Failed to call Credit Agricole API, please try again later",
                )

            if isinstance(pdf_bytes, bytes):
                with open(file_path, "wb") as fichier:
                    _ = fichier.write(pdf_bytes)

        return f"http://{get_local_ip()}:{load_preferences().get('api_port')}/exports/{document['libelleTypeDocument']}/{document['id']}.pdf"

    return ""
