---
name: lecture-notes-v2
description: >
  Generate high-quality Chinese lecture notes from a video URL (Bilibili / Douyin / TikTok / YouTube).
  Upgrades the original lecture-to-notes skill with: WhisperX word-level timestamps + VAD,
  pyannote speaker diarization (老师 vs 学生), visual-change-based smart keyframe extraction,
  Marker/Surya slide text extraction, and a three-layer transcript–slide–topic alignment timeline.
  Outputs structured Markdown notes with speaker attribution, inline slide references, and chapter navigation.
  Trigger words: 课程笔记, 讲义, 视频转笔记, B站笔记, 抖音笔记, WhisperX, 话者分离, BV号, lecture notes.
---

# lecture-notes-v2

将 Bilibili / 抖音 / TikTok / YouTube 课程视频，通过词级转写 + 话者分离 + 智能关键帧 + 幻灯片 OCR + 三层对齐，
最终由 LLM 生成一份结构化中文讲义 Markdown。

---

## 依赖检查

在开始前确认以下工具已安装，缺失则提示用户安装：

| 工具 | 必须 | 用途 |
|------|:----:|------|
| `yt-dlp` | ✓ | 视频/元数据/字幕下载（B站/抖音/YouTube） |
| `ffmpeg` | ✓ | 音频提取（WhisperX 内部调用） |
| `python3` | ✓ | 所有 Python 模块 |
| `whisperx` | ✓ | `pip install whisperx` |
| `pyannote.audio` | ✓ | `pip install pyannote.audio` — 需要 HF Token |
| `opencv-python` | ✓ | `pip install opencv-python` — 关键帧提取 |
| `marker-pdf` | △ | `pip install marker-pdf` — 有原始课件时使用 |
| `surya-ocr` | △ | `pip install surya-ocr` — 无课件时 OCR 关键帧 |
| `openai` | ✓ | `pip install openai` — LLM 生成讲义 |

**HF Token 说明**：pyannote 话者分离模型需要 Hugging Face 授权。
让用户访问 [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) 接受协议后生成 token。
无 token 则跳过话者分离，所有片段标记为 `SPEAKER_00`。

---

## 目标

输出一份专业中文课程讲义，必须：

- 以视频真实教学内容为依据，而非简单照抄转写
- 按章节 / 主题结构组织（而非按时间顺序堆砌）
- 标注来自哪位说话人（老师讲解 vs. 学生提问）
- 融合幻灯片文字与口述内容
- 每节包含：核心概念、注意事项、背景知识、小结
- 结尾有跨章节综合与延伸建议

---

## 平台检测

| URL 模式 | 平台 |
|----------|------|
| `bilibili.com`, `b23.tv` | Bilibili |
| `douyin.com`, `iesdouyin.com` | 抖音 |
| `tiktok.com` | TikTok |
| `youtube.com`, `youtu.be` | YouTube |

---

## 快速路径（推荐）

如果用户系统上已有本项目的 `pipeline.py`：

```bash
# 最简 — 仅视频，Surya OCR，无话者分离
python3 pipeline.py --video video.mp4 --output out/ --api-key sk-xxx

# 完整 — 中文课程 + 原始课件 + 话者分离
python3 pipeline.py \
  --video  lecture.mp4 \
  --slides slides.pdf \
  --language zh \
  --hf-token hf_xxx \
  --model  large-v2 \
  --title  "操作系统原理 第01讲" \
  --api-key sk-xxx \
  --output out/
```

`pipeline.py` 完成后直接跳到 **Phase 7：交付**。

若没有 `pipeline.py`，按以下各阶段手动执行。

---

## 工作目录约定

**CRITICAL**：所有后台命令（WhisperX、视频下载）必须使用绝对路径。
Claude Code 的 shell 在命令之间会重置工作目录；相对路径会写到错误位置。

推荐命名：`<course_id>_<lecture_no>_<short_title>/`  
示例：`nju_os_01_intro/`、`csapp_06_memory/`

---

## Phase 1：视频下载

```bash
WORKDIR="$(pwd)/nju_os_01_intro"
mkdir -p "$WORKDIR"

# 1a. 获取元数据（标题、时长、章节）
yt-dlp --dump-json --no-download --no-playlist "$URL" > "$WORKDIR/meta.json"

# 1b. 下载视频（最高 1080p mp4）
yt-dlp \
  -f "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best" \
  --merge-output-format mp4 \
  -o "$WORKDIR/video.mp4" \
  --no-playlist \
  "$URL"

# 1c. 下载封面（可选，用于讲义题图）
yt-dlp --write-thumbnail --skip-download --convert-thumbnails jpg \
  -o "$WORKDIR/thumb" "$URL"
```

**认证问题**：
- YouTube 提示 "Sign in to confirm you're not a bot" → 加 `--cookies-from-browser chrome`
- Bilibili 1080P+ → 加 `--cookies-from-browser chrome`
- 抖音水印版 → 无需特殊处理，yt-dlp 默认拉无水印流

---

## Phase 2：WhisperX 转写 + pyannote 话者分离

v2 核心升级：**词级时间戳 + VAD + 话者标签**，比原版 Whisper 精确得多。

```python
# transcribe_run.py — 在 $WORKDIR 下运行
import sys
sys.path.insert(0, "/path/to/lecture-notes-v2")  # 调整为实际路径

from modules.transcribe import transcribe
import json, os

segments = transcribe(
    audio_path  = os.path.join(os.environ["WORKDIR"], "video.mp4"),
    model_size  = "large-v2",        # tiny/base/small/medium/large-v2/large-v3
    language    = "zh",              # None = 自动检测
    hf_token    = os.environ.get("HF_TOKEN"),   # 无则跳过话者分离
    batch_size  = 16,                # OOM 时调小
    initial_prompt = None,           # 可传领域术语字符串
)

out = os.path.join(os.environ["WORKDIR"], "segments.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(segments, f, ensure_ascii=False, indent=2)
print(f"[done] {len(segments)} segments → {out}")
```

**每条 segment 结构**：
```json
{
  "start": 12.34,
  "end": 15.67,
  "text": "操作系统是什么？",
  "speaker": "SPEAKER_00",
  "words": [{"word": "操作系统", "start": 12.34, "end": 13.10, "score": 0.98}]
}
```

**说话人约定**（仅参考，实际标签由 pyannote 自动分配）：
- `SPEAKER_00`：通常是主讲教师（发言最多）
- `SPEAKER_01` 及以上：学生提问或助教

---

## Phase 3：智能关键帧提取（视觉变化检测）

v2 核心升级：**按 slide 内容变化抽帧**，而非固定 15 秒。
算法：RGB 直方图 χ² 距离，超过阈值则视为幻灯片切换。

```python
# keyframes_run.py
import sys
sys.path.insert(0, "/path/to/lecture-notes-v2")
from modules.keyframes import extract_keyframes
import json, os

keyframes = extract_keyframes(
    video_path       = os.path.join(os.environ["WORKDIR"], "video.mp4"),
    output_dir       = os.path.join(os.environ["WORKDIR"], "keyframes"),
    sample_interval  = 1.0,   # 每 N 秒采样一帧（用于检测）
    threshold        = 0.08,  # 更小 = 更敏感（更多帧）
    min_gap          = 3.0,   # 两个关键帧最小间距（秒）
)

out = os.path.join(os.environ["WORKDIR"], "keyframes.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(keyframes, f, ensure_ascii=False, indent=2)
print(f"[done] {len(keyframes)} keyframes → keyframes/")
```

**与原版对比**：
- 原版：每 15 秒固定一帧，90 分钟课 → 360 帧
- v2：按内容变化，同一课 → 通常 80–150 帧，更少冗余，OCR 成本更低

---

## Phase 4：幻灯片文字提取

### 优先路径 — 有原始课件（PDF / PPTX / DOCX）

```python
# extract_run.py  — Marker 路径
from modules.extract_text import extract_with_marker
slides = extract_with_marker("/path/to/slides.pdf")
```

Marker 保留表格、数学公式、代码块的结构，是最高质量的来源。

### 退回路径 — 只有视频帧（无课件）

```python
# extract_run.py  — Surya OCR 路径
import json, os
from modules.extract_text import extract_with_surya

with open(os.path.join(os.environ["WORKDIR"], "keyframes.json")) as f:
    keyframes = json.load(f)

slides = extract_with_surya(keyframes)
```

Surya 做版面分析 + 阅读顺序 + LaTeX 数学 OCR，适合从视频截图提取结构化文字。

### 统一接口

```python
from modules.extract_text import extract_slide_text
# doc_path=None 自动退回 Surya
slides = extract_slide_text(keyframes=keyframes, doc_path="/path/to/slides.pdf")
```

---

## Phase 5：三层时间线对齐

v2 核心升级：把转写 / 幻灯片 / 主题三层信息对齐到同一时间线。

```python
import json, os
from modules.align import align_timeline

with open(os.path.join(os.environ["WORKDIR"], "segments.json")) as f:
    segments = json.load(f)
with open(os.path.join(os.environ["WORKDIR"], "keyframes.json")) as f:
    keyframes = json.load(f)

# 可选：从 meta.json 读取视频章节
with open(os.path.join(os.environ["WORKDIR"], "meta.json")) as f:
    meta = json.load(f)
chapters = [(ch["start_time"], ch["title"]) for ch in (meta.get("chapters") or [])]

timeline = align_timeline(
    segments   = segments,
    keyframes  = keyframes,
    slides     = slides,          # 来自 Phase 4
    chapter_timestamps = chapters or None,
)

out = os.path.join(os.environ["WORKDIR"], "timeline.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(timeline, f, ensure_ascii=False, indent=2)
print(f"[done] {len(timeline)} timeline events → {out}")
```

**每条 timeline event 结构**：
```json
{
  "start": 12.34,  "end": 15.67,
  "speaker": "SPEAKER_00",
  "text": "操作系统是什么？",
  "slide_index": 3,
  "slide_markdown": "## 操作系统定义\n- 管理硬件资源的软件层…",
  "slide_timestamp": 11.0,
  "slide_frame_path": "/abs/path/keyframes/kf_00003_000011s.png",
  "topic_index": 0,
  "topic_label": "第一章 绪论"
}
```

---

## Phase 6：LLM 生成讲义

读取 `timeline.json`，按 topic 分组，为每个主题调用 LLM 写一个章节，最后写综合总结。

### 方式 A — 调用 generate_notes 模块

```python
import json, os
from modules.generate_notes import generate_notes

with open(os.path.join(os.environ["WORKDIR"], "timeline.json")) as f:
    timeline = json.load(f)

notes_md = generate_notes(
    timeline   = timeline,
    title      = "操作系统原理 第01讲",
    api_key    = os.environ["OPENAI_API_KEY"],
    model      = "gpt-4o",           # 或 claude-3-5-sonnet-20241022
    provider   = "openai",           # 或 "anthropic"
    base_url   = None,               # 代理 / 本地模型 endpoint
)

out = os.path.join(os.environ["WORKDIR"], "notes.md")
with open(out, "w", encoding="utf-8") as f:
    f.write(notes_md)
print(f"[done] notes → {out}")
```

### 方式 B — 由 Claude Code 直接编写（无需 API Key）

读取 `timeline.json` 后，由你（Claude Code）直接按以下写作规则撰写。

---

## 写作规则（Phase 6 方式 B）

阅读 `timeline.json`，按 `topic_label` 分组，为每组写一个章节。

### 信息来源优先级

1. **说话人口述**（`text` 字段）：教学逻辑、解释、强调
2. **幻灯片文字**（`slide_markdown`）：定义、公式、代码、结构
3. **说话人标签**（`speaker`）：区分老师讲授与学生提问

### 章节写作格式

```markdown
## {topic_label}

{核心内容段落 — 提炼，不照抄}

> 💡 **核心**：关键定义 / 核心原理

> ⚠️ **注意**：易错点 / 常见误解

> 📖 **背景**：历史背景 / 设计动机（可选）

{代码块（如有）}

$$数学公式（如有）$$

### 本节小结
- 要点 1
- 要点 2
- 要点 3
```

### 说话人视角规则

- `SPEAKER_00`（主讲）的内容 → 正文讲解、定义、示例
- `SPEAKER_01+`（提问方）的内容 → 如有教学价值，以 `> 🙋 **学生提问**：` 引用
- 客套话、签到、结束语 → 跳过

### 幻灯片引用规则

- 每章第一次引用某张幻灯片时，在对应段落末尾加脚注：`（参见 @{slide_timestamp}s 的幻灯片）`
- 若幻灯片文字与口述内容有矛盾，以口述为准，幻灯片作补充

### 数学与代码

- 行内公式：`$...$`；独立公式：`$$...$$` + 紧随符号解释列表
- 代码：用 ``` 代码块，注明语言

### 全文结构

```
# {讲义标题}

## {topic_1}
…
## {topic_2}
…
## 总结与延伸

### 核心要点汇总
- …

### 章节逻辑关系
…

### 延伸学习建议
1. …
```

---

## Phase 7：交付

```bash
# 输出文件
$WORKDIR/
├── notes.md           # 最终讲义（Markdown）
├── timeline.json      # 完整三层对齐数据
├── transcript.srt     # 带说话人标签的字幕（可选）
└── keyframes/         # 幻灯片关键帧截图
    └── kf_*.png
```

**可选后处理**：

将 Markdown 转 PDF（需 pandoc + 中文字体）：
```bash
pandoc notes.md -o notes.pdf \
  --pdf-engine=xelatex \
  -V CJKmainfont="Source Han Serif CN" \
  -V geometry:margin=2cm \
  --highlight-style=tango
```

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| WhisperX OOM | 减小 `batch_size`（默认 16 → 8 → 4）或用更小模型 |
| pyannote 报 401 | 确认 HF Token 有效且已接受模型协议 |
| yt-dlp 下载失败 | 加 `--cookies-from-browser chrome` 或更新 yt-dlp |
| Surya OCR 慢 | 关键帧太多 → 调高 `threshold`（0.08 → 0.15）|
| LLM 生成质量差 | 升级模型（gpt-4o-mini → gpt-4o）或用方式 B 由 Claude 直接写 |

---

## Assets

- `assets/notes-template.md` — Markdown 讲义模板
- 项目 `modules/` 目录下各 Python 脚本可独立调用（见各 Phase）
