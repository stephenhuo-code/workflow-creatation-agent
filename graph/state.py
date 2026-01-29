"""
LangGraph 状态定义
定义 ConversationState TypedDict 和初始状态

注意：创建工作流相关的状态（creation_stage, draft_* 字段）
已迁移到 graph/subgraphs/workflow_skills.py 中的 WorkflowSkillsState
"""

from typing import Annotated, TypedDict, Literal, Optional, List
from langgraph.graph.message import add_messages

from persistence import load_all_workflows


class ConversationState(TypedDict):
    """
    主图对话状态

    简化后的状态结构：
    - messages: 对话消息列表
    - route: Supervisor 决策的路由目标
    - workflow_collection: 工作流集合
    - matched_workflow_id: 匹配到的工作流 ID（用于执行）

    创建工作流相关状态由 workflow_skills 子图内部管理
    """
    messages: Annotated[list, add_messages]

    # Supervisor Agent 路由决策
    route: Optional[str]

    # 工作流集合
    workflow_collection: dict

    # 执行工作流时的匹配 ID
    matched_workflow_id: Optional[str]

    # ============================================================
    # 以下字段用于 workflow_execution 子图状态传递
    # ============================================================

    # 执行阶段（新增 "wait_input" 用于 collect 步骤暂停等待用户输入）
    execution_stage: Optional[Literal["start", "process_step", "wait_input", "finalize"]]

    # 当前步骤索引（从 0 开始）
    current_step_index: int

    # 每步执行结果
    step_results: List[dict]

    # 正在执行的工作流 ID
    execution_workflow_id: Optional[str]

    # 收集的用户输入（用于 collect 步骤）{step_id: user_input}
    collected_inputs: dict

    # 保存触发工作流时的原始用户输入
    initial_user_input: Optional[str]

    # ============================================================
    # 以下字段用于 workflow_skills 子图状态传递
    # 子图会读取和更新这些字段
    # ============================================================

    # 操作类型 (子图使用)
    action: Optional[str]

    # 创建流程阶段 (子图使用)
    creation_stage: Optional[Literal[
        "start",
        "collect_name",
        "collect_triggers",
        "collect_step",
        "confirm",
        "save"
    ]]

    # 工作流草稿字段 (子图使用)
    draft_name: Optional[str]
    draft_description: Optional[str]
    draft_triggers: list[str]
    draft_required_inputs: list[str]
    draft_optional_inputs: list[str]
    draft_steps: list[dict]
    draft_output_format: Optional[str]


def get_initial_state(load_workflows: bool = True) -> ConversationState:
    """
    获取初始状态

    Args:
        load_workflows: 是否从 skills 目录加载已保存的工作流，默认 True
    """
    # 加载已保存的工作流
    if load_workflows:
        initial_collection = load_all_workflows()
        workflow_collection = initial_collection.model_dump()
    else:
        workflow_collection = {"workflows": {}}

    return {
        "messages": [],
        "route": None,
        "workflow_collection": workflow_collection,
        "matched_workflow_id": None,
        # workflow_execution 子图状态字段（初始值）
        "execution_stage": None,
        "current_step_index": 0,
        "step_results": [],
        "execution_workflow_id": None,
        "collected_inputs": {},
        "initial_user_input": None,
        # workflow_skills 子图状态字段（初始值）
        "action": None,
        "creation_stage": None,
        "draft_name": None,
        "draft_description": None,
        "draft_triggers": [],
        "draft_required_inputs": [],
        "draft_optional_inputs": [],
        "draft_steps": [],
        "draft_output_format": None,
    }
