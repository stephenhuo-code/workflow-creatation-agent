"""
LangGraph 状态图构建器
构建完整的对话状态机

架构：
supervisor ─┬─→ workflow_skills (子图) ─┬─→ create_workflow (内部子图)
            │                           ├─→ delete_workflow
            │                           └─→ list_workflows
            ├─→ execute_workflow (子图) ─→ start → process_step (循环) → finalize → END
            └─→ general_chat
"""

from langgraph.graph import StateGraph, END

from .state import ConversationState
from .nodes import general_chat_node
from .subgraphs import build_workflow_skills_subgraph, build_workflow_execution_subgraph
from agents.supervisor import supervisor_node
from utils.logger import setup_logger

# 模块日志
logger = setup_logger("GraphBuilder")


def _get_route(state: ConversationState) -> str:
    """
    从 state 中获取路由目标
    用于 LangGraph conditional_edges
    """
    route = state.get("route", "general_chat")

    # 有效的路由目标
    valid_routes = {"workflow_skills", "execute_workflow", "general_chat"}

    # 如果路由值无效，降级到 general_chat
    if route not in valid_routes:
        logger.warning(f"无效路由 '{route}'，降级到 general_chat")
        route = "general_chat"

    logger.info(f"路由决策 | route={route}")
    return route


def build_graph() -> StateGraph:
    """
    构建 LangGraph 状态图

    简化后的架构：
    - supervisor: 主控 Agent，负责意图识别和路由
    - workflow_skills: 子图，处理工作流管理（创建/删除/查看）
    - execute_workflow: 执行匹配的工作流
    - general_chat: 通用对话
    """
    logger.info("构建主图")

    graph = StateGraph(ConversationState)

    # 添加节点
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("workflow_skills", build_workflow_skills_subgraph())
    graph.add_node("execute_workflow", build_workflow_execution_subgraph())
    graph.add_node("general_chat", general_chat_node)

    # 设置入口点
    graph.set_entry_point("supervisor")

    # Supervisor 路由
    graph.add_conditional_edges(
        "supervisor",
        _get_route,
        {
            "workflow_skills": "workflow_skills",
            "execute_workflow": "execute_workflow",
            "general_chat": "general_chat",
        }
    )

    # 所有节点完成后结束（等待下一次用户输入）
    graph.add_edge("workflow_skills", END)
    graph.add_edge("execute_workflow", END)
    graph.add_edge("general_chat", END)

    return graph.compile()


# 全局图实例
_graph = None


def get_graph(force_rebuild: bool = False):
    """
    获取全局图实例（单例模式）

    Args:
        force_rebuild: 是否强制重建图实例
    """
    global _graph
    if _graph is None or force_rebuild:
        _graph = build_graph()
    return _graph


def reset_graph():
    """重置图实例，下次调用 get_graph() 时会重建"""
    global _graph
    _graph = None
    logger.info("图实例已重置")
