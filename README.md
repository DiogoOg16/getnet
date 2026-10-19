# Getnet AI Support System

Este projeto implementa um sistema multiagente para suporte de clientes e consultas de produtos da Getnet. A arquitetura foi pensada para permitir roteamento de intenção, recuperação de conhecimento interno e consulta a dados de cliente/transação, além de acesso a informação externa quando necessário.

## Visão geral

O sistema é composto por agentes especializados:

- Router Agent: decide qual agente deve atender a mensagem.
- Knowledge Agent: responde com base em FAQ e documentação interna do corpus da Getnet.
- Customer Support Agent: consulta dados simulados do cliente e da transação usando ferramentas internas.
- Web Search Agent: consulta fontes externas quando a pergunta exige informações atuais ou gerais.
- Human Escalation Agent (bônus): detecta solicitações sensíveis, fora do escopo ou sem confiança suficiente e encaminha para atendimento humano.

A API expõe um endpoint `POST /chat` com payload:

```json
{
  "message": "Como funciona a antecipação de recebíveis?",
  "user_id": "cliente1988"
}
```

## Arquitetura e fluxo de mensagens

1. A mensagem entra pela API FastAPI.
2. O `RouterAgent` analisa a intenção e escolhe o agente correto.
3. O agente escolhido processa a pergunta usando as ferramentas e o conhecimento disponível.
4. A resposta volta em JSON estruturado com `agent`, `response`, `sources`, `routing_reason` e `tool_used`.

Fluxo principal:

- Perguntas sobre produtos e serviços da Getnet -> `KnowledgeAgent`
- Dúvidas de conta, cadastro ou transação -> `CustomerSupportAgent`
- Clima, câmbio, notícias e informações externas -> `WebSearchAgent`
- Solicitações sensíveis, fora do escopo ou sem confiança para responder -> `HumanEscalationAgent`

## Agentes

### Router Agent

Localização: `app/agents/router.py`

Responsável por interpretar a intenção da mensagem e encaminhar para o agente adequado. A regra atual usa padrões explícitos para identificar:

- transações (`txn...`)
- problemas com maquininha e internet
- perguntas sobre conta, cadastro e dados do cliente
- consultas externas, como clima e câmbio
- perguntas sobre Getnet, Pix, antecipação e produtos

### Knowledge Agent

Localização: `app/agents/knowledge.py`

O conhecimento interno é recuperado por um retriever lexical com BM25 sobre um corpus em `app/rag/documents`. Esse agente não inventa respostas; ele responde com base nas FAQ e documentos ingeridos.

### Customer Support Agent

Localização: `app/agents/customer_support.py`

Este agente usa ferramentas internas para:

- consultar clientes por `user_id`
- consultar transações por `transaction_id`

Além disso, mantém a autorização por `user_id`: uma transação só pode ser consultada se pertencer ao usuário que a solicita.

### Web Search Agent

Localização: `app/agents/web_search.py`

Este agente faz consultas de dados externos com controle de domínio e fontes permitidas. Ele cobre cenários como:

- previsão do tempo
- câmbio e taxas
- busca genérica em fontes públicas

### Human Escalation Agent (bônus)

Localização: `app/agents/router.py` e fluxo de API em `app/main.py`

Este handoff foi adicionado como critério de segurança e operação. Quando a mensagem envolve dados sensíveis, tarefas fora do escopo ou um nível de incerteza que não pode ser resolvido com segurança, o router envia para atendimento humano. Isso reduz riscos de resposta inadequada e melhora a confiabilidade da operação.

## Pipeline de RAG

### 1. Ingestão

Os documentos foram armazenados em JSON Lines em `app/rag/documents/getnet_sources.jsonl`.

### 2. Normalização e indexação

O retriever em `app/rag/retriever.py` faz:

- normalização de texto
- remoção de acentos
- tokenização por expressão regular
- remoção de stopwords
- stemming simples por truncamento de termos
- indexação lexical com BM25

### 3. Recuperação

`retrieve(query)` calcula:

- pontuação BM25 por documento
- cobertura dos termos conhecidos
- filtro mínimo de qualidade
- ordenação por relevância
- deduplicação por título

### 4. Resposta

O `KnowledgeAgent` monta a resposta com os títulos e conteúdos recuperados. Como o projeto ainda usa recuperação lexical, não há uma afirmação de uso de embeddings, busca vetorial ou LLM generativo neste fluxo.

## Tecnologias utilizadas

- Python 3.11
- FastAPI
- Pydantic
- Uvicorn
- Pytest
- BM25 lexical retrieval
- BeautifulSoup para web scraping e parsing de resultados
- requests para acesso externo

## Execução local

### Requisitos

- Python 3.11
- Ambiente virtual recomendado

### Instalar dependências

```bash
cd ~/Documents/getnet
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Rodar a API

```bash
cd ~/Documents/getnet
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Testar

```bash
cd ~/Documents/getnet
source .venv/bin/activate
pytest -q
```

## Docker

### Build e execução com Docker

```bash
cd ~/Documents/getnet
docker build -t getnet-ai-agent .
docker run --rm -p 8000:8000 getnet-ai-agent
```

### Com Docker Compose

```bash
cd ~/Documents/getnet
docker compose up --build
```

A aplicação fica disponível em:

- http://localhost:8000/health
- http://localhost:8000/docs

## Exemplos de uso da API

### Requisição

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Como funciona a antecipação de recebíveis?",
    "user_id": "cliente1988"
  }'
```

### Resposta esperada

```json
{
  "user_id": "cliente1988",
  "message": "Como funciona a antecipação de recebíveis?",
  "response": "Encontrei informações relacionadas ...",
  "agent": "knowledge",
  "routing_reason": "The message appears to ask about a Getnet product or service.",
  "sources": ["O que é antecipação de vendas?"],
  "tool_used": null,
  "handoff_required": false
}
```

Exemplo de escalonamento humano:

```json
{
  "user_id": "cliente1988",
  "message": "Preciso de ajuda com dados pessoais sensíveis e não posso continuar sem atendimento humano.",
  "response": "Solicitação fora do escopo ou sensível. Encaminho para atendimento humano para continuidade segura.",
  "agent": "human_escalation",
  "routing_reason": "The request is sensitive, unsupported, or requires human assistance.",
  "sources": [],
  "tool_used": "human_escalation",
  "handoff_required": true
}
```

## Estratégia de testes

Os testes cobrem:

- recuperador de conhecimento
- roteamento por intenção
- autorização de transação
- busca por FAQ relevante
- consultas de clientes e transações
- integrações de API e agentes
- handoff humano para solicitações sensíveis e fora do escopo

A suite atual usa `pytest` e valida os comportamentos críticos sem depender de rede estável. Para cenários de rede, o código usa validações de falha sem depender de disponibilidade externa. O bônus de escalation também foi validado com testes automatizados.

## Limitações e honestidade técnica

Este projeto foi implementado com um retriever lexical em vez de um pipeline de embeddings completo. Portanto:

- não se afirma uso de LLM generativo no fluxo de recuperação interno;
- não se afirma busca vetorial se ela não estiver implementada;
- fontes externas são consultadas com regras de validação de domínio e cuidado para não inventar resposta.

Essa abordagem é adequada para um desafio técnico de engenharia aplicada, especialmente quando o objetivo é demonstrar robustez, rastreabilidade e organização de código.

## Melhorias futuras

- adicionar persistência de logs estruturados
- implementar avaliação automatizada por conjunto de perguntas
- ampliar guardrails para outros tipos de conteúdo sensível
- expandir o corpus documental
- evoluir para um pipeline com LLM real, se houver necessidade de geração mais sofisticada

## Observações finais

O projeto está organizado em módulos bem separados:

- `app/agents/`
- `app/rag/`
- `app/tools/`
- `app/main.py`
- `tests/`

Essa separação facilita manutenção, extensão e entendimento do sistema multiagente.
