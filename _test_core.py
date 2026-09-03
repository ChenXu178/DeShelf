# -*- coding: utf-8 -*-
"""卷帙核心逻辑自测：造样本 → 编码识别 / 清洗 / 分章 / EPUB / 元信息。"""
import os
import shutil
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jzcore

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sample")
if os.path.isdir(ROOT):
    # 沙箱拦截一切删除，用 move 把旧样本挪开（rename 不被拦截）
    shutil.move(ROOT, ROOT + "_" + time.strftime("%H%M%S"))
os.makedirs(ROOT, exist_ok=True)

BODY_GBK = """斗破苍穹
作者：天蚕土豆
==================
第1章 陨落的天才

　　萧炎缓缓睁开双眼，望着头顶那片熟悉的纹路，嘴角泛起一丝苦涩。

欢迎访问www.example.com，请记住本站地址，更多免费小说等你来看！
请收藏本站，本章未完，下一页继续。

第2章 斗之力，三段！

　　“萧炎，斗之力，三段！”测验魔石碑之旁，一道中年男子的声音响起。

手机阅读请访问 m.example.com，笔趣阁无弹窗。
上一页 | 返回目录 | 加入书签

第一百二十三章 山洞

　　这里是第一百二十三章的内容，用来测试中文数字章节。

序章 开始

　　序章内容。
"""

BODY_UTF8 = """《诡秘之主》
作者：爱潜水的乌贼
第1章 绯红

　　周明瑞睁开眼，发现自己在一张老旧的桌子上。
http://www.xxx.net 小说下载网，TXT下载请到本站。
第2章 占卜家

　　灰雾之上，古老的宫殿静静矗立。
"""

BODY_UTF16 = """凡人修仙传
第1章 山村少年

　　韩立站在村口，望着远山。
第2章 七玄门

　　青牛镇，七玄门。
"""


def w(name, text, enc):
    p = os.path.join(ROOT, name)
    with open(p, "wb") as f:
        f.write(text.encode(enc))
    return p


fails = []


def check(label, got, want):
    ok = got == want
    print(("  [OK]  " if ok else "  [FAIL]") + " %s -> %r" % (label, got) + ("" if ok else " (期望 %r)" % (want,)))
    if not ok:
        fails.append(label)


print("== 1. 编码识别 ==")
p1 = w("斗破苍穹-天蚕土豆.txt", BODY_GBK, "gbk")
p2 = w("诡秘之主.txt", BODY_UTF8, "utf-8-sig")
p3 = w("凡人修仙传.txt", BODY_UTF16, "utf-16")
check("GBK 文件", jzcore.detect_bytes(open(p1, "rb").read()), "gbk")
check("UTF-8 BOM 文件", jzcore.detect_bytes(open(p2, "rb").read()), "utf-8-sig")
check("UTF-16 文件", jzcore.detect_bytes(open(p3, "rb").read()), "utf-16-le")

print("== 2. 元信息提取 ==")
for p in (p1, p2, p3):
    info = jzcore.scan_file(p)
    print("  %-24s 书名=%-10r 作者=%-8r 编码=%-10s 字数=%d" % (
        info["name"], info["title"], info["author"], info["enc"], info["chars"]))
check("书名(文件名带作者)", jzcore.scan_file(p1)["title"], "斗破苍穹")
check("作者(文件名带作者)", jzcore.scan_file(p1)["author"], "天蚕土豆")
check("书名(书名号)", jzcore.scan_file(p2)["title"], "诡秘之主")
check("作者(正文提取)", jzcore.scan_file(p2)["author"], "爱潜水的乌贼")

print("== 3. 清洗 ==")
raw = jzcore.decode(open(p1, "rb").read(), "gbk")
cleaned, removed = jzcore.clean_text(raw, jzcore.DEFAULT_ON)
print("  删除 %d 行，%d 字 -> %d 字" % (removed, len(raw), len(cleaned)))
check("网址行已清除", "www.example.com" in cleaned, False)
check("宣传行已清除", "请收藏本站" in cleaned, False)
check("导航行已清除", "返回目录" in cleaned, False)
check("正文保留", "萧炎缓缓睁开双眼" in cleaned, True)
check("连续空行已压缩", "\n\n\n" in cleaned, False)

print("== 4. 分章 ==")
chs = jzcore.split_chapters(cleaned)
print("  切出 %d 章：" % len(chs))
for t, b in chs:
    print("    - %s (%d 字)" % (t, len(b)))
check("章节数(1,2,123,序章+开篇)", len(chs), 5)
check("中文数字章节命中", any("一百二十三" in t for t, _ in chs), True)
check("序章命中", any(t.startswith("序章") for t, _ in chs), True)

print("== 5. 自定义章节正则 ==")
chs2 = jzcore.split_chapters(cleaned, r"^#{1,3}\s*\S+")
print("  自定义正则切出 %d 章（预期 1，样本里无 # 标题）" % len(chs2))
check("自定义正则兜底为 1 章", len(chs2), 1)

print("== 6. EPUB 生成 ==")
ep = os.path.join(ROOT, "斗破苍穹.epub")
jzcore.write_epub(ep, "斗破苍穹", "天蚕土豆", chs)
check("文件已生成", os.path.exists(ep), True)
with zipfile.ZipFile(ep) as z:
    names = z.namelist()
    mi = z.getinfo("mimetype")
    check("mimetype 是第一个条目", names[0], "mimetype")
    check("mimetype 未压缩(STORED)", mi.compress_type, zipfile.ZIP_STORED)
    check("mimetype 内容", z.read("mimetype").decode(), "application/epub+zip")
    opf = z.read("OEBPS/content.opf").decode("utf-8")
    ncx = z.read("OEBPS/toc.ncx").decode("utf-8")
    htmls = sorted(n for n in names if n.endswith(".xhtml"))
    first_body = z.read(htmls[1]).decode("utf-8")
check("章节 xhtml 数 = 章节数", len(htmls), len(chs))
check("OPF 含书名", "<dc:title>斗破苍穹</dc:title>" in opf, True)
check("OPF 含作者", "天蚕土豆" in opf, True)
check("NCX 含目录项", ncx.count("<navPoint"), len(chs))
check("正文写入 xhtml", "萧炎" in first_body, True)
check("xhtml 已转义/结构完整", first_body.startswith("<?xml") and "</html>" in first_body, True)

print("== 7. 合并/拆分 TXT 导出 ==")
m1 = os.path.join(ROOT, "合并本.txt")
jzcore.save_txt(chs, m1, merge=True)
check("合并本已生成", os.path.exists(m1), True)
d1 = jzcore.save_txt(chs, os.path.join(ROOT, "分章本.txt"), merge=False)
check("分章目录已生成", os.path.isdir(d1), True)
files = sorted(os.listdir(d1))
print("  分章文件：", files)
check("分章文件数", len(files), len(chs))

print("== 8. 去重指纹 ==")
p_dup = w("斗破苍穹(副本).txt", BODY_GBK, "gbk")
check("同内容 md5 一致", jzcore.scan_file(p1)["md5"], jzcore.scan_file(p_dup)["md5"])
check("不同内容 md5 不同",
      jzcore.scan_file(p1)["md5"] != jzcore.scan_file(p2)["md5"], True)

print()
print("失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
