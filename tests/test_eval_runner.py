"""Testes offline do runner de EVAL-01 (eval/run_official_scenarios.py).

Não chamam o Ollama nem sobem a aplicação (de app/ só usam OllamaClient._payload,
que não acessa a rede): verificam o congelamento dos
critérios, a classificação das execuções, o cegamento (A1), o fluxo separado de
fallback (B1), os dados de reprodutibilidade (C1–C3) e o ciclo
blind → freeze → report.
"""

import importlib.util
import json
import re
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("eval_runner", ROOT / "eval" / "run_official_scenarios.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

ABSOLUTE_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")


def turn(text, *, tool="ollama", llm_ok=True, status=200, model="qwen2.5:7b"):
    call = {"ok": llm_ok, "latency_s": 1.0, "options": "not_sent", "has_tools": False,
            "system_prompt_sha256_16": "d21a93002e54b7e0", "timeout_s": 60, "model_requested": model}
    if llm_ok:
        call["model_returned"] = model
    return {
        "message": "pergunta",
        "http_status": status,
        "latency_s": 1.0,
        "response": {"response": text, "tool_used": tool},
        "retrieved": [[{"line": 269, "content_sha256_12": "40b9aeaf79b8", "title": "Doc", "score": 9.0}]],
        "llm_calls": [call],
    }


def test_frozen_criteria_match_the_files():
    assert runner.check_frozen_criteria() == runner.FROZEN_CRITERIA


def test_n_per_scenario_follows_the_criteria():
    criteria = runner.load_criteria()
    n = criteria["layer2_conventions"]["n_per_scenario"]
    ids = [c["id"] for c in criteria["scenarios"]] + [c["id"] for c in criteria["additional_cases"]]
    assert set(n) == set(ids)
    assert n["S02"] == n["S07"] == 3
    assert all(n[s] == 10 for s in ids if s not in {"S02", "S07"})


@pytest.mark.parametrize(
    ("scenario", "turns", "outcome"),
    [
        ("S01", [turn("resposta")], "generated"),
        ("S01", [turn("trechos", tool="retrieval_only")], "degraded"),
        ("S03", [turn("resposta", tool="lookup_settlement", llm_ok=False)], "degraded"),
        ("S02", [turn("Serviço indisponível.", tool="open_meteo")], "external_unavailable"),
        ("S02", [turn("mínima de 15.8 °C", tool="open_meteo")], "generated"),
        ("S07", [turn("compra R$ 6,1300", tool="bcb_ptax")], "generated"),
        ("S08", [turn("ok"), turn("erro", status=500)], "http_error"),
    ],
)
def test_classify_execution(scenario, turns, outcome):
    assert runner.classify_execution(scenario, turns)["outcome"] == outcome


# --- A1: datas relativas ----------------------------------------------------

SUNDAY = date(2026, 11, 8)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # S02: amanhã continua identificável sem a data absoluta.
        ("Previsão para Porto Alegre, Rio Grande do Sul em 09/11/2026: mínima de 15.8 °C.",
         "Previsão para Porto Alegre, Rio Grande do Sul em [D+1, seg]: mínima de 15.8 °C."),
        # S03: "ontem" e os valores ficam; as datas viram relativas.
        ("Prazo de recebimento das vendas de ontem (07/11/2026): venda txn1001 realizada em 07/11/2026; "
         "valor: R$ 149.90; data prevista de liquidação: 09/11/2026.",
         "Prazo de recebimento das vendas de ontem ([D-1, sáb]): venda txn1001 realizada em [D-1, sáb]; "
         "valor: R$ 149.90; data prevista de liquidação: [D+1, seg]."),
        # S07: o dia da semana permite julgar "último dia útil".
        ("Cotação do euro (PTAX de fechamento do Banco Central, 06/11/2026 13:06): compra R$ 6,1300, venda R$ 6,1317.",
         "Cotação do euro (PTAX de fechamento do Banco Central, [D-2, sex] 13:06): compra R$ 6,1300, venda R$ 6,1317."),
        ("sale_date 2026-11-08", "sale_date [D, dom]"),
        ("data inválida 31/02/2026 fica como está", "data inválida 31/02/2026 fica como está"),
    ],
)
def test_mask_dates_keeps_meaning_and_hides_absolute_dates(text, expected):
    assert runner.mask_dates(text, SUNDAY) == expected


# --- C1–C3: reprodutibilidade ----------------------------------------------


def test_pip_freeze_is_saved_with_its_hash(tmp_path):
    info = runner.capture_pip_freeze(tmp_path)
    saved = tmp_path / info["file"]
    assert saved.exists() and info["packages"] > 0 and info["returncode"] == 0
    assert info["sha256"] == runner.sha256_file(saved)
    assert "pytest==" in saved.read_text()


class PayloadClient:
    """Imita OllamaClient._payload sem rede."""

    timeout = 60
    model = "qwen2.5:7b"

    def __init__(self, options=None):
        self.options = options

    def _payload(self, messages, tools=None):
        payload = {"model": self.model, "stream": False, "messages": messages}
        if tools is not None:
            payload["tools"] = tools
        if self.options is not None:
            payload["options"] = self.options
        return payload


MESSAGES = [{"role": "system", "content": "Você é um agente de suporte da Getnet."}, {"role": "user", "content": "oi"}]


def test_payload_facts_distinguishes_options_not_sent_from_explicit():
    absent = runner.payload_facts(PayloadClient(), MESSAGES, None)
    explicit = runner.payload_facts(PayloadClient(options={"temperature": 0}), MESSAGES, [{"type": "function"}])

    assert absent["options"] == "not_sent" and "options" not in absent["payload_keys"]
    assert explicit["options"] == {"temperature": 0} and "options" in explicit["payload_keys"]
    assert absent["has_tools"] is False and explicit["has_tools"] is True
    assert absent["timeout_s"] == 60 and absent["model_requested"] == "qwen2.5:7b"
    assert absent["system_prompt_sha256_16"] == runner.sha256_text(MESSAGES[0]["content"])


def test_payload_facts_uses_the_real_client_payload():
    from app.llm.ollama_client import OllamaClient

    facts = runner.payload_facts(OllamaClient("http://127.0.0.1:9", "qwen2.5:7b"), MESSAGES, None)
    assert facts["options"] == "not_sent"
    assert facts["timeout_s"] == 60


def test_summarize_llm_calls_reports_models_returned_and_configuration():
    executions = [
        {"turns": [turn("a", model="qwen2.5:7b"), turn("b", llm_ok=False)]},
        {"turns": [turn("c", model="qwen2.5:7b-instruct")]},
    ]
    summary = runner.summarize_llm_calls(executions)
    assert summary["llm_calls"] == 3 and summary["llm_calls_failed"] == 1
    assert summary["models_returned"] == ["qwen2.5:7b", "qwen2.5:7b-instruct"]
    assert summary["options_sent"] == ["not_sent"]
    assert summary["timeouts_s"] == [60]
    assert summary["system_prompts"] == [{"has_tools": False, "sha256_16": "d21a93002e54b7e0"}]


# --- blind / freeze / report ------------------------------------------------


def write_run(directory: Path, run_id: str, commit: str, executions: list[dict]):
    directory.mkdir(parents=True)
    criteria = {name: runner.FROZEN_CRITERIA[name] for name in runner.FROZEN_CRITERIA}
    (directory / "manifest.json").write_text(json.dumps({"run_id": run_id, "code": {"head": commit}, "criteria_sha256": criteria}))
    (directory / "executions.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in executions) + "\n")


def execution(scenario, index, outcome, text, day="2026-11-08"):
    turns = [turn(text, llm_ok=outcome != "degraded")]
    return {"scenario": scenario, "index": index, "outcome": outcome, "execution_date": day,
            "finished_at": f"{day}T12:00:00+00:00", "turns": turns}


S03_TEXT = "Prazo de recebimento das vendas de ontem (07/11/2026): venda txn1001 realizada em 07/11/2026."


@pytest.fixture
def two_runs(tmp_path):
    write_run(tmp_path / "run_a", "A", "939d2ba", [
        execution("S03", 0, "generated", S03_TEXT),
        execution("S03", 1, "degraded", "fallback A1 " + S03_TEXT),
    ])
    write_run(tmp_path / "run_b", "B", "abc1234", [
        execution("S03", 0, "generated", "Prazo de recebimento das vendas de ontem (08/11/2026).", day="2026-11-09"),
        execution("S03", 1, "generated", "texto B1", day="2026-11-09"),
    ])
    return tmp_path


def blind(two_runs, seed=7, name="blind"):
    out = two_runs / name
    runner.main(["blind", "--runs", str(two_runs / "run_a"), str(two_runs / "run_b"), "--out", str(out), "--seed", str(seed)])
    return out


def label_all(path: Path, label_for):
    labels = json.loads(path.read_text())
    for item_id in labels:
        labels[item_id] = {"label": label_for(item_id), "justification": "teste", "annotations": {}}
    path.write_text(json.dumps(labels))


def test_blind_sheets_hide_version_and_absolute_dates(two_runs):
    out = blind(two_runs)
    sheets = "".join(p.read_text() for p in out.glob("*.md"))
    for leak in ("939d2ba", "abc1234", "run_a", "run_b", "qwen2.5", "d21a93002e54b7e0"):
        assert leak not in sheets
    assert not ABSOLUTE_DATE.search(sheets)
    main_sheet = (out / "cego_S03.md").read_text()
    assert "vendas de ontem ([D-1, sáb])" in main_sheet and "txn1001" in main_sheet
    # runs de dias diferentes mostram o mesmo texto relativo
    assert main_sheet.count("vendas de ontem ([D-1,") == 2


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"tool_used": None, "step_status": "handoff",
          "handoff": {"id": "6e5ed31c9f26", "flow": "terminal_connectivity", "status": "pending"}},
         "Operação: tool_used=nenhuma; step_status=handoff; ticket_opened=sim; ticket_flow=terminal_connectivity"),
        ({"tool_used": "lookup_transaction", "step_status": "success", "handoff": None},
         "Operação: tool_used=lookup_transaction; step_status=success; ticket_opened=não; ticket_flow=—"),
        ("erro 500", "Operação: resposta não disponível"),
    ],
)
def test_operational_facts(response, expected):
    line = runner.operational_facts(response)
    assert line == expected
    assert "6e5ed31c9f26" not in line  # o ID do ticket não aparece


def test_blind_sheets_show_operational_facts_without_leaking_version(tmp_path):
    handoff_turn = turn("Vou encaminhar para atendimento humano.", tool=None)
    handoff_turn["response"].update({"step_status": "handoff",
                                     "handoff": {"id": "abc123def456", "flow": "terminal_connectivity"}})
    write_run(tmp_path / "run_a", "A", "939d2ba", [
        {"scenario": "S05", "index": 0, "outcome": "generated", "execution_date": "2026-11-08",
         "finished_at": "2026-11-08T12:00:00+00:00", "turns": [handoff_turn]},
    ])
    out = tmp_path / "blind"
    runner.main(["blind", "--runs", str(tmp_path / "run_a"), "--out", str(out), "--seed", "1"])
    sheet = (out / "cego_S05.md").read_text()
    assert "ticket_opened=sim; ticket_flow=terminal_connectivity" in sheet
    assert "step_status=handoff" in sheet
    for leak in ("abc123def456", "939d2ba", "qwen2.5", "run_a"):
        assert leak not in sheet


def test_blind_does_not_modify_the_original_runs(two_runs):
    before = {p: runner.sha256_file(p) for p in sorted(two_runs.glob("run_*/*"))}
    blind(two_runs)
    after = {p: runner.sha256_file(p) for p in sorted(two_runs.glob("run_*/*"))}
    assert before == after


def test_degraded_executions_go_only_to_the_fallback_sheet(two_runs):
    out = blind(two_runs)
    assert "fallback A1" not in (out / "cego_S03.md").read_text()
    assert "fallback A1" in (out / "fallback_S03.md").read_text()
    mapping = json.loads((out / "mapa_oculto" / "map.json").read_text())
    assert len(mapping["items"]) == 3 and len(mapping["fallback_items"]) == 1 and mapping["excluded"] == []
    assert set(json.loads((out / "labels_fallback.json").read_text())) == set(mapping["fallback_items"])
    assert (out / "README.md").exists()


def test_blind_is_reproducible_with_the_same_seed(two_runs):
    first = json.loads((blind(two_runs, 7, "b1") / "mapa_oculto" / "map.json").read_text())
    second = json.loads((blind(two_runs, 7, "b2") / "mapa_oculto" / "map.json").read_text())
    assert first["items"] == second["items"] and first["fallback_items"] == second["fallback_items"]


def test_report_keeps_fallback_quality_separate_from_quality(two_runs):
    out = blind(two_runs)
    with pytest.raises(SystemExit):
        runner.main(["report", "--blind", str(out)])

    label_all(out / "labels.json", lambda item: "P")
    with pytest.raises(SystemExit):
        runner.main(["freeze", "--blind", str(out)])  # fallback ainda sem rótulo

    label_all(out / "labels_fallback.json", lambda item: "C")
    runner.main(["freeze", "--blind", str(out)])
    runner.main(["report", "--blind", str(out)])

    rows = {row["run_id"]: row for row in json.loads((out / "report.json").read_text())["rows"]}
    assert rows["A"]["executions"] == 2 and rows["A"]["generated"] == 1 and rows["A"]["degraded"] == 1
    assert rows["A"]["availability"] == 0.5 and rows["A"]["degradation_rate"] == 0.5
    assert rows["A"]["quality"] == {"C": 0, "P": 1, "I": 0}
    assert rows["A"]["fallback_quality"] == {"C": 1, "P": 0, "I": 0}
    assert rows["B"]["quality"] == {"C": 0, "P": 2, "I": 0} and rows["B"]["fallback_quality"] == {"C": 0, "P": 0, "I": 0}


@pytest.mark.parametrize("changed", ["labels.json", "labels_fallback.json"])
def test_report_refuses_labels_changed_after_freeze(two_runs, changed):
    out = blind(two_runs)
    label_all(out / "labels.json", lambda item: "C")
    label_all(out / "labels_fallback.json", lambda item: "C")
    runner.main(["freeze", "--blind", str(out)])
    label_all(out / changed, lambda item: "I")
    with pytest.raises(SystemExit):
        runner.main(["report", "--blind", str(out)])


def test_blind_refuses_runs_with_different_criteria(two_runs):
    manifest = json.loads((two_runs / "run_b" / "manifest.json").read_text())
    manifest["criteria_sha256"] = {"eval/official_scenarios.json": "outro"}
    (two_runs / "run_b" / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SystemExit):
        blind(two_runs)
