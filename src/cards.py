"""文案 → 贴图卡片图（PIL，3:4 1080×1440）。

模板：纸质米白底 + 衬线黑字（思源宋体）+ 标题下手绘波浪线 + 极简无彩色装饰。
"""
import math
import os
import random
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

load_dotenv()
BRAND = os.getenv("BRAND_NAME", "虾笔刀")

# === 字体（衬线优先：思源宋 > macOS Songti > fallback） ===
FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/source-han-serif/SourceHanSerifSC-Regular.otf",  # 华为云
    "/Users/yanhan/Library/Fonts/SourceHanSerifSC-Regular.otf",        # mac 自装
    "/System/Library/Fonts/Supplemental/Songti.ttc",                   # macOS 自带宋体
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/source-han-serif/SourceHanSerifSC-Bold.otf",
    "/Users/yanhan/Library/Fonts/SourceHanSerifSC-Bold.otf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    cands = FONT_BOLD_CANDIDATES if bold else FONT_REGULAR_CANDIDATES
    for path in cands:
        if not os.path.exists(path):
            continue
        # macOS Songti.ttc 是 collection，bold 用 index=1
        if path.endswith("Songti.ttc"):
            try:
                return ImageFont.truetype(path, size, index=1 if bold else 0)
            except Exception:
                pass
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


_LEADING_PUNCT = set("，。、；：？！）」』】》〉…—,.;:?!)]}")

import re as _re
_TOKEN_RE = _re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]+|.", _re.U)


def _tokenize_cn_en(s: str) -> list:
    """把字符串切成 token：英文单词/数字保持原子，中文一字一 token。"""
    return _TOKEN_RE.findall(s)


def _wrap_cn(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """中英混排折行，英文单词不切，含标点禁则。"""
    tokens = _tokenize_cn_en(text)
    lines, cur = [], ""
    for tok in tokens:
        test = cur + tok
        w = font.getbbox(test)[2]
        if w > max_width and cur:
            if tok in _LEADING_PUNCT:
                cur += tok
                lines.append(cur)
                cur = ""
            else:
                lines.append(cur)
                cur = tok
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


# === 颜色（极简：纸色 + 黑） ===
PAPER_BG = (243, 238, 226)     # 米黄纸
PAPER_HIGHLIGHT = (250, 246, 235)
PAPER_SHADOW = (228, 220, 200)
INK = (28, 26, 22)             # 近黑墨色
INK_LIGHT = (60, 56, 50)


def _make_paper_texture(W: int, H: int, seed: int = 0) -> Image.Image:
    """生成带颗粒+折痕的纸纹理底。"""
    rng = random.Random(seed)
    img = Image.new("RGB", (W, H), PAPER_BG)
    px = img.load()
    # 颗粒噪点
    for _ in range(int(W * H * 0.08)):
        x = rng.randint(0, W - 1)
        y = rng.randint(0, H - 1)
        r, g, b = px[x, y]
        delta = rng.randint(-12, 8)
        px[x, y] = (
            max(0, min(255, r + delta)),
            max(0, min(255, g + delta)),
            max(0, min(255, b + delta)),
        )
    # 大色斑（让背景不死板）
    blob = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    for _ in range(8):
        cx = rng.randint(0, W)
        cy = rng.randint(0, H)
        r = rng.randint(180, 380)
        c = rng.choice([PAPER_HIGHLIGHT, PAPER_SHADOW])
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*c, rng.randint(35, 70)))
    blob = blob.filter(ImageFilter.GaussianBlur(radius=80))
    img = Image.alpha_composite(img.convert("RGBA"), blob).convert("RGB")
    # 轻微整体模糊去噪点锐角
    img = img.filter(ImageFilter.GaussianBlur(radius=0.4))
    return img


def _draw_handdrawn_underline(draw: ImageDraw.ImageDraw, x1: int, y: int, x2: int,
                                seed: int = 0, weight: int = 7):
    """画一根手绘风波浪/抖动下划线。"""
    rng = random.Random(seed)
    pts = []
    step = 6
    amp = rng.uniform(2.5, 4.5)
    freq = rng.uniform(0.018, 0.028)
    phase = rng.uniform(0, math.pi * 2)
    for x in range(x1, x2 + 1, step):
        wobble = amp * math.sin((x - x1) * freq + phase) + rng.uniform(-1.4, 1.4)
        pts.append((x, int(y + wobble)))
    # 多次粗描，模拟笔触
    for offset in range(-1, 2):
        offset_pts = [(p[0], p[1] + offset) for p in pts]
        draw.line(offset_pts, fill=INK, width=weight, joint="curve")


def _draw_thin_rule(draw: ImageDraw.ImageDraw, x1: int, y: int, x2: int):
    """页眉/页脚那种细短横线。"""
    draw.line([(x1, y), (x2, y)], fill=INK, width=2)


import re as _re

_TOKEN_RE = _re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]+|.", _re.U)


def _tokenize_cn_en(s: str) -> list:
    """把字符串切成 token：英文单词/数字保持原子，中文一字一 token。"""
    return _TOKEN_RE.findall(s)


def _balanced_split_title(title: str, n_lines: int) -> list:
    """按语义/平均切分标题为 n_lines 行。
    优先按标点切（，。；：—— 等），无标点按 token 数平均切（英文单词不切）。
    """
    if n_lines <= 1 or len(title) <= 1:
        return [title]
    # 1. 找标点
    punct_idx = [i for i, c in enumerate(title) if c in "，,。.；;：:—!？?！" and 0 < i < len(title) - 1]
    if punct_idx and n_lines == 2:
        mid = len(title) / 2
        best = min(punct_idx, key=lambda i: abs(i - mid))
        return [title[:best + 1], title[best + 1:]]
    # 2. token 化（保护英文单词）后按 token 数平均切
    tokens = _tokenize_cn_en(title)
    n = len(tokens)
    if n <= 1:
        return [title]
    base = n // n_lines
    extra = n - base * n_lines
    parts = []
    pos = 0
    for k in range(n_lines):
        cnt = base + (1 if k >= n_lines - extra else 0)
        parts.append("".join(tokens[pos:pos + cnt]))
        pos += cnt
    return parts


def _auto_fit_title(title: str, max_width: int, target_lines: int = 2,
                    min_size: int = 90, max_size: int = 250) -> tuple:
    """优先 1 行，1 行字号过小（< 1 行可接受字号 = max_size*0.65）则退化到 2 行。
    再过小退到 target_lines 行。"""
    def fit_at(n_lines: int) -> tuple:
        lines = _balanced_split_title(title, n_lines)
        longest = max(lines, key=len)
        for s in range(max_size, min_size - 1, -2):
            f = _font(s, bold=True)
            if f.getbbox(longest)[2] <= max_width:
                return f, lines, s
        f = _font(min_size, bold=True)
        return f, lines, min_size

    # 1 行可接受字号
    accept_1 = max_size * 0.7
    f1, l1, s1 = fit_at(1)
    if s1 >= accept_1:
        return f1, l1, s1
    # 2 行（默认期望）
    f2, l2, s2 = fit_at(2)
    if s2 >= min_size + 30:
        return f2, l2, s2
    # 退到 target_lines（≥3）
    return fit_at(max(target_lines, 3))


# === 卡片渲染 ===

W, H = 1080, 1440
MARGIN_X = 110
HEADER_Y = 100      # 顶部页码区基线
FOOTER_Y = H - 130  # 底部品牌区基线


def _draw_header(draw, text: str):
    """左上：'01 / 06' 形式 + 下方细横线。"""
    f = _font(36, bold=False)
    draw.text((MARGIN_X, HEADER_Y), text, font=f, fill=INK)
    bbox = f.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    _draw_thin_rule(draw, MARGIN_X, HEADER_Y + text_h + 24, MARGIN_X + max(110, text_w + 20))


def _draw_footer(draw):
    """左下：品牌名 + 下方细横线。"""
    f = _font(34, bold=False)
    draw.text((MARGIN_X, FOOTER_Y), BRAND, font=f, fill=INK)
    bbox = f.getbbox(BRAND)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    _draw_thin_rule(draw, MARGIN_X, FOOTER_Y + text_h + 18, MARGIN_X + max(90, text_w + 20))


def _render_base(seed: int) -> tuple:
    img = _make_paper_texture(W, H, seed=seed)
    return img, ImageDraw.Draw(img)


NAVAL_IMG_PATH = Path(__file__).parent.parent / "assets" / "naval.jpg"


def _overlay_naval(img: Image.Image) -> Image.Image:
    """把纳瓦尔淡化叠在右上半区作为标志性背景元素。"""
    if not NAVAL_IMG_PATH.exists():
        return img
    try:
        portrait = Image.open(NAVAL_IMG_PATH).convert("RGBA")
    except Exception:
        return img
    # 目标尺寸：右半区，宽 ~720px（占画布 2/3 宽度），高度按原图比例
    target_w = 720
    src_w, src_h = portrait.size
    target_h = int(src_h * (target_w / src_w))
    portrait = portrait.resize((target_w, target_h), Image.LANCZOS)
    # 新源图本身已是水彩素描风，少量处理：略微去饱和 + 调亮 + 染暖色
    from PIL import ImageEnhance
    rgb = portrait.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(0.45)         # 降低饱和保留素描感
    rgb = ImageEnhance.Brightness(rgb).enhance(1.05)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.08)
    sepia = rgb.convert("RGBA")
    # 羽化 alpha：边缘软过渡，整体半透明融入纸面
    mask = Image.new("L", sepia.size, 0)
    md = ImageDraw.Draw(mask)
    md.rectangle([(40, 40), (sepia.size[0] - 40, sepia.size[1] - 40)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=30))
    sepia.putalpha(Image.eval(mask, lambda v: int(v * 0.82)))
    # 贴到右上：靠右边缘（轻微出血），顶部 80px
    px = W - target_w + 80
    py = 80
    base = img.convert("RGBA")
    base.alpha_composite(sepia, dest=(px, py))
    return base.convert("RGB")


def render_lead_card(title: str, lead: str, total: int, out_path: Path) -> Path:
    """首张卡：序号 01 / N + 纳瓦尔背景肖像 + 大标题 + 标题下手绘下划线 + 引导文 + 底部品牌。"""
    seed = (hash(title) & 0xFFFF) or 1
    img, d = _render_base(seed)

    # 叠纳瓦尔背景（在文字之前）
    img = _overlay_naval(img)
    d = ImageDraw.Draw(img)

    page_text = f"01 / {total + 1:02d}"  # +1 因为引导卡也算一张
    _draw_header(d, page_text)
    _draw_footer(d)

    # 标题——目标 2 行，字号铺满宽度
    title_max_w = W - MARGIN_X * 2
    f_title, title_lines, title_size = _auto_fit_title(
        title, title_max_w, target_lines=2, min_size=140, max_size=260
    )
    line_height = int(title_size * 1.18)
    title_top = 360
    last_line_top = title_top + (len(title_lines) - 1) * line_height
    last_line = title_lines[-1]
    last_line_w = f_title.getbbox(last_line)[2]
    for i, line in enumerate(title_lines):
        d.text((MARGIN_X, title_top + i * line_height), line, font=f_title, fill=INK)

    # 标题最后一行下方的手绘波浪线（用 font metrics 算准确位置）
    ascent, descent = f_title.getmetrics()
    underline_y = last_line_top + ascent + descent // 2 + 6
    _draw_handdrawn_underline(
        d, MARGIN_X - 6, underline_y, MARGIN_X + last_line_w + 24,
        seed=seed, weight=9,
    )
    title_y = title_top + len(title_lines) * line_height  # 给后面 lead 算位置

    # 引导文（用全宽避免标点压缩，但起点稍下方避开纳瓦尔）
    f_lead = _font(46, bold=False)
    lead_y = max(underline_y + 90, 990)
    for line in _wrap_cn(lead, f_lead, W - MARGIN_X * 2):
        d.text((MARGIN_X, lead_y), line, font=f_lead, fill=INK)
        lead_y += 70

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_content_card(idx: int, total: int, headline: str, body: str, out_path: Path) -> Path:
    """内容卡：页码 + 小标题(带下划波浪) + 正文 + 纳瓦尔背景。"""
    seed = (idx * 7919 + hash(headline)) & 0xFFFF or (idx + 1)
    img, d = _render_base(seed)

    # 叠纳瓦尔背景(跟首页保持视觉一致)
    img = _overlay_naval(img)
    d = ImageDraw.Draw(img)

    # idx 从 1 开始；含引导卡共 total+1 张
    total_with_lead = total + 1
    page_text = f"{idx + 1:02d} / {total_with_lead:02d}"
    _draw_header(d, page_text)
    _draw_footer(d)

    # 小标题
    f_head_max = 110 if len(headline) <= 7 else 92
    f_head_min = 76
    f_head, head_lines, head_size = _auto_fit_title(
        headline, W - MARGIN_X * 2, target_lines=2,
        min_size=f_head_min, max_size=f_head_max,
    )
    head_line_height = int(head_size * 1.18)
    head_top = 380
    last_head_top = head_top + (len(head_lines) - 1) * head_line_height
    last_head_w = f_head.getbbox(head_lines[-1])[2]
    for i, line in enumerate(head_lines):
        d.text((MARGIN_X, head_top + i * head_line_height), line, font=f_head, fill=INK)

    # 小标题下波浪
    h_ascent, h_descent = f_head.getmetrics()
    underline_y = last_head_top + h_ascent + h_descent // 2 + 6
    _draw_handdrawn_underline(
        d, MARGIN_X - 6, underline_y, MARGIN_X + last_head_w + 24,
        seed=seed, weight=8,
    )
    head_y = head_top + len(head_lines) * head_line_height

    # 正文（衬线，行距宽松）
    f_body = _font(46, bold=False)
    body_y = head_y + 100
    for line in _wrap_cn(body, f_body, W - MARGIN_X * 2):
        d.text((MARGIN_X, body_y), line, font=f_body, fill=INK)
        body_y += 70

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_all(script: dict, out_dir: Path) -> list:
    """script 来自 rewrite.rewrite()。返回卡片路径列表。
    顺序：首卡（标题）+ N 张内容卡。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cards_data = script["cards"]
    total = len(cards_data)
    paths = []

    p = out_dir / "card_00_lead.png"
    render_lead_card(script["title"], script["lead"], total, p)
    paths.append(p)

    for i, c in enumerate(cards_data, start=1):
        p = out_dir / f"card_{i:02d}.png"
        render_content_card(i, total, c["headline"], c["body"], p)
        paths.append(p)

    return paths


if __name__ == "__main__":
    import json
    import sys
    if sys.argv[1:]:
        script = json.loads(open(sys.argv[1]).read())
    else:
        script = {
            "title": "苹果的致命一步",
            "lead": "手握苹果股票的人注意了——苹果放弃AI，可能是这个时代最错的决定。但不放弃，它好像也没更好的办法。",
            "cards": [
                {"headline": "iPhone体验的真相", "body": "以前觉得iPhone体验好？其实是APP做得漂亮、交互流畅。安卓总被比下去，就是输在这生态细节上。"},
                {"headline": "AI让APP变多余", "body": "但AI时代来了，谁还需要APP？想要财务软件、主播数据统计？跟Claude Code说句话，5分钟就给你生成一个。"},
                {"headline": "以前找APP多折腾", "body": "以前得满网找APP，挨个试功能，自己让步、降低条件，才能勉强匹配需求。苹果体验好，就是靠这点赢了安卓。"},
                {"headline": "手机只剩三个零件", "body": "AI时代拼的是表达能力——你说清楚要啥，AI就给你做啥。手机可能退化到只剩屏幕、网络、麦克风，其他功能都多余。"},
                {"headline": "苹果生态要凉了", "body": "那苹果的生态还有啥价值？可能连三星、华为都不如。iPhone的优势被AI抹平，苹果时代真的要过去了？"},
            ],
        }
    out_dir = Path(__file__).parent.parent / "output" / "test_template_v2"
    import shutil; shutil.rmtree(out_dir, ignore_errors=True)
    paths = render_all(script, out_dir)
    for p in paths:
        print(p, p.stat().st_size, "B")
