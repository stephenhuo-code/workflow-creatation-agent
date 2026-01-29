"""
LangGraph 状态机定义（兼容层）
此文件保留用于向后兼容，实际实现已迁移到 graph/ 模块

已迁移至:
- graph/state.py - ConversationState 定义
- graph/nodes.py - 所有节点函数
- graph/builder.py - build_graph() 函数
"""

# 从新模块重新导出，保持向后兼容
from graph.state import ConversationState, get_initial_state
from graph.builder import build_graph, get_graph

__all__ = [
    "ConversationState",
    "get_initial_state",
    "build_graph",
    "get_graph"
]
