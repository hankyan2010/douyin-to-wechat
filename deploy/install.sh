#!/bin/bash
# 华为云部署脚本（CentOS 7 + miniconda 3.9）
set -e
ROOT=/root/douyin-to-wechat
PY=/root/miniconda3/bin/python
PIP=/root/miniconda3/bin/pip

cd "$ROOT"

echo "[1/4] 安装 Python 依赖..."
$PIP install -q -r requirements.txt

echo "[2/4] 验证 ffmpeg..."
ffmpeg -version | head -1

echo "[3/4] 设置 cron（每天 07:00 北京时间）..."
SCRIPT="$ROOT/deploy/cron_daily.sh"
chmod +x "$SCRIPT"
( crontab -l 2>/dev/null | grep -v "douyin-to-wechat/deploy/cron_daily" ; echo "0 7 * * * $SCRIPT" ) | crontab -
crontab -l | grep cron_daily

echo "[4/4] 创建日志路径..."
touch /var/log/d2w-daily.log
chmod 644 /var/log/d2w-daily.log

echo ""
echo "✅ 部署完成"
echo "   测试运行：cd $ROOT && $PY -m src.notify '部署测试'"
echo "   手动触发日更：$SCRIPT"
echo "   日志：tail -f /var/log/d2w-daily.log"
