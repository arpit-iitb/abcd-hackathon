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


def _normalize_text(text: str) -> str:
    return (text or "").lower()


def _extract_results(search_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    results_summary = search_results.get("results_summary", [])
    all_results: List[Dict[str, Any]] = []
    if isinstance(results_summary, list):
        for item in results_summary:
            if not isinstance(item, dict):
                continue
            for result in item.get("results", []) or []:
                if isinstance(result, dict):
                    all_results.append(result)
    return all_results


def _summarize_results(
    results: List[Dict[str, Any]],
    name: str,
    city: str,
    employer: str,
) -> Dict[str, Any]:
    name_norm = _normalize_text(name)
    city_norm = _normalize_text(city)
    employer_norm = _normalize_text(employer)

    applicant_hits: List[Dict[str, Any]] = []
    employer_hits: List[Dict[str, Any]] = []

    for item in results:
        title = _normalize_text(item.get("title", ""))
        snippet = _normalize_text(item.get("snippet", ""))
        combined = f"{title} {snippet}"
        if name_norm and name_norm in combined:
            applicant_hits.append(item)
        if employer_norm and employer_norm in combined:
            employer_hits.append(item)

    def _top_titles(items: List[Dict[str, Any]], limit: int = 2) -> List[str]:
        titles = []
        for item in items[:limit]:
            title = item.get("title") or ""
            if title:
                titles.append(title)
        return titles

    applicant_titles = _top_titles(applicant_hits)
    employer_titles = _top_titles(employer_hits)

    applicant_conf = "low"
    employer_conf = "low"
    if len(applicant_hits) >= 2:
        applicant_conf = "medium"
    if len(employer_hits) >= 2:
        employer_conf = "medium"
    if name_norm and employer_norm:
        for item in applicant_hits:
            combined = _normalize_text(f"{item.get('title','')} {item.get('snippet','')}")
            if employer_norm in combined:
                applicant_conf = "high"
                break
    if employer_norm and (employer_norm in " ".join(_normalize_text(t) for t in employer_titles)):
        employer_conf = "medium"

    applicant_summary = "No clear applicant-specific results found."
    if applicant_titles:
        applicant_summary = f"Top applicant-related results: {', '.join(applicant_titles)}."

    employer_summary = "No clear employer-specific results found."
    if employer_titles:
        employer_summary = f"Top employer-related results: {', '.join(employer_titles)}."

    summary_parts = []
    if applicant_titles:
        summary_parts.append(f"Applicant: {applicant_titles[0]}")
    else:
        summary_parts.append("Applicant: no clear matches")
    if employer_titles:
        summary_parts.append(f"Employer: {employer_titles[0]}")
    else:
        summary_parts.append("Employer: no clear matches")

    summary = "; ".join(summary_parts)
    if city_norm and name_norm and applicant_hits:
        summary = f"{summary} (city query matched: {city})."

    confidence_score = 0.2
    if applicant_hits or employer_hits:
        confidence_score = 0.4
    if applicant_conf == "high" or employer_conf == "high":
        confidence_score = 0.6

    return {
        "summary": summary,
        "applicant_profile": applicant_summary,
        "employer_profile": employer_summary,
        "confidence_applicant": applicant_conf,
        "confidence_employer": employer_conf,
        "confidence_score": confidence_score,
    }


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
    results_summary = search_results.get("results_summary", [])
    provider_errors = []
    has_any_results = False
    if isinstance(results_summary, list):
        for item in results_summary:
            if not isinstance(item, dict):
                continue
            if item.get("error"):
                provider_errors.append(str(item.get("error")))
            if item.get("results"):
                has_any_results = True

    if provider_errors and not has_any_results:
        result = AgentResultBase(
            agent_name="web_search",
            status="ok",
            errors=[],
            missing_data=[],
            rationale_summary=["Web search provider unavailable; returning low-confidence placeholder summary."],
            evidence=mask_sensitive({"search_results": search_results}),
            calculations={},
            confidence=0.1,
            output={
                "summary": "Web search provider unavailable. No reliable applicant or employer profile found.",
                "applicant_profile": "Inconclusive (provider unavailable).",
                "employer_profile": "Inconclusive (provider unavailable).",
                "confidence_applicant": "low",
                "confidence_employer": "low",
            },
        )
        return result.model_dump(mode="json")

    if not has_any_results:
        result = AgentResultBase(
            agent_name="web_search",
            status="ok",
            errors=[],
            missing_data=[],
            rationale_summary=["Web search returned no results for applicant/employer queries."],
            evidence=mask_sensitive({"search_results": search_results}),
            calculations={},
            confidence=0.2,
            output={
                "summary": "No web search results found for the applicant or employer.",
                "applicant_profile": "No results found.",
                "employer_profile": "No results found.",
                "confidence_applicant": "low",
                "confidence_employer": "low",
            },
        )
        return result.model_dump(mode="json")
    llm_payload = {
        "lead": lead,
        "employer": employer,
        "queries": queries,
        "search_results": search_results,
    }

    llm_result = run_llm_agent("web_search", llm_payload, config, prompts)
    if isinstance(llm_result, dict) and llm_result.get("status") == "ok":
        return llm_result

    results = _extract_results(search_results)
    fallback_summary = _summarize_results(results, str(name), str(city), str(employer))
    error_note = None
    if isinstance(llm_result, dict):
        errors = llm_result.get("errors", [])
        if errors:
            error_note = errors[0].get("message") if isinstance(errors[0], dict) else None

    warning = ErrorItem(
        code="llm_fallback",
        message="LLM summarization failed; using rule-based summary."
        + (f" ({error_note})" if error_note else ""),
        where="web_search.llm_summary",
        severity="warning",
    )

    fallback = AgentResultBase(
        agent_name="web_search",
        status="ok",
        errors=[warning],
        missing_data=[],
        rationale_summary=["LLM summarization failed; used rule-based summary from search results."],
        evidence=mask_sensitive({"search_results": search_results}),
        calculations={},
        confidence=float(fallback_summary.get("confidence_score", 0.3)),
        output={
            "summary": fallback_summary.get("summary"),
            "applicant_profile": fallback_summary.get("applicant_profile"),
            "employer_profile": fallback_summary.get("employer_profile"),
            "confidence_applicant": fallback_summary.get("confidence_applicant"),
            "confidence_employer": fallback_summary.get("confidence_employer"),
        },
    )
    return fallback.model_dump(mode="json")
