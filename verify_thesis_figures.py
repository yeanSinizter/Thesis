#!/usr/bin/env python3
"""Verify thesis figures: source PNGs, markdown refs, and docx embeds."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
THESIS = ROOT / "thesis_draft.md"
DOCX = ROOT / "thesis_draft.docx"
REPORT = ROOT / "outputs" / "reports" / "thesis_figure_audit.json"

EXPECTED = {
    1: ROOT / "outputs/reports/figures/mermaid/figure_01.png",
    2: ROOT / "outputs/reports/figures/mermaid/figure_02.png",
    3: ROOT / "outputs/reports/figures/rq2_prompt_comparison.png",
    4: ROOT / "outputs/reports/figures/rq3_model_comparison.png",
    5: ROOT / "outputs/reports/figures/vulnerability_by_iteration.png",
}

MIN_BYTES = 10_000
MIN_WIDTH = 300


def _png_meta(path: Path) -> dict:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return {"width": im.width, "height": im.height, "format": im.format}
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    text = THESIS.read_text(encoding="utf-8")
    issues: list[str] = []
    figures: list[dict] = []

    for n, path in EXPECTED.items():
        meta = _png_meta(path) if path.is_file() else {}
        ok = path.is_file() and path.stat().st_size >= MIN_BYTES
        if ok and "width" in meta and meta["width"] < MIN_WIDTH:
            ok = False
            issues.append(f"Figure {n}: width {meta['width']} < {MIN_WIDTH}px")
        if not ok:
            issues.append(f"Figure {n}: missing or too small ({path})")
        in_md = f"Figure {n}" in text or f"figure_{n:02d}" in text
        figures.append(
            {
                "number": n,
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "referenced_in_md": in_md,
                "ok": ok and in_md,
                **meta,
            }
        )

    docx_media = 0
    missing_ph = False
    if DOCX.is_file():
        with zipfile.ZipFile(DOCX) as zf:
            media = [n for n in zf.namelist() if n.startswith("word/media/")]
            docx_media = len(media)
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
            missing_ph = "Missing image" in xml
            caps = len(re.findall(r"Figure\s+[1-5]", xml))
    else:
        caps = 0
        issues.append("thesis_draft.docx not found")

    if docx_media < 5:
        issues.append(f"docx has only {docx_media} media files (expected 5)")
    if missing_ph:
        issues.append("docx contains [Missing image: ...] placeholder")

    out = {
        "figures": figures,
        "docx_media_count": docx_media,
        "docx_figure_mentions": caps,
        "all_ok": len(issues) == 0,
        "issues": issues,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
