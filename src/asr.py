"""口播识别。

主路径：火山大模型录音文件识别（标准版）— 需 VOLC_ASR_APP_KEY + VOLC_ASR_ACCESS_KEY
备路径：本地 OpenAI Whisper — 自动下载 base 模型，纯 CPU 跑
"""
import json
import os
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

VOLC_ASR_APP_KEY = os.getenv("VOLC_ASR_APP_KEY", "")
VOLC_ASR_ACCESS_KEY = os.getenv("VOLC_ASR_ACCESS_KEY", "")

VOLC_SUBMIT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
VOLC_QUERY = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"


def _volc_headers(req_id: str) -> dict:
    return {
        "X-Api-App-Key": VOLC_ASR_APP_KEY,
        "X-Api-Access-Key": VOLC_ASR_ACCESS_KEY,
        "X-Api-Resource-Id": "volc.bigasr.auc",
        "X-Api-Request-Id": req_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json",
    }


def transcribe_volc(audio_url: str) -> str:
    """提交远程音频URL → 轮询 → 文本。

    audio_url 必须是公网可访问的 URL（火山服务器要去拉），
    所以本地音频得先上传到 OSS / 临时挂个 HTTP 服务。
    本项目走 fallback whisper 时不需要这步。
    """
    req_id = str(uuid.uuid4())
    body = {
        "user": {"uid": "douyin-to-wechat"},
        "audio": {"url": audio_url, "format": "wav", "codec": "raw"},
        "request": {"model_name": "bigmodel", "enable_punc": True},
    }
    r = requests.post(VOLC_SUBMIT, headers=_volc_headers(req_id), json=body, timeout=15)
    r.raise_for_status()
    if r.headers.get("X-Api-Status-Code") not in (None, "20000000"):
        raise RuntimeError(f"火山 ASR 提交失败: {r.headers} {r.text}")

    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(2)
        q = requests.post(VOLC_QUERY, headers=_volc_headers(req_id), json={}, timeout=15)
        status = q.headers.get("X-Api-Status-Code", "")
        if status == "20000000":
            data = q.json()
            return data.get("result", {}).get("text", "")
        if status.startswith("4") or status.startswith("5"):
            raise RuntimeError(f"火山 ASR 失败 status={status}: {q.text}")
    raise TimeoutError("火山 ASR 轮询超时")


def transcribe_whisper(audio_path: str) -> str:
    """本地 Whisper —— 纯 CPU，base 模型 ≈74M 参数，1分钟音频约 30s。"""
    try:
        import whisper  # type: ignore
    except ImportError:
        raise RuntimeError(
            "本地 Whisper 未安装。运行：pip install openai-whisper\n"
            "（需要 ffmpeg，已确认存在）"
        )
    model_name = os.getenv("WHISPER_MODEL", "base")
    print(f"[asr] loading whisper model={model_name} (首次会下载 ≈140MB)...")
    model = whisper.load_model(model_name)
    print(f"[asr] transcribing {audio_path}...")
    result = model.transcribe(audio_path, language="zh", fp16=False)
    return result.get("text", "").strip()


def proofread(text: str) -> str:
    """豆包修错别字：处理同音误识、英文专有名词错拼、缺失标点。"""
    if not text.strip():
        return text
    try:
        from openai import OpenAI
        ark_key = os.getenv("ARK_API_KEY")
        ark_model = os.getenv("ARK_MODEL", "doubao-seed-1-6-250615")
        if not ark_key:
            return text
        client = OpenAI(
            api_key=ark_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
        sys_prompt = (
            "你是 ASR 转写校对员，给一段抖音口播原文做错别字修正。\n\n"
            "【硬性规则】\n"
            "1. 只改明显错的，不改写句子，不增删任何信息\n"
            "2. 不要把口语词换成网络梗：\n"
            "   ✗ 把'大部分人'改成'麻瓜'/'小白'/'菜鸟'\n"
            "   ✗ 把'马瓜'当 muggle 去翻——大概率是'大部分'/'门外汉'被错识，按上下文判断\n"
            "3. 英文专有名词按通用拼写还原。常见 ASR 错配清单（必须套用）：\n"
            "   · Cloud Code / 克劳德 / 克劳的 → Claude Code\n"
            "   · Codex / Co-Dex → Codex\n"
            "   · GitHub / 给特哈 → GitHub\n"
            "   · Cursor / 克勒索 → Cursor\n"
            "   · Type Lapse / Tape Lapse / Typeless / 抬泼勒丝 → 不确定时保留'（专有名词）'占位，不要瞎猜\n"
            "   · 云书乳 / 云输入 / 云输 → '（云端工具，不确定）' 不要瞎猜成具体产品\n"
            "4. 中文同音错字按上下文修（'语输入'→'语音输入'，'各行化'→'个性化'，'OroCo'→'Oracle'）\n"
            "5. 不确定的英文专有名词，不要硬猜，原样保留并在后面加（？）\n"
            "6. 加合理标点（逗号/句号/问号），不加引号、括号、Markdown\n\n"
            "直接输出修正后文本，不要任何解释。"
        )
        resp = client.chat.completions.create(
            model=ark_model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        out = resp.choices[0].message.content.strip()
        return out or text
    except Exception as e:
        print(f"[asr] proofread 失败 ({e})，使用原文")
        return text


def transcribe(audio_path: str, audio_url: str = "", proofread_enabled: bool = True) -> str:
    """主入口：火山优先，没凭据走 whisper。默认开启豆包错别字修正。"""
    if VOLC_ASR_APP_KEY and VOLC_ASR_ACCESS_KEY and audio_url:
        print("[asr] using 火山大模型 ASR")
        raw = transcribe_volc(audio_url)
    else:
        print("[asr] 火山 ASR 凭据未配置，fallback 到本地 Whisper")
        raw = transcribe_whisper(audio_path)

    if proofread_enabled:
        print("[asr] 豆包校对错别字...")
        return proofread(raw)
    return raw


if __name__ == "__main__":
    import sys
    text = transcribe(sys.argv[1])
    print("---")
    print(text)
