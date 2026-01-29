"""
LangGraph 节点函数
包含通用对话的节点实现

注意：
- 工作流创建相关节点已迁移到 graph/subgraphs/workflow_skills.py
- 工作流执行相关节点已迁移到 graph/subgraphs/workflow_execution.py
"""

import os

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from schemas import WorkflowCollection
from .state import ConversationState
from utils.logger import setup_logger

# 模块日志
logger = setup_logger("GraphNodes")


# ============================================================
# LLM 配置
# ============================================================

def get_llm():
    """获取 Claude LLM 实例"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 ANTHROPIC_API_KEY")
    return ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=api_key,
        max_tokens=4096
    )


# ============================================================
# 节点函数
# ============================================================

def general_chat_node(state: ConversationState) -> dict:
    """普通对话节点"""
    logger.info("▶ 节点: general_chat | 通用对话")
    llm = get_llm()
    collection = WorkflowCollection(**state["workflow_collection"])

    workflow_list = collection.list_workflows()
    wf_text = "\n".join(f"- {wf['name']}: {wf['triggers']}" for wf in workflow_list) if workflow_list else "（暂无）"

    system_prompt = f"""你是一个智能工作流助手。

## 能力
1. 创建工作流：用户说"我要创建XX流程"
2. 执行工作流：用户输入匹配触发词时执行
3. 查看工作流：用户说"查看所有流程"

## 已有工作流
{wf_text}

请简洁友好地回复用户。"""

    history = []
    for msg in state["messages"][-10:]:
        if isinstance(msg, HumanMessage):
            history.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            history.append(AIMessage(content=msg.content))

    response = llm.invoke([SystemMessage(content=system_prompt)] + history)

    logger.info("◀ 节点: general_chat | 完成")
    return {"messages": [AIMessage(content=response.content)]}
