# Old School Document Classification

This project processes PDFs, images, spreadsheets and emails through the OpenRouter Chat Completions API using `openai/gpt-5.6-luna` by default.

## Current structure

The project is split into modules:

- `ingest.py` - file discovery, Excel extraction, and email metadata/attachment extraction
- `classify.py` - prompt generation, model calls, schema validation, and response parsing
- `main.py` - CLI entry point and table output
- `test_model.py` - evaluation script for known test cases

## Current behavior

The workflow is:

- scan the `input/` directory recursively
- select supported PDF, image, Excel and `.eml` files
- for spreadsheets, extract sheet names and row-by-row text in a structured format
- for emails, extract subject, sender, recipient and body
- if supported attachments are present, classify the attachment(s) and choose the strongest attachment result as the email result
- if no supported attachment is found, classify the email body itself as normal, including the `missing_attachment` flag when the body says a document was attached or enclosed but none was found
- print a tabular summary for each file showing file name, type, reasoning, and cost in USD

## Supported file types

- PDF (`.pdf`)
- Images (`.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.gif`)
- Excel (`.xlsx`, `.xlsm`, `.xls`)
- Email (`.eml`)

## Assumptions and notes

- Email attachments: when multiple supported attachments are present, the script chooses the single attachment with the highest confidence as the email-level result, and includes disagreement in the evidence if labels differ.
- Missing attachments: if an email body says a document was attached or enclosed but no supported attachment is found, the script sets `missing_attachment` to `true` and still sends the email body to the model for classification. This is meant to catch cover notes and forwarding emails that include the actual document details in the body instead of a file attachment.
- Cover-note-only emails: if the body clearly refers to an absent attachment but contains no actual document content, the model should classify as `other` with `missing_attachment` set to `true`.
- `.xls` limitation: legacy `.xls` files are not supported by `openpyxl`; the script raises a clear error and asks the user to convert to `.xlsx` first.
- Model override: the model name can be set with `OPENROUTER_MODEL` or the `--model` CLI flag. The default remains `openai/gpt-5.6-luna`.

## OpenRouter API contract

This project targets the confirmed model and endpoint:

- Model: `openai/gpt-5.6-luna` (default)
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
  "reasoning": "This is primarily a supplier invoice because it requests payment for goods or services.",
  "missing_attachment": false
}

Allowed labels:

- `supplier_invoice`
- `credit_note`
- `statement`
- `remittance_advice`
- `other`

## Project files

- `ingest.py` - ingestion and extraction logic
- `classify.py` - prompt building and API integration
- `main.py` - CLI entry point
- `prompt.md` - classification prompt template
- `input/` - files to process
- `.env` - local variables
- `.env.example` - sample environment file
- `.gitignore` - local file exclusions
- `requirements.txt` - Python dependencies

## Environment variables

Create a local `.env` file from `.env.example` and set values such as:

- `OPENROUTER_API_KEY=...`
- `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
- `OPENROUTER_MODEL=openai/gpt-5.6-luna`

## Getting started

1. Copy `.env.example` to `.env` and fill in the values.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Place files in `input/`.
4. Run:
   `python main.py --input-dir input`

## Notes

This project intentionally keeps a single model call per document and uses the strict JSON schema to keep the output predictable and reviewable.

## Cost summary reporting

The model evaluation output can be reported in a per-document table showing:

- document name
- predicted category
- short reasoning summary
- cost in USD for that file

A summary section can also report the minimum, maximum, and average cost across the processed documents so the run is easier to compare and review.

