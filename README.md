# Crédit Agricole Unofficial API

> ⚠️ Disclaimer: this project is unofficial and is not affiliated with Crédit Agricole S.A., Use at your own risk. Endpoints that perform transactions or modify your account will act on real accounts when the server is authenticated.

Lightweight local REST API that reuses an authenticated Crédit Agricole web session to expose convenient endpoints for account data, documents and transfers.

## How it works

1. The program authenticates via the official Crédit Agricole flow (the server must establish the bank session at startup).
2. A local FastAPI server runs and forwards requests to Crédit Agricole's private REST endpoints (reusing the authenticated session).
3. You call the local endpoints to read account data, download documents, create beneficiaries and perform transfers.

Important: no external API key is required to call the local server, but the server itself must be logged in to Crédit Agricole.

## Running the API server

### Option 1: via pip (recommended)
```bash
  pip install credit-agricole-uapi
  credit-agricole-uapi
```

### Option 2: from source (development)
Create a venv, install requirements and run the package entrypoint (adjust the command if your project uses a different CLI module):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m credit_agricole_uapi.cli
```

The server listens on the port configured in preferences (default shown by the CLI). Interactive docs are available once the server runs (see below).

## Interactive API documentation

If the server runs using FastAPI, visit:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Raw OpenAPI JSON: http://127.0.0.1:8000/openapi.json

Replace host/port if your configuration uses different values.

## Endpoints

All endpoints are served from your running instance base URL (for example `http://127.0.0.1:8000`). The API mounts a static `/exports` directory where downloaded documents (PDFs) are served.

Summary of available endpoints (from `credit_agricole_uapi/api_server.py`):

- GET `/api/accounts` — Account
  - Summary: Get accounts data (cash & securities)
  - Returns: list of bank product objects (cleaned)

- GET `/api/insurances` — Insurance
  - Summary: Get insurance data
  - Returns: list of insurance product objects

- GET `/api/savings` — Savings
  - Summary: Get savings products
  - Returns: list of savings product objects

- GET `/api/loans` — Loans
  - Summary: Get loans data
  - Returns: list of loan product objects

- GET `/api/investments` — Investments
  - Summary: Get investments / placements data
  - Returns: list of investment product objects

- GET `/api/documents-list` — Documents
  - Summary: List available documents
  - Returns: list of documents (metadata)

- GET `/api/transaction-accounts` — Transactions
  - Summary: Get transaction-enabled accounts and known beneficiaries
  - Returns: object with `internal` (accounts) and `external` (beneficiaries)

- POST `/api/transaction` — Transactions
  - Summary: Carry out a transaction (single transfer)
  - Request body: TransactionParams (see schema below)
  - Returns: confirmation message (or HTTP error)

- POST `/api/add-beneficiary` — Beneficiaries
  - Summary: Add a beneficiary to the user's account (triggers phone auth)
  - Request body: AddBeneficiaryRequest (see schema below)
  - Returns: result message including activation date

- GET `/api/transactions` — Transactions
  - Summary: Retrieve the last year of transactions (CSV parsed)
  - Returns: list of accounts with their operations (parsed from CSV)

- POST `/api/document-by-id` — Documents
  - Summary: Download a document by its ID
  - Request body: DocumentRequest (id)
  - Returns: `{ "url": "<local exports URL>" }` if found, otherwise `{}`

- POST `/api/document-by-type` — Documents
  - Summary: Download documents by type (e.g. statements)
  - Request body: DocumentTypeRequest (type: `"Relevés" | "Contrats" | "Autres"`)
  - Returns: list of `{ "<document_label>": "<local exports URL>" }` pairs

## Request schemas

- DocumentRequest
```json
{ "id": "12345678" }
```

- DocumentTypeRequest
```json
{ "type": "Relevés" }  // allowed: "Relevés", "Contrats", "Autres"
```

- TransactionParams
```json
{
  "amount": 125.00,
  "motif": "Invoice payment",
  "additional_motif": "June 2026 invoice #1234",
  "source_account_iban": "FR7612345987650123456789014",
  "recipient_account_iban": "FR7611111122222333334444455"
}
```

- AddBeneficiaryRequest
```json
{
  "name": "John Doe",
  "iban": "FR7611111122222333334444455",
  "identifier": "John personal account"
}
```

## Documents and exports

Downloaded PDFs are stored under `data/exports/<DocumentType>/<document_id>.pdf` and served from the local server via the `/exports` static mount. The API returns local HTTP URLs pointing to those exports (e.g. `http://<local-ip>:<api_port>/exports/Relevés/12345.pdf`).

## Examples

Replace example values with your own. These assume the server runs on `http://127.0.0.1:8000`.

- List accounts:
```bash
curl -s -X GET "http://127.0.0.1:8000/api/accounts"
```

- Get transactions (last year, parsed):
```bash
curl -s -X GET "http://127.0.0.1:8000/api/transactions"
```

- Get transaction-enabled accounts and beneficiaries:
```bash
curl -s -X GET "http://127.0.0.1:8000/api/transaction-accounts"
```

- Make a transfer:
```bash
curl -s -X POST "http://127.0.0.1:8000/api/transaction" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 50.0,
    "motif": "Gift",
    "additional_motif": "Birthday",
    "source_account_iban": "FR7612345987650123456789014",
    "recipient_account_iban": "FR7611111122222333334444455"
  }'
```

- Add a beneficiary (this triggers an authentication request to your phone):
```bash
curl -s -X POST "http://127.0.0.1:8000/api/add-beneficiary" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "iban": "FR7611111122222333334444455",
    "identifier": "John personal account"
  }'
```

- List documents:
```bash
curl -s -X GET "http://127.0.0.1:8000/api/documents-list"
```

- Download a specific document by ID:
```bash
curl -s -X POST "http://127.0.0.1:8000/api/document-by-id" \
  -H "Content-Type: application/json" \
  -d '{"id":"12345678"}'
```

- Download documents by type:
```bash
curl -s -X POST "http://127.0.0.1:8000/api/document-by-type" \
  -H "Content-Type: application/json" \
  -d '{"type":"Relevés"}'
```

## Notes on responses

- The transactions endpoint generates a CSV file via the bank API, then parses it into a JSON structure (see `parse_releve` in `api_server.py`) and returns the parsed `comptes` list with each account's operations.
- Document download endpoints return a local URL pointing to the exported PDF if the file could be retrieved and saved under `data/exports`.

## Security & responsibility

- This is an unofficial project. Do not store credentials in plaintext. Be careful: endpoints that create transfers or add beneficiaries will act on real accounts when your server session is authenticated.
- Test carefully and prefer simulation or non-critical accounts before running transfers on production accounts.
- The project author is not responsible for any loss or misuse.

## Development & contribution

Contributions are welcome: bug reports, documentation fixes, tests and improvements. Open an issue or a pull request with a clear description of the change.
