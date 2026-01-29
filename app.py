"""
Gradio 图形化对话界面
工作流 Agent 的前端应用
"""

from dotenv import load_dotenv
load_dotenv()

import gradio as gr
import json
import os
import socket
import subprocess
import sys
from langchain_core.messages import HumanMessage, AIMessage

from graph import get_graph, ConversationState, get_initial_state
from schemas import WorkflowCollection


class WorkflowAgentApp:
    """工作流 Agent 应用"""

    def __init__(self):
        # 使用统一的初始状态（自动加载已保存的工作流）
        self.state: ConversationState = get_initial_state()
        self.graph = get_graph()

    def chat(self, message: str, history: list) -> tuple[str, list]:
        """处理用户消息

        改进：
        - 执行过程中：显示简短状态消息
        - 执行完成后：只显示最终格式化输出
        """
        if not message.strip():
            return "", history

        # 记录当前消息数量，用于后续计算新增消息
        old_message_count = len(self.state.get("messages", []))

        # 添加用户消息到状态
        self.state["messages"].append(HumanMessage(content=message))

        # 运行图
        try:
            result = self.graph.invoke(self.state)
            self.state = result

            # 获取本次新增的所有 AI 消息
            all_messages = result.get("messages", [])

            # 找出新增的 AI 消息（跳过之前已有的消息 + 刚添加的用户消息）
            new_messages = all_messages[old_message_count + 1:]  # +1 跳过刚添加的 HumanMessage
            new_ai_messages = [m for m in new_messages if isinstance(m, AIMessage)]

            if new_ai_messages:
                # 无论执行是否完成，都显示所有新消息（包括进度消息 + 最终输出）
                response = "\n\n".join(m.content for m in new_ai_messages[-10:])
            else:
                # 降级：如果没有新增消息，取最后一条 AI 消息
                ai_messages = [m for m in all_messages if isinstance(m, AIMessage)]
                if ai_messages:
                    response = ai_messages[-1].content
                else:
                    response = "处理出错，请重试。"
        except Exception as e:
            response = f"发生错误: {str(e)}\n\n请确保已正确设置 ANTHROPIC_API_KEY 环境变量。"

        # 更新历史 (Gradio 6.0 message format)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
        return "", history

    def get_workflow_list(self) -> str:
        """获取工作流列表的 Markdown 格式"""
        collection = WorkflowCollection(**self.state["workflow_collection"])
        workflows = collection.list_workflows()

        if not workflows:
            return "### 工作流列表\n\n*暂无已创建的工作流*\n\n使用「我要创建XX流程」来创建新工作流"

        md = "### 工作流列表\n\n"
        for wf in workflows:
            md += f"**{wf['name']}** (`{wf['id']}`)\n"
            md += f"- 领域: {wf['domain']}\n"
            md += f"- 触发词: {', '.join(wf['triggers'])}\n\n"
        return md

    def get_current_workflow_detail(self) -> str:
        """获取当前工作流详情"""
        # 检查是否在创建流程中（通过 creation_stage 判断）
        if self.state.get("creation_stage") and self.state.get("draft_name"):
            draft_info = {
                "name": self.state.get("draft_name"),
                "description": self.state.get("draft_description"),
                "triggers": self.state.get("draft_triggers", []),
                "steps": self.state.get("draft_steps", [])
            }
            return f"### 正在创建工作流\n\n```json\n{json.dumps(draft_info, ensure_ascii=False, indent=2)}\n```"
        return "### 工作流详情\n\n*选择或创建一个工作流查看详情*"

    def clear_chat(self) -> tuple[list, str]:
        """清空对话"""
        self.state["messages"] = []
        self.state["route"] = None
        self.state["matched_workflow_id"] = None
        # workflow_execution 子图状态字段
        self.state["execution_stage"] = None
        self.state["current_step_index"] = 0
        self.state["step_results"] = []
        self.state["execution_workflow_id"] = None
        self.state["collected_inputs"] = {}
        self.state["initial_user_input"] = None
        # workflow_skills 子图状态字段
        self.state["action"] = None
        self.state["creation_stage"] = None
        self.state["draft_name"] = None
        self.state["draft_description"] = None
        self.state["draft_triggers"] = []
        self.state["draft_required_inputs"] = []
        self.state["draft_optional_inputs"] = []
        self.state["draft_steps"] = []
        self.state["draft_output_format"] = None
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
            return f"成功导入 {len(collection.workflows)} 个工作流"
        except Exception as e:
            return f"导入失败: {str(e)}"


def create_app():
    """创建 Gradio 应用"""
    agent = WorkflowAgentApp()

    with gr.Blocks() as app:
        # 头部
        gr.HTML("""
        <div class="header">
            <h1>智能工作流 Agent</h1>
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
                    clear_btn = gr.Button("清空对话", size="sm")
                    examples_btn = gr.Button("示例命令", size="sm")

            # 右侧：工作流管理
            with gr.Column(scale=1, elem_classes=["sidebar"]):
                workflow_list = gr.Markdown(
                    agent.get_workflow_list(),
                    elem_classes=["workflow-list"]
                )

                refresh_btn = gr.Button("刷新列表", size="sm")

                gr.Markdown("---")

                with gr.Accordion("导入/导出", open=False):
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
                ### 快速指令
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


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def get_process_on_port(port: int) -> str:
    """获取占用端口的进程信息"""
    try:
        result = subprocess.run(
            ['lsof', '-i', f':{port}'],
            capture_output=True,
            text=True
        )
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                # 解析进程信息
                parts = lines[1].split()
                if len(parts) >= 2:
                    return f"进程: {parts[0]} (PID: {parts[1]})"
        return "未知进程"
    except Exception:
        return "无法获取进程信息"


def kill_process_on_port(port: int) -> bool:
    """终止占用端口的进程"""
    try:
        result = subprocess.run(
            f'lsof -ti:{port} | xargs kill -9',
            shell=True,
            capture_output=True
        )
        return result.returncode == 0
    except Exception:
        return False


def find_available_port(start_port: int, max_attempts: int = 10) -> int:
    """查找可用端口"""
    for i in range(max_attempts):
        port = start_port + i
        if not is_port_in_use(port):
            return port
    return -1


def handle_port_conflict(port: int) -> int:
    """处理端口冲突，返回最终使用的端口"""
    process_info = get_process_on_port(port)
    print(f"\n端口 {port} 已被占用")
    print(f"  {process_info}")
    print()
    print("请选择处理方式：")
    print(f"  [1] 终止占用进程，使用端口 {port}")
    print("  [2] 自动选择其他可用端口")
    print("  [3] 手动输入端口号")
    print("  [q] 退出程序")
    print()

    while True:
        choice = input("请输入选项 (1/2/3/q): ").strip().lower()

        if choice == '1':
            print(f"正在终止占用端口 {port} 的进程...")
            if kill_process_on_port(port):
                print("进程已终止")
                return port
            else:
                print("终止进程失败，请手动处理或选择其他选项")
                continue

        elif choice == '2':
            new_port = find_available_port(port + 1)
            if new_port > 0:
                print(f"将使用端口 {new_port}")
                return new_port
            else:
                print("未找到可用端口，请手动输入")
                continue

        elif choice == '3':
            try:
                new_port = int(input("请输入端口号 (1024-65535): ").strip())
                if 1024 <= new_port <= 65535:
                    if is_port_in_use(new_port):
                        print(f"端口 {new_port} 也被占用，请重新选择")
                        continue
                    return new_port
                else:
                    print("端口号应在 1024-65535 之间")
                    continue
            except ValueError:
                print("请输入有效的数字")
                continue

        elif choice == 'q':
            print("退出程序")
            sys.exit(0)

        else:
            print("无效选项，请重新输入")


def main():
    """主函数"""
    # 检查 API Key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("警告: 未设置 ANTHROPIC_API_KEY 环境变量")
        print("请设置: export ANTHROPIC_API_KEY='your-api-key'")
        print()

    # 默认端口
    port = 7860

    # 检查端口是否被占用
    if is_port_in_use(port):
        port = handle_port_conflict(port)

    app = create_app()
    print(f"\n启动服务器，访问地址: http://localhost:{port}\n")

    app.launch(
        server_name="0.0.0.0",
        server_port=port,
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
