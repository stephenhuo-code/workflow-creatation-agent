"""
Workflow Execution 子图
负责工作流的步骤级执行，每次处理一个步骤

架构：
execute_workflow (子图)
    │
    ├─ 入口路由（根据 execution_stage）
    │     │
    │     ├─ 新执行 → start_execution     # 初始化，准备第一个步骤
    │     │               │
    │     │               ▼
    │     └─ wait_input → receive_input   # 接收用户输入（collect 步骤）
    │                         │
    │                         ▼
    ├─→ process_step ◄────────┴───┐   # 循环：每次处理一个步骤
    │         │                   │
    │         ├─ 还有下一步 ───────┘
    │         │
    │         ├─ collect 且无输入 → wait_input → END（暂停等待）
    │         │
    │         ▼ 所有步骤完成
    └─→ finalize_execution  # 整合输出
              │
              ▼
             END

Human-in-the-loop 机制：
- collect 类型步骤会设置 execution_stage="wait_input" 并退出子图
- 用户输入后，Supervisor 识别 wait_input 状态，路由回 execute_workflow
- 子图入口路由到 receive_input 节点，保存输入后继续 process_step
"""

import os
from typing import Annotated, TypedDict, Literal, Optional, List

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from schemas import WorkflowCollection, WorkflowSchema
from utils.logger import setup_logger

# 模块日志
logger = setup_logger("WorkflowExecutionSubgraph")


# ============================================================
# 子图状态定义
# ============================================================

class WorkflowExecutionState(TypedDict):
    """Workflow Execution 子图状态"""
    messages: Annotated[list, add_messages]

    # 工作流集合（从主图传入）
    workflow_collection: dict

    # 执行工作流时的匹配 ID（从主图传入）
    matched_workflow_id: Optional[str]

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

def _get_last_user_message(state: WorkflowExecutionState) -> str:
    """获取最后一条用户消息"""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def _get_workflow(state: WorkflowExecutionState) -> Optional[WorkflowSchema]:
    """从状态中获取正在执行的工作流"""
    workflow_id = state.get("execution_workflow_id") or state.get("matched_workflow_id")
    if not workflow_id:
        return None

    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))
    return collection.get_workflow(workflow_id)


def _format_previous_results(step_results: List[dict]) -> str:
    """格式化之前步骤的结果"""
    if not step_results:
        return "（这是第一个步骤，没有之前的结果）"

    formatted = []
    for i, result in enumerate(step_results):
        formatted.append(f"**步骤 {i + 1}** ({result.get('step_id', 'unknown')}):\n{result.get('result', '无结果')}")

    return "\n\n".join(formatted)


# ============================================================
# 节点函数
# ============================================================

def start_execution_node(state: WorkflowExecutionState) -> dict:
    """初始化执行状态，准备第一个步骤"""
    logger.info("▶ 节点: start_execution | 初始化工作流执行")

    workflow_id = state.get("matched_workflow_id")
    collection = WorkflowCollection(**state.get("workflow_collection", {"workflows": {}}))

    # 尝试通过 ID 获取工作流
    workflow = collection.get_workflow(workflow_id) if workflow_id else None

    # 获取用户输入
    user_input = _get_last_user_message(state)

    # 如果没有匹配到，尝试通过触发词查找
    if not workflow:
        workflow = collection.find_by_trigger(user_input)

    if not workflow:
        logger.warning("◀ 节点: start_execution | 未找到工作流")
        return {
            "messages": [AIMessage(content="抱歉，未找到匹配的工作流。请检查触发词或工作流是否存在。")],
            "execution_stage": None,
            "matched_workflow_id": None
        }

    step_count = len(workflow.steps)
    logger.info(f"  工作流: {workflow.name}, 共 {step_count} 个步骤")

    return {
        "messages": [AIMessage(content=f"开始执行「{workflow.name}」，共 {step_count} 个步骤...\n")],
        "execution_stage": "process_step",
        "current_step_index": 0,
        "step_results": [],
        "execution_workflow_id": workflow.workflow_id,
        "collected_inputs": {},
        "initial_user_input": user_input  # 保存原始用户输入
    }


def process_step_node(state: WorkflowExecutionState) -> dict:
    """处理单个步骤（循环核心）

    对于 collect 类型步骤：
    - 如果已有用户输入，使用该输入继续执行
    - 如果没有用户输入，暂停并请求用户输入（设置 execution_stage="wait_input"）

    对于 generate/analyze 类型步骤：
    - 直接调用 LLM 执行
    """
    current_index = state.get("current_step_index", 0)
    logger.info(f"▶ 节点: process_step | 执行步骤 {current_index + 1}")

    workflow = _get_workflow(state)
    if not workflow:
        logger.error("◀ 节点: process_step | 工作流丢失")
        return {
            "messages": [AIMessage(content="执行出错：工作流状态丢失。")],
            "execution_stage": None
        }

    step = workflow.steps[current_index]
    total_steps = len(workflow.steps)
    step_results = list(state.get("step_results", []))
    collected_inputs = dict(state.get("collected_inputs", {}))

    # 获取初始用户输入（用于 generate/analyze 步骤的上下文）
    initial_input = state.get("initial_user_input") or _get_last_user_message(state)

    # ============================================================
    # 处理 collect 类型步骤
    # ============================================================
    if step.action.value == "collect":
        # 检查是否已收集该步骤的用户输入
        if step.step_id in collected_inputs:
            # 使用已收集的输入
            user_provided_input = collected_inputs[step.step_id]
            logger.info(f"  collect 步骤 {step.step_id} 使用已收集的输入: {user_provided_input[:50]}...")

            step_results.append({
                "step_id": step.step_id,
                "step_description": step.description,
                "result": user_provided_input
            })

            # 判断是否继续循环
            if current_index + 1 < total_steps:
                logger.info(f"◀ 节点: process_step | 步骤 {current_index + 1} (collect) 完成，继续下一步")
                return {
                    "messages": [AIMessage(content=f"✓ 步骤 {current_index + 1}/{total_steps} 完成: {step.description}")],
                    "execution_stage": "process_step",
                    "current_step_index": current_index + 1,
                    "step_results": step_results,
                    "collected_inputs": collected_inputs
                }
            else:
                logger.info(f"◀ 节点: process_step | 步骤 {current_index + 1} (collect) 完成，所有步骤执行完毕")
                return {
                    "messages": [AIMessage(content=f"✓ 步骤 {current_index + 1}/{total_steps} 完成: {step.description}")],
                    "execution_stage": "finalize",
                    "step_results": step_results,
                    "collected_inputs": collected_inputs
                }
        else:
            # 暂停，等待用户输入
            prompt_text = step.prompt_template or step.description
            logger.info(f"◀ 节点: process_step | 步骤 {current_index + 1} (collect) 暂停等待用户输入")
            return {
                "messages": [AIMessage(content=f"**步骤 {current_index + 1}/{total_steps}: {step.description}**\n\n请输入: {prompt_text}")],
                "execution_stage": "wait_input"  # 标记暂停等待用户输入
            }

    # ============================================================
    # 处理 generate/analyze 等 LLM 执行类型步骤
    # ============================================================
    previous_results = _format_previous_results(step_results)

    step_prompt = f"""你正在执行工作流「{workflow.name}」的第 {current_index + 1}/{total_steps} 步。

## 当前步骤
- **步骤 ID**: {step.step_id}
- **动作类型**: {step.action.value}
- **描述**: {step.description}
{f'- **执行要点**: {step.prompt_template}' if step.prompt_template else ''}

## 用户原始输入
{initial_input}

## 之前步骤的执行结果
{previous_results}

## 执行指令
1. 基于之前步骤收集的信息完成本步骤的任务
2. 输出应该简洁明了，聚焦于本步骤的目标"""

    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=step_prompt),
        HumanMessage(content=f"请执行步骤 {current_index + 1}: {step.description}")
    ])

    # 保存结果
    step_results.append({
        "step_id": step.step_id,
        "step_description": step.description,
        "result": response.content
    })

    # 判断是否继续循环
    if current_index + 1 < total_steps:
        logger.info(f"◀ 节点: process_step | 步骤 {current_index + 1} 完成，继续下一步")
        return {
            "messages": [AIMessage(content=f"✓ 步骤 {current_index + 1}/{total_steps} 完成: {step.description}")],
            "execution_stage": "process_step",  # 保持循环
            "current_step_index": current_index + 1,
            "step_results": step_results,
            "collected_inputs": collected_inputs
        }
    else:
        logger.info(f"◀ 节点: process_step | 步骤 {current_index + 1} 完成，所有步骤执行完毕")
        return {
            "messages": [AIMessage(content=f"✓ 步骤 {current_index + 1}/{total_steps} 完成: {step.description}")],
            "execution_stage": "finalize",  # 退出循环
            "step_results": step_results,
            "collected_inputs": collected_inputs
        }


def receive_input_node(state: WorkflowExecutionState) -> dict:
    """接收用户输入，保存到 collected_inputs，然后继续执行"""
    logger.info("▶ 节点: receive_input | 接收用户输入")

    workflow = _get_workflow(state)
    if not workflow:
        logger.error("◀ 节点: receive_input | 工作流丢失")
        return {
            "messages": [AIMessage(content="执行出错：工作流状态丢失。")],
            "execution_stage": None
        }

    current_index = state.get("current_step_index", 0)
    current_step = workflow.steps[current_index]

    # 获取用户刚输入的内容
    user_input = _get_last_user_message(state)

    # 保存到 collected_inputs
    collected_inputs = dict(state.get("collected_inputs", {}))
    collected_inputs[current_step.step_id] = user_input

    logger.info(f"◀ 节点: receive_input | 已收到步骤 {current_step.step_id} 的输入: {user_input[:50]}...")

    return {
        "messages": [AIMessage(content=f"✓ 已收到: {user_input}")],
        "execution_stage": "process_step",  # 继续执行 process_step
        "collected_inputs": collected_inputs
    }


def finalize_execution_node(state: WorkflowExecutionState) -> dict:
    """整合所有步骤结果，生成最终输出"""
    logger.info("▶ 节点: finalize_execution | 整合最终输出")

    workflow = _get_workflow(state)
    step_results = state.get("step_results", [])

    if not workflow:
        logger.error("◀ 节点: finalize_execution | 工作流丢失")
        return {
            "messages": [AIMessage(content="执行完成，但工作流信息丢失。")],
            "execution_stage": None,
            "current_step_index": 0,
            "step_results": [],
            "execution_workflow_id": None,
            "matched_workflow_id": None
        }

    # 只输出最后一个步骤的结果
    if step_results:
        last_result = step_results[-1].get("result", "")
        final_output = f"**执行完成！**\n\n{last_result}"
    else:
        final_output = "**执行完成！**\n\n（无输出结果）"

    logger.info(f"◀ 节点: finalize_execution | 完成，共 {len(step_results)} 个步骤")
    return {
        "messages": [AIMessage(content=final_output)],
        "execution_stage": None,
        "current_step_index": 0,
        "step_results": [],
        "execution_workflow_id": None,
        "matched_workflow_id": None,  # 清除匹配 ID
        "collected_inputs": {},  # 清除收集的输入
        "initial_user_input": None  # 清除初始输入
    }


# ============================================================
# 路由函数
# ============================================================

def _route_entry_point(state: WorkflowExecutionState) -> str:
    """入口路由：判断是新执行还是继续等待输入的执行"""
    stage = state.get("execution_stage")
    logger.debug(f"执行入口路由 | stage={stage}")

    if stage == "wait_input":
        # 用户刚输入了等待的数据，路由到 receive_input
        return "receive_input"
    else:
        # 新的执行，从 start 开始
        return "start"


def _route_execution_stage(state: WorkflowExecutionState) -> str:
    """根据 execution_stage 路由到对应节点"""
    stage = state.get("execution_stage")
    logger.debug(f"执行流程路由 | stage={stage}")

    if stage == "process_step":
        return "process_step"
    elif stage == "finalize":
        return "finalize"
    elif stage == "wait_input":
        # wait_input 时暂停，退出子图等待用户输入
        return END
    else:
        # execution_stage 为 None 时，直接结束
        return END


# ============================================================
# 构建执行子图
# ============================================================

def build_workflow_execution_subgraph():
    """
    构建工作流执行子图

    结构：
    入口路由：
    - 新执行 → start → process_step (循环) → finalize → END
    - wait_input 状态 → receive_input → process_step (继续循环)

    collect 步骤会设置 execution_stage="wait_input" 并退出到 END，
    下次用户输入后会通过入口路由进入 receive_input 节点。
    """
    logger.info("构建 workflow_execution 子图")

    graph = StateGraph(WorkflowExecutionState)

    # 添加节点
    graph.add_node("start", start_execution_node)
    graph.add_node("process_step", process_step_node)
    graph.add_node("receive_input", receive_input_node)
    graph.add_node("finalize", finalize_execution_node)

    # 设置条件入口点：根据 execution_stage 决定从哪里开始
    graph.set_conditional_entry_point(
        _route_entry_point,
        {
            "start": "start",
            "receive_input": "receive_input"
        }
    )

    # start → 路由（根据 execution_stage）
    graph.add_conditional_edges(
        "start",
        _route_execution_stage,
        {
            "process_step": "process_step",
            "finalize": "finalize",
            END: END
        }
    )

    # process_step → 循环路由（包括 wait_input 退出）
    graph.add_conditional_edges(
        "process_step",
        _route_execution_stage,
        {
            "process_step": "process_step",
            "finalize": "finalize",
            END: END  # wait_input 或 None 时退出
        }
    )

    # receive_input → process_step（继续执行下一步）
    graph.add_edge("receive_input", "process_step")

    # finalize → END
    graph.add_edge("finalize", END)

    return graph.compile()
