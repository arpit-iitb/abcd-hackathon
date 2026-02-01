from __future__ import annotations

from typing import Any, Dict, List, Optional


class WebSearchTool:
    provider_name = "base"

    def search(self, query: str) -> Dict[str, Any]:
        raise NotImplementedError


class DisabledWebSearchTool(WebSearchTool):
    provider_name = "disabled"

    def search(self, query: str) -> Dict[str, Any]:
        return {
            "query": query,
            "results_summary": "web_search_disabled_provider",
        }


class DuckDuckGoSearchTool(WebSearchTool):
    provider_name = "duckduckgo"

    def __init__(self, max_results: int = 5, timeout_sec: int = 8):
        self.max_results = max_results
        self.timeout_sec = timeout_sec

    def search(self, query: str) -> Dict[str, Any]:
        try:
            from duckduckgo_search import DDGS
        except Exception as exc:
            return {"query": query, "error": f"duckduckgo_search_not_available: {exc}", "results": []}

        results: List[Dict[str, Any]] = []
        try:
            with DDGS() as ddgs:
                for item in ddgs.text(query, max_results=self.max_results):
                    results.append(
                        {
                            "title": item.get("title"),
                            "snippet": item.get("body"),
                            "url": item.get("href"),
                        }
                    )
        except Exception as exc:
            return {"query": query, "error": str(exc), "results": []}
        return {"query": query, "results": results}


def get_web_search_tool(enabled: bool, provider: str = "disabled", max_results: int = 5, timeout_sec: int = 8) -> WebSearchTool:
    if not enabled:
        return DisabledWebSearchTool()
    if provider == "duckduckgo":
        return DuckDuckGoSearchTool(max_results=max_results, timeout_sec=timeout_sec)
    return DisabledWebSearchTool()


def run_web_search(queries: List[str], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    config = config or {}
    enabled = bool(config.get("enabled", False))
    provider = str(config.get("provider", "disabled"))
    max_results = int(config.get("max_results", 5))
    max_queries = int(config.get("max_queries", len(queries)))
    timeout_sec = int(config.get("timeout_sec", 8))
    tool = get_web_search_tool(enabled, provider=provider, max_results=max_results, timeout_sec=timeout_sec)
    results = []
    for query in queries[:max_queries]:
        results.append(tool.search(query))
    return {
        "enabled": enabled,
        "queries": queries[:max_queries],
        "provider": tool.provider_name,
        "results_summary": results,
    }
