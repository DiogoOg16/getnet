# Response Contract

This document describes the response contract currently implemented by the API and validated by tests.

## 1. Goal

Separate three different concerns:

- execution lifecycle
- response delivery
- business resolution

The current review identified a semantic bug in the API contract: a single `resolved` field was being used for business resolution, flow completion, and orchestration stop conditions at the same time.

---

## 2. Public request/result fields

### `flow_completed: boolean`

Indicates whether the current request execution has ended.

Rules:
- `true` means the request lifecycle has reached a terminal state.
- It does not imply the customer issue was solved.
- A failed request can still have `flow_completed = true` when the request has clearly terminated.

Examples:
- a tool fails and the system ends with an explicit error response → `flow_completed = true`
- a request is paused waiting for required user input → `flow_completed = true`
- a request is still actively executing a later dependency → `flow_completed = false`

### `response_delivered: boolean`

Indicates whether a non-empty response was actually produced and included in the API payload.

Rules:
- `true` only when the API returned a response to the user.
- A failed or generic response may still be delivered.

### `issue_resolved: boolean`

Indicates whether there is sufficient evidence that the customer need was actually addressed.

Rules:
- This is a business-level result.
- It is not a control signal for the orchestrator.
- It must be based on observable evidence: tool result, retrieved content, final answer, and scenario-specific criteria.
- It must be `false` when the response is generic, requires missing data, is speculative, or still requires human intervention.

### `handoff_required: boolean`

Indicates whether human intervention is required.

Rules:
- Independent from `issue_resolved`.
- A handoff can occur even when the customer problem is not resolved by the system.

### `step_status: enum`

Allowed values:
- `success`
- `failed`
- `waiting_for_user_input`
- `waiting_for_dependency`
- `handoff`

Interpretation:
- This describes the execution state of the current step or final terminal state.
- It must be explicit and not inferred from `issue_resolved`.

### `awaiting_user_input: boolean`

Indicates that automation is suspended pending required information from the user.

Rules:
- `true` when the system is waiting for a required fact or credential to continue.
- `false` otherwise.

---

## 3. Invariants

The following invariants must hold:

- `flow_completed` may be `true` while `issue_resolved` is `false`
- `response_delivered` may be `true` while `issue_resolved` is `false`
- `handoff_required` may be `true` while `issue_resolved` is `false`
- `issue_resolved` must not be used as the sole stop condition for orchestration
- `step_status` is the operational truth; `issue_resolved` is the business truth

---

## 4. Explicit rule for failure

A terminal failure must still be represented as a completed request if the request lifecycle ended.

Correct representation:

```
{
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": false,
  "handoff_required": false,
  "step_status": "failed",
  "awaiting_user_input": false
}
```

This separates:
- end of execution (`flow_completed`)
- failure state (`step_status = "failed"`)
- unresolved business outcome (`issue_resolved = false`)

---

## 5. Explicit rule for waiting for user input

If the request has reached a valid termination point but requires more information, then:

```
{
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": false,
  "handoff_required": false,
  "step_status": "waiting_for_user_input",
  "awaiting_user_input": true
}
```

This covers scenarios such as:
- missing transaction ID
- missing device diagnostic detail
- missing supporting proof or data needed for the next step

---

## 6. Rule for per-stage vs per-request state

Each stage may maintain its own state:

- `stage_status`
- stage output
- dependencies pending
- tool execution result

The public response fields describe the consolidated request state, not the average of stage states.

Important rules:
- a successful intermediate step does not make an incomplete request fully resolved
- a final request can be unresolved even if one stage succeeded
- a request can be considered `flow_completed = true` while still requiring another action or user input

---

## 7. Compatibility contract for legacy `resolved`

The legacy field `resolved` is a compatibility concern. It should not be treated as a definitive business status.

### Recommended migration path

- Phase 1: keep `resolved` temporarily as a legacy alias for `issue_resolved`
- Phase 2: document it as deprecated and emit warnings in API usage
- Phase 3: remove it only after all clients and tests migrate to the explicit fields

### Compatibility rules

- `resolved` may remain temporarily for backward compatibility, but it must be documented as legacy
- `resolved` must never be used as a control signal in orchestration
- `issue_resolved` is the canonical field for business resolution semantics

### Legacy equivalence

```
legacy resolved == issue_resolved
```

This equivalence must be maintained only during the deprecation window.

---

## 8. Example JSON payloads

### Complete and grounded answer

```
{
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": true,
  "handoff_required": false,
  "step_status": "success",
  "awaiting_user_input": false
}
```

### Missing required information

```
{
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": false,
  "handoff_required": false,
  "step_status": "waiting_for_user_input",
  "awaiting_user_input": true
}
```

### Human handoff

```
{
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": false,
  "handoff_required": true,
  "step_status": "handoff",
  "awaiting_user_input": false
}
```

### Terminal failure

```
{
  "flow_completed": true,
  "response_delivered": true,
  "issue_resolved": false,
  "handoff_required": false,
  "step_status": "failed",
  "awaiting_user_input": false
}
```

---

## 9. Evidence-based resolution rule

`issue_resolved` must be based on observable evidence, not only the agent’s classification.

Minimum evidence should include:
- tool output that answers the request
- retrieved knowledge content or valid procedure
- final message delivered to the user
- scenario-appropriate verification criteria

Examples:
- transaction status answer requires real transaction lookup result
- settlement answer requires grounded receipt/liquidity information, not speculation
- device diagnosis must be backed by a valid diagnostic path or explicit data requirement
- generic suggestions without evidence must not become `issue_resolved = true`

---

## 10. Acceptance criterion summary

The implementation is acceptable only if it satisfies all of the following:

- `flow_completed` is explicitly separated from `issue_resolved`
- a failed but terminal request keeps `flow_completed = true` and `step_status = "failed"`
- waiting for data is represented as `waiting_for_user_input`
- public fields describe the request, while step state describes execution details
- `issue_resolved` is evidence-based, not agent-self-classified
- `resolved` is handled through a documented migration plan, not silently repurposed
