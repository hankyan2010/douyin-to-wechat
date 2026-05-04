"""华为云 bot 长轮询守护进程。

逻辑：
  long-poll bot 2 (ILINK_BOT2_TOKEN) → 解析用户消息 → 路由到处理器 → 回复

支持的指令：
  https://v.douyin.com/xxx     → 入队
  发布 / 发布 <id>             → 发布对应草稿
  队列 / list                  → 列出待办
  状态 / stats                 → 统计
  下一条 / next                → 立即跑队列下一条（手动触发，不等 cron）
  帮助 / help / ?              → 列出指令
"""
import base64
import json
import os
import re
import secrets
import sys
import time
import traceback
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ILINK_BASE = "https://ilinkai.weixin.qq.com"
BOT_TOKEN = os.getenv("ILINK_BOT2_TOKEN", "") or os.getenv("ILINK_BOT_TOKEN", "")
BOT_ACCOUNT = os.getenv("ILINK_BOT2_ACCOUNT", "") or os.getenv("ILINK_BOT_ACCOUNT", "")
USER_ID = os.getenv("ILINK_USER_ID", "")

UPDATE_BUF_FILE = Path(__file__).parent.parent / ".cloudbot_buf"


def _uin() -> str:
    return base64.b64encode(secrets.token_bytes(4)).decode()


def _client_id() -> str:
    return secrets.token_hex(16)


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BOT_TOKEN}",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _uin(),
    }


def get_updates(buf: str = "") -> dict:
    body = {"get_updates_buf": buf} if buf else {}
    r = requests.post(
        f"{ILINK_BASE}/ilink/bot/getupdates",
        headers=_headers(),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=40,
    )
    return r.json() if r.text else {}


def reply(to_user: str, text: str, context_token: str = "") -> dict:
    body = {
        "msg": {
            "from_user_id": BOT_ACCOUNT,
            "to_user_id": to_user,
            "client_id": _client_id(),
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }
    }
    r = requests.post(
        f"{ILINK_BASE}/ilink/bot/sendmessage",
        headers=_headers(),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=15,
    )
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text[:200]}


# ===== 命令处理 =====

URL_PATTERN = re.compile(r"https?://[^\s,，。]+(?:douyin|iesdouyin)[^\s,，。]*", re.I)
CMD_PUBLISH = re.compile(r"^\s*(发布|publish)(?:\s+(\S+))?\s*$", re.I)
CMD_LIST = re.compile(r"^\s*(队列|list|queue)\s*$", re.I)
CMD_STATS = re.compile(r"^\s*(状态|stats|status)\s*$", re.I)
CMD_NEXT = re.compile(r"^\s*(下一条|next|run)\s*$", re.I)
CMD_HELP = re.compile(r"^\s*(帮助|help|\?)\s*$", re.I)


def handle_text(text: str, from_user: str, context_token: str) -> str:
    """返回要发回的消息文本。"""
    text = (text or "").strip()
    if not text:
        return ""

    # 1. 抖音链接 → 入队 + 立即异步触发生成
    m = URL_PATTERN.search(text)
    if m:
        from . import queue
        import subprocess, sys as _sys
        url = m.group(0)
        priority = 10 if any(k in text for k in ["插队", "急", "优先", "priority"]) else 0
        item = queue.add(url, priority=priority, source="cloudbot")
        pending = queue.list_items(status="pending")
        pos = next((i for i, x in enumerate(pending, 1) if x["id"] == item["id"]), 0)
        mark = "（已插队）" if priority > 0 else ""
        # 异步启动生成（不阻塞 long-poll）
        # 用 nohup + 重定向，进程脱离当前 daemon
        proj_root = str(Path(__file__).parent.parent)
        subprocess.Popen(
            [_sys.executable, "-m", "src.daily_publish", "generate"],
            cwd=proj_root,
            stdout=open("/var/log/d2w-generate.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return (f"✅ 已入队{mark}\n"
                f"位置 #{pos} / 共 {len(pending)} 条待办\n"
                f"ID: {item['id']}\n"
                f"⏳ 后台生成中（约 3 分钟），完成会推草稿通知。\n"
                f"明早 7:00 自动发布最早一条 draft_ready。")

    # 2. 帮助
    if CMD_HELP.match(text):
        return ("📖 指令：\n"
                "• 发抖音链接 → 自动入队\n"
                "• 发布 / 发布 <id> → 发布草稿\n"
                "• 队列 → 看待办\n"
                "• 状态 → 看统计\n"
                "• 下一条 → 立即跑下一条（不等 cron）")

    # 3. 队列
    if CMD_LIST.match(text):
        from . import queue
        items = queue.list_items(status="pending", limit=20)
        if not items:
            return "队列空"
        lines = ["📋 待办队列:"]
        for i, it in enumerate(items, 1):
            mark = "★" if it["priority"] > 0 else " "
            lines.append(f"{i}.{mark} {it['id'][:8]} {it['url'][:40]}")
        return "\n".join(lines)

    # 4. 状态
    if CMD_STATS.match(text):
        from . import queue
        s = queue.stats()
        return f"📊 共 {s['total']} 条\n按状态: {json.dumps(s['by_status'], ensure_ascii=False)}"

    # 5. 立即跑下一条
    if CMD_NEXT.match(text):
        from . import daily_publish
        result = daily_publish.run_one(force_publish=False)
        if result.get("ok"):
            if "skipped" in result:
                return "队列空，没东西可跑"
            return f"✅ 已跑完: 《{result['title']}》\n草稿: {result['draft_media_id'][:24]}..."
        return f"❌ 失败: {result.get('error', '?')[:200]}"

    # 6. 发布
    m = CMD_PUBLISH.match(text)
    if m:
        from . import queue, wechat
        target_id = m.group(2)
        items = queue.list_items()
        candidates = [i for i in items if i["status"] == "draft_ready" and i.get("draft_media_id")]
        if target_id:
            candidates = [i for i in candidates if i["id"].startswith(target_id)]
        if not candidates:
            return "❌ 没有可发布的草稿（status=draft_ready）"
        # 取最新的（按 added_at 降序）
        candidates.sort(key=lambda i: i["added_at"], reverse=True)
        target = candidates[0]
        try:
            r = wechat.publish_draft(target["draft_media_id"])
            queue.update(target["id"], status="published", publish_id=r.get("publish_id"))
            return f"✅ 已发布《{target['title']}》\npublish_id: {r.get('publish_id')}"
        except Exception as e:
            return f"❌ 发布失败: {e}"

    return f"❓ 没看懂指令。回复 \"帮助\" 看可用指令"


# ===== 主循环 =====

def load_buf() -> str:
    return UPDATE_BUF_FILE.read_text().strip() if UPDATE_BUF_FILE.exists() else ""


def save_buf(buf: str):
    UPDATE_BUF_FILE.write_text(buf or "")


def extract_messages(updates: dict) -> list:
    """从 getupdates 返回里抠出文本消息列表 [(text, from_user, context_token)...]"""
    out = []
    msgs = updates.get("msg_list", []) or updates.get("messages", []) or []
    for msg in msgs:
        # 跳过 bot 自己发的
        if msg.get("message_type") == 2:
            continue
        from_user = msg.get("from_user_id", "")
        context_token = msg.get("context_token", "")
        for item in msg.get("item_list", []) or []:
            if item.get("type") == 1 and item.get("text_item"):
                out.append((item["text_item"].get("text", ""), from_user, context_token))
    return out


def loop():
    if not BOT_TOKEN:
        print("[cloudbot] 缺少 ILINK_BOT2_TOKEN（或 ILINK_BOT_TOKEN）", file=sys.stderr)
        sys.exit(1)
    print(f"[cloudbot] 启动，bot={BOT_ACCOUNT[:20]}... user={USER_ID[:30]}...")
    buf = load_buf()
    while True:
        try:
            updates = get_updates(buf)
            new_buf = updates.get("get_updates_buf") or buf
            if new_buf != buf:
                buf = new_buf
                save_buf(buf)
            msgs = extract_messages(updates)
            for text, from_user, ctx in msgs:
                print(f"[cloudbot] <- {from_user[:24]}: {text[:60]}")
                try:
                    resp = handle_text(text, from_user, ctx)
                    if resp:
                        reply(from_user, resp, ctx)
                        print(f"[cloudbot] -> {resp[:80]}")
                except Exception as e:
                    err = f"❌ 处理失败: {e}"
                    print(f"[cloudbot] error: {traceback.format_exc()}", file=sys.stderr)
                    try:
                        reply(from_user, err, ctx)
                    except Exception:
                        pass
        except requests.exceptions.RequestException as e:
            print(f"[cloudbot] 网络错误，10s 后重试: {e}", file=sys.stderr)
            time.sleep(10)
        except Exception as e:
            print(f"[cloudbot] 未知错误: {e}", file=sys.stderr)
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    loop()
