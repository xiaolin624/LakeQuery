from langgraph.graph import END, StateGraph

from lakequery.agent.nodes import (
    check_golden_node,
    fix_sql_node,
    generate_sql_node,
    metadata_node,
    parse_intent_node,
    respond_node,
    search_schema_node,
    transpile_sql_node,
    validate_sql_node,
)
from lakequery.models.state import AgentState


def route_after_intent(state: AgentState) -> str:
    if state.status == "failed":
        return "respond"
    if state.intent and state.intent.get("ambiguous"):
        return "respond"
    if state.intent and state.intent.get("is_metadata_query"):
        return "metadata"
    return "check_golden"


def route_after_validation(state: AgentState) -> str:
    if not state.generated_sql.strip():
        return "respond"
    if state.validation_errors:
        return "fix_sql"
    return "transpile_sql"


def route_after_fix(state: AgentState) -> str:
    if state.retry_count >= state.max_retries:
        return "respond"
    return "generate_sql"


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_intent", parse_intent_node)
    workflow.add_node("metadata", metadata_node)
    workflow.add_node("check_golden", check_golden_node)
    workflow.add_node("search_schema", search_schema_node)
    workflow.add_node("generate_sql", generate_sql_node)
    workflow.add_node("validate_sql", validate_sql_node)
    workflow.add_node("fix_sql", fix_sql_node)
    workflow.add_node("transpile_sql", transpile_sql_node)
    workflow.add_node("respond", respond_node)

    workflow.set_entry_point("parse_intent")
    workflow.add_conditional_edges("parse_intent", route_after_intent, {
        "respond": "respond",
        "metadata": "metadata",
        "check_golden": "check_golden",
    })
    workflow.add_edge("metadata", "respond")
    workflow.add_edge("check_golden", "search_schema")
    workflow.add_edge("search_schema", "generate_sql")
    workflow.add_edge("generate_sql", "validate_sql")
    workflow.add_conditional_edges("validate_sql", route_after_validation, {
        "fix_sql": "fix_sql",
        "transpile_sql": "transpile_sql",
        "respond": "respond",
    })
    workflow.add_conditional_edges("fix_sql", route_after_fix, {
        "generate_sql": "generate_sql",
        "respond": "respond",
    })
    workflow.add_edge("transpile_sql", "respond")
    workflow.add_edge("respond", END)

    return workflow


graph = build_graph().compile()
