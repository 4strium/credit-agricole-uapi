from typing import Any, cast


def bank_product_cleaner(data: list[dict[str, Any]]) -> None:
    for element in data:
        element.pop("libelle_role_intervenant_contrat", None)
        element.pop("id_parcours", None)
        element.pop("motif_non_valorisation", None)
        element.pop("solde_valeur", None)
        element.pop("code_role_intervenant_contrat", None)
        element.pop("categorie_etablissement", None)
        element.pop("position", None)


def document_attributes_cleaner(data: list[dict[str, Any]]) -> None:
    for element in data:
        element.pop("organisme", None)
        element.pop("origine", None)
        element.pop("documentSize", None)
        element.pop("key", None)
        element.pop("idCategorie", None)
        element.pop("idTypeDocument", None)
        element.pop("titulaire", None)

        contrat = cast(dict[str, Any] | None, element.get("contrat"))

        if (
            contrat is not None
            and contrat.get("id") == ""
            and contrat.get("libelle") == ""
        ):
            element.pop("contrat", None)


def beneficiary_cleaner(data: list[dict[str, Any]]) -> None:
    for element in data:
        element.pop("delay", None)
        element.pop("custom_label", None)
