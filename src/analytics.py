"""数据复盘：拉昨日公众号数据，格式化为复盘报告，推送到微信。

数据源（公众号官方 datacube API）：
  getuserread       图文页阅读统计（按 user_source 拆分）
  getusersummary    粉丝增减
  getusershare      转发统计
  getuser_summary   用户增减详细
  freepublish/batchget  当天发布的文章列表

⚠️ getarticlesummary 接口只统计**群发的图文**，**贴图（newspic）不算**。
   单篇贴图的阅读量需要从公众号后台 → 内容分析 → 贴图 手动看。
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .wechat import API_BASE, get_token

CST = timezone(timedelta(hours=8))


# user_source 字段含义对照
USER_SOURCE_LABELS = {
    0: "公众号会话",
    1: "好友转发",
    2: "聊天会话/群聊",
    3: "看一看精选",
    4: "看一看",
    5: "搜一搜",
    6: "支付完成页",
    7: "公众号文章广告",
    8: "其他",
    100: "卡券",
    101: "支付凭证",
    149: "搜索",
    200: "二维码",
    201: "图文页内公众号名称",
    202: "图文末尾公众号名片",
    99999999: "合计",
}


def _post(endpoint: str, body: dict) -> dict:
    token = get_token()
    url = f"{API_BASE}/{endpoint}?access_token={token}"
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = requests.post(url, data=raw,
                      headers={"Content-Type": "application/json; charset=utf-8"},
                      timeout=20)
    r.encoding = "utf-8"
    return r.json()


def fetch_user_read(date: str) -> dict:
    return _post("datacube/getuserread", {"begin_date": date, "end_date": date})


def fetch_user_summary(date: str) -> dict:
    return _post("datacube/getusersummary", {"begin_date": date, "end_date": date})


def fetch_user_share(date: str) -> dict:
    return _post("datacube/getusershare", {"begin_date": date, "end_date": date})


def fetch_published_articles(limit: int = 20) -> list:
    """最近发布的 N 条 freepublish 文章。"""
    res = _post("cgi-bin/freepublish/batchget",
                {"offset": 0, "count": limit, "no_content": 1})
    out = []
    for item in res.get("item", []):
        update_time = item.get("update_time", 0)
        for n in item.get("content", {}).get("news_item", []):
            out.append({
                "publish_id": item.get("article_id"),
                "title": n.get("title", ""),
                "article_type": n.get("article_type", ""),
                "url": n.get("url", ""),
                "update_time": update_time,
                "update_dt": datetime.fromtimestamp(update_time, CST).isoformat(timespec="minutes"),
            })
    return out


def aggregate_read(user_read_list: list) -> dict:
    """把多个 user_source 行合并成一份汇总。"""
    total_users = 0
    total_reads = 0
    by_source = {}
    for row in user_read_list:
        src = row.get("user_source", 0)
        u = row.get("int_page_read_user", 0)
        c = row.get("int_page_read_count", 0)
        if src == 99999999:
            total_users = u
            total_reads = c
        else:
            label = USER_SOURCE_LABELS.get(src, f"未知({src})")
            by_source[label] = {"users": u, "reads": c}
    return {"total_users": total_users, "total_reads": total_reads, "by_source": by_source}


def aggregate_users(user_summary_list: list) -> dict:
    new = 0
    cancel = 0
    by_source = {}
    for row in user_summary_list:
        n = row.get("new_user", 0)
        c = row.get("cancel_user", 0)
        new += n
        cancel += c
        src = row.get("user_source", 0)
        label = USER_SOURCE_LABELS.get(src, f"未知({src})")
        by_source[label] = {"new": n, "cancel": c}
    return {"new": new, "cancel": cancel, "net": new - cancel, "by_source": by_source}


def aggregate_share(user_share_list: list) -> dict:
    sh_user = sum(r.get("share_user", 0) for r in user_share_list)
    sh_count = sum(r.get("share_count", 0) for r in user_share_list)
    return {"share_users": sh_user, "share_counts": sh_count}


def yesterday() -> str:
    return (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")


def daily_report(date: str = None) -> dict:
    date = date or yesterday()
    read = aggregate_read(fetch_user_read(date).get("list", []))
    users = aggregate_users(fetch_user_summary(date).get("list", []))
    share = aggregate_share(fetch_user_share(date).get("list", []))
    articles = fetch_published_articles(limit=10)
    # 当日发布的（按 update_time 在 date 这一天）
    same_day = [a for a in articles if a["update_dt"].startswith(date)]
    return {
        "date": date,
        "read": read,
        "users": users,
        "share": share,
        "articles_published_today": same_day,
        "recent_articles": articles[:5],
    }


def format_report(r: dict) -> str:
    lines = []
    lines.append(f"📊 {r['date']} 数据复盘\n")

    # 阅读
    lines.append(f"📖 阅读：{r['read']['total_users']} 人 / {r['read']['total_reads']} 次")
    if r['read']['by_source']:
        srcs = sorted(r['read']['by_source'].items(), key=lambda kv: -kv[1]['reads'])[:3]
        for label, d in srcs:
            lines.append(f"   · {label}: {d['users']}人/{d['reads']}次")
    lines.append("")

    # 粉丝
    u = r['users']
    arrow = "📈" if u['net'] > 0 else ("📉" if u['net'] < 0 else "➖")
    lines.append(f"👥 粉丝：{arrow} 净 {u['net']:+d}（新增 {u['new']} / 取关 {u['cancel']}）")
    if u['by_source']:
        for label, d in sorted(u['by_source'].items(), key=lambda kv: -kv[1]['new'])[:3]:
            if d['new'] > 0:
                lines.append(f"   · 新增来自 {label}: {d['new']}")
    lines.append("")

    # 分享
    s = r['share']
    lines.append(f"🔁 转发：{s['share_users']} 人 / {s['share_counts']} 次")
    lines.append("")

    # 当日发布
    lines.append(f"📝 当日发布 {len(r['articles_published_today'])} 篇:")
    for a in r['articles_published_today']:
        tag = "[贴图]" if a['article_type'] == 'newspic' else ""
        lines.append(f"   · {tag}《{a['title']}》 {a['update_dt'][-5:]}")
    if not r['articles_published_today']:
        lines.append("   （无）")
    lines.append("")

    lines.append("⚠️ 贴图单篇阅读不在 API，需去公众号后台→内容分析→贴图 看")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    r = daily_report(date)
    print(format_report(r))
    print()
    print("=== raw json ===")
    print(json.dumps(r, ensure_ascii=False, indent=2))
