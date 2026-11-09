# Rubricas dos cenários oficiais — camada 2 (Ollama real)

Versão 1.1 — revisada com as decisões D1–D8 e D4-b de 2026-11-08. Status: congelado em 2026-11-08. Este arquivo não muda depois da leitura das respostas. Mudanças futuras criam uma nova versão, sem reclassificar resultados antigos.

Documentos citados por linha (`L<n>`) referem-se a `app/rag/documents/getnet_sources.jsonl` com sha256 `4606534b…`, conforme `eval/official_scenarios.json`.

Os dez cenários oficiais (S01–S10) e o caso adicional S05-V são relatados em grupos separados.

## Procedimento

1. **Congelar** este arquivo e `official_scenarios.json` (hashes registrados) antes de gerar.
2. **Gerar** N execuções por cenário via `POST /chat`, cada uma numa sessão nova, com as mesmas mensagens e condições entre versões. Em S05 e S08, cada execução é a conversa completa de dois turnos.
3. **Registrar** por execução: commit, digest do modelo, timestamp, latência, `agent`, `tool_used`, `sources`, conteúdos recuperados (linha + hash), `step_status` e o texto completo de cada turno.
4. **Cegar**: embaralhar as respostas de cada cenário entre versões, com semente registrada, e esconder versão e metadados. Os conteúdos recuperados ficam disponíveis ao classificador, porque a suficiência das evidências depende deles.
5. **Classificar** cada execução gerada numa das três categorias, com uma frase de justificativa, e preencher as anotações.
6. **Registrar** hashes dos rótulos antes de revelar o mapa.
7. **Revelar** e comparar por cenário. O critério de comparação entre versões é definido antes de cada experimento.

Um juiz LLM pode ser usado só como segunda opinião registrada. O rótulo de referência é o humano.

## N por cenário

| Cenários | N | Motivo |
|---|---|---|
| S01, S04, S06, S09, S10 | 10 | Resposta gerada pelo LLM a partir do contexto recuperado. |
| S03, S08 | 10 | Function calling no Ollama decide e executa a ferramenta; o texto final é template, mas o caminho varia. |
| S05 | 10 | Pelo código atual, nenhum turno chama o LLM (variabilidade esperada zero); N=10 por decisão D5, o que também detecta mudanças futuras no fluxo. |
| S05-V | 10 | Passa por Knowledge e geração. |
| S02, S07 | 3, inicialmente | Texto é template da ferramenta e a variação vem da API externa. Aumentar se as 3 execuções divergirem. |

N mede a variabilidade da resposta final, não só o determinismo das ferramentas.

## Métricas

| Métrica | Definição |
|---|---|
| **Availability** | Execuções com resposta efetivamente gerada ÷ execuções do cenário. |
| **Quality** | Distribuição Correta / Parcial / Incorreta, calculada só sobre as respostas geradas. |
| **Degradation** | Quantidade e percentual de respostas degradadas: `tool_used = retrieval_only` ou timeout do Ollama. |
| **External unavailable** | S02 e S07: falha da API externa com mensagem de indisponibilidade e sem valores. Contada à parte. |

Respostas degradadas e indisponibilidade externa não recebem rótulo C/P/I. Uma mudança que melhora quality e piora availability não conta como melhoria absoluta: as métricas são sempre relatadas juntas.

## Categorias

| Categoria | Significado geral |
|---|---|
| **Correta** | Cumpre os itens obrigatórios do cenário e não tem afirmação sem suporte que afete a conclusão. |
| **Parcial** | Útil e sem erro central, mas falta um item obrigatório, generaliza um escopo ou contém extrapolação periférica. |
| **Incorreta** | Conclusão central errada ou sem suporte, dado inventado, dado de outro cliente, ou recusa quando há evidência para responder. |

## Regras gerais

- **G1** — Dizer que não consegue confirmar um ponto não é recusa, se a resposta apresenta o que as evidências sustentam.
- **G2 — recusas e evidência.** "Evidência disponível" é o conjunto do que aquela execução recebeu: documentos recuperados (conteúdo, não só título) e resultados de ferramentas. Cada cenário define abaixo o que conta como evidência suficiente.

| Situação | Classificação |
|---|---|
| Evidência suficiente + recusa | Incorreta |
| Evidência parcial + resposta limitada ao que é sustentado, com a limitação explícita | Parcial |
| Evidência parcial + recusa completa, sem fornecer nenhuma informação sustentada | Incorreta (D4-b) |
| Evidência insuficiente + recusa justificada | Correta |
| Evidência insuficiente + afirmação inventada | Incorreta |

Justificativa (D4-b): o agente deve fornecer as informações que consegue sustentar, deixando claras as limitações, em vez de recusar integralmente quando existe informação útil disponível. Isso evita premiar um agente que se abstém sempre que há alguma incerteza.

- **G3** — Extrapolação periférica que não muda a conclusão impede Correta, mas não torna a resposta Incorreta.

## Anotações (independentes do rótulo)

- `gold_no_contexto`: lista dos documentos gold presentes no resultado da recuperação daquela execução. Explica o resultado; não decide o rótulo.
- `evidencia`: suficiente / parcial / insuficiente, conforme a definição do cenário.
- `recusa`, `afirmacao_sem_suporte`, `contradicao`, `generaliza`, `idioma`.

---

## S01 — Get Clássica vs Get Smart {#s01}

Fontes: L269 (aluguel e isenção das duas); L76, L74, L83 (Get Smart). O corpus não descreve recursos da Get Clássica.

Evidência suficiente: L269 no contexto (comparação de preço e isenção). Evidência parcial: só documentos da Get Smart.

- **Correta**: compara aluguel (R$ 79,90 vs R$ 129,90) **e** isenção (acima de R$ 20 mil vs R$ 40 mil) conforme L269; descreve a Get Smart com recursos de L76/L74/L83; **não** atribui à Get Clássica recursos ou ausência de recursos sem fonte, ou diz explicitamente que a base não detalha a Get Clássica.
- **Parcial**: compara só preço **ou** só recursos; ou afirma sem fonte que a Get Clássica "não tem" os recursos da Smart (G3).
- **Incorreta**: valores de aluguel ou isenção trocados ou inventados; recursos inventados para qualquer uma das duas; recusa com L269 no contexto (G2).

## S02 — Previsão do tempo em Porto Alegre amanhã {#s02}

Saída de ferramenta (template); a rubrica avalia a integração real. Evidência: resultado da Open-Meteo.

- **Correta**: Porto Alegre, data = dia seguinte ao da execução, mínima, máxima e chance de chuva, fonte Open-Meteo.
- **Parcial**: dados corretos, mas data de hoje em vez de amanhã, ou local ambíguo.
- **Incorreta**: valores sem fonte, cidade errada, ou previsão apresentada quando a ferramenta falhou.

## S03 — Quando cai o dinheiro das vendas de ontem {#s03}

Evidência: resultado de `lookup_settlement` relativo à data da execução.

- **Correta**: só as vendas com data de venda = ontem; para cada uma, data da venda **e** data prevista de liquidação, separadas; status em português; aviso de dados simulados. Se a ferramenta não tiver venda de ontem, dizer isso é Correta (G2).
- **Parcial**: dados corretos, mas inclui vendas de outra data, ou não separa data da venda e data de liquidação.
- **Incorreta**: datas ou valores diferentes dos da ferramenta; prazo genérico sem consultar a ferramenta; dados de outro cliente.

## S04 — Conta bancária para receber vendas via Pix {#s04}

Critérios do gabarito `23baf0fc0a31da84` (cenário 4) e de `ambig.md` A1–A7, para manter a comparabilidade com os experimentos de 2026-11-07 e 2026-11-08.

Evidência suficiente: L16 no contexto (exigência do Get Tap) mais pelo menos uma fonte de outra modalidade (L63 ou L231). Evidência parcial: só L63/L231/L120, como no contexto atual (RAG-07a).

- **Correta**: explica que a exigência depende da modalidade; informa que o Get Tap exige vincular conta bancária (L16); não generaliza; não afirma que a Get Conta cumpre a exigência sem evidência. Caso limite (A7): restringe a exigência ao Get Tap e aponta que pode não valer em geral.
- **Parcial**: correta para uma modalidade, mas como regra geral (A1); "não precisa de conta específica" (A2); restrita ao Get Tap sem explicar a variação (A6); com evidência parcial, reconhece a limitação e apresenta o que L63/L231 sustentam.
- **Incorreta**: afirma universalmente que não é necessária conta; afirma que a Get Conta cumpre a exigência sem evidência; conclusão apoiada em contradição (ex.: prazo de "2 dias úteis no cartão" da Get Conta atribuído ao Pix); recusa total conforme G2.

## S05 — Maquininha sem internet {#s05}

Fluxo de atendimento em dois turnos; o segundo é determinístico. O corpus não tem diagnóstico de conectividade de maquininha, então não há evidência suficiente para orientar tecnicamente.

- **Correta**: turno 1 pede o sintoma (sinal/Wi-Fi e mensagem da tela) sem inventar dados do terminal; turno 2 encaminha para atendimento humano com ticket.
- **Parcial**: pede dados desnecessários, ou encaminha sem ter pedido o sintoma.
- **Incorreta**: inventa procedimento técnico, modelo, operadora ou configuração; usa L97 (Get Tap) como orientação para maquininha; pede senha ou dado de cartão.

## S05-V — Conectividade com detalhes na primeira mensagem (caso adicional) {#s05-v}

Fora dos dez oficiais. Avalia a recuperação técnica, não o fluxo de atendimento.

Evidência: o corpus não tem documento relevante; L97 (Get Tap precisa de internet) não é evidência para maquininha.

- **Correta**: diz que a base não tem orientação técnica para o caso e encaminha para atendimento humano, sem inventar procedimento (G2, sem evidência).
- **Parcial**: encaminha, mas inclui orientação genérica sem fonte e sem erro (G3).
- **Incorreta**: apresenta L97 ou outro documento não relacionado como orientação para a maquininha; inventa procedimento.

## S06 — Como funciona a antecipação de recebíveis {#s06}

Fontes: L145 (conceito); L46/L47/L158 (como e onde solicitar). L176 é caso específico de Receba Já.

Evidência suficiente: L145 e pelo menos um de L46/L47/L158. Evidência parcial: só documentos de procedimento (contexto atual, RAG-07b).

- **Correta**: explica o conceito (receber antes do prazo de compensação, vendas no crédito à vista ou parceladas) **e** como ou onde solicitar (app, canais); não inventa taxas, prazos ou condições; só menciona Receba Já se o contexto relacionar de forma pertinente.
- **Parcial**: explica só como solicitar, sem o conceito, reconhecendo a limitação; ou explica o conceito sem o procedimento; ou equipara antecipação a Receba Já.
- **Incorreta**: taxas, prazos ou condições inventados; confunde antecipação com liquidação normal; diz que o contexto não explica nada quando há fonte de procedimento (G2).

## S07 — Cotação do euro hoje {#s07}

Saída de ferramenta (template). Evidência: boletim PTAX.

- **Correta**: PTAX de fechamento do Banco Central, compra e venda, data e hora do boletim; aviso de que não é cotação em tempo real; em fim de semana ou feriado, a data do último dia útil.
- **Parcial**: valor correto sem data ou sem o aviso.
- **Incorreta**: valor sem fonte ou inventado, ou valor apresentado como cotação comercial em tempo real.

## S08 — Erro de transação recusada {#s08}

Avaliada sobre a **conversa completa**: turno 1 sem ID; turno 2 com `txn1003` (do cliente, recusada, sem motivo registrado). Evidência: resultado de `lookup_transaction` e, se recuperado, L48 ("Negada: venda não autorizada pelo emissor/bandeira do cartão").

Requisitos da orientação, em qualquer turno: sustentada por informação disponível; sem atribuir causa específica sem evidência; sem contradizer `lookup_transaction`; sem inventar procedimento de resolução. Não é exigido orientar antes de receber o identificador.

- **Correta**: pede o identificador; confirma a recusa de `txn1003` pela ferramenta e diz que o registro não traz o motivo; em algum turno, explica com base em L48 o que significa uma venda negada.
- **Parcial**: pede o ID e confirma a recusa, sem orientação documentada (comportamento da baseline, ARCH-02); ou orienta de forma genérica sem fonte, mas sem erro (G3).
- **Incorreta**: inventa motivo de recusa, status, valor ou procedimento; contradiz a ferramenta; mostra dados de transação de outro cliente.

## S09 — Parcelas no crediário {#s09}

Fontes: L267 ("até 48 vezes² no cartão de crédito"); L183 (cada emissor estabelece o limite de parcelas; juros na simulação da maquininha); L268 (juros variam conforme o emissor).

Evidência suficiente: L267 e L183. Evidência parcial: só L267 (contexto atual, RAG-07c), que traz a nota ² sobre juros mas não sobre o limite.

- **Correta**: distingue o máximo anunciado (até 48 vezes, L267) do limite efetivo, que depende do emissor do cartão (L183); não confunde com parcelamento lojista no cartão.
- **Parcial**: informa "até 48 vezes" como máximo, sem a ressalva de que o limite efetivo depende do emissor (comportamento observado na baseline); ou só a dependência do emissor, sem o número.
- **Incorreta**: apresenta 48 vezes como disponível para qualquer cartão ou venda (garantia); número diferente de 48 ou sem fonte; afirma que o limite é igual para todos os cartões.

## S10 — Vender pelo WhatsApp com Link de Pagamento {#s10}

Fontes: L203 (envio por redes sociais, WhatsApp, email e SMS; cliente clica, escolhe o método e finaliza); L263.

Evidência suficiente: L203.

- **Correta**: confirma que sim, pelo envio do link no WhatsApp; descreve o fluxo (vendedor envia, cliente clica, escolhe o método e paga); não inventa taxas nem requisitos de contratação.
- **Parcial**: só "sim", sem o fluxo.
- **Incorreta**: nega a possibilidade, ou inventa integração, taxa ou requisito; recusa com L203 no contexto (G2).
