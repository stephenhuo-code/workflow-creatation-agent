"""
工作流持久化模块
负责将工作流保存到 skills/ 目录并从中加载
使用 YAML frontmatter 格式存储元数据
"""

import re
from pathlib import Path
from typing import Optional

import yaml

from schemas import WorkflowSchema, WorkflowCollection, WorkflowStep, ActionType, OutputFormat


# 默认 skills 目录
SKILLS_DIR = Path(__file__).parent / "skills"

# YAML frontmatter 正则匹配
FRONTMATTER_PATTERN = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)


def ensure_skills_dir() -> Path:
    """确保 skills 目录存在"""
    SKILLS_DIR.mkdir(exist_ok=True)
    return SKILLS_DIR


def save_workflow(workflow: WorkflowSchema) -> str:
    """
    保存工作流到 skills 目录（仅 markdown 文件）

    Args:
        workflow: 工作流对象

    Returns:
        保存的 markdown 文件路径
    """
    skills_dir = ensure_skills_dir()
    md_path = skills_dir / f"{workflow.workflow_id}_skill.md"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(workflow.to_markdown_file())

    return str(md_path)


def load_workflow(workflow_id: str) -> Optional[WorkflowSchema]:
    """
    从 skills 目录加载单个工作流

    Args:
        workflow_id: 工作流 ID

    Returns:
        工作流对象，如果不存在则返回 None
    """
    md_path = SKILLS_DIR / f"{workflow_id}_skill.md"

    if not md_path.exists():
        return None

    try:
        content = md_path.read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(content)
        if match:
            data = yaml.safe_load(match.group(1))
            return _parse_workflow_data(data)
    except Exception as e:
        print(f"加载工作流 {workflow_id} 失败: {e}")

    return None


def _parse_workflow_data(data: dict) -> WorkflowSchema:
    """解析 YAML 数据为 WorkflowSchema 对象"""
    # 解析步骤
    steps = []
    for step_data in data.get("steps", []):
        steps.append(WorkflowStep(
            step_id=step_data.get("step_id", ""),
            action=ActionType(step_data.get("action", "generate")),
            description=step_data.get("description", ""),
            inputs=step_data.get("inputs", []),
            outputs=step_data.get("outputs", []),
            prompt_template=step_data.get("prompt_template")
        ))

    return WorkflowSchema(
        workflow_id=data.get("workflow_id", ""),
        name=data.get("name", ""),
        description=data.get("description", ""),
        trigger_phrases=data.get("trigger_phrases", []),
        domain=data.get("domain", "通用"),
        required_inputs=data.get("required_inputs", []),
        optional_inputs=data.get("optional_inputs", []),
        output_format=OutputFormat(data.get("output_format", "markdown")),
        steps=steps,
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at")
    )


def load_all_workflows() -> WorkflowCollection:
    """
    从 skills 目录加载所有工作流

    Returns:
        包含所有工作流的 WorkflowCollection
    """
    collection = WorkflowCollection()

    if not SKILLS_DIR.exists():
        return collection

    # 遍历所有 *_skill.md 文件
    for md_file in SKILLS_DIR.glob("*_skill.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            match = FRONTMATTER_PATTERN.match(content)
            if match:
                data = yaml.safe_load(match.group(1))
                workflow = _parse_workflow_data(data)
                collection.add_workflow(workflow)
                print(f"已加载工作流: {workflow.name} ({workflow.workflow_id})")
        except Exception as e:
            print(f"加载工作流文件 {md_file.name} 失败: {e}")

    return collection


def delete_workflow(workflow_id: str) -> bool:
    """
    删除工作流 markdown 文件

    Args:
        workflow_id: 工作流 ID

    Returns:
        是否成功删除
    """
    md_path = SKILLS_DIR / f"{workflow_id}_skill.md"

    if md_path.exists():
        md_path.unlink()
        return True

    return False
