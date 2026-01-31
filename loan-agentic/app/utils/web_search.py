from __future__ import annotations

from typing import Any, Dict, List


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


def get_web_search_tool(enabled: bool) -> WebSearchTool:
    return DisabledWebSearchTool()


def run_web_search(queries: List[str]) -> Dict[str, Any]:
    tool = get_web_search_tool(True)
    results = []
    for query in queries:
        results.append(tool.search(query))
    return {
        "enabled": True,
        "queries": queries,
        "provider": tool.provider_name,
        "results_summary": results,
    }
