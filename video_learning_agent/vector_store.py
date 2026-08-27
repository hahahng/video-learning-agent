from __future__ import annotations

from pathlib import Path


def build_chroma_index(docs_dir: Path, persist_dir: Path, collection_name: str = "video_learning") -> int:
    """Build an optional Chroma semantic index from generated markdown docs."""
    try:
        import chromadb  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("Chroma is optional. Install with: pip install chromadb") from exc

    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.get_or_create_collection(collection_name)
    count = 0
    for path in sorted(docs_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = _chunk(text)
        if not chunks:
            continue
        ids = [f"{path.stem}-{i}" for i in range(len(chunks))]
        collection.add(
            ids=ids,
            documents=chunks,
            metadatas=[{"path": str(path), "title": _title(text), "chunk": i} for i in range(len(chunks))],
        )
        count += len(chunks)
    return count


def query_chroma(query: str, persist_dir: Path, collection_name: str = "video_learning", top_k: int = 8) -> list[dict]:
    try:
        import chromadb  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("Chroma is optional. Install with: pip install chromadb") from exc

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(collection_name)
    result = collection.query(query_texts=[query], n_results=top_k)
    rows = []
    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]
    for doc, meta, distance in zip(documents[0], metadatas[0], distances[0]):
        rows.append({"distance": distance, "text": doc, "metadata": meta})
    return rows


def _chunk(text: str, size: int = 1200, overlap: int = 180) -> list[str]:
    text = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "untitled"
