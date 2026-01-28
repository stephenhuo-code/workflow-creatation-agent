"""
LangGraph 状态机定义（改进版）
使用显式状态机控制工作流创建流程，每个阶段是独立节点
"""

from typing import Annotated, TypedDict, Literal, Optional
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_anthropic import ChatAnthropic
import os
import json
import uuid
import re
from datetime import datetime

from schemas import (
    WorkflowSchema, WorkflowStep, WorkflowCollection,
    ActionType, OutputFormat
)
from persistence import save_workflow, delete_workflow


# ============================================================
# 状态定义
# ============================================================

class ConversationState(TypedDict):
    """对话状态"""
    messages: Annotated[list, add_messages]

    # 模式控制
    current_mode: Literal["chat", "creating_workflow", "executing_workflow"]

    # 创建工作流的阶段（显式控制）
    # 简化流程：name -> triggers -> collect_step (loop) -> confirm -> save
    creation_stage: Optional[Literal[
        "collect_name",
        "collect_triggers",
        "collect_step",
        "confirm",
        "save"
    ]]

    # 工作流草稿（分字段存储，便于验证）
    draft_name: Optional[str]
    draft_description: Optional[str]
    draft_triggers: list[str]
    draft_required_inputs: list[str]
    draft_optional_inputs: list[str]
    draft_steps: list[dict]
    draft_output_format: Optional[str]

    # 步骤收集相关状态
    current_step_index: int  # 当前步骤编号（用于显示）

    # 工作流集合
    workflow_collection: dict

    # 等待用户确认的标志
    awaiting_confirmation: bool


def get_initial_state() -> ConversationState:
    """获取初始状态"""
    return {
        "messages": [],
        "current_mode": "chat",
        "creation_stage": None,
        "draft_name": None,
        "draft_description": None,
        "draft_triggers": [],
        "draft_required_inputs": [],
        "draft_optional_inputs": [],
        "draft_steps": [],
        "draft_output_format": None,
        "current_step_index": 0,
        "workflow_collection": {"workflows": {}},
        "awaiting_confirmation": False
    }


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
# 辅助函数
# ============================================================

def extract_list_from_response(text: str) -> list[str]:
    """从文本中提取列表项"""
    lines = text.strip().split('\n')
    items = []
    for line in lines:
        cleaned = re.sub(r'^[\s]*[-*•\d.]+[\s]*', '', line).strip()
        if cleaned and len(cleaned) > 1:
            items.append(cleaned)
    return items if items else [text.strip()]


def get_last_user_message(state: ConversationState) -> str:
    """获取最后一条用户消息"""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def is_confirmation(text: str) -> bool:
    """判断用户是否确认"""
    positive_keywords = ["确认", "没问题", "可以", "好的", "对", "是的", "yes", "ok", "确定", "同意", "通过", "行"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in positive_keywords)


def is_rejection(text: str) -> bool:
    """判断用户是否拒绝/要求修改"""
    negative_keywords = ["不对", "不是", "修改", "改一下", "重新", "不行", "错了", "no", "取消", "改"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in negative_keywords)


def is_skip(text: str) -> bool:
    """判断用户是否跳过"""
    skip_keywords = ["跳过", "不需要", "不用", "没有", "skip", "无", "暂时不", "先不"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in skip_keywords)


def is_cancel(text: str) -> bool:
    """判断用户是否要取消创建"""
    cancel_keywords = ["取消", "不创建了", "不要了", "退出", "算了", "cancel"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in cancel_keywords)


# ============================================================
# 主路由节点
# ============================================================

def route_entry(state: ConversationState) -> str:
    """入口路由：决定进入哪个流程"""
    if state["current_mode"] == "creating_workflow":
        return "creation_router"

    user_input = get_last_user_message(state)
    user_input_lower = user_input.lower()

    if "创建" in user_input and ("流程" in user_input or "工作流" in user_input):
        return "start_creation"

    # 检测删除请求
    if any(kw in user_input for kw in ["删除", "移除"]) and ("流程" in user_input or "工作流" in user_input):
        return "delete_workflow"

    if any(kw in user_input_lower for kw in ["查看所有", "列出", "显示", "有哪些"]) and ("流程" in user_input or "工作流" in user_input):
        return "list_workflows"

    collection = WorkflowCollection(**state["workflow_collection"])
    matched = collection.find_by_trigger(user_input)
    if matched:
        return "execute_workflow"

    return "general_chat"


# ============================================================
# 创建流程路由
# ============================================================

def route_creation_stage(state: ConversationState) -> str:
    """根据创建阶段路由到对应节点"""
    stage = state.get("creation_stage")

    stage_mapping = {
        "collect_name": "collect_name",
        "collect_triggers": "collect_triggers",
        "collect_step": "collect_step",
        "confirm": "confirm",
        "save": "save_workflow"
    }

    return stage_mapping.get(stage, "collect_name")


# ============================================================
# 创建流程：各阶段节点
# ============================================================

def cancel_creation_node(state: ConversationState) -> dict:
    """取消工作流创建，重置状态"""
    return {
        "messages": [AIMessage(content="已取消工作流创建。如需重新创建，请说「创建XX工作流」。")],
        "current_mode": "chat",
        "creation_stage": None,
        "draft_name": None,
        "draft_description": None,
        "draft_triggers": [],
        "draft_required_inputs": [],
        "draft_optional_inputs": [],
        "draft_steps": [],
        "draft_output_format": None,
        "current_step_index": 0,
        "awaiting_confirmation": False
    }


def start_creation_node(state: ConversationState) -> dict:
    """开始创建工作流，初始化状态并询问名称"""
    user_input = get_last_user_message(state)
    
    workflow_hint = ""
    if "创建" in user_input:
        parts = user_input.split("创建")
        if len(parts) > 1:
            workflow_hint = parts[1].replace("流程", "").replace("工作流", "").strip()
    
    if workflow_hint:
        response_text = f"""好的，我来帮你创建「{workflow_hint}」工作流。

请告诉我：
1. **工作流名称**（简短，如"周报生成"、"竞品分析"）
2. **简单描述**一下这个工作流是做什么的"""
    else:
        response_text = """好的，我来帮你创建一个新工作流。

请告诉我：
1. **工作流名称**（简短，如"周报生成"、"竞品分析"）
2. **简单描述**一下这个工作流是做什么的"""

    return {
        "messages": [AIMessage(content=response_text)],
        "current_mode": "creating_workflow",
        "creation_stage": "collect_name",
        "draft_name": None,
        "draft_description": None,
        "draft_triggers": [],
        "draft_required_inputs": [],
        "draft_optional_inputs": [],
        "draft_steps": [],
        "draft_output_format": None,
        "current_step_index": 0,
        "awaiting_confirmation": False
    }


def collect_name_node(state: ConversationState) -> dict:
    """收集工作流名称和描述"""
    user_input = get_last_user_message(state)

    # 检测取消
    if is_cancel(user_input):
        return cancel_creation_node(state)

    system_prompt = """请从用户输入中提取工作流的名称和描述。

严格按以下 JSON 格式输出（不要有其他内容）：
{"name": "提取的名称", "description": "提取的描述"}"""

    llm = get_llm()
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input)
    ])
    
    # 解析 JSON
    name = user_input[:20]
    description = user_input
    try:
        data = json.loads(response.content)
        name = data.get("name", name)
        description = data.get("description", description)
    except:
        if "名称" in user_input or "叫" in user_input:
            parts = re.split(r'[,，。;；\n]', user_input)
            if parts:
                name = parts[0].replace("名称", "").replace("叫", "").strip()[:20]

    response_text = f"""收到！工作流名称：**{name}**

接下来，请告诉我**触发短语**——当用户说什么话时，应该触发这个工作流？

请提供 2-5 个短语，例如：
- "写周报"
- "生成本周总结"
- "weekly report" """

    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_triggers",
        "draft_name": name,
        "draft_description": description
    }


def collect_triggers_node(state: ConversationState) -> dict:
    """收集触发短语"""
    user_input = get_last_user_message(state)

    # 检测取消
    if is_cancel(user_input):
        return cancel_creation_node(state)

    # 解析触发短语
    triggers = []
    parts = re.split(r'[,，、;；\n]', user_input)
    for part in parts:
        cleaned = re.sub(r'^[\s]*[-*•\d.\"\']+[\s]*', '', part).strip()
        cleaned = cleaned.strip('"\'「」""''')
        if cleaned and len(cleaned) >= 2:
            triggers.append(cleaned)

    if not triggers:
        triggers = [user_input.strip()]

    triggers_display = '、'.join(f'「{t}」' for t in triggers)

    response_text = f"""好的，触发短语：{triggers_display}

现在请输入第一个执行步骤的描述：
（输入「完成」结束步骤收集）"""

    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_step",
        "draft_triggers": triggers,
        "draft_steps": []
    }


def infer_action_type(description: str) -> str:
    """根据描述推断步骤的动作类型"""
    if any(kw in description for kw in ["收集", "询问", "获取", "了解", "问", "输入", "提供"]):
        return "collect"
    elif any(kw in description for kw in ["分析", "评估", "判断", "比较", "对比", "研究", "调研"]):
        return "analyze"
    elif any(kw in description for kw in ["验证", "确认", "检查", "核实", "审核"]):
        return "validate"
    elif any(kw in description for kw in ["转换", "格式化", "处理"]):
        return "transform"
    else:
        return "generate"


def collect_step_node(state: ConversationState) -> dict:
    """收集用户输入的步骤"""
    user_input = get_last_user_message(state)
    draft_steps = list(state.get("draft_steps", []))

    # 检测取消
    if is_cancel(user_input):
        return cancel_creation_node(state)

    # 更严格的完成检测：只识别明确的完成意图
    finish_keywords = ["完成", "结束", "够了", "done", "finish"]
    user_lower = user_input.lower().strip()
    is_finish = any(user_lower == kw or user_lower.startswith(kw) for kw in finish_keywords)

    if is_finish:
        if not draft_steps:
            return {
                "messages": [AIMessage(content="工作流至少需要一个步骤。请输入步骤描述，或输入「取消」退出：")],
                "creation_stage": "collect_step"
            }

        steps_display = '\n'.join(
            f'{i+1}. [{s["action"]}] {s["description"]}'
            for i, s in enumerate(draft_steps)
        )

        triggers_display = ', '.join(f'「{t}」' for t in state.get('draft_triggers', []))

        summary = f"""## 📋 工作流确认

**名称**：{state.get('draft_name', '未命名')}

**描述**：{state.get('draft_description', '无描述')}

**触发短语**：{triggers_display}

**执行步骤**：
{steps_display}

**输出格式**：json

---

请确认以上信息：
- 输入「**确认**」保存工作流
- 输入「**修改 + 内容**」进行调整
- 输入「**取消**」退出创建"""

        return {
            "messages": [AIMessage(content=summary)],
            "creation_stage": "confirm",
            "draft_steps": draft_steps,
            "draft_required_inputs": [],
            "draft_optional_inputs": [],
            "draft_output_format": "json",
            "awaiting_confirmation": True
        }

    # 添加用户输入作为新步骤
    action = infer_action_type(user_input)
    draft_steps.append({
        "step_id": f"step_{len(draft_steps)+1}",
        "action": action,
        "description": user_input,
        "inputs": [],
        "outputs": [],
        "prompt_template": None
    })

    steps_display = '\n'.join(
        f'{i+1}. [{s["action"]}] {s["description"]}'
        for i, s in enumerate(draft_steps)
    )

    response_text = f"""已添加步骤 {len(draft_steps)}：[{action}] {user_input}

当前步骤列表：
{steps_display}

- 继续输入下一个步骤
- 输入「完成」进入确认
- 输入「取消」退出创建"""

    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_step",
        "draft_steps": draft_steps
    }


def confirm_node(state: ConversationState) -> dict:
    """处理用户确认"""
    user_input = get_last_user_message(state)

    # 检测取消
    if is_cancel(user_input):
        return cancel_creation_node(state)

    if is_confirmation(user_input):
        return {
            "creation_stage": "save",
            "awaiting_confirmation": False
        }
    elif is_rejection(user_input):
        user_lower = user_input.lower()

        if any(kw in user_lower for kw in ["名称", "名字", "描述"]):
            response_text = "好的，请重新输入工作流的**名称和描述**："
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "collect_name",
                "awaiting_confirmation": False
            }
        elif any(kw in user_lower for kw in ["触发", "关键词", "短语"]):
            response_text = "好的，请重新输入**触发短语**（2-5个）："
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "collect_triggers",
                "awaiting_confirmation": False
            }
        elif any(kw in user_lower for kw in ["步骤", "流程", "执行"]):
            response_text = "好的，请重新输入第一个**执行步骤**：\n（输入「完成」结束步骤收集）"
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "collect_step",
                "draft_steps": [],  # 重置步骤列表
                "awaiting_confirmation": False
            }
        else:
            response_text = """请告诉我要修改哪部分：
- 名称/描述
- 触发短语
- 执行步骤"""
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "confirm",
                "awaiting_confirmation": False
            }
    else:
        return {
            "messages": [AIMessage(content="请输入「确认」保存工作流，或告诉我需要「修改」哪里。")]
        }


def save_workflow_node(state: ConversationState) -> dict:
    """保存工作流（程序控制，必定执行）"""
    workflow_id = f"wf_{uuid.uuid4().hex[:8]}"
    
    steps = []
    for step_data in state.get("draft_steps", []):
        steps.append(WorkflowStep(
            step_id=step_data.get("step_id", f"step_{len(steps)+1}"),
            action=ActionType(step_data.get("action", "generate")),
            description=step_data.get("description", ""),
            inputs=step_data.get("inputs", []),
            outputs=step_data.get("outputs", []),
            prompt_template=step_data.get("prompt_template")
        ))
    
    workflow = WorkflowSchema(
        workflow_id=workflow_id,
        name=state.get("draft_name") or "未命名工作流",
        description=state.get("draft_description") or "",
        trigger_phrases=state.get("draft_triggers") or ["触发"],
        domain="通用",
        required_inputs=state.get("draft_required_inputs") or [],
        optional_inputs=state.get("draft_optional_inputs") or [],
        output_format=OutputFormat(state.get("draft_output_format") or "json"),
        steps=steps,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    
    collection = WorkflowCollection(**state["workflow_collection"])
    collection.add_workflow(workflow)

    # 持久化保存到 skills 目录
    saved_path = save_workflow(workflow, generate_markdown=True)

    success_msg = f"""✅ **工作流创建成功！**

**ID**：`{workflow_id}`
**名称**：{workflow.name}
**触发方式**：{', '.join(f'「{t}」' for t in workflow.trigger_phrases)}
**已保存至**：`{saved_path}`

现在你可以通过说触发短语来使用这个工作流了！"""

    return {
        "messages": [AIMessage(content=success_msg)],
        "current_mode": "chat",
        "creation_stage": None,
        "workflow_collection": collection.model_dump(),
        "awaiting_confirmation": False,
        "draft_name": None,
        "draft_description": None,
        "draft_triggers": [],
        "draft_required_inputs": [],
        "draft_optional_inputs": [],
        "draft_steps": [],
        "draft_output_format": None,
        "current_step_index": 0
    }


# ============================================================
# 其他功能节点
# ============================================================

def list_workflows_node(state: ConversationState) -> dict:
    """列出所有工作流"""
    collection = WorkflowCollection(**state["workflow_collection"])
    workflows = collection.list_workflows()

    if not workflows:
        response = "📋 当前没有已创建的工作流。\n\n说「我要创建XX流程」来创建一个新的工作流。"
    else:
        response = "📋 **已创建的工作流**：\n\n"
        for wf in workflows:
            response += f"**{wf['name']}** (`{wf['id']}`)\n"
            response += f"触发词：{', '.join(f'「{t}」' for t in wf['triggers'])}\n\n"

    return {"messages": [AIMessage(content=response)]}


def delete_workflow_node(state: ConversationState) -> dict:
    """删除工作流"""
    user_input = get_last_user_message(state)
    collection = WorkflowCollection(**state["workflow_collection"])

    # 查找匹配的工作流（通过名称或触发词）
    workflow_to_delete = None
    for wf in collection.workflows.values():
        if wf.name in user_input or any(t in user_input for t in wf.trigger_phrases):
            workflow_to_delete = wf
            break

    if not workflow_to_delete:
        return {
            "messages": [AIMessage(content="未找到要删除的工作流。请提供工作流名称。")]
        }

    # 从内存中删除
    collection.delete_workflow(workflow_to_delete.workflow_id)

    # 从磁盘删除
    delete_workflow(workflow_to_delete.workflow_id)

    # 列出剩余工作流
    remaining = [wf["name"] for wf in collection.list_workflows()]
    remaining_text = "、".join(remaining) if remaining else "无"

    response = f"""✅ 工作流删除成功！

已删除工作流：
- **ID**：{workflow_to_delete.workflow_id}
- **名称**：{workflow_to_delete.name}

剩余工作流：{remaining_text}"""

    return {
        "messages": [AIMessage(content=response)],
        "workflow_collection": collection.model_dump()
    }


def execute_workflow_node(state: ConversationState) -> dict:
    """执行匹配的工作流"""
    llm = get_llm()
    collection = WorkflowCollection(**state["workflow_collection"])
    user_input = get_last_user_message(state)
    
    workflow = collection.find_by_trigger(user_input)
    if not workflow:
        return general_chat_node(state)
    
    skill_text = workflow.to_skill_text()
    
    execute_prompt = f"""你正在执行工作流「{workflow.name}」。

## Skill 定义
{skill_text}

## 用户输入
{user_input}

## 执行指令
严格按照工作流定义执行。如果缺少必需信息，向用户询问。
输出格式：{workflow.output_format.value}"""

    response = llm.invoke([
        SystemMessage(content=execute_prompt),
        HumanMessage(content=user_input)
    ])
    
    return {
        "messages": [AIMessage(content=f"🔄 **{workflow.name}**\n\n{response.content}")]
    }


def general_chat_node(state: ConversationState) -> dict:
    """普通对话节点"""
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
    
    return {"messages": [AIMessage(content=response.content)]}


# ============================================================
# 构建图
# ============================================================

def build_graph() -> StateGraph:
    """构建 LangGraph 状态图"""

    workflow = StateGraph(ConversationState)

    # 添加所有节点
    workflow.add_node("entry_router", lambda x: x)
    workflow.add_node("creation_router", lambda x: x)
    workflow.add_node("start_creation", start_creation_node)
    workflow.add_node("collect_name", collect_name_node)
    workflow.add_node("collect_triggers", collect_triggers_node)
    workflow.add_node("collect_step", collect_step_node)
    workflow.add_node("confirm", confirm_node)
    workflow.add_node("save_workflow", save_workflow_node)
    workflow.add_node("list_workflows", list_workflows_node)
    workflow.add_node("delete_workflow", delete_workflow_node)
    workflow.add_node("execute_workflow", execute_workflow_node)
    workflow.add_node("general_chat", general_chat_node)

    # 设置入口点
    workflow.set_entry_point("entry_router")

    # 入口路由
    workflow.add_conditional_edges(
        "entry_router",
        route_entry,
        {
            "start_creation": "start_creation",
            "creation_router": "creation_router",
            "list_workflows": "list_workflows",
            "delete_workflow": "delete_workflow",
            "execute_workflow": "execute_workflow",
            "general_chat": "general_chat"
        }
    )

    # 创建流程内部路由
    workflow.add_conditional_edges(
        "creation_router",
        route_creation_stage,
        {
            "collect_name": "collect_name",
            "collect_triggers": "collect_triggers",
            "collect_step": "collect_step",
            "confirm": "confirm",
            "save_workflow": "save_workflow"
        }
    )

    # 所有节点指向 END（等待下一次用户输入）
    workflow.add_edge("start_creation", END)
    workflow.add_edge("collect_name", END)
    workflow.add_edge("collect_triggers", END)
    workflow.add_edge("collect_step", END)
    workflow.add_edge("confirm", END)
    workflow.add_edge("save_workflow", END)
    workflow.add_edge("list_workflows", END)
    workflow.add_edge("delete_workflow", END)
    workflow.add_edge("execute_workflow", END)
    workflow.add_edge("general_chat", END)

    return workflow.compile()


# 全局图实例
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
