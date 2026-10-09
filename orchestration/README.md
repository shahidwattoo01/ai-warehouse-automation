# Orchestration (n8n)

- `n8n/workflows/` : the seven importable workflows WH-01 to WH-07 (orchestrator, agent supervisor, copilot,
  RAG ingestion, experiment runner, error handler, MLOps).
- `n8n/mock_backend/` : a mock of every endpoint the workflows call, so they can be tested before the real
  services exist. Replace endpoint by endpoint with the real routers in `src/warehouse_ai/api/routers`.
- `n8n/generator/` : the script that generates the workflow JSON (`build_flows.py`).

## Import (one workflow per import)

1. Create the credential *Warehouse API Key* (Header Auth, header `x-api-key`).
2. In n8n: Workflows, Create workflow, Import from file, pick one JSON, Save. Repeat for each file.
3. Set WH-06 as the Error Workflow of the others, then activate.

Or: `n8n import:workflow --separate --input=./n8n/workflows`
