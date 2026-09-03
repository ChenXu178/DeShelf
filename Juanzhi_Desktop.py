# -*- coding: utf-8 -*-
"""卷帙 DeShelf — 本地文本整理工具（桌面版）

扫描 → 清洗 → 分章 → 导出，全程在本机完成，不发起任何网络请求。
"""

import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import jzcore

APP_CN = jzcore.APP_CN
APP_EN = jzcore.APP_EN
APP_VER = jzcore.APP_VER
AUTHOR = "© 永远的兰兰 · Lanlan Eternal"
BG = "#F0F0F0"
FONT = ("Microsoft YaHei UI", 9)
FONT_S = ("Microsoft YaHei UI", 8)
MONO = ("Consolas", 9)

# ---- 开屏海报配色（书卷风深底 + 金线）----
SPLASH_W, SPLASH_H = 560, 340
SPLASH_BG = "#202838"
SPLASH_GOLD = "#C9A24B"
SPLASH_INK = "#F1E7CE"
SPLASH_GRAY = "#9AA5B6"
SPLASH_DIM = "#7C8695"
SPLASH_LINE = "#465061"

HELP_TEXT = """卷帙 DeShelf 使用说明

【1 扫描入库】
  选择一个目录后点「扫描」，程序会递归查找其中所有 .txt 文件，
  自动识别编码（GBK / UTF-8 / UTF-16）、统计字数、按内容指纹标出重复文件。
  原文件始终保持原地不动，卷帙只记录索引，不会把书搬进自己的库。

【2 批量清洗】
  勾选需要的规则，点「预览效果」可以对比清洗前后的文本。
  常用组合：含网址的行 + 站点宣传行 + 翻页导航残留 + 乱码行 + 压缩连续空行。
  「删除所有空行」与「压缩连续空行」建议二选一，前者把全文压成不分段的一片。

【3 智能分章】
  内置中文网文章节规则库，可识别「第1章 / 第一百二十三章 / 卷三 / 序章 / 番外」等写法。
  若内置规则不适合，可填写自定义正则（填写后将只使用自定义规则）。
  点「试分章节」可查看切分结果，章节数不对就调整正则再来。

【4 导出分发】
  清洗结果去向：
    输出到新目录 — 原文件一个字节都不动，最安全
    原地覆盖 — 先备份为 .bak 再写回，省空间但有风险
    仅导出 — 不落盘整理后的 TXT，只生成导出文件
  导出格式可多选：EPUB（兼容绝大多数阅读器）、合并 TXT、分章 TXT。

【小提示】
  · 双击书库中的行可切换勾选；右键可打开文件位置。
  · 扫描结果会缓存在目录下的 .deshelf_index.json，下次打开秒载入。
  · 导出到手机后，用支持本地导入的阅读器打开 EPUB 即可带目录阅读。
"""

DISCLAIMER = """免责声明

卷帙 DeShelf 是一款纯本地的文本整理工具：它不联网、不下载、不上传、
不提供也不存储任何书籍内容，仅对用户本机已有的文件做清洗、分章与格式转换。

用户应确保其处理的文件拥有合法来源并仅用于个人学习研究，
因使用本工具产生的任何版权或法律问题，由使用者自行承担。

本软件按「现状」提供，作者不对数据丢失或损坏承担责任。
请在执行「原地覆盖」前确认已做好备份。
"""


def safe_name(s, maxlen=60):
    s = (s or "未命名").strip()
    s = "".join(c for c in s if c not in '\\/:*?"<>|\r\n\t')
    s = s.strip(" .")
    return (s or "未命名")[:maxlen]


def _dpi(root):
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _center_win(win, w, h):
    """把窗口放到主屏居中偏上，开屏与主窗同位置切换不会跳动。"""
    try:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    except Exception:
        return
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2 - 12)
    win.geometry("%dx%d+%d+%d" % (w, h, x, y))


class App:
    def __init__(self, root):
        self.root = root
        self.books = []
        self.q = queue.Queue()
        self.busy = False
        self.cancel = False
        self.cfg = jzcore.load_config()
        self.dir_var = tk.StringVar(value=self.cfg.get("lastdir", ""))
        self.out_var = tk.StringVar()
        self.custom_re = tk.StringVar()
        self.mode_var = tk.StringVar(value="new")
        self.rule_vars = {r["id"]: tk.BooleanVar(value=r["id"] in jzcore.DEFAULT_ON)
                          for r in jzcore.RULES}
        self.fmt_vars = {"epub": tk.BooleanVar(value=True),
                         "merge": tk.BooleanVar(value=False),
                         "split": tk.BooleanVar(value=False)}
        self.status_var = tk.StringVar(value="就绪")
        self.prog_var = tk.DoubleVar(value=0)

        root.title("%s %s %s" % (APP_CN, APP_EN, APP_VER))
        root.geometry("1080x720")
        root.minsize(900, 620)
        root.configure(bg=BG)
        self._style()
        self._menu()
        self._top(root)
        self._tabs(root)
        self._log(root)
        self._status(root)
        self.poll()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        d = self.dir_var.get()
        if d and os.path.isdir(d):
            self.load_index(d)

    # ------------------------------------------------------------ 界面
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, font=FONT)
        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG)
        st.configure("TLabelframe", background=BG)
        st.configure("TLabelframe.Label", background=BG)
        st.configure("TCheckbutton", background=BG)
        st.configure("TRadiobutton", background=BG)
        st.configure("TNotebook", background=BG)
        st.configure("Treeview", rowheight=23)
        st.configure("Accent.TButton", background="#4A7EBB", foreground="white")
        st.configure("Go.TButton", background="#2E7D32", foreground="white")

    def _menu(self):
        m = tk.Menu(self.root)
        self.root.configure(menu=m)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="选择目录…", command=self.pick_dir)
        fm.add_command(label="重新扫描", command=self.do_scan)
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)
        sm = tk.Menu(m, tearoff=0)
        sm.add_command(label="全选", command=lambda: self.set_all(True))
        sm.add_command(label="全不选", command=lambda: self.set_all(False))
        sm.add_command(label="反选", command=self.invert_sel)
        sm.add_separator()
        sm.add_command(label="只选重复文件", command=self.sel_dup)
        sm.add_command(label="导出书单 CSV", command=self.export_list)
        m.add_cascade(label="书库", menu=sm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="使用说明", command=lambda: self.show_text("使用说明", HELP_TEXT))
        hm.add_command(label="免责声明", command=lambda: self.show_text("免责声明", DISCLAIMER))
        hm.add_separator()
        hm.add_command(label="关于", command=self.show_about)
        m.add_cascade(label="帮助", menu=hm)

    def _top(self, root):
        f = ttk.Frame(root, padding=(8, 6))
        f.pack(fill="x")
        ttk.Label(f, text="书库目录：").pack(side="left")
        e = ttk.Entry(f, textvariable=self.dir_var)
        e.pack(side="left", fill="x", expand=True, padx=4)
        e.bind("<Return>", lambda _e: self.do_scan())
        ttk.Button(f, text="浏览…", command=self.pick_dir).pack(side="left")
        ttk.Button(f, text="扫描", style="Accent.TButton", command=self.do_scan).pack(side="left", padx=(4, 0))
        ttk.Button(f, text="重新扫描（忽略缓存）", command=lambda: self.do_scan(fresh=True)).pack(side="left", padx=4)
        self.btn_stop = ttk.Button(f, text="停止", command=self.do_stop, state="disabled")
        self.btn_stop.pack(side="left")

    def _tabs(self, root):
        nb = ttk.Notebook(root)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.tab_lib = ttk.Frame(nb)
        self.tab_clean = ttk.Frame(nb)
        self.tab_chap = ttk.Frame(nb)
        self.tab_out = ttk.Frame(nb)
        nb.add(self.tab_lib, text=" 1 扫描入库 ")
        nb.add(self.tab_clean, text=" 2 批量清洗 ")
        nb.add(self.tab_chap, text=" 3 智能分章 ")
        nb.add(self.tab_out, text=" 4 导出分发 ")
        self._build_lib()
        self._build_clean()
        self._build_chap()
        self._build_out()

    def _build_lib(self):
        f = self.tab_lib
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(6, 4))
        for txt, cmd in (("全选", lambda: self.set_all(True)),
                         ("全不选", lambda: self.set_all(False)),
                         ("反选", self.invert_sel),
                         ("只选重复", self.sel_dup)):
            ttk.Button(bar, text=txt, command=cmd).pack(side="left", padx=2)
        ttk.Label(bar, text="  双击行可切换勾选，右键可打开文件位置",
                  foreground="#666666").pack(side="left")
        self.info_var = tk.StringVar(value="共 0 本")
        ttk.Label(bar, textvariable=self.info_var).pack(side="right")

        cols = ("sel", "title", "author", "chars", "enc", "chap", "size", "rel")
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True)
        self.tv = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        heads = {"sel": "✓", "title": "书名", "author": "作者", "chars": "字数",
                 "enc": "编码", "chap": "章节", "size": "大小", "rel": "相对路径"}
        widths = {"sel": 32, "title": 190, "author": 100, "chars": 80, "enc": 76,
                  "chap": 56, "size": 78, "rel": 320}
        for c in cols:
            self.tv.heading(c, text=heads[c])
            self.tv.column(c, width=widths[c], anchor="w" if c in ("title", "author", "rel") else "center")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(side="left", fill="both", expand=True)
        self.tv.tag_configure("dup", foreground="#C05621")
        self.tv.bind("<Double-1>", self.toggle_row)
        self.tv.bind("<Button-3>", self.popup)

    def _build_clean(self):
        f = self.tab_clean
        left = ttk.LabelFrame(f, text="清洗规则", width=280)
        left.pack(side="left", fill="y", padx=(6, 4), pady=6)
        left.pack_propagate(False)
        for r in jzcore.RULES:
            cb = ttk.Checkbutton(left, text=r["name"], variable=self.rule_vars[r["id"]])
            cb.pack(anchor="w", padx=8, pady=2)
            ttk.Label(left, text="    " + r["tip"], foreground="#777777",
                      font=FONT_S, wraplength=250).pack(anchor="w", padx=8)
        bf = ttk.Frame(left)
        bf.pack(anchor="w", padx=8, pady=8)
        ttk.Button(bf, text="全选规则", command=lambda: self.set_rules(True)).pack(side="left")
        ttk.Button(bf, text="恢复默认", command=lambda: self.set_rules(None)).pack(side="left", padx=4)

        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=4, pady=6)
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        ttk.Button(bar, text="预览效果", style="Accent.TButton",
                   command=self.preview_clean).pack(side="left")
        ttk.Label(bar, text="  对第一本勾选的书试跑，左边原文、右边清洗后",
                  foreground="#666666").pack(side="left")
        self.cmp_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.cmp_var, foreground="#2E7D32").pack(side="right")
        box = ttk.Frame(right)
        box.pack(fill="both", expand=True, pady=4)
        self.txt_before = self._mk_text(box, "清洗前")
        self.txt_after = self._mk_text(box, "清洗后")

    def _mk_text(self, parent, title):
        f = ttk.LabelFrame(parent, text=title)
        f.pack(side="left", fill="both", expand=True, padx=2)
        # width 必须给小值：pack 按顺序满足请求宽度，80 字符会吃满空间导致两栏不等分
        t = tk.Text(f, wrap="none", font=MONO, width=30, height=10, bg="#FFFFFF",
                    relief="solid", borderwidth=1)
        sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        return t

    def _build_chap(self):
        f = self.tab_chap
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(top, text="章节正则（留空使用内置中文规则库）：").pack(side="left")
        e = ttk.Entry(top, textvariable=self.custom_re)
        e.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(top, text="试分章节", style="Accent.TButton",
                   command=self.preview_chap).pack(side="left")
        ttk.Label(f, text="内置可识别：第1章 / 第一百二十三章 / 卷三 / Chapter 5 / 序章 / 楔子 / 番外 / 后记；"
                          "填写自定义正则后将只使用自定义规则。",
                  foreground="#666666", font=FONT_S).pack(anchor="w", padx=8)
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True, padx=8, pady=4)
        self.tv_chap = ttk.Treeview(wrap, columns=("no", "title", "chars"),
                                    show="headings", height=8)
        for c, w, t in (("no", 60, "#"), ("title", 520, "章节标题"), ("chars", 100, "字数")):
            self.tv_chap.heading(c, text=t)
            self.tv_chap.column(c, width=w, anchor="w" if c == "title" else "center")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tv_chap.yview)
        self.tv_chap.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv_chap.pack(side="left", fill="both", expand=True)
        self.chap_var = tk.StringVar(value="点「试分章节」查看结果")
        ttk.Label(f, textvariable=self.chap_var).pack(anchor="w", padx=8, pady=(0, 6))

    def _build_out(self):
        f = self.tab_out
        g1 = ttk.LabelFrame(f, text="清洗结果的去向")
        g1.pack(fill="x", padx=8, pady=(10, 6))
        for v, t in (("new", "输出到新目录（原文件不动，推荐）"),
                     ("inplace", "原地覆盖（先备份为 .bak）"),
                     ("none", "仅导出，不保存整理后的 TXT")):
            ttk.Radiobutton(g1, text=t, value=v, variable=self.mode_var,
                            command=self.sync_out).pack(anchor="w", padx=10, pady=2)

        g2 = ttk.LabelFrame(f, text="导出格式（可多选）")
        g2.pack(fill="x", padx=8, pady=6)
        row = ttk.Frame(g2)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Checkbutton(row, text="EPUB（带目录，推荐）",
                        variable=self.fmt_vars["epub"]).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(row, text="合并 TXT（整本一个文件）",
                        variable=self.fmt_vars["merge"]).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(row, text="分章 TXT（一章一个文件）",
                        variable=self.fmt_vars["split"]).pack(side="left")

        g3 = ttk.LabelFrame(f, text="输出目录")
        g3.pack(fill="x", padx=8, pady=6)
        r = ttk.Frame(g3)
        r.pack(fill="x", padx=10, pady=6)
        ttk.Entry(r, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(r, text="浏览…", command=self.pick_out).pack(side="left")

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=8, pady=10)
        self.btn_go = ttk.Button(bar, text="开始处理", style="Go.TButton", command=self.start_run)
        self.btn_go.pack(side="left")
        self.pb = ttk.Progressbar(bar, variable=self.prog_var, maximum=100)
        self.pb.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Label(f, text="处理期间请勿关闭窗口。大批量任务建议先选少量书试跑。",
                  foreground="#777777", font=FONT_S).pack(anchor="w", padx=8)

    def _log(self, root):
        f = ttk.LabelFrame(root, text="运行日志", height=130)
        f.pack(fill="x", padx=8, pady=(0, 4))
        f.pack_propagate(False)
        self.logbox = tk.Text(f, height=7, font=FONT_S, bg="#FFFFFF",
                              relief="solid", borderwidth=1)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(fill="both", expand=True)

    def _status(self, root):
        ttk.Label(root, textvariable=self.status_var, anchor="w",
                  relief="sunken", padding=(6, 2)).pack(fill="x", padx=8, pady=(0, 6))

    # ------------------------------------------------------------ 基础操作
    def log(self, msg):
        self.q.put(("log", msg))

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.logbox.insert("end", payload + "\n")
                    self.logbox.see("end")
                elif kind == "book":
                    self.add_book(payload)
                elif kind == "prog":
                    cur, total, label = payload
                    self.prog_var.set(0 if not total else cur * 100.0 / total)
                    if label:
                        self.status_var.set(label)
                elif kind == "done":
                    self.on_done(payload)
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def set_busy(self, busy):
        self.busy = busy
        self.btn_stop.configure(state="normal" if busy else "disabled")
        self.btn_go.configure(state="disabled" if busy else "normal")

    def do_stop(self):
        self.cancel = True
        self.status_var.set("正在停止…")

    def on_close(self):
        cfg = self.cfg
        cfg["lastdir"] = self.dir_var.get()
        jzcore.save_config(cfg)
        self.root.destroy()

    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or None)
        if d:
            self.dir_var.set(d)
            self.out_var.set(d.rstrip("\\/") + "_卷帙整理")
            self.do_scan()

    def pick_out(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or self.dir_var.get() or None)
        if d:
            self.out_var.set(d)

    def sync_out(self):
        if not self.out_var.get() and self.dir_var.get():
            self.out_var.set(self.dir_var.get().rstrip("\\/") + "_卷帙整理")

    def show_text(self, title, body):
        w = tk.Toplevel(self.root)
        w.title(title)
        w.geometry("640x520")
        t = tk.Text(w, wrap="word", font=FONT, padx=10, pady=10)
        t.insert("1.0", body)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)
        ttk.Button(w, text="关闭", command=w.destroy).pack(pady=6)

    def show_about(self):
        messagebox.showinfo(
            "关于 %s %s" % (APP_CN, APP_EN),
            "%s %s %s\n\n本地文本整理工具：扫描 · 清洗 · 分章 · 导出\n"
            "纯离线运行，不联网、不下载、不上传任何内容。\n\n%s"
            % (APP_CN, APP_EN, APP_VER, AUTHOR))

    # ------------------------------------------------------------ 书库
    def add_book(self, info):
        idx = len(self.books)
        self.books.append(info)
        rel = info.get("rel", os.path.basename(info["path"]))
        self.tv.insert("", "end", iid=str(idx), values=(
            "✓" if info["sel"] else "", info["title"], info["author"],
            "{:,}".format(info["chars"]), info["enc"], "-",
            jzcore.human_size(info["size"]), rel))
        self.refresh_info()

    def refresh_info(self):
        n = len(self.books)
        m = sum(1 for b in self.books if b["sel"])
        d = self.dup_count()
        self.info_var.set("共 %d 本 · 已选 %d 本%s" % (n, m, " · 重复 %d 本" % d if d else ""))

    def dup_count(self):
        c = Counter(b["md5"] for b in self.books)
        return sum(v for v in c.values() if v > 1)

    def toggle_row(self, event):
        row = self.tv.identify_row(event.y)
        if not row:
            return
        b = self.books[int(row)]
        b["sel"] = not b["sel"]
        self.tv.set(row, "sel", "✓" if b["sel"] else "")
        self.refresh_info()

    def set_all(self, val):
        for i, b in enumerate(self.books):
            b["sel"] = val
            self.tv.set(str(i), "sel", "✓" if val else "")
        self.refresh_info()

    def invert_sel(self):
        for i, b in enumerate(self.books):
            b["sel"] = not b["sel"]
            self.tv.set(str(i), "sel", "✓" if b["sel"] else "")
        self.refresh_info()

    def sel_dup(self):
        c = Counter(b["md5"] for b in self.books)
        dups = {k for k, v in c.items() if v > 1}
        if not dups:
            messagebox.showinfo("没有重复", "当前书库中未发现内容完全相同的文件。")
            return
        for i, b in enumerate(self.books):
            b["sel"] = b["md5"] in dups
            self.tv.set(str(i), "sel", "✓" if b["sel"] else "")
        self.refresh_info()
        self.log("已选中 %d 个重复文件，可在书库中取消保留项的勾选后清理。"
                 % sum(1 for b in self.books if b["sel"]))

    def popup(self, event):
        row = self.tv.identify_row(event.y)
        if not row:
            return
        self.tv.selection_set(row)
        b = self.books[int(row)]
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="打开文件位置",
                      command=lambda: self.open_folder(b["path"]))
        m.add_command(label="用记事本打开",
                      command=lambda: self.open_file(b["path"]))
        m.add_separator()
        m.add_command(label="复制完整路径",
                      command=lambda: self.copy_path(b["path"]))
        m.tk_popup(event.x_root, event.y_root)

    def open_folder(self, path):
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except OSError:
            self.log("无法打开资源管理器：%s" % path)

    def open_file(self, path):
        try:
            os.startfile(path)
        except OSError:
            self.log("无法打开文件：%s" % path)

    def copy_path(self, path):
        self.root.clipboard_clear()
        self.root.clipboard_append(path)

    def export_list(self):
        if not self.books:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV 文件", "*.csv")],
                                         initialfile="书单.csv")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write("书名,作者,字数,编码,大小,相对路径\n")
                for b in self.books:
                    f.write('"%s","%s",%d,%s,%d,"%s"\n' % (
                        b["title"].replace('"', '""'), b["author"].replace('"', '""'),
                        b["chars"], b["enc"], b["size"], b.get("rel", "").replace('"', '""')))
            self.log("书单已导出：%s" % p)
        except OSError as e:
            messagebox.showerror("导出失败", str(e))

    # ------------------------------------------------------------ 扫描
    def do_scan(self, fresh=False):
        d = self.dir_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showwarning("目录无效", "请先选择一个存在的目录。")
            return
        if self.busy:
            return
        if not fresh and self.load_index(d):
            return
        self.clear_books()
        self.set_busy(True)
        self.cancel = False
        self.log("开始扫描：%s" % d)
        threading.Thread(target=self.scan_worker, args=(d,), daemon=True).start()

    def clear_books(self):
        self.books = []
        for i in self.tv.get_children():
            self.tv.delete(i)
        self.refresh_info()

    def scan_worker(self, root):
        files = []
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.lower().endswith((".txt", ".text")):
                    files.append(os.path.join(dp, f))
        files.sort()
        total = len(files)
        self.q.put(("log", "发现 %d 个文本文件，开始读取…" % total))
        got = 0
        for i, p in enumerate(files, 1):
            if self.cancel:
                break
            try:
                info = jzcore.scan_file(p)
                info["rel"] = os.path.relpath(p, root)
                self.q.put(("book", info))
                got += 1
            except Exception as e:
                self.q.put(("log", "  跳过 %s（%s）" % (os.path.basename(p), e)))
            if i % 5 == 0 or i == total:
                self.q.put(("prog", (i, total, "扫描中 %d/%d" % (i, total))))
        self.q.put(("done", ("scan", root, got, total)))

    def load_index(self, root):
        data = jzcore.load_index(root)
        books = data.get("books") or []
        if not books:
            return False
        self.clear_books()
        missing = 0
        for b in books:
            p = os.path.join(root, b.get("rel", ""))
            if not os.path.exists(p):
                missing += 1
                continue
            if int(os.path.getmtime(p)) != int(b.get("mtime", 0)) or os.path.getsize(p) != b.get("size"):
                b["stale"] = True
            b["path"] = p
            b.setdefault("sel", True)
            self.add_book(b)
        self.mark_dup()
        self.out_var.set(root.rstrip("\\/") + "_卷帙整理")
        self.log("已从索引载入 %d 本（%s）%s" % (
            len(self.books), time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("scanned", 0))),
            "，%d 本已失效建议重新扫描" % missing if missing else ""))
        if missing:
            self.log("提示：索引中有 %d 个文件已不存在，建议点「重新扫描」。" % missing)
        return True

    def mark_dup(self):
        c = Counter(b["md5"] for b in self.books)
        for i, b in enumerate(self.books):
            if c[b["md5"]] > 1:
                self.tv.item(str(i), tags=("dup",))

    def on_done(self, payload):
        kind = payload[0]
        self.set_busy(False)
        self.prog_var.set(0)
        if kind == "scan":
            _s, root, got, total = payload
            self.mark_dup()
            self.status_var.set("扫描完成：%d / %d 本" % (got, total))
            self.log("扫描完成，共 %d 本。%s" % (got, "已停止" if self.cancel else ""))
            jzcore.save_index(root, {
                "root": root, "scanned": time.time(),
                "books": [{k: v for k, v in b.items() if k != "path"} for b in self.books]})
        elif kind == "run":
            _s, ok, fail, outdir = payload
            self.status_var.set("处理完成：成功 %d 本，失败 %d 本" % (ok, fail))
            self.log("处理完成：成功 %d 本，失败 %d 本，输出目录 %s" % (ok, fail, outdir))
            if outdir and os.path.isdir(outdir) and not self.cancel:
                try:
                    os.startfile(outdir)
                except OSError:
                    pass

    # ------------------------------------------------------------ 预览
    def first_selected(self):
        for b in self.books:
            if b["sel"]:
                return b
        return None

    def active_rules(self):
        return [i for i, v in self.rule_vars.items() if v.get()]

    def set_rules(self, val):
        for r in jzcore.RULES:
            v = self.rule_vars[r["id"]]
            v.set(val if val is not None else r["id"] in jzcore.DEFAULT_ON)

    def preview_clean(self):
        b = self.first_selected()
        if not b:
            messagebox.showinfo("未选择", "请先在书库中勾选至少一本书。")
            return
        try:
            text = jzcore.load_text(b["path"])
            rules = self.active_rules()
            cleaned, removed = jzcore.clean_text(text, rules)
        except Exception as e:
            messagebox.showerror("预览失败", str(e))
            return
        for t, s in ((self.txt_before, text), (self.txt_after, cleaned)):
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.insert("1.0", "\n".join(s.splitlines()[:400]))
            t.configure(state="disabled")
        self.cmp_var.set("删除 %d 行，%d → %d 字" % (removed, len(text), len(cleaned)))
        self.log("预览《%s》：启用 %d 条规则，删除 %d 行" % (b["title"], len(rules), removed))

    def preview_chap(self):
        b = self.first_selected()
        if not b:
            messagebox.showinfo("未选择", "请先在书库中勾选至少一本书。")
            return
        custom = self.custom_re.get().strip() or None
        try:
            text = jzcore.load_text(b["path"])
            rules = self.active_rules()
            if rules:
                text, _r = jzcore.clean_text(text, rules)
            chapters = jzcore.split_chapters(text, custom)
        except ValueError as e:
            messagebox.showerror("正则无效", str(e))
            return
        except Exception as e:
            messagebox.showerror("分章失败", str(e))
            return
        for i in self.tv_chap.get_children():
            self.tv_chap.delete(i)
        for i, (t, body) in enumerate(chapters[:2000], 1):
            self.tv_chap.insert("", "end", values=(i, t, "{:,}".format(len(body))))
        total = sum(len(x[1]) for x in chapters)
        self.chap_var.set("《%s》共切出 %d 章，正文合计 %s 字"
                          % (b["title"], len(chapters), "{:,}".format(total)))
        self.log("试分《%s》：%d 章" % (b["title"], len(chapters)))

    # ------------------------------------------------------------ 执行
    def start_run(self):
        sel = [b for b in self.books if b["sel"]]
        if not sel:
            messagebox.showinfo("未选择", "请先在书库中勾选要处理的书。")
            return
        fmts = [k for k, v in self.fmt_vars.items() if v.get()]
        mode = self.mode_var.get()
        outdir = self.out_var.get().strip()
        if mode in ("new", "none") and not outdir:
            messagebox.showwarning("缺少输出目录", "请先选择输出目录。")
            return
        if mode == "none" and not fmts:
            messagebox.showwarning("无事可做",
                                   "你选择了「仅导出」却又没有勾选任何导出格式。")
            return
        if mode == "inplace":
            if not messagebox.askyesno(
                    "确认原地覆盖",
                    "将把清洗后的内容写回 %d 个原文件，每个原文件会先备份为 .bak。\n\n"
                    "此操作会改动你的原始文件，确定继续吗？" % len(sel)):
                return
        if self.busy:
            return
        self.set_busy(True)
        self.cancel = False
        threading.Thread(target=self.run_worker, args=(sel, fmts, mode, outdir),
                         daemon=True).start()

    def run_worker(self, sel, fmts, mode, outdir):
        rules = self.active_rules()
        custom = self.custom_re.get().strip() or None
        ok = fail = 0
        if mode != "inplace" and outdir:
            try:
                os.makedirs(outdir, exist_ok=True)
            except OSError as e:
                self.q.put(("log", "无法创建输出目录：%s" % e))
                self.q.put(("done", ("run", 0, len(sel), outdir)))
                return
        total = len(sel)
        for i, b in enumerate(sel, 1):
            if self.cancel:
                break
            self.q.put(("prog", (i - 1, total, "处理中 %d/%d：%s" % (i, total, b["title"]))))
            try:
                text = jzcore.load_text(b["path"])
                removed = 0
                if rules:
                    text, removed = jzcore.clean_text(text, rules)
                chapters = jzcore.split_chapters(text, custom)
                title = b["title"] or os.path.splitext(b["name"])[0]
                base = safe_name(title)
                if mode == "inplace":
                    bak = b["path"] + ".bak"
                    if not os.path.exists(bak):
                        try:
                            os.replace(b["path"], bak)
                        except OSError:
                            pass
                    with open(b["path"], "w", encoding="utf-8", newline="\n") as f:
                        f.write(text)
                elif mode == "new" and outdir:
                    with open(self.uniq(outdir, base + ".txt"), "w",
                              encoding="utf-8", newline="\n") as f:
                        f.write(text)
                if outdir:
                    if "epub" in fmts:
                        jzcore.write_epub(self.uniq(outdir, base + ".epub"),
                                          title, b["author"], chapters)
                    # “输出到新目录”落盘的 TXT 与合并 TXT 内容等价，避免生成重复文件
                    if "merge" in fmts and mode != "new":
                        jzcore.save_txt(chapters, self.uniq(outdir, base + ".txt"), merge=True)
                    if "split" in fmts:
                        jzcore.save_txt(chapters, self.uniq(outdir, base + ".txt"), merge=False)
                self.q.put(("log", "[%d/%d] %s：%d 章，清洗删除 %d 行"
                            % (i, total, title, len(chapters), removed)))
                ok += 1
            except Exception as e:
                fail += 1
                self.q.put(("log", "[%d/%d] %s 失败：%s" % (i, total, b["title"], e)))
                self.q.put(("log", traceback.format_exc(limit=1).strip()))
        self.q.put(("prog", (total, total, "处理完成")))
        self.q.put(("done", ("run", ok, fail, outdir if mode != "inplace" else "原地覆盖")))

    def uniq(self, outdir, filename):
        p = os.path.join(outdir, filename)
        if not os.path.exists(p):
            return p
        stem, ext = os.path.splitext(filename)
        n = 1
        while True:
            p = os.path.join(outdir, "%s (%d)%s" % (stem, n, ext))
            if not os.path.exists(p):
                return p
            n += 1


class _Splash:
    """开屏海报：无边框置顶窗，alpha 淡入 → 回调构建主窗 → close() 淡出销毁。

    任意键或点击海报可跳过等待，直接进入主界面。
    时序全部由 after 驱动；_skipped 置位后淡入链立即收敛。
    """

    def __init__(self, root):
        self.root = root
        self._fade_job = None
        self._skipped = False
        self._fade_done = None
        self._hold_then = None
        self._then = None
        win = tk.Toplevel(root)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=SPLASH_BG)
        _center_win(win, SPLASH_W, SPLASH_H)
        c = tk.Canvas(win, width=SPLASH_W, height=SPLASH_H, bg=SPLASH_BG,
                      highlightthickness=0, bd=0)
        c.pack()
        self._paint(c)
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            # 极少数远程环境不支持窗口透明度：直接亮起并让 owner 尽快接手
            win.attributes("-alpha", 1.0)
            self._skipped = True
        win.bind("<Button-1>", self._skip)
        win.bind("<Key>", self._skip)
        win.focus_force()
        win.update_idletasks()

    def _paint(self, c):
        W, H = SPLASH_W, SPLASH_H
        cx = W // 2
        g, ln = SPLASH_GOLD, SPLASH_LINE
        # 细金外框
        c.create_rectangle(11, 11, W - 11, H - 11, outline=g, width=2)
        # 四角回形小装饰（沿框延伸的短金线）
        L = 22
        c.create_line(11, 11, 11 + L, 11, fill=g, width=3)
        c.create_line(11, 11, 11, 11 + L, fill=g, width=3)
        c.create_line(W - 11, 11, W - 11 - L, 11, fill=g, width=3)
        c.create_line(W - 11, 11, W - 11, 11 + L, fill=g, width=3)
        c.create_line(11, H - 11, 11 + L, H - 11, fill=g, width=3)
        c.create_line(11, H - 11, 11, H - 11 - L, fill=g, width=3)
        c.create_line(W - 11, H - 11, W - 11 - L, H - 11, fill=g, width=3)
        c.create_line(W - 11, H - 11, W - 11, H - 11 - L, fill=g, width=3)
        # 主标题「卷帙」：楷体大字
        c.create_text(cx, 88, text=APP_CN, font=("KaiTi", 58),
                      fill=SPLASH_INK, anchor="n")
        # 英文名（字母间隔拉宽，模拟字距）
        c.create_text(cx, 172, text=" ".join(APP_EN), font=(FONT[0], 13),
                      fill=SPLASH_GOLD, anchor="n")
        # 一句定位
        c.create_text(cx, 212, text="扫描 · 清洗 · 分章 · 导出",
                      font=(FONT[0], 11), fill=SPLASH_GRAY, anchor="n")
        # 分隔线 + 底部信息
        c.create_line(cx - 90, 250, cx + 90, 250, fill=ln, width=1)
        c.create_text(cx, 272, text="%s · 纯本地离线工具 · 点击或按任意键跳过"
                      % APP_VER, font=(FONT[0], 9), fill=SPLASH_DIM, anchor="n")

    # ------------------------------------------------------------ 动画
    def fade_in(self, done):
        """从透明淡入到完全不透明，完成时调用 done()（供 owner 构建主窗）。"""
        self._fade_done = done
        self._step(0.0, 1.0)

    def hold(self, ms, then):
        """不透明状态停留 ms 后执行 then；停留期间点击可提前触发。"""
        self._hold_then = then
        self._fade_job = self.root.after(ms, self._fire_hold)

    def _fire_hold(self):
        self._fade_job = None
        cb, self._hold_then = self._hold_then, None
        if cb:
            cb()

    def _cancel_job(self):
        if self._fade_job:
            try:
                self.root.after_cancel(self._fade_job)
            except Exception:
                pass
            self._fade_job = None

    def _step(self, a0, a1):
        a = min(a1, a0 + 0.13) if not self._skipped else a1
        try:
            self.win.attributes("-alpha", a)
        except tk.TclError:
            a = a1
        if a < a1 - 1e-9:
            self._fade_job = self.root.after(20, lambda: self._step(a, a1))
        else:
            cb, self._fade_done = self._fade_done, None
            if cb:
                cb()

    def close(self, then=None):
        """从当前透明度淡出并销毁，完成后回调 then（进入主窗口）。"""
        self._then = then
        self._step_out()

    def _step_out(self):
        try:
            cur = float(self.win.attributes("-alpha"))
        except tk.TclError:
            cur = 0.0
        a = max(0.0, cur - 0.15)
        try:
            self.win.attributes("-alpha", a)
        except tk.TclError:
            a = 0.0
        if a > 1e-9:
            self._fade_job = self.root.after(18, self._step_out)
        else:
            self._destroy()

    def _destroy(self):
        self._fade_job = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        cb, self._then = self._then, None
        if cb:
            cb()

    def _skip(self, _e=None):
        """点击 / 按键：从当前阶段尽量跳到终点，可连点逐级推进。"""
        self._cancel_job()
        if self._fade_done:                 # 淡入中：直接到最亮并继续原流程
            self._skipped = True
            try:
                self.win.attributes("-alpha", 1.0)
            except tk.TclError:
                pass
            cb, self._fade_done = self._fade_done, None
            if cb:
                cb()
        elif self._hold_then:               # 停驻中：提前结束停留
            self._fire_hold()
        elif self._then:                    # 淡出中：立即销毁收尾
            self._destroy()


def _boot(root):
    app = App(root)
    _center_win(root, 1080, 720)


def main():
    root = tk.Tk()
    _dpi(root)
    if os.environ.get("JUANZHI_NO_SPLASH"):     # 测试/调试逃生门
        _boot(root)
        root.mainloop()
        return
    root.withdraw()
    try:
        sp = _Splash(root)
    except Exception:
        root.deiconify()
        _boot(root)
        root.mainloop()
        return

    def build_and_go():
        _boot(root)                             # 海报最亮时构建主窗，无感
        sp.hold(550, lambda: sp.close(then=lambda: root.deiconify()))

    sp.fade_in(build_and_go)
    root.mainloop()


if __name__ == "__main__":
    main()
