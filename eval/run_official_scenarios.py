"""EVAL-01, camada 2: avaliação dos cenários oficiais com o Ollama real.

Fora do CI. Quatro subcomandos, na ordem do procedimento das rubricas:

  run     gera N execuções por cenário (N de eval/official_scenarios.json) e grava
          manifesto, execuções, pip freeze e hashes. Usa a aplicação em processo
          (TestClient sobre POST /chat), com armazenamento temporário próprio e
          tokens gerados na hora: não lê .env nem toca dados de produção.
  blind   embaralha as execuções de um ou mais runs, esconde versão e metadados
          e escreve duas folhas por cenário: a principal (execuções `generated`)
          e a de fallback (execuções `degraded`). Datas absolutas viram datas
          relativas ao dia da execução ([D-1, sáb]); os arquivos originais não mudam.
  freeze  registra o hash dos rótulos (principal e fallback) antes de revelar o mapa.
  report  só roda com os rótulos congelados; revela o mapa e calcula, por run e
          cenário, availability, quality, degradation e, à parte, a qualidade
          do fallback.

Exemplos:
  python eval/run_official_scenarios.py run --out ~/getnet-experiments/eval01/run-939d2ba
  python eval/run_official_scenarios.py run --out DIR --only S03,S05
  python eval/run_official_scenarios.py blind --runs DIR_A DIR_B --out BLIND --seed 20261108
  python eval/run_official_scenarios.py freeze --blind BLIND
  python eval/run_official_scenarios.py report --blind BLIND

O rótulo de referência é humano (Correta / Parcial / Incorreta). Não há juiz LLM.

Limitações conhecidas do cegamento:
  A2  As folhas mostram os documentos recuperados, porque a rubrica julga a
      suficiência da evidência. Se uma versão muda a recuperação, a lista de
      documentos pode revelar qual versão produziu a resposta.
  A3  O mapa de identificação fica em BLIND/mapa_oculto/. O cegamento depende
      também do procedimento: quem classifica não abre essa pasta antes do
      `freeze`. `freeze` e `report` garantem a ordem, não o desconhecimento.
  A1  (residual) As datas relativas trazem o dia da semana, necessário para
      julgar "último dia útil" (S07); runs feitos em dias da semana diferentes
      podem ser distinguidos, mas não ordenados.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITERIA_PATH = ROOT / "eval" / "official_scenarios.json"
RUBRICS_PATH = ROOT / "eval" / "official_scenarios_rubrics.md"

# Critérios v1.2 congelados em 2026-11-08. Mudar os critérios exige nova versão
# e atualização explícita destes valores.
FROZEN_CRITERIA = {
    "eval/official_scenarios.json": "f2f6875105fc96a98b63b2cbf199e7fb84145e230f4939b1ab179354ffc1b5de",
    "eval/official_scenarios_rubrics.md": "b8f9d7f61f7c7eb5c152615f6b44f75ce94b57ace9fb37b50a70e1239e0f8cff",
}

LABELS = {"C": "Correta", "P": "Parcial", "I": "Incorreta"}
EXTERNAL_VALUE_MARKERS = {"S02": "°C", "S07": "R$"}
WEEKDAYS_PT = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
BLIND_README = """# Classificação cega

- `cego_<cenário>.md`: execuções geradas normalmente; rótulos em `labels.json`. Entram em quality.
- `fallback_<cenário>.md`: execuções degradadas (falha do LLM ou resposta extrativa); rótulos em
  `labels_fallback.json`. Avaliam só a qualidade do fallback e não entram em quality.
- Rótulos: C (Correta), P (Parcial), I (Incorreta), sempre com justificativa, conforme
  eval/official_scenarios_rubrics.md.
- Datas absolutas aparecem como datas relativas ao dia da execução D, com o dia da semana:
  `[D-1, sáb]` é a véspera de D. O cabeçalho de cada item informa o dia da semana de D.
- Cada turno mostra a linha `Operação:` com a ferramenta usada (`tool_used`), o `step_status`
  e se um ticket de atendimento humano foi aberto (`ticket_opened`, `ticket_flow`). São fatos
  da resposta da API que as rubricas julgam e que não aparecem no texto.

Não abra `mapa_oculto/` antes de rodar `freeze`.

Limitações: os documentos recuperados podem revelar a versão (A2); o cegamento depende de não
abrir o mapa antes do congelamento (A3); o dia da semana permite distinguir, mas não ordenar,
runs de dias diferentes (A1 residual).
"""


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def check_frozen_criteria() -> dict[str, str]:
    actual = {name: sha256_file(ROOT / name) for name in FROZEN_CRITERIA}
    if actual != FROZEN_CRITERIA:
        raise SystemExit(
            "Critérios diferentes da versão congelada. Crie uma nova versão e atualize "
            f"FROZEN_CRITERIA explicitamente.\nesperado: {FROZEN_CRITERIA}\natual: {actual}"
        )
    return actual


def load_criteria() -> dict:
    return json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))


def scenario_turns(case: dict) -> list[str]:
    return list(case["turns"]) if "turns" in case else [case["message"]]


def write_sha256sums(directory: Path) -> None:
    lines = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{sha256_file(path)}  {path.relative_to(directory)}")
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def code_identity() -> dict:
    """Identifica o código avaliado sem ambiguidade, inclusive com árvore suja."""
    tracked_app = git("ls-files", "app").splitlines()
    digest = hashlib.sha256()
    for name in sorted(tracked_app):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((ROOT / name).read_bytes())
    app_matches_head = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "app"], cwd=ROOT
    ).returncode == 0
    return {
        "head": git("rev-parse", "HEAD"),
        "head_tree": git("rev-parse", "HEAD^{tree}"),
        "head_app_tree": git("rev-parse", "HEAD:app"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "status_porcelain": git("status", "--porcelain").splitlines(),
        "app_working_tree_sha256": digest.hexdigest(),
        "app_matches_head": app_matches_head,
    }


def capture_pip_freeze(out: Path) -> dict:
    """C1: versões das dependências do interpretador que executa a avaliação."""
    result = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True)
    path = out / "pip_freeze.txt"
    path.write_text(result.stdout, encoding="utf-8")
    return {"file": path.name, "sha256": sha256_file(path), "packages": len(result.stdout.splitlines()),
            "returncode": result.returncode}


def payload_facts(client, messages: list[dict], tools) -> dict:
    """C2: o que a chamada realmente envia ao /api/chat, sem adivinhar padrões.

    Usa o próprio `_payload` do cliente. Se o campo `options` não está no payload,
    registra "not_sent": o Ollama usa os padrões do servidor e nada foi configurado.
    """
    payload = client._payload(messages, tools)
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), None)
    return {
        "payload_keys": sorted(payload),
        "options": payload["options"] if "options" in payload else "not_sent",
        "model_requested": payload.get("model"),
        "has_tools": tools is not None,
        "system_prompt_sha256_16": sha256_text(system) if system is not None else None,
        "timeout_s": getattr(client, "timeout", None),
    }


def summarize_llm_calls(executions: list[dict]) -> dict:
    """C2/C3: resumo das configurações e modelos efetivamente usados no run."""
    calls = [call for e in executions for t in e["turns"] for call in t["llm_calls"]]
    options = sorted({json.dumps(c.get("options"), sort_keys=True) for c in calls})
    prompts = sorted({(c.get("has_tools"), c.get("system_prompt_sha256_16")) for c in calls}, key=str)
    return {
        "llm_calls": len(calls),
        "llm_calls_failed": sum(1 for c in calls if not c.get("ok")),
        "models_requested": sorted({c.get("model_requested") for c in calls if c.get("model_requested")}),
        "models_returned": sorted({c.get("model_returned") for c in calls if c.get("model_returned")}),
        "options_sent": [json.loads(o) for o in options],
        "timeouts_s": sorted({c.get("timeout_s") for c in calls if c.get("timeout_s") is not None}),
        "system_prompts": [{"has_tools": t, "sha256_16": h} for t, h in prompts],
    }


_DATE_BR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def mask_dates(text: str, execution_day: date) -> str:
    """A1: troca datas absolutas por datas relativas ao dia da execução.

    "07/11/2026" com D = 08/11/2026 vira "[D-1, sáb]". Preserva o que as rubricas
    julgam (amanhã, ontem, último dia útil) e esconde a data absoluta.
    """

    def token(day: date) -> str:
        offset = (day - execution_day).days
        label = "D" if offset == 0 else f"D{offset:+d}"
        return f"[{label}, {WEEKDAYS_PT[day.weekday()]}]"

    def replace_br(match):
        try:
            return token(date(int(match.group(3)), int(match.group(2)), int(match.group(1))))
        except ValueError:
            return match.group(0)

    def replace_iso(match):
        try:
            return token(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            return match.group(0)

    return _DATE_ISO.sub(replace_iso, _DATE_BR.sub(replace_br, text))


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> None:
    criteria_hashes = check_frozen_criteria()
    criteria = load_criteria()
    out = Path(args.out).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} já existe e não está vazio; use outro diretório.")
    out.mkdir(parents=True, exist_ok=True)

    cases = {c["id"]: c for c in criteria["scenarios"]}
    cases.update({c["id"]: c for c in criteria["additional_cases"]})
    n_per = criteria["layer2_conventions"]["n_per_scenario"]
    selected = args.only.split(",") if args.only else list(cases)
    unknown = [s for s in selected if s not in cases]
    if unknown:
        raise SystemExit(f"Cenários desconhecidos: {unknown}")

    # Estado e credenciais isolados, definidos antes de importar a aplicação.
    state_dir = Path(tempfile.mkdtemp(prefix="eval01-state-"))
    token = "eval-" + secrets.token_hex(16)
    os.environ["GETNET_HUMAN_HANDOFF_PATH"] = str(state_dir / "handoff.json")
    os.environ["GETNET_SESSION_MEMORY_PATH"] = str(state_dir / "session.json")
    os.environ["GETNET_DEMO_AUTH_TOKENS"] = json.dumps({token: "cliente1988"})
    os.environ["OLLAMA_URL"] = args.ollama_url
    os.environ["OLLAMA_MODEL"] = args.model
    sys.path.insert(0, str(ROOT))

    import requests
    from fastapi.testclient import TestClient

    import app.agents.knowledge as knowledge_module
    from app.llm.ollama_client import OllamaClient
    from app.main import app, orchestrator
    from app.tools.customer_tools import settlement_reference_date

    corpus_path = ROOT / criteria["corpus"]["path"]
    by_hash = {}
    for number, line in enumerate(corpus_path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            row = json.loads(line)
            by_hash.setdefault(hashlib.sha256(row["content"].encode()).hexdigest()[:12], number)

    turn_log: dict = {"retrieved": [], "llm_calls": []}
    original_retrieve = knowledge_module.retrieve

    def recording_retrieve(query, *a, **kw):
        documents = original_retrieve(query, *a, **kw)
        turn_log["retrieved"].append([
            {
                "line": by_hash.get(hashlib.sha256(d["content"].encode()).hexdigest()[:12]),
                "content_sha256_12": hashlib.sha256(d["content"].encode()).hexdigest()[:12],
                "title": d["title"],
                "score": d.get("score"),
            }
            for d in documents
        ])
        return documents

    knowledge_module.retrieve = recording_retrieve

    original_chat = OllamaClient.chat

    def recording_chat(self, messages, tools=None):
        call = payload_facts(self, messages, tools)
        started = time.perf_counter()
        try:
            response = original_chat(self, messages, tools)
        except Exception as error:
            call.update({"ok": False, "error": type(error).__name__,
                         "latency_s": round(time.perf_counter() - started, 2)})
            turn_log["llm_calls"].append(call)
            raise
        call.update({"ok": True, "latency_s": round(time.perf_counter() - started, 2),
                     "model_returned": response.get("model"), "eval_count": response.get("eval_count")})
        turn_log["llm_calls"].append(call)
        return response

    OllamaClient.chat = recording_chat

    def server_info(path: str):
        try:
            return requests.get(f"{args.ollama_url}{path}", timeout=10).json()
        except Exception as error:  # registrado no manifesto; as execuções aparecerão como degradadas
            return {"unavailable": type(error).__name__}

    tags = server_info("/api/tags")
    model_digest = next((m.get("digest") for m in tags.get("models", []) if m.get("name") == args.model), None) \
        if "models" in tags else f"indisponível: {tags.get('unavailable')}"
    ollama_version = server_info("/api/version")

    warmup = None
    if not args.no_warmup:
        started = time.perf_counter()
        try:
            original_chat(OllamaClient(args.ollama_url, args.model), [{"role": "user", "content": "ok"}])
            warmup = {"ok": True, "latency_s": round(time.perf_counter() - started, 2)}
        except Exception as error:
            warmup = {"ok": False, "error": type(error).__name__, "latency_s": round(time.perf_counter() - started, 2)}

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    manifest = {
        "run_id": run_id,
        "started_at": now_utc(),
        "code": code_identity(),
        "criteria_sha256": criteria_hashes,
        "criteria_version": criteria["version"],
        "corpus_sha256": sha256_file(corpus_path),
        "model": args.model,
        "model_digest": model_digest,
        "ollama_url": args.ollama_url,
        "ollama_server_version": ollama_version.get("version", ollama_version),
        "client_timeouts_s": {
            "knowledge": getattr(orchestrator.knowledge.client, "timeout", None),
            "customer_support": getattr(orchestrator.support.client, "timeout", None),
        },
        "warmup": warmup,
        "settlement_reference_date": settlement_reference_date().isoformat(),
        "scenarios": selected,
        "n_per_scenario": {s: n_per[s] for s in selected},
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pip_freeze": capture_pip_freeze(out),
        "isolated_state_dir": str(state_dir),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    official_ids = {c["id"] for c in criteria["scenarios"]}
    executions = []
    with (out / "executions.jsonl").open("w", encoding="utf-8") as sink:
        for scenario_id in selected:
            case = cases[scenario_id]
            for index in range(n_per[scenario_id]):
                session_id = f"eval-{run_id}-{scenario_id}-{index:02d}"
                execution_day = date.today()
                turns = []
                for message in scenario_turns(case):
                    turn_log["retrieved"], turn_log["llm_calls"] = [], []
                    started = time.perf_counter()
                    response = client.post("/chat", json={"message": message, "user_id": "cliente1988", "session_id": session_id})
                    turns.append({
                        "message": message,
                        "http_status": response.status_code,
                        "latency_s": round(time.perf_counter() - started, 2),
                        "response": response.json() if response.status_code == 200 else response.text,
                        "retrieved": turn_log["retrieved"],
                        "llm_calls": turn_log["llm_calls"],
                    })
                record = classify_execution(scenario_id, turns)
                record.update({"scenario": scenario_id, "group": "official" if scenario_id in official_ids else "additional",
                               "index": index, "session_id": session_id, "execution_date": execution_day.isoformat(),
                               "finished_at": now_utc(), "turns": turns})
                executions.append(record)
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                print(f"{scenario_id} #{index:02d} {record['outcome']} {sum(t['latency_s'] for t in turns):.1f}s", flush=True)

    manifest["finished_at"] = now_utc()
    manifest["generation"] = summarize_llm_calls(executions)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_sha256sums(out)
    print(f"Execução gravada em {out}")


def classify_execution(scenario_id: str, turns: list[dict]) -> dict:
    """outcome = generated | degraded | external_unavailable | http_error."""
    if any(t["http_status"] != 200 for t in turns):
        return {"outcome": "http_error"}
    llm_failed = any(not call["ok"] for t in turns for call in t["llm_calls"])
    extractive = any("retrieval_only" in str(t["response"].get("tool_used") or "") for t in turns)
    if llm_failed or extractive:
        return {"outcome": "degraded", "degraded_reason": "llm_error" if llm_failed else "retrieval_only"}
    marker = EXTERNAL_VALUE_MARKERS.get(scenario_id)
    if marker and not any(marker in t["response"].get("response", "") for t in turns):
        return {"outcome": "external_unavailable"}
    return {"outcome": "generated"}


# --------------------------------------------------------------------------
# blind / freeze / report
# --------------------------------------------------------------------------


def load_run(directory: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    executions = [json.loads(line) for line in (directory / "executions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return manifest, executions


def _execution_day(execution: dict) -> date:
    if execution.get("execution_date"):
        return date.fromisoformat(execution["execution_date"])
    return datetime.fromisoformat(execution["finished_at"]).astimezone().date()


def operational_facts(response) -> str:
    """Estado operacional do turno que as rubricas julgam (ferramenta, status, ticket).

    Vem da resposta da API, não identifica versão, commit ou modelo, e o ID do
    ticket não é mostrado (só se foi aberto e com qual fluxo).
    """
    if not isinstance(response, dict):
        return "Operação: resposta não disponível"
    ticket = response.get("handoff") if isinstance(response.get("handoff"), dict) else None
    opened = "sim" if ticket and ticket.get("id") else "não"
    flow = (ticket or {}).get("flow") or "—"
    return (f"Operação: tool_used={response.get('tool_used') or 'nenhuma'}; "
            f"step_status={response.get('step_status') or '—'}; "
            f"ticket_opened={opened}; ticket_flow={flow}")


def _sheet(scenario_id: str, title: str, items: list[tuple[str, dict]]) -> str:
    lines = [f"# {scenario_id} — {title}", "",
             f"Rubrica: eval/official_scenarios_rubrics.md#{scenario_id.lower()}", ""]
    for item_id, execution in items:
        day = _execution_day(execution)
        lines.append(f"## {item_id}")
        lines.append(f"Dia da execução: D ({WEEKDAYS_PT[day.weekday()]})")
        lines.append("")
        for turn_number, turn in enumerate(execution["turns"], start=1):
            lines.append(f"**Turno {turn_number} — usuário:** {mask_dates(turn['message'], day)}")
            recovered = [f"L{d['line']} {d['title']}" for call in turn["retrieved"] for d in call]
            lines.append(f"Documentos recuperados: {', '.join(recovered) if recovered else 'nenhum'}")
            lines.append(operational_facts(turn["response"]))
            lines.append("")
            text = turn["response"].get("response", "") if isinstance(turn["response"], dict) else str(turn["response"])
            lines.append(mask_dates(text, day))
            lines.append("")
    return "\n".join(lines)


def cmd_blind(args: argparse.Namespace) -> None:
    out = Path(args.out).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} já existe e não está vazio.")
    out.mkdir(parents=True)
    runs = [Path(r).expanduser().resolve() for r in args.runs]
    loaded = [(run, *load_run(run)) for run in runs]
    criteria_versions = {json.dumps(m["criteria_sha256"], sort_keys=True) for _, m, _ in loaded}
    if len(criteria_versions) != 1:
        raise SystemExit("Os runs usam versões diferentes dos critérios; não é possível compará-los.")

    pools: dict[str, dict[str, list]] = {"generated": {}, "degraded": {}}
    excluded = []
    for run, manifest, executions in loaded:
        for execution in executions:
            source = {"run_dir": str(run), "run_id": manifest["run_id"], "commit": manifest["code"]["head"],
                      "scenario": execution["scenario"], "index": execution["index"], "outcome": execution["outcome"]}
            if execution["outcome"] in pools:
                pools[execution["outcome"]].setdefault(execution["scenario"], []).append((source, execution))
            else:
                excluded.append(source)

    rng = random.Random(args.seed)
    maps = {"generated": {}, "degraded": {}}
    templates = {"generated": {}, "degraded": {}}
    sheet_kind = {"generated": ("cego", "classificação cega", ""),
                  "degraded": ("fallback", "qualidade do fallback (não entra em quality)", "F")}
    for outcome, by_scenario in pools.items():
        prefix, title, id_mark = sheet_kind[outcome]
        for scenario_id in sorted(by_scenario):
            items = by_scenario[scenario_id]
            rng.shuffle(items)
            numbered = []
            for number, (source, execution) in enumerate(items, start=1):
                item_id = f"{scenario_id}-{id_mark}{number:03d}"
                maps[outcome][item_id] = source
                templates[outcome][item_id] = {"label": None, "justification": "", "annotations": {}}
                numbered.append((item_id, execution))
            (out / f"{prefix}_{scenario_id}.md").write_text(_sheet(scenario_id, title, numbered), encoding="utf-8")

    (out / "labels.json").write_text(json.dumps(templates["generated"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "labels_fallback.json").write_text(json.dumps(templates["degraded"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "README.md").write_text(BLIND_README, encoding="utf-8")
    hidden = out / "mapa_oculto"
    hidden.mkdir()
    (hidden / "map.json").write_text(json.dumps({
        "seed": args.seed, "items": maps["generated"], "fallback_items": maps["degraded"],
        "excluded": excluded, "runs": [str(r) for r in runs],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    write_sha256sums(out)
    print(f"{len(maps['generated'])} itens principais e {len(maps['degraded'])} de fallback em {out}; "
          f"{len(excluded)} execuções sem classificação. Não abra mapa_oculto/ antes de congelar os rótulos.")


LABEL_FILES = ("labels.json", "labels_fallback.json")


def cmd_freeze(args: argparse.Namespace) -> None:
    blind = Path(args.blind).expanduser().resolve()
    frozen = {"frozen_at": now_utc()}
    for name in LABEL_FILES:
        labels = json.loads((blind / name).read_text(encoding="utf-8"))
        problems = [i for i, v in labels.items() if v.get("label") not in LABELS or not str(v.get("justification", "")).strip()]
        if problems:
            raise SystemExit(f"{name}: rótulos incompletos ou inválidos (use C, P ou I com justificativa): {problems}")
        frozen[name] = sha256_file(blind / name)
    (blind / "labels_frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print(json.dumps(frozen))


def cmd_report(args: argparse.Namespace) -> None:
    blind = Path(args.blind).expanduser().resolve()
    frozen_path = blind / "labels_frozen.json"
    if not frozen_path.exists():
        raise SystemExit("Rótulos não congelados. Rode `freeze` antes de revelar o mapa.")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    for name in LABEL_FILES:
        if sha256_file(blind / name) != frozen.get(name):
            raise SystemExit(f"{name} mudou depois de congelado.")
    report = build_report(
        json.loads((blind / "labels.json").read_text(encoding="utf-8")),
        json.loads((blind / "mapa_oculto" / "map.json").read_text(encoding="utf-8")),
        json.loads((blind / "labels_fallback.json").read_text(encoding="utf-8")),
    )
    report["labels_sha256"] = {name: frozen[name] for name in LABEL_FILES}
    (blind / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def build_report(labels: dict, mapping: dict, fallback_labels: dict | None = None) -> dict:
    """Por run e cenário: availability, quality, degradation e, à parte, fallback_quality."""
    fallback_labels = fallback_labels or {}
    table: dict = {}

    def cell(source):
        key = (source["run_id"], source["commit"], source["scenario"])
        return table.setdefault(key, {"executions": 0, "generated": 0, "degraded": 0,
                                      "external_unavailable": 0, "http_error": 0,
                                      "quality": {"C": 0, "P": 0, "I": 0},
                                      "fallback_quality": {"C": 0, "P": 0, "I": 0}})

    for item_id, source in mapping["items"].items():
        entry = cell(source)
        entry["executions"] += 1
        entry["generated"] += 1
        entry["quality"][labels[item_id]["label"]] += 1
    for item_id, source in mapping.get("fallback_items", {}).items():
        entry = cell(source)
        entry["executions"] += 1
        entry["degraded"] += 1
        entry["fallback_quality"][fallback_labels[item_id]["label"]] += 1
    for source in mapping["excluded"]:
        entry = cell(source)
        entry["executions"] += 1
        entry[source["outcome"]] += 1

    rows = []
    for (run_id, commit, scenario), entry in sorted(table.items()):
        executions = entry["executions"]
        rows.append({
            "run_id": run_id, "commit": commit, "scenario": scenario, **entry,
            "availability": round(entry["generated"] / executions, 3) if executions else None,
            "degradation_rate": round(entry["degraded"] / executions, 3) if executions else None,
        })
    return {"rows": rows, "labels": LABELS,
            "notes": "quality conta só execuções generated; fallback_quality conta só execuções degraded e não entra em quality."}


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="gera as execuções com o Ollama real")
    run.add_argument("--out", required=True)
    run.add_argument("--only", help="lista de cenários separada por vírgula (padrão: todos)")
    run.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://localhost:11434"))
    run.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
    run.add_argument("--no-warmup", action="store_true", help="não aquece o modelo antes das execuções")
    run.set_defaults(func=cmd_run)

    blind = sub.add_parser("blind", help="prepara a classificação cega (principal e fallback)")
    blind.add_argument("--runs", nargs="+", required=True)
    blind.add_argument("--out", required=True)
    blind.add_argument("--seed", type=int, required=True)
    blind.set_defaults(func=cmd_blind)

    freeze = sub.add_parser("freeze", help="registra o hash dos rótulos antes da revelação")
    freeze.add_argument("--blind", required=True)
    freeze.set_defaults(func=cmd_freeze)

    report = sub.add_parser("report", help="revela o mapa e calcula as métricas")
    report.add_argument("--blind", required=True)
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
