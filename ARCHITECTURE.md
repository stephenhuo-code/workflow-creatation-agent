# LangGraph 图结构

## 主图 (Main Graph)

```mermaid
flowchart TB
    subgraph MainGraph["主图 (Main Graph)"]
        supervisor["supervisor<br/>入口节点"]

        supervisor --> |"_get_route()"| route_decision{{"路由决策"}}

        route_decision --> |"workflow_skills"| ws["workflow_skills<br/>(子图)"]
        route_decision --> |"execute_workflow"| ew["execute_workflow<br/>(子图)"]
        route_decision --> |"general_chat"| gc["general_chat"]

        ws --> END1["END"]
        ew --> END2["END"]
        gc --> END3["END"]
    end
```

## workflow_skills 子图

```mermaid
flowchart TB
    subgraph WorkflowSkills["workflow_skills 子图"]
        classify["classify<br/>入口节点"]

        classify --> |"_route_action()"| action_decision{{"action?"}}

        action_decision --> |"create"| cw["create_workflow<br/>(嵌套子图)"]
        action_decision --> |"delete"| dw["delete_workflow"]
        action_decision --> |"list"| lw["list_workflows"]

        cw --> END1["END"]
        dw --> END2["END"]
        lw --> END3["END"]
    end
```

## create_workflow 子图 (嵌套)

```mermaid
flowchart TB
    subgraph CreateWorkflow["create_workflow 子图"]
        router["router<br/>入口节点"]

        router --> |"_route_creation_stage()"| stage_decision{{"creation_stage?"}}

        stage_decision --> |"null/start"| start["start"]
        stage_decision --> |"collect_name"| cn["collect_name"]
        stage_decision --> |"collect_triggers"| ct["collect_triggers"]
        stage_decision --> |"collect_step"| cs["collect_step"]
        stage_decision --> |"confirm"| conf["confirm"]
        stage_decision --> |"save"| save["save"]

        start --> END1["END<br/>(等待用户输入)"]
        cn --> END2["END"]
        ct --> END3["END"]
        cs --> END4["END"]
        conf --> END5["END"]
        save --> END6["END"]
    end

    note["流程: start → collect_name → collect_triggers → collect_step(循环) → confirm → save"]
```

## execute_workflow 子图

```mermaid
flowchart TB
    subgraph ExecuteWorkflow["execute_workflow 子图"]
        entry{{"_route_entry_point()<br/>入口路由"}}

        entry --> |"新执行"| start["start_execution"]
        entry --> |"wait_input"| receive["receive_input"]

        start --> |"_route_execution_stage()"| stage1{{"stage?"}}

        stage1 --> |"process_step"| process["process_step"]
        stage1 --> |"finalize"| finalize["finalize_execution"]
        stage1 --> |"END"| END1["END"]

        receive --> process

        process --> |"_route_execution_stage()"| stage2{{"stage?"}}

        stage2 --> |"process_step"| process
        stage2 --> |"finalize"| finalize
        stage2 --> |"wait_input/END"| END2["END<br/>(暂停等待)"]

        finalize --> END3["END"]
    end
```

## 图结构层级关系

```mermaid
flowchart LR
    subgraph Main["Main Graph"]
        supervisor

        subgraph WS["workflow_skills"]
            classify
            list_workflows
            delete_workflow

            subgraph CW["create_workflow"]
                router
                start_c["start"]
                collect_name
                collect_triggers
                collect_step
                confirm
                save
            end
        end

        subgraph EW["execute_workflow"]
            start_e["start"]
            process_step
            receive_input
            finalize
        end

        general_chat
    end
```

## 关键路由逻辑

| 路由函数 | 位置 | 判断依据 |
|---------|------|---------|
| `_get_route()` | 主图 | `state.route` |
| `_route_action()` | workflow_skills | `state.action` (create/delete/list) |
| `_route_creation_stage()` | create_workflow | `state.creation_stage` |
| `_route_entry_point()` | execute_workflow | `state.execution_stage == "wait_input"` |
| `_route_execution_stage()` | execute_workflow | `state.execution_stage` |

## 文件对应关系

| 组件 | 文件路径 |
|-----|---------|
| 主图构建 | `graph/builder.py` |
| 主图状态 | `graph/state.py` |
| general_chat 节点 | `graph/nodes.py` |
| supervisor 节点 | `agents/supervisor.py` |
| workflow_skills 子图 | `graph/subgraphs/workflow_skills.py` |
| execute_workflow 子图 | `graph/subgraphs/workflow_execution.py` |

## Human-in-the-loop 机制

### 工作流创建 (create_workflow)

每个阶段处理完成后都会 `→ END`，暂停等待用户下一次输入。下次用户输入时，通过 `creation_stage` 状态路由到对应的阶段节点继续执行。

```mermaid
sequenceDiagram
    participant User
    participant Supervisor
    participant CreateWorkflow

    User->>Supervisor: "创建周报流程"
    Supervisor->>CreateWorkflow: route=workflow_skills, action=create
    CreateWorkflow->>CreateWorkflow: start → 询问名称
    CreateWorkflow-->>User: "请告诉我工作流名称"
    Note over CreateWorkflow: creation_stage=collect_name, END

    User->>Supervisor: "周报生成"
    Supervisor->>CreateWorkflow: 检测 creation_stage≠null
    CreateWorkflow->>CreateWorkflow: collect_name → 询问触发词
    CreateWorkflow-->>User: "请输入触发短语"
    Note over CreateWorkflow: creation_stage=collect_triggers, END

    User->>Supervisor: "写周报, 生成周报"
    Supervisor->>CreateWorkflow: 继续创建流程
    CreateWorkflow->>CreateWorkflow: collect_triggers → 收集步骤
    CreateWorkflow-->>User: "请输入第一个步骤"
    Note over CreateWorkflow: creation_stage=collect_step, END
```

### 工作流执行 (execute_workflow)

```mermaid
sequenceDiagram
    participant User
    participant Supervisor
    participant ExecuteWorkflow

    User->>Supervisor: "写周报"
    Supervisor->>ExecuteWorkflow: matched_workflow_id
    ExecuteWorkflow->>ExecuteWorkflow: start → process_step

    alt collect 类型步骤
        ExecuteWorkflow-->>User: "请提供本周工作内容"
        Note over ExecuteWorkflow: execution_stage=wait_input, END

        User->>Supervisor: "完成了项目A和B"
        Supervisor->>ExecuteWorkflow: 检测 wait_input 状态
        ExecuteWorkflow->>ExecuteWorkflow: receive_input → process_step
    end

    ExecuteWorkflow->>ExecuteWorkflow: 继续执行后续步骤...
    ExecuteWorkflow->>ExecuteWorkflow: finalize
    ExecuteWorkflow-->>User: 最终输出
```

## 状态字段说明

| 字段 | 类型 | 用途 |
|-----|------|-----|
| `messages` | `Annotated[list, add_messages]` | 对话历史 |
| `route` | `str` | 主图路由目标 |
| `action` | `str` | workflow_skills 操作类型 |
| `creation_stage` | `str` | 创建工作流当前阶段 |
| `execution_stage` | `str` | 执行工作流当前阶段 |
| `workflow_collection` | `dict` | 所有工作流集合 |
| `draft_*` | 各类型 | 创建中的工作流草稿字段 |
| `execution_*` | 各类型 | 执行中的工作流状态字段 |
