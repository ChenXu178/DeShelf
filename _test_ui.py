# -*- coding: utf-8 -*-
"""界面布局探测：逐个切页测量关键控件尺寸，防止出现 1×1 不可见控件。"""
import atexit
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tkinter as tk

import jzcore

# 界面探测也会走「试分章节」，那会顺手把分章规则写回索引：
# 测试不能改用户真实书库的 .deshelf_index.json，这里直接掐掉落盘
jzcore.save_index = lambda *a, **k: True

from Juanzhi_Desktop import App, safe_name, theme_title, _ellipsize, px

fails = []


def check(label, w, minw, minh):
    w.update_idletasks()
    ww, hh = w.winfo_width(), w.winfo_height()
    ok = ww >= minw and hh >= minh
    print(("  [OK]  " if ok else "  [FAIL]") + " %-16s %dx%d (要求 >=%dx%d)" % (label, ww, hh, minw, minh))
    if not ok:
        fails.append(label)


root = tk.Tk()
app = App(root)
root.geometry("1080x720")
root.update_idletasks()
root.update()
time.sleep(0.3)

# 界面探测只需要几本书：样本建在系统临时目录，跑完自动删（不再依赖 _test_core.py 的 _sample）
SAMPLE = tempfile.mkdtemp(prefix="deshelf_ui_")
atexit.register(shutil.rmtree, SAMPLE, ignore_errors=True)
_SAMPLES = {
    "界面样本一.txt": ("界面样本一\n作者：甲\n\n第1章 开始\n"
                  "　　正文第一段，用来测字数与清洗预览。\n"
                  "请收藏本站 www.example.com\n\n"
                  "第2章 继续\n　　正文第二段。\n"),
    "界面样本二.txt": ("《界面样本二》\n作者：乙\n\n第1章 开篇\n"
                  "　　正文甲。\n"
                  "上一页 | 返回目录 | 加入书签\n\n"
                  "第2章 承接\n　　正文乙。\n"),
}
for _name, _text in _SAMPLES.items():
    with open(os.path.join(SAMPLE, _name), "w", encoding="utf-8") as _f:
        _f.write(_text)

n = 0
for f in sorted(os.listdir(SAMPLE)):
    p = os.path.join(SAMPLE, f)
    if f.lower().endswith(".txt"):
        info = jzcore.scan_file(p)
        info["rel"] = f
        app.add_book(info)
        n += 1
root.update()
print("样本载入 %d 本" % n)
check("书库行数", app.tv, 1, 1)
print("  书库实际条目数：%d" % len(app.tv.get_children()))

print("\n== 页1 扫描入库 ==")
app.nb.select(app.tab_lib)
root.update()
check("书库 Treeview", app.tv, 500, 200)
check("停止按钮", app.btn_stop, 30, 12)

print("\n== 页2 批量清洗 ==")
app.nb.select(app.tab_clean)
root.update()
check("规则容器", app.tab_clean, 500, 200)
check("清洗前文本框", app.txt_before, 200, 80)
check("清洗后文本框", app.txt_after, 200, 80)
app.preview_clean()
root.update()
before = app.txt_before.get("1.0", "end-1c")
after = app.txt_after.get("1.0", "end-1c")
print("  预览对比：%r" % app.cmp_var.get())
if not before or not after:
    fails.append("清洗预览无内容")
    print("  [FAIL] 清洗预览无内容")
else:
    print("  [OK]   清洗预览有内容（前 %d 字 / 后 %d 字）" % (len(before), len(after)))

print("\n== 页3 智能分章 ==")
app.nb.select(app.tab_chap)
root.update()
check("章节 Treeview", app.tv_chap, 500, 100)
check("试分书下拉", app.cb_chap, 100, 18)
# 比“本机书库条目数”而不是“本次载入的样本数”：书库会从上次扫描的索引里恢复旧书
if n and len(list(app.cb_chap["values"])) != len(app.books):
    fails.append("试分书下拉未同步书库")
    print("  [FAIL] 试分书下拉未同步书库（书库 %d，下拉 %d）" % (len(app.books), len(list(app.cb_chap["values"]))))
else:
    print("  [OK]   试分书下拉已同步书库（%d 项）" % len(list(app.cb_chap["values"])))
app.preview_chap()
root.update()
cnt = len(app.tv_chap.get_children())
print("  分章结果：%s" % app.chap_var.get())
if cnt <= 0:
    fails.append("分章列表为空")
    print("  [FAIL] 分章列表为空")
else:
    print("  [OK]   分章列表 %d 行" % cnt)

print("\n== 页4 导出分发 ==")
app.nb.select(app.tab_out)
root.update()
check("开始处理按钮", app.btn_go, 60, 18)
check("进度条", app.pb, 200, 10)
check("文件名下拉框", app.cb_name, 80, 18)
check("版面主题按钮", app.btn_theme, 60, 18)
check("封面按钮", app.btn_cover, 60, 18)
pats = app.name_pats()
want_pats = ["", "author - book", "[author] book", app.S["name_pat_book_author"], None]
ok = pats == want_pats
print(("  [OK]  " if ok else "  [FAIL]") + " 文件名预设映射 %r" % (pats,))
if not ok:
    fails.append("文件名预设映射")
app.cfg["name_fmt"] = "author - book"
app._restore_name_opt()
ok = app.cb_name.current() == 1 and app.name_format() == "author - book"
print(("  [OK]  " if ok else "  [FAIL]") + " 文件名预设可恢复")
if not ok:
    fails.append("文件名预设恢复")
app.cfg["name_fmt"] = "《book》·author"
app._restore_name_opt()
ok = app.cb_name.current() == len(app.name_labels) - 1 and \
    app.name_format() == "《book》·author"
print(("  [OK]  " if ok else "  [FAIL]") + " 自定义格式可恢复")
if not ok:
    fails.append("自定义格式恢复")
app.cfg["name_fmt"] = ""
app._restore_name_opt()
ok = app.cb_name.current() == 0 and app.name_format() == ""
print(("  [OK]  " if ok else "  [FAIL]") + " 保持原样时为书名")
if not ok:
    fails.append("保持原样")
got = safe_name(jzcore.apply_name_format("book/author", "斗破/苍穹", "天蚕土豆"), maxlen=80)
ok = got == "斗破苍穹天蚕土豆"
print(("  [OK]  " if ok else "  [FAIL]") + " 文件名非法字符已清掉 -> %r" % got)
if not ok:
    fails.append("文件名非法字符")
# 自定义格式确认后要显示在下拉框里（最后一项换成用户填的模板）
app._custom_fmt = "《book》·author"
app._refresh_name_box()
app.cb_name.set(app.name_labels[-1])
ok = app.cb_name.get() == "《book》·author" and app.name_labels[-1] == "《book》·author"
print(("  [OK]  " if ok else "  [FAIL]") + " 自定义格式显示在下拉框 -> %r" % app.cb_name.get())
if not ok:
    fails.append("自定义格式显示")

print("\n== 主题按钮：过长文本用省略号截断 ==")


def ui(label, ok, detail=""):
    print(("  [OK]  " if ok else "  [FAIL]") + " %s%s" % (label, detail))
    if not ok:
        fails.append(label)


font = app._theme_btn_font()
DOT = font.measure("…")
utxt = "abcdef"
for src, limit, want, tag in (
        ("", 200, "", "空串"),
        (utxt, font.measure(utxt), utxt, "刚好放得下"),
        (utxt, font.measure("abc") + DOT, "abc…", "刚好放得下 abc + …"),
        (utxt, 0, "", "宽度为 0"),
        (utxt, max(1, DOT - 1), "", "连省略号都放不下")):
    got = _ellipsize(src, font, limit)
    ui("_ellipsize %s -> %r" % (tag, got), got == want, "" if got == want else "（期望 %r）" % want)

w0 = app.btn_theme.winfo_width()
avail0 = w0 - 2 * px(10) - px(4)
real_id = app.theme_id
fake_long = {"id": "__long__",
             "name": "一个特别特别长的主题名称 For Testing Long Theme Names"}
app.theme_by_id["__long__"] = fake_long
app.theme_id = "__long__"
app._refresh_theme_btn()
root.update()
shown = app.btn_theme.cget("text")
full = theme_title(fake_long, app.S, app.lang)
ui("长主题名被截断", shown != full and shown.endswith("…"), " -> %r" % shown)
ui("截断后仍放得下", font.measure(shown) <= avail0,
   "（%dpx / 可用 %dpx）" % (font.measure(shown), avail0))
ui("保持单行", "\n" not in shown)
ui("按钮宽度没被文字撑大", app.btn_theme.winfo_width() == w0,
   "（%d -> %d）" % (w0, app.btn_theme.winfo_width()))

app._refresh_theme_btn()                       # 重复设同一个主题：文字必须稳定
root.update()
ui("重复刷新不抖动", app.btn_theme.cget("text") == shown)

app.btn_theme.configure(width=6)               # 按钮变窄：截得更短，依旧带省略号
root.update()
app._fit_theme_btn()
root.update()
narrow = app.btn_theme.cget("text")
avail_n = app.btn_theme.winfo_width() - 2 * px(10) - px(4)
ui("窄按钮也带省略号", narrow.endswith("…"), " -> %r" % narrow)
ui("窄按钮不溢出", font.measure(narrow) <= avail_n,
   "（%dpx / 可用 %dpx）" % (font.measure(narrow), avail_n))
ui("窄按钮截得更短", len(narrow) <= len(shown))

app.btn_theme.configure(width=10)              # 复原：文字自动回长
root.update()
app._fit_theme_btn()
root.update()
ui("恢复宽度后文字回长", app.btn_theme.cget("text") == shown)

app.theme_by_id["__short__"] = {"id": "__short__", "name": "短名"}
app.theme_id = "__short__"
app._refresh_theme_btn()
root.update()
ui("短名字不截断", app.btn_theme.cget("text") == "短名",
   " -> %r" % app.btn_theme.cget("text"))
del app.theme_by_id["__long__"], app.theme_by_id["__short__"]
app.theme_id = real_id
app._refresh_theme_btn()
root.update()

print("\n== 工具函数 ==")
cases = [("第1章/楔子", "第1章楔子"), ("", "未命名"), ("  a/b:c*d?e  ", "abcde")]
for src, want in cases:
    got = safe_name(src)
    ok = got == want
    print(("  [OK]  " if ok else "  [FAIL]") + " safe_name(%r) -> %r" % (src, got))
    if not ok:
        fails.append("safe_name(%r)" % src)

print("\n失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
root.destroy()
sys.exit(1 if fails else 0)
