# AI Warehouse Platform: n8n Orchestration (WH-01 to WH-07)

Seven importable n8n workflows that orchestrate the whole project map (simulator, ML, DL, CV, NLP, RAG,
tools, agents, optimization/RL, evaluation, monitoring), plus a mock backend and tests so you can run it
end to end before your real services exist.

**Key idea:** n8n is the *conductor*. All intelligence (models, planner, RAG, agents) lives in your FastAPI
backend. n8n handles triggers, sequencing, branching, retries, human approval, locking, alerting and scheduling.

---

## 1. The workflow set

| # | Workflow | Trigger | Purpose |
|---|---|---|---|
| WH-01 | Orchestrator (main loop) | timer 30 s, `POST /webhook/warehouse/new-order`, `POST /webhook/warehouse/run-cycle` | One full warehouse cycle: state, orders, ML, assignment, A*/Dijkstra, RL (optional), safety loop, simulate, vision (optional), update, evaluate, agent hand-off, persist, publish |
| WH-02 | Agent Supervisor | `POST /webhook/warehouse/agent-task` | Planner, specialist agents, policy gate, human approval, controlled tools, verify, commit or rollback, audit log |
| WH-03 | Operations Copilot | `POST /webhook/warehouse/copilot` | Guardrails, rate limit, NLP intent/entities, route to monitoring / investigation / RAG / what-if / action |
| WH-04 | RAG Ingestion | manual, nightly, `POST /webhook/warehouse/rag-ingest` | Extract, chunk, embed, vector DB, retrieval-quality gate |
| WH-05 | Experiment Runner | manual, `POST /webhook/warehouse/run-experiments` | The 7-experiment story (random to RL), same seed each mode, comparison report |
| WH-06 | Global Error Handler | any workflow failure | Force-release sim lock, record incident, page on-call |
| WH-07 | MLOps | every 5 min, weekly | Health / drift / fleet monitoring; weekly retrain with champion-vs-challenger promotion |

### How to read the canvas
See **WORKFLOW_MAPS.md** for a diagram of every workflow (renders in GitHub / VS Code / any Mermaid viewer). On the n8n canvas:
- Read **left to right**; nodes are numbered in execution order (`01`, `02`, ...).
- **Green** = trigger, **orange** = decision (IF / Switch: top output = true, bottom = false), **blue** = HTTP call to the backend or reply to the caller, **yellow** = safety guard, **grey** = code, **purple** = waits for a human, **red** = error trigger.
- Short grey captions under the main nodes say what each one does; the yellow sticky notes above each workflow give the overview.
- Rebuild the maps with `python3 make_maps.py`.

## 2. What changed compared with the first flow

| Gap found | Fix |
|---|---|
| No operator/Copilot entry point, no NLP | **WH-03** (webhook, guardrails, intent + entities, routing) |
| RAG had only a lookup node | **WH-04** full ingestion pipeline + quality gate; query-time RAG in WH-02 and WH-03 |
| No experiment switch | **Modes** (`random`, `heuristic`, `astar`, `ml`, `dynamic`, `agentic`, `rl`), each = previous + one capability, and **WH-05** to run them |
| RL was a hard dependency | RL is behind an IF and a **guard node**: if it fails, the cycle continues with `rl.status = degraded` |
| No human approval | Policy gate, then **Wait node** (30 min) with resume URL; timeout or denial executes nothing |
| No training / drift / offline work | **WH-07** (export dataset, retrain, compare, promote, drift alerts) |
| Overlapping runs could corrupt state | **Simulation lock** with TTL, released on success and force-released by WH-06 on crash |
| Infinite replan risk | Replan loop capped by a guard node (max 5) |
| No error handling / retries | Retries on all stage calls, `continueRegularOutput` on optional calls, global error workflow |
| Duplicate node names, mismatched ports | Unique numbered names; one backend gateway (matches your project map section 20) |
| Merge of 6 parallel agent branches | Replaced by a single specialist node with dynamic URL (see design notes) |

## 3. Setup (15 minutes)

1. **Run the mock backend** (optional but recommended for the first import):
   ```bash
   pip install fastapi uvicorn
   cd mock_backend && API_KEY=dev-key uvicorn mock_backend:app --port 8000
   ```
2. **Create one credential in n8n:** type *Header Auth*, name **Warehouse API Key**, header name `x-api-key`,
   value `dev-key` (use a real secret in production). It is used both for calls to your backend and for
   protecting the n8n webhooks.
3. **Point flows at your backend.** The default is `http://host.docker.internal:8000` (n8n in Docker, backend
   on the host). Change it either by editing `api_base` in the *Config / Build Run Context* Code node of each
   workflow, or by regenerating: `API_BASE=http://my-backend:8000 python3 build_flows.py`.
4. **Import** the 7 files from `flows/` (Workflows, Import from File).
5. **Link credentials.** If nodes show a credential warning, open one and select *Warehouse API Key*. To avoid
   this entirely, copy the credential ID from its URL (`/credentials/<id>`) and regenerate with
   `CRED_ID=<id> python3 build_flows.py`, then re-import.
6. **Set WH-06 as Error Workflow** in the Settings of WH-01 to WH-05 and WH-07.
7. **Activate** WH-02, WH-03, WH-04 (webhooks) first, then WH-01, WH-05, WH-07.
   Webhook URLs use `/webhook/...` when active (`/webhook-test/...` only while testing a single workflow).
   If n8n is not at `http://localhost:5678` for self-calls, regenerate with `N8N_BASE=...`.

### Try it
```bash
# operator question (WH-03)
curl -X POST localhost:5678/webhook/warehouse/copilot -H 'x-api-key: dev-key' -H 'Content-Type: application/json' \
     -d '{"message":"What should happen when a robot battery is below the critical threshold?","operator_id":"shahid"}'

# new order (WH-01)
curl -X POST localhost:5678/webhook/warehouse/new-order -H 'x-api-key: dev-key' -H 'Content-Type: application/json' \
     -d '{"order_id":"O-1001","items":[{"product_id":"P-7","quantity":2}],"priority":"high"}'

# a command that changes the warehouse -> agent task -> approval (WH-03 -> WH-02)
curl -X POST localhost:5678/webhook/warehouse/copilot -H 'x-api-key: dev-key' -H 'Content-Type: application/json' \
     -d '{"message":"Pause Robot 7","operator_id":"shahid"}'
# the mock backend prints the curl command to approve it

# experiments (WH-05): 3 modes x 20 cycles
curl -X POST localhost:5678/webhook/warehouse/run-experiments -H 'x-api-key: dev-key' -H 'Content-Type: application/json' \
     -d '{"modes":["random","astar","ml"],"cycles_per_mode":20,"seed":42}'
```

## 4. Backend contract (what your FastAPI must implement)

**Pipeline stages** (WH-01): `POST` body `{run_id, mode, features, trigger, context}` and return `{"context": {...}}`
with the stage's output added under its own key (`forecast`, `eta`, `anomaly`, `assignment`, `routes`, `safety`,
`execution`, `vision`, `evaluation`, ...). Stages must be **idempotent per `run_id`** because n8n retries them.

`features` is derived from the mode, so your services never need to know experiment names:

| mode | assignment | path_algo | predictions | replanning | vision | agents | RL |
|---|---|---|---|---|---|---|---|
| random | random | dijkstra | no | no | no | no | no |
| heuristic | nearest | dijkstra | no | no | no | no | no |
| astar | nearest | astar | no | no | no | no | no |
| ml | ml_eta | astar | yes | no | no | no | no |
| dynamic | ml_eta | astar | yes | yes | yes | no | no |
| agentic | ml_eta | astar | yes | yes | yes | yes | no |
| rl | ml_eta | astar | yes | yes | yes | yes | yes |

Endpoints by router (65 in total; `mock_backend/mock_backend.py` implements every one with the exact shapes):

- **simulation:** `/simulation/lock|unlock|state|step|state/update|reset`, `/orders/process`, `/events/analyze|collect`
- **ml:** `/prediction/forecast|eta|anomaly`, `/training/dataset|retrain|compare`, `/models/promote`
- **optimization / navigation / safety:** `/optimization/assign|what-if`, `/navigation/plan|replan`, `/rl/coordinate`, `/safety/check`
- **vision:** `/vision/perceive`
- **nlp / copilot:** `/nlp/parse`, `/copilot/rate-limit|monitor|investigate|log`
- **rag:** `/rag/query|answer|documents/pending|extract|chunk|embed|upsert|documents/mark-indexed|evaluate`
- **agents / tools:** `/agents/planner|fleet|inventory|navigation|maintenance|vision|knowledge|monitor|tasks/result`,
  `/tools/policy-check|execute|verify|commit|rollback`, `/approvals/request`
- **evaluation / ops:** `/evaluation/cycle|collect|report`, `/experiments/create`, `/database/persist-cycle`,
  `/dashboard/publish`, `/monitoring/heartbeat|event|alert|incident|model-health|fleet-health`, `/health`

Special rules:
- `/simulation/lock` receives `trigger_type`; while an experiment is active it must refuse `schedule` ticks
  (`{acquired:false}`). `/evaluation/report` should end the experiment (mock does this).
- `/agents/<name>` returns `{result, proposed_actions:[{tool,args}], sources?}`. Agents only **propose**.
- `/tools/policy-check` returns `{allowed_actions, blocked_actions, requires_approval, risk_level, reasons}`.
- `/tools/execute` must honour `idempotency_key`. `/tools/verify` returns `{verified}`.
- `/approvals/request` receives `resume_url`. Your dashboard approves with
  `POST <resume_url>` `{"approved": true, "approved_by": "<user>"}`.

## 5. Coverage of your project map

| Project layer | Where |
|---|---|
| 1 Data engineering | WH-07 B1 (dataset export), backend `/database/persist-cycle`, WH-05 seeded scenarios |
| 2 Simulator (single source of truth) | WH-01 lock, state, step, update, WH-05 reset |
| 3 Classical ML | WH-01 04-06 (demand, ETA, anomaly), WH-07 retraining |
| 4 Deep learning | Same endpoints; `/training/compare` benchmarks RF vs MLP vs LSTM/Transformer as champion vs challenger |
| 5 Computer vision | WH-01 12 (optional stage) |
| 6 NLP + Transformers | WH-03 `/nlp/parse` (intent + entities), guardrails |
| 7 RAG | WH-04 ingestion + quality gate; WH-03 and WH-02 query with citations |
| 8 Tool calling | WH-02 policy gate, controlled executor, verify, commit or rollback |
| 9 Agents / multi-agent | WH-02 planner + fleet, inventory, navigation, maintenance, vision, knowledge |
| 10 Optimization + RL | WH-01 07-09 (assignment, A*/Dijkstra, optional RL) |
| Evaluation | WH-01 15 (per cycle), WH-05 (experiments, tables/graphs), WH-04 RAG metrics |
| Production / monitoring | WH-06 errors, WH-07 health + drift + retraining |
| Core vs advanced | Core works with mode `ml`; RL, multi-agent and vision are switchable extras |

## 6. Design notes (why it is built this way)

- **One backend gateway, not 8 ports.** Matches section 20 of your map (`/robots /orders /prediction ...`).
- **n8n never touches the database.** The backend owns writes, so the LLM and n8n cannot bypass validation.
- **Optional stages degrade instead of failing** (RL, vision, dashboard, heartbeat).
- **One specialist node instead of a 6-way fan-out.** In n8n, a normal node that receives several parallel
  branches runs once *per branch*. That would have run the policy gate and the approval repeatedly. A single
  dynamic-URL node keeps exactly one downstream execution.
- **Agent hand-off is asynchronous.** WH-01 dispatches to WH-02 and continues, so a slow LLM or a 30-minute
  approval never blocks the simulation tick. Tools must check `state_version` (optimistic concurrency).
- **Copilot never executes actions.** Read-only questions are answered directly; anything that changes the
  warehouse becomes an agent task with policy, approval and verification.
- **Experiments are comparable.** Same seed, same scenario, cycles run sequentially through WH-01.

## 7. Tests included

```bash
python3 build_flows.py                                              # builds + validates graph structure
node tests/check_js.js                                              # syntax-checks all Code nodes + expressions
cd mock_backend && uvicorn mock_backend:app --port 8000 &           # then, from repo root:
python3 tests/endpoint_check.py                                     # every endpoint the flows call exists
API_BASE=http://localhost:8000 OUT=flows_test python3 build_flows.py
node tests/sim_n8n.js flows_test                                    # executes all 7 workflows against the mock
```
`sim_n8n.js` is a small executor that models n8n semantics (per-branch execution, IF/Switch routing, batch loops,
expressions, webhook-to-webhook calls, Wait auto-approve). 40+ assertions cover all 7 modes, order validation,
lock contention, approval flow, guardrails, RAG, the experiment loop, error handling and retraining.

**Honest limits:** these tests run against the mock and a simulator of n8n behaviour, not a live n8n instance.
Node parameters follow current n8n node versions, but if your n8n build flags a node on import, tell me the
node and version and I will adjust the generator.

## 8. Going to production

- Replace the mock endpoint by endpoint with real routers; keep the contract and the flows do not change.
- Use n8n **queue mode** with Redis and workers; raise `N8N_CONCURRENCY_PRODUCTION_LIMIT` so the 30 s tick,
  Copilot requests and approvals do not starve each other. Keep WH-01 `executionTimeout` (180 s) below the tick
  interval times a safe multiple, or lengthen the interval.
- Keep robot *real-time control* (collision avoidance in the loop) in the backend/simulator. n8n is for
  orchestration at second-to-minute granularity, not millisecond control.
- Store secrets only in n8n credentials; rotate the API key; put n8n and the backend behind TLS.
- Keep `saveDataSuccessExecution: none` on the tick workflow (already set) so execution history does not
  explode; the backend keeps the durable record.
- Back up workflows via the generator (they are code) and keep the JSON in Git.
