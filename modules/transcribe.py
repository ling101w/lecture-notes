"""
transcribe.py — WhisperX-based transcription with word-level timestamps,
VAD filtering, and pyannote speaker diarization.

Output schema (list of segments):
[
  {
    "start": float,       # segment start (seconds)
    "end": float,         # segment end (seconds)
    "text": str,          # full segment text
    "speaker": str,       # e.g. "SPEAKER_00"
    "words": [
      {"word": str, "start": float, "end": float, "score": float}
    ]
  }, ...
]
"""

from __future__ import annotations

import gc
import os
from typing import Optional

import torch


def transcribe(
    audio_path: str,
    model_size: str = "large-v2",
    language: Optional[str] = None,
    hf_token: Optional[str] = None,
    device: Optional[str] = None,
    batch_size: int = 16,
    initial_prompt: Optional[str] = None,
) -> list[dict]:
    """
    Transcribe audio using WhisperX, then align word timestamps and
    assign speaker labels via pyannote diarization.

    Parameters
    ----------
    audio_path : str
        Path to audio file (wav / mp3 / mp4 — anything ffmpeg can read).
    model_size : str
        WhisperX / faster-whisper model size: tiny, base, small, medium,
        large-v2 (default), large-v3.
    language : str, optional
        ISO-639-1 code, e.g. "zh", "en".  None = auto-detect.
    hf_token : str, optional
        Hugging Face token required by pyannote speaker diarization models.
        Set via HF_TOKEN env var if not passed directly.
    device : str, optional
        "cuda" or "cpu".  Auto-selected when None.
    batch_size : int
        Batch size for WhisperX inference (reduce if OOM on GPU).
    initial_prompt : str, optional
        Domain vocabulary hint fed to Whisper (same semantics as
        openai-whisper --initial_prompt).

    Returns
    -------
    list[dict]
        Diarized, word-aligned segments as described in the module docstring.
    """
    import whisperx

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    compute_type = "float16" if device == "cuda" else "int8"

    token = hf_token or os.environ.get("HF_TOKEN", "")

    # ── Step 1: Transcribe ────────────────────────────────────────────────
    print(f"[transcribe] Loading WhisperX model '{model_size}' on {device} …")
    model = whisperx.load_model(
        model_size,
        device=device,
        compute_type=compute_type,
        language=language,
    )

    audio = whisperx.load_audio(audio_path)

    transcribe_kwargs: dict = {"batch_size": batch_size}
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt
    if language:
        transcribe_kwargs["language"] = language

    result = model.transcribe(audio, **transcribe_kwargs)
    detected_language = result.get("language", language or "en")
    print(f"[transcribe] Detected language: {detected_language}")

    # Free GPU memory before alignment step
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    # ── Step 2: Word-level alignment ──────────────────────────────────────
    print("[transcribe] Aligning word timestamps …")
    align_model, metadata = whisperx.load_align_model(
        language_code=detected_language, device=device
    )
    result = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    del align_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    # ── Step 3: Speaker diarization ───────────────────────────────────────
    if token:
        print("[transcribe] Running speaker diarization via pyannote …")
        diarize_model = whisperx.DiarizationPipeline(
            use_auth_token=token, device=device
        )
        diarize_segments = diarize_model(audio_path)
        result = whisperx.assign_word_speakers(diarize_segments, result)
    else:
        print(
            "[transcribe] No HF_TOKEN — skipping diarization. "
            "Pass --hf-token or set HF_TOKEN env var to enable speaker labels."
        )

    # ── Step 4: Normalise output ──────────────────────────────────────────
    segments: list[dict] = []
    for seg in result["segments"]:
        segments.append(
            {
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "text": seg["text"].strip(),
                "speaker": seg.get("speaker", "SPEAKER_00"),
                "words": [
                    {
                        "word": w["word"],
                        "start": round(w.get("start", seg["start"]), 3),
                        "end": round(w.get("end", seg["end"]), 3),
                        "score": round(w.get("score", 0.0), 4),
                    }
                    for w in seg.get("words", [])
                ],
            }
        )

    print(f"[transcribe] Done — {len(segments)} segments.")
    return segments
