"""日更主流程（审核机制版）：

generate_one()         从 pending 取一条 → 完整生成 → 建草稿 → 标记 draft_ready + notified_at → 微信通知用户审核
auto_publish_due()     扫 draft_ready 状态 + notified_at 超过 60 分钟的 → 自动 publish_one
publish_one(id)        按 ID 发布(用户在微信回复"发 xxx"或自动兜底触发)
regen_one(id)          按 ID 用改后的 script.json 重渲染卡片+重建草稿+刷新 notified_at(用户改完字后用)

cron 5min        调 auto_publish_due — 兜底超时自动发
cloudbot URL     收到链接 → enqueue → 异步触发 generate_one — 生成第二天的草稿
手动触发         python -m src.daily_publish [generate|publish-one|regen|auto-publish-due]
"""
import argparse
import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import main as main_mod, notify, queue, wechat

CST = timezone(timedelta(hours=8))
REVIEW_DEADLINE_MIN = 60  # 草稿就绪后自动发布的等待时长(分钟)


def _pending_count() -> int:
    return len(queue.list_items(status="pending"))


def _draft_ready_count() -> int:
    return len(queue.list_items(status="draft_ready"))


def generate_one() -> dict:
    """从 pending 队列取一条 → 跑生成 → 建草稿 → 通知。"""
    item = queue.next_pending()
    if not item:
        print("[generate] 队列空")
        return {"ok": True, "skipped": "empty_queue"}

    print(f"[generate] 取出: {item['id']} url={item['url']}")
    queue.update(item["id"], status="processing")

    try:
        result = main_mod.run(item["url"], publish=False, max_cards=6)
        title = result["title"]
        draft_id = result["draft_media_id"]
        backend = result.get("backend", "")
        work_dir = result.get("work_dir", "")
        notified_at = datetime.now(CST).isoformat(timespec="seconds")

        queue.update(
            item["id"],
            status="draft_ready",
            title=title,
            draft_media_id=draft_id,
            work_dir=work_dir,
            notified_at=notified_at,
        )

        # 读 script.json 拿 lead + 卡片摘要
        try:
            script = json.loads((Path(work_dir) / "script.json").read_text(encoding="utf-8"))
            lead = script.get("lead", "")
            cards = script.get("cards", [])
        except Exception:
            lead, cards = "", []

        n = notify.notify_pending_review(item["id"], title, lead, cards,
                                          backend=backend, deadline_min=REVIEW_DEADLINE_MIN)
        print(f"[generate] notify: {n}")

        return {"ok": True, "action": "generate", "item_id": item["id"],
                "title": title, "draft_media_id": draft_id,
                "notified_at": notified_at, "notify": n}

    except Exception as e:
        traceback.print_exc()
        queue.update(item["id"], status="failed", title=str(e)[:200])
        try:
            notify.notify_failed(item["id"], str(e))
        except Exception:
            pass
        return {"ok": False, "error": str(e)}


def publish_due() -> dict:
    """从 draft_ready 取最早入队那条 → 发布 → 通知。"""
    items = queue.list_items(status="draft_ready")
    items.sort(key=lambda i: i["added_at"])  # 最早的优先发
    if not items:
        print("[publish] 没有待发草稿")
        notify.send_text("⚠️ 7点自动发布：今天没有待发草稿（draft_ready 队列空）")
        return {"ok": True, "skipped": "no_draft"}

    item = items[0]
    if not item.get("draft_media_id"):
        print(f"[publish] {item['id']} 无 draft_media_id，跳过")
        return {"ok": False, "error": "missing draft_media_id"}

    print(f"[publish] 发布 {item['id']}: 《{item['title']}》")
    try:
        r = wechat.publish_draft(item["draft_media_id"])
        publish_id = r.get("publish_id")
        queue.update(item["id"], status="published", publish_id=publish_id)
        n = notify.notify_published(item["title"], publish_id)
        print(f"[publish] notify: {n}")
        return {"ok": True, "action": "publish", "item_id": item["id"],
                "title": item["title"], "publish_id": publish_id, "notify": n}
    except Exception as e:
        traceback.print_exc()
        try:
            notify.notify_failed(item["id"], f"自动发布失败: {e}")
        except Exception:
            pass
        return {"ok": False, "error": str(e)}


PUBLISH_COOLDOWN_HOURS = 20  # 两次自动发布间隔下限(防一次发多条)


def auto_publish_due() -> dict:
    """扫 draft_ready 状态 + notified_at 已超 REVIEW_DEADLINE_MIN 的草稿,自动发布。
    cron 每 5 分钟跑一次,实现"1 小时不回自动发"机制。
    保护:同时多条超时时,只发一条;且 PUBLISH_COOLDOWN_HOURS 内已发过就跳过。"""
    all_items = queue._load() if hasattr(queue, "_load") else queue.list_items(limit=9999)
    now = datetime.now(CST)

    # 1) 检查冷却:近 N 小时内有没有已发过
    cooldown = timedelta(hours=PUBLISH_COOLDOWN_HOURS)
    for i in all_items:
        if i.get("status") != "published":
            continue
        pub_at = i.get("published_at")
        if not pub_at:
            continue
        try:
            if now - datetime.fromisoformat(pub_at) < cooldown:
                print(f"[auto-publish] 冷却中 (上次发布 {pub_at}, 间隔需 ≥ {PUBLISH_COOLDOWN_HOURS}h)")
                return {"ok": True, "skipped": "cooldown", "last_published_at": pub_at}
        except Exception:
            continue

    # 2) 找超时草稿
    items = [i for i in all_items if i.get("status") == "draft_ready"]
    deadline = timedelta(minutes=REVIEW_DEADLINE_MIN)
    due = []
    for i in items:
        notified_at_str = i.get("notified_at")
        if not notified_at_str:
            continue
        try:
            notified_at = datetime.fromisoformat(notified_at_str)
            if now - notified_at >= deadline:
                due.append(i)
        except Exception:
            continue

    if not due:
        print(f"[auto-publish] 没有超时草稿 (审核中 {len(items)} 条)")
        return {"ok": True, "skipped": "no_due", "in_review": len(items)}

    # 3) 发最早的一条
    due.sort(key=lambda i: i["notified_at"])
    item = due[0]
    waited_min = (now - datetime.fromisoformat(item["notified_at"])).total_seconds() / 60
    print(f"[auto-publish] {item['id']} 等待 {waited_min:.0f} 分钟,自动发布: 《{item['title']}》")
    return publish_one(item["id"])


def regen_one(item_id: str) -> dict:
    """从已修改的 script.json 重建草稿(审核流程核心命令)。
    1) 按 item_id 找到对应的 work_dir
    2) 调 main.regenerate_from_script
    3) 更新 queue 的 draft_media_id
    """
    items = queue.list_items()
    matched = [i for i in items if i["id"] == item_id or i["id"].startswith(item_id)]
    if not matched:
        return {"ok": False, "error": f"id not found: {item_id}"}
    item = matched[0]
    work_dir = item.get("work_dir")
    if not work_dir:
        return {"ok": False, "error": f"item {item['id']} 没有 work_dir 字段(可能是旧数据,跑 generate 重新生成)"}
    print(f"[regen] {item['id']} work_dir={work_dir}")
    try:
        result = main_mod.regenerate_from_script(Path(work_dir), publish=False)
        new_draft_id = result["draft_media_id"]
        new_title = result["title"]
        # 重建后刷新 notified_at,审核窗口重置 (用户改完字给新版多看 1 小时)
        notified_at = datetime.now(CST).isoformat(timespec="seconds")
        queue.update(item["id"], title=new_title, draft_media_id=new_draft_id,
                     status="draft_ready", notified_at=notified_at)
        # 推新通知
        try:
            script = json.loads((Path(work_dir) / "script.json").read_text(encoding="utf-8"))
            n = notify.notify_pending_review(item["id"], new_title,
                                              script.get("lead", ""), script.get("cards", []),
                                              backend="claude_bridge_regen",
                                              deadline_min=REVIEW_DEADLINE_MIN)
        except Exception as e:
            n = {"err": str(e)}
        return {"ok": True, "action": "regen", "item_id": item["id"],
                "title": new_title, "draft_media_id": new_draft_id,
                "notified_at": notified_at, "notify": n}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def publish_one(item_id: str) -> dict:
    """按 ID 发布指定的 draft_ready 条目（审核通过后用）。"""
    items = queue.list_items()
    matched = [i for i in items if i["id"] == item_id or i["id"].startswith(item_id)]
    if not matched:
        print(f"[publish_one] 找不到 ID={item_id}")
        return {"ok": False, "error": f"id not found: {item_id}"}
    item = matched[0]
    if item.get("status") != "draft_ready":
        print(f"[publish_one] {item['id']} 状态={item.get('status')},不是 draft_ready")
        return {"ok": False, "error": f"status={item.get('status')}"}
    if not item.get("draft_media_id"):
        return {"ok": False, "error": "missing draft_media_id"}
    print(f"[publish_one] 发布 {item['id']}: 《{item['title']}》")
    try:
        r = wechat.publish_draft(item["draft_media_id"])
        publish_id = r.get("publish_id")
        published_at = datetime.now(CST).isoformat(timespec="seconds")
        queue.update(item["id"], status="published", publish_id=publish_id,
                     published_at=published_at)
        try:
            n = notify.notify_published(item["title"], publish_id)
            print(f"[publish_one] notify: {n}")
        except Exception:
            pass
        return {"ok": True, "action": "publish_one", "item_id": item["id"],
                "title": item["title"], "publish_id": publish_id,
                "published_at": published_at}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", nargs="?", default="publish",
                   choices=["publish", "generate", "run-one", "publish-one", "regen", "auto-publish-due"],
                   help="publish: 发最早 draft_ready / generate: 生成 / publish-one: 按 ID 发 / regen: 改完 script.json 重建草稿 / auto-publish-due: cron 兜底超时自动发")
    p.add_argument("--id", help="publish-one / regen 时指定的条目 ID (支持前缀)")
    args = p.parse_args()

    if args.action == "publish":
        out = publish_due()
    elif args.action == "auto-publish-due":
        out = auto_publish_due()
    elif args.action == "publish-one":
        if not args.id:
            print("[error] publish-one 需要 --id <item_id>"); sys.exit(2)
        out = publish_one(args.id)
    elif args.action == "regen":
        if not args.id:
            print("[error] regen 需要 --id <item_id>"); sys.exit(2)
        out = regen_one(args.id)
    else:
        out = generate_one()

    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)


# 旧名兼容（cloudbot listener 之前调用的接口）
def run_one(force_publish: bool = False) -> dict:
    return generate_one()


if __name__ == "__main__":
    main()
