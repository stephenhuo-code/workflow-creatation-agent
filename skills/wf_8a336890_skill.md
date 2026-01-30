---
created_at: '2026-01-30T06:23:05.844617'
description: 自动生成工作周报的工作流程
domain: 通用
name: 周报生成
optional_inputs: []
output_format: json
required_inputs: []
steps:
- action: generate
  description: 选择信息源
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_1
- action: generate
  description: 选择总结维度
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_2
- action: generate
  description: 选择输出格式，默认为markdown
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_3
- action: generate
  description: 输出可下载的文档
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_4
trigger_phrases:
- 写周报
- 生成周报
- weekly report
- 本周总结
- 周报助手
updated_at: '2026-01-30T06:23:05.844624'
workflow_id: wf_8a336890
---

## 周报生成

### 概述
自动生成工作周报的工作流程

### 触发条件
当用户表达以下意图时触发此工作流：
- "写周报"
- "生成周报"
- "weekly report"
- "本周总结"
- "周报助手"

### 必需信息
无特定要求

### 可选信息
无

### 执行步骤

**步骤 1: 选择信息源**
- 动作类型: generate

**步骤 2: 选择总结维度**
- 动作类型: generate

**步骤 3: 选择输出格式，默认为markdown**
- 动作类型: generate

**步骤 4: 输出可下载的文档**
- 动作类型: generate

### 输出格式
json
