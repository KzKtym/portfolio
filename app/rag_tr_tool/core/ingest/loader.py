from pathlib import Path
from typing import List, Dict


def strip_frontmatter(text: str) -> str:
    """
    Remove YAML frontmatter (--- ... ---) if present.
    """
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text

def load_markdown_documents(base_path: str) -> List[Dict[str, str]]:
    """
    Recursively load markdown files from base_path.

    Returns:
        List of dict:
            {
                "source": relative posix path,
                "text": file content
            }
    """

    base = Path(base_path)
    documents: List[Dict[str, str]] = []

    for path in base.rglob("*.md"):
        text = path.read_text(encoding="utf-8")

        documents.append({
            "source": path.relative_to(base).as_posix(),
            "text": text
        })

    return documents

def load_markdown_documents_old(root_path: str) -> List[Dict]:
    root = Path(root_path)
    documents = []

    for file_path in root.rglob("*.md"):
        relative_path = file_path.relative_to(root).as_posix()

        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        text = strip_frontmatter(text)

        documents.append({
            "doc_id": relative_path,
            "text": text,
            "metadata": {
                "source": "fastapi_docs",
                "path": relative_path,
            }
        })

    return documents