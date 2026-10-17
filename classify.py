from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from ingest import (
    SUPPORTED_ATTACHMENT_EXTENSIONS,
    detect_missing_attachment,
    extract_email_metadata,
    extract_excel_text,
    file_to_data_url,
)


JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": [
                "supplier_invoice",
                "credit_note",
                "statement",
                "remittance_advice",
                "other",
            ],
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "reasoning": {"type": "string"},
        "missing_attachment": {"type": "boolean"},
    },
    "required": ["label", "confidence", "evidence", "reasoning", "missing_attachment"],
    "additionalProperties": False,
}


def get_api_key() -> str | None:
    load_dotenv()
    return os.getenv("OPENROUTER_API_KEY") or os.getenv("API_KEY")


def get_model_name() -> str:
    load_dotenv()
    return os.getenv("OPENROUTER_MODEL", "openai/gpt-5.6-luna")


def get_openrouter_base_url() -> str:
    load_dotenv()
    return os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"


def load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompt.md"
    if prompt_path.exists():
        template = prompt_path.read_text(encoding="utf-8")
        return template.replace("{{DOCUMENT_TEXT}}", "").strip()
    return ""


def build_document_prompt(file_path: Path) -> str:
    prompt_template = load_prompt_template()
    if prompt_template:
        return prompt_template

    return (
        "You are a document classification system used by a finance team to categorise incoming supplier-related documents. "
        "Review the supplied document and return only a valid JSON object matching this schema: "
        "{\"label\": \"supplier_invoice|credit_note|statement|remittance_advice|other\", "
        "\"confidence\": 0.0, \"evidence\": [\"specific observation\"], \"reasoning\": \"brief explanation\", "
        "\"missing_attachment\": false}. "
        "Do not include markdown or extra text."
    )


def sanitize_classification_payload(payload: dict[str, Any]) -> dict[str, Any]:
    label = payload.get("label")
    if label not in {"supplier_invoice", "credit_note", "statement", "remittance_advice", "other"}:
        raise ValueError(f"Invalid label returned by model: {label!r}")

    confidence = payload.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid confidence returned by model: {confidence!r}") from exc

    if confidence_value < 0 or confidence_value > 1:
        raise ValueError(f"Confidence must be between 0 and 1, got {confidence_value}")

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) for item in evidence):
        raise ValueError("Evidence must be a non-empty list of strings.")

    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("Reasoning must be a non-empty string.")

    missing_attachment = payload.get("missing_attachment")
    if not isinstance(missing_attachment, bool):
        raise ValueError("missing_attachment must be a boolean.")

    return {
        "label": label,
        "confidence": round(confidence_value, 4),
        "evidence": [str(item).strip() for item in evidence if str(item).strip()],
        "reasoning": reasoning.strip(),
        "missing_attachment": missing_attachment,
    }


def parse_structured_response(raw_content: str | None) -> dict[str, Any]:
    if not raw_content:
        raise ValueError("OpenRouter returned an empty response.")

    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response was not valid JSON: {cleaned[:200]}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response was not a JSON object.")

    return sanitize_classification_payload(parsed)


def extract_cost(response_json: dict[str, Any]) -> float | None:
    usage = response_json.get("usage") or {}
    if not isinstance(usage, dict):
        return None

    cost_candidates = [
        usage.get("cost"),
        usage.get("cost_usd"),
        usage.get("total_cost"),
        usage.get("total_cost_usd"),
    ]

    for candidate in cost_candidates:
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue

    return None


def build_user_message(file_path: Path) -> dict[str, Any]:
    prompt = build_document_prompt(file_path)
    ext = file_path.suffix.lower()

    if ext == ".eml":
        email_data = extract_email_metadata(file_path)
        missing_attachment = detect_missing_attachment(email_data["body"])
        email_body = email_data["body"] or "No body text found."
        email_text = (
            f"{prompt}\n\n"
            f"Email subject: {email_data['subject']}\n"
            f"From: {email_data['from']}\n"
            f"To: {email_data['to']}\n\n"
            f"Email body:\n{email_body}\n\n"
            f"Attachment files detected: {', '.join(item['filename'] for item in email_data['attachments']) or 'none'}"
        )
        if missing_attachment:
            email_text += "\n\nNote: the email refers to a document being attached or enclosed, but no supported attachment was found."
        return {"role": "user", "content": [{"type": "text", "text": email_text}]}

    if ext in {".xlsx", ".xlsm", ".xls"}:
        spreadsheet_text = extract_excel_text(file_path)
        return {
            "role": "user",
            "content": [{"type": "text", "text": f"{prompt}\n\nStructured spreadsheet content:\n{spreadsheet_text}"}],
        }

    data_url = file_to_data_url(file_path)
    if ext == ".pdf":
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "file", "file": {"filename": file_path.name, "file_data": data_url}},
            ],
        }

    return {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }


def call_openrouter(messages: list[dict[str, Any]], api_key: str, model_name: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": messages,
        "reasoning": {"enabled": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "document_classification",
                "schema": JSON_SCHEMA,
                "strict": True,
            },
        },
    }

    response = requests.post(
        url=f"{get_openrouter_base_url()}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def classify_file(file_path: Path, api_key: str, model_name: str) -> dict[str, Any]:
    message = build_user_message(file_path)
    response = call_openrouter([message], api_key, model_name)
    cost_usd = extract_cost(response)
    message_obj = response["choices"][0]["message"]
    structured = parse_structured_response(message_obj.get("content"))
    return {
        "file": file_path.name,
        "result": structured,
        "cost_usd": cost_usd,
    }


def classify_email_attachments(file_path: Path, api_key: str, model_name: str) -> dict[str, Any]:
    email_data = extract_email_metadata(file_path)
    attachments = email_data["attachments"]
    supported_results: list[dict[str, Any]] = []
    total_cost = 0.0

    for attachment in attachments:
        suffix = attachment["extension"]
        with open(file_path.parent / "__tmp_attachment__.bin", "wb") as tmp:
            tmp.write(attachment["payload"])
        temp_path = file_path.parent / "__tmp_attachment__.bin"
        temp_path = temp_path.with_suffix(suffix)
        temp_path.write_bytes(attachment["payload"])
        try:
            result = classify_file(temp_path, api_key, model_name)
            supported_results.append(result)
            if result.get("cost_usd") is not None:
                total_cost += float(result["cost_usd"])
        finally:
            temp_path.unlink(missing_ok=True)

    if not supported_results:
        email_body = email_data["body"]
        missing_attachment = detect_missing_attachment(email_body)
        prompt_message = build_user_message(file_path)
        response = call_openrouter([prompt_message], api_key, model_name)
        structured = parse_structured_response(response["choices"][0]["message"].get("content"))
        structured["missing_attachment"] = missing_attachment
        return {
            "file": file_path.name,
            "result": structured,
            "cost_usd": extract_cost(response),
            "email": email_data,
        }

    best_result = max(supported_results, key=lambda item: float(item["result"].get("confidence", 0.0) or 0.0))
    labels = [item["result"].get("label") for item in supported_results]
    evidence = [
        f"Found {len(supported_results)} supported attachment(s) in the email.",
        f"Selected attachment {best_result['file']} because it had the highest confidence ({best_result['result'].get('confidence')}).",
    ]
    if len(set(labels)) > 1:
        evidence.append(f"Attachment labels disagreed: {', '.join(sorted(set(labels)))}. Review manually.")

    final_result = {
        "label": best_result["result"]["label"],
        "confidence": best_result["result"]["confidence"],
        "evidence": evidence,
        "reasoning": (
            f"The email was classified using the attachment with the highest-confidence result: "
            f"{best_result['file']} ({best_result['result']['label']}). "
            f"This is the best-supported attachment among the email's supported files."
        ),
        "missing_attachment": False,
    }

    return {
        "file": file_path.name,
        "result": final_result,
        "cost_usd": total_cost,
        "email": email_data,
        "attachments": supported_results,
    }
