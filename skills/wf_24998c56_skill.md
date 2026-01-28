---
created_at: '2026-01-28T20:52:41.079914'
description: 竞品分析工作流，用来分析行业内相关竞争对手的产品情况
domain: 通用
name: 竞品分析工作流，用来分析行业内相关竞争对
optional_inputs: []
output_format: json
required_inputs: []
steps:
- action: collect
  description: 输入要分析的产品
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_1
- action: collect
  description: 输入要研究的竞争对手
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_2
- action: generate
  description: 搜集相关的信息
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_3
- action: generate
  description: 总结相关信息，并输出markdown的报告
  inputs: []
  outputs: []
  prompt_template: null
  step_id: step_4
trigger_phrases:
- 竞品分析
- 分析竞争对手
- competitor analysis
- 竞品调研
- 竞对分析
updated_at: '2026-01-28T20:52:41.079921'
workflow_id: wf_24998c56
---

## 竞品分析工作流，用来分析行业内相关竞争对

### 概述
竞品分析工作流，用来分析行业内相关竞争对手的产品情况

### 触发条件
当用户表达以下意图时触发此工作流：
- "竞品分析"
- "分析竞争对手"
- "competitor analysis"
- "竞品调研"
- "竞对分析"

### 必需信息
无特定要求

### 可选信息
无

### 执行步骤

**步骤 1: 输入要分析的产品**
- 动作类型: collect

**步骤 2: 输入要研究的竞争对手**
- 动作类型: collect

**步骤 3: 搜集相关的信息**
- 动作类型: generate

**步骤 4: 总结相关信息，并输出markdown的报告**
- 动作类型: generate

### 输出格式
json
