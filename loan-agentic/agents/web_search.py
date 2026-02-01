from __future__ import annotations

import json
from typing import Any, Dict, List

from app.llm_runner import resolve_model_config
from app.prompt_loader import render_prompt
from app.state import AgentResultBase, ErrorItem
from app.utils.masking import mask_sensitive
from app.utils.web_search import run_openai_web_search


def _build_queries(name: str, city: str, company: str) -> List[str]:
    queries = []
    if name and city:
        queries.append(f"\"{name}\" {city}")
    if name and company:
        queries.append(f"\"{name}\" \"{company}\"")
    if company and city:
        queries.append(f"\"{company}\" {city}")
    if company:
        queries.append(f"\"{company}\" company profile")
    return queries


def _serialize(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=True)


def run_web_search_agent(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    web_cfg = config.get("web_search") or {}
    enabled = bool(web_cfg.get("enabled", False))

    lead = payload.get("lead", {}) if isinstance(payload, dict) else {}
    employer = payload.get("employer") or ""
    name = lead.get("name") or ""
    city = lead.get("city") or ""

    if not enabled:
        result = AgentResultBase(
            agent_name="web_search",
            status="ok",
            errors=[],
            missing_data=[],
            rationale_summary=["Web search disabled by config."],
            evidence=mask_sensitive({"lead": lead, "employer": employer}),
            calculations={},
            confidence=0.0,
            output={
                "summary": "Web search disabled.",
                "applicant_profile": "Not searched (disabled).",
                "employer_profile": "Not searched (disabled).",
                "confidence_applicant": "low",
                "confidence_employer": "low",
                "sources": [],
            },
        )
        return result.model_dump(mode="json")

    queries = _build_queries(str(name), str(city), str(employer))
    max_queries = int(web_cfg.get("max_queries", len(queries) or 0))
    if max_queries and len(queries) > max_queries:
        queries = queries[:max_queries]
    if not queries:
        result = AgentResultBase(
            agent_name="web_search",
            status="insufficient_data",
            errors=[],
            missing_data=["lead.name", "lead.city", "employer_name"],
            rationale_summary=["Missing lead/employer fields to perform web search."],
            evidence=mask_sensitive({"lead": lead, "employer": employer}),
            calculations={},
            confidence=0.2,
            output={},
        )
        return result.model_dump(mode="json")

    llm_payload = {
        "lead": lead,
        "employer": employer,
        "queries": queries,
    }

    system_prompt, user_prompt = render_prompt(
        prompts,
        "web_search",
        input_json=_serialize(llm_payload),
        config_json=_serialize(config),
    )
    model_cfg = resolve_model_config(config, "web_search")
    include_sources = bool(web_cfg.get("include_sources", True))

    try:
        response = run_openai_web_search(
            system_prompt,
            user_prompt,
            model=model_cfg.get("model", "gpt-5.2"),
            temperature=float(model_cfg.get("temperature", 0.1)),
            include_sources=include_sources,
        )
    except Exception as exc:
        error = ErrorItem(
            code="web_search_runtime_error",
            message=str(exc),
            where="web_search_call",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="web_search",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Web search call failed."],
            evidence=mask_sensitive({"lead": lead, "employer": employer, "queries": queries}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    parsed = response.get("parsed")
    sources = response.get("sources", []) or []
    queries_used = response.get("queries", []) or []
    if not parsed:
        error = ErrorItem(
            code="web_search_parse_error",
            message="Failed to parse JSON output from web search LLM.",
            where="web_search_response",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="web_search",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Web search LLM output was not valid JSON."],
            evidence=mask_sensitive({"queries": queries, "queries_used": queries_used, "sources": sources}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    parsed["agent_name"] = "web_search"
    output = parsed.get("output", {})
    if isinstance(output, dict):
        if sources and not output.get("sources"):
            output["sources"] = sources
        if queries_used and not output.get("queries_used"):
            output["queries_used"] = queries_used
        parsed["output"] = output

    try:
        validated = AgentResultBase.model_validate(parsed)
        return validated.model_dump(mode="json")
    except Exception as exc:
        error = ErrorItem(
            code="web_search_validation_error",
            message=str(exc),
            where="web_search_response",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="web_search",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Web search LLM output failed schema validation."],
            evidence=mask_sensitive({"queries": queries, "queries_used": queries_used, "sources": sources}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")
