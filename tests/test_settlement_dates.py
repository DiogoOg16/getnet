"""Liquidações simuladas com data da venda relativa a uma data de referência fixa.

Cenário 3 do desafio: "When will the money from yesterday's sales be deposited?".
Nenhum teste depende do relógio do sistema: a data de referência é fixada.
"""

from datetime import date

import pytest

from app.agents import customer_support as customer_support_module
from app.agents.customer_support import CustomerSupportAgent
from app.tools import customer_tools
from app.tools.customer_tools import filter_settlement_records, lookup_settlement

REFERENCE = date(2026, 11, 8)


class ErrorLoop:
    """Simula o Ollama indisponível para forçar o fallback do backend."""

    def run(self, messages, *, context=None, tools=None):
        raise ConnectionError("ollama unavailable")


@pytest.fixture
def fixed_reference(monkeypatch):
    monkeypatch.setattr(customer_tools, "settlement_reference_date", lambda: REFERENCE)
    monkeypatch.setattr(customer_support_module, "settlement_reference_date", lambda: REFERENCE)
    monkeypatch.setattr(customer_tools, "date", _DateWithoutToday)
    return REFERENCE


class _DateWithoutToday(date):
    @classmethod
    def today(cls):
        raise AssertionError("date.today() não deve ser chamado nos testes")


def test_records_have_sale_and_settlement_dates_relative_to_reference():
    result = lookup_settlement("cliente1988", reference_date=REFERENCE)

    assert result["reference_date"] == "2026-11-08"
    by_transaction = {record["transaction_id"]: record for record in result["records"]}
    assert by_transaction["txn1001"]["sale_date"] == "2026-11-07"
    assert by_transaction["txn1001"]["estimated_settlement_date"] == "2026-11-09"
    assert by_transaction["txn1002"]["sale_date"] == "2026-11-05"
    assert by_transaction["txn1002"]["estimated_settlement_date"] == "2026-11-08"
    for record in result["records"]:
        assert "sale_offset_days" not in record
        assert "settlement_offset_days" not in record


def test_dates_follow_the_reference_date_across_month_boundaries():
    result = lookup_settlement("cliente1988", reference_date=date(2026, 12, 1))

    by_transaction = {record["transaction_id"]: record for record in result["records"]}
    assert by_transaction["txn1001"]["sale_date"] == "2026-11-30"
    assert by_transaction["txn1001"]["estimated_settlement_date"] == "2026-12-02"


@pytest.mark.parametrize("reference", [date(2026, 1, 1), REFERENCE, date(2027, 2, 28)])
def test_status_is_coherent_with_the_estimated_settlement_date(reference):
    for record in lookup_settlement("cliente1988", reference_date=reference)["records"]:
        settlement = date.fromisoformat(record["estimated_settlement_date"])
        sale = date.fromisoformat(record["sale_date"])
        assert sale < reference
        if record["status"] in {"scheduled", "processing"}:
            assert settlement >= reference
        if record["status"] == "settled":
            assert settlement <= reference


def test_tool_filters_by_sale_date_and_excludes_other_dates():
    result = lookup_settlement("cliente1988", sale_date="2026-11-07", reference_date=REFERENCE)

    assert [record["transaction_id"] for record in result["records"]] == ["txn1001"]

    none = lookup_settlement("cliente1988", sale_date="2026-11-06", reference_date=REFERENCE)
    assert none["found"] is True
    assert none["records"] == []


def test_filter_ignores_records_without_sale_date():
    records = [{"transaction_id": "a"}, {"transaction_id": "b", "sale_date": "2026-11-07"}]

    assert filter_settlement_records(records, "2026-11-07") == [records[1]]


def test_tool_uses_the_reference_function_instead_of_the_clock(fixed_reference):
    result = lookup_settlement("cliente1988")

    assert result["reference_date"] == "2026-11-08"


@pytest.mark.parametrize(
    "message",
    [
        "When will the money from yesterday's sales be deposited?",
        "Quando o dinheiro das vendas de ontem será depositado?",
    ],
)
@pytest.mark.parametrize("loop", [None, ErrorLoop()], ids=["function_calling", "backend_fallback"])
def test_agent_answers_only_with_yesterdays_sales(fixed_reference, message, loop):
    agent = CustomerSupportAgent(loop=loop) if loop else CustomerSupportAgent()

    result = agent.answer(message, "cliente1988")
    response = result["response"]

    assert result["tool_used"] == "lookup_settlement"
    assert result["step_status"] == "success"
    assert "Prazo de recebimento das vendas de ontem (07/11/2026)" in response
    assert "venda txn1001 realizada em 07/11/2026" in response
    assert "data prevista de liquidação: 09/11/2026" in response
    assert "status da liquidação: agendada" in response
    assert "txn1002" not in response
    assert "05/11/2026" not in response
    assert "dados simulados" in response


def test_agent_distinguishes_sale_date_from_settlement_date(fixed_reference):
    response = CustomerSupportAgent(loop=ErrorLoop()).answer(
        "Quando o dinheiro das vendas será depositado?", "cliente1988"
    )["response"]

    assert "venda txn1001 realizada em 07/11/2026" in response
    assert "data prevista de liquidação: 09/11/2026" in response
    assert "venda txn1002 realizada em 05/11/2026" in response
    assert "data prevista de liquidação: 08/11/2026" in response
    assert "status da liquidação: em processamento" in response
    assert "scheduled" not in response
    assert "processing" not in response


def test_agent_says_when_there_are_no_sales_from_yesterday(fixed_reference, monkeypatch):
    records = customer_tools.SETTLEMENTS["cliente1988"]
    monkeypatch.setitem(
        customer_tools.SETTLEMENTS,
        "cliente1988",
        [record for record in records if record["transaction_id"] != "txn1001"],
    )

    response = CustomerSupportAgent(loop=ErrorLoop()).answer(
        "When will the money from yesterday's sales be deposited?", "cliente1988"
    )["response"]

    assert "Não encontrei vendas de ontem (07/11/2026)" in response
    assert "txn1002" not in response
    assert "dados simulados" in response


def test_settlements_stay_isolated_per_customer(fixed_reference):
    own = lookup_settlement("cliente1988")
    other = lookup_settlement("cliente2001")
    unknown = lookup_settlement("cliente9999")

    assert {record["customer_id"] for record in own["records"]} == {"cliente1988"}
    assert other["found"] is True
    assert other["records"] == []
    assert unknown["found"] is False

    response = CustomerSupportAgent(loop=ErrorLoop()).answer(
        "When will the money from yesterday's sales be deposited?", "cliente2001"
    )["response"]
    assert "venda txn1001" not in response
    assert "Não encontrei vendas de ontem (07/11/2026)" in response


# --- Registros malformados: todos os caminhos devolvem o contrato invalid_result ---


class _Loop:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def run(self, messages, *, context=None, tools=None):
        if self.error is not None:
            raise self.error
        return self.result


def _settlement_tool_result(payload):
    return {"tool_name": "lookup_settlement", "result": {"ok": True, "result": payload}}


def _paths(payload):
    """Os quatro caminhos que chegam a `_settlement_message`."""
    return {
        "function_calling": (_Loop({"status": "completed", "tool_results": [_settlement_tool_result(payload)]}), False),
        "fallback_on_tool_call_error": (_Loop(error=ConnectionError("ollama unavailable")), True),
        "fallback_when_other_tool_was_called": (
            _Loop({"status": "completed", "tool_results": [{"tool_name": "lookup_customer", "result": {"ok": True, "result": {}}}]}),
            True,
        ),
        "fallback_without_tool_calls": (_Loop({"status": "completed", "tool_results": []}), True),
    }


MALFORMED_RECORDS = {
    "list_with_non_dict": [{"transaction_id": "txn1001", "sale_date": "2026-11-07"}, "registro"],
    "number": 5,
    "dict_instead_of_list": {"transaction_id": "txn1001"},
}


@pytest.mark.parametrize("records_kind", MALFORMED_RECORDS)
@pytest.mark.parametrize(
    "path",
    ["function_calling", "fallback_on_tool_call_error", "fallback_when_other_tool_was_called", "fallback_without_tool_calls"],
)
def test_malformed_settlement_records_return_invalid_result(fixed_reference, monkeypatch, path, records_kind):
    payload = {"found": True, "simulated": True, "reference_date": "2026-11-08", "records": MALFORMED_RECORDS[records_kind]}
    loop, uses_backend = _paths(payload)[path]
    if uses_backend:
        monkeypatch.setattr(CustomerSupportAgent, "_execute_backend_tool", lambda self, name, arguments, user_id: payload)

    result = CustomerSupportAgent(loop=loop).answer(
        "When will the money from yesterday's sales be deposited?", "cliente1988"
    )

    assert result["step_status"] == "invalid_result"
    assert result["function_call_status"] == "invalid_result"
    assert result["tool_used"] == "lookup_settlement"
    assert result["issue_resolved"] is False
    assert result["awaiting_user_input"] is True
    assert "registros incompletos" in result["response"]
    assert "Prazo de recebimento" not in result["response"]


@pytest.mark.parametrize(
    "path",
    ["function_calling", "fallback_on_tool_call_error", "fallback_when_other_tool_was_called", "fallback_without_tool_calls"],
)
def test_valid_settlement_records_still_succeed_on_every_path(fixed_reference, path):
    payload = lookup_settlement("cliente1988")
    loop, _ = _paths(payload)[path]

    result = CustomerSupportAgent(loop=loop).answer(
        "When will the money from yesterday's sales be deposited?", "cliente1988"
    )

    assert result["step_status"] == "success"
    assert "Prazo de recebimento das vendas de ontem (07/11/2026)" in result["response"]
