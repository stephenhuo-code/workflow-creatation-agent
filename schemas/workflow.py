"""
工作流 Schema 定义
使用 Pydantic 定义工作流的 JSON Schema 结构
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class ActionType(str, Enum):
    """步骤动作类型"""
    COLLECT = "collect"          # 收集信息
    ANALYZE = "analyze"          # 分析处理
    GENERATE = "generate"        # 生成内容
    VALIDATE = "validate"        # 验证确认
    TRANSFORM = "transform"      # 转换格式
    CALL_TOOL = "call_tool"      # 调用外部工具
    CONDITIONAL = "conditional"  # 条件判断


class OutputFormat(str, Enum):
    """输出格式类型"""
    MARKDOWN = "markdown"
    JSON = "json"
    TABLE = "table"
    PLAIN_TEXT = "plain_text"
    HTML = "html"


class WorkflowStep(BaseModel):
    """工作流单个步骤"""
    step_id: str = Field(description="步骤唯一标识")
    action: ActionType = Field(description="步骤动作类型")
    description: str = Field(description="步骤描述")
    inputs: list[str] = Field(default_factory=list, description="该步骤需要的输入")
    outputs: list[str] = Field(default_factory=list, description="该步骤产出")
    prompt_template: Optional[str] = Field(default=None, description="执行该步骤时的提示词模板")
    condition: Optional[str] = Field(default=None, description="条件判断表达式（仅 CONDITIONAL 类型）")
    next_step_on_true: Optional[str] = Field(default=None, description="条件为真时的下一步")
    next_step_on_false: Optional[str] = Field(default=None, description="条件为假时的下一步")


class WorkflowSchema(BaseModel):
    """工作流 JSON Schema 定义"""
    workflow_id: str = Field(description="工作流唯一标识")
    name: str = Field(description="工作流名称")
    description: str = Field(description="工作流描述")
    trigger_phrases: list[str] = Field(description="触发短语列表")
    domain: str = Field(default="通用", description="所属领域（可选）")
    required_inputs: list[str] = Field(default_factory=list, description="必需的输入字段（可选）")
    optional_inputs: list[str] = Field(default_factory=list, description="可选的输入字段")
    output_format: OutputFormat = Field(default=OutputFormat.MARKDOWN, description="输出格式")
    steps: list[WorkflowStep] = Field(description="工作流步骤列表")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")

    def to_skill_text(self) -> str:
        """将 Schema 转换为 Skill 文本格式"""
        skill_text = f"""## {self.name}

### 概述
{self.description}

### 触发条件
当用户表达以下意图时触发此工作流：
{chr(10).join(f'- "{phrase}"' for phrase in self.trigger_phrases)}

### 必需信息
{chr(10).join(f'- {inp}' for inp in self.required_inputs) if self.required_inputs else '无特定要求'}

### 可选信息
{chr(10).join(f'- {inp}' for inp in self.optional_inputs) if self.optional_inputs else '无'}

### 执行步骤
"""
        for i, step in enumerate(self.steps, 1):
            skill_text += f"\n**步骤 {i}: {step.description}**\n"
            skill_text += f"- 动作类型: {step.action.value}\n"
            if step.inputs:
                skill_text += f"- 输入: {', '.join(step.inputs)}\n"
            if step.outputs:
                skill_text += f"- 输出: {', '.join(step.outputs)}\n"
            if step.prompt_template:
                skill_text += f"- 执行要点: {step.prompt_template}\n"

        skill_text += f"\n### 输出格式\n{self.output_format.value}\n"

        return skill_text

    def to_markdown_file(self) -> str:
        """生成带 YAML frontmatter 的完整 markdown 文件"""
        import yaml

        # 准备 frontmatter 数据
        metadata = {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "trigger_phrases": self.trigger_phrases,
            "domain": self.domain,
            "required_inputs": self.required_inputs,
            "optional_inputs": self.optional_inputs,
            "output_format": self.output_format.value,
            "steps": [
                {
                    "step_id": s.step_id,
                    "action": s.action.value,
                    "description": s.description,
                    "inputs": s.inputs,
                    "outputs": s.outputs,
                    "prompt_template": s.prompt_template
                }
                for s in self.steps
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

        frontmatter = yaml.dump(metadata, allow_unicode=True, default_flow_style=False)
        skill_content = self.to_skill_text()

        return f"---\n{frontmatter}---\n\n{skill_content}"


class WorkflowCollection(BaseModel):
    """工作流集合"""
    workflows: dict[str, WorkflowSchema] = Field(default_factory=dict, description="工作流字典")

    def add_workflow(self, workflow: WorkflowSchema) -> None:
        self.workflows[workflow.workflow_id] = workflow

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowSchema]:
        return self.workflows.get(workflow_id)

    def find_by_trigger(self, user_input: str) -> Optional[WorkflowSchema]:
        """根据用户输入匹配工作流"""
        user_input_lower = user_input.lower()
        for workflow in self.workflows.values():
            for phrase in workflow.trigger_phrases:
                if phrase.lower() in user_input_lower:
                    return workflow
        return None

    def delete_workflow(self, workflow_id: str) -> Optional[WorkflowSchema]:
        """删除工作流，返回被删除的工作流（如果存在）"""
        if workflow_id in self.workflows:
            deleted = self.workflows.pop(workflow_id)
            return deleted
        return None

    def list_workflows(self) -> list[dict]:
        """列出所有工作流摘要"""
        return [
            {
                "id": w.workflow_id,
                "name": w.name,
                "triggers": w.trigger_phrases,
                "domain": w.domain
            }
            for w in self.workflows.values()
        ]
