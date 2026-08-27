from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(.+)$", re.M)


def tokenize(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9_./+-]+", text)
    zh = re.findall(r"[\u4e00-\u9fff]+", text)
    grams = []
    for block in zh:
        if len(block) == 1:
            grams.append(block)
        else:
            grams.extend(block[i : i + 2] for i in range(len(block) - 1))
            if len(block) > 2:
                grams.extend(block[i : i + 3] for i in range(len(block) - 2))
    return words + grams


def vectorize(text: str) -> dict[str, float]:
    counts = Counter(tokenize(text))
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def score(query_vec: dict[str, float], doc_vec: dict[str, float]) -> float:
    if len(query_vec) > len(doc_vec):
        query_vec, doc_vec = doc_vec, query_vec
    return sum(v * doc_vec.get(k, 0.0) for k, v in query_vec.items())


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sections(text: str):
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        yield "全文", normalize(text)
        return
    prefix = normalize(text[: matches[0].start()])
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = normalize(text[start:end])
        if prefix and i == 0:
            body = normalize(prefix + " " + body)
        yield match.group(1).strip(), body


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    text = normalize(text)
    if len(text) <= max_chars:
        return [text] if text else []
    chunks = []
    start = 0
    last_start = -1
    while start < len(text):
        end = min(len(text), start + max_chars)
        cut = text.rfind("。", start, end)
        if cut <= start + max_chars // 2:
            cut = text.rfind(" ", start, end)
        if cut <= start:
            cut = end
        chunks.append(text[start:cut].strip())
        if cut >= len(text):
            break
        next_start = max(0, cut - overlap)
        if next_start <= start or next_start == last_start:
            next_start = cut
        last_start = start
        start = next_start
    return [c for c in chunks if c]


def build_index(docs_dir: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.execute(
        "create table chunks (id text primary key, title text, video text, section text, path text, text text, vector text)"
    )
    total = 0
    for path in sorted(docs_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        title_match = re.search(r"^#\s+(.+)$", text, re.M)
        title = title_match.group(1).strip() if title_match else path.stem
        video_match = re.search(r"BV[0-9A-Za-z]+|20\d+_\d+", text)
        video = video_match.group(0) if video_match else ""
        for section, section_text in split_sections(text):
            for n, chunk in enumerate(chunk_text(section_text)):
                chunk_id = hashlib.sha1(f"{path}:{section}:{n}:{chunk}".encode()).hexdigest()
                con.execute(
                    "insert into chunks values (?,?,?,?,?,?,?)",
                    (
                        chunk_id,
                        title,
                        video,
                        section,
                        str(path),
                        chunk,
                        json.dumps(vectorize(" ".join([title, section, chunk])), ensure_ascii=False),
                    ),
                )
                total += 1
    con.commit()
    con.close()
    return total


def search_index(query: str, db_path: Path, top_k: int = 8) -> list[dict]:
    qv = vectorize(query)
    con = sqlite3.connect(db_path)
    rows = con.execute("select title, video, section, path, text, vector from chunks").fetchall()
    con.close()
    ranked = []
    for title, video, section, path, text, vec_json in rows:
        s = score(qv, json.loads(vec_json))
        if s > 0:
            ranked.append(
                {"score": s, "title": title, "video": video, "section": section, "path": path, "text": text}
            )
    ranked.sort(reverse=True, key=lambda x: x["score"])
    return ranked[:top_k]


def snippet(text: str, query: str, width: int = 180) -> str:
    pos = -1
    for term in [t for t in re.split(r"\s+", query.strip()) if t]:
        pos = text.lower().find(term.lower())
        if pos >= 0:
            break
    if pos < 0:
        pos = 0
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    return ("..." if start else "") + text[start:end] + ("..." if end < len(text) else "")
