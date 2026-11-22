# Camada 2 — evidência versionada

Respostas reais do modelo (`qwen2.5:7b`, Ollama) para os cenários oficiais, rotuladas às cegas por humano como Correta (C), Parcial (P) ou Incorreta (I) segundo `eval/official_scenarios_rubrics.md`. Os números citados no README principal saem destes arquivos.

| Rodada | Commit avaliado | Escopo | C / P / I (10 oficiais, sem S05-V) |
|---|---|---|---|
| `2026-11-08_939d2ba` | `939d2ba` | 10 cenários + S05-V | 32 / 48 / 6 |
| `2026-11-15_df1ddbb` | `df1ddbb` | 10 cenários + S05-V | 47 / 27 / 12 |
| `2026-11-17_877163b_S06` | `877163b` | só S06 (depois do H1b) | 5 / 2 / 3 |

`df1ddbb` com o S06 revisado pela rubrica literal: 47 / 35 / 4 (decisões em `2026-11-15_df1ddbb/revisao_S06_decisoes.json`; os rótulos originais não foram alterados). Combinação `df1ddbb` + S06 de `877163b`: 50 / 29 / 7, que mistura duas rodadas (ver `2026-11-17_877163b_S06/comparacao.md`).

## Arquivos de cada rodada

| Arquivo | Conteúdo |
|---|---|
| `manifest.json` | commit, hash dos critérios e do corpus, modelo e digest, versões, número de execuções |
| `executions.jsonl` | uma linha por execução: mensagens, status HTTP, latência e resposta completa da API |
| `map.json` | liga cada item da folha cega à execução correspondente (semente do embaralhamento) |
| `labels.json`, `labels_fallback.json` | rótulos humanos por item cego (respostas geradas e respostas de fallback) |
| `labels_frozen.json` | registro do congelamento: data e hashes dos rótulos, feito antes de revelar o mapa |
| `report.json` | totais por cenário e hashes dos rótulos usados |

`index.json` lista o SHA-256 de cada arquivo. As cópias são idênticas aos originais, exceto `map.json`, em que caminhos absolutos da máquina local foram trocados por relativos (o hash original também está no índice). As folhas cegas em Markdown e os arquivos intermediários de revisão não foram copiados.

`tests/test_layer2_evidence.py` recalcula os totais acima a partir de `report.json` e confere os hashes dos rótulos com o relatório e com o registro de congelamento.

## Limitações

- A versão entregue (`634a0c8`) não passou por uma nova rodada: as mudanças depois de `df1ddbb` (respostas fixas, roteamento, Knowledge só pelo resultado da ferramenta) foram verificadas só pela camada 1.
- Um único avaliador humano; não há medida de concordância entre avaliadores.
- Gerar o relatório de novo a partir destas cópias (`run_official_scenarios.py report`) não foi testado; os totais são verificados pelo teste acima.
