# Priority 2 — Multi-Agent Architecture Audit (V1)

This audit maps the current architecture, decision flow, failure behavior, and key risks to support technical defense and next-step prioritization.

## 1) End-to-end request flow

Primary path (`POST /chat`):

1. Authenticate Bearer token and map token -> user (`authenticate_user`).
2. Enforce identity match: authenticated user must equal request `user_id`.
3. Resolve session key (`session_id` or user fallback).
4. If active handoff exists and user asks status/human support lifecycle:
   - return explicit handoff status contract.
5. Load recent session context.
6. Attempt direct memory answer (`answer_from_context`) for name-recall style requests.
7. Otherwise, call orchestrator with:
   - raw message if no context, or
   - "context + current question" prompt.
8. Normalize contract fields (`flow_completed`, `response_delivered`, `issue_resolved`, `step_status`, etc.).
9. Persist turn in session memory.
10. Return JSON response + execution trace.

Reference files:
- `app/main.py`
- `app/auth.py`
- `app/orchestrator.py`
- `app/session_memory.py`
- `app/human_handoff.py`

## 2) Is this truly multi-agent?

### What is already multi-agent

- Specialized agents with distinct responsibilities:
  - router decision logic (`RouterAgent`)
  - customer support (`CustomerSupportAgent`)
  - knowledge/RAG (`KnowledgeAgent`)
  - web utilities (`WebSearchAgent`)
  - human escalation path
- Bounded execution plan object and step trace in orchestrator.
- Multi-step execution exists for a specific class of messages:
  - customer support first, then knowledge follow-up for declined-transaction guidance.

### What is still limited

- Agent sequencing is narrow and rule-triggered (not general-purpose planning).
- No generic delegation graph between agents.
- Router remains lexical/rule-based only.
- Memory answer can short-circuit routing and hide potential intent changes.

Conclusion:
- The system is legitimately multi-agent in structure and execution tracing,
  but with **limited planning depth** and **deterministic routing**.

## 3) Routing decision matrix (current behavior)

Priority order in router is deterministic:
1. human escalation patterns
2. explicit transaction id (`txn...`)
3. device-related patterns (operational failure or procedural guidance)
4. support/account/payment phrases
5. general concept (non-Getnet) -> web
6. web/external/current-info patterns
7. knowledge product/service patterns
8. fallback

Strength:
- Predictable, testable, explainable.

Risk:
- Pattern precedence can produce false positives in mixed-intent prompts.

## 4) Failure and resilience behavior

### Agent/tool failure behavior

- Knowledge agent:
  - if Ollama fails, fallback to retrieval-only extractive response.
- Web/external tools:
  - external failures converted to controlled response paths.
- Orchestrator step exceptions:
  - catches exception, appends error trace step, returns fallback failure message.

### Operational terminal conditions in orchestrator

Execution halts when a step returns:
- handoff required,
- waiting for user input,
- failed step status,
- handoff/waiting terminal status.

This prevents runaway loops and keeps execution bounded.

## 5) Shared state and contamination risk

Stateful stores are process-global instances in `app/main.py`:
- `session_memory`
- `handoff_store`

Implications:
- Good for continuity and simple runtime persistence.
- Risk of cross-case contamination in non-isolated evaluations unless sessions are explicitly separated.

Mitigations already added in Priority 1:
- isolated `session_id` conventions in behavior dataset.
- evaluation runners clear per-case state before execution.

## 6) Top observed architecture risks

1. Context influence over routing intent (documented by behavior sample case BEH-019).
2. Multi-step narrative conflict when support says approved but follow-up reasoning assumes declined context (BEH-008 style).
3. `issue_resolved` semantics can overstate resolution for generic guidance (e.g., settlement explanations).
4. Rule-based router scalability pressure as intent surface grows.

## 7) Recommended Priority 2 backlog

## Must

1. Add request correlation id and propagate through logs and response metadata.
2. Add per-step latency capture (router, orchestrator step, tool/agent total).
3. Add architecture-oriented tests for:
   - mixed intent precedence,
   - context contamination prevention,
   - multi-step consistency checks.
4. Tighten resolution semantics for support responses that are advisory but not case-closed.

## Should

1. Add a context gating rule before prepending full prior context to routing path.
2. Add trace metadata with `plan_steps`, `executed_steps`, and stop reason.
3. Add a deterministic "explanation code" taxonomy for routing reasons (stable keys, not only text).

## Could

1. Expand planning beyond one hardcoded follow-up edge (support -> knowledge).
2. Add confidence scoring for routing to trigger clarification instead of forced routing.

## 8) Interview-defense summary (short)

How to explain the architecture:
1. "We use a deterministic router for explainability and testability, then execute specialized agents through a bounded orchestrator plan."
2. "The system is multi-agent with explicit traces and limited sequencing; this was a deliberate tradeoff to prioritize reliability over unconstrained planning."
3. "We added behavior and semantic baselines to detect routing and quality regressions, and we explicitly track where context can distort intent routing."
4. "Priority 2 focuses on observability and correctness under mixed intent/context, not feature inflation."
