from pathlib import Path
import re


DOCUMENT_PATH = Path(__file__).parent / "documents" / "getnet_faq.md"


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[a-zA-ZÀ-ÿ0-9]+\b", text.casefold()))


def load_sections() -> list[dict[str, str]]:
    content = DOCUMENT_PATH.read_text(encoding="utf-8")
    sections = []
    title = "General"
    lines = []

    for line in content.splitlines():
        if line.startswith("## "):
            if lines:
                sections.append({
                    "title": title,
                    "content": "\n".join(lines).strip(),
                })
            title = line[3:].strip()
            lines = []
        elif line.strip() and not line.startswith("# "):
            lines.append(line.strip())

    if lines:
        sections.append({
            "title": title,
            "content": "\n".join(lines).strip(),
        })

    return sections


def retrieve(query: str, limit: int = 2) -> list[dict[str, str]]:
    query_terms = tokenize(query)
    if not query_terms:
        return []

    scored_sections = []

    for section in load_sections():
        section_terms = tokenize(section["title"] + " " + section["content"])
        score = len(query_terms & section_terms)

        if score > 0:
            scored_sections.append((score, section))

    scored_sections.sort(key=lambda item: item[0], reverse=True)
    return [section for _, section in scored_sections[:limit]]
