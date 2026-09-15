"""DeepSeek Planner: 把 LLM 输出约束为 JSON action。无Key时降级为echo，保证可测可跑。"""
import json
import os


SYSTEM_PROMPT = (
    "你是企业运维助手Planner。只输出JSON，不要markdown。\n"
    '格式1 结束: {"action":"finish","answer":"..."}\n'
    '格式2 调工具: {"action":"call_tool","tool":"db.query","args":{...}}\n'
    "没有工具结果就先finish，不要编造数据。"
)


def get_default_client():
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxxx"):
        return None, os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    return client, os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def _parse_json(text: str) -> dict:
    t = text.strip()
    # 去掉 ```json fences
    if t.startswith("```"):
        t = t.strip("`")
        # 去掉首行 json 标记
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t.strip())


def build_deepseek_planner(client=None, model: str = "deepseek-chat"):
    def planner(state) -> dict:
        if client is None:
            return {"action": "finish", "answer": f"[runtime-echo] {state.task}"}
        user_content = f"任务: {state.task}\n历史: {state.messages[-3:]}"
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=300,
        )
        text = resp.choices[0].message.content or ""
        try:
            plan = _parse_json(text)
        except Exception:
            return {"action": "finish", "answer": text}
        if plan.get("action") not in ("finish", "call_tool"):
            return {"action": "finish", "answer": text}
        return plan

    return planner
