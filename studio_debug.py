"""
LangGraph Studio 调试辅助脚本

使用方法:
1. 运行此脚本获取初始状态 JSON
2. 在 LangGraph Studio 中使用此 JSON 作为输入

或者直接运行测试:
    python studio_debug.py --test "你好"
"""

import json
import sys
from dotenv import load_dotenv
load_dotenv()

from graph import get_graph, get_initial_state
from langchain_core.messages import HumanMessage


def get_initial_state_json() -> str:
    """获取初始状态的 JSON 格式（用于 LangGraph Studio）"""
    state = get_initial_state()
    # 转换 messages 为可序列化格式
    state_dict = dict(state)
    state_dict["messages"] = []  # 空消息列表
    return json.dumps(state_dict, ensure_ascii=False, indent=2)


def test_with_message(message: str):
    """使用消息测试图"""
    graph = get_graph()
    state = get_initial_state()

    # 添加用户消息
    state["messages"] = [HumanMessage(content=message)]

    print(f"输入消息: {message}")
    print("-" * 50)

    # 运行图
    result = graph.invoke(state)

    # 显示结果
    print(f"路由: {result.get('route')}")
    print(f"匹配的工作流: {result.get('matched_workflow_id')}")
    print()
    print("AI 响应:")
    for msg in result["messages"]:
        if hasattr(msg, 'content') and msg.type == "ai":
            print(msg.content[:500] + "..." if len(msg.content) > 500 else msg.content)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test" and len(sys.argv) > 2:
            test_with_message(sys.argv[2])
        elif sys.argv[1] == "--state":
            print(get_initial_state_json())
        else:
            print(__doc__)
    else:
        print("初始状态 JSON (复制到 LangGraph Studio):")
        print("=" * 50)
        print(get_initial_state_json())
        print("=" * 50)
        print()
        print("使用方法:")
        print("  python studio_debug.py --state    # 获取初始状态 JSON")
        print("  python studio_debug.py --test '你好'  # 测试消息")


if __name__ == "__main__":
    main()
