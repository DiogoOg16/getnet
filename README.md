# Getnet AI Support System

Este projeto implementa um assistente multiagente para suporte de clientes da Getnet, com rota por intenção, recuperação de conhecimento local e integração opcional com um modelo LLM executando no host via Ollama.

## Objetivo

Cria um sistema que:

- roteia mensagens para o agente correto;
- responde perguntas sobre produtos e serviços da Getnet com base em um corpus local;
- consulta dados internos de cliente/transação quando necessário;
- usa busca externa para informações gerais e atuais;
- aplica guardrails e handoff humano para solicitações sensíveis ou fora do escopo.

## Visão geral da arquitetura

### Agentes

- Router Agent: decide qual agente atende a mensagem.
- Knowledge Agent: responde usando RAG local e, opcionalmente, um modelo LLM pelo Ollama.
- Customer Support Agent: consulta dados simulados de cliente e transação.
- Web Search Agent: consulta APIs externas, como clima e câmbio.
- Human Escalation Agent: encaminha solicitações sensíveis para atendimento humano.

### Fluxo principal

1. A mensagem entra pela API FastAPI.
2. O router classifica a intenção.
3. O agente correspondente executa a lógica.
4. A resposta volta em JSON estruturado com `agent`, `routing_reason`, `response`, `sources`, `source_sections`, `tool_used` e `handoff_required`.

## Estrutura do projeto

- `app/main.py`: API FastAPI e rota `/chat`
- `app/agents/router.py`: roteamento por intenção
- `app/agents/knowledge.py`: recuperação de conhecimento + LLM opcional + fallback
- `app/agents/customer_support.py`: suporte ao cliente
- `app/agents/web_search.py`: busca externa
- `app/tools/customer_tools.py`: ferramentas de consulta de clientes e transações
- `app/rag/retriever.py`: recuperação lexical sobre o corpus
- `app/rag/ingest.py`: ingestão e preparação do corpus
- `app/rag/documents/getnet_sources.jsonl`: base documental local
- `tests/`: suíte de testes automatizados
- `docker-compose.yml`: execução da API e do Ollama em perfil opcional

## Como o Knowledge Agent funciona

O agente de conhecimento usa uma abordagem híbrida:

1. Recupera documentos relevantes do corpus local pelo retriever.
2. Tenta responder diretamente quando a pergunta é específica e bem coberta pela base.
3. Se a base não for suficiente, chama o Ollama com `OLLAMA_URL/api/chat`.
4. Se o modelo falhar ou não estiver disponível, usa resposta extrativa a partir dos trechos recuperados.

### Estados de resposta

O campo `tool_used` pode assumir:

- `ollama` → uso do modelo local
- `retrieval_only` → fallback sem LLM
- `lookup_transaction` / `lookup_customer` → suporte do cliente
- `open_meteo` → busca externa
- `human_escalation` → handoff humano

Esse comportamento foi pensado para manter o sistema funcional mesmo sem LLM, e para deixar explícito quando o modelo foi realmente usado.

## Roteamento por módulo

### Knowledge

Perguntas sobre:

- Getnet
- Pix
- antecipação
- plugins
- produtos e serviços
- erros de maquininha
- status de vendas

### Customer Support

Perguntas que envolvem:

- transação (`txn...`)
- dados do cliente
- status de conta
- consulta de extrato ou transação

### Web Search

Perguntas como:

- clima
- câmbio
- previsões
- notícias
- informações externas ou atuais

### Human Escalation

Perguntas sensíveis ou fora do escopo:

- dados pessoais
- pedidos de atendimento humano
- mensagens que exigem continuidade manual

## Requisitos

- Python 3.11
- Docker e Docker Compose (opcional, para execução em container)
- Ollama opcional local para geração com LLM

## Instalação local

```bash
cd ~/Documents/getnet
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execução local da API

```bash
cd ~/Documents/getnet
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Healthcheck:

```bash
curl http://localhost:8000/health
```

Resposta esperada:

```json
{"status":"ok"}
```

## Execução com Docker

### Modo padrão sem LLM

```bash
docker compose up --build
docker compose ps
```

Esse modo sobe somente a API e usa fallback extrativo quando o Ollama não está disponível.

### Modo com Ollama

```bash
docker compose --profile llm up --build
```

Esse perfil sobe:

- `api`
- `ollama`
- `ollama-pull`

O serviço `ollama-pull` baixa o modelo padrão `qwen2.5:7b` uma vez.

### Conexao com Ollama do host

Se você já tem Ollama rodando no host, pode usar:

```bash
OLLAMA_URL=http://host.docker.internal:11434 docker compose up --build
```

## Variáveis de ambiente

- `OLLAMA_URL`: URL do serviço Ollama
- `OLLAMA_MODEL`: modelo usado pelo agente de conhecimento

Valores padrão:

```bash
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

## Testes

### Rodar a suíte completa

```bash
cd ~/Documents/getnet
source .venv/bin/activate
pytest -q
```

### Resultado verificado

A suíte atual foi validada com sucesso:

- mais de 100 testes aprovados (rode `pytest -q` para o número atual)
- 1 teste skipped (usa a internet; rode com `RUN_NETWORK_TESTS=1`)
- 1 warning de dependência do FastAPI/Starlette

## Exemplos de uso da API

### Pergunta de conhecimento

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Como funciona a antecipação de recebíveis?",
    "user_id": "cliente1988"
  }'
```

### Pergunta de clima

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Qual é a previsão do tempo em Porto Alegre amanhã?",
    "user_id": "cliente1988"
  }'
```

### Pergunta de suporte

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Minha transação txn123 foi recusada e eu quero saber o status.",
    "user_id": "cliente1988"
  }'
```

### Pergunta sensível

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Preciso falar com um humano sobre dados sensíveis do meu cadastro.",
    "user_id": "cliente1988"
  }'
```

## Observações importantes

- O projeto foi pensado para funcionar mesmo sem LLM, usando recuperação local e fallback extrativo.
- Quando o Ollama está disponível, o sistema usa geração real por LLM.
- O `tool_used` é a forma mais clara de ver o que aconteceu no processamento.
- O sistema evita responder com segurança quando o input é sensível ou fora do escopo.

## Bônus implementado e observabilidade

Este projeto inclui elementos do bônus proposto:

- Agente de escalonamento humano para solicitações sensíveis ou fora do escopo
- Guardrails explícitos de segurança e classificação de intenção
- Respostas estruturadas com metadados de `agent`, `routing_reason`, `tool_used`, `sources` e `handoff_required`
- Logs de execução para rastrear decisão do router e ferramenta usada
- Validação funcional por cenários reais de negócio e suporte

### Estratégia de avaliação

A validação usa cenários representativos (ainda não há conjunto de avaliação automatizado nem métricas de qualidade das respostas), incluindo:

- perguntas sobre Pix e Getnet
- busca externa (clima)
- suporte de transação com dados de cliente
- interação com handoff humano

Os testes automatizados cobrem essas rotas pela API. O LLM (Ollama) e as chamadas de rede são simulados nos testes (`tests/conftest.py`), então a suíte roda offline em menos de 1 segundo. A geração real por LLM é conferida manualmente com `scripts/agent_probe.py`.

### Observabilidade

O projeto expõe metadados que facilitam a inspeção:

- `agent`: agente que resolveu a mensagem
- `routing_reason`: justificativa da decisão do router
- `tool_used`: ferramenta executada
- `handoff_required`: indica encaminhamento para humano
- `sources`: fontes consultadas para resposta

Essa estrutura simplifica debug, auditoria e análise de qualidade dos agentes.

## Checklist do desafio

O projeto cobre os requisitos principais do desafio:

- arquitetura multiagente
- API HTTP
- roteamento por intenção
- recuperação de conhecimento
- busca externa
- suporte ao cliente
- guardrails e handoff humano
- Docker
- testes
- documentação

## Pipeline de RAG

1. **Ingestão** (`app/rag/ingest.py`): `requests` e BeautifulSoup baixam artigos de ajuda, páginas de FAQ (`/duvidas/<categoria>/`, um trecho por par pergunta e resposta), páginas de produto e documentação técnica da Getnet. A última ingestão gerou 269 trechos, cada um com `title`, `content`, `source_url`, `category` e `ingested_at`. A base é um retrato da data da ingestão.
2. **Armazenamento**: arquivo JSONL versionado (`app/rag/documents/getnet_sources.jsonl`). O índice é montado em memória na primeira consulta. Não há banco vetorial.
3. **Recuperação** (`app/rag/retriever.py`): texto normalizado sem acentos, radical de 5 letras, sinônimos de inglês para português e BM25 (k1=1,5 e b=0,75) com o título pesando em dobro. Um trecho só é devolvido se passar de um score mínimo, cobrir pelo menos 45% do peso dos termos da pergunta e conter o termo mais raro dela. Abaixo disso o agente diz que não encontrou, em vez de arriscar uma resposta.
4. **Geração** (`app/agents/knowledge.py`): para algumas perguntas específicas já cobertas pela base há respostas diretas por regras (`_direct_answer`). Nos demais casos o contexto recuperado vai para o Ollama (`qwen2.5:7b`) com um prompt de sistema que manda responder só com o contexto, não inventar regras, taxas ou procedimentos, e dizer quando não há informação suficiente. Se o Ollama não estiver disponível, a resposta é extrativa, com os trechos recuperados. O prompt pede respostas em português, por isso perguntas em inglês também voltam em português.

## Estratégia de testes

**O que existe hoje**

- Testes unitários por agente e por ferramenta, com rede simulada (câmbio, clima, busca na web e suporte ao cliente).
- Roteamento: tabela parametrizada com os 10 cenários do desafio, equivalentes em português, falsos positivos e casos de escalação.
- Recuperação: testes de regressão com perguntas conhecidas, incluindo casos em que nada deve ser devolvido.
- Integração pela API: `TestClient` percorre o fluxo completo (router, agente e resposta JSON), incluindo a propriedade da transação e o handoff humano.
- Isolamento: `tests/conftest.py` simula o LLM em todos os testes, e o único teste que usa a internet fica pulado por padrão.
- Verificação manual: `scripts/agent_probe.py` mostra a resposta exata (com Ollama real, se estiver ligado), `scripts/validate_functionality.py` grava respostas de cenários em `logs/`, e o Docker Compose sobe a API para testes de ponta a ponta.

**Como eu aprofundaria a integração** (ainda não implementado)

- Um conjunto de perguntas de referência (as 10 do desafio mais variações em português e inglês) com o agente e a fonte esperados, medindo acurácia de roteamento e acerto da recuperação em CI.
- Avaliação da geração com o Ollama real em um job separado: fidelidade ao contexto e taxa de recusa correta quando a base não tem a resposta.
- Testes de contrato agendados contra as APIs do Banco Central e do Open-Meteo, para detectar mudanças.
- Rodar esse conjunto contra o container no Compose antes de cada entrega.

## Limitações e honestidade técnica

Este projeto foi implementado com um retriever lexical em vez de um pipeline de embeddings completo. Portanto:

- a recuperação é lexical (BM25 com radical de 5 letras); a geração com LLM (Ollama, `qwen2.5:7b`) é opcional: sem ele a resposta é extrativa (`tool_used=retrieval_only`);
- não se afirma busca vetorial se ela não estiver implementada;
- fontes externas são consultadas com regras de validação de domínio e cuidado para não inventar resposta;
- dados de clientes e transações são simulados;
- a base não tem artigo sobre falha de conexão nem sobre recusa de transação na maquininha, e nesses casos a resposta é fraca ou diz que não há informação;
- as respostas saem em português, mesmo quando a pergunta é em inglês;
- câmbio é a PTAX de fechamento do Banco Central (não é tempo real) e a busca geral via DuckDuckGo é instável por causa do bloqueio anti-robô;
- a base é um retrato da data da ingestão e preços e condições podem mudar.

Essa abordagem é adequada para um desafio técnico de engenharia aplicada, especialmente quando o objetivo é demonstrar robustez, rastreabilidade e organização de código. O projeto mantém um compromisso explícito com honestidade técnica: ele responde com o que a base documental suporta e direciona cenários fora do escopo para atendimento humano.

## Melhorias futuras

- adicionar persistência de logs estruturados
- implementar avaliação automatizada por conjunto de perguntas
- ampliar guardrails para outros tipos de conteúdo sensível
- expandir o corpus documental
- embeddings e busca vetorial para recuperação semântica
- detectar o idioma da pergunta e responder no mesmo idioma

## Observações finais

O projeto está organizado em módulos bem separados:

- `app/agents/`
- `app/rag/`
- `app/tools/`
- `app/orchestrator.py`
- `app/main.py`
- `tests/`

Essa separação facilita manutenção, extensão e entendimento do sistema multiagente.
