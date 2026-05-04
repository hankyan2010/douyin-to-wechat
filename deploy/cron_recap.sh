#!/bin/bash
# 每天 21:00 跑昨日数据复盘 + 推微信
set -e
cd /root/douyin-to-wechat
LOG=/var/log/d2w-recap.log
echo "===== $(date '+%F %T') start =====" >> "$LOG"
/root/miniconda3/bin/python -c "
from src import analytics
from src.notify import send_text
r = analytics.daily_report()
text = analytics.format_report(r)
print(text)
send_text(text)
" >> "$LOG" 2>&1
echo "===== $(date '+%F %T') end exit=$? =====" >> "$LOG"
