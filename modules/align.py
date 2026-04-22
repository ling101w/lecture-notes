"""
align.py — Build the three-layer timeline: transcript ↔ slide ↔ topic.

Algorithm
---------
1. For every transcript segment, find the keyframe whose timestamp is the
   closest *before* the segment start (i.e. the slide that was on screen
   when the speaker started saying that sentence).

2. Detect topic boundaries via slide transitions: a new "topic" begins
   whenever the slide index jumps (a slide change happened).  Optionally
   the caller can pass explicit chapter timestamps from video metadata to
   override this heuristic.

3. Emit a flat list of "timeline events" — each event carries:
   - the transcript segment text + speaker
   - the slide index + slide markdown text
   - the topic / chapter label

Output schema:
[
  {
    "start": float,
    "end": float,
    "speaker": str,
    "text": str,
    "words": list[dict],
    "slide_index": int | None,
    "slide_markdown": str,
    "slide_timestamp": float | None,
    "slide_frame_path": str | None,
    "topic_index": int,
    "topic_label": str,
  }, ...
]
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Optional


def align_timeline(
    segments: list[dict],
    keyframes: list[dict],
    slides: list[dict],
    chapter_timestamps: Optional[list[tuple[float, str]]] = None,
) -> list[dict]:
    """
    Build transcript–slide–topic timeline.

    Parameters
    ----------
    segments : list[dict]
        Diarized transcript segments from transcribe.transcribe().
    keyframes : list[dict]
        Keyframe records from keyframes.extract_keyframes().
    slides : list[dict]
        Slide text records from extract_text.extract_slide_text().
    chapter_timestamps : list[(float, str)], optional
        Optional list of (start_seconds, chapter_title) pairs from video
        metadata.  When provided, topics are named after chapters instead
        of being auto-numbered from slide transitions.

    Returns
    -------
    list[dict]
        Aligned timeline events as described in the module docstring.
    """

    # ── Build fast lookup: keyframe timestamps sorted ─────────────────────
    kf_times = [kf["timestamp"] for kf in keyframes]

    # Map slide_index → slide record for O(1) lookup
    slide_map: dict[int, dict] = {s["slide_index"]: s for s in slides}

    # ── Build topic index (from chapters or slide transitions) ────────────
    if chapter_timestamps:
        # Sort by start time just in case
        chapters = sorted(chapter_timestamps, key=lambda x: x[0])
        chapter_times = [c[0] for c in chapters]
        chapter_labels = [c[1] for c in chapters]
    else:
        # Auto-derive topics from slide transitions in the keyframe list
        chapters = []
        prev_slide = -1
        topic_idx = 0
        for kf in keyframes:
            if kf["index"] != prev_slide:
                label = f"Topic {topic_idx + 1}"
                chapters.append((kf["timestamp"], label))
                topic_idx += 1
                prev_slide = kf["index"]
        chapter_times = [c[0] for c in chapters]
        chapter_labels = [c[1] for c in chapters]

    def _topic_at(ts: float) -> tuple[int, str]:
        if not chapter_times:
            return 0, "Topic 1"
        idx = bisect_right(chapter_times, ts) - 1
        idx = max(0, idx)
        return idx, chapter_labels[idx]

    def _keyframe_at(ts: float) -> Optional[dict]:
        """Return the last keyframe whose timestamp <= ts."""
        if not kf_times:
            return None
        pos = bisect_right(kf_times, ts) - 1
        if pos < 0:
            return keyframes[0]
        return keyframes[pos]

    # ── Build timeline ────────────────────────────────────────────────────
    timeline: list[dict] = []
    for seg in segments:
        kf = _keyframe_at(seg["start"])
        slide_idx = kf["index"] if kf else None
        slide_rec = slide_map.get(slide_idx) if slide_idx is not None else None

        topic_idx, topic_label = _topic_at(seg["start"])

        timeline.append(
            {
                "start": seg["start"],
                "end": seg["end"],
                "speaker": seg.get("speaker", "SPEAKER_00"),
                "text": seg["text"],
                "words": seg.get("words", []),
                "slide_index": slide_idx,
                "slide_markdown": slide_rec["markdown"] if slide_rec else "",
                "slide_timestamp": kf["timestamp"] if kf else None,
                "slide_frame_path": kf["frame_path"] if kf else None,
                "topic_index": topic_idx,
                "topic_label": topic_label,
            }
        )

    print(
        f"[align] {len(timeline)} events  "
        f"| {len(set(e['speaker'] for e in timeline))} speakers  "
        f"| {len(set(e['topic_label'] for e in timeline))} topics"
    )
    return timeline
