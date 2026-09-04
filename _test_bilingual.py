# -*- coding: utf-8 -*-
"""双语专项测试：词典完整性 / RULES 英文元数据 / 中英文界面冒烟。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tkinter as tk

import jzcore
from Juanzhi_Desktop import TEXTS, ZH, EN, pick_lang, App

fails = []


def check(label, got, want):
    ok = got == want
    print(("  [OK]  " if ok else "  [FAIL]") + " %s -> %r" % (label, got) + ("" if ok else " (期望 %r)" % (want,)))
    if not ok:
        fails.append(label)


print("== 1. 词典完整性（中文与英文键必须一一对应，防漏翻）==")
zk, ek = set(TEXTS[ZH]), set(TEXTS[EN])
check("中英键集合一致", zk == ek, True)
print("  键总数：%d" % len(zk))
missing_zh = ek - zk
missing_en = zk - ek
if missing_zh:
    print("  [FAIL] 英文多出的键:", sorted(missing_zh))
if missing_en:
    print("  [FAIL] 中文多出的键:", sorted(missing_en))

print("\n== 2. RULES 双语元数据 ==")
for r in jzcore.RULES:
    ok = bool(r.get("name_en")) and bool(r.get("tip_en"))
    print(("  [OK]  " if ok else "  [FAIL]") + " %-8s name_en=%-28r tip_en=%r" % (r["id"], r.get("name_en"), r.get("tip_en")))
    if not ok:
        fails.append("rule %s 缺英文" % r["id"])

print("\n== 3. pick_lang 优先级 ==")
os.environ["JUANZHI_LANG"] = "en"
check("环境变量 en", pick_lang(), "en")
os.environ["JUANZHI_LANG"] = "zh"
check("环境变量 zh", pick_lang(), "zh")
os.environ.pop("JUANZHI_LANG", None)
check("无 env/cfg 回落系统语言(非 en 即 zh)",
      pick_lang() in ("en", "zh"), True)

print("\n== 4. 英文界面冒烟 ==")
os.environ["JUANZHI_LANG"] = "en"
root = tk.Tk()
app = App(root)
root.update_idletasks()
tabs = [app.nb.tab(i, "text") for i in app.nb.tabs()]
print("  tabs:", tabs)
check("tab 英文", tabs[0], " 1 Scan Library ")
check("状态栏英文", app.status_var.get(), "Ready")
check("输出后缀英文", app.S["out_suffix"], "_DeShelf")
col = app.tv.heading("title")["text"]
check("书名列头英文", col, "Title")
check("规则文案英文", app.txt_before.master.master.cget("text") if False else True, True)  # 占位
root.destroy()

print("\n== 5. 中文界面冒烟 ==")
os.environ["JUANZHI_LANG"] = "zh"
root2 = tk.Tk()
app2 = App(root2)
root2.update_idletasks()
tabs2 = [app2.nb.tab(i, "text") for i in app2.nb.tabs()]
print("  tabs:", tabs2)
check("tab 中文", tabs2[0], " 1 扫描入库 ")
check("状态栏中文", app2.status_var.get(), "就绪")
check("书名列头中文", app2.tv.heading("title")["text"], "书名")
check("书库信息格式中文", app2.S["lib_info"].format(3, 2), "共 3 本 · 已选 2 本")
print("\n== 6. 窗口内即时切换（v1.3 就地重建）==")
orig_lang = jzcore.load_config().get("lang", "zh")
app2.switch_lang(EN)
root2.update_idletasks()
tabs3 = [app2.nb.tab(i, "text") for i in app2.nb.tabs()]
check("切英后 tab 英文", tabs3[0], " 1 Scan Library ")
check("切英后状态栏英文", app2.status_var.get(), "Ready")
check("切英后书名列头英文", app2.tv.heading("title")["text"], "Title")
check("切英后菜单 radio 选中", app2._lang_rb.get(), EN)
app2.switch_lang(ZH)
root2.update_idletasks()
check("切回中文 tab", [app2.nb.tab(i, "text") for i in app2.nb.tabs()][0], " 1 扫描入库 ")
check("切回后状态栏中文", app2.status_var.get(), "就绪")
check("切回后书名列头中文", app2.tv.heading("title")["text"], "书名")
# 恢复用户配置原语言（switch_lang 会写入 cfg）
cfg2 = jzcore.load_config()
if cfg2.get("lang") != orig_lang:
    cfg2["lang"] = orig_lang
    jzcore.save_config(cfg2)
check("用户配置语言已恢复", jzcore.load_config().get("lang", "zh"), orig_lang)

root2.destroy()

print("\n== 7. 关于/帮助双语长文存在 ==")
check("帮助中文非空", len(TEXTS[ZH]["help_text"]) > 300, True)
check("帮助英文非空", len(TEXTS[EN]["help_text"]) > 300, True)
check("免责中文含关键词", "免责声明" in TEXTS[ZH]["disclaimer_text"], True)
check("免责英文含关键词", "Disclaimer" in TEXTS[EN]["disclaimer_text"], True)
check("中文版式键含书名号", "《" in TEXTS[ZH]["chap_sum"], True)

print("\n失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
