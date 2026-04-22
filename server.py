"""
server.py — FastAPI backend for lecture-notes-v2.

Start:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET  /                                 → frontend/index.html
    POST /api/process                      → submit a job (multipart form)
    GET  /api/job/{id}/stream              → SSE progress stream
    GET  /api/job/{id}/result              → final notes + timeline JSON
    GET  /api/job/{id}/download/{file}     → download output files
    GET  /api/job/{id}/keyframe/{file}     → serve keyframe PNGs for the viewer
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import traceback
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

app = FastAPI(title="lecture-notes-v2")

# ── Job store ─────────────────────────────────────────────────────────────────
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
JOBS_DIR = Path("jobs")
JOBS_DIR.mkdir(exist_ok=True)

STEPS = ["download", "transcribe", "keyframes", "ocr", "align", "generate", "done"]


def _update(job_id: str, **kwargs) -> None:
    with _LOCK:
        JOBS[job_id].update(kwargs)


def _log(job_id: str, msg: str) -> None:
    _update(job_id, message=msg)
    print(f"[{job_id[:8]}] {msg}")


# ── Pipeline (runs in a background thread) ────────────────────────────────────

def _run_pipeline(
    job_id: str,
    url: str,
    api_key: str,
    hf_token: str,
    language: str,
    whisper_model: str,
    llm_model: str,
    llm_provider: str,
    llm_base_url: str,
    title_override: str,
    slides_path: Optional[str],
    cookies_browser: str,
) -> None:
    out = JOBS_DIR / job_id
    out.mkdir(exist_ok=True)

    def cb(msg: str):
        _log(job_id, msg)

    try:
        # ── 1. Download ───────────────────────────────────────────────────
        _update(job_id, step="download")
        cb("正在下载视频…")
        from modules.download import download_video
        dl = download_video(
            url,
            str(out),
            cookies_browser=cookies_browser or None,
            progress_cb=cb,
        )
        video_path = dl["video_path"]
        title = title_override or dl["title"]
        chapters = dl["chapters"]
        _update(job_id, video_title=title)
        cb(f"下载完成：{title}")

        # ── 2. Transcribe ─────────────────────────────────────────────────
        _update(job_id, step="transcribe")
        cb("WhisperX 转写中（可能需要几分钟）…")
        from modules.transcribe import transcribe
        segments = transcribe(
            audio_path=video_path,
            model_size=whisper_model,
            language=language or None,
            hf_token=hf_token or None,
            initial_prompt=None,
        )
        cb(f"转写完成，共 {len(segments)} 个片段")

        # ── 3. Keyframes ──────────────────────────────────────────────────
        _update(job_id, step="keyframes")
        cb("正在提取关键帧（视觉变化检测）…")
        from modules.keyframes import extract_keyframes
        keyframes = extract_keyframes(
            video_path=video_path,
            output_dir=str(out / "keyframes"),
        )
        cb(f"关键帧提取完成：{len(keyframes)} 帧")

        # ── 4. OCR / Slide text ───────────────────────────────────────────
        _update(job_id, step="ocr")
        cb(
            "Marker 解析课件…" if slides_path else "Surya OCR 幻灯片识别中…"
        )
        from modules.extract_text import extract_slide_text
        slides = extract_slide_text(keyframes=keyframes, doc_path=slides_path)
        cb(f"幻灯片文字提取完成：{len(slides)} 张")

        # ── 5. Align ──────────────────────────────────────────────────────
        _update(job_id, step="align")
        cb("对齐时间线（transcript ↔ slide ↔ topic）…")
        from modules.align import align_timeline
        timeline = align_timeline(
            segments=segments,
            keyframes=keyframes,
            slides=slides,
            chapter_timestamps=chapters if chapters else None,
        )
        cb(f"对齐完成：{len(timeline)} 条记录")

        # ── 6. Generate notes ─────────────────────────────────────────────
        _update(job_id, step="generate")
        cb("LLM 正在生成讲义（每章节一次调用）…")
        from modules.generate_notes import generate_notes
        notes_md = generate_notes(
            timeline=timeline,
            title=title,
            api_key=api_key,
            model=llm_model,
            provider=llm_provider,
            base_url=llm_base_url or None,
            progress_cb=cb,
        )
        cb("讲义生成完成！")

        # ── 7. Save outputs ───────────────────────────────────────────────
        from modules.export import save_json, save_srt

        json_path = out / "timeline.json"
        srt_path  = out / "transcript.srt"
        notes_path = out / "notes.md"

        save_json(timeline, str(json_path))
        save_srt(timeline, str(srt_path))
        notes_path.write_text(notes_md, encoding="utf-8")

        # ── Serialise timeline for result (strip large base64 images) ─────
        slim_timeline = [
            {
                k: v for k, v in ev.items()
                if k not in ("words",)  # omit word-level detail from result JSON
            }
            for ev in timeline
        ]

        _update(
            job_id,
            step="done",
            status="done",
            message="全部完成！",
            result={
                "title": title,
                "notes": notes_md,
                "timeline": slim_timeline,
                "files": {
                    "notes_md": f"/api/job/{job_id}/download/notes.md",
                    "timeline_json": f"/api/job/{job_id}/download/timeline.json",
                    "transcript_srt": f"/api/job/{job_id}/download/transcript.srt",
                },
            },
        )

    except Exception as exc:
        tb = traceback.format_exc()
        print(tb)
        _update(job_id, status="error", message=str(exc), traceback=tb)


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.post("/api/process")
async def process(
    url: str              = Form(...),
    api_key: str          = Form(""),
    hf_token: str         = Form(""),
    language: str         = Form(""),
    whisper_model: str    = Form("large-v2"),
    llm_model: str        = Form("gpt-4o"),
    llm_provider: str     = Form("openai"),
    llm_base_url: str     = Form(""),
    title: str            = Form(""),
    cookies_browser: str  = Form(""),
    slides: Optional[UploadFile] = File(None),
):
    if not url.strip():
        raise HTTPException(400, "url is required")

    job_id = str(uuid.uuid4())
    with _LOCK:
        JOBS[job_id] = {
            "status": "running",
            "step": "queued",
            "message": "任务已加入队列，正在启动…",
            "result": None,
        }

    out_dir = JOBS_DIR / job_id
    out_dir.mkdir(exist_ok=True)

    # Save optional slides file
    slides_path: Optional[str] = None
    if slides and slides.filename:
        slides_path = str(out_dir / slides.filename)
        content = await slides.read()
        with open(slides_path, "wb") as f:
            f.write(content)

    # Launch pipeline in a daemon thread
    t = threading.Thread(
        target=_run_pipeline,
        args=(
            job_id, url.strip(),
            api_key, hf_token, language,
            whisper_model, llm_model, llm_provider, llm_base_url,
            title, slides_path, cookies_browser,
        ),
        daemon=True,
    )
    t.start()

    return {"job_id": job_id}


@app.get("/api/job/{job_id}/stream")
async def stream_job(job_id: str):
    """Server-Sent Events endpoint: pushes job state updates to the browser."""
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")

    async def event_gen():
        prev_msg: Optional[str] = None
        while True:
            with _LOCK:
                state = dict(JOBS.get(job_id, {}))
            state.pop("result", None)           # don't stream the whole result
            state.pop("traceback", None)

            msg = state.get("message")
            status = state.get("status", "running")

            if msg != prev_msg or status in ("done", "error"):
                prev_msg = msg
                yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"

            if status in ("done", "error"):
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/job/{job_id}/result")
async def get_result(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")
    with _LOCK:
        job = dict(JOBS[job_id])
    if job.get("status") == "error":
        raise HTTPException(500, job.get("message", "pipeline error"))
    if job.get("status") != "done":
        raise HTTPException(202, "job not finished yet")
    return job.get("result", {})


@app.get("/api/job/{job_id}/download/{filename}")
async def download_file(job_id: str, filename: str):
    p = JOBS_DIR / job_id / filename
    if not p.exists():
        raise HTTPException(404, f"{filename} not found")
    return FileResponse(str(p), filename=filename)


@app.get("/api/job/{job_id}/keyframe/{filename}")
async def get_keyframe(job_id: str, filename: str):
    p = JOBS_DIR / job_id / "keyframes" / filename
    if not p.exists():
        raise HTTPException(404, "keyframe not found")
    return FileResponse(str(p), media_type="image/png")
