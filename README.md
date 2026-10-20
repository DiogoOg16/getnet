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

- recuperador de conhecimento e RAG lexical
- roteamento por intenção
- autorização de transação e atendimento ao cliente
- busca por FAQ relevante e consultas de Pix/Get Tap
- cobertura de plugins e integrações de e-commerce
- handoff humano para solicitações sensíveis e fora do escopo

Validação executada no projeto:

```bash
cd ~/Documents/getnet
source .venv/bin/activate
pytest -q
```

Resultado verificado: 82 testes passaram, com 1 warning de dependência do FastAPI/Starlette, sem falhas de regressão.

## Estado atual do projeto

O sistema está operacional e alinhado com a proposta de desafio: arquitetura multiagente com roteamento, suporte ao cliente, recuperação lexical sobre um corpus local e handoff humano quando necessário. A base documental foi expandida para cobrir Pix, Get Tap, plugins de e-commerce, erros de maquininha e FAQ da Getnet de forma auditável.

### Milestones validados

Os blocos abaixo foram revisados com base nas páginas oficiais da Getnet e validados por testes e checagens de resposta:

- Pix
- Plugins digitais
- Erros de maquininha ADQ/IDL
- FAQ de Get Tap e suporte geral

Para perguntas que mencionam um erro específico da maquininha, a resposta segue o tutorial da página correspondente, incluindo descrição do erro, momento em que ocorre e passos de correção, em vez de responder apenas com uma frase genérica como “erro de comunicação”.

### Próximo bloco em revisão: Gestão de Vendas

A próxima etapa do escopo é a área de Gestão de Vendas, com foco em:

- acesso às vendas realizadas
- status das vendas
- cancelamento e exportação
- consulta de vendas Pix
- entendimento de status e estados de autorização

Validação executada no projeto:

- consulta da rota `/chat` em blocos-chave do suporte Getnet
- verificação de respostas em português brasileiro e sem inventar passos
- confirmação de agrupamento por seção em `source_sections`
- testes focados em recuperação e API para os blocos já validados

Estrutura esperada da resposta:

```json
{
  "source_sections": {
    "Pix": [
      "Como habilitar o recebimento de vendas via pix no aplicativo Getnet Brasil - Getnet",
      "Como desabilitar o recebimento de vendas via pix no aplicativo Getnet Brasil? - Getnet",
      "Como fazer uma venda com Pix na maquininha? - Getnet"
    ]
  }
}
```

Esse padrão mostra que o Pix está sendo tratado como um bloco identificado, sem misturar o escopo do restante do catálogo.

### Próximo bloco: Get Tap / maquininha / plugins

Como segunda etapa, o foco agora é continuar com blocos específicos de produto e processo, sem abrir o escopo do sistema como um todo de forma genérica.

Próximos blocos em ordem de priorização:

1. Get Tap
2. Maquininha
3. Plugins de e-commerce
4. demais categorias de ajuda da Getnet

A regra daqui em diante é manter a separação por bloco de conhecimento e evitar misturar respostas de diferentes categoriais em uma única bagunça de fontes.

Os ajustes mais recentes preservam seções específicas de plataformas como VTEX, Magento, WooCommerce e Shopify, em vez de perder a informação no resumo geral da página. Isso melhora a qualidade do retriever para perguntas como “quais plugins a Getnet trabalha?” ou “qual plataforma tem Pix e boleto?”.

## Limitações e honestidade técnica

Este projeto foi implementado com um retriever lexical em vez de um pipeline de embeddings completo. Portanto:

- não se afirma uso de LLM generativo no fluxo de recuperação interno;
- não se afirma busca vetorial se ela não estiver implementada;
- fontes externas são consultadas com regras de validação de domínio e cuidado para não inventar resposta.

Essa abordagem é adequada para um desafio técnico de engenharia aplicada, especialmente quando o objetivo é demonstrar robustez, rastreabilidade e organização de código. O projeto mantém um compromisso explícito com honestidade técnica: ele responde com o que a base documental suporta e direciona cenários fora do escopo para atendimento humano.

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
