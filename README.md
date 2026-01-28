# 🤖 智能工作流 Agent

基于 LangGraph + Claude 的可定制工作流系统，支持通过自然语言对话创建和执行自定义工作流。

## ✨ 特性

- **图形化界面**：基于 Gradio 的现代化 Web UI
- **主动引导创建**：通过对话式引导帮助用户定义工作流
- **混合存储结构**：Skill（自然语言）+ JSON Schema（结构化）
- **工作流执行**：自动匹配并执行已创建的工作流
- **导入导出**：支持工作流配置的备份和迁移

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    Gradio UI                            │
├─────────────────────────────────────────────────────────┤
│                   LangGraph State Machine               │
│  ┌─────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │ Router  │→ │ Workflow     │→ │ Execute         │    │
│  │         │  │ Creator      │  │ Workflow        │    │
│  └─────────┘  └──────────────┘  └─────────────────┘    │
│       ↓                                                 │
│  ┌─────────────────┐                                   │
│  │ General Chat    │                                   │
│  └─────────────────┘                                   │
├─────────────────────────────────────────────────────────┤
│              Workflow Storage (Skill + Schema)          │
└─────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
workflow-agent/
├── app.py              # Gradio 图形界面应用
├── graph.py            # LangGraph 状态机和节点定义
├── schemas.py          # Pydantic Schema 定义
├── requirements.txt    # 项目依赖
├── skills/             # Skill 文档目录
│   └── weekly_report_skill.md  # 示例 Skill
└── README.md           # 项目说明
```

## 🚀 快速开始

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

## 📖 使用指南

### 创建工作流

1. 输入「我要创建XX流程」（如：我要创建周报流程）
2. 按照 Agent 的引导回答问题：
   - 工作流名称和描述
   - 触发短语
   - 所属领域
   - 必需输入信息
   - 执行步骤
   - 输出格式
3. 确认生成的工作流定义
4. 完成创建

### 执行工作流

当你的输入匹配已创建工作流的触发短语时，Agent 会自动执行对应工作流。

### 管理工作流

- 「查看所有流程」- 列出已创建的工作流
- 右侧面板可导入/导出工作流配置

## 🔧 核心概念

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

## 🔄 状态机流程

```
用户输入
    │
    ▼
┌───────────┐
│  Router   │ ← 判断意图
└───────────┘
    │
    ├─「创建XX流程」──→ Workflow Creator ──→ 引导创建
    │
    ├─「查看流程」────→ List Workflows ────→ 显示列表
    │
    ├─ 匹配触发词 ───→ Execute Workflow ──→ 执行工作流
    │
    └─ 其他 ────────→ General Chat ──────→ 普通对话
```

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| ANTHROPIC_API_KEY | Claude API 密钥 | ✅ |

### 端口配置

默认端口 7860，可在 `app.py` 中修改：

```python
app.launch(
    server_name="0.0.0.0",
    server_port=7860,  # 修改这里
)
```

## 📝 扩展开发

### 添加新的动作类型

在 `schemas.py` 中扩展 `ActionType`：

```python
class ActionType(str, Enum):
    COLLECT = "collect"
    ANALYZE = "analyze"
    # 添加新类型
    SEARCH_WEB = "search_web"
    CALL_API = "call_api"
```

### 添加新的节点

在 `graph.py` 中添加节点函数并注册：

```python
def my_custom_node(state: ConversationState) -> ConversationState:
    # 自定义逻辑
    return state

# 在 build_graph() 中注册
workflow.add_node("my_node", my_custom_node)
```

## 🐛 常见问题

**Q: 提示 API Key 错误？**
A: 确保正确设置了 `ANTHROPIC_API_KEY` 环境变量。

**Q: 工作流没有被触发？**
A: 检查输入是否包含工作流的触发短语，触发匹配区分大小写。

**Q: 如何持久化工作流？**
A: 使用界面右侧的导出功能，将 JSON 保存到文件。下次启动时导入即可。

## 📄 License

MIT License
