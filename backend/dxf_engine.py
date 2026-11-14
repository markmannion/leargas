#!/usr/bin/env python3
"""Inspect, query or batch-extract Swiss DXFs without consulting gold answers."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

from ezdxf import DXFError

from app.dxf import CannotVerify, Query, parse_dxf, resolve_twin


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("parse", "query"):
        command = commands.add_parser(name)
        command.add_argument("path", type=Path)
        command.add_argument("--dataset-root", type=Path, help="Resolve the path's same-stem DXF under this root")
        if name == "query":
            command.add_argument("query_json", help='e.g. {"operation":"count","kind":"window"}')
    batch = commands.add_parser("batch")
    batch.add_argument("root", type=Path, help="Swiss DXF directory (searched recursively)")
    batch.add_argument("--output", required=True, type=Path, help="Local JSONL extraction; keep derived data private")
    batch.add_argument("--report", required=True, type=Path)
    batch.add_argument("--expected-count", type=int, help="Fail if the discovered file count differs")
    args = parser.parse_args(argv)
    if args.command != "batch":
        try:
            path = resolve_twin(args.path, args.dataset_root) if args.dataset_root else args.path
            drawing = parse_dxf(path)
            result = (drawing.to_dict() if args.command == "parse" else
                      asdict(drawing.query(Query(**json.loads(args.query_json)))))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, TypeError, DXFError) as error:
            print(json.dumps({"status": "cannot_verify", "explanation": str(error)}))
            return 1
    if args.output.resolve() == args.report.resolve():
        parser.error("--output and --report must be different files")
    paths = sorted(p for p in args.root.rglob("*") if p.is_file() and p.suffix.lower() == ".dxf")
    if args.expected_count is not None and args.expected_count != len(paths):
        print(f"Expected {args.expected_count} DXFs; found {len(paths)}. No output written.", file=sys.stderr)
        return 2
    if not paths:
        print("No DXFs found. No output written.", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    objects, warnings, errors = Counter(), [], []
    parsed, supported = 0, 0
    # Per-file failures are explicit in the report; one broken drawing does not
    # prevent inspecting the rest of a large corpus.
    with args.output.open("w", encoding="utf-8") as stream:
        for path in paths:
            try:
                drawing = parse_dxf(path)
                stream.write(json.dumps(drawing.to_dict(), ensure_ascii=False) + "\n")
                parsed += 1
                supported += drawing.profile == "swiss_dwellings"
                objects.update(i.kind for i in drawing.items)
                if drawing.warnings:
                    warnings.append({"path": str(path), "warnings": drawing.warnings})
            except Exception as error:
                errors.append({"path": str(path), "error": f"{type(error).__name__}: {error}"})
    report = {"discovered": len(paths), "parsed": parsed, "supported": supported,
              "objects": dict(objects), "warnings": warnings, "errors": errors}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"warnings", "errors"}}))
    return 1 if errors or supported != len(paths) else 0


if __name__ == "__main__":
    raise SystemExit(main())
