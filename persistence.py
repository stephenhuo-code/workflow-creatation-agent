"""
工作流持久化模块
负责将工作流保存到 skills/ 目录并从中加载
"""

import os
import json
from pathlib import Path
from typing import Optional

from schemas import WorkflowSchema, WorkflowCollection


# 默认 skills 目录
SKILLS_DIR = Path(__file__).parent / "skills"


def ensure_skills_dir() -> Path:
    """确保 skills 目录存在"""
    SKILLS_DIR.mkdir(exist_ok=True)
    return SKILLS_DIR


def save_workflow(workflow: WorkflowSchema, generate_markdown: bool = True) -> str:
    """
    保存工作流到 skills 目录

    Args:
        workflow: 工作流对象
        generate_markdown: 是否同时生成 markdown skill 文件

    Returns:
        保存的 JSON 文件路径
    """
    skills_dir = ensure_skills_dir()

    # 保存 JSON 文件
    json_path = skills_dir / f"{workflow.workflow_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(workflow.model_dump(), f, ensure_ascii=False, indent=2)

    # 生成 markdown skill 文件
    if generate_markdown:
        md_path = skills_dir / f"{workflow.workflow_id}_skill.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(workflow.to_skill_text())

    return str(json_path)


def load_workflow(workflow_id: str) -> Optional[WorkflowSchema]:
    """
    从 skills 目录加载单个工作流

    Args:
        workflow_id: 工作流 ID

    Returns:
        工作流对象，如果不存在则返回 None
    """
    json_path = SKILLS_DIR / f"{workflow_id}.json"

    if not json_path.exists():
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return WorkflowSchema(**data)
    except (json.JSONDecodeError, Exception) as e:
        print(f"加载工作流 {workflow_id} 失败: {e}")
        return None


def load_all_workflows() -> WorkflowCollection:
    """
    从 skills 目录加载所有工作流

    Returns:
        包含所有工作流的 WorkflowCollection
    """
    collection = WorkflowCollection()

    if not SKILLS_DIR.exists():
        return collection

    # 遍历所有 .json 文件
    for json_file in SKILLS_DIR.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            workflow = WorkflowSchema(**data)
            collection.add_workflow(workflow)
            print(f"已加载工作流: {workflow.name} ({workflow.workflow_id})")
        except (json.JSONDecodeError, Exception) as e:
            print(f"加载工作流文件 {json_file.name} 失败: {e}")

    return collection


def delete_workflow(workflow_id: str) -> bool:
    """
    删除工作流文件

    Args:
        workflow_id: 工作流 ID

    Returns:
        是否成功删除
    """
    json_path = SKILLS_DIR / f"{workflow_id}.json"
    md_path = SKILLS_DIR / f"{workflow_id}_skill.md"

    deleted = False

    if json_path.exists():
        json_path.unlink()
        deleted = True

    if md_path.exists():
        md_path.unlink()

    return deleted
