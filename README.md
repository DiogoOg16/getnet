# Getnet AI Support System

Assistente de suporte multiagente desenvolvido como desafio técnico. A aplicação recebe mensagens por uma API HTTP, identifica a intenção e encaminha a solicitação para um agente especializado: conhecimento da Getnet, suporte a cliente/transação, busca externa ou escalonamento humano.

> **Escopo do protótipo:** dados de clientes e transações são simulados. O sistema não está conectado aos sistemas internos da Getnet e não deve ser usado para decisões operacionais reais.

## Índice

- [Principais funcionalidades](#principais-funcionalidades)
- [Arquitetura e fluxo da mensagem](#arquitetura-e-fluxo-da-mensagem)
- [Pipeline de RAG](#pipeline-de-rag)
- [Requisitos](#requisitos)
- [Execução local](#execução-local)
- [Execução com Docker](#execução-com-docker)
- [API HTTP](#api-http)
- [Testes e avaliação](#testes-e-avaliação)
- [Observabilidade](#observabilidade)
- [Limitações conhecidas](#limitações-conhecidas)
- [Estrutura do projeto](#estrutura-do-projeto)

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

### 1. Criar e instalar o ambiente

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Iniciar a API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

A API ficará disponível em `http://127.0.0.1:8000`. A documentação interativa do FastAPI fica em `http://127.0.0.1:8000/docs`.

### 3. Verificar a aplicação

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

Exemplo de requisição:

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
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
  "handoff_required": false
}
```

O exemplo ilustra o contrato da resposta; a mensagem, o status da transação e outros valores dependem dos dados simulados disponíveis na versão executada.

### Exemplos adicionais

**Pergunta sobre conhecimento local:**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Como funciona o Pix?","user_id":"cliente1988"}'
```

**Previsão do tempo:**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Qual é a previsão do tempo em Porto Alegre amanhã?","user_id":"cliente1988"}'
```

**Pedido de atendimento humano:**

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Preciso falar com um humano sobre dados sensíveis do meu cadastro.","user_id":"cliente1988"}'
```

No caso de escalonamento, espera-se que `agent` seja `human_escalation` e `handoff_required` seja `true`. No protótipo, isso representa o sinal de encaminhamento na resposta; não integra automaticamente com uma fila ou sistema real de atendimento.

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

A suíte cobre API, roteamento, agentes, ferramentas, fallback de conhecimento, integração e escalonamento. Os testes automatizados simulam o LLM e as dependências de rede para manter a execução previsível. Um teste dependente de internet é ignorado por padrão.

Para habilitar os testes de rede que reconhecem essa opção:

```bash
RUN_NETWORK_TESTS=1 python -m pytest -v
```

Esses testes exigem conectividade e podem falhar se serviços externos estiverem indisponíveis ou alterarem seu comportamento.

**Resultado registrado durante a validação deste projeto:** 111 testes passaram e 1 foi ignorado por depender de rede. O resultado pode variar após alterações no código ou no ambiente. Foi observado também um aviso de depreciação relacionado a dependências de teste.

### Scripts auxiliares

```bash
python scripts/agent_probe.py
python scripts/validate_functionality.py
python scripts/check_scenarios.py
```

- `agent_probe.py`: permite inspecionar respostas de agentes; a geração real depende da disponibilidade do Ollama.
- `validate_functionality.py`: executa cenários de validação funcional e grava resultados em `logs/`.
- `check_scenarios.py`: auxilia na verificação de cenários de roteamento.

Consulte o código dos scripts para opções e comportamento detalhados.

### Estratégia de avaliação

A validação combina testes unitários, testes de integração via API, cenários representativos e inspeção manual. A cobertura atual verifica o comportamento implementado, mas não equivale a uma avaliação quantitativa completa da qualidade das respostas geradas por um LLM real.

Melhorias futuras incluem um conjunto versionado de perguntas e respostas esperadas, métricas de acurácia de roteamento e recuperação, avaliação de fidelidade ao contexto e testes periódicos de contratos com serviços externos.

## Observabilidade

A API registra eventos de requisição, decisão de roteamento e resposta. A resposta JSON expõe:

| Campo | Finalidade |
|---|---|
| `agent` | Agente que processou a mensagem. |
| `routing_reason` | Justificativa registrada pelo roteador. |
| `tool_used` | Ferramenta ou caminho de execução utilizado, quando aplicável. |
| `sources` | URLs ou fontes usadas pelo agente. |
| `source_sections` | Agrupamento dos documentos recuperados por seção. |
| `handoff_required` | Indica se a solicitação deve ser encaminhada para atendimento humano. |

Para observar logs no Docker:

```bash
docker compose logs -f api
```

Os logs atuais são voltados à depuração. O projeto ainda não implementa dashboard, tracing distribuído, alertas operacionais ou persistência dedicada de eventos. Em um ambiente real, também seria necessário revisar a política de logging para evitar registrar mensagens ou dados pessoais desnecessários.

## Limitações conhecidas

- **Dados simulados:** as consultas de clientes e transações não acessam sistemas reais da Getnet.
- **Recuperação lexical:** o RAG usa BM25 e normalização de texto, não embeddings ou busca vetorial; perguntas semanticamente distantes dos termos da base podem não recuperar bons trechos.
- **Corpus estático:** o JSONL reflete a data de ingestão; informações de produtos, taxas e procedimentos podem mudar.
- **Dependência opcional do LLM:** o Ollama pode não estar disponível ou pode produzir respostas incorretas apesar das instruções de contexto.
- **Busca externa:** a pesquisa geral via DuckDuckGo pode ser instável ou bloqueada. Resumos do mecanismo de busca não são verificação independente das páginas.
- **Câmbio:** a fonte e o tipo de cotação seguem a implementação da ferramenta; não se deve interpretar o valor como uma cotação comercial em tempo real sem verificar a resposta e a fonte.
- **Idioma:** a geração foi orientada principalmente para respostas em português; não há garantia de responder no mesmo idioma de toda mensagem recebida.
- **Escalonamento:** o protótipo sinaliza a necessidade de atendimento humano, mas não cria um chamado nem transfere a conversa para um operador real.
- **Guardrails por regras:** a detecção de intenções sensíveis usa padrões explícitos e não substitui uma solução completa de segurança ou revisão humana.

## Estrutura do projeto

```text
.
├── app/
│   ├── agents/
│   │   ├── router.py
│   │   ├── knowledge.py
│   │   ├── customer_support.py
│   │   └── web_search.py
│   ├── rag/
│   │   ├── documents/
│   │   │   └── getnet_sources.jsonl
│   │   ├── ingest.py
│   │   └── retriever.py
│   ├── tools/
│   ├── orchestrator.py
│   └── main.py
├── scripts/
├── tests/
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
