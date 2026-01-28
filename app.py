"""
Gradio 图形化对话界面
工作流 Agent 的前端应用
"""

import gradio as gr
import json
import os
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage

from graph import get_graph, ConversationState
from schemas import WorkflowCollection
from persistence import load_all_workflows


class WorkflowAgentApp:
    """工作流 Agent 应用"""

    def __init__(self):
        # 从 skills 目录加载已保存的工作流
        initial_collection = load_all_workflows()

        self.state: ConversationState = {
            "messages": [],
            "current_mode": "chat",
            "creation_stage": None,
            "draft_name": None,
            "draft_description": None,
            "draft_triggers": [],
            "draft_required_inputs": [],
            "draft_optional_inputs": [],
            "draft_steps": [],
            "draft_output_format": None,
            "current_step_index": 0,
            "workflow_collection": initial_collection.model_dump(),
            "awaiting_confirmation": False
        }
        self.graph = get_graph()
    
    def chat(self, message: str, history: list) -> tuple[str, list]:
        """处理用户消息"""
        if not message.strip():
            return "", history
        
        # 添加用户消息到状态
        self.state["messages"].append(HumanMessage(content=message))
        
        # 运行图
        try:
            result = self.graph.invoke(self.state)
            self.state = result
            
            # 获取最后的 AI 响应
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            if ai_messages:
                response = ai_messages[-1].content
            else:
                response = "处理出错，请重试。"
        except Exception as e:
            response = f"❌ 发生错误: {str(e)}\n\n请确保已正确设置 ANTHROPIC_API_KEY 环境变量。"
        
        # 更新历史 (Gradio 6.0 message format)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
        return "", history
    
    def get_workflow_list(self) -> str:
        """获取工作流列表的 Markdown 格式"""
        collection = WorkflowCollection(**self.state["workflow_collection"])
        workflows = collection.list_workflows()
        
        if not workflows:
            return "### 📋 工作流列表\n\n*暂无已创建的工作流*\n\n使用「我要创建XX流程」来创建新工作流"
        
        md = "### 📋 工作流列表\n\n"
        for wf in workflows:
            md += f"**{wf['name']}** (`{wf['id']}`)\n"
            md += f"- 领域: {wf['domain']}\n"
            md += f"- 触发词: {', '.join(wf['triggers'])}\n\n"
        return md
    
    def get_current_workflow_detail(self) -> str:
        """获取当前工作流详情"""
        if self.state["current_mode"] == "creating_workflow" and self.state.get("draft_name"):
            draft_info = {
                "name": self.state.get("draft_name"),
                "description": self.state.get("draft_description"),
                "triggers": self.state.get("draft_triggers", []),
                "steps": self.state.get("draft_steps", [])
            }
            return f"### 🔧 正在创建工作流\n\n```json\n{json.dumps(draft_info, ensure_ascii=False, indent=2)}\n```"
        return "### 工作流详情\n\n*选择或创建一个工作流查看详情*"

    def clear_chat(self) -> tuple[list, str]:
        """清空对话"""
        self.state["messages"] = []
        self.state["current_mode"] = "chat"
        self.state["creation_stage"] = None
        self.state["draft_name"] = None
        self.state["draft_description"] = None
        self.state["draft_triggers"] = []
        self.state["draft_required_inputs"] = []
        self.state["draft_optional_inputs"] = []
        self.state["draft_steps"] = []
        self.state["draft_output_format"] = None
        self.state["current_step_index"] = 0
        self.state["awaiting_confirmation"] = False
        return [], self.get_workflow_list()
    
    def export_workflows(self) -> str:
        """导出工作流为 JSON"""
        return json.dumps(self.state["workflow_collection"], ensure_ascii=False, indent=2)
    
    def import_workflows(self, json_str: str) -> str:
        """导入工作流"""
        try:
            data = json.loads(json_str)
            collection = WorkflowCollection(**data)
            self.state["workflow_collection"] = collection.model_dump()
            return f"✅ 成功导入 {len(collection.workflows)} 个工作流"
        except Exception as e:
            return f"❌ 导入失败: {str(e)}"


def create_app():
    """创建 Gradio 应用"""
    agent = WorkflowAgentApp()

    with gr.Blocks() as app:
        # 头部
        gr.HTML("""
        <div class="header">
            <h1>🤖 智能工作流 Agent</h1>
            <p>通过对话创建和执行自定义工作流 | 基于 LangGraph + Claude</p>
        </div>
        """)
        
        with gr.Row():
            # 左侧：聊天区域
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="对话",
                    height=500,
                    avatar_images=(None, "https://api.iconify.design/fluent-emoji:robot.svg")
                )
                
                with gr.Row():
                    msg = gr.Textbox(
                        label="输入消息",
                        placeholder="输入消息... 试试「我要创建周报流程」",
                        scale=4,
                        show_label=False
                    )
                    submit_btn = gr.Button("发送", variant="primary", scale=1)
                
                with gr.Row():
                    clear_btn = gr.Button("🗑️ 清空对话", size="sm")
                    examples_btn = gr.Button("📝 示例命令", size="sm")
            
            # 右侧：工作流管理
            with gr.Column(scale=1, elem_classes=["sidebar"]):
                workflow_list = gr.Markdown(
                    agent.get_workflow_list(),
                    elem_classes=["workflow-list"]
                )
                
                refresh_btn = gr.Button("🔄 刷新列表", size="sm")
                
                gr.Markdown("---")
                
                with gr.Accordion("📥 导入/导出", open=False):
                    export_btn = gr.Button("导出工作流", size="sm")
                    export_output = gr.Code(label="JSON", language="json")
                    
                    import_input = gr.Textbox(
                        label="导入 JSON",
                        placeholder="粘贴 JSON...",
                        lines=3
                    )
                    import_btn = gr.Button("导入", size="sm")
                    import_status = gr.Textbox(label="状态", interactive=False)
                
                gr.Markdown("---")
                
                gr.Markdown("""
                ### 💡 快速指令
                - `我要创建XX流程` - 创建工作流
                - `查看所有流程` - 列出工作流
                - `帮助` - 显示帮助
                """)
        
        # 示例对话
        gr.Examples(
            examples=[
                "我要创建周报流程",
                "我要创建竞品分析流程",
                "我要创建代码审查流程",
                "查看所有流程",
                "帮助"
            ],
            inputs=msg,
            label="示例命令"
        )
        
        # 事件绑定
        def on_submit(message, history):
            response, new_history = agent.chat(message, history)
            workflow_md = agent.get_workflow_list()
            return response, new_history, workflow_md
        
        msg.submit(
            on_submit,
            inputs=[msg, chatbot],
            outputs=[msg, chatbot, workflow_list]
        )
        
        submit_btn.click(
            on_submit,
            inputs=[msg, chatbot],
            outputs=[msg, chatbot, workflow_list]
        )
        
        clear_btn.click(
            agent.clear_chat,
            outputs=[chatbot, workflow_list]
        )
        
        refresh_btn.click(
            agent.get_workflow_list,
            outputs=[workflow_list]
        )
        
        export_btn.click(
            agent.export_workflows,
            outputs=[export_output]
        )
        
        import_btn.click(
            agent.import_workflows,
            inputs=[import_input],
            outputs=[import_status]
        ).then(
            agent.get_workflow_list,
            outputs=[workflow_list]
        )
    
    return app


def main():
    """主函数"""
    # 检查 API Key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  警告: 未设置 ANTHROPIC_API_KEY 环境变量")
        print("请设置: export ANTHROPIC_API_KEY='your-api-key'")
        print()
    
    app = create_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        css="""
        .container { max-width: 1200px; margin: auto; }
        .chatbot { min-height: 500px; }
        .sidebar { background: #f7f7f8; padding: 15px; border-radius: 8px; }
        .workflow-list { font-size: 14px; }
        .header { text-align: center; margin-bottom: 20px; }
        .header h1 { color: #1a1a2e; margin-bottom: 5px; }
        .header p { color: #666; }
        """
    )


if __name__ == "__main__":
    main()
