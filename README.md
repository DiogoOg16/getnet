# Getnet AI Support System

Assistente de suporte multiagente desenvolvido como desafio técnico. A aplicação recebe mensagens por uma API HTTP, identifica a intenção e encaminha a solicitação para um agente especializado: conhecimento da Getnet, suporte a cliente/transação, busca externa ou escalonamento humano.

> **Escopo do protótipo:** dados de clientes e transações são simulados. O sistema não está conectado aos sistemas internos da Getnet e não deve ser usado para decisões operacionais reais.

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
- [Testes e avaliação](#testes-e-avaliação)
- [Reprodução da validação final](#reprodução-da-validação-final)
- [Observabilidade](#observabilidade)
- [Limitações conhecidas](#limitações-conhecidas)
- [Estrutura do projeto](#estrutura-do-projeto)

## Checklist de compliance do desafio

| Requisito do desafio | Implementação (código) | Evidência de testes |
|---|---|---|
| Router e fluxo multiagente | `app/orchestrator.py`, `app/agents/router.py` | `tests/test_router.py`, `tests/test_router_scenarios.py`, `tests/test_orchestrator.py` |
| Knowledge Agent com RAG + busca web | `app/agents/knowledge.py`, `app/rag/retriever.py`, `app/agents/web_search.py` | `tests/test_knowledge.py`, `tests/test_knowledge_fallback.py`, `tests/test_web_search.py` |
| Customer Support com 2+ tools | `app/tools/customer_tools.py`, `app/tools/registry.py`, `app/agents/customer_support.py` | `tests/test_customer_support.py`, `tests/test_tool_registry.py` |
| Endpoint `POST /chat` com JSON significativo | `app/main.py` | `tests/test_api.py`, `tests/acceptance/test_resolution_contract.py` |
| Persistência de sessão e handoff | `app/session_memory.py`, `app/human_handoff.py` | `tests/test_api.py`, `tests/test_behavior_evaluation.py` |
| Dockerização para execução padrão | `Dockerfile`, `docker-compose.yml` | validação manual documentada em "Reprodução da validação final" |
| Testes automatizados e estratégia | `tests/` + seção de estratégia | `python -m pytest -q` (suíte padrão) + testes reais opt-in (`RUN_OLLAMA_INTEGRATION=1`) |
| CI em push/PR para `main` | `.github/workflows/ci.yml` | [Execução CI aprovada no GitHub Actions](https://github.com/DiogoOg16/getnet/actions/runs/4146379649) |

Observação: os testes de integração real com Ollama permanecem opt-in por variável de ambiente e não fazem parte da suíte padrão do CI.

## Principais funcionalidades

- **Roteamento por intenção:** regras explícitas e normalização de texto para direcionar cada mensagem.
- **Conhecimento da Getnet:** recuperação de trechos de uma base documental local e geração opcional com Ollama.
- **Suporte ao cliente:** ferramentas para consultar dados simulados de clientes e transações.
- **Busca externa:** consultas de clima, câmbio e busca geral na web, com validação de domínios permitidos.
- **Guardrails e escalonamento:** pedidos sensíveis, solicitações explícitas de atendimento humano e casos que exigem continuidade manual são encaminhados para o agente de escalonamento.
- **Fallback sem LLM:** o serviço pode funcionar sem Ollama, usando respostas extraídas dos documentos recuperados.
- **Metadados de execução:** a API informa o agente escolhido, motivo do roteamento, fontes, ferramenta usada e necessidade de handoff.

## Arquitetura e fluxo da mensagem

```text
Cliente
  |
  v
FastAPI (/chat)
  |
  v
Router Agent
  |
  +--> Knowledge Agent ------> Retriever local ------> Ollama (opcional)
  |
  +--> Customer Support -----> Ferramentas de cliente/transação simuladas
  |
  +--> Web Search -----------> Clima / câmbio / busca web
  |
  +--> Human Escalation -----> Resposta de encaminhamento
  |
  v
Resposta JSON + metadados
```

### Agentes

| Componente | Responsabilidade |
|---|---|
| `RouterAgent` | Normaliza a mensagem e classifica a intenção por regras explícitas. |
| `KnowledgeAgent` | Recupera informações da base local, aplica respostas diretas em casos específicos e pode consultar o Ollama. |
| `CustomerSupportAgent` | Atende solicitações sobre clientes e transações usando ferramentas com dados simulados. |
| `WebSearchAgent` | Trata perguntas de clima, câmbio e pesquisa externa. |
| Human escalation | Encaminha solicitações sensíveis ou que exigem atendimento humano. É representado pelo fluxo de escalonamento no orquestrador. |
| `ChatOrchestrator` | Executa o agente indicado pelo roteador e padroniza o fluxo de resposta. |

O roteador é baseado em regras, não em uma chamada de LLM. Isso torna a decisão principal previsível e testável, embora regras lexicais possam não reconhecer todas as formas possíveis de uma intenção.

### Fluxo de uma requisição

1. A API valida `message` e `user_id`.
2. O orquestrador chama o roteador.
3. O roteador seleciona o agente de conhecimento, suporte, busca externa, escalonamento ou fallback.
4. O agente executa sua lógica e, quando aplicável, consulta ferramentas ou documentos.
5. A API devolve uma resposta JSON com metadados para inspeção e depuração.

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

1. **Ingestão:** `app/rag/ingest.py` reúne páginas públicas de ajuda e documentação da Getnet, extrai o conteúdo e prepara os registros.
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

- Python 3.11 ou compatível.
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
  "handoff": null
}
```

O exemplo ilustra o contrato da resposta; a mensagem, o status da transação e outros valores dependem dos dados simulados disponíveis na versão executada.

### Endpoints de handoff humano

- `GET /human-handoff`: lista tickets visíveis para o usuário autenticado.
- `GET /human-handoff/{ticket_id}`: consulta um ticket específico.
- `POST /human-handoff/{ticket_id}/assume`: um atendente assume o ticket.
- `POST /human-handoff/{ticket_id}/complete`: um atendente conclui o ticket.

Os endpoints exigem autenticação Bearer. Usuários cliente só podem acessar tickets próprios; atendentes podem operar tickets conforme as regras de transição implementadas.

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

No caso de escalonamento, espera-se que `agent` seja `human_escalation` e `handoff_required` seja `true`. No protótipo, isso representa o sinal de encaminhamento na resposta; não integra automaticamente com uma fila ou sistema real de atendimento.

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
- não há rotina automática de governança além dos limites de tamanho e idade configurados na aplicação.

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

- `tests/conftest.py` substitui `KnowledgeAgent._generate` por resposta simulada;
- testes marcados com `network` são pulados quando `RUN_NETWORK_TESTS` não é `1`.

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

A validação combina testes unitários, testes de integração via API, cenários representativos e inspeção manual. A cobertura atual verifica o comportamento implementado, mas não equivale a uma avaliação quantitativa completa da qualidade das respostas geradas por um LLM real.

Melhorias futuras incluem um conjunto versionado de perguntas e respostas esperadas, métricas de acurácia de roteamento e recuperação, avaliação de fidelidade ao contexto e testes periódicos de contratos com serviços externos.

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
| `agent` | Agente que processou a mensagem. |
| `routing_reason` | Justificativa registrada pelo roteador. |
| `tool_used` | Ferramenta ou caminho de execução utilizado, quando aplicável. |
| `sources` | URLs ou fontes usadas pelo agente. |
| `source_sections` | Agrupamento dos documentos recuperados por seção. |
| `flow_completed` | Indica término do ciclo da requisição atual. |
| `response_delivered` | Indica se uma resposta textual foi entregue. |
| `issue_resolved` | Resultado de resolução do problema no nível de negócio. |
| `resolved` | Campo legado de compatibilidade, espelhando `issue_resolved`. |
| `awaiting_user_input` | Indica suspensão aguardando informação obrigatória do usuário. |
| `step_status` | Estado operacional final (`success`, `failed`, `waiting_for_user_input`, `handoff`). |
| `handoff_required` | Indica se a solicitação deve ser encaminhada para atendimento humano. |
| `handoff` | Ticket de handoff quando criado ou consultado no fluxo. |

Para observar logs no Docker:

```bash
docker compose logs -f api
```

Os logs atuais são voltados à depuração. O projeto ainda não implementa dashboard, tracing distribuído, alertas operacionais ou persistência dedicada de eventos. Em um ambiente real, também seria necessário revisar a política de logging para evitar registrar mensagens ou dados pessoais desnecessários.

## Limitações conhecidas

- **Dados simulados:** as consultas de clientes e transações não acessam sistemas reais da Getnet.
- **Recuperação lexical:** o RAG usa BM25 e normalização de texto, não embeddings ou busca vetorial; perguntas semanticamente distantes dos termos da base podem não recuperar bons trechos.
- **Sem reranking semântico:** não há reranker dedicado após a recuperação lexical.
- **Corpus estático:** o JSONL reflete a data de ingestão; informações de produtos, taxas e procedimentos podem mudar.
- **Dependência opcional do LLM:** o Ollama pode não estar disponível ou pode produzir respostas incorretas apesar das instruções de contexto.
- **Busca externa:** a pesquisa geral via DuckDuckGo pode ser instável ou bloqueada. Resumos do mecanismo de busca não são verificação independente das páginas.
- **Câmbio:** a fonte e o tipo de cotação seguem a implementação da ferramenta; não se deve interpretar o valor como uma cotação comercial em tempo real sem verificar a resposta e a fonte.
- **Idioma:** a geração foi orientada principalmente para respostas em português; não há garantia de responder no mesmo idioma de toda mensagem recebida.
- **Escalonamento:** o protótipo cria e persiste tickets de handoff em armazenamento local de arquivo JSON; não há integração com plataforma externa de atendimento.
- **Guardrails por regras:** a detecção de intenções sensíveis usa padrões explícitos e não substitui uma solução completa de segurança ou revisão humana.
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
│   ├── session_memory.py
│   ├── verified_facts.py
│   └── main.py
├── docs/
├── eval/
├── scripts/
│   ├── agent_probe.py
│   ├── check_scenarios.py
│   └── validate_functionality.py
├── tests/
│   ├── acceptance/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_customer_support.py
│   ├── test_router.py
│   └── test_scripts_auth.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Melhorias futuras

- Criar um dataset de avaliação versionado para os cenários do desafio.
- Medir separadamente acurácia do roteamento, qualidade da recuperação e fidelidade da geração.
- Avaliar embeddings e recuperação semântica como complemento ao BM25.
- Detectar o idioma da entrada e responder no mesmo idioma.
- Persistir logs estruturados com política explícita de retenção e privacidade.
- Integrar o handoff com uma fila ou ferramenta de atendimento real, se houver autorização e infraestrutura.

---

Este projeto demonstra uma arquitetura multiagente modular, recuperação documental local, uso opcional de LLM, ferramentas externas, guardrails, testes e metadados para inspeção. As limitações acima são intencionais na documentação para distinguir o que está implementado do que seria necessário para uma implantação de produção.