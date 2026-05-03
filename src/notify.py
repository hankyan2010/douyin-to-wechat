"""微信通知推送（ilinkai CloudBot API）。

纯腾讯云端服务，不依赖本机 wechat-claude-code daemon。

环境变量：
  ILINK_BOT_TOKEN     bot token，形如 xxx@im.bot:xxxxx
  ILINK_BOT_ACCOUNT   bot 账号，形如 xxx@im.bot（token 冒号前的部分）
  ILINK_USER_ID       接收方 user_id，形如 oXxxx@im.wechat
"""
import base64
import json
import os
import secrets
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

ILINK_BASE = "https://ilinkai.weixin.qq.com"
BOT_TOKEN = os.getenv("ILINK_BOT_TOKEN", "")
BOT_ACCOUNT = os.getenv("ILINK_BOT_ACCOUNT", "")
USER_ID = os.getenv("ILINK_USER_ID", "")


def _uin() -> str:
    return base64.b64encode(secrets.token_bytes(4)).decode()


def _client_id() -> str:
    # 任意稳定的 32 位 hex 即可
    return secrets.token_hex(16)


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BOT_TOKEN}",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _uin(),
    }


def send_text(text: str, to_user: str = None, context_token: str = "") -> dict:
    """主动给指定用户推一条文本。"""
    if not BOT_TOKEN or not BOT_ACCOUNT:
        raise RuntimeError("缺少 ILINK_BOT_TOKEN / ILINK_BOT_ACCOUNT")
    to_user = to_user or USER_ID
    if not to_user:
        raise RuntimeError("缺少 ILINK_USER_ID")

    body = {
        "msg": {
            "from_user_id": BOT_ACCOUNT,
            "to_user_id": to_user,
            "client_id": _client_id(),
            "message_type": 2,        # BOT
            "message_state": 2,       # FINISH
            "context_token": context_token,
            "item_list": [
                {"type": 1, "text_item": {"text": text}}
            ],
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
        return {"http_status": r.status_code, "text": r.text[:500]}


def notify_draft_ready(title: str, draft_media_id: str, queue_pos: int = 0,
                       url: str = "") -> dict:
    text = (
        f"📝 公众号日更草稿已建好\n\n"
        f"《{title}》\n\n"
        f"draft_id: {draft_media_id[:24]}...\n"
        f"剩余队列: {queue_pos} 条\n"
        + (f"原视频: {url}\n" if url else "")
        + "\n操作方式：\n"
        f"① 公众号后台直接发布\n"
        f"② 回复\"发布\"让机器人自动发"
    )
    return send_text(text)


def notify_published(title: str, publish_id: int) -> dict:
    return send_text(f"✅ 已发布《{title}》\npublish_id: {publish_id}")


def notify_failed(item_id: str, err: str) -> dict:
    return send_text(f"❌ 日更失败 {item_id}\n{err[:300]}")


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "🦐 测试推送来自 douyin-to-wechat"
    print(json.dumps(send_text(text), ensure_ascii=False, indent=2))
