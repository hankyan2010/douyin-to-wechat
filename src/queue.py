"""日更素材队列。

存储：~/douyin-to-wechat/queue.json （JSON 数组，原子读写）
排序规则：priority DESC, added_at ASC
"""
import argparse
import fcntl
import json
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
QUEUE_FILE = Path(__file__).parent.parent / "queue.json"


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _load() -> list:
    if not QUEUE_FILE.exists():
        return []
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def _save(items: list):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(QUEUE_FILE)


def _with_lock(fn):
    """读写时加文件锁，防多 cron 并发。"""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = QUEUE_FILE.with_suffix(".lock")
    lock.touch(exist_ok=True)
    with open(lock, "r+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def add(url: str, priority: int = 0, source: str = "cli") -> dict:
    """入队。url 可以是分享文本，会自动抠链接（在 publish 阶段抠）。"""

    def _do():
        items = _load()
        # 去重（pending 状态的同 URL 不重复入队）
        for it in items:
            if it["url"] == url and it["status"] == "pending":
                return it
        item = {
            "id": uuid.uuid4().hex[:12],
            "url": url,
            "added_at": _now(),
            "priority": priority,
            "status": "pending",
            "scheduled_at": None,
            "publish_id": None,
            "draft_media_id": None,
            "title": None,
            "source": source,
        }
        items.append(item)
        _save(items)
        return item

    return _with_lock(_do)


def list_items(status: str = None, limit: int = 50) -> list:
    items = _load()
    if status:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (-i["priority"], i["added_at"]))
    return items[:limit]


def next_pending() -> dict:
    """取出优先级最高、最早入队的 pending 项（不出队，由 publish 阶段标记 done）。"""
    items = list_items(status="pending")
    return items[0] if items else None


def update(item_id: str, **fields) -> dict:
    def _do():
        items = _load()
        for i in items:
            if i["id"] == item_id:
                i.update(fields)
                _save(items)
                return i
        raise KeyError(item_id)

    return _with_lock(_do)


def remove(item_id: str) -> bool:
    def _do():
        items = _load()
        new = [i for i in items if i["id"] != item_id]
        if len(new) == len(items):
            return False
        _save(new)
        return True

    return _with_lock(_do)


def stats() -> dict:
    items = _load()
    out = {"total": len(items), "by_status": {}}
    for i in items:
        out["by_status"][i["status"]] = out["by_status"].get(i["status"], 0) + 1
    return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="入队")
    p_add.add_argument("url")
    p_add.add_argument("--priority", type=int, default=0)
    p_add.add_argument("--source", default="cli")

    sub.add_parser("list", help="列出全部")
    sub.add_parser("pending", help="只看待办")
    sub.add_parser("next", help="看下一条要发的")
    sub.add_parser("stats", help="统计")

    p_rm = sub.add_parser("remove", help="按 ID 删除")
    p_rm.add_argument("id")

    args = p.parse_args()

    if args.cmd == "add":
        item = add(args.url, args.priority, args.source)
        pos = sum(1 for i in list_items(status="pending")
                  if (-i["priority"], i["added_at"]) <= (-item["priority"], item["added_at"]))
        print(json.dumps({"ok": True, "id": item["id"], "queue_position": pos,
                          "total_pending": len(list_items(status="pending"))},
                         ensure_ascii=False))
    elif args.cmd in ("list", "pending"):
        items = list_items(status="pending" if args.cmd == "pending" else None)
        for i, it in enumerate(items, 1):
            mark = "★" if it["priority"] > 0 else " "
            print(f"{i:2d}. {mark} [{it['status']:10s}] {it['id']}  {it['url'][:60]}")
    elif args.cmd == "next":
        nxt = next_pending()
        print(json.dumps(nxt, ensure_ascii=False, indent=2) if nxt else "队列空")
    elif args.cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "remove":
        ok = remove(args.id)
        print("ok" if ok else "not found")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
