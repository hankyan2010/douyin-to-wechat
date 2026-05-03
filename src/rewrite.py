"""口播文案 → 公众号贴图脚本。

输出 JSON：
{
  "title": "贴图标题（≤22字，钩子式）",
  "lead": "首张卡片的引导话术（≤30字）",
  "cards": [
    {"headline": "小标题", "body": "正文 50~80 字"},
    ...
  ],
  "cover_prompt": "封面 AI 生图 prompt（小红书风插画）"
}
"""
import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
ARK_KEY = os.getenv("ARK_API_KEY")
ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-1-6-250615")

if not ARK_KEY:
    raise RuntimeError("缺少 ARK_API_KEY")

client = OpenAI(api_key=ARK_KEY, base_url=ARK_BASE)

SYSTEM = """你是一位资深公众号"贴图号"内容编辑。把抖音口播原文重写成"贴图"格式。

【标题】（最重要！）
- 长度 16~22 字，必须**反常识/反共识**，让人一看就想点开
- 用对比、反差、悖论结构，把作者的核心观点最锋利的那一面亮出来
- 优秀范例（学这种感觉）：
  · "AI时代赚小钱跟捡钱一样，赚大钱几乎不可能"
  · "外卖店越拼命做活动，越亏得快"
  · "招人最贵的成本，从来不是工资"
  · "做副业赚到第一笔钱的人，都没在'学'副业"
- 烂标题特征（绝对不要）：
  · "X的Y逻辑"、"X的几个真相"、"关于X你必须知道的Y件事"
  · "深度解析"、"全面盘点"、"一文读懂"
  · 任何 AI 总结味套话

【卡片】
- 1 张引导卡（lead）+ 6 张内容卡（cards）
- 每张内容卡：小标题 ≤12 字 + 正文 50~80 字
- 文风：口语化、有信息密度、有节奏感

【封面/图片】
- cover_prompt 字段保留，但本项目不再用，留空字符串即可

输出严格 JSON，无 markdown 代码块包裹。"""

USER_TEMPLATE = """以下是抖音口播原文：

「{transcript}」

请改写成贴图脚本，输出格式：
{{
  "title": "...",
  "lead": "首卡引导（点出文章在讲什么，30字内）",
  "cards": [
    {{"headline": "...", "body": "..."}},
    ...共 6 张
  ],
  "cover_prompt": "用于封面 AI 生图的 prompt（中文，小红书插画风，明亮治愈感，描述场景和主体，不出现文字）"
}}"""


def rewrite(transcript: str, max_cards: int = 6) -> dict:
    user_msg = USER_TEMPLATE.format(transcript=transcript.strip())
    resp = client.chat.completions.create(
        model=ARK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
    )
    raw = resp.choices[0].message.content.strip()
    # 容错：剥掉可能的 ```json``` 包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    # 截断到 max_cards
    data["cards"] = data.get("cards", [])[:max_cards]
    return data


if __name__ == "__main__":
    import sys
    text = sys.stdin.read() if not sys.argv[1:] else open(sys.argv[1]).read()
    out = rewrite(text)
    print(json.dumps(out, ensure_ascii=False, indent=2))
