import os
from pathlib import Path
from anthropic import Anthropic 
from dotenv import load_dotenv
from utils.colors import CYAN, GREEN, YELLOW, GRAY, MAGENTA, BLUE, RED, RESET
from tools import TOOLS, execute_tool

load_dotenv()

BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_ID = os.getenv("MODEL_ID")

print(f"{MAGENTA}BASE_URL={BASE_URL}{RESET}")
print(f"{MAGENTA}MODEL_ID={MODEL_ID}{RESET}")
print(f"{GRAY}{'='*50}{RESET}")
client = Anthropic(base_url=BASE_URL, api_key=API_KEY)

WORKSPACE_DIR = Path.cwd() / ".workspace"
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = f"""
你是mini-harness, 工作目录是{WORKSPACE_DIR}, 使用工具完成任务。直接执行命令，不要解释。
"""
messages = []
total_input_tokens = 0
total_output_tokens = 0

while True:
    print(f"{CYAN}请输入你的问题: {RESET}")
    query = input(f"{CYAN}mini-harness >> {RESET}")
    messages.append({ "role": "user", "content": query })

    round_input_tokens = 0
    round_output_tokens = 0
    max_turns = 10
    stop = False
    while max_turns > 0 and not stop:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
            # stream=True
        )
        max_turns -= 1
        round_input_tokens += response.usage.input_tokens
        round_output_tokens += response.usage.output_tokens

        if isinstance(response.content, list):
            for item in response.content:
                if item.type == "thinking":
                    print(f"{CYAN}thinking: {item.thinking}{RESET}")
                    print(f"{GRAY}{'='*50}{RESET}")
   
        if response.stop_reason == "tool_use":
            for item in response.content:
                if item.type == "tool_use":
                    result = execute_tool(item)
                    messages.append({ "role": "user", "content": result })

        if response.stop_reason == "end_turn":
            for item in response.content:
                if item.type == "text":
                    print(f"{GREEN}assistant: {item.text}{RESET}")
                    print(f"{GRAY}{'='*50}{RESET}")
                    messages.append({ "role": "assistant", "content": item.text })
                    stop = True
        if stop:
            break
    
    print(f"{YELLOW}\n--- Token 统计 ---{RESET}")
    print(f"{YELLOW}本轮: 总共={round_input_tokens + round_output_tokens} 输入={round_input_tokens} 输出={round_output_tokens}{RESET}")

    total_input_tokens += round_input_tokens
    total_output_tokens += round_output_tokens
    print(f"{YELLOW}总计: 总共={total_input_tokens + total_output_tokens} 输入={total_input_tokens} 输出={total_output_tokens}{RESET}")


