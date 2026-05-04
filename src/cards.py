"""文案 → 小红书风卡片图（PIL 直绘，3:4，1080×1440 — 微信贴图官方推荐比例）。

风格：米白底 / 大字标题 / 圆角图块 / 柔和投影感 / 序号角标。
"""
import os
import random
import textwrap
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

load_dotenv()
BRAND = os.getenv("BRAND_NAME", "虾笔刀")

# 字体路径优先级（macOS → Linux 文泉中文字体 → fallback）
FONT_CANDIDATES = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",  # 华为云 / Linux
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
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

# 抽象装饰调色盘（柔和、不抢标题）
DECOR_PALETTE = [
    (255, 138, 76, 70),    # 暖橙（主色）
    (255, 200, 130, 60),   # 米黄
    (135, 195, 215, 55),   # 雾蓝
    (210, 180, 240, 50),   # 淡紫
    (255, 175, 165, 60),   # 珊瑚粉
    (170, 215, 180, 55),   # 薄荷绿
]


def _draw_abstract_decor(img: Image.Image, seed: int, top_y: int, bottom_y: int,
                          *, density: int = 3, blur: int = 14) -> Image.Image:
    """在 [top_y, bottom_y] 纵向区间内画半透明抽象装饰。
    随机性按 seed 决定，同一张卡每次渲染一致。返回新 RGB 图。
    """
    if bottom_y - top_y < 100:
        return img
    rng = random.Random(seed * 1337 + 7)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    W = img.width

    # 大色块：圆 / 椭圆 / 圆角矩形
    for _ in range(density):
        cx = rng.randint(60, W - 60)
        cy = rng.randint(top_y + 60, bottom_y - 60)
        r = rng.randint(150, 280)
        color = rng.choice(DECOR_PALETTE)
        shape = rng.choice(["circle", "ellipse", "rounded"])
        if shape == "circle":
            ld.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        elif shape == "ellipse":
            rx, ry = r, int(r * rng.uniform(0.55, 0.85))
            ld.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=color)
        else:
            rr = rng.randint(60, 110)
            half_w, half_h = r, int(r * rng.uniform(0.55, 0.8))
            ld.rounded_rectangle([cx - half_w, cy - half_h, cx + half_w, cy + half_h],
                                 radius=rr, fill=color)

    # 小圆点散布
    for _ in range(rng.randint(6, 11)):
        cx = rng.randint(50, W - 50)
        cy = rng.randint(top_y + 20, bottom_y - 20)
        r = rng.randint(6, 22)
        c = rng.choice(DECOR_PALETTE)
        ld.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(c[0], c[1], c[2], 150))

    # 一两根波浪/折线
    for _ in range(rng.randint(1, 2)):
        y0 = rng.randint(top_y + 80, bottom_y - 80)
        amp = rng.randint(25, 55)
        pts = []
        for x in range(40, W - 40, 24):
            phase = (x / 110.0) + rng.random() * 0.3
            import math
            pts.append((x, int(y0 + amp * math.sin(phase))))
        c = rng.choice(DECOR_PALETTE)
        ld.line(pts, fill=(c[0], c[1], c[2], 140), width=rng.randint(5, 9), joint="curve")

    # 高斯模糊柔化
    layer = layer.filter(ImageFilter.GaussianBlur(radius=blur))

    base = img.convert("RGBA")
    out = Image.alpha_composite(base, layer)
    return out.convert("RGB")


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
    """首张卡：关键信息全部集中在上半部分（60% 内），下半部分留白/装饰。
    研究小红书 + 贴图号设计规范得出：缩略图主要露出图片上部分。
    """
    W, H = 1080, 1440
    img = Image.new("RGB", (W, H), BG)
    # 抽象装饰打底（下半部分）
    img = _draw_abstract_decor(img, seed=hash(title) & 0xFFFF, top_y=720, bottom_y=H - 230, density=4)
    d = ImageDraw.Draw(img)
    margin = 90

    # ===== 上 60% 区（0 ~ 864）= 缩略图可见区 =====

    # 顶部分类小标
    f_tag = _font(34, bold=True)
    d.text((margin, 80), "今日干货", font=f_tag, fill=ACCENT)
    d.rectangle([(margin, 132), (margin + 70, 138)], fill=ACCENT)

    # 标题：紧凑版，留更多呼吸空间
    title_max_w = W - margin * 2
    f_title, title_lines, title_size = _auto_fit_title(
        title, title_max_w, target_lines=3, min_size=64, max_size=110
    )
    line_height = int(title_size * 1.35)
    title_y = 200
    for line in title_lines:
        d.text((margin, title_y), line, font=f_title, fill=TEXT_DARK)
        title_y += line_height

    # 标题底分隔
    title_y += 30
    d.rectangle([(margin, title_y), (margin + 140, title_y + 8)], fill=ACCENT)

    # 引导文紧跟标题
    f_lead = _font(36)
    lead_y = title_y + 50
    for line in _wrap_cn(lead, f_lead, title_max_w):
        d.text((margin, lead_y), line, font=f_lead, fill=TEXT_GREY)
        lead_y += 52

    # ===== 下 40% 区（864 ~ 1440）= 详情页才看到 =====

    # 底部品牌
    f_brand = _font(38, bold=True)
    d.text((margin, H - 200), f"@ {BRAND}", font=f_brand, fill=ACCENT)

    # CTA
    f_cta = _font(40, bold=True)
    d.text((margin, H - 130), f"共 {total} 张  滑动查看 →", font=f_cta, fill=TEXT_DARK)

    # 底部装饰条
    d.rectangle([(0, H - 16), (W, H)], fill=ACCENT)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_content_card(idx: int, total: int, headline: str, body: str, out_path: Path) -> Path:
    """内容卡：序号 + 小标题 + 正文。"""
    W, H = 1080, 1440
    img = Image.new("RGB", (W, H), BG)

    # 先估算正文结束位置，用于决定装饰区
    f_body_probe = _font(42)
    body_lines = _wrap_cn(body, f_body_probe, W - 160)
    f_head_probe = _font(60, bold=True)
    head_lines = _wrap_cn(headline, f_head_probe, W - 160)
    body_end_y = 380 + 80 * len(head_lines) + 70 + 64 * len(body_lines)
    decor_top = max(body_end_y + 60, 880)

    # 抽象装饰打底（正文下方空白区）
    img = _draw_abstract_decor(img, seed=idx * 41 + (hash(headline) & 0xFFF),
                                 top_y=decor_top, bottom_y=H - 130, density=3)
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
    for line in head_lines:
        d.text((80, y), line, font=f_head, fill=TEXT_DARK)
        y += 80

    # 横线
    y += 20
    d.rectangle([(80, y), (160, y + 5)], fill=ACCENT)
    y += 50

    # 正文
    f_body = _font(42)
    for line in body_lines:
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
