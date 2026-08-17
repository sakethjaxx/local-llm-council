# Project Context — LLM Council

## Product

LLM Council helps a developer or researcher gather independent model analyses and a final chairman verdict. It supports attachments, project review, replay/export, local memory, and optional dynamic personas.

## Product principles

1. Local-first is the default experience and cost model.
2. Cloud models are optional and explicitly keyed by the user.
3. The UI should expose meaningful progress and failures instead of silently stopping.
4. Run history and memory must be useful without leaking secrets or unrelated context.
5. Hardware constraints are product behavior: model selection must fit concurrent local inference.

## Terminology

| Term | Meaning |
|---|---|
| Seat/member | A council persona and its configured model. |
| Chairman | The synthesizing model that emits verdict, risk score, actions, consensus, and disputes. |
| Deep Debate | Optional peer cross-review phase. |
| Dynamic Swarm | LLM-generated roster/persona configuration. |
| Historical memory | Relevance-filtered triples extracted from prior runs. |
| Skill | Reusable, confidence-scored guidance extracted from strong runs. |

## Non-goals

This project is not a hosted multi-tenant service, credential vault, general remote crawler, or autonomous code executor by default.

