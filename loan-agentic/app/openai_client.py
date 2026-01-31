from __future__ import annotations

import os
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

_CLIENTS = {}


def _require_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Copy .env.example to .env and set OPENAI_API_KEY=your_key_here."
        )
    return key


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def get_model_config() -> Dict[str, Any]:
    model = os.getenv("OPENAI_MODEL", "gpt-5.2")
    try:
        temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
    except ValueError:
        temperature = 0.1
    return {"model": model, "temperature": temperature}


def get_llm_client(model: str = None, temperature: float = None):
    api_key = _require_api_key()
    config = get_model_config()
    model_name = model or config["model"]
    temp_value = config["temperature"] if temperature is None else temperature
    key = (model_name, float(temp_value))
    if key in _CLIENTS:
        return _CLIENTS[key]

    from langchain_openai import ChatOpenAI

    client = ChatOpenAI(api_key=api_key, model=model_name, temperature=temp_value)
    _CLIENTS[key] = client
    return client
