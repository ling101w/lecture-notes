"""
extract_text.py — Slide / document text extraction.

Strategy
--------
Priority 1 — Original courseware (PDF / PPTX / DOCX / XLSX):
    Use Marker to parse the file into structured Markdown, preserving
    tables, formulas, and code blocks.

Priority 2 — Video keyframes only (no source file):
    Use Surya to OCR each keyframe PNG: layout analysis, reading-order
    reconstruction, and LaTeX math detection.

Output schema (list of dicts, one per slide/page):
[
  {
    "slide_index": int,        # 0-based
    "source": "marker"|"surya",
    "page": int,               # page/slide number in source doc (Marker)
                               # or keyframe index (Surya)
    "timestamp": float|None,   # only set for Surya (from keyframe)
    "frame_path": str|None,    # only set for Surya
    "markdown": str,           # extracted text as Markdown
  }, ...
]
"""

from __future__ import annotations

import os
from typing import Optional


# ── Marker path (PDF / PPTX / DOCX) ──────────────────────────────────────────

def extract_with_marker(doc_path: str) -> list[dict]:
    """
    Parse a structured document (PDF, PPTX, DOCX, XLSX) with Marker.

    Returns one record per page/slide.
    """
    from marker.convert import convert_single_pdf
    from marker.models import load_all_models

    print(f"[extract_text] Marker: parsing '{os.path.basename(doc_path)}' …")

    models = load_all_models()
    full_text, images, metadata = convert_single_pdf(
        doc_path,
        models,
        max_pages=None,
        langs=None,
        batch_multiplier=2,
    )

    # Split on Marker's page-break markers (form-feed or horizontal rule)
    import re
    pages = re.split(r"\n---+\n|\f", full_text)

    slides = []
    for i, page_text in enumerate(pages):
        text = page_text.strip()
        if not text:
            continue
        slides.append(
            {
                "slide_index": i,
                "source": "marker",
                "page": i + 1,
                "timestamp": None,
                "frame_path": None,
                "markdown": text,
            }
        )

    print(f"[extract_text] Marker: {len(slides)} pages extracted.")
    return slides


# ── Surya path (keyframes OCR) ────────────────────────────────────────────────

def extract_with_surya(keyframes: list[dict]) -> list[dict]:
    """
    OCR each keyframe PNG with Surya.

    Parameters
    ----------
    keyframes : list[dict]
        Records from keyframes.extract_keyframes() — each must have
        ``frame_path`` and ``timestamp``.

    Returns
    -------
    list[dict]
        One record per keyframe with extracted Markdown text.
    """
    from PIL import Image
    from surya.ocr import run_ocr
    from surya.model.detection.model import load_model as load_det_model
    from surya.model.detection.processor import load_processor as load_det_processor
    from surya.model.recognition.model import load_model as load_rec_model
    from surya.model.recognition.processor import load_processor as load_rec_processor

    print(f"[extract_text] Surya: OCR-ing {len(keyframes)} keyframes …")

    det_model = load_det_model()
    det_processor = load_det_processor()
    rec_model = load_rec_model()
    rec_processor = load_rec_processor()

    slides = []
    for kf in keyframes:
        img = Image.open(kf["frame_path"]).convert("RGB")
        predictions = run_ocr(
            [img],
            [["en", "zh"]],
            det_model,
            det_processor,
            rec_model,
            rec_processor,
        )

        lines = []
        for page_pred in predictions:
            for text_line in page_pred.text_lines:
                text = text_line.text.strip()
                if text:
                    lines.append(text)

        markdown = "\n".join(lines)
        slides.append(
            {
                "slide_index": kf["index"],
                "source": "surya",
                "page": kf["index"],
                "timestamp": kf["timestamp"],
                "frame_path": kf["frame_path"],
                "markdown": markdown,
            }
        )

    print(f"[extract_text] Surya: done ({len(slides)} slides).")
    return slides


# ── Unified entry point ───────────────────────────────────────────────────────

def extract_slide_text(
    keyframes: list[dict],
    doc_path: Optional[str] = None,
) -> list[dict]:
    """
    Extract slide text using Marker (if doc_path provided) or Surya (fallback).

    Parameters
    ----------
    keyframes : list[dict]
        Output of keyframes.extract_keyframes().  Always required so that
        even Marker output can be matched to video timestamps later.
    doc_path : str, optional
        Path to the original PDF / PPTX / DOCX supplied by the teacher.
        When absent, Surya OCR is used on keyframes instead.

    Returns
    -------
    list[dict]
        Slide records as described in the module docstring.
    """
    if doc_path and os.path.isfile(doc_path):
        return extract_with_marker(doc_path)
    else:
        if doc_path:
            print(
                f"[extract_text] Warning: doc_path '{doc_path}' not found; "
                "falling back to Surya OCR."
            )
        return extract_with_surya(keyframes)
