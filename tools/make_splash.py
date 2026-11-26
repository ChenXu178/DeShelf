# -*- coding: utf-8 -*-
"""卷帙书卷风海报 -> PNG 渲染器。

桌面版启动时的开屏海报已移除，这套深底金线的视觉仍用于 README / 分享图，
本脚本把同一套设计渲成高清 PNG。

用法:  python tools/make_splash.py    ->  assets/splash_poster.png (1120x680)
"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1120, 680            # 2x 渲染，作高清源图
CX = W // 2

BG   = "#202838"            # 深青黛底
GOLD = "#C9A24B"            # 细金
INK  = "#F1E7CE"            # 米白主字
GRAY = "#9AA5B6"            # 定位语
DIM  = "#7C8695"            # 底部版本信息
LINE = "#465061"            # 分隔线

FD = r"C:\Windows\Fonts"
def _first(*names):
    for n in names:
        p = os.path.join(FD, n)
        if os.path.exists(p):
            return p
    return None

KAI = _first("simkai.ttf")          # 楷体：主标题「卷帙」
YH  = _first("msyh.ttc", "msyhl.ttc", "simhei.ttf", "arial.ttf")  # 雅黑：西文/说明


def spaced(dr, cx, y, s, f, fill, track):
    """逐字绘制并拉宽字距，整体水平居中（对应 tk 的 ' '.join 字距模拟）。"""
    widths = [dr.textlength(ch, font=f) for ch in s]
    total = sum(widths) + track * (len(s) - 1)
    x = cx - total / 2
    for ch, w in zip(s, widths):
        dr.text((x, y), ch, font=f, fill=fill)
        x += w + track


def main():
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    # 细金外框（inset 22，宽 4）——对应原海报 11/2
    dr.rectangle([22, 22, W - 22, H - 22], outline=GOLD, width=4)

    # 四角回形短金线
    L = 44
    for x0, y0 in [(22, 22), (W - 22, 22), (22, H - 22), (W - 22, H - 22)]:
        sx = -1 if x0 > CX else 1
        sy = 1 if y0 < H // 2 else -1
        dr.line([x0, y0, x0 + sx * L, y0], fill=GOLD, width=6)
        dr.line([x0, y0, x0, y0 + sy * L], fill=GOLD, width=6)

    # 主标题「卷帙」楷体大字
    dr.text((CX, 130), "卷帙", font=ImageFont.truetype(KAI, 150), fill=INK, anchor="ma")

    # 英文名（拉宽字距，金色）
    spaced(dr, CX, 396, "D E S H E L F", ImageFont.truetype(YH, 40), GOLD, 6)

    # 一句定位
    spaced(dr, CX, 468, "扫描 · 清洗 · 分章 · 导出", ImageFont.truetype(YH, 30), GRAY, 4)

    # 分隔线
    dr.line([CX - 180, 548, CX + 180, 548], fill=LINE, width=3)

    # 底部版本信息
    dr.text((CX, 600), "卷帙 DeShelf · 本地整理 · 可选联网取图",
            font=ImageFont.truetype(YH, 26), fill=DIM, anchor="ma")

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "splash_poster.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, "PNG")
    print("saved:", out, "%dx%d" % img.size)


if __name__ == "__main__":
    main()
