"""BM25 lexical retriever over the ingested Getnet knowledge base."""

import json
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

DOCUMENTS_PATH = (
    Path(__file__).parent / "documents" / "getnet_sources.jsonl"
)

K1 = 1.5
B = 0.75
STEM_LEN = 5

# Calibrados com as perguntas de teste; ajustar medindo, não adivinhando.
MIN_SCORE = 3.0
MIN_COVERAGE = 0.7

STOPWORDS = {
    # português
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "com", "e", "ou",
    "que", "como", "qual", "quais", "meu", "minha", "meus", "minhas",
    "eu", "voce", "voces", "ser", "ter", "ao", "se", "via", "pelo",
    "pela", "pode", "posso", "fazer","faco","funciona", "sobre", "mais",
    "nao", "sua", "seu", "suas", "seus", "esta", "isso", "ja", "onde",
    "quando", "quantas", "quanto", "quantos", "preciso", "precisa",
    "ontem", "hoje", "amanha", "informacoes", "informacao", "existem",
    "existe", "tem", "sao", "foi", "vou", "ha",
    # inglês
    "the", "an", "of", "to", "in", "is", "are", "do", "does", "did",
    "my", "me", "can", "what", "how", "with", "and", "or", "for", "on",
    "it", "be", "will", "from", "between", "into", "should", "i", "you",
    "your", "have", "has", "need", "won", "t", "s", "yesterday", "today",
    "tomorrow", "many", "much", "work", "split", "there", "this", "that",
    "sale", "sales", "through", "using", "showing", "into",
}

# Termos de perguntas em inglês traduzidos para o vocabulário da base.
SYNONYMS = {
    "installment": "parcelas", "installments": "parcelas",
    "machine": "maquininha", "machines": "maquininha",
    "terminal": "maquininha", "reader": "maquininha",
    "receivable": "recebiveis", "receivables": "recebiveis",
    "advance": "antecipacao", "anticipation": "antecipacao",
    "deposit": "deposito", "deposited": "depositado",
    "envio": "enviado",
    "sell": "vender",
    "transacao": "vendas",
    "bank": "banco", "account": "conta",
    "money": "dinheiro", "receive": "receber", "payment": "pagamento",
    "connect": "conecta", "connection": "conexao",
    "decline": "recusada venda negada",
    "declined": "recusada venda negada",
    "refused": "recusada venda negada",
    "recusada": "venda negada",
    "recusado": "venda negada",
    "recusadas": "venda negada",
    "recusados": "venda negada",
    "error": "erro", "difference": "diferenca", "card": "cartao",
    "fee": "taxa", "fees": "taxas", "rate": "taxa", "rates": "taxas",
    "wifi": "wi fi",
}

# Chunks de rodapé herdados das primeiras ingestões.
NOISE_TITLE_WORDS = {"veja", "videos"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def _stem(word: str) -> str:
    return word[:STEM_LEN]


def _doc_terms(text: str) -> list[str]:
    return [
        _stem(w) for w in _words(text)
        if len(w) > 1 and w not in STOPWORDS
    ]


def query_terms(query: str) -> list[str]:
    words = []
    for word in _words(query):
        if len(word) <= 1 or word in STOPWORDS:
            continue
        words.extend(SYNONYMS.get(word, word).split())
    return sorted({_stem(w) for w in words})


def _title_boost(title: str, known_terms: list[str]) -> float:
    title_terms = set(_doc_terms(title))
    title_matches = sum(1 for term in known_terms if term in title_terms)
    boost = 0.35 * title_matches

    if re.match(r"^(o que e|como funciona|qual e|quais sao|como e)\b", normalize(title)):
        boost += 0.6
    return boost


@lru_cache(maxsize=1)
def _index() -> dict:
    docs = []

    if DOCUMENTS_PATH.exists():
        with DOCUMENTS_PATH.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                record = json.loads(line)
                title = record.get("title", "").strip()
                content = record.get("content", "").strip()
                if not title or not content:
                    continue
                if NOISE_TITLE_WORDS <= set(_words(title)):
                    continue

                title_terms = _doc_terms(title)
                content_terms = _doc_terms(content)
                terms = title_terms * 2 + content_terms

                record["_title_tf"] = Counter(title_terms)
                record["_tf"] = Counter(terms)
                record["_len"] = len(terms)
                docs.append(record)

    df = Counter()
    for doc in docs:
        df.update(doc["_tf"].keys())

    avgdl = (
        sum(doc["_len"] for doc in docs) / len(docs) if docs else 0.0
    )
    return {"docs": docs, "df": df, "avgdl": avgdl}


def _idf(df: Counter, total: int, term: str) -> float:
    n = df.get(term, 0)
    return math.log(1 + (total - n + 0.5) / (n + 0.5))


def retrieve(query: str, limit: int = 3) -> list[dict]:
    terms = query_terms(query)
    if not terms or limit < 1:
        return []

    index = _index()
    docs, df, avgdl = index["docs"], index["df"], index["avgdl"]
    if not docs:
        return []

    # Termos ausentes da base não contam na cobertura.
    known = [t for t in terms if df.get(t, 0) > 0]
    if not known:
        return []

    idf = {t: _idf(df, len(docs), t) for t in known}
    total_idf = sum(idf.values())
    key_term = max(known, key=lambda t: idf[t])

    results = []
    for doc in docs:
        tf, length = doc["_tf"], doc["_len"]
        score = 0.0
        matched = 0.0
        title_matched = 0.0

        for term in known:
            freq = tf.get(term, 0)
            if not freq:
                continue

            norm = freq + K1 * (1 - B + B * length / avgdl)
            score += idf[term] * freq * (K1 + 1) / norm
            matched += idf[term]

            if doc["_title_tf"].get(term, 0):
                title_matched += idf[term]

        coverage = matched / total_idf
        if key_term not in tf:
            continue
        if score < MIN_SCORE or coverage < MIN_COVERAGE:
            continue

        score += _title_boost(doc["title"], known)

        results.append({
            "title": doc["title"],
            "content": doc["content"],
            "source_url": doc["source_url"],
            "category": doc["category"],
            "score": round(score, 2),
            "coverage": round(coverage, 2),
        })

    results.sort(
        key=lambda r: (r["score"], r["coverage"]),
        reverse=True,
    )

    unique, seen_titles = [], set()
    for result in results:
        if result["title"] in seen_titles:
            continue
        seen_titles.add(result["title"])
        unique.append(result)

    return unique[:limit]
