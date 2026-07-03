from anthropic import Anthropic 
from dotenv import load_dotenv
import os

# ANSI 颜色转义码
CYAN = '\033[96m'      # 青色 - 思考内容
GREEN = '\033[92m'     # 绿色 - 最终回复
YELLOW = '\033[93m'    # 黄色 - Token 统计
GRAY = '\033[90m'      # 灰色 - 分隔符
MAGENTA = '\033[95m'   # 品红色 - 调试信息
RESET = '\033[0m'      # 重置颜色

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

TOOLS = []

response = client.messages.create(
    model=MODEL_ID,
    max_tokens=8192,
    system=SYSTEM_PROMPT,
    messages=messages,
    tools=[{
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
    }],
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
            print(item.to_json())
            print(f"{GRAY}{'='*50}{RESET}")
else:
    print(response)
    print(f"{GRAY}{'='*50}{RESET}")
    
print(f"{YELLOW}\n--- Token 使用统计 ---{RESET}")
print(f"{YELLOW}输入 token={response.usage.input_tokens}{RESET}")
print(f"{YELLOW}输出 token={response.usage.output_tokens}{RESET}")
print(f"{YELLOW}总共 token={response.usage.input_tokens + response.usage.output_tokens}{RESET}")
