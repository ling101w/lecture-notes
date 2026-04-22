"""
generate_notes.py — Generate structured Chinese lecture notes from the aligned
timeline using an LLM (OpenAI gpt-4o / Anthropic Claude).

Strategy
--------
1. Group timeline events by topic.
2. For each topic group, build a compact context block:
     - Transcript lines (speaker + timestamp + text), truncated to ~2000 chars
     - Unique slide OCR text for that segment
3. Call the LLM once per topic → one Markdown section.
4. Call the LLM once more for a cross-topic synthesis section.
5. Concatenate: YAML front-matter header + sections + synthesis.

Output: a single Markdown string suitable for rendering or PDF conversion.
"""

from __future__ import annotations

import os
from typing import Callable, Optional


# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM = """\
你是一位一流的课程笔记助理，专注于将课程视频内容整理成高质量的中文学习讲义。

你的笔记具备以下特点：
- 信息密度高：每句话都有价值，不堆砌废话
- 结构清晰：合理使用标题层级，便于快速扫读
- 教学信号明确：用固定标注格式突出核心概念、注意事项和背景知识
- 多源整合：融合讲师口述与幻灯片文字，而非简单照抄某一来源
- 语言精炼：专业、准确的中文技术表达\
"""

_SECTION_TMPL = """\
请根据以下课程片段，整理出一个章节的讲义内容。

【章节标题】{topic}

【视频转写】（格式：[时间] 说话人: 内容）
{transcript}

【本节幻灯片文字】
{slides}

输出要求：
1. 以 `## {topic}` 作为二级标题开始
2. 提炼核心知识点，改写归纳，不照抄转写原文
3. `> 💡 **核心**：` 标注关键定义、核心原理
4. `> ⚠️ **注意**：` 标注易错点、常见误解
5. `> 📖 **背景**：` 标注历史背景、设计动机（可选）
6. 数学公式：行内用 `$...$`，独立公式用 `$$...$$`
7. 代码片段用 ``` 代码块包裹，注明语言
8. 整合幻灯片中的关键文字和图表说明
9. 末尾加 `### 本节小结`，列出 3–5 条关键要点（用简洁的要点列表）\
"""

_SUMMARY_TMPL = """\
以下是课程《{title}》各章节的笔记摘要。请写出最终的"总结与延伸"部分。

【章节列表与摘要】
{sections_summary}

输出要求：
1. 以 `## 总结与延伸` 作为标题
2. 用 2–3 句话逐章点评，串联各章节的逻辑关系
3. 提炼全课最核心的 5–8 条知识要点（编号列表）
4. 给出 3–5 条具体的延伸学习建议（书目、工具、实验方向均可）
5. 语言精炼，不超过 600 字\
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_ts(sec: float) -> str:
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _build_section_context(events: list[dict], max_chars: int = 3000) -> tuple[str, str]:
    """Return (transcript_str, slides_str) for a list of timeline events."""
    lines: list[str] = []
    total = 0
    slide_seen: set[str] = set()
    slide_parts: list[str] = []

    for ev in events:
        if total < max_chars:
            line = f"[{_fmt_ts(ev['start'])}] {ev.get('speaker','?')}: {ev['text']}"
            lines.append(line)
            total += len(ev["text"])

        md = (ev.get("slide_markdown") or "").strip()[:600]
        if md and md not in slide_seen:
            slide_seen.add(md)
            slide_parts.append(md)

    if total >= max_chars:
        lines.append("…（内容过长已截断）")

    transcript = "\n".join(lines) or "（无转写内容）"
    slides = "\n---\n".join(slide_parts) or "（无幻灯片文字）"
    return transcript, slides


# ── LLM call abstraction ──────────────────────────────────────────────────────

def _call_llm(
    system: str,
    user: str,
    api_key: str,
    model: str,
    provider: str,
    base_url: Optional[str],
) -> str:
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    else:  # openai-compatible
        from openai import OpenAI
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=2048,
            temperature=0.4,
        )
        return resp.choices[0].message.content or ""


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_notes(
    timeline: list[dict],
    title: str,
    api_key: str,
    model: str = "gpt-4o",
    provider: str = "openai",
    base_url: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Generate structured Chinese lecture notes from an aligned timeline.

    Parameters
    ----------
    timeline    : Output of align.align_timeline()
    title       : Lecture title
    api_key     : OpenAI or Anthropic API key
    model       : Model name (gpt-4o, claude-3-5-sonnet-20241022, …)
    provider    : "openai" (default) or "anthropic"
    base_url    : Optional custom endpoint (OpenAI-compatible proxy / local LLM)
    progress_cb : Optional log callback

    Returns
    -------
    str — Full Markdown lecture notes
    """
    log = progress_cb or print

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
    if not api_key:
        raise ValueError("No API key provided. Set api_key or OPENAI_API_KEY env var.")

    # ── Group by topic ────────────────────────────────────────────────────
    topics: dict[str, list[dict]] = {}
    for ev in timeline:
        label = ev.get("topic_label") or "全文"
        topics.setdefault(label, []).append(ev)

    log(f"[generate] {len(topics)} topics → {len(timeline)} events  model={model}")

    sections: list[str] = []

    # ── Generate one section per topic ────────────────────────────────────
    for i, (topic, events) in enumerate(topics.items(), 1):
        log(f"[generate] Section {i}/{len(topics)}: {topic} ({len(events)} events) …")
        transcript, slides = _build_section_context(events)
        prompt = _SECTION_TMPL.format(
            topic=topic,
            transcript=transcript,
            slides=slides,
        )
        section_md = _call_llm(_SYSTEM, prompt, api_key, model, provider, base_url)
        sections.append(section_md.strip())

    # ── Generate synthesis section ────────────────────────────────────────
    log("[generate] Writing synthesis section …")
    # One-liner summary per section for the summary prompt
    sections_summary = "\n".join(
        f"{i+1}. **{label}**：" + (s.split("\n")[2] if len(s.split("\n")) > 2 else "…")
        for i, (label, s) in enumerate(zip(topics.keys(), sections))
    )
    summary_prompt = _SUMMARY_TMPL.format(title=title, sections_summary=sections_summary)
    summary_md = _call_llm(_SYSTEM, summary_prompt, api_key, model, provider, base_url)

    # ── Assemble final document ───────────────────────────────────────────
    header = f"# {title}\n"
    body = "\n\n".join(sections)
    full_notes = f"{header}\n\n{body}\n\n{summary_md.strip()}\n"

    log(f"[generate] Done — {len(full_notes)} chars.")
    return full_notes
