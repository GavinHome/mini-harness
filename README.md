**Agent = LLM + Harness**

* **LLM**：提供 Agency 的能力（感知、推理、决策）
* **Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions**

**四层结构：L1 内核 + L2 骨架 + L3 器官 + L4 外设**

* L1 **最小执行框架：** Loop + Tools + Action
* L2 **安全与可持续：** Permission + Compact + Recovery + Hooks
* L3 **复杂任务支持：** Todo + Task + Memory + Subagent + Multi-Agent + Teams
* L4 **产品化的扩展：** Cron + Background + MCP + Skills

LLM → L1（让它能动）→ L2（让它不崩）→ L3（让它能干大事）→ L4（让它成产品）

**Agent 的最小闭环 = LLM + Loop + Tools + Action = while True -> LLM -> Tool_Use -> execute -> loop**

**Harness 的最小内核(L1) = Loop + Tools + Action**


**环境：**

```python
python -m venv .venv

source .venv/bin/activate

pip install -r requirement.txt
```

**使用：**

```python
python mini-harness
```
