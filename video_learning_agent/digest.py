from __future__ import annotations

import os
import re
from pathlib import Path

from .jobs import slugify


REQUIRED_SECTIONS = [
    "## 0. 这节课的主线流程图",
    "## 1. 知识点",
    "## 2. 老师例子",
    "## 3. 中间用了什么工具、命令、工作流，我们可以学什么",
    "## 4. GitHub 可复现项目",
    "## 5. 我们利用 AI 可以做什么项目",
    "## 6. 今天可以动手做什么",
    "## 7. 学完这节应该留下什么",
]


PROMPT_TEMPLATE = """你是一个技术学习视频消化 Agent。

目标：用户不再看原视频，也能学到知识，并能动手做项目。

必须按这个 Markdown 模板输出：

# 编号｜总结标题

## 0. 这节课的主线流程图
使用 mermaid flowchart，展示老师知识点的因果流程。

## 1. 知识点
写具体，不要泛泛总结。每个知识点解释机制、用途、适用场景。

## 2. 老师例子
抽取老师讲的例子，并说明例子在证明什么。

## 3. 中间用了什么工具、命令、工作流，我们可以学什么
列工具、命令、参数、命令能干什么、什么时候用。

## 4. GitHub 可复现项目
给出可复现方向。能识别具体项目就写项目名、用途、星标判断、能不能用。

## 5. 我们利用 AI 可以做什么项目
结合大模型、Agent、RAG、自动化，设计能落地、够酷的项目。

## 6. 今天可以动手做什么
给出 30-120 分钟可执行步骤。

## 7. 学完这节应该留下什么
必须包含：落地产物、输入、步骤、命令、验收标准、效率提升。

视频信息：
{title}

转写稿：
{transcript}
"""


def read_transcript_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:50000]


def generate_digest_text(transcript_path: Path, number: int | None = None, use_llm: bool = True) -> str:
    title = _extract_title(transcript_path)
    transcript = read_transcript_text(transcript_path)
    if use_llm and os.environ.get("OPENAI_API_KEY"):
        try:
            generated = _openai_generate(title, transcript)
            if validate_digest(generated):
                return generated
        except Exception:
            pass
    return fallback_digest(title, transcript, number)


def _openai_generate(title: str, transcript: str) -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI()
    response = client.chat.completions.create(
        model=os.environ.get("VIDEO_AGENT_SUMMARY_MODEL", "gpt-4.1"),
        messages=[
            {"role": "system", "content": "你写中文技术学习文档，要求具体、可操作、能落地。"},
            {"role": "user", "content": PROMPT_TEMPLATE.format(title=title, transcript=transcript)},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def fallback_digest(title: str, transcript: str, number: int | None = None) -> str:
    number_text = f"{number:02d}" if number is not None else "00"
    facts = _pick_sentences(transcript, 10)
    commands = _extract_commands(transcript)
    flow_nodes = facts[:5] or ["视频转写稿需要进一步总结"]
    flow = ["```mermaid", "flowchart TD"]
    previous = "A0"
    flow.append(f"  {previous}[{_mermaid_text(flow_nodes[0])}]")
    for i, sentence in enumerate(flow_nodes[1:], 1):
        node = f"A{i}"
        flow.append(f"  {previous} --> {node}[{_mermaid_text(sentence)}]")
        previous = node
    flow.append("```")

    command_block = "\n".join(f"- `{cmd}`：转写稿中出现的工具/命令线索，需要结合视频上下文复现。" for cmd in commands[:12])
    if not command_block:
        command_block = "- 暂未从转写稿中识别到明确命令。后续可由大模型结合画面和仓库补充。"

    fact_block = "\n".join(f"### {i}. {_short_heading(s)}\n\n{s}\n\n可落地理解：把这句话还原成输入、状态、动作、输出四件事，再做一个最小 demo。" for i, s in enumerate(facts[:8], 1))
    if not fact_block:
        fact_block = "转写稿内容不足，需要补充字幕或重新 ASR。"

    examples = "\n".join(f"- {s}" for s in facts[2:8]) or "- 暂无可抽取例子。"
    return f"""# {number_text}｜{title}

## 0. 这节课的主线流程图

{os.linesep.join(flow)}

## 1. 知识点

{fact_block}

## 2. 老师例子

{examples}

## 3. 中间用了什么工具、命令、工作流，我们可以学什么

{command_block}

工作流可以这样学：

1. 先把老师讲的概念拆成输入、处理、输出。
2. 找一个 GitHub 项目复现最小版本。
3. 用 AI 生成测试数据、解释报错、补充边界条件。
4. 把过程写成可重复脚本。

## 4. GitHub 可复现项目

- 检索关键词：`{title}`、`agent`、`rag`、`asr`、`automation`。
- 判断标准：最近一年有提交，README 能跑通，有 issue/PR 活动，星标只是参考。
- 复现方式：先跑官方 quickstart，再把老师例子替换成自己的输入。

## 5. 我们利用 AI 可以做什么项目

做一个“视频知识自动落地 Agent”：输入视频链接，自动拿字幕或 ASR，抽知识点、工具命令、可复现 GitHub 项目，再生成今天能动手做的 demo。

## 6. 今天可以动手做什么

1. 准备一个视频链接或转写稿。
2. 运行 `video-agent ingest <url>` 创建任务。
3. 如果没有字幕，配置 GPU SSH 后运行远程 ASR。
4. 运行 `video-agent digest <job_id>` 生成学习文档。
5. 运行 `video-agent search "关键词"` 搜索知识库。

## 7. 学完这节应该留下什么

- 落地产物：一个可运行的小 demo、一份 Markdown 学习文档、一个可搜索索引。
- 输入：视频链接、字幕或 ASR 转写稿、相关 GitHub 项目。
- 步骤：拿字幕，缺字幕跑 ASR，总结知识点，补工具命令，找可复现项目，做 demo。
- 命令：`video-agent ingest`、`video-agent status --watch`、`video-agent digest`、`video-agent search`。
- 验收标准：不看原视频也能讲清知识点，能跑一个最小项目，能搜索到对应片段。
- 效率提升：把“看视频、记笔记、找项目、写实践步骤”合成一条自动流水线。
"""


def write_digests(transcript_dir: Path, digest_dir: Path, use_llm: bool = True) -> list[Path]:
    digest_dir.mkdir(parents=True, exist_ok=True)
    transcripts = sorted(transcript_dir.glob("**/transcript.md"))
    if not transcripts:
        transcripts = sorted(transcript_dir.glob("*.md"))
    written = []
    for i, path in enumerate(transcripts, 1):
        text = generate_digest_text(path, number=i, use_llm=use_llm)
        out = digest_dir / f"{i:02d}_{slugify(_extract_video_id(path) or path.stem)}.md"
        out.write_text(text, encoding="utf-8")
        written.append(out)
    return written


def validate_digest(text: str) -> bool:
    return all(section in text for section in REQUIRED_SECTIONS) and all(
        marker in text for marker in ("落地产物", "输入", "步骤", "命令", "验收标准", "效率提升")
    )


def _extract_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^#\s+(.+)$", text, re.M)
    return match.group(1).strip() if match else path.stem


def _extract_video_id(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^-\s+(?:BV|ID):\s*(.+)$", text, re.M)
    return match.group(1).strip() if match else path.parent.name


def _pick_sentences(text: str, limit: int) -> list[str]:
    cleaned = re.sub(r"\[[^\]]+\]", "", text)
    parts = re.split(r"[。！？\n]+", cleaned)
    candidates = []
    for part in parts:
        s = re.sub(r"\s+", " ", part).strip(" -")
        if 18 <= len(s) <= 180 and not s.startswith(("#", "URL:", "BV:", "Model:")):
            candidates.append(s)
    return candidates[:limit]


def _extract_commands(text: str) -> list[str]:
    commands = re.findall(r"`([^`]+)`", text)
    words = re.findall(r"\b(?:git|python|pip|npm|pnpm|bun|curl|ssh|yt-dlp|ffmpeg|docker|kubectl)\b[^\n。；]*", text)
    seen = []
    for command in commands + words:
        cmd = command.strip()
        if cmd and cmd not in seen:
            seen.append(cmd)
    return seen


def _short_heading(sentence: str) -> str:
    return sentence[:28].strip() + ("..." if len(sentence) > 28 else "")


def _mermaid_text(text: str) -> str:
    return re.sub(r"[\[\]{}|]", "", text[:32])

