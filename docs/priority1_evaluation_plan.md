# Priority 1 — Evaluation and Behavior Audit (V1)

This document defines the behavior-first evaluation baseline requested before adding more features.

## Scope

Priority 1 focuses on:
- behavior and routing quality
- semantic grounding expectations
- memory/context impact on decisions
- out-of-domain and ambiguous request safety
- explicit limitation reporting

Out of scope for this phase:
- external human-support platform integration
- large-scale eval dataset (80+ cases)
- full production hardening

## Dataset

The first baseline dataset is versioned in:
- `eval/behavior_cases_v1.json`

Current size:
- 24 cases

Coverage categories:
- customer support routing
- knowledge routing
- web-search routing
- human escalation routing
- fallback behavior
- ambiguous requests
- out-of-domain requests
- unknown-knowledge requests
- contextualized memory behavior
- session isolation behavior
- cross-user authorization behavior
- context influence visibility on routing

## Automated checks

Behavior checks are automated in:
- `tests/test_behavior_evaluation.py`

What is validated automatically:
- expected HTTP status
- agent decision (`agent`)
- handoff requirement (`handoff_required`)
- execution status (`step_status` when expected)
- issue resolution contract (`issue_resolved` when expected)
- minimum source evidence (`sources` count when expected)
- trace depth for multi-step cases
- session memory isolation between parallel sessions
- cross-user access denial (`403`)

## Semantic quality method

For this baseline, semantic quality is assessed by combining:
- structural evidence checks (sources + section grouping)
- behavior checks per scenario
- manual reviewer judgment for factual accuracy and completeness

Reviewer rubric (manual):
1. **Grounding**: does the response stay aligned with retrieved sources?
2. **Factuality**: does the response avoid unsupported claims?
3. **Completeness**: does it answer the actual user intent?
4. **Safety**: does it avoid exposing other users or sensitive data?

Scoring suggestion (manual):
- 0 = failed
- 1 = partially acceptable
- 2 = acceptable

Per-case score range: 0 to 8.

## Before/after comparison template

Use the same dataset and method in future revisions.

| Metric | Baseline (V1) | Next revision |
|---|---:|---:|
| Routing correctness | _to fill from test run_ | _pending_ |
| Grounded responses (manual) | _to fill from review_ | _pending_ |
| Safe abstentions | _to fill from review_ | _pending_ |
| Cross-user isolation pass rate | _to fill from test run_ | _pending_ |
| Useful fallback when LLM unavailable | _to fill from test run_ | _pending_ |

## Known limitations (kept explicit)

1. Handoff is internally persisted and managed, but not integrated with an external customer-service platform.
2. Semantic quality still depends on human review; automated checks do not prove factual correctness alone.
3. Context can influence routing behavior when the same session includes prior intents, by design of contextual prompting.
4. The dataset is intentionally small in V1 for fast iteration and explainability.

## How to run this phase

Run only behavior-focused evaluation:

```bash
python -m pytest -q tests/test_behavior_evaluation.py
```

Generate reproducible baseline metrics snapshot:

```bash
python eval/run_behavior_baseline.py
```

Generated artifact:
- `eval/behavior_baseline_v1_results.json`

Generate semantic sample evidence for assisted review:

```bash
python eval/run_semantic_sample.py
```

Generated artifact:
- `eval/semantic_sample_v1_results.json`

Both runners explicitly clear session-scoped memory and handoff records for each evaluated case to reduce shared-state contamination outside pytest fixtures.

Then run full suite when needed:

```bash
python -m pytest -q
```
