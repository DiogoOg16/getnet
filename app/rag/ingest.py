import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup



SOURCES = [
    {
        "url": "https://site.getnet.com.br/get-ajuda-pix/como-habilitar-o-recebimento-de-vendas-via-pix-no-aplicativo-getnet-brasil/",
        "category": "customer_faq",
    },
    {
        "url": "https://site.getnet.com.br/get-ajuda-pix/como-fazer-uma-venda-com-pix-na-maquininha/",
        "category": "customer_faq",
    },
    {
        "url": "https://site.getnet.com.br/get-ajuda-pix/como-habilitar-pix-pelo-portal/",
        "category": "customer_faq",
    },
    {
        "url": "https://site.getnet.com.br/get-ajuda-antecipacao-de-venda/como-antecipar-sua-vendas-pelo-app/",
        "category": "customer_faq",
    },
    {
        "url": "https://site.getnet.com.br/get-ajuda-gestao-de-vendas/quais-possiveis-status-das-minhas-vendas/",
        "category": "customer_faq",
    },
    {
        "url": "https://getstore.getnet.com.br/docs/integracao-pagamento/pix/",
        "category": "technical_documentation",
    },
]


OUTPUT_PATH = Path(__file__).parent / "documents" / "getnet_sources.jsonl"
USER_AGENT = "GetnetSupportPrototype/0.1 (educational project)"


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_into_chunks(text: str, max_chars: int = 1000) -> list[str]:
    """Split text into readable chunks without discarding its content."""
    paragraphs = [
        clean_text(part)
        for part in re.split(r"(?<=[.!?])\s+|(?<=:)\s+", text)
        if clean_text(part)
    ]

    chunks = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""

            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start:start + max_chars])
            continue

        candidate = f"{current} {paragraph}".strip()

        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def extract_sections(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")

    for element in soup.select(
        "script, style, nav, footer, header, noscript, svg, form, "
        "[role='navigation'], [aria-hidden='true']"
    ):
        element.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    page_title = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else "Getnet documentation"
    )

    sections = []
    current_title = page_title
    current_text = []

    for element in main.find_all(["h1", "h2", "h3", "p", "li"]):
        text = clean_text(element.get_text(" ", strip=True))

        if not text:
            continue

        if element.name in ("h1", "h2", "h3"):
            if current_text:
                sections.append({
                    "title": current_title,
                    "content": " ".join(current_text),
                })
            current_title = text
            current_text = []
            continue

        # Ignora itens curtos e elementos compostos principalmente por links.
        if len(text) < 40:
            continue

        linked_text = clean_text(
            " ".join(link.get_text(" ", strip=True)
                     for link in element.find_all("a"))
        )
        if linked_text and len(linked_text) / len(text) > 0.5:
            continue

        current_text.append(text)

    if current_text:
        sections.append({
            "title": current_title,
            "content": " ".join(current_text),
        })

    return sections


def ingest_source(source: dict) -> list[dict]:
    response = requests.get(
        source["url"],
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        raise ValueError(f"Expected HTML, got {content_type!r}")

    sections = extract_sections(response.text)
    records = []

    for section in sections:
        for chunk in split_into_chunks(section["content"]):
            if len(chunk) < 40:
                continue

            records.append({
                "title": section["title"],
                "content": chunk,
                "source_url": source["url"],
                "category": source["category"],
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })

    if not records:
        raise ValueError("No useful text extracted from the page")

    return records


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_records = []
    failures = []

    for source in SOURCES:
        try:
            records = ingest_source(source)
            all_records.extend(records)
            print(f"OK: {source['url']} -> {len(records)} chunks")
        except (requests.RequestException, ValueError) as error:
            failures.append(source["url"])
            print(f"ERROR: {source['url']} -> {error}")

    if not all_records:
        raise SystemExit(
            "No pages were ingested. Check network access and source URLs."
        )

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        for record in all_records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(all_records)} chunks to {OUTPUT_PATH}")

    if failures:
        print(f"WARNING: {len(failures)} source(s) failed.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
