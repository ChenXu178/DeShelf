# -*- coding: utf-8 -*-
"""端到端流程测试：真实调用 App.run_worker，覆盖 输出到新目录 / 原地覆盖 两种去向。"""
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tkinter as tk

import jzcore

os.startfile = lambda p: None  # 防止测试时弹出资源管理器

from Juanzhi_Desktop import App

BASE = os.path.join(HERE, "_flow")
if os.path.isdir(BASE):
    shutil.move(BASE, BASE + "_" + time.strftime("%H%M%S"))
SRC = os.path.join(BASE, "src")
IPSRC = os.path.join(BASE, "inplace")
OUT = os.path.join(BASE, "out_整理")
os.makedirs(SRC)
os.makedirs(IPSRC)

BODY = """斗破苍穹
作者：天蚕土豆
第1章 陨落的天才

　　萧炎缓缓睁开双眼，望着头顶那片熟悉的纹路。
请收藏本站，www.example.com，笔趣阁无弹窗，手机版阅读。
上一页 | 返回目录 | 加入书签

第2章 斗之力，三段！

　　“萧炎，斗之力，三段！”测验魔石碑之旁，一道中年男子的声音响起。
http://www.xxx.net TXT下载请到本站，本章未完。

第一百二十三章 山洞

　　这里是第一百二十三章的内容。

序章 开始

　　序章内容。
"""

OTHER = """《诡秘之主》
作者：爱潜水的乌贼
第1章 绯红

　　周明瑞睁开眼，发现自己在一张老旧的桌子上。
小说下载网，免费小说网，请记住本站地址。
第2章 占卜家

　　灰雾之上，古老的宫殿静静矗立。
"""


def w(d, name, text, enc):
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(text.encode(enc))
    return p


f1 = w(SRC, "斗破苍穹-天蚕土豆.txt", BODY, "gbk")
f2 = w(SRC, "斗破苍穹(副本).txt", BODY, "gbk")   # 同内容，测重名与去重
f3 = w(SRC, "诡秘之主.txt", OTHER, "utf-8-sig")
f4 = w(IPSRC, "凡人修仙传.txt", BODY, "gbk")

fails = []


def check(label, got, want):
    ok = got == want
    print(("  [OK]  " if ok else "  [FAIL]") + " %s -> %r" % (label, got) + ("" if ok else " (期望 %r)" % (want,)))
    if not ok:
        fails.append(label)


root = tk.Tk()
app = App(root)
root.update_idletasks()

print("== 准备：扫描源目录 ==")
books = []
for p in (f1, f2, f3):
    info = jzcore.scan_file(p)
    info["rel"] = os.path.basename(p)
    books.append(info)
    print("  %-24s 书名=%r 作者=%r 编码=%s 字数=%d"
          % (info["name"], info["title"], info["author"], info["enc"], info["chars"]))
check("副本与原书 md5 相同（会被判重复）", books[0]["md5"] == books[1]["md5"], True)

print("\n== 场景1：输出到新目录 + EPUB + 合并TXT ==")
app.books = books
app.out_var.set(OUT)
app.fmt_vars["epub"].set(True)
app.fmt_vars["merge"].set(True)
app.fmt_vars["split"].set(False)
app.mode_var.set("new")
app.run_worker(books, ["epub", "merge"], "new", OUT, app.active_rules(), None)
root.update()

produced = sorted(os.listdir(OUT))
print("  输出目录：", produced)
check("产物数量（3本 × txt+epub）", len(produced), 6)
check("重名文件自动加序号", any(n.startswith("斗破苍穹 (1)") for n in produced), True)

dp = os.path.join(OUT, "斗破苍穹.txt")
body_out = open(dp, encoding="utf-8").read()
check("清洗后无网址", "www.example.com" in body_out, False)
check("清洗后无站点宣传", "请收藏本站" in body_out, False)
check("清洗后无导航残留", "返回目录" in body_out, False)
check("正文保留", "萧炎缓缓睁开双眼" in body_out, True)

ep = os.path.join(OUT, "斗破苍穹.epub")
check("EPUB 已生成", os.path.exists(ep), True)
with zipfile.ZipFile(ep) as z:
    names = z.namelist()
    htmls = [n for n in names if n.endswith(".xhtml")]
    opf = z.read("OEBPS/content.opf").decode("utf-8")
    ncx = z.read("OEBPS/toc.ncx").decode("utf-8")
    c0002 = z.read("OEBPS/c0002.xhtml").decode("utf-8")
    all_text = "".join(z.read(n).decode("utf-8") for n in htmls)
check("EPUB 章节数 = 5（含序章）", len(htmls), 5)
check("EPUB 目录项数一致", ncx.count("<navPoint"), 5)
check("EPUB 元数据含作者", "天蚕土豆" in opf, True)
check("EPUB 内含正文", "萧炎" in all_text, True)
check("EPUB 章节标题正确", "陨落的天才" in c0002, True)
check("EPUB 无广告残留", "请收藏本站" in all_text, False)

print("\n== 场景2：原地覆盖（先备份 .bak）==")
ip_books = []
info = jzcore.scan_file(f4)
info["rel"] = os.path.basename(f4)
ip_books.append(info)
app.books = ip_books
app.run_worker(ip_books, [], "inplace", None, app.active_rules(), None)
root.update()

check(".bak 备份已生成", os.path.exists(f4 + ".bak"), True)
bak_bytes = open(f4 + ".bak", "rb").read()
now_bytes = open(f4, "rb").read()
check("备份内容是原始文件", "请收藏本站" in bak_bytes.decode("gbk", "replace"), True)
check("原文件已被清洗", "请收藏本站" in now_bytes.decode("utf-8", "replace"), False)
check("原文件保留正文", "萧炎" in now_bytes.decode("utf-8", "replace"), True)
check("原文件已转为 UTF-8", jzcore.detect_bytes(now_bytes), "utf-8")

print("\n== 场景3：仅导出（不落盘整理后 TXT）==")
OUT2 = os.path.join(BASE, "out_仅导出")
app.out_var.set(OUT2)
app.fmt_vars["merge"].set(False)
app.run_worker([books[2]], ["epub"], "none", OUT2, [], None)
root.update()
got = sorted(os.listdir(OUT2))
print("  输出目录：", got)
check("只产出一个 EPUB", got, ["诡秘之主.epub"])
check("未生成整理后 TXT", os.path.exists(os.path.join(OUT2, "诡秘之主.txt")), False)

print("\n失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
root.destroy()
sys.exit(1 if fails else 0)
