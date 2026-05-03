"""微信公众号 API（贴图 / newspic 模式）。

复用 wechat-mp-publish 的代理（华为云固定 IP 解决 API 白名单）。
"""
import json
import mimetypes
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("WECHAT_APP_ID")
APP_SECRET = os.getenv("WECHAT_APP_SECRET")
API_BASE = os.getenv("WECHAT_API_BASE", "http://121.36.105.43:18900/wechat-api")

TOKEN_CACHE = Path(__file__).parent.parent / ".wechat-token.json"


def get_token() -> str:
    if TOKEN_CACHE.exists():
        c = json.loads(TOKEN_CACHE.read_text())
        if c.get("expires_at", 0) > time.time():
            return c["access_token"]
    url = f"{API_BASE}/cgi-bin/token?grant_type=client_credential&appid={APP_ID}&secret={APP_SECRET}"
    r = requests.get(url, timeout=15).json()
    if "access_token" not in r:
        raise RuntimeError(f"Token error: {r}")
    TOKEN_CACHE.write_text(json.dumps({
        "access_token": r["access_token"],
        "expires_at": time.time() + r["expires_in"] - 300,
    }))
    return r["access_token"]


def upload_permanent_image(image_path: Path) -> str:
    """上传永久图文素材，返回 media_id（贴图必须用永久素材）。"""
    token = get_token()
    url = f"{API_BASE}/cgi-bin/material/add_material?access_token={token}&type=image"
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, mime)}
        r = requests.post(url, files=files, timeout=60).json()
    if "media_id" not in r:
        raise RuntimeError(f"上传失败 {image_path.name}: {r}")
    return r["media_id"]


def _truncate_bytes(s: str, max_bytes: int) -> str:
    """按 UTF-8 字节截断，不切坏字符。"""
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    cut = b[:max_bytes]
    while True:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]


def create_newspic_draft(title: str, content: str, image_media_ids: list,
                          need_open_comment: int = 1) -> str:
    """创建贴图草稿，返回 media_id。

    title 字段贴图限制较严（实测 ~30 字节 / 10 中文字），自动截断。
    content 字段是描述文字，限制宽松（数千字节）。
    """
    token = get_token()
    url = f"{API_BASE}/cgi-bin/draft/add?access_token={token}"
    title = _truncate_bytes(title, 90)  # 贴图标题：90 字节 ≈ 30 中文字
    content = _truncate_bytes(content, 600)
    article = {
        "article_type": "newspic",
        "title": title,
        "content": content,
        "need_open_comment": need_open_comment,
        "only_fans_can_comment": 0,
        "image_info": {
            "image_list": [{"image_media_id": mid} for mid in image_media_ids],
        },
    }
    # 关键：必须 ensure_ascii=False 用 raw bytes 发送，否则微信会把 \uXXXX 当字面字符存
    body = json.dumps({"articles": [article]}, ensure_ascii=False).encode("utf-8")
    r = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    ).json()
    if "media_id" not in r:
        raise RuntimeError(f"创建草稿失败: {r}")
    return r["media_id"]


def publish_draft(media_id: str) -> dict:
    token = get_token()
    url = f"{API_BASE}/cgi-bin/freepublish/submit?access_token={token}"
    body = json.dumps({"media_id": media_id}, ensure_ascii=False).encode("utf-8")
    r = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    ).json()
    if r.get("errcode", 0) != 0:
        raise RuntimeError(f"发布失败: {r}")
    return r


def publish_newspic(title: str, content: str, image_paths: list,
                    publish: bool = False) -> dict:
    """端到端：上传所有图 → 创建贴图草稿 → 可选立即发布。"""
    print(f"[wechat] 上传 {len(image_paths)} 张永久图片素材...")
    media_ids = []
    for i, p in enumerate(image_paths, 1):
        mid = upload_permanent_image(Path(p))
        print(f"  [{i}/{len(image_paths)}] {Path(p).name} → {mid[:20]}...")
        media_ids.append(mid)

    print(f"[wechat] 创建贴图草稿: {title}")
    draft_id = create_newspic_draft(title, content, media_ids)
    print(f"[wechat] 草稿 media_id: {draft_id}")

    result = {"draft_media_id": draft_id, "image_media_ids": media_ids}

    if publish:
        print("[wechat] 立即发布草稿...")
        pub = publish_draft(draft_id)
        result["publish_id"] = pub.get("publish_id")
        print(f"[wechat] 发布成功: publish_id={pub.get('publish_id')}")
    else:
        print("[wechat] 已存草稿，未发布。去公众号后台预览/发布。")

    return result


if __name__ == "__main__":
    import sys
    print(get_token()[:30] + "...")
