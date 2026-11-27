# -*- coding: utf-8 -*-
"""端到端流程测试：真实调用 App.run_worker，覆盖 输出到新目录 / 原地覆盖 两种去向。"""
import atexit
import os
import re
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# 下面的断言比对的是中文汇总文案：固定界面语言，免得用户把界面切成英文后误报失败
os.environ["JUANZHI_LANG"] = "zh"
import tkinter as tk

import jzcore

# 测试不能受本机配置影响：用户配置里的「上次目录」会自动载入书库索引，
# 而索引顶层的全局分章正则（chap_re）会盖掉默认规则，让分章结果对不上
jzcore.load_config = lambda: {}
jzcore.save_config = lambda cfg: None

os.startfile = lambda p: None  # 防止测试时弹出资源管理器

import Juanzhi_Desktop as _D
from Juanzhi_Desktop import App, TEXTS

# 导出章节树会弹提示框：测试里改成记录，别卡住
_errors = []


def _stub_showinfo(*a, **k):
    return None


_D.messagebox.showinfo = _stub_showinfo
_D.messagebox.showwarning = _stub_showinfo
_D.messagebox.showerror = lambda *a, **k: _errors.append(a)

BASE = os.path.join(HERE, "_flow")
# 旧版把上次目录挪成 _flow_HHMMSS（越攒越多）：直接删干净，跑完也整目录删掉
shutil.rmtree(BASE, ignore_errors=True)
for _name in os.listdir(HERE):
    if _name.startswith("_flow"):
        shutil.rmtree(os.path.join(HERE, _name), ignore_errors=True)
atexit.register(shutil.rmtree, BASE, ignore_errors=True)
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
app.sum_var.set(True)
app.run_worker(books, ["epub", "merge"], "new", OUT, app.active_rules(), None)
root.update()

produced = sorted(os.listdir(OUT))
print("  输出目录：", produced)
check("产物数量（3本 × txt+epub + 汇总）", len(produced), 7)
check("重名文件自动加序号", any(n.startswith("斗破苍穹 (1)") for n in produced), True)

# 清洗内容汇总：按书籍分类列出被清理的原文 + 清洗后的行号
sum_path = os.path.join(OUT, jzcore.SUMMARY_NAME)
check("已生成清洗内容汇总", os.path.exists(sum_path), True)
sum_txt = open(sum_path, encoding="utf-8").read()
check("汇总按书籍分类", "《斗破苍穹》" in sum_txt and "《诡秘之主》" in sum_txt, True)
check("汇总列出被清理的原文", "返回目录" in sum_txt, True)
nav_line = BODY.splitlines().index("上一页 | 返回目录 | 加入书签") + 1
check("汇总记录的是原文行号",
      bool(re.search(r"^\s*%d\s+翻页导航残留\s+整行删除\s+上一页" % nav_line,
                     sum_txt, re.M)), True)
check("汇总标注了启用的规则", "翻页导航残留" in sum_txt, True)
check("每条内容带清理原因（规则名）",
      bool(re.search(r"^\s*\d+\s+翻页导航残留\s+整行删除\s+上一页", sum_txt, re.M)), True)
check("汇总按原因统计条数",
      bool(re.search(r"原因统计：.*翻页导航残留 \d+ 条", sum_txt)), True)
check("汇总统计删除的空行数",
      bool(re.search(r"共 \d+ 本书 · 清理 \d+ 条 · 删除空行 \d+ 行", sum_txt)), True)

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
# 封面页（cover.xhtml）与 nav 导航文档（nav.xhtml）不算章节；按章节页单独计数
chaps = [n for n in htmls if not n.endswith(("cover.xhtml", "nav.xhtml"))]
check("EPUB 章节数 = 5（含序章）", len(chaps), 5)
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
check("只产出一个 EPUB 与汇总", got, [jzcore.SUMMARY_NAME, "诡秘之主.epub"])
check("未生成整理后 TXT", os.path.exists(os.path.join(OUT2, "诡秘之主.txt")), False)

print("\n== 场景4：章节树（校验栏 + 导出章节树）==")
# 造一本两级结构的书：第二卷缺第2章；番外/后记单独成组，不占正文序号
TREE_BOOK = """章节树样本
作者：测试
第一卷 起
正文。

第1章 甲
正文一。

第2章 乙
正文二。

第3章 丙
正文三。

第二卷 承
正文四。

第1章 丁
正文五。

第3章 戊
正文六。

番外一 甲
正文七。

后记一 乙
正文八。
"""
f5 = w(SRC, "章节树样本.txt", TREE_BOOK, "utf-8")
tree_info = jzcore.scan_file(f5)
tree_info["rel"] = os.path.basename(f5)
app.books = [tree_info]
app._fill_chap_pick()
app.chap_pick_text.set(tree_info["title"])
TREE_OUT = os.path.join(BASE, "out_章节树")
app.out_var.set(TREE_OUT)
app.preview_chap()
root.update()

rows = app.tv_chap.get_children()
vals = [app.tv_chap.item(i, "values") for i in rows]
print("  校验栏：")
for v in vals:
    print("    %-3s %-18s %-6s %s" % (v[0], v[1], v[2], v[3]))
check("章节数（含开篇、番外、后记）", len(rows), 10)
check("开篇不校验", vals[0][3], "正常")
check("卷行标出层级", vals[1][3], "第1级 正常")
check("普通章不标层级", vals[2][3], "正常")
check("缺章文案", vals[7][3], "第2章缺失/顺序错误")
check("缺章整行标红", app.tv_chap.item(rows[7], "tags"), ("bad",))
check("正常行不着色", len(app.tv_chap.item(rows[2], "tags")), 0)

app.export_chap_tree()
root.update()
tree_txt = os.path.join(TREE_OUT, os.path.splitext(tree_info["name"])[0] + "_章节树.txt")
check("导出文件已生成", os.path.exists(tree_txt), True)
body_tree = open(tree_txt, encoding="utf-8").read()
check("导出标题行", body_tree.splitlines()[0], "章节树导出")
check("导出含各级统计", "各级章节数：" in body_tree, True)
check("导出无序号章记 0", "[0] 开篇" in body_tree, True)
check("导出卷行顶格", "\n[1] 第一卷 起" in body_tree, True)
check("导出子章节缩进", "\n    [2] 第1章 甲" in body_tree, True)
check("导出带校验结果", "第2章缺失/顺序错误" in body_tree, True)

# 英文模式下：文件名后缀与内容都要变英文
app.lang = "en"
app.S = TEXTS["en"]
app.preview_chap()
root.update()
app.export_chap_tree()
root.update()
tree_en = os.path.join(TREE_OUT, os.path.splitext(tree_info["name"])[0] + "_chapter_tree.txt")
check("英文后缀文件名", os.path.exists(tree_en), True)
body_en = open(tree_en, encoding="utf-8").read()
check("英文导出标题", body_en.splitlines()[0], "Chapter tree export")
check("英文各级统计", "Chapters per level:" in body_en, True)
check("英文无序号标记", "[0] 开篇  ← no number | OK" in body_en, True)
check("英文校验文案", "missing or out of order" in body_en, True)
check("导出过程没有报错", _errors, [])
app.lang = "zh"
app.S = TEXTS["zh"]

print("\n== 场景5：批量试分 + 双击进入单本 ==")
app.books = [tree_info, books[2]]
app._fill_chap_pick()
app._chap_cols(True)
for i in app.tv_chap.get_children():
    app.tv_chap.delete(i)
app._chap_rows = {}
app.chap_worker(app.books, "", app.active_rules())      # 同步跑一遍后台逻辑
app.poll()
rows = app.tv_chap.get_children()
vals = [app.tv_chap.item(i, "values") for i in rows]
for v in vals:
    print("    %-3s %-12s %-5s %s" % (v[0], v[1], v[2], v[3]))
check("批量行数", len(rows), 2)
check("异常书显示汇总", vals[0][3], "共1个异常")
check("异常书整行标红", app.tv_chap.item(rows[0], "tags"), ("bad",))
check("正常书显示正常", vals[1][3], "正常")
check("正常书不着色", len(app.tv_chap.item(rows[1], "tags")), 0)
check("行与书的映射", len(app._chap_rows), 2)


class _Ev(object):
    def __init__(self, y):
        self.y = y


app.tv_chap.see(rows[0])
root.update()
box = app.tv_chap.bbox(rows[0])
app.on_chap_double(_Ev((box[1] if box else 1) + 2))
root.update()
check("双击后回到单本模式", app._chap_batch, False)
check("双击后下拉框切到该书", app.chap_pick_text.get(), tree_info["title"])
check("双击后列表变成章节明细", len(app.tv_chap.get_children()), 10)
check("双击后表头恢复章节标题", app.tv_chap.heading("title", "text"), TEXTS["zh"]["col_chap_title"])

print("\n失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
print("弹窗报错：%d" % len(_errors))
root.destroy()
sys.exit(1 if fails or _errors else 0)
