#!/usr/bin/env python3
"""
pipeline.py — lecture-notes-v2 CLI

Usage examples
--------------
# Minimal (video only, auto-detect language, no diarization)
python pipeline.py --video lecture.mp4 --output out/

# With teacher's original slides (Marker path)
python pipeline.py --video lecture.mp4 --slides slides.pdf --output out/

# Full pipeline: diarization + Chinese lecture
python pipeline.py \\
    --video lecture.mp4 \\
    --slides slides.pdf \\
    --language zh \\
    --hf-token hf_xxxxx \\
    --model large-v2 \\
    --output out/ \\
    --title "操作系统原理 第01讲"
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _check_deps() -> None:
    """Fail fast with a helpful message if key packages are missing."""
    missing = []
    for pkg, import_name in [
        ("whisperx", "whisperx"),
        ("cv2", "opencv-python"),
        ("numpy", "numpy"),
        ("PIL", "Pillow"),
    ]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(import_name)
    if missing:
        print(
            "[pipeline] Missing dependencies:\n"
            + "\n".join(f"  pip install {m}" for m in missing),
            file=sys.stderr,
        )
        sys.exit(1)


def _load_chapters(metadata_json: str | None) -> list[tuple[float, str]]:
    """
    Try to read chapter info from a yt-dlp metadata JSON (--dump-json).
    Returns a list of (start_seconds, title) pairs, sorted by start time.
    Falls back to [] if the file is absent or has no chapters.
    """
    if not metadata_json or not os.path.isfile(metadata_json):
        return []
    with open(metadata_json, encoding="utf-8") as f:
        meta = json.load(f)
    chapters = meta.get("chapters") or []
    result = []
    for ch in chapters:
        start = ch.get("start_time") or 0.0
        title = ch.get("title") or f"Chapter {len(result)+1}"
        result.append((float(start), title))
    return sorted(result, key=lambda x: x[0])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="lecture-notes-v2: WhisperX + smart keyframes + Marker/Surya + interactive HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # I/O
    parser.add_argument("--video", required=True, help="Path to video file (mp4/mkv/…)")
    parser.add_argument("--output", default="output", help="Output directory (default: output/)")
    parser.add_argument("--slides", default=None, help="Optional PDF/PPTX/DOCX from teacher (Marker)")
    parser.add_argument("--metadata", default=None, help="Optional yt-dlp --dump-json file for chapters")
    parser.add_argument("--title", default=None, help="Lecture title for the HTML viewer")

    # Transcription
    parser.add_argument("--model", default="large-v2",
                        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
                        help="WhisperX model size (default: large-v2)")
    parser.add_argument("--language", default=None,
                        help="ISO-639-1 language code, e.g. zh or en (default: auto-detect)")
    parser.add_argument("--hf-token", default=None,
                        help="Hugging Face token for pyannote diarization (or set HF_TOKEN env var)")
    parser.add_argument("--initial-prompt", default=None,
                        help="Domain vocabulary hint for Whisper (plain text or file path)")
    parser.add_argument("--batch-size", type=int, default=16,
                        help="WhisperX inference batch size (reduce if OOM, default: 16)")

    # Keyframe extraction
    parser.add_argument("--sample-interval", type=float, default=1.0,
                        help="Probe one frame every N seconds for change detection (default: 1)")
    parser.add_argument("--kf-threshold", type=float, default=0.08,
                        help="Histogram distance threshold for slide-change detection (default: 0.08)")
    parser.add_argument("--min-gap", type=float, default=3.0,
                        help="Minimum seconds between keyframes (default: 3)")

    # Export
    parser.add_argument("--no-embed-images", action="store_true",
                        help="Do not embed images as base64 in HTML (smaller file, needs local paths)")

    args = parser.parse_args(argv)

    _check_deps()

    # ── Setup ──────────────────────────────────────────────────────────────
    out = os.path.abspath(args.output)
    kf_dir = os.path.join(out, "keyframes")
    title = args.title or os.path.splitext(os.path.basename(args.video))[0]

    print(f"[pipeline] Output dir : {out}")
    print(f"[pipeline] Video      : {args.video}")
    print(f"[pipeline] Slides     : {args.slides or '(none — Surya OCR fallback)'}")
    print(f"[pipeline] Title      : {title}")
    print()

    initial_prompt: str | None = args.initial_prompt
    if initial_prompt and os.path.isfile(initial_prompt):
        with open(initial_prompt, encoding="utf-8") as f:
            initial_prompt = f.read().strip()

    # ── Step 1: Transcription ──────────────────────────────────────────────
    print("=" * 60)
    print("Step 1 / 4  — Transcription (WhisperX + pyannote)")
    print("=" * 60)
    from modules.transcribe import transcribe
    segments = transcribe(
        audio_path=args.video,
        model_size=args.model,
        language=args.language,
        hf_token=args.hf_token,
        batch_size=args.batch_size,
        initial_prompt=initial_prompt,
    )

    # ── Step 2: Smart keyframe extraction ─────────────────────────────────
    print()
    print("=" * 60)
    print("Step 2 / 4  — Keyframe extraction (visual-change detection)")
    print("=" * 60)
    from modules.keyframes import extract_keyframes
    keyframes = extract_keyframes(
        video_path=args.video,
        output_dir=kf_dir,
        sample_interval=args.sample_interval,
        threshold=args.kf_threshold,
        min_gap=args.min_gap,
    )

    # ── Step 3: Slide text extraction ─────────────────────────────────────
    print()
    print("=" * 60)
    print("Step 3 / 4  — Slide text extraction (Marker / Surya)")
    print("=" * 60)
    from modules.extract_text import extract_slide_text
    slides = extract_slide_text(keyframes=keyframes, doc_path=args.slides)

    # ── Step 4: Alignment ─────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("Step 4 / 4  — Timeline alignment (transcript ↔ slide ↔ topic)")
    print("=" * 60)
    chapters = _load_chapters(args.metadata)
    if chapters:
        print(f"[pipeline] Using {len(chapters)} chapters from metadata JSON.")
    from modules.align import align_timeline
    timeline = align_timeline(
        segments=segments,
        keyframes=keyframes,
        slides=slides,
        chapter_timestamps=chapters if chapters else None,
    )

    # ── Export ─────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("Export")
    print("=" * 60)
    from modules.export import save_json, save_srt, save_html

    json_path = os.path.join(out, "timeline.json")
    srt_path  = os.path.join(out, "transcript.srt")
    html_path = os.path.join(out, "viewer.html")

    save_json(timeline, json_path)
    save_srt(timeline, srt_path)
    save_html(
        timeline,
        html_path,
        title=title,
        embed_images=not args.no_embed_images,
    )

    print()
    print("=" * 60)
    print("Done!")
    print(f"  JSON      : {json_path}")
    print(f"  SRT       : {srt_path}")
    print(f"  HTML      : {html_path}")
    print(f"  Keyframes : {kf_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
