# 智能工作流 Agent

基于 LangGraph + Claude 的可定制工作流系统，支持通过自然语言对话创建和执行自定义工作流。

## 特性

- **双层 Agent 架构**：Supervisor Agent + Workflow Skills Agent 分层决策
- **图形化界面**：基于 Gradio 的现代化 Web UI
- **主动引导创建**：通过对话式引导帮助用户定义工作流
- **混合存储结构**：Skill（自然语言）+ JSON Schema（结构化）
- **工作流执行**：自动匹配并执行已创建的工作流
- **导入导出**：支持工作流配置的备份和迁移

## 架构设计

### 双层 Agent 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户输入                                 │
│                            ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │               Supervisor Agent (主控 Agent)              │    │
│  │  识别用户意图，决定走向：                                 │    │
│  │                                                         │    │
│  │  1. 工作流管理操作？ ──────→ Workflow Skills Agent       │    │
│  │     (创建/删除/查看流程)         ↓                       │    │
│  │                              创建/删除/查看/执行工作流    │    │
│  │                                                         │    │
│  │  2. 匹配已有 Skill？ ─────→ 执行对应 Workflow            │    │
│  │     (触发词匹配)                                         │    │
│  │                                                         │    │
│  │  3. 无匹配 ───────────────→ 通用对话                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Gradio UI (app.py)                     │
├─────────────────────────────────────────────────────────────┤
│                    LangGraph State Machine                  │
│  ┌──────────────────┐  ┌──────────────────────────────┐    │
│  │ Supervisor Agent │→ │ Workflow Skills Agent        │    │
│  │ (意图分类)        │  │ (CRUD 操作分类)              │    │
│  └──────────────────┘  └──────────────────────────────┘    │
│           ↓                         ↓                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Workflow Creator  │  Execute  │  List  │  Delete    │  │
│  └──────────────────────────────────────────────────────┘  │
│           ↓                                                 │
│  ┌─────────────────┐                                       │
│  │ General Chat    │                                       │
│  └─────────────────┘                                       │
├─────────────────────────────────────────────────────────────┤
│              Workflow Storage (Skill + Schema)              │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构

```
workflow-agent/
├── app.py                      # Gradio 图形界面应用
├── agents/                     # Agent 模块
│   ├── __init__.py
│   ├── supervisor.py           # Supervisor Agent（主控）
│   └── workflow_skills.py      # Workflow Skills Agent
├── graph/                      # LangGraph 状态机
│   ├── __init__.py
│   ├── state.py                # ConversationState 定义
│   ├── nodes.py                # 所有节点函数
│   └── builder.py              # build_graph() 函数
├── schemas/                    # 数据模型
│   ├── __init__.py
│   └── workflow.py             # WorkflowSchema, WorkflowCollection
├── persistence/                # 持久化
│   ├── __init__.py
│   └── storage.py              # 存储逻辑
├── skills/                     # 生成的 workflow skills
├── requirements.txt            # 项目依赖
├── graph.py                    # 兼容层（重导出）
├── schemas.py                  # 兼容层（重导出）
├── persistence.py              # 兼容层（重导出）
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 设置环境变量

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

### 3. 启动应用

```bash
python app.py
```

访问 http://localhost:7860 打开界面。

## 使用指南

### 创建工作流

1. 输入「我要创建XX流程」（如：我要创建周报流程）
2. 按照 Agent 的引导回答问题：
   - 工作流名称和描述
   - 触发短语
   - 执行步骤
3. 确认生成的工作流定义
4. 完成创建

### 执行工作流

当你的输入匹配已创建工作流的触发短语时，Agent 会自动执行对应工作流。

### 管理工作流

- 「查看所有流程」- 列出已创建的工作流
- 「删除XX流程」- 删除指定工作流
- 右侧面板可导入/导出工作流配置

## 核心概念

### Supervisor Agent

主控 Agent，负责识别用户意图：

| 意图类型 | 说明 | 示例 |
|----------|------|------|
| `workflow_management` | 工作流管理操作 | "创建一个周报流程"、"删除XX流程" |
| `skill_execution` | 执行已有工作流 | "帮我写周报"（匹配触发词） |
| `general_chat` | 普通对话 | "你好"、"写段代码" |

### Workflow Skills Agent

工作流技能 Agent，负责识别具体操作：

| 操作类型 | 说明 | 路由目标 |
|----------|------|----------|
| `create` | 创建新工作流 | `start_creation` |
| `delete` | 删除工作流 | `delete_workflow` |
| `list` | 查看工作流列表 | `list_workflows` |
| `execute` | 执行工作流 | `execute_workflow` |

### Skill（技能文档）

自然语言描述的执行策略，包含：
- 执行原则和判断逻辑
- 语气和风格要求
- 特殊情况处理

示例：
```markdown
## 周报生成技能

当用户需要写周报时：
1. 先询问本周主要做了什么，如果用户说得太笼统，追问具体产出
2. 了解遇到的困难，注意区分「已解决」和「待解决」
3. 生成时注意：语气正式但不僵硬，突出成果而非过程
```

### JSON Schema

结构化的工作流定义，包含：
- 触发条件
- 必需/可选输入
- 步骤序列
- 输出格式

示例：
```json
{
  "name": "周报生成",
  "trigger_phrases": ["写周报", "生成周报"],
  "required_inputs": ["本周完成事项", "下周计划"],
  "steps": [
    {"action": "collect", "description": "收集信息"},
    {"action": "generate", "description": "生成周报"}
  ],
  "output_format": "markdown"
}
```

## 状态机流程

```
用户输入
    │
    ▼
┌───────────────────┐
│ Supervisor Agent  │ ← 判断意图类型
└───────────────────┘
    │
    ├─ workflow_management ──→ Workflow Skills Agent
    │                              │
    │                              ├─ create ──→ 引导创建
    │                              ├─ delete ──→ 删除工作流
    │                              └─ list ────→ 显示列表
    │
    ├─ skill_execution ──────→ Execute Workflow ──→ 执行工作流
    │
    └─ general_chat ─────────→ General Chat ──────→ 普通对话
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| ANTHROPIC_API_KEY | Claude API 密钥 | 是 |

### 端口配置

默认端口 7860，可在 `app.py` 中修改：

```python
app.launch(
    server_name="0.0.0.0",
    server_port=7860,  # 修改这里
)
```

## 扩展开发

### 添加新的动作类型

在 `schemas/workflow.py` 中扩展 `ActionType`：

```python
class ActionType(str, Enum):
    COLLECT = "collect"
    ANALYZE = "analyze"
    # 添加新类型
    SEARCH_WEB = "search_web"
    CALL_API = "call_api"
```

### 添加新的节点

在 `graph/nodes.py` 中添加节点函数：

```python
def my_custom_node(state: ConversationState) -> dict:
    # 自定义逻辑
    return {"messages": [AIMessage(content="...")]}
```

在 `graph/builder.py` 中注册：

```python
workflow.add_node("my_node", my_custom_node)
```

### 添加新的 Agent

在 `agents/` 目录创建新文件：

```python
# agents/my_agent.py
def my_agent(state: dict) -> dict:
    """自定义 Agent 逻辑"""
    # 使用 LLM 进行意图分类
    # 返回路由决策
    return {"route": "target_node", ...}
```

在 `agents/__init__.py` 中导出：

```python
from .my_agent import my_agent
```

## 常见问题

**Q: 提示 API Key 错误？**
A: 确保正确设置了 `ANTHROPIC_API_KEY` 环境变量。

**Q: 工作流没有被触发？**
A: 检查输入是否包含工作流的触发短语。Supervisor Agent 会先尝试精确匹配，再使用 LLM 判断。

**Q: 如何持久化工作流？**
A: 工作流会自动保存到 `skills/` 目录。也可使用界面右侧的导出功能备份 JSON。

**Q: 误触发了工作流怎么办？**
A: 双层 Agent 架构大幅降低了误触发概率。如果仍有问题，可以调整 `agents/supervisor.py` 中的 prompt。

## License

MIT License
