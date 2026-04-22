"""
download.py — Download video (and optional thumbnail) from Bilibili, Douyin,
TikTok, YouTube, or any yt-dlp-supported platform.

Returns a dict with:
  video_path   : str   — absolute path to downloaded mp4
  title        : str   — video title
  duration     : float — seconds
  chapters     : list[(float, str)]  — (start_sec, chapter_title)
  thumb_path   : str | None          — downloaded thumbnail (jpg)
  platform     : str                 — bilibili | douyin | tiktok | youtube | other
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Callable, Optional


def detect_platform(url: str) -> str:
    url = url.lower()
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "douyin.com" in url or "iesdouyin.com" in url:
        return "douyin"
    if "tiktok.com" in url:
        return "tiktok"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return "other"


def _run(cmd: list[str], log: Callable[[str], None] | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if log:
        for line in (proc.stdout + proc.stderr).splitlines():
            if line.strip():
                log(line)
    return proc


def download_video(
    url: str,
    output_dir: str,
    cookies_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Download a lecture video to output_dir.

    Parameters
    ----------
    url             : Video URL (Bilibili / Douyin / TikTok / YouTube / …)
    output_dir      : Directory where files will be saved
    cookies_browser : e.g. "chrome" — pass to yt-dlp --cookies-from-browser
    cookies_file    : Path to a Netscape cookies.txt file
    progress_cb     : Callback for log lines (used by the server to stream progress)

    Returns
    -------
    dict  (see module docstring)
    """
    os.makedirs(output_dir, exist_ok=True)
    platform = detect_platform(url)
    log = progress_cb or print

    # ── Step 1: Fetch metadata (no download) ─────────────────────────────
    log(f"[download] Fetching metadata for {platform} …")
    meta_cmd = ["yt-dlp", "--dump-json", "--no-download", "--no-playlist", url]
    if cookies_browser:
        meta_cmd += ["--cookies-from-browser", cookies_browser]
    if cookies_file:
        meta_cmd += ["--cookies", cookies_file]

    meta_proc = _run(meta_cmd)
    if meta_proc.returncode != 0:
        raise RuntimeError(
            f"yt-dlp metadata failed (exit {meta_proc.returncode}):\n{meta_proc.stderr[:800]}"
        )

    meta: dict = json.loads(meta_proc.stdout)
    title: str = meta.get("title") or "lecture"
    duration: float = float(meta.get("duration") or 0)
    raw_chapters: list = meta.get("chapters") or []
    chapters: list[tuple[float, str]] = [
        (float(ch.get("start_time", 0)), ch.get("title", f"Chapter {i+1}"))
        for i, ch in enumerate(raw_chapters)
    ]

    # Sanitise title for use as a filename hint
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
    log(f"[download] Title: {title}  duration: {duration:.0f}s  chapters: {len(chapters)}")

    # ── Step 2: Download video ────────────────────────────────────────────
    video_path = os.path.join(output_dir, "video.mp4")

    # Skip download if file already exists (resumable runs)
    if os.path.isfile(video_path) and os.path.getsize(video_path) > 1_000_000:
        log(f"[download] video.mp4 already exists, skipping download.")
    else:
        log(f"[download] Downloading video …")
        dl_cmd = [
            "yt-dlp",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", video_path,
            "--no-playlist",
            "--newline",          # one progress line per update (friendlier for logging)
            url,
        ]
        if cookies_browser:
            dl_cmd += ["--cookies-from-browser", cookies_browser]
        if cookies_file:
            dl_cmd += ["--cookies", cookies_file]

        dl_proc = _run(dl_cmd, log=log)
        if dl_proc.returncode != 0:
            raise RuntimeError(
                f"yt-dlp download failed (exit {dl_proc.returncode}):\n{dl_proc.stderr[:800]}"
            )

    if not os.path.isfile(video_path):
        raise RuntimeError(f"Expected video at {video_path} but file not found after download.")

    # ── Step 3: Download thumbnail (best-effort) ──────────────────────────
    thumb_path: Optional[str] = None
    thumb_base = os.path.join(output_dir, "thumb")
    thumb_cmd = [
        "yt-dlp",
        "--write-thumbnail", "--skip-download",
        "--convert-thumbnails", "jpg",
        "-o", thumb_base,
        "--no-playlist",
        url,
    ]
    if cookies_browser:
        thumb_cmd += ["--cookies-from-browser", cookies_browser]
    thumb_proc = _run(thumb_cmd)
    candidate = thumb_base + ".jpg"
    if os.path.isfile(candidate):
        thumb_path = candidate
        log(f"[download] Thumbnail saved → {candidate}")

    log(f"[download] Done. video → {video_path}")
    return {
        "video_path": os.path.abspath(video_path),
        "title": title,
        "safe_title": safe_title,
        "duration": duration,
        "chapters": chapters,
        "thumb_path": thumb_path,
        "platform": platform,
    }
