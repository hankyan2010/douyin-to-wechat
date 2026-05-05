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
import subprocess

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
ARK_KEY = os.getenv("ARK_API_KEY")
ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-1-6-250615")

if not ARK_KEY:
    raise RuntimeError("缺少 ARK_API_KEY")

client = OpenAI(api_key=ARK_KEY, base_url=ARK_BASE)

# 主备切换：优先走 Mac 上的 Claude Code（5x 会员，质量更高）
# 优先用 HTTP bridge (本机 daemon 包装,绕过 SSH 无法访问 Keychain 的问题)
# 失败再降级到 SSH 直跑 (兼容旧路径) → 失败再降级到豆包
CLAUDE_BRIDGE_URL = os.getenv("CLAUDE_BRIDGE_URL", "")
CLAUDE_BRIDGE_TOKEN = os.getenv("CLAUDE_BRIDGE_TOKEN", "")
MAC_TS_IP = os.getenv("MAC_TS_IP", "100.119.31.39")
MAC_USER = os.getenv("MAC_USER", "yanhan")
MAC_CLAUDE_BIN = os.getenv("MAC_CLAUDE_BIN", "/Users/yanhan/.npm-global/bin/claude")
PRIMARY_TIMEOUT = int(os.getenv("REWRITE_PRIMARY_TIMEOUT", "180"))

SYSTEM = """你是一位资深公众号"贴图号"内容编辑。把抖音口播原文重写成"贴图"格式。

【标题】（最重要！）
- **严格 ≤ 20 字（含所有标点和空格）**——超过 20 字微信前端会截断显示
- 必须**反常识/反共识**，让人一看就想点开
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


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # 容错：claude -p 可能输出多行说明，取第一段 JSON
    m = re.search(r"\{[\s\S]*\}", raw)
    return m.group(0) if m else raw


def _call_claude_via_bridge(full_prompt: str) -> str:
    """通过本机 HTTP bridge 调 claude (绕过 SSH 不可访问 Keychain 问题)。"""
    if not CLAUDE_BRIDGE_URL or not CLAUDE_BRIDGE_TOKEN:
        raise RuntimeError("CLAUDE_BRIDGE_URL/TOKEN 未配置")
    r = requests.post(
        f"{CLAUDE_BRIDGE_URL}/rewrite",
        headers={"X-Token": CLAUDE_BRIDGE_TOKEN, "Content-Type": "application/json"},
        json={"prompt": full_prompt},
        timeout=PRIMARY_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"bridge http={r.status_code}: {r.text[:300]}")
    data = r.json()
    if "output" not in data:
        raise RuntimeError(f"bridge 返回异常: {data}")
    return data["output"]


def _call_claude_once(full_prompt: str) -> str:
    """旧路径:直接 SSH 跑 claude -p (备用,通常在 SSH session 里读不到 Keychain 凭证会失败)。"""
    cmd = [
        "ssh",
        "-o", "ConnectTimeout=8",
        "-o", "ServerAliveInterval=15",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        f"{MAC_USER}@{MAC_TS_IP}",
        f"cat | {MAC_CLAUDE_BIN} -p",
    ]
    r = subprocess.run(cmd, input=full_prompt.encode("utf-8"),
                       capture_output=True, timeout=PRIMARY_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"ssh/claude exit={r.returncode}: {r.stderr.decode()[:300]}")
    return r.stdout.decode("utf-8")


def rewrite_via_claude(transcript: str, max_cards: int = 6) -> dict:
    """主：HTTP bridge → 本机 claude (优先) / SSH 直跑 (兜底)。失败重试一次。"""
    user_msg = USER_TEMPLATE.format(transcript=transcript.strip())
    full_prompt = SYSTEM + "\n\n---\n\n" + user_msg + "\n\n严格只输出 JSON 对象本体，不要任何前后说明文字、不要 markdown 代码块。"

    use_bridge = bool(CLAUDE_BRIDGE_URL and CLAUDE_BRIDGE_TOKEN)
    backend_label = "claude_bridge" if use_bridge else "claude_ssh"
    print(f"[rewrite] 主路径: {'HTTP bridge' if use_bridge else 'SSH→Mac claude -p'} (timeout={PRIMARY_TIMEOUT}s)")

    last_err = None
    for attempt in range(2):
        try:
            raw_out = _call_claude_via_bridge(full_prompt) if use_bridge else _call_claude_once(full_prompt)
            stripped = _strip_json_fence(raw_out)
            data = json.loads(stripped)
            data["cards"] = data.get("cards", [])[:max_cards]
            data["_backend"] = backend_label
            return data
        except (json.JSONDecodeError, KeyError) as e:
            last_err = e
            print(f"[rewrite] 主路径第{attempt+1}次解析失败 ({type(e).__name__}): {str(e)[:150]}")
            if attempt == 0:
                print("[rewrite] 重试中...")
    raise RuntimeError(f"claude 输出解析失败（已重试1次）: {last_err}")


def rewrite_via_doubao(transcript: str, max_cards: int = 6) -> dict:
    """备：本地豆包 API。"""
    print("[rewrite] 备用路径: 豆包 API")
    user_msg = USER_TEMPLATE.format(transcript=transcript.strip())
    resp = client.chat.completions.create(
        model=ARK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.7,
    )
    raw = _strip_json_fence(resp.choices[0].message.content)
    data = json.loads(raw)
    data["cards"] = data.get("cards", [])[:max_cards]
    data["_backend"] = "doubao_fallback"
    return data


def rewrite(transcript: str, max_cards: int = 6) -> dict:
    """主备切换：优先 Claude，失败降级豆包。"""
    try:
        return rewrite_via_claude(transcript, max_cards)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
            RuntimeError, json.JSONDecodeError, OSError) as e:
        print(f"[rewrite] 主路径失败 ({type(e).__name__}): {str(e)[:200]}")
        print("[rewrite] → 降级到豆包")
        return rewrite_via_doubao(transcript, max_cards)


if __name__ == "__main__":
    import sys
    text = sys.stdin.read() if not sys.argv[1:] else open(sys.argv[1]).read()
    out = rewrite(text)
    print(json.dumps(out, ensure_ascii=False, indent=2))
