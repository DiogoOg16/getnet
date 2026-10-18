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


FAQ_BASE = "https://site.getnet.com.br/duvidas/"
FAQ_SLUGS = [
    "get-smart", "get-tap", "operacional", "pix", "pix-mais-respostas",
    "antecipacao-de-vendas", "receba-ja-2-dias", "crediario", "parcelado",
    "link-de-pagamento", "taxas", "aluguel", "aluguel-zero", "bandeiras",
    "cancelamento-descredenciamento", "get-conta", "split-de-pagamento",
    "pre-autorizacao", "plano-light", "tef-captura-pinpad",
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


def ingest_faq(slug: str) -> list[dict]:
    """One chunk per question/answer pair from a /duvidas/ page."""
    url = f"{FAQ_BASE}{slug}/"
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=25
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    now = datetime.now(timezone.utc).isoformat()
    records = []

    for modal in soup.select("div.o-modal__content--faq"):
        question = modal.select_one(".o-modal__title")
        answer = modal.select_one(".o-modal__text")
        if not question or not answer:
            continue

        q = clean_text(question.get_text(" ", strip=True))
        a = clean_text(answer.get_text(" ", strip=True))
        if len(q) < 10 or len(a) < 20:
            continue

        records.append({
            "title": q,
            "content": a,
            "source_url": url,
            "category": "faq",
            "ingested_at": now,
        })

    return records


def _page_soup(slug: str) -> tuple[BeautifulSoup, str]:
    url = f"https://site.getnet.com.br/{slug}/"
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=25
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup.select("script, style, noscript, svg, form"):
        element.decompose()
    return soup, url


def _text(element) -> str:
    return clean_text(element.get_text(" ", strip=True))


def ingest_product_pages() -> list[dict]:
    """Selected, noise-free sections from product pages."""
    now = datetime.now(timezone.utc).isoformat()
    records = []

    def add(title, content, url):
        records.append({
            "title": title,
            "content": content,
            "source_url": url,
            "category": "product_page",
            "ingested_at": now,
        })

    soup, url = _page_soup("link-de-pagamento")
    for css, title in [
        ("section.banner-section", "Link de Pagamento: visão geral"),
        ("section.s-benefits", "Link de Pagamento: benefícios"),
        ("section.s-payment", "Link de Pagamento: planos e custos"),
        ("section.s-steps", "Link de Pagamento: como criar e compartilhar"),
    ]:
        element = soup.select_one(css)
        if element:
            add(title, _text(element), url)

    soup, url = _page_soup("crediario")
    for element in soup.select("div.o-image-text"):
        add("Crediário: vantagens", _text(element), url)
    for element in soup.select("section.c-disclaimer-text-image"):
        add("Crediário: observações sobre taxas e juros", _text(element), url)

    soup, url = _page_soup("todas-as-maquininhas")
    candidates = [
        e for e in soup.find_all(True)
        if "79,90" in _text(e) and "129,90" in _text(e)
    ]
    if candidates:
        prices = _text(min(candidates, key=lambda e: len(_text(e))))
        add(
            "Maquininhas Get Clássica e Get Smart: valor mensal de utilização",
            (
                "Valor de utilização mensal das maquininhas, cobrado caso o "
                f"faturamento mínimo não seja atingido: {prices}. "
                "Faturamento acima de R$ 20 mil por mês: Get Clássica "
                "sem aluguel. Acima de R$ 40 mil por mês: Get Clássica ou "
                "Get Smart sem aluguel. Vendas por Voucher (VA/VR) e "
                "Crediário não compõem o faturamento para a isenção do "
                "aluguel. Valores e condições podem mudar; confirme no site."
            ),
            url,
        )

    return records


def dedupe(records: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for record in records:
        key = (record["title"], record["content"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


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

    for slug in FAQ_SLUGS:
        try:
            records = ingest_faq(slug)
            all_records.extend(records)
            print(f"OK: faq/{slug} -> {len(records)} chunks")
        except requests.RequestException as error:
            failures.append(f"faq/{slug}")
            print(f"ERROR: faq/{slug} -> {error}")

    try:
        products = ingest_product_pages()
        all_records.extend(products)
        print(f"OK: product pages -> {len(products)} chunks")
    except requests.RequestException as error:
        failures.append("product_pages")
        print(f"ERROR: product pages -> {error}")

    all_records = dedupe(all_records)

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
