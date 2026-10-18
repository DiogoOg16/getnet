
import json
import re
import unicodedata
from pathlib import Path

DOCUMENTS_PATH = (
    Path(__file__).parent / "documents" / "getnet_sources.jsonl"
)

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "com", "e", "ou",
    "que", "como", "qual", "quais", "meu", "minha", "meus", "minhas",
    "eu", "voce", "voces", "ser", "ter", "ao", "se", "via", "pelo",
    "pela", "pode", "posso", "fazer", "funciona", "sobre", "mais",
}

IGNORED_TITLE_TERMS = {
    "veja", "videos", "video", "beneficios",
}

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )
    return text


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", normalize(text))
    return {
        word for word in words
        if len(word) > 1 and word not in STOPWORDS
    }


def load_documents() -> list[dict]:
    if not DOCUMENTS_PATH.exists():
        return []

    documents = []

    with DOCUMENTS_PATH.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            document = json.loads(line)
            title = document.get("title", "").strip()
            content = document.get("content", "").strip()

            if not title or not content:
                continue

            if tokenize(title) & IGNORED_TITLE_TERMS:
                continue

            document["_title_tokens"] = tokenize(title)
            document["_content_tokens"] = tokenize(content)
            documents.append(document)

    return documents





def retrieve(query: str, limit: int = 3) -> list[dict]:
    query_tokens = tokenize(query)

    if not query_tokens or limit < 1:
        return []

    normalized_query = normalize(query)
    documents = load_documents()
    best_by_url = {}

    # Identifica o assunto principal da pergunta.
    intent = None

    if any(
        term in normalized_query
        for term in ["antecipar", "antecipacao", "antecipação"]
    ):
        intent = "antecipacao"
    elif "expirado" in query_tokens and (
        "qr" in query_tokens or "code" in query_tokens
    ):
        intent = "status_pix"
    elif "integrar" in query_tokens or "integracao" in query_tokens:
        intent = "integracao"
    elif "maquininha" in query_tokens and (
        "venda" in query_tokens or "vendas" in query_tokens
    ):
        intent = "venda_maquininha"
    elif "habilitar" in query_tokens and "pix" in query_tokens:
        if "aplicativo" in query_tokens or "app" in query_tokens:
            intent = "habilitar_app"
        elif "portal" in query_tokens:
            intent = "habilitar_portal"

    for document in documents:
        title = normalize(document["title"])
        content = normalize(document["content"])
        title_tokens = document["_title_tokens"]
        content_tokens = document["_content_tokens"]
        url = normalize(document["source_url"])

        title_matches = query_tokens & title_tokens
        content_matches = query_tokens & content_tokens

        # Busca lexical: títulos têm mais peso que o conteúdo.
        score = len(title_matches) * 5 + len(content_matches)

        # Reforça correspondências com a intenção identificada.
        if intent == "habilitar_app":
            if "habilitar" in title and (
                "aplicativo" in title or "app" in title
            ):
                score += 20
            if "habilitar-pix-pelo-portal" in url:
                score -= 10

        elif intent == "habilitar_portal":
            if "portal" in title and "habilitar" in title:
                score += 20

        elif intent == "venda_maquininha":
            if "venda" in title and "maquininha" in title:
                score += 20

            if (
                "maquininha" in normalized_query
                and any(
                    term in content
                    for term in [
                        "selecione a opcao",
                        "digite o valor",
                        "escolha pix",
                        "qr code",
                    ]
                )
            ):
                score += 25

        elif intent == "antecipacao":
            if "antecipar" in title or "antecipacao" in title:
                score += 20

        elif intent == "status_pix":
            if "status" in title or "expirado" in title:
                score += 15
            if "expirado" in content:
                score += 5

        elif intent == "integracao":
            if document.get("category") == "technical_documentation":
                score += 15
            if "pix" in title:
                score += 5

        # Descarta resultados sem correspondência lexical suficiente.
        has_sale_steps = (
            intent == "venda_maquininha"
            and any(
                term in content
                for term in [
                    "selecione a opcao",
                    "digite o valor",
                    "escolha pix",
                    "qr code",
                ]
            )
        )

        has_anticipation_content = (
            intent == "antecipacao"
            and any(
                term in content
                for term in ["antecipar", "antecipacao", "antecipação"]
            )
        )

        if (
            not title_matches
            and len(content_matches) < 2
            and not has_sale_steps
            and not has_anticipation_content
        ):
            continue

        if has_anticipation_content:
            score += 20

        if has_sale_steps:
            score += 40

        if score <= 0:
            continue

        result = {
            "title": document["title"],
            "content": document["content"],
            "source_url": document["source_url"],
            "category": document["category"],
            "score": score,
        }

        # Retém o chunk mais relevante por página.
        if url not in best_by_url or score > best_by_url[url]["score"]:
            best_by_url[url] = result

    results = sorted(
        best_by_url.values(),
        key=lambda item: item["score"],
        reverse=True,
    )

    return results[:limit]
