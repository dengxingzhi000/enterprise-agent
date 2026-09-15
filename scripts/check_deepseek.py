"""Stage0 DeepSeek连通检查: python scripts/check_deepseek.py"""
import os
from openai import OpenAI

api_key = os.getenv("DEEPSEEK_API_KEY", "")
base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

if not api_key or api_key.startswith("sk-xxxx"):
    print("SKIP: 请先 copy .env.example -> .env 并填入 DEEPSEEK_API_KEY")
    raise SystemExit(2)

client = OpenAI(api_key=api_key, base_url=base_url)
resp = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "用一句话证明你连通了。"}],
    max_tokens=50,
)
print("OK:", resp.choices[0].message.content)
