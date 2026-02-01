from __future__ import annotations

from typing import Any, Dict, List

from app.llm_runner import run_llm_agent
from app.state import AgentResultBase, ErrorItem
from app.utils.masking import mask_sensitive
from app.utils.web_search import run_web_search


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
            },
        )
        return result.model_dump(mode="json")

    queries = _build_queries(str(name), str(city), str(employer))
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

    search_results = run_web_search(queries, web_cfg)
    llm_payload = {
        "lead": lead,
        "employer": employer,
        "queries": queries,
        "search_results": search_results,
    }

    llm_result = run_llm_agent("web_search", llm_payload, config, prompts)
    if isinstance(llm_result, dict) and llm_result.get("status") == "ok":
        return llm_result

    fallback = AgentResultBase(
        agent_name="web_search",
        status="insufficient_data",
        errors=[],
        missing_data=["web_search.summary"],
        rationale_summary=["Web search LLM summarization failed."],
        evidence=mask_sensitive({"search_results": search_results}),
        calculations={},
        confidence=0.2,
        output={},
    )
    return fallback.model_dump(mode="json")
