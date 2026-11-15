# Getnet AI Support System

Assistente de suporte multiagente desenvolvido como desafio técnico. A aplicação recebe mensagens por uma API HTTP, identifica a intenção e encaminha a solicitação para um agente especializado: conhecimento da Getnet, suporte a cliente/transação, busca externa ou escalonamento humano.

> **Escopo do protótipo:** dados de clientes e transações são simulados. O sistema não está conectado aos sistemas internos da Getnet e não deve ser usado para decisões operacionais reais.

> **Summary (English):** multi-agent support API (FastAPI) for the Getnet challenge. A rule-based Router builds a bounded plan and dispatches to a Knowledge Agent (BM25 RAG over an ingested Getnet corpus, optional Ollama generation), a Customer Support Agent (Ollama function calling over customer/transaction/settlement tools, with backend validation), a Web Search agent (weather, exchange rate, allow-listed search) and a human escalation flow with persisted tickets. Bearer-token identity is enforced per request; personal data (CPF, CNPJ, card numbers, e-mail, phone) is regex-masked before it reaches agents, the LLM, external search or storage. Tests: deterministic pytest suite plus a human-labelled evaluation of the 10 official scenarios. Known limitations are listed at the end, including the scenarios still marked `xfail`.

## Índice

- [Checklist de compliance do desafio](#checklist-de-compliance-do-desafio)
- [Principais funcionalidades](#principais-funcionalidades)
- [Arquitetura e fluxo da mensagem](#arquitetura-e-fluxo-da-mensagem)
- [Function Calling no Customer Support (Incremento 5B)](#function-calling-no-customer-support-incremento-5b)
- [Pipeline de RAG](#pipeline-de-rag)
- [Requisitos](#requisitos)
- [Execução local](#execução-local)
- [Execução com Docker](#execução-com-docker)
- [API HTTP](#api-http)
- [Memória de sessão](#memória-de-sessão)
- [Segurança e privacidade](#segurança-e-privacidade)
- [Testes e avaliação](#testes-e-avaliação)
- [Reprodução da validação final](#reprodução-da-validação-final)
- [Observabilidade](#observabilidade)
- [Limitações conhecidas](#limitações-conhecidas)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Melhorias futuras](#melhorias-futuras)

## Checklist de compliance do desafio

| Requisito do desafio | Implementação (código) | Evidência de testes |
|---|---|---|
| Router e fluxo multiagente | `app/orchestrator.py`, `app/agents/router.py` | `tests/test_router.py`, `tests/test_router_scenarios.py`, `tests/test_orchestrator.py`, `tests/test_conditional_plan.py` |
| Knowledge Agent com RAG + busca web | `app/agents/knowledge.py`, `app/rag/retriever.py`, `app/agents/web_search.py` | `tests/test_knowledge.py`, `tests/test_knowledge_fallback.py`, `tests/test_web_search.py` |
| Customer Support com 2+ tools | `app/tools/customer_tools.py`, `app/tools/registry.py`, `app/agents/customer_support.py` | `tests/test_customer_support.py`, `tests/test_tool_registry.py` |
| Endpoint `POST /chat` com JSON significativo | `app/main.py` | `tests/test_api.py`, `tests/acceptance/test_resolution_contract.py` |
| Persistência de sessão e handoff | `app/session_memory.py`, `app/human_handoff.py` | `tests/test_api.py`, `tests/test_attendant_flow.py`, `tests/test_handoff_completion.py`, `tests/test_conversation_isolation.py` |
| Autenticação e identidade | `app/auth.py`, `app/main.py` | `tests/test_api.py`, `tests/test_attendant_flow.py`, `tests/test_scripts_auth.py` |
| Guardrails e privacidade (bônus) | `app/agents/router.py`, `app/privacy.py`, `app/orchestrator.py` | `tests/test_privacy.py`, `tests/test_privacy_agents.py`, `tests/test_router_escalation.py` |
| Agente de escalonamento humano (bônus) | `app/human_handoff.py`, endpoints `/human-handoff` em `app/main.py` | `tests/test_attendant_flow.py`, `tests/test_active_handoff_interception.py` |
| Avaliação dos cenários do desafio (bônus) | `eval/official_scenarios.json`, `eval/official_scenarios_rubrics.md`, `eval/run_official_scenarios.py` | `tests/test_official_scenarios.py` (camada 1); camada 2 com rótulo humano (ver [Estratégia de avaliação](#estratégia-de-avaliação)) |
| Dockerização para execução padrão | `Dockerfile`, `docker-compose.yml` | validação manual documentada em "Reprodução da validação final" |
| Testes automatizados e estratégia | `tests/` + seção de estratégia | `python -m pytest -q` (suíte padrão) + testes reais opt-in (`RUN_OLLAMA_INTEGRATION=1`) |
| CI em push/PR para `main` e `feat/**` | `.github/workflows/ci.yml` | [Execuções do workflow CI no GitHub Actions](https://github.com/DiogoOg16/getnet/actions/workflows/ci.yml) |

Observação: os testes de integração real com Ollama permanecem opt-in por variável de ambiente e não fazem parte da suíte padrão do CI.

## Principais funcionalidades

- **Roteamento por intenção:** regras explícitas e normalização de texto para direcionar cada mensagem.
- **Conhecimento da Getnet:** recuperação de trechos de uma base documental local e geração opcional com Ollama.
- **Suporte ao cliente:** ferramentas para consultar dados simulados de clientes e transações.
- **Busca externa:** consultas de clima, câmbio e busca geral na web, com validação de domínios permitidos.
- **Guardrails e escalonamento:** pedidos sensíveis (incluindo CPF ou número de cartão colado na mensagem), solicitações explícitas de atendimento humano e casos que exigem continuidade manual são encaminhados para o escalonamento, que cria um ticket persistido.
- **Privacidade:** dados pessoais são mascarados por padrões antes de chegar aos agentes, ao LLM, à busca externa, aos tickets e à memória (ver [Segurança e privacidade](#segurança-e-privacidade)).
- **Fallback sem LLM:** o serviço pode funcionar sem Ollama, usando respostas extraídas dos documentos recuperados.
- **Metadados de execução:** a API informa o agente escolhido, motivo do roteamento, fontes, ferramenta usada, necessidade de handoff, fatos verificados e um `trace` por etapa com duração.

## Arquitetura e fluxo da mensagem

```text
Cliente
  |
  v
FastAPI (/chat) -- autenticação Bearer, user_id == token, memória de sessão
  |
  v
ChatOrchestrator -- Router Agent (texto original) monta um plano de até 3 etapas
  |                 agentes recebem a mensagem já mascarada
  |
  +--> Knowledge Agent ------> Retriever local ------> Ollama (opcional)
  |
  +--> Customer Support -----> Ferramentas de cliente/transação simuladas
  |
  +--> Web Search -----------> Clima / câmbio / busca web
  |
  +--> Human Escalation -----> Ticket persistido (pending -> assigned -> completed)
  |
  v
Resposta JSON + metadados + trace por etapa
```

### Agentes

| Componente | Responsabilidade |
|---|---|
| `RouterAgent` | Normaliza a mensagem e classifica a intenção por regras explícitas. |
| `KnowledgeAgent` | Recupera informações da base local, aplica respostas diretas em casos específicos e pode consultar o Ollama. |
| `CustomerSupportAgent` | Atende solicitações sobre clientes e transações usando ferramentas com dados simulados. |
| `WebSearchAgent` | Trata perguntas de clima, câmbio e pesquisa externa. |
| Human escalation | Encaminha solicitações sensíveis ou que exigem atendimento humano. É representado pelo fluxo de escalonamento no orquestrador. |
| `ChatOrchestrator` | Monta um plano limitado (`ExecutionPlan`, máximo de 3 etapas) a partir da decisão do roteador, executa as etapas em sequência, compartilha fatos verificados entre elas, detecta conflitos de fatos, acrescenta uma etapa durante a execução quando o resultado verificado de uma ferramenta pede (ver abaixo), registra um `trace` por etapa e padroniza a resposta. |

O roteador é baseado em regras, não em uma chamada de LLM. Isso torna a decisão principal previsível e testável, embora regras lexicais possam não reconhecer todas as formas possíveis de uma intenção.

**Colaboração entre agentes (o que existe e o que falta):** o plano encadeia agentes de duas formas.

- **Pelo texto, na criação do plano:** quando a mesma mensagem menciona uma transação recusada e pede orientação ("por que", "o que fazer"), o Customer Support consulta os dados e o Knowledge acrescenta a orientação documentada, recebendo os fatos verificados da etapa anterior.
- **Pelo resultado da ferramenta, durante a execução (ARCH-02):** depois de cada etapa, o orquestrador olha o resultado verificado de `lookup_transaction`. Transação aprovada ou pendente, negada com motivo registrado, não encontrada ou erro de ferramenta: nenhuma etapa nova. Transação **negada sem motivo registrado**: o orquestrador acrescenta o Knowledge com uma consulta fixa sobre o significado de uma venda negada com cartão, **sem** os fatos da transação, para que a explicação geral não seja apresentada como causa daquela transação. É o que acontece no cenário oficial S08, em que a recusa e o identificador chegam em turnos separados.

O plano tem no máximo 3 etapas e não repete agente. Em execução multi-etapa, `agent` e `tool_used` representam a etapa principal (a primeira) e o `trace` registra todos os agentes, ferramentas e o motivo de cada etapa acrescentada. As respostas são combinadas em partes com cabeçalho (fato verificado; depois a explicação geral, identificada como tal), não sintetizadas por um LLM.

### Fluxo de uma requisição

1. A API autentica o token Bearer e exige que o `user_id` do payload seja o do token (`403` caso contrário).
2. Se a sessão tem um atendimento humano ativo e a mensagem pergunta por ele, a API devolve o estado do ticket.
3. A memória de sessão fornece contexto recente e resolve referências curtas ("e essa?").
4. O roteador analisa o texto original (necessário para detectar CPF ou cartão) e o orquestrador monta o plano.
5. Cada agente do plano recebe a mensagem já mascarada e, quando aplicável, consulta ferramentas, documentos ou o LLM.
6. Se houver escalonamento, a API cria (ou reaproveita) um ticket de handoff com a mensagem mascarada.
7. O turno é gravado na memória, mascarado, e a API devolve a resposta JSON com metadados e `trace`.

## Function Calling no Customer Support (Incremento 5B)

O fluxo operacional do Customer Support usa Function Calling com validação backend antes de qualquer execução de ferramenta.

### Fluxo completo

1. `CustomerSupportAgent` identifica a operação e define a lista de tools permitidos (`allowed_tools`).
2. `OllamaTools` converte os schemas do `ToolRegistry` para o formato de tools aceito pelo Ollama.
3. `OllamaClient` envia mensagens e tools para o modelo (`/api/chat`).
4. `OllamaFunctionCallingLoop` interpreta os `tool_calls` solicitados pelo modelo.
5. `ToolExecutor` valida argumentos públicos, contexto confiável e autorização antes de executar o handler.
6. O resultado da ferramenta volta ao modelo como mensagem com role `tool`.
7. O loop continua até uma resposta final sem novas tools ou até atingir o limite de iterações.

### Contratos de segurança e inicialização

- As ferramentas de suporte são inicializadas explicitamente com `register_customer_tools` no bootstrap da API.
- A API, o Orchestrator, o CustomerSupportAgent e o ToolExecutor compartilham a mesma instância de `ToolRegistry`.
- A identidade do usuário vem do backend autenticado e é injetada como contexto confiável; o modelo não envia `user_id` como argumento público.
- O backend restringe quais ferramentas podem ser executadas por operação, enviando apenas as autorizadas naquele passo.

### Componentes principais

- Registro e execução: `app/tools/registry.py` e `app/tools/customer_tools.py`
- Conversão de schema para tools do Ollama: `app/llm/ollama_tools.py`
- Loop de Function Calling: `app/llm/ollama_function_calling.py`
- Cliente de chat com Ollama: `app/llm/ollama_client.py`
- Integração no suporte: `app/agents/customer_support.py`
- Bootstrap explícito: `app/main.py`

## Pipeline de RAG

O agente de conhecimento utiliza recuperação lexical; **não há embeddings nem banco vetorial implementados**.

1. **Ingestão:** `app/rag/ingest.py` reúne páginas públicas de ajuda e documentação da Getnet (as fontes estão listadas no próprio arquivo), extrai o conteúdo e prepara os registros. Para regenerar a base: `python -m app.rag.ingest`. O comando acessa a internet e **sobrescreve** `app/rag/documents/getnet_sources.jsonl` (se alguma fonte falhar, a base existente é preservada). Como os cenários oficiais e o fixture de ranking fixam hashes do conteúdo e posições dos documentos, uma nova ingestão pode invalidar esses testes; regenere a base só de forma deliberada.
2. **Armazenamento:** os documentos ficam versionados em `app/rag/documents/getnet_sources.jsonl`. A base representa um retrato da data da ingestão e pode ficar desatualizada.
3. **Recuperação:** `app/rag/retriever.py` normaliza os termos da consulta e usa BM25, com ajustes lexicais e critérios mínimos de relevância, para selecionar trechos.
4. **Resposta:** `app/agents/knowledge.py` pode responder diretamente em casos específicos, enviar o contexto recuperado ao Ollama ou usar um fallback extrativo se o modelo estiver indisponível.

O prompt usado com o Ollama orienta o modelo a responder com base no contexto recuperado e a reconhecer quando as informações disponíveis não são suficientes. Isso reduz, mas não elimina, o risco de respostas incorretas.

### Comportamento do agente de conhecimento

- `tool_used: "ollama"`: o modelo local foi chamado.
- `tool_used: "retrieval_only"`: resposta sem geração pelo LLM.
- Respostas diretas por regras podem ser produzidas para perguntas específicas cobertas pela implementação.

O modelo padrão é `qwen2.5:7b`. O uso do Ollama é opcional.

## Requisitos

- Python 3.11 ou mais recente (obrigatório: os padrões de mascaramento em `app/privacy.py` usam quantificadores possessivos, que não existem no 3.10). A imagem Docker e o CI usam 3.11.
- `pip` e ambiente virtual Python.
- Docker Engine e Docker Compose v2, se preferir executar em containers.
- Ollama e o modelo configurado, somente se quiser usar geração por LLM.

## Execução local

Execute os comandos a partir da raiz do repositório, onde estão `requirements.txt` e `app/`.

### 1. Preparar variáveis de ambiente

```bash
cp -n .env.example .env
```

### 2. Criar e instalar o ambiente

```bash
python3.11 -m venv .venv
source .venv/bin/activate
set -a
source .env
set +a
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Iniciar a API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

A API ficará disponível em `http://127.0.0.1:8000`. A documentação interativa do FastAPI fica em `http://127.0.0.1:8000/docs`.

### 4. Verificar a aplicação

Em outro terminal:

```bash
curl -s http://127.0.0.1:8000/health
```

Resposta esperada:

```json
{"status":"ok"}
```

Para encerrar a API iniciada no terminal, pressione `Ctrl+C`.

## Execução com Docker

O arquivo de Compose do projeto é `docker-compose.yml`.

### API sem LLM

Antes de iniciar com Docker Compose, crie o arquivo `.env` a partir do modelo `.env.example`, que já inclui a configuração inicial de demonstração:

```bash
cp .env.example .env
```

```bash
docker compose up --build -d
docker compose ps
curl -s http://localhost:8000/health
```

Nesse modo, a API sobe sem iniciar um serviço Ollama próprio. Se não houver Ollama acessível na URL configurada, o agente de conhecimento usa seu fallback.

Observações:

- **Atualizações de código:** use sempre `--build` depois de mudar o código (`docker compose up --build -d`). Sem isso, o Compose reaproveita a imagem antiga e o container continua executando a versão anterior.
- **Dados persistidos:** tickets e memória de sessão ficam em `/app/data`, no volume `api_data` (no projeto padrão, `getnet_api_data`). Eles sobrevivem a `restart` e a `down`; só são apagados com `docker compose down -v`.
- **Uma instância por vez:** o `docker-compose.yml` fixa `container_name: getnet-ai-agent` e a porta `8000`. Para subir uma segunda instância em paralelo, use outro nome de projeto (`-p`) e um arquivo de override que troque o nome do container e a porta.

Para acompanhar os logs:

```bash
docker compose logs -f api
```

Para parar os serviços:

```bash
docker compose down
```

### API com Ollama no Compose

```bash
docker compose --profile llm up --build -d
docker compose ps
docker compose logs -f api
```

O perfil `llm` inicia a API, o serviço Ollama e o serviço que baixa o modelo configurado. O primeiro download do modelo pode demorar e exige acesso à internet, além de espaço em disco e memória suficientes.

Para parar os serviços:

```bash
docker compose --profile llm down
```

### Usar um Ollama que já esteja rodando no host

Se o Ollama estiver instalado e rodando no host, configure a URL antes de subir a API:

```bash
OLLAMA_URL=http://host.docker.internal:11434 docker compose up --build -d
```

Esse endereço é configurado para o cenário Docker previsto no `docker-compose.yml`. Em execução local fora do Docker, o padrão do código é `http://localhost:11434`.

### Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` no processo local; o Compose define `http://ollama:11434` como padrão do serviço | Endereço base do Ollama. |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Nome do modelo usado para geração. |
| `OLLAMA_TIMEOUT_SECONDS` | `60` | Tempo máximo de cada chamada ao Ollama. Valor inválido (não numérico, zero ou negativo) volta a 60 s, com aviso no log. Nas avaliações com `qwen2.5:7b` em CPU, a geração levou até cerca de 51 s. |
| `GETNET_DEMO_AUTH_TOKENS` | sem padrão; obrigatória | JSON que mapeia cada token Bearer a um `user_id`. O `.env.example` traz tokens fictícios para `cliente1988`, `cliente2001` e `atendente_01`, só para desenvolvimento. |
| `GETNET_SESSION_MEMORY_PATH` | `<tmp>/getnet_session_memory.json` no processo local; `/app/data/getnet_session_memory.json` no Compose | Arquivo JSON da memória de sessão. |
| `GETNET_HUMAN_HANDOFF_PATH` | `<tmp>/getnet_human_handoff.json` no processo local; `/app/data/getnet_human_handoff.json` no Compose | Arquivo JSON dos tickets de handoff. |

Exemplo para execução local:

```bash
export OLLAMA_URL=http://localhost:11434
export OLLAMA_MODEL=qwen2.5:7b
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## API HTTP

### `GET /health`

Verifica se a API está respondendo.

```bash
curl -s http://127.0.0.1:8000/health
```

### `POST /chat`

Recebe uma mensagem e o identificador do usuário.

O enunciado do desafio define `message` e `user_id` no corpo da requisição. Nesta implementação, o endpoint também exige autenticação Bearer. A identidade autenticada pelo token é validada contra o `user_id` enviado no payload para impedir acesso cruzado entre clientes.

Exemplo de requisição:

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Authorization: Bearer demo-token-cliente1988' \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Qual o status da transação txn1001?",
    "user_id": "cliente1988"
  }'
```

A resposta inclui os campos abaixo (o conteúdo exato depende da rota e dos dados disponíveis):

```json
{
  "user_id": "cliente1988",
  "message": "Qual o status da transação txn1001?",
  "response": "Resposta produzida pelo agente selecionado",
  "agent": "customer_support",
  "routing_reason": "The message references a specific transaction ID.",
  "sources": [],
  "source_sections": {},
  "tool_used": "lookup_transaction",
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": true,
  "resolved": true,
  "handoff_required": false,
  "awaiting_user_input": false,
  "step_status": "success",
  "handoff": null,
  "request_id": "9f2c…",
  "total_latency_ms": 12,
  "verified_facts": [
    {"entity": "txn1001", "name": "status", "value": "approved", "verified": true}
  ],
  "fact_conflicts": [],
  "trace": [
    {"agent": "customer_support", "reason": "The message references a specific transaction ID.", "status": "success", "tool_used": "lookup_transaction", "request_id": "9f2c…", "duration_ms": 11}
  ]
}
```

O exemplo ilustra o contrato da resposta; a mensagem, o status da transação e outros valores dependem dos dados simulados disponíveis na versão executada. O campo `message` devolve a pergunta com os dados pessoais mascarados (ver [Segurança e privacidade](#segurança-e-privacidade)).

### Endpoints de handoff humano

- `GET /human-handoff`: lista tickets visíveis para o usuário autenticado.
- `GET /human-handoff/{ticket_id}`: consulta um ticket específico.
- `POST /human-handoff/{ticket_id}/assume`: um atendente assume o ticket.
- `POST /human-handoff/{ticket_id}/complete`: um atendente conclui o ticket.

Os endpoints exigem autenticação Bearer. Usuários cliente só podem acessar tickets próprios; atendentes podem operar tickets conforme as regras de transição implementadas.

#### Fluxo do atendente

Um `user_id` que começa com `atendente_` é tratado como atendente. Só atendentes podem assumir e concluir tickets, e cada atendente só pode assumir um ticket para si mesmo. **Só o atendente que assumiu o ticket pode concluí-lo:** a regra é verificada no armazenamento (`HumanHandoffStore.complete`), não só na rota, e uma tentativa negada não altera o ticket. As transições permitidas são `pending` → `assigned` → `completed`: concluir um ticket que ainda não foi assumido devolve `400`. A mensagem e a resolução do ticket são gravadas com os dados pessoais mascarados.

> **Só para desenvolvimento:** o token `demo-token-atendente_01` do `.env.example` é público e fictício. Substitua todos os tokens antes de usar o projeto em qualquer ambiente real. Se o seu `.env` foi criado antes dessa credencial existir, acrescente o par `"demo-token-atendente_01":"atendente_01"` ao JSON de `GETNET_DEMO_AUTH_TOKENS` e reinicie a API.

1. Abrir um ticket como cliente. O campo `handoff.id` da resposta é o identificador do ticket:

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Authorization: Bearer demo-token-cliente1988' \
  -H 'Content-Type: application/json' \
  -d '{"message":"Preciso falar com um humano sobre dados sensíveis do meu cadastro.","user_id":"cliente1988"}'
```

2. Consultar o ticket como atendente. O `status` deve ser `pending`:

```bash
TICKET_ID=<valor de handoff.id>

curl -s http://127.0.0.1:8000/human-handoff/$TICKET_ID \
  -H 'Authorization: Bearer demo-token-atendente_01'
```

3. Assumir o ticket. O campo `assignee` precisa ser o próprio atendente autenticado:

```bash
curl -s -X POST http://127.0.0.1:8000/human-handoff/$TICKET_ID/assume \
  -H 'Authorization: Bearer demo-token-atendente_01' \
  -H 'Content-Type: application/json' \
  -d '{"assignee":"atendente_01"}'
```

4. Confirmar a atribuição: o ticket deve ter `status` igual a `assigned` e `assignee` igual a `atendente_01`:

```bash
curl -s http://127.0.0.1:8000/human-handoff/$TICKET_ID \
  -H 'Authorization: Bearer demo-token-atendente_01'
```

5. Concluir o ticket. O campo `resolution` não pode ser vazio:

```bash
curl -s -X POST http://127.0.0.1:8000/human-handoff/$TICKET_ID/complete \
  -H 'Authorization: Bearer demo-token-atendente_01' \
  -H 'Content-Type: application/json' \
  -d '{"resolution":"Cadastro revisado com o cliente."}'
```

6. Confirmar o estado final: `status` igual a `completed`, com a `resolution` registrada. O cliente dono do ticket também pode consultá-lo com o próprio token:

```bash
curl -s http://127.0.0.1:8000/human-handoff/$TICKET_ID \
  -H 'Authorization: Bearer demo-token-cliente1988'
```

Respostas de erro esperadas:

| Situação | Código |
|---|---|
| Sem token ou com token inválido | `401` |
| Cliente tenta assumir ou concluir um ticket | `403` |
| Atendente tenta assumir um ticket em nome de outro (`assignee` diferente do próprio `user_id`) | `403` |
| Atendente tenta concluir um ticket assumido por outro atendente | `403` |
| Cliente consulta um ticket de outro cliente | `403` |
| Ticket inexistente na consulta | `404` |
| Concluir antes de assumir, assumir de novo, `assignee` ausente ou `resolution` vazia | `400` |

### Exemplos adicionais

**Pergunta sobre conhecimento local:**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Authorization: Bearer demo-token-cliente1988' \
  -H 'Content-Type: application/json' \
  -d '{"message":"Como funciona o Pix?","user_id":"cliente1988"}'
```

**Previsão do tempo:**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Authorization: Bearer demo-token-cliente1988' \
  -H 'Content-Type: application/json' \
  -d '{"message":"Qual é a previsão do tempo em Porto Alegre amanhã?","user_id":"cliente1988"}'
```

**Pedido de atendimento humano:**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Authorization: Bearer demo-token-cliente1988' \
  -H 'Content-Type: application/json' \
  -d '{"message":"Preciso falar com um humano sobre dados sensíveis do meu cadastro.","user_id":"cliente1988"}'
```

No caso de escalonamento, espera-se que `agent` seja `human_escalation`, `handoff_required` seja `true` e `handoff` traga o ticket criado (`status: pending`). O ticket é persistido em arquivo JSON e operado pelos endpoints de handoff acima; não há integração com uma fila ou plataforma real de atendimento.

## Memória de sessão

A API usa memória de sessão para complementar contexto recente de conversa e resolver referências curtas.

- Chave de sessão: combinação de `user_id` autenticado com `session_id` (ou o próprio `user_id` quando `session_id` não é enviado).
- Armazenamento: arquivo JSON local (`/tmp/getnet_session_memory.json` por padrão) ou caminho configurado em `GETNET_SESSION_MEMORY_PATH`.
- Isolamento: cada chave `user_id:session_id` mantém seu próprio histórico, sem mistura entre usuários/sessões diferentes.
- Limites atuais:
  - máximo de 20 entradas por sessão;
  - poda por idade com janela padrão de 7 dias;
  - persistência em arquivo JSON no filesystem da aplicação (em Docker, depende de volumes; sem um volume persistente, os dados podem ser perdidos ao recriar o contêiner).

Limitações conhecidas da memória:

- não há política avançada de expiração por tenant;
- não há criptografia dedicada para o arquivo de memória local;
- não há rotina automática de governança além dos limites de tamanho e idade configurados na aplicação;
- a resolução de referências curtas reconhece uma lista fixa de expressões ("essa", "isso", "e essa"...), e a lembrança de nome usa padrões de texto.

## Segurança e privacidade

### Identidade

- `POST /chat` e os endpoints `/human-handoff` exigem token Bearer (`/health` e a documentação do FastAPI são públicos). Os tokens vêm de `GETNET_DEMO_AUTH_TOKENS` e são comparados em tempo constante.
- Em `POST /chat`, o `user_id` do payload precisa ser o do token; caso contrário, `403`. As ferramentas recebem o `user_id` autenticado como contexto confiável, nunca do modelo, e `lookup_transaction` só devolve transações do próprio cliente.
- Os tokens são estáticos e sem expiração: adequados para demonstração, não para produção.

### Mascaramento de dados pessoais

`app/privacy.py` concentra a detecção e o mascaramento. Os padrões cobertos e os marcadores usados:

| Dado | Formatos detectados | Marcador |
|---|---|---|
| CPF | 11 dígitos, com ou sem ponto, espaço ou hífen | `[CPF]` |
| CNPJ | 14 dígitos, com ou sem pontuação | `[CNPJ]` |
| Cartão | 13 a 19 dígitos sem separador; grupos 4-4-4-4 (+1 a 3) e 4-6-5/4-6-4 com espaço, ponto ou hífen; e, logo depois de uma palavra de cartão ("cartão", "crédito", "visa"...), outros agrupamentos de 3 a 6 dígitos com 13 a 19 dígitos no total | `[CARTAO]` |
| E-mail | endereço com domínio | `[EMAIL]` |
| Telefone | com `+55`, com DDD entre parênteses, ou logo depois de uma palavra de contexto ("telefone", "celular", "whatsapp", "ligue", "meu número"...) | `[TELEFONE]` |

Onde o mascaramento é aplicado:

- **Antes dos agentes:** o roteador lê o texto original, porque precisa dele para detectar CPF ou cartão; depois do roteamento, todos os agentes (e, por meio deles, o LLM, as ferramentas e a busca externa) recebem a versão mascarada.
- **Na persistência:** mensagem, resposta e follow-up pendente na memória de sessão; mensagem e resolução dos tickets.
- **Na busca externa:** a consulta enviada ao provedor.
- **Na resposta HTTP:** o campo `message` devolve a pergunta mascarada.

O que **não** é mascarado: documentos da base de conhecimento (os contatos oficiais da Getnet, como e-mails e telefones de atendimento, continuam disponíveis para o modelo) e resultados das ferramentas. Os logs da aplicação não registram o conteúdo das mensagens, só identificadores, agente, status e latência.

**Guardrail:** CPF ou número de cartão na mensagem leva ao escalonamento humano, com o ticket gravado já mascarado.

**Limitações (o mascaramento é uma proteção adicional, não anonimização):**

- A detecção é por expressões regulares e não garante encontrar todo dado pessoal. Não há validação de dígito verificador (Luhn, CPF).
- Telefone sem palavra de contexto (ex.: `98765-4321` sozinho) e cartão em agrupamento incomum sem palavra de cartão por perto não são detectados.
- Onze dígitos sem pontuação são marcados como `[CPF]` mesmo quando são um celular com DDD, e outros números longos (ex.: protocolos) podem ser marcados como cartão ou CNPJ.
- Nome, RG, CEP, endereço e conta bancária estão fora do escopo.
- O texto original existe na memória do processo durante o roteamento.
- Arquivos JSON gravados por versões anteriores não são saneados automaticamente.
- Os arquivos de memória e de tickets não são criptografados.

## Testes e avaliação

### Executar os testes automatizados

Com o ambiente virtual ativado:

```bash
python -m pytest -v
```

Ou, em formato compacto:

```bash
python -m pytest -q
```

A suíte cobre API, roteamento, agentes, ferramentas, fallback de conhecimento, integração e escalonamento. Os testes automatizados simulam o LLM e as dependências de rede para manter a execução previsível.

### Testes padrão (sem Ollama real)

Esses testes rodam sem depender de Ollama real ou serviços externos opcionais:

```bash
python -m pytest -q
```

Comportamento da suíte padrão:

- `tests/conftest.py` substitui `KnowledgeAgent._generate` e o cliente Ollama do Customer Support por versões simuladas;
- `tests/conftest.py` aponta `GETNET_SESSION_MEMORY_PATH` e `GETNET_HUMAN_HANDOFF_PATH` para uma pasta temporária antes de importar a aplicação: a suíte não lê, não apaga e não sobrescreve os arquivos de uma API rodando localmente;
- testes marcados com `network` são pulados quando `RUN_NETWORK_TESTS` não é `1`.

#### Como ler o resultado

Com os critérios v1.3, a suíte padrão dá `756 passed, 5 skipped, 5 xfailed`.

- **`skipped` (5):** testes opt-in que dependem de rede ou do Ollama real (`RUN_NETWORK_TESTS=1`, `RUN_OLLAMA_INTEGRATION=1`).
- **`xfailed` (5):** requisitos dos cenários oficiais que o sistema ainda **não** cumpre, marcados com `xfail(strict=True)` e o item de backlog correspondente. São limitações conhecidas, não testes desligados:

| Requisito | Backlog | Defeito |
|---|---|---|
| S02-R3 | REL-05 | Com a API de clima indisponível, a resposta não inventa valores, mas o `step_status` volta `success` em vez de `failed`. |
| S04-R2 | RAG-07a | O documento do Pix no Get Tap fica em 6º lugar e não entra no contexto (`limit=3`). |
| S06-R3 | RAG-07b | O documento sobre antecipação não entra no top 3. |
| S09-R3 | RAG-07c | O documento que diz que o limite de parcelas depende do emissor não entra no top 3. |
| S05V-R2 | RAG-01 | No modo filtrado de conectividade, o IDF usa a contagem do corpus inteiro. |

Com `strict=True`, se um desses defeitos for corrigido o teste vira `XPASS` e a suíte falha de propósito, para que o critério seja atualizado conscientemente. Foi o que aconteceu com S08-R4 (ARCH-02): a correção do planejamento condicional o fez passar, e a versão 1.3 de `eval/official_scenarios.json` o moveu de `xfail` para `pass`, com o motivo registrado no histórico do arquivo.

### Testes de integração reais com Ollama

Esses testes exercitam integração real com modelo local e dependem de variáveis de ambiente explícitas.

Pré-requisitos:

- Ollama local disponível;
- modelo configurado (padrão `qwen2.5:7b`);
- rede habilitada para testes `network`.

Comandos:

```bash
RUN_NETWORK_TESTS=1 RUN_OLLAMA_INTEGRATION=1 python -m pytest -v tests/test_ollama_integration_real.py
RUN_NETWORK_TESTS=1 RUN_OLLAMA_INTEGRATION=1 python -m pytest -v tests/test_customer_support_integration_real.py
```

`RUN_NETWORK_TESTS=1` habilita todos os testes marcados com `network` (incluindo cenários que podem depender de serviços externos além do Ollama).
`RUN_OLLAMA_INTEGRATION=1` habilita especificamente os cenários reais de integração com Ollama.

Por padrão, sem `RUN_NETWORK_TESTS=1`, os testes `network` serão pulados.
Sem `RUN_OLLAMA_INTEGRATION=1`, os testes reais de Ollama serão pulados pelos próprios testes.

Para habilitar os testes de rede que reconhecem essa opção:

```bash
RUN_NETWORK_TESTS=1 python -m pytest -v
```

Esses testes exigem conectividade e podem falhar se serviços externos estiverem indisponíveis ou alterarem seu comportamento.

Para validar o estado atual do projeto no seu ambiente, execute a suíte completa:

```bash
python -m pytest -q
```

O resultado pode variar conforme alterações no código, dependências externas e configuração do ambiente.

### Scripts auxiliares

```bash
python scripts/agent_probe.py
python scripts/validate_functionality.py
python scripts/check_scenarios.py
```

Antes de executar os scripts, garanta que as variáveis estejam disponíveis no shell:

```bash
cp -n .env.example .env
set -a
source .env
set +a
```

- `agent_probe.py`: permite inspecionar respostas de agentes; a geração real depende da disponibilidade do Ollama.
- `validate_functionality.py`: executa cenários de validação funcional e grava resultados em `logs/`.
- `check_scenarios.py`: auxilia na verificação de cenários de roteamento.

Os três scripts utilizam `GETNET_DEMO_AUTH_TOKENS` para montar o cabeçalho `Authorization: Bearer ...`. Sem essa configuração, a execução termina com código diferente de zero.

Consulte o código dos scripts para opções e comportamento detalhados.

### Estratégia de avaliação

A avaliação separa o que é determinístico do que depende do modelo.

1. **Testes unitários e de integração via API** (`pytest`, LLM e rede simulados): contratos de cada agente, ferramentas, autenticação, permissões, memória, privacidade e o fluxo HTTP completo com `TestClient`.
2. **Camada 1 dos cenários oficiais** (`tests/test_official_scenarios.py`, roda no CI): para os 10 cenários do enunciado, `eval/official_scenarios.json` fixa rota, plano, ferramenta, documentos que precisam ser recuperados (por hash de conteúdo) e o contrato da resposta. Os requisitos ainda não atendidos ficam em `xfail` com o item de backlog (tabela acima).
3. **Camada 2, com o modelo real** (`eval/run_official_scenarios.py`, fora do CI): gera várias execuções por cenário contra o Ollama, embaralha as respostas e esconde a versão, e um avaliador humano rotula cada resposta como Correta, Parcial ou Incorreta pela rubrica congelada em `eval/official_scenarios_rubrics.md`. Não há juiz LLM. O relatório separa disponibilidade, qualidade e respostas de fallback.

   ```bash
   python eval/run_official_scenarios.py run --out DIR      # exige Ollama
   python eval/run_official_scenarios.py blind --runs DIR --out BLIND --seed 20261108
   python eval/run_official_scenarios.py freeze --blind BLIND   # depois da rotulagem
   python eval/run_official_scenarios.py report --blind BLIND
   ```

**Resultado da camada 2 registrado** (execução de 2026-11-08 sobre o commit `939d2ba`, `qwen2.5:7b`, 86 respostas): 32 Corretas, 48 Parciais e 6 Incorretas, com 100% de disponibilidade. Por cenário: S02, S03, S05 e S07 corretos em todas as execuções; S10 com 5 de 10 corretas; S01 com 1 correta, 7 parciais e 2 incorretas; S04 com 6 parciais e 4 incorretas; S06, S08 e S09 parciais em todas. Leitura honesta desse resultado:

- não é uma aprovação integral: mais da metade das respostas é parcial. Em S04, S06 e S09 as parciais coincidem com os `xfail` de recuperação (RAG-07a/b/c), e em S08 com a falha de orquestração ARCH-02, corrigida depois dessa rodada; em S01 e S10 há respostas parciais ou incorretas sem `xfail` correspondente, ligadas à síntese do modelo;
- foi medido antes das mudanças de privacidade e da correção de ARCH-02. Depois delas, os testes da camada 1 dão 31 aprovados e 5 `xfail` (S08-R4 passou a ser cumprido), e só o S08 foi medido de novo na camada 2 (abaixo);
- os rótulos são de um único avaliador e as amostras são pequenas (3 a 10 execuções por cenário); os arquivos rotulados não estão versionados no repositório.

**Camada 2 do S08 depois da correção de ARCH-02** (2026-11-15, commit `75a8a4a`, `qwen2.5:7b`, 10 execuções, rótulos humanos às cegas, critérios v1.3): **1 Correta, 0 Parciais e 9 Incorretas**, com 100% de disponibilidade. A arquitetura funcionou em todas as execuções: o segundo turno aciona o Knowledge, recupera só L48 e apresenta o fato verificado separado da explicação geral. O problema está na geração: em 9 de 10 respostas o modelo acrescenta causas que L48 não traz (limite de crédito, cartão bloqueado, fraude, saldo insuficiente) ou afirmações não sustentadas, e a rubrica trata isso como informação inventada. Corrigir isso exige restringir a geração (por exemplo, citar o trecho de L48 em vez de gerar texto livre) e uma nova rodada de avaliação; não foi feito.

#### Métricas de recuperação (EVAL-02)

`eval/retrieval_metrics.py` mede Recall@K e MRR sobre os documentos gold dos critérios v1.3, de forma determinística (só `retrieve`, sem LLM e sem rede), e `tests/test_retrieval_metrics.py` roda no CI.

```bash
python eval/retrieval_metrics.py              # tabela em Markdown
python eval/retrieval_metrics.py --json OUT   # também grava o resultado em JSON
```

- **Casos:** os 6 cenários com documentos `required` (S01, S04, S06, S08, S09, S10). Os demais não têm documento gold (ferramentas externas, dados do cliente ou lacuna do corpus).
- **Consulta:** o texto que o sistema envia ao `retrieve`. É a mensagem do usuário nos cenários do Knowledge e a consulta fixa do orquestrador (`DECLINED_SALE_QUERY`) no S08.
- **Métricas:** Recall@K com K ∈ {1, 3, 5, 10} (K = 3 é o `limit` de produção) e MRR sobre os 10 primeiros, ambos com os documentos `required`; e Recall@3 sobre o conjunto ampliado (`required` + `any_of` + `supporting`). Os documentos são identificados pelo hash do conteúdo, como nos critérios.

| Cenário | Posição dos `required` | R@1 | R@3 | R@5 | R@10 | RR | R@3 ampliado |
|---|---|---|---|---|---|---|---|
| S01 | L269: 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.75 |
| S04 | L16: 6 | 0.00 | 0.00 | 0.00 | 1.00 | 0.17 | 0.75 |
| S06 | L145: 5 | 0.00 | 0.00 | 1.00 | 1.00 | 0.20 | 0.50 |
| S08 | L48: 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| S09 | L267: 1, L183: 5 | 0.50 | 0.50 | 1.00 | 1.00 | 1.00 | 0.33 |
| S10 | L203: 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| **Média (6)** | | 0.58 | 0.58 | 0.83 | 1.00 | **MRR 0.73** | 0.72 |

Leitura: todos os documentos `required` aparecem entre os 10 primeiros, mas só 58% entram no contexto de produção (top 3). As três ausências no top 3 são exatamente os `xfail` de recuperação (RAG-07a/b/c). Com K = 5, a cobertura subiria para 83%; mudar o `limit` não foi feito, porque altera o contexto de todas as respostas e exige avaliação própria.

Limitações: são 6 consultas e 7 documentos `required`, então as médias descrevem os cenários oficiais, não a qualidade geral da recuperação; os documentos gold foram definidos por um único autor dos critérios; a relevância é binária e não mede se o contexto é suficiente nem a qualidade da geração; a consulta do S08 foi escolhida para recuperar L48, então o resultado perfeito desse caso é em parte construído; com mais de um documento `required`, o MRR considera só o primeiro (no S09, RR = 1,00 embora L183 esteja em 5º), por isso deve ser lido junto com o Recall@K; os resultados valem para o retrato atual do corpus.

Ainda faltam testes periódicos de contrato com os serviços externos.

## Reprodução da validação final

Sequência recomendada para validar o estado final do projeto:

1. Preparar ambiente e dependências

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. Executar testes padrão

```bash
python -m pytest -q
```

3. Executar testes reais com Ollama

```bash
export RUN_NETWORK_TESTS=1
export RUN_OLLAMA_INTEGRATION=1

python -m pytest -v tests/test_ollama_integration_real.py
python -m pytest -v tests/test_customer_support_integration_real.py
```

4. Subir aplicação com Docker Compose

```bash
cp -n .env.example .env
docker compose up --build -d
docker compose ps
```

5. Verificar API autenticada

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Authorization: Bearer demo-token-cliente1988' \
  -H 'Content-Type: application/json' \
  -d '{"message":"Qual o status da transação txn1001?","user_id":"cliente1988"}'
```

6. Consultar logs e resultados

```bash
docker compose logs -f api
```

## Observabilidade

A API registra eventos de requisição, decisão de roteamento e resposta. A resposta JSON expõe:

| Campo | Finalidade |
|---|---|
| `agent` | Agente que processou a mensagem; em execução multi-etapa, o agente da etapa principal (o `trace` lista todos). |
| `routing_reason` | Justificativa registrada pelo roteador. |
| `tool_used` | Ferramenta ou caminho de execução utilizado, quando aplicável. |
| `sources` | URLs ou fontes usadas pelo agente. |
| `source_sections` | Agrupamento dos documentos recuperados por seção. |
| `flow_completed` | Indica término do ciclo da requisição atual. |
| `response_delivered` | Indica se uma resposta textual foi entregue. |
| `issue_resolved` | Resultado de resolução do problema no nível de negócio. |
| `resolved` | Campo legado de compatibilidade, espelhando `issue_resolved`. |
| `awaiting_user_input` | Indica suspensão aguardando informação obrigatória do usuário. |
| `step_status` | Estado operacional final: `success`, `failed`, `waiting_for_user_input`, `handoff`, `conflict` (fatos verificados contraditórios) ou, no Customer Support, `tool_call_error`, `invalid_result` e `max_iterations_exceeded`. |
| `handoff_required` | Indica se a solicitação deve ser encaminhada para atendimento humano. |
| `handoff` | Ticket de handoff quando criado ou consultado no fluxo. |
| `request_id` | Identificador da requisição, repetido nos logs e no `trace`. |
| `total_latency_ms` | Latência total da requisição na API. |
| `trace` | Uma entrada por etapa executada do plano: agente, motivo, status, ferramenta e `duration_ms`. |
| `verified_facts` / `fact_conflicts` | Fatos confirmados por ferramentas (ex.: status e valor de uma transação) e eventuais contradições entre etapas. |

Para observar logs no Docker:

```bash
docker compose logs -f api
```

Os logs registram, por requisição, o `request_id`, a decisão de roteamento, cada etapa do orquestrador (agente, status, ferramenta e duração) e a latência total. O conteúdo das mensagens não é registrado. Exceções capturadas para devolver uma resposta segura (falha de um agente no orquestrador, erro no loop de function calling, queda do Ollama com fallback extrativo, indisponibilidade de busca, clima ou câmbio) são registradas com o tipo e o stack trace, com dados pessoais mascarados (`app/logging_utils.py`). O projeto ainda não implementa dashboard, tracing distribuído, métricas agregadas, alertas operacionais ou persistência dedicada de eventos, e o `trace` não mede separadamente o tempo de cada chamada ao LLM ou às ferramentas.

## Limitações conhecidas

- **Dados simulados:** as consultas de clientes e transações não acessam sistemas reais da Getnet.
- **Recuperação lexical:** o RAG usa BM25 e normalização de texto, não embeddings ou busca vetorial; perguntas semanticamente distantes dos termos da base podem não recuperar bons trechos.
- **Sem reranking semântico:** não há reranker dedicado após a recuperação lexical.
- **Corpus estático:** o JSONL reflete a data de ingestão; informações de produtos, taxas e procedimentos podem mudar.
- **Dependência opcional do LLM:** o Ollama pode não estar disponível ou pode produzir respostas incorretas apesar das instruções de contexto.
- **Síntese de fontes com escopos diferentes:** na configuração avaliada (BM25 com `limit=3`, prompt atual, `qwen2.5:7b` com parâmetros padrão do Ollama), o sistema não respondeu com segurança a uma pergunta cuja regra muda conforme o produto ou canal: "Do I need a bank account to receive my sales via Pix?". A limitação foi observada só nessa pergunta.
  - **Recuperação:** o documento que traz a exigência específica (Pix no Get Tap) fica em 6º lugar e não entra no contexto.
  - **Geração, com o contexto real:** nenhuma de 40 respostas foi correta. A maioria recusa ou generaliza; as 2 que distinguem modalidades têm erros (uma atribui ao Pix um prazo da Get Conta; a outra extrapola além dos documentos).
  - **Geração, com o Get Tap inserido no contexto:** o modelo restringe a exigência ao Get Tap quando o documento aparece sozinho (19 de 20 respostas). Junto com documentos de outras modalidades, transforma a exigência em regra geral (20 de 20).
  - **Instrução de escopo no prompt:** só ajudou no contexto montado com o Get Tap, onde as respostas corretas foram de 0 para 7 em 20. No contexto real, as recusas subiram de 9 para 16 em 20, e por isso não foi adotada.
  - **Alcance:** a limitação vale para essa configuração. Não foi verificado se persiste com outros modelos.
- **Busca externa:** a pesquisa geral via DuckDuckGo pode ser instável ou bloqueada. Resumos do mecanismo de busca não são verificação independente das páginas.
- **Câmbio:** a fonte e o tipo de cotação seguem a implementação da ferramenta; não se deve interpretar o valor como uma cotação comercial em tempo real sem verificar a resposta e a fonte.
- **Idioma:** a geração foi orientada principalmente para respostas em português; não há garantia de responder no mesmo idioma de toda mensagem recebida.
- **Escalonamento:** o protótipo cria e persiste tickets de handoff em armazenamento local de arquivo JSON; não há integração com plataforma externa de atendimento.
- **Guardrails por regras:** a detecção de intenções sensíveis usa padrões explícitos e não substitui uma solução completa de segurança ou revisão humana.
- **Mascaramento por padrões:** protege os formatos listados em [Segurança e privacidade](#segurança-e-privacidade), com as limitações descritas lá; não é anonimização.
- **Orquestração limitada:** o replanejamento pelo resultado das ferramentas cobre um caso (transação negada sem motivo registrado); não há planejamento geral, várias intenções na mesma mensagem não são tratadas e as respostas das etapas são combinadas em partes, não sintetizadas. Na camada 2, o fluxo funcionou em 10 de 10 execuções, mas só 1 resposta foi correta: o modelo acrescenta causas não documentadas à explicação geral.
- **Persistência em arquivo JSON:** sem bloqueio entre processos; adequada à execução com um único worker, como no `Dockerfile`.
- **Roteamento lexical:** a decisão principal do roteador é baseada em regras de texto, sem classificador semântico dedicado.
- **Observabilidade avançada ausente:** não há dashboard operacional, tracing distribuído ou alertas automáticos nativos.

## Estrutura do projeto

```text
.
├── .github/
│   └── workflows/
│       └── ci.yml
├── app/
│   ├── agents/
│   │   ├── router.py
│   │   ├── knowledge.py
│   │   ├── customer_support.py
│   │   └── web_search.py
│   ├── llm/
│   │   ├── ollama_client.py
│   │   ├── ollama_function_calling.py
│   │   └── ollama_tools.py
│   ├── rag/
│   │   ├── documents/
│   │   │   └── getnet_sources.jsonl
│   │   ├── ingest.py
│   │   └── retriever.py
│   ├── tools/
│   │   ├── customer_tools.py
│   │   ├── exchange_rate.py
│   │   ├── registry.py
│   │   └── weather.py
│   ├── auth.py
│   ├── human_handoff.py
│   ├── orchestrator.py
│   ├── privacy.py
│   ├── session_memory.py
│   ├── verified_facts.py
│   └── main.py
├── docs/                       # auditorias, contrato de resposta e transições do orquestrador
├── eval/
│   ├── official_scenarios.json         # critérios congelados dos 10 cenários
│   ├── official_scenarios_rubrics.md   # rubrica da avaliação humana
│   ├── retrieval_metrics.py            # Recall@K e MRR (EVAL-02)
│   └── run_official_scenarios.py       # camada 2 (modelo real)
├── scripts/
│   ├── agent_probe.py
│   ├── check_scenarios.py
│   └── validate_functionality.py
├── tests/
│   ├── acceptance/
│   ├── fixtures/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_customer_support.py
│   ├── test_handoff_completion.py
│   ├── test_official_scenarios.py
│   ├── test_privacy.py
│   ├── test_privacy_agents.py
│   ├── test_router.py
│   ├── test_scripts_auth.py
│   ├── test_storage_isolation.py
│   └── ...                     # demais testes de agentes, ferramentas e fluxos
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Melhorias futuras

- Estender o replanejamento pelo resultado das ferramentas a outros casos e compor uma resposta única a partir dos fatos verificados e da orientação documentada, medindo o fluxo de ARCH-02 com o modelo real (camada 2).
- Corrigir os casos de recuperação marcados como `xfail` (RAG-07a/b/c, RAG-01) com experimentos controlados e uma nova versão dos critérios.
- Ampliar o conjunto de consultas com relevância anotada (hoje 6 cenários), medir a acurácia do roteamento e a fidelidade da geração, e repetir a camada 2 a cada mudança relevante.
- Avaliar embeddings e recuperação semântica como complemento ao BM25.
- Detectar o idioma da entrada e responder no mesmo idioma.
- Persistir logs estruturados com política explícita de retenção e privacidade.
- Integrar o handoff com uma fila ou ferramenta de atendimento real, se houver autorização e infraestrutura.

---

Este projeto demonstra uma arquitetura multiagente modular, recuperação documental local, uso opcional de LLM, ferramentas externas, guardrails, testes e metadados para inspeção. As limitações acima são intencionais na documentação para distinguir o que está implementado do que seria necessário para uma implantação de produção.