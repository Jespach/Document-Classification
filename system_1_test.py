from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from email import policy
from email.parser import BytesParser
from openpyxl import load_workbook
from pypdf import PdfReader
from PIL import Image
import pytesseract
import re


LABELS = [
    "supplier_invoice",
    "credit_note",
    "statement",
    "remittance_advice",
    "other",
]

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".eml",
}


def get_api_key() -> str | None:
    load_dotenv()
    return os.getenv("OPENROUTER_API_KEY") or os.getenv("API_KEY")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as exc:
        return f"PDF extraction failed: {exc}"


def extract_image_text(path: Path) -> str:
    try:
        with Image.open(path) as img:
            text = pytesseract.image_to_string(img)
        return text or "No OCR text found in image."
    except Exception as exc:
        return f"Image OCR failed: {exc}"


def extract_excel_text(path: Path) -> str:
    if path.suffix.lower() == ".xls":
        raise ValueError("Legacy .xls files are not supported by openpyxl. Please convert to .xlsx first.")

    workbook = load_workbook(path, read_only=True, data_only=True)
    sections: list[str] = []
    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        sheet_lines = [f"Sheet: {sheet.title}"]
        for row_index, row in enumerate(rows, start=1):
            cleaned = ["" if value is None else str(value).strip() for value in row]
            if not any(cleaned):
                continue
            sheet_lines.append(f"Row {row_index}: | " + " | ".join(cleaned))
        if len(sheet_lines) > 1:
            sections.append("\n".join(sheet_lines))
    workbook.close()
    return "\n\n".join(sections) if sections else "No rows found in spreadsheet."


def parse_email_body(message) -> str:
    parts: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        if content_type in {"text/plain", "text/html"}:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode("utf-8", errors="replace")
            if text.strip():
                parts.append(text)
    return "\n\n".join(parts)


def parse_email_attachments(message) -> list[str]:
    filenames: list[str] = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        suffix = Path(filename).suffix.lower()
        if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".xlsx", ".xlsm", ".xls"}:
            filenames.append(filename)
    return filenames


def extract_email_text(path: Path) -> str:
    raw = path.read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject = (message.get("Subject") or "").strip()
    sender = (message.get("From") or "").strip()
    recipient = (message.get("To") or "").strip()
    body = parse_email_body(message)
    attachments = parse_email_attachments(message)
    parts = [
        f"Email subject: {subject}",
        f"From: {sender}",
        f"To: {recipient}",
        f"Body: {body or 'No body text found.'}",
        f"Attachments: {', '.join(attachments) if attachments else 'none'}",
    ]
    return "\n".join(parts)


def convert_file_to_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return normalize_text(extract_pdf_text(path))
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}:
        return normalize_text(extract_image_text(path))
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return normalize_text(extract_excel_text(path))
    if suffix == ".eml":
        return normalize_text(extract_email_text(path))
    return normalize_text(path.read_text(encoding="utf-8", errors="replace"))


def build_jev_payload(file_name: str, document_text: str) -> dict[str, Any]:
    prompt_text = (
        "Classify the document content below. "
        "Use the document content only; do not add assumptions. "
        f"Document file: {file_name}\n\n{document_text}"
    )

    return {
        "model": "~typesafe/jev-latest",
        "state": [
            prompt_text,
        ],
        "questions": {
            "label": {
                "type": "choice",
                "instructions": "Which finance document category best fits the extracted document text?",
                "criteria": {
                    "supplier_invoice": "Supplier invoice or supplier bill for payment.",
                    "credit_note": "Credit note issued to reduce an amount owed.",
                    "statement": "Bank or account statement summarizing transactions.",
                    "remittance_advice": "Payment remittance or payment advice document.",
                    "other": "Anything else or a non-matching document type."
                },
            },
            "confidence": {
                "type": "noul",
                "instructions": "How confident is the classification based only on the extracted document text?",
                "criteria": {
                    "true": "The selected label is correct.",
                    "false": "The selected label is uncertain or wrong."
                },
            },
            "evidence": {
                "type": "choice",
                "instructions": "Pick the strongest type of support visible in the text.",
                "criteria": {
                    "invoice_number": "Contains an invoice number or billing details.",
                    "credit_reference": "Contains credit memo or adjustment details.",
                    "transaction_summary": "Contains statement summary or transaction totals.",
                    "payment_reference": "Contains remittance or payment advice details.",
                    "other_text": "The text is general or unclear and does not strongly support a specific label."
                },
            },
        },
    }


def parse_jev_response(response_json: dict[str, Any]) -> dict[str, Any]:
    answers = response_json.get("answers") or {}

    label_choice = answers.get("label", {}).get("choice") or "other"
    if label_choice not in LABELS:
        label_choice = "other"

    confidence_value = answers.get("confidence", {}).get("noul")
    try:
        confidence = float(confidence_value)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence_choice = answers.get("evidence", {}).get("choice") or "other_text"
    evidence_map = {
        "invoice_number": "The extracted text includes invoice or billing reference details.",
        "credit_reference": "The extracted text includes credit note or adjustment details.",
        "transaction_summary": "The extracted text includes transaction summary or account activity details.",
        "payment_reference": "The extracted text includes remittance or payment confirmation details.",
        "other_text": "The extracted text does not strongly indicate a more specific document type.",
    }

    evidence = [evidence_map.get(evidence_choice, "The document text was evaluated for document type and context.")]
    reasoning = (
        f"The JEV model classified the document as {label_choice} with a confidence of {confidence:.2f}. "
        f"This was determined from the extracted text that was converted before model evaluation."
    )

    return {
        "label": label_choice,
        "confidence": round(confidence, 4),
        "evidence": evidence,
        "reasoning": reasoning,
        "missing_attachment": False,
    }


def call_jev_api(file_name: str, file_text: str, api_key: str) -> dict[str, Any]:
    payload = build_jev_payload(file_name, file_text)
    response = requests.post(
        url="https://openrouter.ai/api/alpha/decisions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    return parse_jev_response(data)


def iter_supported_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    return sorted(files, key=lambda p: str(p).lower())


def extract_price_from_text(text: str) -> str:
    if not text:
        return "n/a"

    matches = re.findall(r"(?:R\s*|\$\s*)?(\d{1,3}(?:[ ,]\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)", text)
    if not matches:
        return "n/a"

    cleaned: list[float] = []
    for match in matches:
        normalized = match.replace(",", "").replace(" ", "")
        try:
            value = float(normalized)
            if value >= 1:
                cleaned.append(value)
        except ValueError:
            continue

    if not cleaned:
        return "n/a"

    # Prefer the largest plausibly meaningful amount seen in the document.
    return f"R {max(cleaned):,.2f}"


def format_table_row(file_name: str, label: str, confidence: float, price: str) -> str:
    return f"{file_name:<35} | {label:<18} | {price:>14} | {confidence:>10.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify supported documents using the OpenRouter JEV API after converting them to text.")
    parser.add_argument("--input-dir", default="Input", help="Directory containing the files to classify.")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("No OpenRouter API key found. Add OPENROUTER_API_KEY or API_KEY to your .env file.")
        return

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"Input directory does not exist: {input_dir}")
        return

    files = iter_supported_files(input_dir)
    if not files:
        print(f"No supported files found in {input_dir}")
        return

    results: list[dict[str, Any]] = []
    for file_path in files:
        text = convert_file_to_text(file_path)
        result = call_jev_api(file_path.name, text, api_key)
        result["file"] = file_path.name
        result["source_text_preview"] = text[:500]
        results.append(result)

    print(f"{'File':<35} | {'Category':<18} | {'Price':>14} | {'Confidence':>10}")
    print("-" * 110)
    for result in results:
        label = result.get("label", "unknown")
        confidence = float(result.get("confidence", 0.0) or 0.0)
        price = extract_price_from_text(result.get("source_text_preview", ""))
        print(f"{result.get('file', 'unknown'):<35} | {label:<18} | {price:>14} | {confidence:>10.2f}")

    print("-" * 110)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved full results to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
