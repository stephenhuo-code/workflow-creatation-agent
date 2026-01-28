# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Workflow Agent is a conversational workflow automation system built with LangGraph for state machine orchestration and Claude AI for intelligent generation. Users create and execute custom workflows through a Gradio-based web UI.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (starts Gradio server at http://localhost:7860)
python app.py

# Required environment variable
export ANTHROPIC_API_KEY="your-api-key"
```

Note: This project has no test suite, linting configuration, or CI/CD setup.

## Architecture

### Core Files

- **app.py** - Gradio web UI (`WorkflowAgentApp` class handles chat, workflow management, import/export)
- **graph.py** - LangGraph state machine with nodes for workflow creation stages, execution, and general chat
- **schemas.py** - Pydantic models: `WorkflowSchema`, `WorkflowStep`, `WorkflowCollection`, plus `ActionType` and `OutputFormat` enums

### State Machine Flow

```
User Input → entry_router
  ├─→ "创建XX流程" → creation_router → staged collection (name → triggers → steps → inputs → output_format → confirm → save)
  ├─→ "查看流程" → list_workflows
  ├─→ Trigger match → execute_workflow
  └─→ Other → general_chat
```

### Key Patterns

1. **Hybrid Storage Model**: Workflows stored as both JSON schema (`WorkflowSchema`) and natural language skill text (`to_skill_text()`). The skill text format is used when executing workflows with Claude.

2. **Trigger-Based Routing**: `WorkflowCollection.find_by_trigger()` uses substring matching (case-insensitive) to match user input to workflows.

3. **Staged Creation Process**: Workflow creation happens through explicit stages defined in `creation_stage` field, with each stage having its own node in the graph.

4. **State Structure**: `ConversationState` TypedDict includes `messages` (with LangChain's `add_messages` reducer), `current_mode`, `creation_stage`, draft fields for in-progress workflows, and `workflow_collection`.

### Model

Uses `claude-sonnet-4-20250514` via `langchain-anthropic`.

## Extension Points

- Add action types: Extend `ActionType` enum in `schemas.py`
- Add output formats: Extend `OutputFormat` enum in `schemas.py`
- Add workflow stages: Create node function in `graph.py` and register in `build_graph()`
