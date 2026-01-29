"""
Supervisor Agent（主控 Agent）
负责识别用户意图并决定处理方式

简化后的架构：只负责三路分发
- workflow_skills: 工作流管理（创建/删除/查看）
- execute_workflow: 执行已有工作流
- general_chat: 通用对话
"""

import os
import json
import re
from enum import Enum
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from schemas import WorkflowCollection
from utils.logger import setup_logger

# 模块日志
logger = setup_logger("SupervisorAgent")

if TYPE_CHECKING:
    from graph.state import ConversationState


# ============================================================
# 类型定义
# ============================================================

class IntentType(str, Enum):
    """意图类型"""
    WORKFLOW_MANAGEMENT = "workflow_management"  # 工作流管理操作
    SKILL_EXECUTION = "skill_execution"          # 执行已有 skill
    GENERAL_CHAT = "general_chat"                # 通用对话


class SupervisorResult(BaseModel):
    """Supervisor Agent 返回结果"""
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    matched_workflow_id: Optional[str] = None    # 匹配到的 workflow ID
    reasoning: str = ""


# ============================================================
# LLM 配置（本地定义避免循环导入）
# ============================================================

def _get_llm():
    """获取 Claude LLM 实例"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 ANTHROPIC_API_KEY")
    return ChatAnthropic(
        model="claude-sonnet-4-20250514",
        anthropic_api_key=api_key,
        max_tokens=4096
    )


def _get_last_user_message(state: dict) -> str:
    """获取最后一条用户消息"""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


# ============================================================
# Prompt 模板
# ============================================================

SUPERVISOR_AGENT_PROMPT = """你是 Supervisor Agent，负责识别用户意图并决定处理方式。

## 意图类型

1. **workflow_management** - 用户想管理工作流本身
   - 创建新工作流："创建一个XX流程"、"搭建工作流"、"新建流程"
   - 删除工作流："删除XX流程"、"移除工作流"
   - 查看工作流："有哪些流程"、"列出工作流"、"查看所有流程"

2. **skill_execution** - 用户想执行某个已有的工作流技能
   - 用户输入匹配某个工作流的触发短语
   - 用户明确请求执行某个已定义的任务
   - 示例：如果有"周报"工作流，用户说"帮我写周报"
   - 注意：必须是明确的执行请求，不是随便提到

3. **general_chat** - 普通对话，不涉及工作流
   - 闲聊、问答、写代码等
   - 只是提到某个词但不是请求执行
   - "周报太长了" → general_chat（评论而非请求）

## 已有工作流（可执行的 Skills）
{workflow_list}

## 输出格式（严格 JSON）
{{"intent": "workflow_management/skill_execution/general_chat", "confidence": 0.0-1.0, "matched_workflow_id": "ID或null", "reasoning": "说明"}}

## 判断优先级
1. 先判断是否为工作流管理操作（创建/删除/查看）
2. 再判断是否匹配已有 skill
3. 都不是则为 general_chat
"""


# ============================================================
# 辅助函数
# ============================================================

def _format_workflow_list(collection: WorkflowCollection) -> str:
    """格式化工作流列表供 prompt 使用"""
    workflows = collection.list_workflows()
    if not workflows:
        return "（暂无工作流）"

    lines = []
    for wf in workflows:
        triggers = ', '.join(f'"{t}"' for t in wf['triggers'])
        lines.append(f"- {wf['name']} (ID: {wf['id']}) - 触发词: {triggers}")
    return '\n'.join(lines)


def _exact_trigger_match(collection: WorkflowCollection, user_input: str) -> Optional[str]:
    """精确触发词匹配，返回匹配的 workflow_id"""
    user_input_lower = user_input.lower().strip()
    for workflow in collection.workflows.values():
        for phrase in workflow.trigger_phrases:
            phrase_lower = phrase.lower()
            # 完全匹配
            if user_input_lower == phrase_lower:
                return workflow.workflow_id
            # 以触发词开头
            if user_input_lower.startswith(phrase_lower + " "):
                return workflow.workflow_id
            # 触发词包含在输入中（原有逻辑）
            if phrase_lower in user_input_lower:
                return workflow.workflow_id
    return None


def _parse_supervisor_result(content: str) -> SupervisorResult:
    """解析 Supervisor Agent 返回"""
    # 处理 markdown 代码块包裹
    if "```" in content:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if match:
            content = match.group(1)

    try:
        data = json.loads(content.strip())
        return SupervisorResult(
            intent=IntentType(data.get("intent", "general_chat")),
            confidence=float(data.get("confidence", 0.5)),
            matched_workflow_id=data.get("matched_workflow_id"),
            reasoning=data.get("reasoning", "")
        )
    except (json.JSONDecodeError, ValueError) as e:
        # 解析失败，返回默认
        logger.warning(f"JSON 解析失败: {e}，降级到通用对话")
        return SupervisorResult(
            intent=IntentType.GENERAL_CHAT,
            confidence=0.5,
            reasoning="JSON 解析失败，降级到通用对话"
        )


def _supervisor_classify(user_input: str, collection: WorkflowCollection) -> SupervisorResult:
    """Supervisor Agent LLM 分类"""
    llm = _get_llm()
    workflow_list = _format_workflow_list(collection)
    prompt = SUPERVISOR_AGENT_PROMPT.format(workflow_list=workflow_list)

    response = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"用户输入：{user_input}")
    ])

    return _parse_supervisor_result(response.content)


# ============================================================
# Supervisor Agent 主函数
# ============================================================

def supervisor_agent(state: dict) -> dict:
    """
    Supervisor Agent - 主控 Agent
    负责三路分发：workflow_skills / execute_workflow / general_chat

    简化后的逻辑：
    - 不再处理 current_mode（创建流程状态由子图内部管理）
    - 如果在创建流程中（creation_stage 不为空），路由到 workflow_skills 子图
    - 如果在等待用户输入状态（execution_stage == "wait_input"），直接路由到 execute_workflow

    Returns:
        dict: 包含路由目标和可能的 matched_workflow_id
    """
    user_input = _get_last_user_message(state)
    input_preview = user_input[:50] + "..." if len(user_input) > 50 else user_input
    logger.info(f"▶ Supervisor Agent 开始 | 输入: {input_preview}")

    if not user_input.strip():
        logger.info("◀ Supervisor Agent 结束 | route=general_chat (空输入)")
        return {"route": "general_chat", "matched_workflow_id": None}

    # 如果在等待用户输入状态（工作流执行中的 collect 步骤暂停），直接继续执行
    execution_stage = state.get("execution_stage")
    if execution_stage == "wait_input":
        workflow_id = state.get("execution_workflow_id")
        logger.info(f"◀ Supervisor Agent 结束 | route=execute_workflow (等待输入状态, workflow_id={workflow_id})")
        return {"route": "execute_workflow", "matched_workflow_id": workflow_id}

    # 如果在创建流程中（creation_stage 不为空），继续路由到 workflow_skills 子图
    creation_stage = state.get("creation_stage")
    if creation_stage is not None:
        logger.info(f"◀ Supervisor Agent 结束 | route=workflow_skills (创建流程中, stage={creation_stage})")
        return {"route": "workflow_skills", "matched_workflow_id": None, "action": "create"}

    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))

    # 工作流管理关键词（优先级高于触发词匹配）
    management_keywords = ["删除", "移除", "创建", "新建", "搭建", "查看", "列出", "显示所有"]
    is_management_intent = any(kw in user_input for kw in management_keywords)

    # 快速路径：精确触发词匹配（仅当不是管理操作时）
    if not is_management_intent:
        exact_match_id = _exact_trigger_match(collection, user_input)
        if exact_match_id:
            logger.info(f"✓ 精确匹配成功 | workflow_id={exact_match_id}")
            logger.info(f"◀ Supervisor Agent 结束 | route=execute_workflow")
            return {"route": "execute_workflow", "matched_workflow_id": exact_match_id}

    # 调用 LLM 判断意图
    try:
        result = _supervisor_classify(user_input, collection)
        logger.info(f"✓ 意图分类 | intent={result.intent.value}, confidence={result.confidence:.2f}")
        logger.debug(f"  reasoning: {result.reasoning}")

        if result.intent == IntentType.WORKFLOW_MANAGEMENT:
            # 路由到 workflow_skills 子图，子图内部会进一步分类具体操作
            logger.info(f"◀ Supervisor Agent 结束 | route=workflow_skills")
            return {"route": "workflow_skills", "matched_workflow_id": None}

        if result.intent == IntentType.SKILL_EXECUTION:
            if result.matched_workflow_id:
                # 验证 workflow ID 存在
                if collection.get_workflow(result.matched_workflow_id):
                    logger.info(f"◀ Supervisor Agent 结束 | route=execute_workflow, workflow_id={result.matched_workflow_id}")
                    return {"route": "execute_workflow", "matched_workflow_id": result.matched_workflow_id}
            # 没有匹配到具体 workflow 或 ID 无效，降级到通用对话
            logger.warning("Skill 执行意图但无有效 workflow_id，降级到通用对话")
            logger.info("◀ Supervisor Agent 结束 | route=general_chat")
            return {"route": "general_chat", "matched_workflow_id": None}

    except Exception as e:
        logger.error(f"Supervisor Agent 异常: {e}")

    logger.info("◀ Supervisor Agent 结束 | route=general_chat")
    return {"route": "general_chat", "matched_workflow_id": None}


def supervisor_node(state: dict) -> dict:
    """
    Supervisor Agent 节点
    作为 LangGraph 图中的真正节点，可在可视化和 traces 中可见

    Returns:
        dict: 包含 route 和 matched_workflow_id 的状态更新
    """
    return supervisor_agent(state)
