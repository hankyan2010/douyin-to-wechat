"""日更主流程（拆为两个动作）：

generate_one()  从 pending 取第一条 → 跑完整生成（解析→ASR→改写→卡片）→ 建公众号草稿 → 标记 draft_ready → 推通知
publish_due()   从 draft_ready 取最早入队的一条 → 调 freepublish 发布 → 标记 published → 推通知

cron 7:00     调 publish_due() — 自动发布昨天生成好的草稿
cloudbot URL  收到链接 → enqueue → 立即异步触发 generate_one() — 生成第二天的草稿
手动触发      python -m src.daily_publish [publish|generate]
"""
import argparse
import json
import sys
import traceback
from pathlib import Path

from . import main as main_mod, notify, queue, wechat


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

        queue.update(
            item["id"],
            status="draft_ready",
            title=title,
            draft_media_id=draft_id,
            work_dir=work_dir,
        )

        ready_count = _draft_ready_count()
        n = notify.notify_draft_ready(title, draft_id, ready_count, item["url"], backend=backend)
        print(f"[generate] notify: {n}")

        return {"ok": True, "action": "generate", "item_id": item["id"],
                "title": title, "draft_media_id": draft_id, "notify": n}

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
        queue.update(item["id"], title=new_title, draft_media_id=new_draft_id, status="draft_ready")
        return {"ok": True, "action": "regen", "item_id": item["id"],
                "title": new_title, "draft_media_id": new_draft_id}
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
        queue.update(item["id"], status="published", publish_id=publish_id)
        try:
            n = notify.notify_published(item["title"], publish_id)
            print(f"[publish_one] notify: {n}")
        except Exception:
            pass
        return {"ok": True, "action": "publish_one", "item_id": item["id"],
                "title": item["title"], "publish_id": publish_id}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", nargs="?", default="publish",
                   choices=["publish", "generate", "run-one", "publish-one", "regen"],
                   help="publish: 发布最早 draft_ready / generate: 生成 pending → draft_ready / publish-one: 按 ID 发 / regen: 改完 script.json 重建草稿 / run-one: 旧版兼容")
    p.add_argument("--id", help="publish-one / regen 时指定的条目 ID (支持前缀)")
    args = p.parse_args()

    if args.action == "publish":
        out = publish_due()
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
