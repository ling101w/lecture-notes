"""
keyframes.py — Smart keyframe extraction based on visual slide-change detection.

Algorithm
---------
1. Sample one frame every `sample_interval` seconds.
2. Compute a compact RGB histogram for each frame.
3. Measure chi-squared distance between consecutive histograms.
4. Emit a keyframe whenever the distance exceeds `threshold`
   (i.e. a real slide/content change occurred).
5. Always emit the very first frame and—optionally—the last frame.

This is more economical than fixed 15-second sampling: a 90-minute lecture
with ~3 real slide changes per minute yields ~270 keyframes instead of ~360,
and skips the many frames where the presenter is just talking in front of the
same slide.

Output schema (list of dicts):
[
  {
    "index": int,           # 0-based keyframe index
    "timestamp": float,     # seconds from video start
    "frame_path": str,      # absolute path to saved PNG
  }, ...
]
"""

from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np


# ── Histogram helpers ─────────────────────────────────────────────────────────

def _rgb_histogram(frame: np.ndarray, bins: int = 64) -> np.ndarray:
    """Compute a normalised flattened RGB histogram for a BGR frame."""
    hist_parts = []
    for ch in range(3):
        h = cv2.calcHist([frame], [ch], None, [bins], [0, 256])
        hist_parts.append(h.flatten())
    hist = np.concatenate(hist_parts)
    total = hist.sum()
    if total > 0:
        hist = hist / total
    return hist.astype(np.float32)


def _chi2_distance(h1: np.ndarray, h2: np.ndarray) -> float:
    """Chi-squared distance between two normalised histograms."""
    denom = h1 + h2
    mask = denom > 0
    diff = (h1[mask] - h2[mask]) ** 2 / denom[mask]
    return float(diff.sum())


# ── Main function ─────────────────────────────────────────────────────────────

def extract_keyframes(
    video_path: str,
    output_dir: str,
    sample_interval: float = 1.0,
    threshold: float = 0.08,
    min_gap: float = 3.0,
    hist_bins: int = 64,
    max_width: int = 1280,
) -> list[dict]:
    """
    Extract visually distinct keyframes from a video.

    Parameters
    ----------
    video_path : str
        Path to the input video file.
    output_dir : str
        Directory where keyframe PNGs will be saved.
    sample_interval : float
        Probe one frame every this many seconds (default 1 s).
    threshold : float
        Chi-squared histogram distance above which a new keyframe is emitted
        (default 0.08; lower = more sensitive, higher = fewer frames).
    min_gap : float
        Minimum seconds between two consecutive keyframes regardless of
        histogram change (avoids burst emission during rapid transitions).
    hist_bins : int
        Number of bins per channel for the histogram (default 64).
    max_width : int
        Resize frames wider than this before computing histograms (saves RAM).

    Returns
    -------
    list[dict]
        Keyframe records as described in the module docstring.
    """
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    step_frames = max(1, int(round(fps * sample_interval)))

    print(
        f"[keyframes] {os.path.basename(video_path)}  "
        f"fps={fps:.1f}  duration={duration:.1f}s  "
        f"sampling every {sample_interval}s ({step_frames} frames)"
    )

    keyframes: list[dict] = []
    prev_hist: Optional[np.ndarray] = None
    last_kf_ts: float = -999.0
    frame_idx = 0
    kf_index = 0

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step_frames != 0:
            frame_idx += 1
            continue

        timestamp = frame_idx / fps

        # Optionally downscale for faster histogram computation
        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / w
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

        hist = _rgb_histogram(frame, bins=hist_bins)

        is_first = prev_hist is None
        time_ok = (timestamp - last_kf_ts) >= min_gap

        if is_first:
            emit = True
        elif time_ok:
            dist = _chi2_distance(prev_hist, hist)  # type: ignore[arg-type]
            emit = dist >= threshold
        else:
            emit = False

        if emit:
            filename = f"kf_{kf_index:05d}_{int(timestamp):06d}s.png"
            frame_path = os.path.join(output_dir, filename)
            # Save at original captured resolution (re-read is expensive; just
            # save the (possibly resized) frame we already have)
            cv2.imwrite(frame_path, frame)
            keyframes.append(
                {
                    "index": kf_index,
                    "timestamp": round(timestamp, 3),
                    "frame_path": os.path.abspath(frame_path),
                }
            )
            kf_index += 1
            last_kf_ts = timestamp

        prev_hist = hist
        frame_idx += 1

    cap.release()
    print(f"[keyframes] Extracted {len(keyframes)} keyframes → {output_dir}")
    return keyframes
