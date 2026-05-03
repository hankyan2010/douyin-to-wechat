# douyin-to-wechat

> 抖音口播视频 → 微信公众号 "贴图" 自动日更

个人业务管理系统的第一个功能模块。整个系统跑在云端，不依赖本机，通过微信 CloudBot 双向沟通：bot 主动推提醒，你回消息发指令。

## 工作流

```
你微信发抖音链接
   ↓ (CloudBot 接收)
入待更素材队列 (queue.json)

每天早 7:00 (cron):
   抖音链接
     ↓ parse_douyin       iesdouyin SSR → 无水印 MP4 + 音频
     ↓ asr                 本地 Whisper (可切火山ASR)
     ↓ proofread           豆包修错别字 / 还原英文专名
     ↓ rewrite             豆包改写为贴图脚本（标题+引导+N张卡片）
     ↓ cards               PIL 渲染 1080×1440 小红书风
     ↓ wechat              永久素材 → newspic 草稿
   ↓ ilinkai 推送通知
你收到提醒，去公众号后台审核

发布两种方式：
  ① 公众号后台直接发
  ② 回 "发布" 给 bot → 自动调 freepublish
```

## 项目结构

```
src/
  parse_douyin.py     抖音解析（curl + iesdouyin SSR，无需登录）
  asr.py              口播识别（Whisper / 火山ASR）+ 豆包校对
  rewrite.py          口播 → 贴图脚本（豆包）
  cards.py            脚本 → 1080×1440 卡片图（PIL）
  wechat.py           公众号 newspic API（草稿/发布/上传）
  notify.py           ilinkai CloudBot 主动推送
  queue.py            日更素材队列（JSON 文件锁）
  daily_publish.py    cron 入口：取队列 → 跑全流程 → 推通知
  main.py             单链接端到端（手动触发）
```

## 用法

### 手动跑单条
```bash
python -m src.main "<抖音链接>" [--publish]
```

### 加入日更队列
```bash
python -m src.queue add "<抖音链接>" [--priority]
python -m src.queue list
python -m src.queue stats
```

### cron 日更
```bash
# crontab -e
0 7 * * * cd /root/douyin-to-wechat && /opt/miniconda3/bin/python -m src.daily_publish >> /var/log/daily-publish.log 2>&1
```

## 部署（华为云 / 任意云主机）

需要 Python 3.10+ + ffmpeg + Chrome 不必。CentOS 7 推荐用 miniconda 装 Python。

```bash
# 1. 装 miniconda
curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh | bash -s -- -b -p /opt/miniconda3

# 2. 装 ffmpeg
yum install -y epel-release && yum install -y ffmpeg  # 或 dnf install ffmpeg

# 3. 拉代码
git clone https://github.com/<you>/douyin-to-wechat.git /root/douyin-to-wechat
cd /root/douyin-to-wechat

# 4. 装依赖
/opt/miniconda3/bin/pip install -r requirements.txt
/opt/miniconda3/bin/pip install openai-whisper

# 5. 配置
cp .env.example .env
vim .env   # 填凭据

# 6. cron
crontab -e
# 加：0 7 * * * cd /root/douyin-to-wechat && /opt/miniconda3/bin/python -m src.daily_publish >> /var/log/daily-publish.log 2>&1
```

## 凭据获取

| 凭据 | 哪里拿 |
|---|---|
| `VOLC_AK/SK` | 火山引擎控制台 → 访问密钥 |
| `ARK_API_KEY` | 火山方舟 → API Key 管理 |
| `WECHAT_APP_ID/SECRET` | 公众号后台 → 设置与开发 → 基本配置 |
| `ILINK_*` | https://ilinkai.weixin.qq.com 创建机器人 |

## 设计决策记录

- **为什么不用浏览器自动化解析抖音**：iesdouyin 分享页 SSR 直接吐 `_ROUTER_DATA`（含完整 aweme + 无水印 URL），curl + iPhone UA 即可。最初用 DrissionPage 走了弯路。
- **为什么用本地 Whisper 而非火山 ASR**：开通火山语音技术服务需要单独 AppKey/Token，本地 Whisper base 模型 ~140MB / 1分钟音频约 30s，已够用。火山 ASR 凭据存在时自动切换。
- **为什么 1080×1440 不是 1080×1080**：微信贴图官方推荐 3:4 比例（朋友圈完整呈现）。最初做错了。
- **为什么贴图标题要反常识**：贴图核心是"滑动看下一张"的内容形态，标题不抓人就没人滑。

## License

MIT
