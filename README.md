<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-Skill-blueviolet?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiPjxwYXRoIGQ9Ik00IDE5LjVBMi41IDIuNSAwIDAgMSA2LjUgMTdIMjAiLz48cGF0aCBkPSJNNi41IDJIMjB2MjBINi41QTIuNSAyLjUgMCAwIDEgNCAxOS41di0xNUEyLjUgMi41IDAgMCAxIDYuNSAyeiIvPjwvc3ZnPg==" alt="Claude Code Skill"/>
  <img src="https://img.shields.io/badge/Platform-Bilibili_%7C_Douyin_%7C_YouTube-blue?style=for-the-badge" alt="Platforms"/>
  <img src="https://img.shields.io/badge/Output-Markdown-green?style=for-the-badge" alt="Output"/>
</p>

<h1 align="center">lecture-notes-v2</h1>

<p align="center">
  <b>将课程视频一键转为高质量中文讲义</b><br/>
  <sub>WhisperX 词级转写 · pyannote 话者分离 · 智能关键帧 · 幻灯片 OCR · LLM 讲义生成</sub>
</p>

---

## 这是什么？

**lecture-notes-v2** 是一个 [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) / Codex Skill —— 让 AI Agent 将一段课程视频自动处理为结构化中文讲义 Markdown。

粘贴一个 B站 / 抖音 / YouTube 视频链接，Agent 会依次执行：

```
视频链接
  ↓  yt-dlp 下载
词级转写 + 话者分离 (WhisperX + pyannote)
  ↓
智能关键帧提取（视觉变化检测，非固定间隔）
  ↓
幻灯片文字提取 (Marker / Surya OCR)
  ↓
三层时间线对齐（transcript ↔ slide ↔ topic）
  ↓
LLM 生成结构化讲义 / Agent 直接编写
  ↓
📄 notes.md + ⏱ timeline.json + 🎙 transcript.srt
```

## 相比 v1 有什么提升？

| 维度 | v1 (lecture-to-notes) | **v2** |
|------|-----------------------|--------|
| 转写 | openai-whisper | **WhisperX**：词级时间戳 + VAD，更准、更快 |
| 说话人 | 无 | **pyannote**：自动区分老师 / 学生 |
| 抽帧 | 每 15 秒固定一帧 | **视觉变化检测**（χ² 直方图），帧数减少 50%+ |
| 幻灯片文字 | 无 / 仅靠 LLM 看图 | **Marker**（有课件）/ **Surya OCR**（无课件） |
| 时间线 | 字幕 + 帧，未对齐 | **三层对齐**：transcript ↔ slide ↔ topic |
| 输出格式 | LaTeX → PDF | **Markdown**（可选 pandoc → PDF） |
| 支持平台 | YouTube, Bilibili | **+ 抖音, TikTok** |
| 使用方式 | AI Agent Skill | AI Agent Skill **+ Web UI + CLI** |

## 快速开始

### 1. 安装依赖

```bash
# 核心工具
pip install whisperx pyannote.audio opencv-python surya-ocr openai tqdm
pip install marker-pdf          # 可选，有原始课件时使用

# 系统工具
# yt-dlp: https://github.com/yt-dlp/yt-dlp#installation
# ffmpeg: https://ffmpeg.org/download.html
```

### 2. 安装 Skill

将本目录复制到 Claude Code 的 skills 路径：

```bash
# macOS / Linux
cp -r lecture-notes-v2 ~/.claude/skills/

# 或直接在项目里使用
# Claude Code 会自动扫描 ./skills/ 目录
```

### 3. 使用

在 Claude Code 中直接说：

```
帮我把这个B站视频转成讲义：https://www.bilibili.com/video/BVxxxxxxxxxx
```

或带参数：

```
把这个视频做成笔记，用中文，whisper模型用 large-v2：
https://www.youtube.com/watch?v=xxxxx
课件在 slides.pdf
```

**触发词**：`课程笔记` `讲义` `视频转笔记` `B站笔记` `抖音笔记` `lecture notes`

## 环境变量

| 变量 | 用途 | 必须 |
|------|------|:----:|
| `OPENAI_API_KEY` | LLM 生成讲义（方式 A） | △ |
| `ANTHROPIC_API_KEY` | 使用 Claude API 生成（方式 A） | △ |
| `HF_TOKEN` | pyannote 话者分离模型授权 | △ |

> **方式 B（推荐）**：不设 API Key，由 Claude Code 自己读 `timeline.json` 直接写讲义。无额外费用。

## 目录结构

```
skills/lecture-notes-v2/
├── SKILL.md              # Skill 定义（Claude Code 读取）
├── README.md             # 本文件
├── agents/
│   └── openai.yaml       # Agent UI 元数据
└── assets/
    └── notes-template.md # Markdown 讲义模板
```

项目完整代码：

```
lecture-notes-v2/
├── modules/
│   ├── transcribe.py      # WhisperX + pyannote
│   ├── keyframes.py       # 视觉变化检测关键帧
│   ├── extract_text.py    # Marker / Surya 幻灯片文字
│   ├── align.py           # 三层时间线对齐
│   ├── generate_notes.py  # LLM 讲义生成
│   ├── download.py        # yt-dlp 视频下载
│   └── export.py          # JSON / SRT / HTML 导出
├── pipeline.py            # CLI 入口
├── server.py              # FastAPI Web 后端 + SSE
├── frontend/
│   └── index.html         # Web UI（纯 HTML，无需 build）
├── requirements.txt
└── skills/                # ← 你在这里
```

## 输出示例

### 讲义结构

```markdown
# 操作系统原理 第01讲

## 第一章 绪论

操作系统是管理计算机硬件资源、提供程序运行环境的系统软件…

> 💡 **核心**：OS 的三个关键抽象 — 进程、地址空间、文件

> ⚠️ **注意**：操作系统 ≠ 内核，内核只是 OS 的核心组件

### 本节小结
- 操作系统的定义与职责
- 三个关键抽象
- 内核态 vs 用户态

## 第二章 进程管理
…

## 总结与延伸
### 核心要点汇总
…
### 延伸学习建议
1. 《Operating Systems: Three Easy Pieces》
2. MIT 6.828 实验课
```

### Timeline 数据

```json
{
  "start": 125.34,
  "end": 132.67,
  "speaker": "SPEAKER_00",
  "text": "进程是操作系统中最核心的抽象之一",
  "slide_index": 8,
  "slide_markdown": "## 进程抽象\n- 运行中的程序实例\n- 包含：代码 + 数据 + 状态",
  "topic_label": "第二章 进程管理"
}
```

## Web UI（额外附赠）

除了 Skill 模式，本项目还提供了独立的 Web UI：

```bash
pip install -r requirements.txt
uvicorn server:app --port 8000
# 浏览器打开 http://localhost:8000
```

支持：粘贴链接 → 实时进度（SSE）→ 在线预览讲义 / 时间线 → 下载

## 常见问题

<details>
<summary><b>WhisperX 报 OOM</b></summary>

调小 batch_size：`--batch-size 8`（默认 16），或换更小模型：`--model medium`

</details>

<details>
<summary><b>pyannote 报 401 Unauthorized</b></summary>

1. 访问 [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)，接受用户协议
2. 生成 HF Token：https://huggingface.co/settings/tokens
3. 设置 `export HF_TOKEN=hf_xxx` 或在调用时传入

</details>

<details>
<summary><b>yt-dlp 下载失败 / 403</b></summary>

- YouTube → `--cookies-from-browser chrome`
- Bilibili 1080P+ → 需要登录 cookies
- 抖音 → 确保 yt-dlp 版本 ≥ 2024.5

</details>

<details>
<summary><b>想用本地模型 / API 代理</b></summary>

设置 `llm_base_url` 指向你的 endpoint：
```python
generate_notes(..., base_url="http://localhost:11434/v1", model="qwen2.5:72b")
```

</details>

## License

MIT

## Credits

- [WhisperX](https://github.com/m-bain/whisperX) — word-level timestamps
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) — speaker diarization
- [Marker](https://github.com/VikParuchuri/marker) — document parsing
- [Surya](https://github.com/VikParuchuri/surya) — OCR
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — video download
- Inspired by [lecture-to-notes](https://github.com/mazzzystar/lecture-to-notes)
