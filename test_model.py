from __future__ import annotations

import argparse
from pathlib import Path

from classify import classify_file, get_api_key, get_model_name


# Update this mapping if you want to override the expected label for any case.
EXPECTED_LABELS = {
    "Karoo Knitwear - 10482.pdf": "supplier_invoice",
    "BPE_CN0087.pdf": "credit_note",
    "Statement_Sep2026_ATM.pdf": "statement",
    "Remittance - Touchline Sports.pdf": "remittance_advice",
    "Cape Swing Tags 2291.pdf": "supplier_invoice",
    "HL-INV-55031.pdf": "supplier_invoice",
}


def iter_test_files(folder: Path):
    if not folder.exists():
        return []
    files = [p for p in folder.iterdir() if p.is_file()]
    return sorted(files, key=lambda p: p.name.lower())


def run_case(file_path: Path, api_key: str, model_name: str):
    result = classify_file(file_path, api_key, model_name)
    predicted = result["result"].get("label")
    expected = EXPECTED_LABELS.get(file_path.name)

    passed = False
    if expected is not None:
        passed = predicted == expected

    return {
        "file": file_path.name,
        "expected": expected,
        "predicted": predicted,
        "passed": passed,
        "reasoning": result["result"].get("reasoning", ""),
        "confidence": result["result"].get("confidence"),
        "cost_usd": result.get("cost_usd"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run model evaluation against known test cases in the test_cases folder.")
    parser.add_argument("--folder", default="test_cases", help="Folder containing test documents.")
    parser.add_argument("--model", default=None, help="Model name for OpenRouter. Defaults to OPENROUTER_MODEL or openai/gpt-5.6-luna.")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("No OpenRouter API key found. Add OPENROUTER_API_KEY or API_KEY to your .env file.")
        return

    model_name = args.model or get_model_name()
    folder = Path(__file__).resolve().parent / args.folder
    files = iter_test_files(folder)
    if not files:
        print(f"No files found in {folder}")
        return

    passed_count = 0
    total_count = 0
    total_cost = 0.0

    print(f"Testing {len(files)} files in {folder}")
    print(f"{'File':<35} | {'Expected':<22} | {'Actual':<22} | {'Status':<8} | {'Confidence':>10} | {'Cost (USD)':>12}")
    print("-" * 140)

    for file_path in files:
        total_count += 1
        case = run_case(file_path, api_key, model_name)
        expected = case["expected"] if case["expected"] is not None else "n/a"
        actual = case["predicted"] if case["predicted"] is not None else "n/a"
        status = "PASS" if case["passed"] else "FAIL"
        if case["passed"]:
            passed_count += 1
        if case["cost_usd"] is not None:
            total_cost += float(case["cost_usd"])

        print(
            f"{file_path.name:<35} | {str(expected):<22} | {str(actual):<22} | {status:<8} | "
            f"{case['confidence'] if case['confidence'] is not None else 'n/a':>10} | {case['cost_usd'] if case['cost_usd'] is not None else 'n/a':>12}"
        )

    print("-" * 140)
    print(f"Summary: {passed_count}/{total_count} passed | Total cost: ${total_cost:.6f}")


if __name__ == "__main__":
    main()
