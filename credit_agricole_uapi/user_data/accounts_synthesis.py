from credit_agricole_uapi.api_server import app, regular_get
from credit_agricole_uapi.utils.cleaners import bank_product_cleaner
from credit_agricole_uapi.utils.models import GenericAccountResponse


@app.get(
    "/api/accounts",
    tags=["Account"],
    summary="Get accounts data",
    description=("Returns the list of the customer's accounts (cash and securities)."),
    response_description="List of accounts.",
    response_model=list[GenericAccountResponse],
)
def get_accounts_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=COMPTES",
        "COMPTES",
        bank_product_cleaner,
    )


@app.get(
    "/api/insurances",
    tags=["Insurance"],
    summary="Get insurance data",
    description=("Returns the list of the customer's insurance data."),
    response_description="List of insurance.",
)
def get_insurance_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=ASSURANCES",
        "ASSURANCES",
        bank_product_cleaner,
    )


@app.get(
    "/api/savings",
    tags=["Savings"],
    summary="Get savings data",
    description=("Returns the list of the customer's savings data."),
    response_description="List of savings.",
    response_model=list[GenericAccountResponse],
)
def get_savings_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=EPARGNE",
        "EPARGNE",
        bank_product_cleaner,
    )


@app.get(
    "/api/loans",
    tags=["Loans"],
    summary="Get loans data",
    description=("Returns the list of the customer's loans data."),
    response_description="List of loans.",
)
def get_loans_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=CREDITS",
        "CREDITS",
        bank_product_cleaner,
    )


@app.get(
    "/api/investments",
    tags=["Investments"],
    summary="Get investments data",
    description=("Returns the list of the customer's investments data."),
    response_description="List of investments.",
)
def get_investments_data():
    return regular_get(
        "https://espace-client.credit-agricole.fr/bff/api/synthesis/contract/data?code_grande_famille=PLACEMENTS",
        "PLACEMENTS",
        bank_product_cleaner,
    )
