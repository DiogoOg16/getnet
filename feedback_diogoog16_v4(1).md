# Feedback — Diogo Ogochi
## Repositório: `DiogoOg16/getnet`

> **Nota V4: 4,7/10**
> **Classificação:** Insuficiente
> **Confiança:** Média
>
> Benchmark: **João / Skywalker = 10,0**
>
> Avaliação da branch `main`, commit `1abb2a0` (23/10/2026). Autoria pelos commits (Diogo Klafke Ogochi). Vídeo informado em `video.txt` (Google Drive), não assistido.

## Resumo executivo

Entrega honesta e bem testada para o que se propõe, mas que fica no nível de um **roteador por regras com especialistas determinísticos**.

O ponto forte é o conhecimento: 269 chunks extraídos de páginas reais de ajuda da Getnet, com URL e data de ingestão, recuperados por BM25 com stemming, sinônimos EN→PT e limiares de relevância. Clima (Open-Meteo) e câmbio (PTAX do Banco Central) usam fontes reais e dizem o que são. O README declara as limitações sem exagero.

O teto vem da arquitetura: nenhum LLM decide rota ou tool, não há sequência entre agentes, o Customer Support não usa dados do cliente nos cenários oficiais, e não há memória, autenticação nem HITL além de uma flag.

## Quadro V4

| Critério V4 | Peso | Nota |
|---|---:|---:|
| Business & Challenge Fit | 8% | **6,5** |
| Agentic Reasoning & Orchestration | 15% | **4,5** |
| Context, Knowledge & RAG | 10% | **6,5** |
| Tool & Action Engineering | 10% | **5,5** |
| Security & Identity | 13% | **4,5** |
| Memory, State & Resilience | 8% | **1,0** |
| Human Oversight & Risk Management | 7% | **1,5** |
| Evaluation & Quality Engineering | 14% | **5,5** |
| Observability, Reliability & Cost | 6% | **3,5** |
| Production Engineering | 5% | **6,0** |
| Engineering Judgment | 4% | **7,0** |
| **Nota ponderada** | **100%** | **4,7/10** |

Cálculo com os pesos oficiais da Régua V4 (soma = 100%): 4,725.

## 1. Business & Challenge Fit — 6,5

Requisitos atendidos:

- `POST /chat` com `message` + `user_id` e resposta JSON com agente, motivo da rota, fontes e tool;
- três agentes obrigatórios mais Web Search e escalonamento;
- duas tools de cliente (`lookup_customer`, `lookup_transaction`);
- RAG sobre páginas da Getnet;
- Docker e Compose;
- README com arquitetura, pipeline de RAG, testes e limitações;
- vídeo de walkthrough.

Descontos nos cenários oficiais:

- **cenário 3** ("quando cai o dinheiro de ontem"): vai para o Support, mas responde um texto genérico ("o crédito costuma ocorrer em prazo de dias úteis...") **sem consultar nenhum dado** do `cliente1988`;
- **cenários 5 e 8** (máquina sem internet, transação recusada): são roteados para o Knowledge, não para o Support, então não há diagnóstico do terminal nem consulta à transação;
- respostas em português mesmo para perguntas em inglês (declarado no README).

## 2. Agentic Reasoning & Orchestration — 4,5

Fluxo implementado:

```text
FastAPI /chat
      ↓
RouterAgent (regex sobre texto normalizado, ordem fixa de prioridade)
      ↓
1 de: knowledge | customer_support | web_search | human_escalation | fallback
      ↓
resposta
```

- Router 100% por regras, sem LLM. O candidato justifica: previsível e testável.
- Escalonamento não é um agente: é um dicionário fixo dentro do orquestrador.
- Não há sequência entre agentes, estado compartilhado, loop de tools, replanejamento ou stopping condition.
- O enunciado pede que o Router decida "qual agente (ou sequência de agentes)"; só a primeira parte foi implementada.

Faixa da régua: **routing (4–6)**, no limite inferior por ser exclusivamente lexical.

## 3. Context, Knowledge & RAG — 6,5

Pipeline:

```text
URLs de ajuda da Getnet (site.getnet.com.br, /duvidas, getstore docs)
       ↓
ingest.py: extração por seção, FAQ como 1 chunk por pergunta/resposta
       ↓
getnet_sources.jsonl versionado (269 chunks, source_url, section, ingested_at)
       ↓
BM25 (k1=1,5, b=0,75) + stemming + stopwords + sinônimos EN→PT + boost de título
       ↓
gate: MIN_SCORE=1,7 e MIN_COVERAGE=0,45 → sem resultado = abstenção
       ↓
regra direta | Ollama (qwen2.5:7b) com contexto | resposta extrativa
```

Pontos fortes:

- corpus real e rastreável, com URL e timestamp por chunk;
- relevance gate com abstenção;
- prompt de geração instrui a reconhecer falta de informação, e o log de validação mostra isso acontecendo;
- correção registrada de colisão de stem (`crediário` × `crédito`);
- fallback extrativo quando o LLM não está disponível.

Não sobe mais porque:

- só lexical: sem embeddings, hybrid, RRF ou reranker (declarado);
- `_direct_answer` tem dezenas de respostas escritas no código (erros ADQ, chargeback, limites da Get Conta, status de venda). Parecem transcritas das páginas, mas não passam pelo retrieval e não citam a fonte;
- os limiares foram "calibrados com as perguntas de teste", sem métrica de retrieval (Recall@K, MRR);
- corpus estático, sem rotina de atualização.

## 4. Tool & Action Engineering — 5,5

Pontos positivos:

- `lookup_transaction` só devolve a transação se ela pertencer ao `user_id` da request;
- o LLM nunca escolhe identidade;
- Web Search com **allowlist de domínios** e tratamento de redirect do DuckDuckGo;
- câmbio pela PTAX do BCB com retroação para dia útil;
- clima com geocoding e Open-Meteo;
- timeouts nas chamadas externas e erros convertidos em resposta "indisponível".

Gaps:

- tools escolhidas por palavras-chave, sem function calling e sem schema;
- `tool_used: "settlement_timeline"` no cenário 3 rotula como tool um texto fixo;
- as tools de cliente cobrem só cadastro e transação por ID; não há liquidação, terminal ou recusas.

## 5. Security & Identity — 4,5

Pontos positivos:

- isolamento por dono na consulta de transação;
- CPF ou número de cartão na mensagem desviam para escalonamento;
- allowlist de domínios na busca web;
- superfície de prompt injection pequena (o LLM só gera texto a partir do contexto).

Gaps:

- sem autenticação: o `user_id` vem do body;
- **`main.py` loga a mensagem completa antes do roteamento**, então CPF e número de cartão colados pelo usuário vão para o log em texto puro. O próprio README reconhece que a política de logging precisa ser revista;
- sem mascaramento de PII, sem rate limiting;
- guardrails apenas por regex (declarado).

## 6. Memory, State & Resilience — 1,0

Não há memória. Cada request é independente, sem sessão e sem histórico.

```text
turno 1 → (nada persistido) → turno 2 sem contexto
```

## 7. Human Oversight & Risk Management — 1,5

O escalonamento devolve `handoff_required: true` e uma mensagem fixa. Não há ticket, fila, protocolo ou humano no fluxo. O README declara isso com clareza.

Faixa da régua: **apenas flag/escalation (0–2)**.

## 8. Evaluation & Quality Engineering — 5,5

Software quality:

- **82 funções de teste** em 12 arquivos; o README registra 111 casos passando (com parametrizações) e 1 ignorado por rede;
- LLM substituído por fake em todos os testes (`conftest.py`); testes de rede marcados e desligados por padrão;
- matriz de roteamento com os 10 cenários oficiais, equivalentes em português e falsos positivos (`test_router_scenarios.py`);
- testes de fallback do Knowledge, ferramentas externas, API e integração;
- scripts de validação com **logs de execução real** commitados (`logs/validation_20261021_143155.json`), incluindo resposta real do Open-Meteo e do Ollama.

Não sobe mais porque:

- não há dataset de eval versionado, métrica de routing/retrieval nem juiz (o README lista isso como melhoria futura);
- os testes validam roteamento e estrutura; a qualidade semântica das respostas não é medida;
- sem CI.

## 9. Observability, Reliability & Cost — 3,5

Há:

- logs de request, decisão de rota e resposta;
- `routing_reason`, `tool_used`, `sources` e `source_sections` na resposta JSON;
- `/health`;
- degradação graciosa quando Ollama, clima, câmbio ou busca estão fora.

Faltam `trace_id`, latência por etapa, tokens, logs estruturados em JSON, métricas e alertas (declarado). Os logs registram PII.

## 10. Production Engineering — 6,0

Há:

- Dockerfile e Compose com perfil opcional de Ollama e serviço que baixa o modelo;
- healthcheck no Compose;
- dependências pinadas com versão exata;
- corpus versionado no repositório.

Descontos:

- container roda como root;
- testes copiados para a imagem de produção;
- `ollama/ollama:latest` sem versão;
- sem lockfile com hash e sem CI.

Não executei build nem testes nesta correção (ambiente sem acesso ao PyPI).

## 11. Engineering Judgment — 7,0

Melhor critério da entrega.

- router por regras escolhido conscientemente por previsibilidade, com o custo declarado;
- RAG lexical declarado como lexical, sem chamar de semântico;
- câmbio PTAX com aviso de que não é cotação comercial em tempo real;
- abstenção preferida a resposta inventada;
- seção de limitações completa e honesta.

Desconto: as respostas diretas no código e o texto genérico do cenário 3 resolvem casos por atalho, em vez de pela arquitetura.

## Gates V4

### Critical Security Gate
**Não acionado, com ressalva.**

Sem autenticação, mas a consulta de transação valida o dono. O log de PII em texto puro é um problema de privacidade a corrigir antes de qualquer uso real.

### Challenge Fit Gate
**Não acionado.**

O núcleo foi implementado no próprio código, com fontes oficiais da Getnet.

### Evidence Gate
**Médio.**

Código + 82 testes + logs de execução real commitados. Não executei a suíte nesta correção.

### Semantic Quality Gate
**Não comprovado.**

Não há medição de qualidade das respostas. O log de validação mostra o Ollama respondendo "não há informações suficientes" para "Como funciona o Pix?", uma abstenção honesta, mas que indica cobertura ou recuperação insuficiente num tema central.

## Principais forças

1. Corpus real da Getnet com proveniência por chunk.
2. BM25 bem trabalhado, com relevance gate e abstenção.
3. Fontes reais e honestas para clima e câmbio.
4. Suíte de testes ampla e determinística, com logs de execução real.
5. README transparente sobre o que não foi implementado.

## Principais gaps

1. Orquestração por regex para 1 agente, sem LLM decidindo nada.
2. Customer Support não usa dados do cliente nos cenários oficiais.
3. Sem memória, sem autenticação e HITL apenas como flag.
4. PII registrada em log em texto puro.
5. Sem dataset de eval, métricas de qualidade ou CI.
6. Respostas escritas no código para dezenas de perguntas.

## Comparação com João

### Semelhante
- nada material.

### João é superior em
- todos os critérios técnicos: supervisor com especialistas como tools, RAG mais completo, autenticação, memória, HITL via Telegram, evals e observabilidade.

### Diogo é superior em
- nada material. A honestidade da documentação é um ponto positivo de postura, não de capacidade.

```text
Diogo
regex → 1 agente determinístico → (Ollama opcional | texto extrativo | resposta fixa)

João
Supervisor → especialistas como tools → observa → decide → humano → retoma
```

## Perguntas de entrevista

1. O cenário "quando cai o dinheiro de ontem" não consulta nenhum dado do cliente. Que tool você criaria e como o Support decidiria chamá-la?
2. "Transação recusada" vai para o Knowledge. Por que não para o Support, que tem acesso às transações?
3. O enunciado fala em "sequência de agentes". Como você faria Support e Knowledge colaborarem na mesma resposta?
4. Seu log grava a mensagem crua antes do guardrail. O que acontece com um CPF colado pelo cliente, e como corrigiria?
5. Como você mediria se o BM25 está recuperando bem? Que dataset e que métrica usaria antes de trocar por embeddings?

## Veredito

# **4,7/10 — Insuficiente**

Bom fundamento de engenharia de dados e honestidade técnica, mas a profundidade agentic, o uso de dados do cliente, a memória, a segurança e o HITL estão muito abaixo do padrão do conjunto.

Recomendação: não avançar para a vaga AI Hardcore. Se houver posição júnior ou de dados, as perguntas 1 e 5 mostram se ele consegue evoluir a arquitetura.

## Ranking V4

**Nota: 4,7/10 — 28º lugar.**

Abaixo de Paulo Arthur (5,4) e acima de Arthur Di Lorenzo (3,9).
