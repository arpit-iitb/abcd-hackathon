from typing import Any, Dict, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

from .agents import approval_agent, fraud_agent, lead_sourcing_agent, risk_agent, sales_agent


class LoanJourneyState(TypedDict):
    run_id: str
    thread_id: str
    input: Dict[str, Any]
    outputs: Dict[str, Any]
    errors: list


def build_graph(config: Dict[str, Any], prompts: Dict[str, Any], checkpointer: SqliteSaver):
    graph = StateGraph(LoanJourneyState)

    graph.add_node("lead_sourcing", lambda state: lead_sourcing_agent(state, config, prompts))
    graph.add_node("sales_agent", lambda state: sales_agent(state, config, prompts))
    graph.add_node("fraud_agent", lambda state: fraud_agent(state, config, prompts))
    graph.add_node("risk_agent", lambda state: risk_agent(state, config, prompts))
    graph.add_node("approval_agent", lambda state: approval_agent(state, config, prompts))

    graph.set_entry_point("lead_sourcing")
    graph.add_edge("lead_sourcing", "sales_agent")

    def sales_route(state: Dict[str, Any]) -> str:
        sales_output = state.get("outputs", {}).get("sales_agent", {})
        return "end" if sales_output.get("status") == "insufficient_data" else "fraud"

    def fraud_route(state: Dict[str, Any]) -> str:
        fraud_output = state.get("outputs", {}).get("fraud", {})
        return "end" if fraud_output.get("status") == "insufficient_data" else "risk"

    def risk_route(state: Dict[str, Any]) -> str:
        risk_output = state.get("outputs", {}).get("risk", {})
        return "end" if risk_output.get("status") == "insufficient_data" else "approval"

    graph.add_conditional_edges("sales_agent", sales_route, {"fraud": "fraud_agent", "end": END})
    graph.add_conditional_edges("fraud_agent", fraud_route, {"risk": "risk_agent", "end": END})
    graph.add_conditional_edges("risk_agent", risk_route, {"approval": "approval_agent", "end": END})
    graph.add_edge("approval_agent", END)

    return graph.compile(checkpointer=checkpointer)
