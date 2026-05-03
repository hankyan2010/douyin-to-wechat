"""文案 → 小红书风卡片图（PIL 直绘，3:4，1080×1440 — 微信贴图官方推荐比例）。

风格：米白底 / 大字标题 / 圆角图块 / 柔和投影感 / 序号角标。
"""
import os
import textwrap
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()
BRAND = os.getenv("BRAND_NAME", "虾笔刀")

# 字体路径优先级（macOS 自带 → fallback）
FONT_CANDIDATES = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                # PingFang.ttc 索引：0=轻 1=细 2=常规 3=中黑 4=粗 5=重
                idx = 4 if bold else 2
                return ImageFont.truetype(path, size, index=idx)
            except Exception:
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
    return ImageFont.load_default()


def _wrap_cn(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """中文按字宽拆行。"""
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        w = font.getbbox(test)[2]
        if w > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


# 颜色（米白 + 暖橙 + 深炭）
BG = (252, 248, 242)
ACCENT = (255, 138, 76)
TEXT_DARK = (38, 38, 38)
TEXT_GREY = (110, 110, 110)
CARD_BG = (255, 255, 255)


def _auto_fit_title(title: str, max_width: int, target_lines: int = 3,
                     min_size: int = 80, max_size: int = 180) -> tuple:
    """二分搜索一个字号，让 title 折行后行数最接近 target_lines。
    返回 (font, lines)。"""
    best = None
    for size in range(max_size, min_size - 1, -4):
        f = _font(size, bold=True)
        lines = _wrap_cn(title, f, max_width)
        if len(lines) <= target_lines:
            best = (f, lines, size)
            break
    if best is None:
        f = _font(min_size, bold=True)
        best = (f, _wrap_cn(title, f, max_width), min_size)
    return best[0], best[1], best[2]


def render_lead_card(title: str, lead: str, total: int, out_path: Path) -> Path:
    """首张卡：标题占据主视觉，自适应字号铺满；引导/CTA 在下方。"""
    W, H = 1080, 1440
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    margin = 80

    # 顶部装饰条（更厚）
    d.rectangle([(0, 0), (W, 24)], fill=ACCENT)

    # 顶部品牌
    f_brand = _font(38, bold=True)
    d.text((margin, 70), f"@ {BRAND}", font=f_brand, fill=ACCENT)

    # 品牌下方分隔线（细）
    d.rectangle([(margin, 145), (margin + 80, 152)], fill=ACCENT)

    # ===== 计算底部 CTA / 引导 区域高度 =====
    f_cta = _font(48, bold=True)
    cta_text = f"共 {total} 张  滑动查看 →"
    cta_y = H - 180

    f_lead = _font(54, bold=True)
    lead_lines = _wrap_cn(lead, f_lead, W - margin * 2)
    lead_line_h = 78
    lead_block_h = len(lead_lines) * lead_line_h
    lead_y_start = cta_y - 80 - lead_block_h  # 引导块底部留 80 给 CTA

    # ===== 大标题区（核心）=====
    # 上界：220（品牌下方）；下界：lead_y_start - 80（与引导留间距）
    title_top = 220
    title_bottom = lead_y_start - 100
    title_avail_h = title_bottom - title_top

    title_max_w = W - margin * 2
    f_title, title_lines, title_size = _auto_fit_title(
        title, title_max_w, target_lines=3, min_size=100, max_size=220
    )
    line_height = int(title_size * 1.3)
    title_block_h = line_height * len(title_lines)
    # 顶部对齐（不居中）—— 让标题靠近品牌区，下面留出引导区
    title_y = title_top + 30
    for line in title_lines:
        d.text((margin, title_y), line, font=f_title, fill=TEXT_DARK)
        title_y += line_height

    # 标题与引导之间画大引号装饰，填中部空白
    quote_y_top = title_y + 40
    quote_y_bot = lead_y_start - 60
    if quote_y_bot - quote_y_top > 120:
        # 大色块装饰条
        d.rectangle([(margin, quote_y_top + 20), (margin + 240, quote_y_top + 32)], fill=ACCENT)
        # 装饰大引号
        f_quote = _font(180, bold=True)
        d.text((margin, quote_y_top + 50), "“", font=f_quote, fill=ACCENT)

    # ===== 引导文 =====
    y = lead_y_start
    for line in lead_lines:
        d.text((margin, y), line, font=f_lead, fill=TEXT_GREY)
        y += lead_line_h

    # ===== 底部 CTA =====
    d.text((margin, cta_y), cta_text, font=f_cta, fill=ACCENT)

    # 底部装饰条
    d.rectangle([(0, H - 24), (W, H)], fill=ACCENT)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_content_card(idx: int, total: int, headline: str, body: str, out_path: Path) -> Path:
    """内容卡：序号 + 小标题 + 正文。"""
    W, H = 1080, 1440
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 顶部序号 + 进度
    f_idx = _font(36, bold=True)
    d.text((80, 70), f"{idx:02d} / {total:02d}", font=f_idx, fill=ACCENT)

    # 圆形序号大字
    f_big = _font(180, bold=True)
    d.text((78, 130), str(idx).zfill(2), font=f_big, fill=ACCENT)

    # 小标题
    f_head = _font(60, bold=True)
    y = 380
    for line in _wrap_cn(headline, f_head, W - 160):
        d.text((80, y), line, font=f_head, fill=TEXT_DARK)
        y += 80

    # 横线
    y += 20
    d.rectangle([(80, y), (160, y + 5)], fill=ACCENT)
    y += 50

    # 正文
    f_body = _font(42)
    for line in _wrap_cn(body, f_body, W - 160):
        d.text((80, y), line, font=f_body, fill=TEXT_DARK)
        y += 64

    # 底部品牌水印
    f_foot = _font(28)
    d.text((80, H - 80), f"@ {BRAND}", font=f_foot, fill=TEXT_GREY)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_all(script: dict, out_dir: Path) -> list:
    """script 来自 rewrite.rewrite()，返回卡片路径列表（不含封面）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    cards = script["cards"]
    total = len(cards)

    p = out_dir / "card_00_lead.png"
    render_lead_card(script["title"], script["lead"], total, p)
    paths.append(p)

    for i, c in enumerate(cards, start=1):
        p = out_dir / f"card_{i:02d}.png"
        render_content_card(i, total, c["headline"], c["body"], p)
        paths.append(p)

    return paths


if __name__ == "__main__":
    import json
    import sys
    script = json.loads(open(sys.argv[1]).read()) if sys.argv[1:] else {
        "title": "外卖好评率60%→95%？3招亲测有效",
        "lead": "差评多愁坏老板？这套实操技巧帮你翻盘",
        "cards": [
            {"headline": "半小时内主动提问", "body": "订单送到别撒手！半小时内发消息问感受，先一步堵住差评苗头。"},
            {"headline": "有问题立刻补偿", "body": "客户说咸了？别解释，直接转5元红包，90%差评当场截胡。"},
            {"headline": "贴张手写感谢卡", "body": "外卖袋上粘张巴掌大的卡片，手写一句话，比打印的暖10倍。"},
        ],
    }
    out_dir = Path(__file__).parent.parent / "output" / "test_cards"
    paths = render_all(script, out_dir)
    for p in paths:
        print(p)
