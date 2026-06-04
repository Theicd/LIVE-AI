#!/usr/bin/env python3
"""Rebuild archive/manifest.json after adding new HTML files to archive/."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "archive"
MANIFEST = ARCHIVE / "manifest.json"
MIN_HTML_BYTES = 500


def main() -> None:
    files: list[dict] = []
    for html in ARCHIVE.glob("index-4.7-VER*.html"):
        size = html.stat().st_size
        if size < MIN_HTML_BYTES:
            continue
        modified = datetime.fromtimestamp(html.stat().st_mtime).isoformat()
        entry: dict = {
            "name": f"archive/{html.name}",
            "size": size,
            "modified": modified,
        }
        meta_path = html.with_suffix(".json")
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("prompt"):
                    entry["prompt"] = str(meta["prompt"]).strip()
                if meta.get("promptIndex") is not None:
                    entry["promptIndex"] = meta["promptIndex"]
            except (json.JSONDecodeError, OSError):
                pass
        files.append(entry)

    files.sort(key=lambda x: x["modified"], reverse=True)
    payload = {
        "ok": True,
        "updated": datetime.now().isoformat(),
        "count": len(files),
        "files": files,
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[manifest] Wrote {len(files)} entries -> {MANIFEST}")


if __name__ == "__main__":
    main()
