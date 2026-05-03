"""抖音链接解析（轻量版：curl + iPhone UA + 跟随 302 + 解析 _ROUTER_DATA）。

短链 https://v.douyin.com/xxx/ 会 302 到
https://www.iesdouyin.com/share/video/{aweme_id}/ ——
后者的 SSR HTML 里嵌了 _ROUTER_DATA，含完整 aweme 信息（含无水印 URL）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def _extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s,，。]+", text)
    if not m:
        raise ValueError(f"未在文本里找到 URL: {text!r}")
    return m.group(0)


def fetch_aweme(url: str) -> dict:
    """跟随短链 → 拉 iesdouyin SSR HTML → 解析 _ROUTER_DATA。"""
    r = requests.get(
        url,
        headers={"User-Agent": UA_IPHONE},
        allow_redirects=True,
        timeout=20,
    )
    r.raise_for_status()
    html = r.text

    m = re.search(r"_ROUTER_DATA\s*=\s*(\{.+?\})\s*</script>", html, re.S)
    if not m:
        raise RuntimeError("HTML 中未找到 _ROUTER_DATA（可能链接已失效或被风控）")

    data = json.loads(m.group(1))
    page = data.get("loaderData", {}).get("video_(id)/page", {})
    items = page.get("videoInfoRes", {}).get("item_list", [])
    if not items:
        # 可能是图集 (note)
        page = data.get("loaderData", {}).get("note_(id)/page", {})
        items = page.get("videoInfoRes", {}).get("item_list", [])
    if not items:
        raise RuntimeError(f"_ROUTER_DATA 中未找到 item_list；页面 keys={list(page.keys())}")
    return items[0]


def pick_play_url(aweme: dict) -> str:
    video = aweme.get("video", {})
    for key in ("play_addr", "play_addr_h264", "play_addr_265"):
        play = video.get(key, {})
        urls = play.get("url_list") or []
        for u in urls:
            return u.replace("playwm", "play").replace("&watermark=1", "")
    raise RuntimeError(f"未找到播放 URL: {json.dumps(video, ensure_ascii=False)[:300]}")


def download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": UA_IPHONE, "Referer": "https://www.douyin.com/"}
    with requests.get(url, headers=headers, stream=True, timeout=120, allow_redirects=True) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    return out_path


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-f", "wav", str(audio_path),
    ]
    subprocess.run(cmd, check=True)
    return audio_path


def parse(url_or_text: str, work_dir: Path) -> dict:
    short = _extract_url(url_or_text)
    aweme = fetch_aweme(short)
    video_id = str(aweme.get("aweme_id", "unknown"))
    desc = aweme.get("desc", "")
    play_url = pick_play_url(aweme)

    video_path = work_dir / f"{video_id}.mp4"
    audio_path = work_dir / f"{video_id}.wav"

    print(f"[parse] video_id={video_id}")
    print(f"[parse] desc={desc[:80]}")
    print(f"[parse] play_url={play_url[:120]}...")

    download(play_url, video_path)
    print(f"[parse] downloaded: {video_path} ({video_path.stat().st_size // 1024} KB)")

    extract_audio(video_path, audio_path)
    print(f"[parse] audio: {audio_path}")

    return {
        "video_id": video_id,
        "desc": desc,
        "video_path": str(video_path),
        "audio_path": str(audio_path),
        "play_url": play_url,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python parse_douyin.py <抖音链接或分享文本>")
        sys.exit(1)
    out = parse(sys.argv[1], Path(__file__).parent.parent / "output" / "tmp")
    print(json.dumps(out, ensure_ascii=False, indent=2))
