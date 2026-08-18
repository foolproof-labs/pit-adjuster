"""Tiny JSON/JSONL IO helpers (stdlib only).

Bars and actions are plain JSON; a path or a list are interchangeable
inputs, so the library works on both files and in-memory data.
"""

from __future__ import annotations

import json
import os
from typing import Any


def read_json(path: str | os.PathLike[str]) -> Any:
    """Read one JSON document from a file."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: str | os.PathLike[str]) -> list[Any]:
    """Read a JSON-lines file into a list of records."""
    rows: list[Any] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: str | os.PathLike[str], value: Any) -> None:
    """Write a JSON document, atomically via a temp file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_bars(source: str | os.PathLike[str] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept a path (JSON or JSONL) or an in-memory list of bars."""
    if isinstance(source, list):
        return source
    text = os.fspath(source)
    if text.endswith(".jsonl"):
        return [row for row in read_jsonl(text) if isinstance(row, dict)]
    loaded = read_json(text)
    if isinstance(loaded, list):
        return [row for row in loaded if isinstance(row, dict)]
    raise ValueError(f"bars source must be a JSON list of objects: {text}")


def load_actions(source: str | os.PathLike[str] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept a path (JSON or JSONL) or an in-memory list of actions."""
    if isinstance(source, list):
        return source
    text = os.fspath(source)
    if text.endswith(".jsonl"):
        return [row for row in read_jsonl(text) if isinstance(row, dict)]
    loaded = read_json(text)
    if isinstance(loaded, list):
        return [row for row in loaded if isinstance(row, dict)]
    raise ValueError(f"actions source must be a JSON list of objects: {text}")
