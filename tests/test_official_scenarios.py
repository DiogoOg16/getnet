"""EVAL-01, camada 1: os dez cenários oficiais e o caso adicional S05-V.

Os critérios estão congelados em `eval/official_scenarios.json`. Cada requisito
de lá vira um teste com o mesmo ID. Os requisitos com `baseline_expected =
"xfail"` recebem `xfail(strict=True)` a partir do próprio JSON: um XPASS quebra
a suíte e obriga a revisar o critério de forma explícita.

Nada aqui chama Ollama, internet ou APIs reais. O LLM é o fake do conftest;
Open-Meteo e PTAX são mockados; qualquer outra chamada HTTP é registrada e faz
o teste falhar. Esta camada verifica rota, plano, ferramenta, fatos, contratos
e documentos recuperados. Ela não julga texto gerado (isso é a camada 2).

Os documentos gold são conferidos por linha + sha256 do conteúdo no resultado
efetivo de `retrieve` (o que o KnowledgeAgent recebeu) e no contexto entregue a
`KnowledgeAgent._generate`.

Testes de xfail separam pré-condições (PreconditionError, que não é absorvida
pelo xfail) da asserção do requisito (AssertionError). Assim um xfail só passa
pela lacuna documentada, não por um erro de montagem. Violações proibidas, como
dado inventado, levantam ForbiddenViolation e também não são absorvidas.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

import app.agents.knowledge as knowledge_module
from app.agents import customer_support as customer_support_module
from app.agents.knowledge import KnowledgeAgent
from app.main import app, handoff_store, orchestrator, session_memory
from app.rag import retriever
from app.tools import customer_tools, exchange_rate, weather

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = json.loads((ROOT / "eval" / "official_scenarios.json").read_text(encoding="utf-8"))
SCENARIOS = {scenario["id"]: scenario for scenario in CRITERIA["scenarios"]}
ADDITIONAL = {case["id"]: case for case in CRITERIA["additional_cases"]}
REFERENCE_DATE = date(2026, 11, 8)


class PreconditionError(Exception):
    """O cenário não chegou ao ponto que o requisito avalia."""


class ForbiddenViolation(Exception):
    """Algo proibido aconteceu (ex.: dado inventado). Nunca é absorvido por um xfail."""


def forbid(condition: bool, message: str) -> None:
    if condition:
        raise ForbiddenViolation(message)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _corpus_by_line() -> dict[int, dict]:
    rows = {}
    path = ROOT / CRITERIA["corpus"]["path"]
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            rows[number] = json.loads(line)
    return rows


CORPUS = _corpus_by_line()


def _doc(scenario: dict, kind: str, line: int) -> dict:
    for document in scenario["layer1"]["gold_documents"].get(kind, []):
        if document["line"] == line:
            return document
    raise KeyError(f"{scenario['id']}: L{line} não está em {kind}")


# --------------------------------------------------------------------------
# Ambiente controlado: espiões, HTTP mockado e data de referência fixa
# --------------------------------------------------------------------------

GEO_PORTO_ALEGRE = {
    "results": [{
        "name": "Porto Alegre",
        "admin1": "Rio Grande do Sul",
        "country": "Brasil",
        "latitude": -30.03,
        "longitude": -51.23,
        "timezone": "America/Sao_Paulo",
    }]
}
FORECAST = {
    "daily": {
        "time": ["2026-11-08", "2026-11-09"],
        "temperature_2m_max": [24.1, 27.6],
        "temperature_2m_min": [13.2, 15.8],
        "precipitation_probability_max": [10, 35],
    }
}
PTAX_FRIDAY = "11-06-2026"
PTAX_CLOSING = {
    "cotacaoCompra": 6.1300,
    "cotacaoVenda": 6.1317,
    "dataHoraCotacao": "2026-11-06 13:06:21.123456",
    "tipoBoletim": "Fechamento PTAX",
}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class ScenarioEnv:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.retrievals: list[dict] = []
        self.generations: list[str] = []
        self.support_llm_calls = 0
        self.idf_values: list[tuple[str, float]] = []
        self.unexpected_http: list[str] = []
        self.http_handlers: list = []
        self._clients: dict[str, TestClient] = {}

        original_retrieve = knowledge_module.retrieve

        def spy_retrieve(query, *args, **kwargs):
            documents = original_retrieve(query, *args, **kwargs)
            self.retrievals.append({"query": query, "documents": [dict(d) for d in documents]})
            return documents

        monkeypatch.setattr(knowledge_module, "retrieve", spy_retrieve)

        original_idf = retriever._idf

        def spy_idf(df, total, term):
            value = original_idf(df, total, term)
            self.idf_values.append((term, value))
            return value

        monkeypatch.setattr(retriever, "_idf", spy_idf)

        fake_generate = KnowledgeAgent._generate

        def spy_generate(agent, message, context):
            self.generations.append(context)
            return fake_generate(agent, message, context)

        monkeypatch.setattr(KnowledgeAgent, "_generate", spy_generate)

        support_client = orchestrator.support.client
        fake_chat = support_client.chat

        def counting_chat(messages, tools=None):
            self.support_llm_calls += 1
            return fake_chat(messages, tools)

        monkeypatch.setattr(support_client, "chat", counting_chat)

        def guarded(method):
            def call(url, *args, **kwargs):
                for handler in self.http_handlers:
                    response = handler(method, url, kwargs)
                    if response is not None:
                        return response
                self.unexpected_http.append(f"{method} {url}")
                raise requests.ConnectionError(f"HTTP não mockado no teste: {method} {url}")

            return call

        monkeypatch.setattr(requests, "get", guarded("GET"))
        monkeypatch.setattr(requests, "post", guarded("POST"))

        monkeypatch.setattr(customer_tools, "settlement_reference_date", lambda: REFERENCE_DATE)
        monkeypatch.setattr(customer_support_module, "settlement_reference_date", lambda: REFERENCE_DATE)

    # -- HTTP ---------------------------------------------------------------

    def mock_open_meteo(self, *, fail: bool = False):
        def handler(method, url, kwargs):
            if method != "GET" or not url.startswith(("https://geocoding-api.open-meteo.com", "https://api.open-meteo.com")):
                return None
            if fail:
                raise requests.ConnectionError("Open-Meteo indisponível (mock)")
            return _Response(GEO_PORTO_ALEGRE if url == weather.GEOCODING_URL else FORECAST)

        self.http_handlers.append(handler)

    def mock_ptax(self, *, fail: bool = False, today: date = date(2026, 11, 6)):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return today

        self.monkeypatch.setattr(exchange_rate, "date", FixedDate)

        def handler(method, url, kwargs):
            if method != "GET" or url != exchange_rate.PTAX_URL:
                return None
            if fail:
                raise requests.ConnectionError("PTAX indisponível (mock)")
            day = kwargs.get("params", {}).get("@dataCotacao", "").strip("'")
            return _Response({"value": [PTAX_CLOSING] if day == PTAX_FRIDAY else []})

        self.http_handlers.append(handler)

    # -- chat ---------------------------------------------------------------

    def client(self, user_id: str) -> TestClient:
        if user_id not in self._clients:
            self._clients[user_id] = TestClient(app, headers={"Authorization": f"Bearer test-token-{user_id}"})
        return self._clients[user_id]

    def chat(self, message: str, *, session_id: str, user_id: str = "cliente1988") -> dict:
        response = self.client(user_id).post(
            "/chat",
            json={"message": message, "user_id": user_id, "session_id": session_id},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def reset_spies(self):
        self.retrievals.clear()
        self.generations.clear()
        self.support_llm_calls = 0

    # -- documentos ----------------------------------------------------------

    def retrieved_hashes(self) -> set[str]:
        return {_content_hash(d["content"]) for r in self.retrievals for d in r["documents"]}

    def gold_reached_generation(self, document: dict) -> bool:
        """Recuperado de fato (hash no resultado de retrieve) e presente no contexto da geração."""
        content = CORPUS[document["line"]]["content"].strip()
        recovered = document["content_sha256_12"] in self.retrieved_hashes()
        in_context = any(content in context for context in self.generations)
        return recovered and in_context


@pytest.fixture
def env(monkeypatch):
    scenario_env = ScenarioEnv(monkeypatch)
    yield scenario_env
    assert scenario_env.unexpected_http == [], f"chamadas HTTP não mockadas: {scenario_env.unexpected_http}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreconditionError(message)


def assert_plan(message: str, expected: list[str]) -> None:
    _, plan = orchestrator.create_plan(message)
    assert [step.agent for step in plan.steps] == expected


def run_knowledge_scenario(env: ScenarioEnv, scenario_id: str) -> dict:
    scenario = SCENARIOS[scenario_id]
    payload = env.chat(scenario["message"], session_id=f"official-{scenario_id}")
    require(payload["agent"] == "knowledge", f"{scenario_id}: rota {payload['agent']}, esperada knowledge")
    require(env.retrievals, f"{scenario_id}: retrieve não foi chamado")
    require(env.generations, f"{scenario_id}: _generate não foi chamado (resposta direta ou fallback)")
    return payload


def check_knowledge_route(env: ScenarioEnv, scenario_id: str) -> None:
    scenario = SCENARIOS[scenario_id]
    assert_plan(scenario["message"], scenario["layer1"]["plan"])
    payload = env.chat(scenario["message"], session_id=f"official-{scenario_id}")
    assert payload["agent"] == "knowledge"
    assert [step["agent"] for step in payload["trace"]] == scenario["layer1"]["plan"]
    assert payload["step_status"] == "success"
    assert payload["handoff_required"] is False


def check_required_gold(env: ScenarioEnv, scenario_id: str, line: int) -> None:
    run_knowledge_scenario(env, scenario_id)
    document = _doc(SCENARIOS[scenario_id], "required", line)
    assert env.gold_reached_generation(document), (
        f"{scenario_id}: L{line} ({document['title']}) não chegou ao contexto da geração; "
        f"recuperados: {[d['title'] for r in env.retrievals for d in r['documents']]}"
    )


def check_any_of_gold(env: ScenarioEnv, scenario_id: str) -> None:
    run_knowledge_scenario(env, scenario_id)
    candidates = SCENARIOS[scenario_id]["layer1"]["gold_documents"]["any_of"]
    assert any(env.gold_reached_generation(document) for document in candidates)


# --------------------------------------------------------------------------
# Requisitos (IDs iguais aos de eval/official_scenarios.json)
# --------------------------------------------------------------------------


def s01_r1(env):
    check_knowledge_route(env, "S01")


def s01_r2(env):
    check_required_gold(env, "S01", 269)


def s01_r3(env):
    check_any_of_gold(env, "S01")


def s02_r1(env):
    env.mock_open_meteo()
    message = SCENARIOS["S02"]["message"]
    assert_plan(message, ["web_search"])
    payload = env.chat(message, session_id="official-S02")
    assert payload["agent"] == "web_search"
    assert payload["tool_used"] == "open_meteo"


def s02_r2(env):
    env.mock_open_meteo()
    payload = env.chat(SCENARIOS["S02"]["message"], session_id="official-S02")
    response = payload["response"]
    assert "Porto Alegre" in response
    assert "09/11/2026" in response
    assert "08/11/2026" not in response
    assert "15.8 °C" in response and "27.6 °C" in response
    assert "35%" in response
    assert "Fonte: Open-Meteo" in response
    assert payload["sources"] == ["https://open-meteo.com"]
    assert payload["step_status"] == "success"


def s02_r3(env):
    env.mock_open_meteo(fail=True)
    payload = env.chat(SCENARIOS["S02"]["message"], session_id="official-S02")
    response = payload["response"]
    forbid("°C" in response, "S02: temperatura apresentada com a Open-Meteo indisponível")
    forbid(bool(re.search(r"\d+\s*%", response)), "S02: probabilidade apresentada com a Open-Meteo indisponível")
    assert payload["step_status"] == "failed"


def s03_r1(env):
    message = SCENARIOS["S03"]["message"]
    assert_plan(message, ["customer_support"])
    payload = env.chat(message, session_id="official-S03")
    assert payload["agent"] == "customer_support"
    assert payload["tool_used"] == "lookup_settlement"


def s03_r2(env):
    payload = env.chat(SCENARIOS["S03"]["message"], session_id="official-S03")
    response = payload["response"]
    assert "Prazo de recebimento das vendas de ontem (07/11/2026)" in response
    assert "venda txn1001 realizada em 07/11/2026" in response
    assert "data prevista de liquidação: 09/11/2026" in response
    assert "status da liquidação: agendada" in response
    assert "dados simulados" in response
    for forbidden in ("txn1002", "05/11/2026", "scheduled", "processing"):
        assert forbidden not in response
    assert payload["step_status"] == "success"
    assert payload["issue_resolved"] is True
    assert payload["handoff_required"] is False


def s03_r3(env):
    payload = env.chat(SCENARIOS["S03"]["message"], session_id="official-S03", user_id="cliente2001")
    response = payload["response"]
    assert payload["tool_used"] == "lookup_settlement"
    assert "venda txn1001" not in response
    assert "149.90" not in response
    assert "Não encontrei vendas de ontem (07/11/2026)" in response


def s04_r1(env):
    check_knowledge_route(env, "S04")


def s04_r2(env):
    check_required_gold(env, "S04", 16)


def s05_turns(env, session_id="official-S05"):
    first, second = SCENARIOS["S05"]["turns"]
    turn1 = env.chat(first, session_id=session_id)
    pending = session_memory.get_pending_followup(user_id="cliente1988", session_id=session_id)
    env.reset_spies()
    turn2 = env.chat(second, session_id=session_id)
    return turn1, pending, turn2


def s05_r1(env):
    first = SCENARIOS["S05"]["turns"][0]
    assert_plan(first, ["customer_support"])
    payload = env.chat(first, session_id="official-S05")
    response = payload["response"].lower()
    assert payload["agent"] == "customer_support"
    assert payload["awaiting_user_input"] is True
    assert payload["step_status"] == "waiting_for_user_input"
    assert payload["handoff_required"] is False
    assert payload["handoff"] is None
    assert ("wi-fi" in response or "sinal" in response) and ("tela" in response or "mensagem" in response)
    assert handoff_store.list_for_user("cliente1988") == []
    pending = session_memory.get_pending_followup(user_id="cliente1988", session_id="official-S05")
    assert pending and pending["flow"] == "terminal_connectivity"


def s05_r2(env):
    _, pending, turn2 = s05_turns(env)
    require(pending is not None, "S05: turno 1 não deixou fluxo pendente")
    assert turn2["agent"] == "customer_support"
    assert turn2["step_status"] == "handoff"
    assert turn2["handoff_required"] is True
    ticket = turn2["handoff"]
    assert ticket["flow"] == "terminal_connectivity"
    assert ticket["status"] == "pending"
    assert "Complemento:" in ticket["message"]
    assert env.retrievals == [] and env.generations == [] and env.support_llm_calls == 0


def s06_r1(env):
    check_knowledge_route(env, "S06")


def s06_r2(env):
    check_any_of_gold(env, "S06")


def s06_r3(env):
    check_required_gold(env, "S06", 145)


def s07_r1(env):
    env.mock_ptax()
    message = SCENARIOS["S07"]["message"]
    assert_plan(message, ["web_search"])
    payload = env.chat(message, session_id="official-S07")
    assert payload["agent"] == "web_search"
    assert payload["tool_used"] == "bcb_ptax"


def s07_r2(env):
    env.mock_ptax()
    payload = env.chat(SCENARIOS["S07"]["message"], session_id="official-S07")
    response = payload["response"]
    assert "PTAX de fechamento do Banco Central" in response
    assert "06/11/2026 13:06" in response
    assert "R$ 6,1300" in response and "R$ 6,1317" in response
    assert "Não é uma cotação em tempo real" in response
    assert payload["sources"] == ["https://www.bcb.gov.br/conversao"]


def s07_r3(env):
    env.mock_ptax(today=date(2026, 11, 8))  # domingo; sexta 06/11 tem boletim
    payload = env.chat(SCENARIOS["S07"]["message"], session_id="official-S07")
    assert "06/11/2026" in payload["response"]
    assert "R$ 6,1317" in payload["response"]


def s07_r4(env):
    env.mock_ptax(fail=True)
    payload = env.chat(SCENARIOS["S07"]["message"], session_id="official-S07")
    assert "R$" not in payload["response"]
    assert not re.search(r"\d+,\d{4}", payload["response"])


def s08_r1(env):
    first = SCENARIOS["S08"]["turns"][0]
    assert_plan(first, ["customer_support"])
    payload = env.chat(first, session_id="official-S08")
    response = payload["response"]
    assert payload["agent"] == "customer_support"
    assert payload["awaiting_user_input"] is True
    assert payload["step_status"] == "waiting_for_user_input"
    assert "identificador" in response.lower()
    assert payload["tool_used"] is None
    assert "R$" not in response


def s08_r2(env):
    first, second = SCENARIOS["S08"]["turns"]
    env.chat(first, session_id="official-S08")
    payload = env.chat(second, session_id="official-S08")
    response = payload["response"]
    assert payload["agent"] == "customer_support"
    assert payload["tool_used"] == "lookup_transaction"
    assert payload["step_status"] == "success"
    assert "txn1003" in response and "recusada" in response.lower()
    assert re.search(r"(n[aã]o h[aá]|sem)\b.{0,40}motivo", response.lower())
    for invented in ("Cartão bloqueado", "AUTH_DECLINED", "saldo insuficiente"):
        assert invented not in response


def s08_r3(env):
    first = SCENARIOS["S08"]["turns"][0]
    env.chat(first, session_id="official-S08-ownership")
    payload = env.chat("The transaction is txn2001.", session_id="official-S08-ownership")
    response = payload["response"]
    assert payload["tool_used"] == "lookup_transaction"
    assert "não encontrei" in response.lower()
    for leaked in ("250", "Cartão bloqueado", "AUTH_DECLINED", "cliente2001"):
        assert leaked not in response


def s08_r4(env):
    first, second = SCENARIOS["S08"]["turns"]
    turn1 = env.chat(first, session_id="official-S08")
    turn2 = env.chat(second, session_id="official-S08")
    require(turn1["agent"] == "customer_support" and turn2["agent"] == "customer_support",
            "S08: a conversa não seguiu pelo Customer Support")
    require(turn2["tool_used"] == "lookup_transaction", "S08: turno 2 não consultou a transação")
    document = _doc(SCENARIOS["S08"], "required", 48)
    assert env.gold_reached_generation(document), (
        "S08: L48 (significado de 'Negada') não chegou ao contexto de geração em nenhum turno"
    )


def s09_r1(env):
    check_knowledge_route(env, "S09")


def s09_r2(env):
    check_required_gold(env, "S09", 267)


def s09_r3(env):
    check_required_gold(env, "S09", 183)


def s10_r1(env):
    check_knowledge_route(env, "S10")


def s10_r2(env):
    check_required_gold(env, "S10", 203)


def s10_r3(env):
    check_any_of_gold(env, "S10")


def run_s05v(env):
    case = ADDITIONAL["S05-V"]
    payload = env.chat(case["message"], session_id="additional-S05-V")
    require(payload["agent"] == "customer_support", "S05-V: rota diferente de customer_support")
    require(not payload["awaiting_user_input"], "S05-V: a mensagem não bastou para sair da coleta de sintomas")
    require(env.retrievals, "S05-V: o caminho de orientação não chamou retrieve")
    return case, payload


def s05v_r1(env):
    case, payload = run_s05v(env)
    l97 = case["layer1"]["gold_documents"]["not_gold"][0]
    l97_content = CORPUS[l97["line"]]["content"].strip()
    assert l97["title"] not in payload["sources"]
    assert not any(l97_content in context for context in env.generations)
    assert payload["step_status"] == "handoff"
    assert payload["handoff_required"] is True
    assert payload["handoff"]["flow"] == "terminal_connectivity"


def s05v_r2(env):
    run_s05v(env)
    require(env.idf_values, "S05-V: retrieve não calculou IDF (consulta sem termos conhecidos)")
    negative = sorted({(term, round(value, 3)) for term, value in env.idf_values if value < 0})
    assert negative == [], f"S05-V: termos com IDF negativo na chamada real a retrieve: {negative}"


CHECKS = {
    "S01-R1": s01_r1, "S01-R2": s01_r2, "S01-R3": s01_r3,
    "S02-R1": s02_r1, "S02-R2": s02_r2, "S02-R3": s02_r3,
    "S03-R1": s03_r1, "S03-R2": s03_r2, "S03-R3": s03_r3,
    "S04-R1": s04_r1, "S04-R2": s04_r2,
    "S05-R1": s05_r1, "S05-R2": s05_r2,
    "S06-R1": s06_r1, "S06-R2": s06_r2, "S06-R3": s06_r3,
    "S07-R1": s07_r1, "S07-R2": s07_r2, "S07-R3": s07_r3, "S07-R4": s07_r4,
    "S08-R1": s08_r1, "S08-R2": s08_r2, "S08-R3": s08_r3, "S08-R4": s08_r4,
    "S09-R1": s09_r1, "S09-R2": s09_r2, "S09-R3": s09_r3,
    "S10-R1": s10_r1, "S10-R2": s10_r2, "S10-R3": s10_r3,
}
ADDITIONAL_CHECKS = {"S05V-R1": s05v_r1, "S05V-R2": s05v_r2}


def _params(requirements):
    params = []
    for requirement in requirements:
        marks = []
        if requirement["baseline_expected"] == "xfail":
            marks.append(pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason=f"{requirement['backlog_id']}: {requirement['reason']}",
            ))
        params.append(pytest.param(requirement["id"], marks=marks, id=requirement["id"]))
    return params


OFFICIAL_REQUIREMENTS = [r for s in CRITERIA["scenarios"] for r in s["layer1"]["requirements"]]
ADDITIONAL_REQUIREMENTS = [r for c in CRITERIA["additional_cases"] for r in c["layer1"]["requirements"]]


@pytest.mark.parametrize("requirement_id", _params(OFFICIAL_REQUIREMENTS))
def test_official_requirement(requirement_id, env):
    CHECKS[requirement_id](env)


@pytest.mark.parametrize("requirement_id", _params(ADDITIONAL_REQUIREMENTS))
def test_additional_requirement(requirement_id, env):
    ADDITIONAL_CHECKS[requirement_id](env)


# --------------------------------------------------------------------------
# Integridade dos critérios (não contam como requisitos)
# --------------------------------------------------------------------------


def test_every_requirement_has_exactly_one_check():
    assert len(OFFICIAL_REQUIREMENTS) == 30
    assert {r["id"] for r in OFFICIAL_REQUIREMENTS} == set(CHECKS)
    assert {r["id"] for r in ADDITIONAL_REQUIREMENTS} == set(ADDITIONAL_CHECKS)
    assert set(CHECKS).isdisjoint(ADDITIONAL_CHECKS)


def test_xfail_requirements_name_a_backlog_item_and_reason():
    for requirement in OFFICIAL_REQUIREMENTS + ADDITIONAL_REQUIREMENTS:
        assert requirement["baseline_expected"] in {"pass", "xfail"}
        if requirement["baseline_expected"] == "xfail":
            assert requirement.get("backlog_id") and requirement.get("reason") and requirement.get("evidence")


def test_cited_documents_match_the_corpus():
    corpus_hash = hashlib.sha256((ROOT / CRITERIA["corpus"]["path"]).read_bytes()).hexdigest()
    assert corpus_hash == CRITERIA["corpus"]["sha256"], "corpus mudou: os critérios precisam de revisão"
    for case in CRITERIA["scenarios"] + CRITERIA["additional_cases"]:
        for kind in ("required", "any_of", "supporting", "not_gold"):
            for document in case["layer1"]["gold_documents"].get(kind, []):
                row = CORPUS[document["line"]]
                assert row["title"] == document["title"], (case["id"], document["line"])
                assert _content_hash(row["content"]) == document["content_sha256_12"], (case["id"], document["line"])
                assert row["source_url"] == document.get("source_url", row["source_url"])


def test_retriever_returns_corpus_content_unchanged():
    """A comparação por hash depende de retrieve devolver o conteúdo do corpus sem alteração."""
    by_hash = {_content_hash(row["content"]) for row in CORPUS.values()}
    for document in retriever.retrieve(SCENARIOS["S10"]["message"]):
        assert _content_hash(document["content"]) in by_hash
