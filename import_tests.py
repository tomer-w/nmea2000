#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import canboatjs PGN fixtures into a single JSON file without "
            "executing canboatjs."
        )
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default="../canboatjs/test/pgns",
        help="Directory containing canboatjs test fixture modules",
    )
    parser.add_argument(
        "output_file",
        nargs="?",
        default="tests/canboatjs_roundtrip.json",
        help="Output JSON file path",
    )

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent
    args.input_dir = (repo_root / args.input_dir).resolve()
    args.output_file = (repo_root / args.output_file).resolve()
    return args


def list_fixture_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.js"), key=lambda path: int(path.stem))


def _strip_module_wrapper(text: str, source_path: Path) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines or not lines[0].strip().startswith("module.exports = ["):
        raise ValueError(f"{source_path.name} is missing the module.exports wrapper")
    if lines[-1].strip() not in {"]", "];"}:
        raise ValueError(f"{source_path.name} does not end with a closing array")

    return "[\n" + "\n".join(lines[1:-1]) + "\n]"


def _convert_jsish_to_python_literal(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    quote_char = ""
    escape = False

    while index < len(text):
        char = text[index]

        if in_string:
            output.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote_char:
                in_string = False
            index += 1
            continue

        if char in {"'", '"'}:
            in_string = True
            quote_char = char
            output.append(char)
            index += 1
            continue

        if char.isalpha() or char == "_":
            end_index = index + 1
            while end_index < len(text) and (
                text[end_index].isalnum() or text[end_index] == "_"
            ):
                end_index += 1

            token = text[index:end_index]

            previous_index = index - 1
            while previous_index >= 0 and text[previous_index].isspace():
                previous_index -= 1
            previous_char = text[previous_index] if previous_index >= 0 else ""

            next_index = end_index
            while next_index < len(text) and text[next_index].isspace():
                next_index += 1

            if next_index < len(text) and text[next_index] == ":" and previous_char in {
                "{",
                ",",
            }:
                output.append(repr(token))
            elif token == "true":
                output.append("True")
            elif token == "false":
                output.append("False")
            elif token == "null":
                output.append("None")
            else:
                output.append(token)

            index = end_index
            continue

        output.append(char)
        index += 1

    return "".join(output)


def load_fixture_cases(fixture_path: Path) -> list[dict]:
    module_text = fixture_path.read_text(encoding="utf-8")
    python_literal = _convert_jsish_to_python_literal(
        _strip_module_wrapper(module_text, fixture_path)
    )
    fixture_cases = ast.literal_eval(python_literal)
    if not isinstance(fixture_cases, list):
        raise ValueError(f"{fixture_path.name} does not export a list of fixtures")
    if not all(isinstance(case, dict) for case in fixture_cases):
        raise ValueError(f"{fixture_path.name} contains a non-object fixture case")
    return fixture_cases


def convert_fixtures(input_dir: Path, output_file: Path) -> dict:
    cases: list[dict] = []

    for fixture_path in list_fixture_files(input_dir):
        pgn = int(fixture_path.stem)
        for case_index, fixture in enumerate(load_fixture_cases(fixture_path)):
            case = {
                "pgn": pgn,
                "sourceFile": fixture_path.name,
                "caseIndex": case_index,
                "input": fixture["input"],
                "expected": fixture["expected"],
            }
            if "format" in fixture:
                case["format"] = fixture["format"]
            if "skipEncoderTest" in fixture:
                case["skipEncoderTest"] = fixture["skipEncoderTest"]
            cases.append(case)

    output = {
        "generatedAt": None,
        "sourceDirectory": str(input_dir),
        "caseCount": len(cases),
        "cases": cases,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    output = convert_fixtures(args.input_dir, args.output_file)
    print(f"Wrote {output['caseCount']} test cases to {args.output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
