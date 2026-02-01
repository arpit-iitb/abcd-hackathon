from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.openai_client import get_openai_client


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    if not content:
        return None
    text = content.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except Exception:
            return None
    return None


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_sources(output_items: List[Any]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for item in output_items:
        if _get_attr(item, "type") != "web_search_call":
            continue
        action = _get_attr(item, "action", {}) or {}
        for source in action.get("sources", []) or []:
            if isinstance(source, dict):
                sources.append(
                    {
                        "title": source.get("title"),
                        "url": source.get("url"),
                    }
                )
    return sources


def _extract_queries(output_items: List[Any]) -> List[str]:
    queries: List[str] = []
    for item in output_items:
        if _get_attr(item, "type") != "web_search_call":
            continue
        action = _get_attr(item, "action", {}) or {}
        for query in action.get("queries", []) or []:
            if isinstance(query, str):
                queries.append(query)
    return queries


def run_openai_web_search(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    include_sources: bool = True,
) -> Dict[str, Any]:
    client = get_openai_client()
    include = ["web_search_call.action.sources"] if include_sources else []

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[{"type": "web_search"}],
        tool_choice={"type": "web_search"},
        text={"format": {"type": "json_object"}},
        temperature=float(temperature),
        include=include,
    )

    output_items = _get_attr(response, "output", []) or []
    output_text = _get_attr(response, "output_text", None)
    if not output_text:
        # Fallback: try to extract text from output items
        for item in output_items:
            if _get_attr(item, "type") == "message":
                content = _get_attr(item, "content", []) or []
                for part in content:
                    if _get_attr(part, "type") == "output_text":
                        output_text = _get_attr(part, "text")
                        break
            if output_text:
                break

    parsed = _extract_json(str(output_text) if output_text else "")
    sources = _extract_sources(output_items)
    queries = _extract_queries(output_items)

    return {
        "parsed": parsed,
        "output_text": output_text,
        "sources": sources,
        "queries": queries,
    }
