from anthropic import Anthropic 
from dotenv import load_dotenv
import os
from utils.colors import CYAN, GREEN, YELLOW, GRAY, MAGENTA, BLUE, RED, RESET

load_dotenv()

BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_ID = os.getenv("MODEL_ID")

print(f"{MAGENTA}BASE_URL={BASE_URL}{RESET}")
print(f"{MAGENTA}MODEL_ID={MODEL_ID}{RESET}")
print(f"{GRAY}{'='*50}{RESET}")
client = Anthropic(base_url=BASE_URL, api_key=API_KEY)

SYSTEM_PROMPT = """
你是mini-harness, 擅长中文等各种语言的聊天助手。一个擅长写作的大师，
"""

messages = [
    {
        "role": "user",
        "content": "帮我写一首诗, 把结果保存到文件中"
    }
]

TOOLS = [{
        "name": "write_file",
        "description": "写入文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                },
                "content": {
                    "type": "string"
                }
            },
            "required": ["path", "content"]
        }
    }]

def write_file(path: str, content: str):
    print(f"写入文件: {path}, 内容: {content}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"文件 {path} 已写入"

TOOLS_HANDLER = {
    "write_file": write_file
}
def execute_tool(item):
    print(f"{RED}执行工具: {item.name}{RESET}")
    print(f"{RED}工具参数: {item.input}{RESET}")
    return TOOLS_HANDLER[item.name](item.input["path"], item.input["content"])

response = client.messages.create(
    model=MODEL_ID,
    max_tokens=8192,
    system=SYSTEM_PROMPT,
    messages=messages,
    tools=TOOLS,
    # stream=True
)

# print(response.to_json())



if isinstance(response.content, list):
    for item in response.content:
        if item.type == "thinking":
            print(f"{CYAN}thinking: {item.thinking}{RESET}")
            print(f"{GRAY}{'='*50}{RESET}")
        if item.type == "text":
            print(f"{GREEN}assistant: {item.text}{RESET}")
            print(f"{GRAY}{'='*50}{RESET}")
        if item.type == "tool_use":
            print(f"{BLUE}Tool Use: {item.to_json()}{RESET}")
            result = execute_tool(item)
            print(f"{GREEN}工具调用结果: {result}{RESET}")
            print(f"{GRAY}{'='*50}{RESET}")
else:
    print(response)
    print(f"{GRAY}{'='*50}{RESET}")
    
print(f"{YELLOW}\n--- Token 使用统计 ---{RESET}")
print(f"{YELLOW}输入 token={response.usage.input_tokens}{RESET}")
print(f"{YELLOW}输出 token={response.usage.output_tokens}{RESET}")
print(f"{YELLOW}总共 token={response.usage.input_tokens + response.usage.output_tokens}{RESET}")
