"""端到端：抖音链接 → 公众号贴图。

用法：
  python -m src.main "<抖音链接或分享文本>" [--publish] [--max-cards 6]
默认：仅存草稿（去公众号后台手动发布更稳）。加 --publish 才立即群发。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import asr, cards, parse_douyin, rewrite, wechat


def run(url: str, publish: bool = False, max_cards: int = 6, work_root: Path = None):
    work_root = work_root or Path(__file__).parent.parent / "output"
    ts = time.strftime("%Y%m%d-%H%M%S")
    work_dir = work_root / ts
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"[main] 工作目录: {work_dir}\n")

    # 1. 解析抖音
    print("=" * 50)
    print("Step 1/5: 解析抖音链接")
    print("=" * 50)
    parsed = parse_douyin.parse(url, work_dir)

    # 2. ASR
    print("\n" + "=" * 50)
    print("Step 2/5: 提取口播文案 (ASR)")
    print("=" * 50)
    transcript = asr.transcribe(parsed["audio_path"])
    (work_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    print(f"[asr] 文案 ({len(transcript)} 字):")
    print(transcript[:300] + ("..." if len(transcript) > 300 else ""))

    # 3. 改写贴图脚本
    print("\n" + "=" * 50)
    print("Step 3/5: 改写为贴图脚本")
    print("=" * 50)
    script = rewrite.rewrite(transcript, max_cards=max_cards)
    (work_dir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[rewrite] 标题: {script['title']}")
    print(f"[rewrite] 引导: {script['lead']}")
    print(f"[rewrite] 卡片数: {len(script['cards'])}")

    # 4. 生成卡片图（首张引导卡当封面）
    print("\n" + "=" * 50)
    print("Step 4/5: 渲染文案卡片")
    print("=" * 50)
    card_paths = cards.render_all(script, work_dir / "cards")
    print(f"[cards] 渲染 {len(card_paths)} 张（首张作封面）")
    image_paths = card_paths

    # 5. 公众号贴图发布
    print("\n" + "=" * 50)
    print(f"Step 5/5: 微信公众号 {'发布' if publish else '存草稿'}（评论默认开启）")
    print("=" * 50)
    result = wechat.publish_newspic(
        title=script["title"],
        content=script["lead"],
        image_paths=image_paths,
        publish=publish,
    )

    # 保存最终结果
    final = {
        "url": url,
        "title": script["title"],
        "backend": script.get("_backend", "unknown"),
        "transcript_chars": len(transcript),
        "cards_count": len(script["cards"]),
        "images_count": len(image_paths),
        **result,
    }
    (work_dir / "result.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 50)
    print("✅ 完成")
    print("=" * 50)
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return final


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url", help="抖音链接或分享文本")
    p.add_argument("--publish", action="store_true", help="立即群发（默认仅存草稿）")
    p.add_argument("--max-cards", type=int, default=6, help="内容卡数量上限（默认 6）")
    args = p.parse_args()

    try:
        run(args.url, publish=args.publish, max_cards=args.max_cards)
    except Exception as e:
        print(f"\n❌ 失败: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
