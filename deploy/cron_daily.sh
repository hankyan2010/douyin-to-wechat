#!/bin/bash
# 每天 7:00 由 cron 调用，跑日更主流程
set -e
cd /root/douyin-to-wechat
export PATH=/usr/local/bin:/usr/bin:/bin
LOG=/var/log/d2w-daily.log
echo "===== $(date '+%F %T') start =====" >> "$LOG"
/root/miniconda3/bin/python -m src.daily_publish publish >> "$LOG" 2>&1
EC=$?
echo "===== $(date '+%F %T') end exit=$EC =====" >> "$LOG"
exit $EC
