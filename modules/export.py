"""
export.py — Serialise the aligned timeline to JSON and a self-contained HTML
            viewer page.

The HTML page (`viewer.html`) is a standalone single-file app that embeds the
full timeline JSON as a JS variable so it works without a server.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional


def _fmt_time(seconds: float) -> str:
    """Format float seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _encode_image(path: Optional[str]) -> str:
    """Return a data-URI for the image at path, or empty string."""
    if not path or not os.path.isfile(path):
        return ""
    suffix = Path(path).suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(
        suffix, "png"
    )
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{b64}"


def save_json(timeline: list[dict], path: str) -> None:
    """Save the timeline as pretty-printed JSON."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    print(f"[export] JSON saved → {path}")


def save_srt(timeline: list[dict], path: str) -> None:
    """Export transcript as an SRT file with speaker labels."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _srt_ts(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")

    lines = []
    for i, ev in enumerate(timeline, 1):
        speaker_tag = f"[{ev['speaker']}] " if ev.get("speaker") else ""
        lines.append(str(i))
        lines.append(f"{_srt_ts(ev['start'])} --> {_srt_ts(ev['end'])}")
        lines.append(f"{speaker_tag}{ev['text']}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[export] SRT saved → {path}")


def save_html(
    timeline: list[dict],
    path: str,
    title: str = "Lecture Notes",
    embed_images: bool = True,
) -> None:
    """
    Generate a self-contained interactive HTML viewer.

    Parameters
    ----------
    timeline : list[dict]
        Aligned timeline from align.align_timeline().
    path : str
        Output path for the HTML file.
    title : str
        Page title shown in the browser tab and header.
    embed_images : bool
        If True, embed slide images as base64 data-URIs (works offline).
        If False, use local file:// paths (smaller HTML but needs local server).
    """
    # Build a serialisation-friendly copy of the timeline
    export_events = []
    for ev in timeline:
        img = (
            _encode_image(ev.get("slide_frame_path"))
            if embed_images
            else (ev.get("slide_frame_path") or "")
        )
        export_events.append(
            {
                "start": ev["start"],
                "end": ev["end"],
                "startFmt": _fmt_time(ev["start"]),
                "endFmt": _fmt_time(ev["end"]),
                "speaker": ev.get("speaker", ""),
                "text": ev["text"],
                "slideIndex": ev.get("slide_index"),
                "slideMarkdown": ev.get("slide_markdown", ""),
                "slideTimestamp": ev.get("slide_timestamp"),
                "slideImage": img,
                "topicIndex": ev.get("topic_index", 0),
                "topicLabel": ev.get("topic_label", ""),
            }
        )

    # Gather unique topics for the sidebar
    topics: list[dict] = []
    seen: set[int] = set()
    for ev in export_events:
        ti = ev["topicIndex"]
        if ti not in seen:
            seen.add(ti)
            topics.append(
                {
                    "index": ti,
                    "label": ev["topicLabel"],
                    "start": ev["start"],
                    "startFmt": ev["startFmt"],
                }
            )

    timeline_json = json.dumps(export_events, ensure_ascii=False)
    topics_json = json.dumps(topics, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<style>
  /* ── Reset & base ────────────────────────────────────────── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242736;
    --border: #2e3347;
    --accent: #5c7cfa;
    --accent2: #74c0fc;
    --text: #e2e8f0;
    --text-muted: #8892a4;
    --speaker-colors: #f87171, #fb923c, #facc15, #4ade80, #60a5fa, #a78bfa, #f472b6;
    --radius: 8px;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    color: var(--text);
    background: var(--bg);
  }}

  /* ── Layout ─────────────────────────────────────────────── */
  body {{ display: flex; flex-direction: column; height: 100vh; overflow: hidden; }}
  header {{
    display: flex; align-items: center; gap: 12px;
    padding: 10px 20px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }}
  header h1 {{ font-size: 1rem; font-weight: 600; color: var(--accent2); flex: 1; }}
  .stats {{ font-size: 0.75rem; color: var(--text-muted); }}
  .main {{ display: flex; flex: 1; overflow: hidden; }}

  /* ── Sidebar: topics ─────────────────────────────────────── */
  #sidebar {{
    width: 220px; flex-shrink: 0;
    background: var(--surface);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 12px 0;
  }}
  #sidebar h2 {{
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--text-muted); padding: 0 14px 8px;
  }}
  .topic-item {{
    padding: 7px 14px; cursor: pointer; transition: background 0.15s;
    border-left: 3px solid transparent;
  }}
  .topic-item:hover {{ background: var(--surface2); }}
  .topic-item.active {{
    background: var(--surface2); border-left-color: var(--accent);
  }}
  .topic-name {{ font-size: 0.82rem; font-weight: 500; }}
  .topic-time {{ font-size: 0.7rem; color: var(--text-muted); margin-top: 2px; }}

  /* ── Transcript panel ────────────────────────────────────── */
  #transcript {{
    flex: 1; overflow-y: auto; padding: 14px 16px;
    display: flex; flex-direction: column; gap: 4px;
  }}
  .topic-header {{
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--accent); padding: 14px 0 4px; font-weight: 600;
  }}
  .segment {{
    display: flex; gap: 10px; align-items: flex-start;
    padding: 7px 10px; border-radius: var(--radius);
    cursor: pointer; transition: background 0.12s;
  }}
  .segment:hover, .segment.active {{ background: var(--surface2); }}
  .segment.active {{ outline: 1px solid var(--accent); }}
  .seg-time {{
    font-size: 0.72rem; color: var(--text-muted);
    min-width: 52px; padding-top: 2px; font-variant-numeric: tabular-nums;
  }}
  .seg-speaker {{
    font-size: 0.68rem; font-weight: 700; padding: 1px 6px;
    border-radius: 4px; margin-top: 2px; white-space: nowrap;
    min-width: 80px; text-align: center;
  }}
  .seg-text {{ font-size: 0.88rem; line-height: 1.55; flex: 1; }}

  /* ── Slide panel ─────────────────────────────────────────── */
  #slide-panel {{
    width: 380px; flex-shrink: 0;
    background: var(--surface);
    border-left: 1px solid var(--border);
    display: flex; flex-direction: column;
    overflow: hidden;
  }}
  #slide-panel h2 {{
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--text-muted); padding: 12px 14px 8px;
    border-bottom: 1px solid var(--border); flex-shrink: 0;
  }}
  #slide-img-wrap {{
    background: #000; display: flex; align-items: center;
    justify-content: center; flex-shrink: 0; height: 220px;
  }}
  #slide-img {{
    max-width: 100%; max-height: 100%;
    object-fit: contain;
  }}
  .no-slide {{
    color: var(--text-muted); font-size: 0.8rem;
    display: flex; align-items: center; justify-content: center;
    height: 100%;
  }}
  #slide-meta {{
    font-size: 0.72rem; color: var(--text-muted);
    padding: 6px 14px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }}
  #slide-text {{
    flex: 1; overflow-y: auto; padding: 12px 14px;
    font-size: 0.82rem; line-height: 1.65; white-space: pre-wrap;
    color: var(--text);
  }}

  /* ── Search bar ──────────────────────────────────────────── */
  #search-wrap {{
    padding: 8px 14px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }}
  #search {{
    width: 100%; background: var(--surface2); border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 10px; color: var(--text); font-size: 0.83rem;
    outline: none;
  }}
  #search:focus {{ border-color: var(--accent); }}
  .highlight {{ background: rgba(92,124,250,0.35); border-radius: 2px; }}

  /* ── Scrollbar ───────────────────────────────────────────── */
  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>

<header>
  <h1>{title}</h1>
  <span class="stats" id="stats"></span>
</header>

<div class="main">

  <!-- Sidebar: topic list -->
  <nav id="sidebar">
    <h2>章节</h2>
    <div id="topic-list"></div>
  </nav>

  <!-- Centre: transcript -->
  <div style="display:flex;flex-direction:column;flex:1;overflow:hidden;">
    <div id="search-wrap">
      <input id="search" type="search" placeholder="搜索转写文本…" autocomplete="off"/>
    </div>
    <div id="transcript"></div>
  </div>

  <!-- Right: slide viewer -->
  <aside id="slide-panel">
    <h2>当前幻灯片</h2>
    <div id="slide-img-wrap">
      <div class="no-slide" id="no-slide-msg">尚未选中片段</div>
      <img id="slide-img" src="" alt="" style="display:none"/>
    </div>
    <div id="slide-meta"></div>
    <div id="slide-text"></div>
  </aside>

</div>

<script>
// ── Data ──────────────────────────────────────────────────────────────────────
const TIMELINE = {timeline_json};
const TOPICS   = {topics_json};

// ── Speaker colour palette ─────────────────────────────────────────────────
const PALETTE = [
  '#f87171','#fb923c','#facc15','#4ade80',
  '#60a5fa','#a78bfa','#f472b6','#34d399','#38bdf8'
];
const speakerColours = {{}};
let _nextColour = 0;
function speakerColour(name) {{
  if (!speakerColours[name]) {{
    speakerColours[name] = PALETTE[_nextColour % PALETTE.length];
    _nextColour++;
  }}
  return speakerColours[name];
}}

// ── Build transcript ──────────────────────────────────────────────────────────
let currentTopicIndex = -1;
const transcriptEl = document.getElementById('transcript');

function fmtTime(s) {{
  const h = Math.floor(s/3600);
  const m = Math.floor((s%3600)/60);
  const sec = Math.floor(s%60);
  return [h,m,sec].map(x=>String(x).padStart(2,'0')).join(':');
}}

function buildTranscript(events) {{
  transcriptEl.innerHTML = '';
  let lastTopic = -1;

  events.forEach((ev, idx) => {{
    if (ev.topicIndex !== lastTopic) {{
      const hdr = document.createElement('div');
      hdr.className = 'topic-header';
      hdr.textContent = ev.topicLabel;
      hdr.dataset.topicIndex = ev.topicIndex;
      transcriptEl.appendChild(hdr);
      lastTopic = ev.topicIndex;
    }}

    const seg = document.createElement('div');
    seg.className = 'segment';
    seg.dataset.idx = idx;
    seg.innerHTML = `
      <div class="seg-time">${{ev.startFmt}}</div>
      <div class="seg-speaker" style="background:${{speakerColour(ev.speaker)}}22;color:${{speakerColour(ev.speaker)}}">${{ev.speaker}}</div>
      <div class="seg-text">${{escapeHtml(ev.text)}}</div>
    `;
    seg.addEventListener('click', () => selectSegment(idx));
    transcriptEl.appendChild(seg);
  }});
}}

function escapeHtml(t) {{
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

// ── Sidebar topics ────────────────────────────────────────────────────────────
function buildSidebar() {{
  const list = document.getElementById('topic-list');
  TOPICS.forEach(tp => {{
    const item = document.createElement('div');
    item.className = 'topic-item';
    item.dataset.topicIndex = tp.index;
    item.innerHTML = `<div class="topic-name">${{escapeHtml(tp.label)}}</div>
                      <div class="topic-time">${{tp.startFmt}}</div>`;
    item.addEventListener('click', () => {{
      scrollToTopic(tp.index);
      setSidebarActive(tp.index);
    }});
    list.appendChild(item);
  }});
}}

function setSidebarActive(idx) {{
  document.querySelectorAll('.topic-item').forEach(el => {{
    el.classList.toggle('active', parseInt(el.dataset.topicIndex) === idx);
  }});
}}

function scrollToTopic(topicIndex) {{
  const hdr = transcriptEl.querySelector(`[data-topic-index="${{topicIndex}}"]`);
  if (hdr) hdr.scrollIntoView({{ behavior:'smooth', block:'start' }});
}}

// ── Slide panel ───────────────────────────────────────────────────────────────
function selectSegment(idx) {{
  document.querySelectorAll('.segment.active').forEach(el => el.classList.remove('active'));
  const el = transcriptEl.querySelector(`.segment[data-idx="${{idx}}"]`);
  if (el) el.classList.add('active');

  const ev = TIMELINE[idx];
  const imgEl  = document.getElementById('slide-img');
  const noSlide = document.getElementById('no-slide-msg');
  const metaEl = document.getElementById('slide-meta');
  const textEl = document.getElementById('slide-text');

  if (ev.slideImage) {{
    imgEl.src = ev.slideImage;
    imgEl.style.display = 'block';
    noSlide.style.display = 'none';
  }} else {{
    imgEl.style.display = 'none';
    noSlide.style.display = 'flex';
  }}

  metaEl.textContent = ev.slideTimestamp !== null
    ? `幻灯片时间戳：${{fmtTime(ev.slideTimestamp)}}  |  主题：${{ev.topicLabel}}`
    : '';

  textEl.textContent = ev.slideMarkdown || '（无文字提取结果）';

  // Update sidebar
  if (ev.topicIndex !== currentTopicIndex) {{
    currentTopicIndex = ev.topicIndex;
    setSidebarActive(ev.topicIndex);
  }}
}}

// ── Search ────────────────────────────────────────────────────────────────────
const searchInput = document.getElementById('search');
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.trim().toLowerCase();
  document.querySelectorAll('.segment').forEach(seg => {{
    const textEl = seg.querySelector('.seg-text');
    const orig = TIMELINE[parseInt(seg.dataset.idx)].text;
    if (!q) {{
      textEl.innerHTML = escapeHtml(orig);
      seg.style.display = '';
      return;
    }}
    const lower = orig.toLowerCase();
    if (lower.includes(q)) {{
      seg.style.display = '';
      const rx = new RegExp(q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&'),'gi');
      textEl.innerHTML = escapeHtml(orig).replace(rx, m => `<mark class="highlight">${{m}}</mark>`);
    }} else {{
      seg.style.display = 'none';
    }}
  }});
}});

// ── Stats ─────────────────────────────────────────────────────────────────────
function buildStats() {{
  const speakers = [...new Set(TIMELINE.map(e=>e.speaker))];
  const topics   = [...new Set(TIMELINE.map(e=>e.topicLabel))];
  document.getElementById('stats').textContent =
    `${{TIMELINE.length}} 片段  ·  ${{speakers.length}} 说话人  ·  ${{topics.length}} 主题`;
}}

// ── Init ──────────────────────────────────────────────────────────────────────
buildSidebar();
buildTranscript(TIMELINE);
buildStats();
if (TIMELINE.length > 0) selectSegment(0);
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[export] HTML viewer saved → {path}")
