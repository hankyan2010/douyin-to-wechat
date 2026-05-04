"""日更主流程：cron 调用入口。

逻辑：
1. 取队列下一条 pending（按 priority DESC, added_at ASC）
2. 跑 main.run（默认 publish=False，只建草稿）
3. 草稿建好后，发微信通知
4. 队列项标记 status=draft_ready，回填 draft_media_id / title

环境变量：
  DAILY_AUTOPUBLISH=1     如果设了，跳过通知，直接发布（不推荐，谨慎）
"""
import argparse
import os
import sys
import traceback
from pathlib import Path

from . import main as main_mod, notify, queue


def run_one(force_publish: bool = False) -> dict:
    item = queue.next_pending()
    if not item:
        print("[daily] 队列为空，跳过")
        return {"ok": True, "skipped": "empty_queue"}

    print(f"[daily] 取出: {item['id']} url={item['url']}")
    queue.update(item["id"], status="processing")

    try:
        result = main_mod.run(
            item["url"],
            publish=force_publish,
            max_cards=6,
        )
        title = result["title"]
        draft_id = result["draft_media_id"]
        publish_id = result.get("publish_id")
        backend = result.get("backend", "")

        # 回填
        queue.update(
            item["id"],
            status="published" if publish_id else "draft_ready",
            title=title,
            draft_media_id=draft_id,
            publish_id=publish_id,
        )

        # 推送通知
        pending_left = len(queue.list_items(status="pending"))
        if publish_id:
            n = notify.notify_published(title, publish_id)
        else:
            n = notify.notify_draft_ready(title, draft_id, pending_left, item["url"], backend=backend)
        print(f"[daily] notify: {n}")

        return {"ok": True, "item_id": item["id"], "title": title,
                "draft_media_id": draft_id, "publish_id": publish_id,
                "notify": n}

    except Exception as e:
        traceback.print_exc()
        queue.update(item["id"], status="failed", title=str(e)[:200])
        # 失败也通知
        try:
            notify.push_via_custom_message(f"❌ 日更失败 {item['id']}: {e}")
        except Exception:
            pass
        return {"ok": False, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--publish", action="store_true",
                   help="直接发布（不推荐，默认只建草稿等审核）")
    args = p.parse_args()
    force_publish = args.publish or os.getenv("DAILY_AUTOPUBLISH") == "1"
    import json
    out = run_one(force_publish=force_publish)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
