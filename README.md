# Old School Document Classification

This project processes PDF and image files one by one through the OpenRouter Chat Completions API using `openai/gpt-5.6-luna`.

## Current behavior

The script in `script.py`:

- scans the `input/` directory recursively
- selects only supported PDF and image files for this stage
- sends each document to OpenRouter's Chat Completions endpoint
- preserves reasoning between the first and second API call
- validates a strict JSON schema response
- prints a tabular summary for each file showing:
  - file name
  - document type
  - reasoning summary
  - cost in USD

## Supported file types for this stage

- PDF (`.pdf`)
- Images (`.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.gif`)

Excel and `.eml` files are intentionally deferred.

## OpenRouter API contract

This project targets the confirmed model and endpoint:

- Model: `openai/gpt-5.6-luna`
- Base URL: `https://openrouter.ai/api/v1`
- Endpoint: `POST /chat/completions`
- Auth: `Authorization: Bearer $OPENROUTER_API_KEY`

The project also supports an alternative base URL via `.env`:

- `OPENROUTER_BASE_URL=https://eu.openrouter.ai/api/v1`

## Strict JSON output contract

Each classification response must follow this schema:

{
  "label": "supplier_invoice",
  "confidence": 0.93,
  "evidence": [
    "The document contains an invoice number and payment amount.",
    "The supplier details and total payable are clearly shown."
  ],
  "reasoning": "This is primarily a supplier invoice because it requests payment for goods or services."
}

Allowed labels:

- `supplier_invoice`
- `credit_note`
- `statement`
- `remittance_advice`
- `other`

## Project files

- `script.py` - ingestion and API workflow
- `prompt.md` - classification prompt template
- `input/` - files to process
- `.env` - environment variables
- `.gitignore` - local file exclusions
- `requirements.txt` - Python dependencies

## Environment variables

Set one of the following in `.env`:

- `OPENROUTER_API_KEY=...`
- `API_KEY=...`

Optional:

- `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`

## Getting started

1. Add your API key to `.env`.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Place files in `input/`.
4. Run:
   `python script.py --input-dir input`

## Output example

File                          | Document Type        | Reasoning                                 | Cost (USD)
----------------------------- | -------------------- | ----------------------------------------- | -----------
ATM_INV_7740.pdf              | supplier_invoice     | ...                                       | $0.000123

## Notes

The output is intentionally structured and tabular so each file can be reviewed quickly and costs can be tracked per document.
