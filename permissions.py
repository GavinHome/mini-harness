from pathlib import Path
from utils.colors import YELLOW, RED, RESET
from config import WORKSPACE_DIR


# === Permission: 三层闸门 ===
def check_deny_list(command):
    DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
    for deny in DENY_LIST:
        if deny in command:
            return f"""禁止执行命令: {deny}"""
    return False

def check_rules(name, args):
    WORKSPACE = WORKSPACE_DIR
    PERMISSION_RULES = [
        {
            "tools": ["write_file", "edit_file"],
            "check": lambda args: not (WORKSPACE / args.get("path", "")).resolve().is_relative_to(WORKSPACE),
            "message": "Writing outside workspace is not allowed"
        },
        {
            "tools": ["run_bash"],
            "check": lambda args: any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
            "message": "Potentially destructive command"
        },
    ]

    for rule in PERMISSION_RULES:
        if name in rule["tools"] and rule["check"](args):
            return rule["message"]

    return True

def ask_user(name, args, reason):
    # print(f"""⚠️ {reason}""")
    print(f"\n{YELLOW}⚠️ {reason}{RESET}")
    print(f"   Tool: {name}({args})")
    confirm = input(f"""确认执行 {name} 吗？ (y/n) """)
    return confirm.strip().lower() == "y"

def check_permission(tool) -> bool:
    name = tool.name
    args = tool.input or {}
    command = args.get("command", "")

    if name == "run_bash":
        reason = check_deny_list(command)
        if reason:
            # print(f"""⛔ {reason}""")
            print(f"\n{RED}⛔ {reason}{RESET}")
            return False
    reason = check_rules(name, args)
    if reason:
        return ask_user(name, args, reason)
        
    return True

