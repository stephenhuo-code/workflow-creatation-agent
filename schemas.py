"""
工作流 Schema 定义（兼容层）
此文件保留用于向后兼容，实际实现已迁移到 schemas/ 模块

已迁移至: schemas/workflow.py
"""

# 从新模块重新导出，保持向后兼容
from schemas.workflow import (
    ActionType,
    OutputFormat,
    WorkflowStep,
    WorkflowSchema,
    WorkflowCollection
)

__all__ = [
    "ActionType",
    "OutputFormat",
    "WorkflowStep",
    "WorkflowSchema",
    "WorkflowCollection"
]
