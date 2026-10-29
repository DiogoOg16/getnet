# Orchestrator Transitions

This document describes the orchestration lifecycle currently implemented and tested, focusing on execution state, business result, and the separation between those concepts.

## 1. Core principle

The orchestrator must not decide whether to continue or stop based solely on `issue_resolved`.

The orchestration state machine is driven by:
- current plan
- current stage
- dependencies
- recovery rules
- handoff rules
- user input requirements

`issue_resolved` is a business outcome, not a universal control signal.

---

## 2. State model

Each stage may be in one of the following states:

- `success`
- `failed`
- `waiting_for_user_input`
- `waiting_for_dependency`
- `handoff`

The consolidated request state may be represented as:

- `flow_completed: boolean`
- `response_delivered: boolean`
- `issue_resolved: boolean`
- `handoff_required: boolean`
- `awaiting_user_input: boolean`
- `step_status: enum`

Important: `step_status` must clearly indicate whether it refers to the last executed step or to the final state of the request.

The specification requires that each stage keep its own status, while the public result describes the request as a whole.

---

## 3. Transition rules

### 3.1 Success -> continue

When a stage succeeds and another valid stage remains in the plan:

- `step_status = "success"`
- orchestration continues
- `issue_resolved` is not assumed true merely because a stage succeeded

### 3.2 Success -> stop

When a stage succeeds and the plan has no further valid stage:

- `flow_completed = true`
- `response_delivered = true`
- orchestrator stops
- `issue_resolved` is evaluated from final business evidence

### 3.3 Waiting for user input

When a stage requires missing data:

- `step_status = "waiting_for_user_input"`
- `awaiting_user_input = true`
- `flow_completed = true` if the request has reached a valid terminal state
- automatic continuation is suspended until input arrives

### 3.4 Failure with recovery

When a stage fails and a recovery path exists:

- `step_status = "failed"`
- `flow_completed` may be `true` if the request is terminally handled
- orchestrator triggers explicit recovery logic
- no implicit assumption of resolution

### 3.5 Failure without recovery

When a stage fails and there is no valid recovery path:

- `step_status = "failed"`
- `flow_completed = true` if the request attempted completion and ended terminally
- `issue_resolved = false`
- orchestrator stops or escalates

### 3.6 Handoff

When the workflow determines that the case requires human intervention:

- `step_status = "handoff"`
- `handoff_required = true`
- `issue_resolved = false`
- orchestration stops for automation

---

## 4. Terminal state definition

A request is terminal when:
- there are no further valid execution steps
- required data is missing and the system is intentionally pausing
- a handoff has been created
- a terminal failure has been handled

This means that `flow_completed = true` is allowed in states where business resolution is not achieved.

---

## 5. Important separation

The following must remain separate:

- execution completion
- response production
- resolution of customer need
- human escalation

The orchestrator decision must be based on a state machine, not on the single boolean `issue_resolved`.

---

## 6. Legacy `resolved` compatibility note

The legacy field `resolved` must be treated as a compatibility alias during migration. It must not be used to decide orchestration behavior.

Recommended migration:
- keep it temporarily
- map it to `issue_resolved`
- mark it deprecated in documentation
- remove it after client migration

---

## 7. Acceptance rules for orchestration

The orchestrator passes review only if it satisfies these conditions:

- explicit step state is produced for each stage
- orchestrator continues only when the plan requires it
- waiting for user input suspends automation
- failed terminal states preserve `flow_completed = true`
- human handoff stops automation
- no stage success is automatically treated as customer resolution
