# Agentic Loan Journey (LangGraph)

Agentic loan journey system: lead sourcing → sales orchestration → fraud/risk/approval.

## Features
- LangGraph state graph with checkpointing for per-node state inspection
- Strict JSON IO per agent with Pydantic validation
- Structured JSON logs with run_id/thread_id
- Masking for Aadhaar/PAN in logs and evidence
- Explainability outputs without chain-of-thought
- Configurable thresholds and prompt templates (YAML)
- Streamlit demo UI

## Repo layout
```
app/                  Core pipeline + agents
configs/              Thresholds and required fields
prompts/              Agent prompts (YAML)
data/                 Dummy JSON samples
streamlit_app.py      Streamlit demo UI
```

## Run the CLI
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.run_pipeline --input .\data\sample_application.json
```

## Run the Streamlit demo
```powershell
streamlit run .\streamlit_app.py
```

## Inspect checkpoints
The pipeline uses a SQLite checkpoint store at `data/checkpoints.db` (configurable). Each node’s state is persisted for debugging.

## Configuration
- `configs/thresholds.yaml` controls risk thresholds, weights, and required fields
- `prompts/agents.yaml` stores prompt templates used by each agent

## Tests
```powershell
pytest -q
```
