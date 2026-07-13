#!/usr/bin/env python3
import argparse
import csv
import json
import os
from pathlib import Path


FIELDS = ["id", "task", "status", "assigned", "created", "updated", "scope", "tags", "roles", "path", "mtime"]


def parse_frontmatter(path):
    text = path.read_text(errors="ignore")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data = {}
    current = None
    for raw in text[4:end].splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current:
            data.setdefault(current, []).append(line[4:].strip())
            continue
        if line.startswith("  ") and current:
            data.setdefault(current, []).append(line.strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current = key.strip()
            value = value.strip()
            if value:
                data[current] = value.strip("\"'")
            else:
                data[current] = []
    return data


def normalize(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return "" if value is None else str(value)


def main():
    parser = argparse.ArgumentParser(description="Build a JSON or TSV index for coord task archives.")
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("--archive-dir", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--format", choices=["json", "tsv"], default=None)
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    archive = Path(args.archive_dir).expanduser().resolve() if args.archive_dir else root / "tasks" / "archive"
    out = Path(args.output).expanduser().resolve()
    fmt = args.format or ("tsv" if out.suffix == ".tsv" else "json")

    rows = []
    for task_file in sorted(archive.glob("*.md")):
        data = parse_frontmatter(task_file)
        if not data:
            continue
        row = {field: normalize(data.get(field)) for field in FIELDS}
        row["path"] = str(task_file)
        row["mtime"] = str(int(task_file.stat().st_mtime))
        rows.append(row)

    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out.write_text(json.dumps(rows, indent=2) + "\n")
    else:
        with out.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
    print(f"indexed {len(rows)} tasks -> {out}")


if __name__ == "__main__":
    main()
