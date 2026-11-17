"""H1b: o radical da marca ("Getnet") só conta no boost de título.

Propriedades verificadas sobre o corpus real, comparando a mesma consulta com e
sem a marca:
1. pontuação BM25 — os scores diferem só pelo boost de título da marca;
2. cobertura — idêntica, e portanto os gates (MIN_SCORE, MIN_COVERAGE) deixam
   passar exatamente os mesmos documentos;
3. boost de título — documentos com a marca no título ganham +0,35.
Consulta só com a marca mantém o termo na pontuação (senão não sobraria termo).
"""

import pytest

from app.rag import retriever
from app.rag.retriever import BRAND_TERMS, query_terms, retrieve

BRAND_TITLE_BOOST = 0.35
PAIRS = [
    ("Como funciona a antecipação de recebíveis na Getnet?", "Como funciona a antecipação de recebíveis?"),
    ("Como funciona o Pix na Getnet?", "Como funciona o Pix?"),
    ("How does receivables advance (antecipação) work with Getnet?", "How does receivables advance (antecipação) work?"),
    ("Quais produtos a Getnet oferece para pequenos negócios?", "Quais produtos oferece para pequenos negócios?"),
]
ALL = 10_000


def results(query):
    return {(doc["title"], doc["content"]): doc for doc in retrieve(query, limit=ALL)}


def brand_in_title(title):
    return bool(BRAND_TERMS & set(retriever._doc_terms(title)))


def test_brand_stem_is_the_stem_of_getnet():
    assert query_terms("Getnet") == sorted(BRAND_TERMS)


@pytest.mark.parametrize(("with_brand", "without_brand"), PAIRS)
def test_pairs_differ_only_by_the_brand_term(with_brand, without_brand):
    assert set(query_terms(with_brand)) - set(query_terms(without_brand)) == BRAND_TERMS


@pytest.mark.parametrize(("with_brand", "without_brand"), PAIRS)
def test_brand_does_not_change_coverage_or_which_documents_pass_the_gates(with_brand, without_brand):
    a, b = results(with_brand), results(without_brand)
    assert a.keys() == b.keys()
    for key in a:
        assert a[key]["coverage"] == b[key]["coverage"], key[0]


@pytest.mark.parametrize(("with_brand", "without_brand"), PAIRS)
def test_brand_only_adds_the_title_boost_to_the_score(with_brand, without_brand):
    a, b = results(with_brand), results(without_brand)
    for key in a:
        expected = BRAND_TITLE_BOOST if brand_in_title(key[0]) else 0.0
        assert a[key]["score"] - b[key]["score"] == pytest.approx(expected, abs=0.011), key[0]


@pytest.mark.parametrize(("with_brand", "without_brand"), PAIRS[:3])
def test_pairs_exercise_titles_with_and_without_the_brand(with_brand, without_brand):
    # Garante que a propriedade acima foi testada nos dois casos (com e sem boost).
    titles = [key[0] for key in results(with_brand)]
    assert any(brand_in_title(t) for t in titles) and not all(brand_in_title(t) for t in titles)


def test_document_without_the_brand_is_not_penalized():
    # RAG-07b: L145 não menciona "Getnet" e ficava em 5º.
    top = [doc["title"] for doc in retrieve("Como funciona a antecipação de recebíveis na Getnet?")]
    assert top[0] == "O que é antecipação de vendas?"


def test_brand_in_the_title_still_ranks_the_exact_title_first():
    top = [doc["title"] for doc in retrieve("Como funciona o Pix na Getnet?")]
    assert top[0] == "Como funciona o Pix na Getnet?"


@pytest.mark.parametrize("query", ["O que é a Getnet?", "Getnet", "getnet?"])
def test_query_with_only_the_brand_keeps_it_in_scoring(query):
    assert set(query_terms(query)) == BRAND_TERMS
    assert "O que é a Getnet?" in [doc["title"] for doc in retrieve(query)]
