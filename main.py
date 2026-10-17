from __future__ import annotations

import argparse
from pathlib import Path

from classify import classify_file, get_api_key, get_model_name
from ingest import SUPPORTED_EXTENSIONS, list_input_files, resolve_input_dir


def format_table_row(file_name: str, document_type: str, reasoning: str, cost: float | None) -> str:
    clean_reasoning = reasoning.strip().replace("\n", " ")
    if len(clean_reasoning) > 80:
        clean_reasoning = clean_reasoning[:77] + "..."
    cost_label = f"${cost:.6f}" if cost is not None else "n/a"
    return f"{file_name:<30} | {document_type:<18} | {clean_reasoning:<80} | {cost_label}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest supported documents and send each file through OpenRouter for analysis.")
    parser.add_argument("--input-dir", default=None, help="Directory containing documents to analyze. Defaults to ./input or ./Input if present.")
    parser.add_argument("--model", default=None, help="Model name for OpenRouter. Defaults to OPENROUTER_MODEL or openai/gpt-5.6-luna.")
    args = parser.parse_args()

    input_dir = resolve_input_dir(args.input_dir)
    if not input_dir.exists():
        print(f"Input directory does not exist: {input_dir}")
        return

    supported_files = []
    for file_path in list_input_files(input_dir):
        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            supported_files.append(file_path)

    if not supported_files:
        print(f"No supported image, PDF, Excel, or email files found in {input_dir}")
        return

    api_key = get_api_key()
    if not api_key:
        print("No OpenRouter API key found. Add OPENROUTER_API_KEY or API_KEY to your .env file.")
        return

    model_name = args.model or get_model_name()

    print(f"Found {len(supported_files)} supported file(s). Processing...")
    print(f"{'File':<30} | {'Document Type':<18} | {'Reasoning':<80} | {'Cost (USD)'}")
    print("-" * 150)
    for file_path in supported_files:
        try:
            result = classify_file(file_path, api_key, model_name)
            row = format_table_row(
                result["file"],
                result["result"].get("label", "unknown"),
                result["result"].get("reasoning", "No reasoning returned."),
                result.get("cost_usd"),
            )
            print(row)
        except Exception as exc:
            print(format_table_row(file_path.name, "error", str(exc), None))


if __name__ == "__main__":
    main()
