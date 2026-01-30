"""
Workflow Skills 子图
负责工作流的创建/删除/查看生命周期管理

架构：
workflow_skills (子图) ─┬─→ create_workflow (内部子图)
                        ├─→ delete_workflow
                        └─→ list_workflows

create_workflow 子图内部:
  start → collect_name → collect_triggers → collect_step (循环) → confirm → save → END
"""

import os
import re
import json
import uuid
from datetime import datetime
from typing import Annotated, TypedDict, Literal, Optional

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from schemas import (
    WorkflowSchema, WorkflowStep, WorkflowCollection,
    ActionType, OutputFormat
)
from persistence import save_workflow, delete_workflow as delete_workflow_file
from utils.logger import setup_logger

# 模块日志
logger = setup_logger("WorkflowSkillsSubgraph")


# ============================================================
# 子图状态定义
# ============================================================

class WorkflowSkillsState(TypedDict):
    """Workflow Skills 子图状态"""
    messages: Annotated[list, add_messages]

    # 操作类型: "create" / "delete" / "list"
    action: Optional[str]

    # 工作流集合（从主图传入）
    workflow_collection: dict

    # 创建流程状态
    creation_stage: Optional[Literal[
        "start",
        "collect_name",
        "collect_triggers",
        "collect_step",
        "confirm",
        "save"
    ]]

    # 工作流草稿字段
    draft_name: Optional[str]
    draft_description: Optional[str]
    draft_triggers: list[str]
    draft_required_inputs: list[str]
    draft_optional_inputs: list[str]
    draft_steps: list[dict]
    draft_output_format: Optional[str]


# ============================================================
# LLM 配置
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


# ============================================================
# 辅助函数
# ============================================================

def _get_last_user_message(state: WorkflowSkillsState) -> str:
    """获取最后一条用户消息"""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def _is_confirmation(text: str) -> bool:
    """判断用户是否确认"""
    positive_keywords = ["确认", "没问题", "可以", "好的", "对", "是的", "yes", "ok", "确定", "同意", "通过", "行"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in positive_keywords)


def _is_rejection(text: str) -> bool:
    """判断用户是否拒绝/要求修改"""
    negative_keywords = ["不对", "不是", "修改", "改一下", "重新", "不行", "错了", "no", "取消", "改"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in negative_keywords)


def _is_cancel(text: str) -> bool:
    """判断用户是否要取消创建"""
    cancel_keywords = ["取消", "不创建了", "不要了", "退出", "算了", "cancel"]
    text_lower = text.lower().strip()
    return any(kw in text_lower for kw in cancel_keywords)


def _infer_action_type(description: str) -> str:
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


# ============================================================
# 操作分类节点
# ============================================================

CLASSIFY_ACTION_PROMPT = """你是 Workflow Skills Agent，负责识别工作流管理操作。

## 操作类型

1. **create** - 创建新工作流
   - "创建一个周报流程"、"搭建自动化任务"、"新建工作流"

2. **delete** - 删除工作流
   - "删除XX流程"、"移除工作流"、"去掉这个流程"

3. **list** - 查看工作流列表
   - "有哪些流程"、"列出工作流"、"查看所有流程"

## 已有工作流
{workflow_list}

## 输出格式（严格 JSON）
{{"action": "create/delete/list", "reasoning": "说明"}}
"""


def classify_action_node(state: WorkflowSkillsState) -> dict:
    """识别操作类型（create/delete/list）"""
    logger.info("▶ 节点: classify_action | 识别工作流操作类型")

    # 只有在创建流程中（creation_stage 不为空）时，才使用上游设置的 action
    # 这样可以避免旧的 action 值影响新的请求（如删除/查看）
    existing_action = state.get("action")
    creation_stage = state.get("creation_stage")

    if creation_stage is not None and existing_action == "create":
        logger.info(f"✓ 创建流程中，使用 action={existing_action} (stage={creation_stage})")
        return {"action": existing_action}

    user_input = _get_last_user_message(state)
    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))

    # 快速路径：关键词匹配
    if any(kw in user_input for kw in ["创建", "新建", "搭建"]):
        logger.info("✓ 快速匹配 | action=create")
        return {"action": "create"}
    elif any(kw in user_input for kw in ["删除", "移除", "去掉"]):
        logger.info("✓ 快速匹配 | action=delete")
        return {"action": "delete"}
    elif any(kw in user_input for kw in ["查看", "列出", "有哪些", "显示"]):
        logger.info("✓ 快速匹配 | action=list")
        return {"action": "list"}

    # LLM 分类
    llm = _get_llm()
    workflow_list = _format_workflow_list(collection)
    prompt = CLASSIFY_ACTION_PROMPT.format(workflow_list=workflow_list)

    response = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"用户输入：{user_input}")
    ])

    # 解析结果
    content = response.content
    if "```" in content:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if match:
            content = match.group(1)

    try:
        data = json.loads(content.strip())
        action = data.get("action", "list")
        logger.info(f"✓ LLM 分类 | action={action}")
        return {"action": action}
    except (json.JSONDecodeError, ValueError):
        logger.warning("JSON 解析失败，默认 list")
        return {"action": "list"}


# ============================================================
# 列出工作流节点
# ============================================================

def list_workflows_node(state: WorkflowSkillsState) -> dict:
    """列出所有工作流"""
    logger.info("▶ 节点: list_workflows | 列出所有工作流")
    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))
    workflows = collection.list_workflows()

    if not workflows:
        response = "当前没有已创建的工作流。\n\n说「我要创建XX流程」来创建一个新的工作流。"
        logger.info("◀ 节点: list_workflows | 无工作流")
    else:
        response = "**已创建的工作流**：\n\n"
        for wf in workflows:
            response += f"**{wf['name']}** (`{wf['id']}`)\n"
            response += f"触发词：{', '.join(f'「{t}」' for t in wf['triggers'])}\n\n"
        logger.info(f"◀ 节点: list_workflows | count={len(workflows)}")

    return {"messages": [AIMessage(content=response)]}


# ============================================================
# 删除工作流节点
# ============================================================

def delete_workflow_node(state: WorkflowSkillsState) -> dict:
    """删除工作流"""
    logger.info("▶ 节点: delete_workflow | 删除工作流")
    user_input = _get_last_user_message(state)
    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))

    # 查找匹配的工作流（通过名称或触发词）
    workflow_to_delete = None
    for wf in collection.workflows.values():
        if wf.name in user_input or any(t in user_input for t in wf.trigger_phrases):
            workflow_to_delete = wf
            break

    if not workflow_to_delete:
        logger.warning("◀ 节点: delete_workflow | 未找到匹配的工作流")
        return {
            "messages": [AIMessage(content="未找到要删除的工作流。请提供工作流名称。")]
        }

    # 从内存中删除
    collection.delete_workflow(workflow_to_delete.workflow_id)

    # 从磁盘删除
    delete_workflow_file(workflow_to_delete.workflow_id)

    # 列出剩余工作流
    remaining = [wf["name"] for wf in collection.list_workflows()]
    remaining_text = "、".join(remaining) if remaining else "无"

    response = f"""工作流删除成功！

已删除工作流：
- **ID**：{workflow_to_delete.workflow_id}
- **名称**：{workflow_to_delete.name}

剩余工作流：{remaining_text}"""

    logger.info(f"✓ 工作流已删除 | id={workflow_to_delete.workflow_id}, name={workflow_to_delete.name}")
    logger.info("◀ 节点: delete_workflow | 完成")
    return {
        "messages": [AIMessage(content=response)],
        "workflow_collection": collection.model_dump()
    }


# ============================================================
# 创建工作流子图：各阶段节点
# ============================================================

def _get_initial_draft_state() -> dict:
    """获取草稿初始状态"""
    return {
        "draft_name": None,
        "draft_description": None,
        "draft_triggers": [],
        "draft_required_inputs": [],
        "draft_optional_inputs": [],
        "draft_steps": [],
        "draft_output_format": None,
    }


def _cancel_creation() -> dict:
    """取消创建，返回重置状态"""
    logger.info("用户取消创建")
    return {
        "messages": [AIMessage(content="已取消工作流创建。如需重新创建，请说「创建XX工作流」。")],
        "creation_stage": None,
        **_get_initial_draft_state()
    }


def start_creation_node(state: WorkflowSkillsState) -> dict:
    """开始创建工作流，初始化状态并询问名称"""
    logger.info("▶ 节点: start_creation | 开始创建工作流")
    user_input = _get_last_user_message(state)

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

    logger.info("◀ 节点: start_creation | 进入阶段: collect_name")
    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_name",
        **_get_initial_draft_state()
    }


def collect_name_node(state: WorkflowSkillsState) -> dict:
    """收集工作流名称和描述"""
    logger.info("▶ 节点: collect_name | 收集名称和描述")
    user_input = _get_last_user_message(state)

    # 检测取消
    if _is_cancel(user_input):
        return _cancel_creation()

    system_prompt = """请从用户输入中提取工作流的名称和描述。

严格按以下 JSON 格式输出（不要有其他内容）：
{"name": "提取的名称", "description": "提取的描述"}"""

    llm = _get_llm()
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

    # 让 LLM 推荐触发关键词
    recommend_prompt = f"""根据以下工作流信息，推荐 3-5 个触发短语。

工作流名称：{name}
工作流描述：{description}

要求：
1. 短语要简洁自然，符合用户日常表达习惯
2. 包含不同的表达方式（如中文、英文、口语化等）
3. 严格按 JSON 数组格式输出，如：["写周报", "生成周报", "weekly report"]"""

    recommend_response = llm.invoke([
        SystemMessage(content=recommend_prompt),
        HumanMessage(content=f"工作流：{name}")
    ])

    # 解析推荐的触发词
    recommended_triggers = []
    try:
        content = recommend_response.content
        # 处理 markdown 代码块包裹的情况
        if "```" in content:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1)
        recommended_triggers = json.loads(content)
    except:
        pass

    # 构建展示文本
    if recommended_triggers:
        triggers_suggestion = '\n'.join(f'- "{t}"' for t in recommended_triggers)
        response_text = f"""收到！工作流名称：**{name}**

接下来，请告诉我**触发短语**——当用户说什么话时，应该触发这个工作流？

参考推荐：
{triggers_suggestion}

请输入您想要的触发短语（2-5 个，用逗号分隔）："""
    else:
        response_text = f"""收到！工作流名称：**{name}**

接下来，请告诉我**触发短语**——当用户说什么话时，应该触发这个工作流？

请提供 2-5 个短语，例如：
- "写周报"
- "生成本周总结"
- "weekly report" """

    logger.info(f"✓ 名称解析完成 | name={name}")
    logger.info("◀ 节点: collect_name | 进入阶段: collect_triggers")
    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_triggers",
        "draft_name": name,
        "draft_description": description
    }


def collect_triggers_node(state: WorkflowSkillsState) -> dict:
    """收集触发短语"""
    logger.info("▶ 节点: collect_triggers | 收集触发短语")
    user_input = _get_last_user_message(state)

    # 检测取消
    if _is_cancel(user_input):
        return _cancel_creation()

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

    logger.info(f"✓ 触发短语收集完成 | count={len(triggers)}")
    logger.info("◀ 节点: collect_triggers | 进入阶段: collect_step")
    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_step",
        "draft_triggers": triggers,
        "draft_steps": []
    }


def collect_step_node(state: WorkflowSkillsState) -> dict:
    """收集用户输入的步骤"""
    logger.info("▶ 节点: collect_step | 收集执行步骤")
    user_input = _get_last_user_message(state)
    draft_steps = list(state.get("draft_steps", []))

    # 检测取消
    if _is_cancel(user_input):
        return _cancel_creation()

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

        summary = f"""## 工作流确认

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

        logger.info(f"✓ 步骤收集完成 | count={len(draft_steps)}")
        logger.info("◀ 节点: collect_step | 进入阶段: confirm")
        return {
            "messages": [AIMessage(content=summary)],
            "creation_stage": "confirm",
            "draft_steps": draft_steps,
            "draft_required_inputs": [],
            "draft_optional_inputs": [],
            "draft_output_format": "json",
        }

    # 添加用户输入作为新步骤
    action = _infer_action_type(user_input)
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

    logger.info(f"✓ 已添加步骤 {len(draft_steps)} | action={action}")
    return {
        "messages": [AIMessage(content=response_text)],
        "creation_stage": "collect_step",
        "draft_steps": draft_steps
    }


def confirm_node(state: WorkflowSkillsState) -> dict:
    """处理用户确认"""
    logger.info("▶ 节点: confirm | 处理用户确认")
    user_input = _get_last_user_message(state)

    # 检测取消
    if _is_cancel(user_input):
        return _cancel_creation()

    if _is_confirmation(user_input):
        logger.info("✓ 用户确认保存")
        logger.info("◀ 节点: confirm | 进入阶段: save")
        return {"creation_stage": "save"}

    elif _is_rejection(user_input):
        user_lower = user_input.lower()

        if any(kw in user_lower for kw in ["名称", "名字", "描述"]):
            response_text = "好的，请重新输入工作流的**名称和描述**："
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "collect_name",
            }
        elif any(kw in user_lower for kw in ["触发", "关键词", "短语"]):
            response_text = "好的，请重新输入**触发短语**（2-5个）："
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "collect_triggers",
            }
        elif any(kw in user_lower for kw in ["步骤", "流程", "执行"]):
            response_text = "好的，请重新输入第一个**执行步骤**：\n（输入「完成」结束步骤收集）"
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "collect_step",
                "draft_steps": [],  # 重置步骤列表
            }
        else:
            response_text = """请告诉我要修改哪部分：
- 名称/描述
- 触发短语
- 执行步骤"""
            return {
                "messages": [AIMessage(content=response_text)],
                "creation_stage": "confirm",
            }
    else:
        return {
            "messages": [AIMessage(content="请输入「确认」保存工作流，或告诉我需要「修改」哪里。")]
        }


def save_workflow_node(state: WorkflowSkillsState) -> dict:
    """保存工作流"""
    logger.info(f"▶ 节点: save_workflow | name={state.get('draft_name')}")
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

    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))
    collection.add_workflow(workflow)

    # 持久化保存到 skills 目录
    saved_path = save_workflow(workflow)
    logger.info(f"✓ 工作流已保存 | id={workflow_id}, path={saved_path}")

    success_msg = f"""**工作流创建成功！**

**ID**：`{workflow_id}`
**名称**：{workflow.name}
**触发方式**：{', '.join(f'「{t}」' for t in workflow.trigger_phrases)}
**已保存至**：`{saved_path}`

现在你可以通过说触发短语来使用这个工作流了！"""

    logger.info("◀ 节点: save_workflow | 完成")
    return {
        "messages": [AIMessage(content=success_msg)],
        "creation_stage": None,
        "workflow_collection": collection.model_dump(),
        **_get_initial_draft_state()
    }


# ============================================================
# 创建工作流子图路由
# ============================================================

def _route_creation_stage(state: WorkflowSkillsState) -> str:
    """根据 creation_stage 路由到对应节点"""
    stage = state.get("creation_stage")
    logger.debug(f"创建流程路由 | stage={stage}")

    if stage == "collect_name":
        return "collect_name"
    elif stage == "collect_triggers":
        return "collect_triggers"
    elif stage == "collect_step":
        return "collect_step"
    elif stage == "confirm":
        return "confirm"
    elif stage == "save":
        return "save"
    else:
        # 默认从 start 开始
        return "start"


# ============================================================
# 构建创建工作流子图
# ============================================================

def build_create_workflow_subgraph():
    """构建创建工作流的子图"""
    logger.info("构建 create_workflow 子图")

    graph = StateGraph(WorkflowSkillsState)

    # 添加节点
    graph.add_node("router", lambda x: x)  # 路由节点
    graph.add_node("start", start_creation_node)
    graph.add_node("collect_name", collect_name_node)
    graph.add_node("collect_triggers", collect_triggers_node)
    graph.add_node("collect_step", collect_step_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("save", save_workflow_node)

    # 设置入口点
    graph.set_entry_point("router")

    # 路由条件边
    graph.add_conditional_edges(
        "router",
        _route_creation_stage,
        {
            "start": "start",
            "collect_name": "collect_name",
            "collect_triggers": "collect_triggers",
            "collect_step": "collect_step",
            "confirm": "confirm",
            "save": "save",
        }
    )

    # 所有节点完成后结束（等待下一次用户输入）
    graph.add_edge("start", END)
    graph.add_edge("collect_name", END)
    graph.add_edge("collect_triggers", END)
    graph.add_edge("collect_step", END)
    graph.add_edge("confirm", END)
    graph.add_edge("save", END)

    return graph.compile()


# ============================================================
# 构建 Workflow Skills 主子图
# ============================================================

def _route_action(state: WorkflowSkillsState) -> str:
    """根据 action 路由到对应节点"""
    action = state.get("action")
    logger.debug(f"Workflow Skills 路由 | action={action}")

    # 返回值必须匹配 add_conditional_edges 映射的键
    if action == "create":
        return "create"
    elif action == "delete":
        return "delete"
    else:
        return "list"


def build_workflow_skills_subgraph():
    """
    构建 workflow_skills 子图

    结构：
    classify → ┬→ create_workflow (子图)
               ├→ delete_workflow
               └→ list_workflows

    注：classify 节点会优先使用上游设置的 action，避免重复分类
    """
    logger.info("构建 workflow_skills 子图")

    graph = StateGraph(WorkflowSkillsState)

    # 添加节点
    graph.add_node("classify", classify_action_node)
    graph.add_node("list_workflows", list_workflows_node)
    graph.add_node("delete_workflow", delete_workflow_node)
    graph.add_node("create_workflow", build_create_workflow_subgraph())

    # 设置入口点
    graph.set_entry_point("classify")

    # classify 后的路由条件边
    graph.add_conditional_edges(
        "classify",
        _route_action,
        {
            "create": "create_workflow",
            "delete": "delete_workflow",
            "list": "list_workflows",
        }
    )

    # 所有操作完成后结束
    graph.add_edge("list_workflows", END)
    graph.add_edge("delete_workflow", END)
    graph.add_edge("create_workflow", END)

    return graph.compile()
