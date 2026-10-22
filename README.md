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

- 108 testes aprovados
- 1 teste skipped
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

A validação usa cenários de produção simulados, incluindo:

- perguntas sobre Pix e Getnet
- busca externa (clima)
- suporte de transação com dados de cliente
- interação com handoff humano

Os testes automatizados cobrem essas rotas pela API e verificam o comportamento real do sistema sem mocks de fluxo principal.

### Observabilidade

O projeto foi projetado para facilitar inspeção em produção:

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

## Próximo passo sugerido

A próxima etapa recomendada é a apresentação em vídeo, usando um conjunto de perguntas que mostrem cada módulo em ação:

1. Knowledge com LLM
2. Knowledge sem LLM / fallback
3. Web Search
4. Customer Support
5. Human Escalation
6. Pergunta de erro de maquininha ou Pix

Essa sequência deixa claro para o avaliador que o sistema foi construído de forma funcional e que o código está realmente respondendo como esperado.

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
