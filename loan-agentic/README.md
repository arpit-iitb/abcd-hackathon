# Loan Agentic Hello Pipeline

Minimal repo scaffold with a placeholder pipeline that loads config and prompts, reads a sample from `data/`, and prints a stub JSON output.

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure OpenAI
Copy the env template and add your key:
```
copy .env.example .env
```
Edit `.env` and set:
```
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.2
OPENAI_TEMPERATURE=0.1
```

## Run CLI
```powershell
python -m app.run_pipeline --config-dir .\configs --prompt-dir .\prompts --sample-dir .\data
```

## Run Streamlit
```powershell
streamlit run .\streamlit_app.py
```

## Run Demo Dashboard
```powershell
streamlit run .\streamlit_demo.py
```

## Notes
- `.env` is ignored by git. Do not commit secrets.
- Aadhaar + selfie images are expected as PNG/JPG files under `data/images/` (see `data/images/README.txt`). Images are converted to compressed JPEG before sending to the LLM to reduce token size.
- Per-agent LLM model/temperature can be set in `configs/models.yaml`.
- LLM usage per agent is controlled in `configs/llm.yaml`. Set an agent to `false` to use rule-based fallbacks (useful for tests/offline runs).
- This is a hello pipeline stub; extend `app/graph.py` and `agents/` for full orchestration.
