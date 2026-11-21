# -*- coding: utf-8 -*-
"""界面布局探测：逐个切页测量关键控件尺寸，防止出现 1×1 不可见控件。"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tkinter as tk

import jzcore
from Juanzhi_Desktop import App, safe_name

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

sample = os.path.join(HERE, "_sample")
n = 0
if os.path.isdir(sample):
    for f in sorted(os.listdir(sample)):
        p = os.path.join(sample, f)
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
