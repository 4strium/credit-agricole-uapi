from typing import Literal

from pydantic import BaseModel, Field

# Request models

APPROVED_DOC_TYPES = Literal["Relevés", "Contrats", "Autres"]


class DocumentRequest(BaseModel):
    """Request model for downloading a document by its ID."""

    id: str = Field(
        ...,
        description="The ID of the document to retrieve",
        examples=["12345678"],
    )


class DocumentTypeRequest(BaseModel):
    """Request model for downloading documents by their type."""

    type: APPROVED_DOC_TYPES = Field(
        ...,
        description="The type of the document to retrieve",
        examples=["Relevés"],
    )


class TransactionParams(BaseModel):
    amount: float = Field(..., description="The amount to transfer", examples=[100.0])
    motif: str = Field(
        ...,
        description="The reason of the transfer",
        examples=["Reimbursement for the restaurant meal", "Christmas gift"],
    )
    additional_motif: str = Field(
        ...,
        description="The additional reason of the transfer",
        examples=["Refund for invoice no. 47583216"],
    )
    source_account_iban: str = Field(
        ...,
        description="The IBAN of the source account (must be one of the user's accounts)",
        examples=["FR4014508000307377664456G07"],
    )
    recipient_account_iban: str = Field(
        ...,
        description="The IBAN of the recipient account (must be one of the user's accounts or appear in their list of beneficiaries)",
        examples=["FR6210096000304733763795P54"],
    )


class AddBeneficiaryRequest(BaseModel):
    name: str = Field(
        ...,
        description="The name of the beneficiary (as displayed in the bank statement)",
        examples=["John Doe"],
    )
    iban: str = Field(
        ...,
        description="The IBAN of the beneficiary",
        examples=["FR6210096000304733763795P54"],
    )
    identifier: str = Field(
        ...,
        description="The private identifier of the beneficiary",
        examples=["Dad", "Mom"],
    )


# Response models


class GenericAccountResponse(BaseModel):
    id_element_contrat: str = Field(
        ...,
        description="The unique identifier of the contract element",
        examples=["003424195754640C42424F2002424C"],
    )
    cdo_niveau3: str = Field(..., description="The CDO niveau 3", examples=["NPC13000"])
    cdo_niveau4: str = Field(..., description="The CDO niveau 4", examples=["RDPx3100"])
    code_grande_famille: str = Field(
        ..., description="The code of the large family", examples=["COMPTES"]
    )
    code_produit: str = Field(
        ..., description="The code of the product", examples=["00001", "00371"]
    )
    libelle: str = Field(
        ...,
        description="The name of the account holder",
        examples=["M.       DOE JOHN"],
    )
    id_partenaire_consommateur: str = Field(
        ..., description="The ID of the partner consumer", examples=["00000023198103"]
    )
    libelle_produit_commercial: str = Field(
        ...,
        description="The commercial name of the product",
        examples=["Compte de Dépôt", "Livret A"],
    )
    code_devise: str = Field(..., description="The currency code", examples=["EUR"])
    numero_compte: str = Field(
        ..., description="The account number", examples=["85123479510"]
    )
    solde: float = Field(..., description="The account balance", examples=[162.77])


class DocumentResponse(BaseModel):
    id: str = Field(..., description="The document unique ID", examples=["45617823"])
    libelle: str = Field(
        ..., description="The document name", examples=["Relevé n°007 du 27/07/2026"]
    )
    date_creation: str = Field(
        ..., description="The document creation date", examples=["2026-07-31"]
    )
    date_fin_dispo: str = Field(
        ..., description="The document availability end date", examples=["2036-07-31"]
    )
    contrat: dict[str, str] = Field(
        ...,
        description="The relative contract information",
        examples=[
            {
                "id": "CCHQ 85123479510 M.       DOE JOHN",
                "libelle": "CCHQ 85123479510 M. DOE JOHN",
            }
        ],
    )
    document_lu: bool = Field(
        ..., description="Whether the document has been read", examples=[True]
    )
    libelle_categorie: str = Field(
        ..., description="The document category", examples=["Comptes"]
    )
    libelle_type_document: str = Field(
        ..., description="The document type", examples=["Relevés"]
    )
    format_document: str = Field(
        ..., description="The document format", examples=["application/pdf"]
    )
    favori: bool = Field(
        ..., description="Whether the document is a favorite", examples=[False]
    )


class DocumentDownloadResult(BaseModel):
    url: str = Field(
        ...,
        description="The document download URL",
        examples=["http://192.168.1.65:8000/exports/Relev%C3%A9s/45617823.pdf"],
    )


class DocumentsDownloadList(BaseModel):
    documents: list[dict[str, str]] = Field(
        ...,
        description="The list of document download results",
        examples=[
            {
                "Relevé n°007 du 27/07/2026": "http://192.168.1.65:8000/exports/Relevés/45617823.pdf"
            },
            {
                "Relevé n°006 du 26/06/2026": "http://192.168.1.65:8000/exports/Relevés/45617822.pdf"
            },
            {
                "Relevé n°005 du 27/05/2026": "http://192.168.1.65:8000/exports/Relevés/45617821.pdf"
            },
            {
                "Relevé n°002 du 27/05/2026": "http://192.168.1.65:8000/exports/Relevés/45617820.pdf"
            },
        ],
    )
