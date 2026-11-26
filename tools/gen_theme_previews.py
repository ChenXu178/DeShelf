# -*- coding: utf-8 -*-
"""把 styles 下的每套主题渲染成同名预览图（主题列表用）。

预览图就是与 CSS 同名的 .png：01-minimal.css -> 01-minimal.png。
渲染用的是 jzcore.theme_preview_html 给出的页面（与 write_epub 写进
xhtml 的 h2 / p / div.pic 结构一致）+ html2image 无头浏览器截图。

主程序打开「选择版面主题」时直接读这些 png，不必逐张起浏览器；所以
改完 CSS 重跑一次本脚本即可（--missing 只补缺图与过期图）。

尺寸默认 540x880（高分屏下也清楚）：主程序按主题窗口的大小等比缩放这些图，
尺寸给得大一些，窗口拉大时才不糊。

截图落地后统一重编码成 256 色调色板 PNG（见 shrink_png）：文字版面的截图
颜色本来就少，调色板 + 抖动能把 70 KB 压到 25 KB 上下，肉眼几乎无损；
这些图打包进 EXE 时 PNG 不会再被压缩，所以省下的字节数基本等于 EXE 小多少。

用法:
    python tools/gen_theme_previews.py             # 全部重渲
    python tools/gen_theme_previews.py --missing   # 只补缺图和过期图
    python tools/gen_theme_previews.py --recompress  # 只重压已有图（不起浏览器）
    python tools/gen_theme_previews.py 01-minimal 05-grid 10-ink
    python tools/gen_theme_previews.py --size 480x782
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jzcore                                   # noqa: E402


# 预览图是「文字 + 版面」的截图，颜色本来就不多：256 色调色板 + 抖动能把
# 70 KB 左右的 PNG 压到 25 KB 上下（PSNR ~48 dB，肉眼看不出），而 JPEG 同样
# 画质要 50 KB 且字形边缘会起彩边，WebP 也要 30 KB。
_PALETTE_COLORS = 256


def shrink_png(path, colors=_PALETTE_COLORS):
    """把一张预览图原地重编码成调色板 PNG，返回 (原字节数, 新字节数)。

    只在确实变小时才覆盖：万一同尺寸的图重编码后反而更大，保留原图不动。
    """
    from PIL import Image                     # 只有这一处需要 Pillow，延后导入

    old = os.path.getsize(path)
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")                # 截图不透明，丢掉 alpha 即可
    q = im.quantize(colors=colors, method=Image.MEDIANCUT,
                    dither=Image.FLOYDSTEINBERG)

    tmp = path + ".tmp"
    try:
        q.save(tmp, "PNG", optimize=True, compress_level=9)
        new = os.path.getsize(tmp)
        if new < old:
            os.replace(tmp, path)
        else:
            new = old
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return old, new


def parse_size(s):
    try:
        w, h = s.lower().replace("*", "x").split("x")
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError("尺寸要写成 宽x高，例如 224x306")


def pick(themes, wanted):
    """按「文件名 / 去掉扩展名」挑主题；写错名字要能看见。"""
    if not wanted:
        return themes, []
    keys = [w.lower() for w in wanted]
    got = [t for t in themes
           if t["id"].lower() in keys
           or os.path.splitext(t["id"])[0].lower() in keys]
    miss = [w for w, k in zip(wanted, keys)
            if not any(k in (t["id"].lower(),
                             os.path.splitext(t["id"])[0].lower())
                       for t in themes)]
    return got, miss


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="生成主题预览图（与 CSS 同名的 .png）")
    ap.add_argument("names", nargs="*", help="只生成这几套（文件名可省 .css）")
    ap.add_argument("--size", type=parse_size, default=jzcore.THEME_PREVIEW_SIZE,
                    help="预览图尺寸，默认 %dx%d"
                         % jzcore.THEME_PREVIEW_SIZE)
    ap.add_argument("--missing", action="store_true",
                    help="只补缺失的、以及比 CSS 旧的图")
    ap.add_argument("--recompress", action="store_true",
                    help="只把已有预览图重压成调色板 PNG，不启动浏览器")
    args = ap.parse_args(argv)

    themes = jzcore.list_themes()
    if not themes:
        print("没有找到主题：%s 下没有 .css 文件。" % jzcore.styles_dir())
        return 1

    targets, miss = pick(themes, args.names)
    for w in miss:
        print("[跳过] 没有这套主题：%s" % w)
    if not targets:
        print("没有要生成的主题。")
        return 1

    if args.recompress:
        total_old = total_new = done = 0
        for t in targets:
            png = t.get("preview") or jzcore.theme_thumb_path(t["path"])
            if not os.path.isfile(png):
                print("[跳过] 还没有预览图：%s" % os.path.basename(png))
                continue
            old, new = shrink_png(png)
            total_old += old
            total_new += new
            done += 1
            print("%-22s %6.1f KB -> %6.1f KB%s" % (
                os.path.basename(png), old / 1024, new / 1024,
                "" if new < old else "（未变小，保留原图）"))
        if not done:
            print("没有可重压的图。")
            return 1
        print("完成：%d 张，%.1f KB -> %.1f KB（省 %.1f KB）" % (
            done, total_old / 1024, total_new / 1024,
            (total_old - total_new) / 1024))
        return 0

    # --missing 时先筛一遍，剩下的才值得起浏览器
    todo = []
    fresh = 0
    for t in targets:
        png = t.get("preview") or jzcore.theme_thumb_path(t["path"])
        if args.missing and os.path.isfile(png) and not t.get("stale"):
            fresh += 1
            continue
        todo.append(t)
    if fresh:
        print("%d 套已有最新的预览图，跳过。" % fresh)
    if not todo:
        print("全部已是最新，无需生成。")
        return 0

    w, h = args.size
    print("主题目录：%s" % jzcore.styles_dir())
    print("预览尺寸：%dx%d，共 %d 套待生成" % (w, h, len(todo)))
    renderer = None
    fails = 0
    t_all = time.time()
    for i, t in enumerate(todo, 1):
        out = jzcore.theme_thumb_path(t["path"])
        t0 = time.time()
        try:
            renderer = renderer or jzcore.make_renderer(os.path.dirname(out))
            jzcore.render_theme_thumb(t, size=(w, h), renderer=renderer)
        except jzcore.NoBrowser:
            print("找不到可用的浏览器，没法渲染预览图。")
            print("请先安装 Chrome / Edge 等 Chromium 内核浏览器；"
                  "若装在别处，可设置环境变量")
            print("HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP=1 与 "
                  "HTML2IMAGE_CHROME_EXE=<浏览器完整路径>。")
            return 1
        except Exception as e:
            fails += 1
            print("[%d/%d] %s 失败：%s" % (i, len(todo), t["id"], e))
            continue
        old, new = shrink_png(out)
        print("[%d/%d] %s -> %s  (%.1fs, %.1f KB -> %.1f KB)" % (
            i, len(todo), t["id"], os.path.basename(out), time.time() - t0,
            old / 1024, new / 1024))

    print("完成：%d 张，用时 %.1fs%s" % (
        len(todo) - fails, time.time() - t_all,
        "，%d 张失败" % fails if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
