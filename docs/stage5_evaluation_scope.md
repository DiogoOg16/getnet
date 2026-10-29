# Stage5 Evaluation Scope and Baseline Note

This document freezes the current scope for Stage5 evaluation and clarifies what is and is not proven by the current cases.

## Baseline status

There is no previous Git-tracked baseline for `eval/stage5_cases.json`.

Operational consequence:
- historical expectation changes cannot be verified with a Git diff against an older committed version
- future updates must be versioned from now on

## Delivery scope decision

The following items are part of product/test delivery scope:
- `app/human_handoff.py`
- `app/session_memory.py`
- `eval/stage5_cases.json`
- `tests/test_stage5_evaluation.py`
- `tests/acceptance/test_resolution_contract.py`
- orchestrator/router/support/auth/api updates already reflected in tracked files

The following are local process artifacts and should stay out of commits:
- `.session_memory.json`
- `.audit/`

## Stage5 cases: success criteria and limitations

### EVAL-001 prazo_recebimento
- Expected agent: `customer_support`
- Expected handoff: `false`
- Expected resolved: `true`
- Evidence tokens: `prazo`, `recebimento`
- Limitation: proves grounded guidance in simulated context, not real settlement confirmation.

### EVAL-002 conectividade_maquininha
- Expected agent: `customer_support`
- Expected handoff: `false`
- Expected resolved: `false`
- Evidence tokens: `transação`, `txn1001`
- Limitation: validates request for additional diagnostic context; does not prove end-to-end device recovery.

### EVAL-003 transacao_recusada
- Expected agent: `customer_support`
- Expected handoff: `false`
- Expected resolved: `false`
- Evidence tokens: `transação`, `identificador`
- Limitation: without transaction identifier, only data collection is provable.

### EVAL-004 pix_produtos
- Expected agent: `knowledge`
- Expected handoff: `false`
- Expected resolved: `false`
- Evidence tokens: `simulada`, `documentos`
- Limitation: informational answer quality is validated, not operational issue closure.

### EVAL-005 pix_produtos
- Expected agent: `knowledge`
- Expected handoff: `false`
- Expected resolved: `false`
- Evidence tokens: `simulada`, `documentos`
- Limitation: same as EVAL-004; knowledge response does not imply business issue resolution.

### EVAL-006 encaminhamento_humano
- Expected agent: `human_escalation`
- Expected handoff: `true`
- Expected resolved: `false`
- Evidence tokens: `atendimento humano`, `encaminho`
- Limitation: success means correct escalation and persisted ticket, not bot resolution.

### EVAL-007 fora_base
- Expected agent: `fallback`
- Expected handoff: `false`
- Expected resolved: `false`
- Evidence tokens: `não consegui`, `identificar`
- Limitation: validates safe out-of-scope behavior only.

### EVAL-008 externa
- Expected agent: `web_search`
- Expected handoff: `false`
- Expected resolved: `false`
- Objective outcomes:
	- successful query path: exchange quote evidence in response text (e.g., PTAX context with buy/sell wording)
	- provider unavailable path: explicit unavailability message plus official fallback source (`https://www.bcb.gov.br/conversao`)
- Limitation: validates routing and contract behavior under external dependency variance, not external data accuracy audit.

## Governance for next phase

Before changing Stage5 expectations again:
1. commit a baseline snapshot of `eval/stage5_cases.json`
2. document scenario-level acceptance intent in the same change
3. keep `expected_resolved` tied to observable closure criteria, not optimistic interpretation
