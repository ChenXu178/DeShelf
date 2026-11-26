# -*- coding: utf-8 -*-
"""封面与插图下载的冒烟测试（桌面版）。

覆盖这一轮的改动：
  ① 插图链接粗筛：域名首页/目录页这类明显不是图的链接不联网
  ② 插图下载进度：日志里「插图下载中 n/N」原地刷新，只占一行
  ③ 封面查找：书籍目录 → 导出目录，两处都有时书籍目录优先
  ④ 网络封面下载：转格式后按文件名落盘；非图片/失效返回 None
  ⑤ write_epub：封面文件名按 MIME 归一，空字节按「无封面」
  ⑥ 导出页：没有「封面」标签，只有按钮；未勾 EPUB 置灰；勾选变化显示「已设 N 本」
  ⑦ 封面窗：网格卡片（封面/书名/作者）、右键菜单（内置封面的书多一项「更换默认
     封面」）、底栏「默认封面」下拉框统一换风格、本地换图、网络下载、取消/确定
  ⑧ 开始处理：epub 封面就是封面窗里那份字节
  ⑨ 插图下载时日志里有进度、首页/目录不请求、插图按 001… 编号打进 epub

用法：python _test_cover.py   （不需要联网；图片走本机临时 HTTP 服务）
"""
import http.server
import os
import socketserver
import struct
import sys
import tempfile
import threading
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# 断言比对的是中文文案：固定界面语言，免得用户切成英文后误报
os.environ["JUANZHI_LANG"] = "zh"

import jzcore

# 测试隔离：不读、也不写用户自己的配置
jzcore.load_config = lambda: {}
jzcore.save_config = lambda cfg: None

import tkinter as tk
from tkinter import filedialog

os.startfile = lambda p: None       # 别在测试时弹资源管理器

import Juanzhi_Desktop as D
from Juanzhi_Desktop import App, CoverPicker, _book_key

try:
    from PIL import Image as _PIL            # 有 Pillow 才会「统一转 JPEG」
    HAS_PIL = True
except Exception:
    _PIL = None
    HAS_PIL = False

_warns = []
D.messagebox.showinfo = lambda *a, **k: None
D.messagebox.showwarning = lambda *a, **k: _warns.append(a)
D.messagebox.showerror = lambda *a, **k: _warns.append(a)

fails = []


def check(label, got, want):
    ok = got == want
    print(("  [OK]  " if ok else "  [FAIL]") + " %s -> %r" % (label, got)
          + ("" if ok else " (期望 %r)" % (want,)))
    if not ok:
        fails.append(label)


def truth(label, cond):
    check(label, bool(cond), True)


def make_png(path, w, h, rgb):
    """不依赖 Pillow 造一张合法 PNG：测试环境没有 PIL 也能跑。"""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path


# ---------------------------------------------------------------- 造样本
BASE = tempfile.mkdtemp(prefix="deshelf_cover_")
LIB = os.path.join(BASE, "lib")
OUT = os.path.join(BASE, "out")
SRV = os.path.join(BASE, "srv")
for d in (LIB, OUT, SRV):
    os.makedirs(d)
print("工作目录：", BASE)
print("Pillow：%s" % ("有" if HAS_PIL else "没有（格式转换相关用例按原格式校验）"))

TXT = "第一本书\n作者：甲\n\n第1章 开始\n正文一句话。\n"
TXT2 = "第二本书\n作者：乙\n\n第1章 开始\n正文一句话。\n"
p1 = os.path.join(LIB, "第一本书.txt")
p2 = os.path.join(LIB, "第二本书.txt")
for p, t in ((p1, TXT), (p2, TXT2)):
    with open(p, "w", encoding="utf-8") as f:
        f.write(t)

# 本机 HTTP 服务：统计请求，按路径返回图片 / 网页 / 404
HITS = []
N_IMG = 4
for i in range(1, N_IMG + 1):
    make_png(os.path.join(SRV, "%d.png" % i), 40, 60, (10 + i * 30, 40, 90))


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SRV, **kw)

    def _hit(self):
        HITS.append(self.path.split("?")[0])

    def _page(self):
        body = b"<html></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self._hit()
        if self.path.startswith("/page"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", "13")
            self.end_headers()
            return
        return super().do_HEAD()

    def do_GET(self):
        self._hit()
        if self.path.startswith("/page"):
            return self._page()
        if self.path.startswith("/dead"):
            self.send_error(404)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE_URL = "http://127.0.0.1:%d" % PORT

# ---------------------------------------------------------------- 1. 粗筛
print("\n== 1. 插图链接粗筛（明显不是图的不联网） ==")
ACCEPT = ["https://a.com/1.jpg", "https://a.com/pic.png?x=1",
          "http://a.com/showimg.php?id=9", "https://a.com/images?q=tbn:abc",
          "https://a.com/image/12345", "www.a.com/x.gif",
          "//cdn.a.com/x.webp", "https://a.com/pic/1.JPEG"]
REJECT = ["https://zxcstxt.com/", "https://zxcstxt.com", "http://zxcstxt.com/book/",
          "https://a.com/index.html", "https://a.com/book.php", "https://a.com/x.JSP",
          "/img/1.jpg", ""]
for u in ACCEPT:
    truth("放行 %s" % u, jzcore._img_worth_trying(u))
for u in REJECT:
    check("拦掉 %s" % (u or "(空串)"), jzcore._img_worth_trying(u), False)

print("\n== 2. 预取/下载只请求真候选，并按进度回调 ==")
links = [BASE_URL + "/", BASE_URL + "/book/", BASE_URL + "/index.html"]
links += [BASE_URL + "/%d.png" % i for i in range(1, N_IMG + 1)]
text_img = "插图测试\n" + "\n".join(links) + "\n"
seen = []
st = {}
got = jzcore.prefetch_images(text_img, stats=st,
                             progress=lambda d, t: seen.append((d, t)))
check("请求只落在真图上", sorted(set(HITS)),
      sorted("/%d.png" % i for i in range(1, N_IMG + 1)))
check("首页/目录/网页一次都没请求",
      any(h in ("/", "/book/", "/index.html") for h in HITS), False)
check("检查条数不含被拦的链接", st.get("links"), N_IMG)
check("认出张数", st.get("images"), N_IMG)
check("进度回调次数 = 链接数", len(seen), N_IMG)
check("进度首项", seen[0] if seen else None, (1, N_IMG))
check("进度末项", seen[-1] if seen else None, (N_IMG, N_IMG))

HITS[:] = []
dst = os.path.join(BASE, "dl")
res = jzcore.download_images(text_img, dst)
check("下载产物数量", len(res), N_IMG)
check("下载也跳过首页/目录",
      any(h in ("/", "/book/", "/index.html") for h in HITS), False)
check("插图按 001… 编号", sorted(os.listdir(dst)),
      ["%03d.png" % i for i in range(1, N_IMG + 1)])

# ---------------------------------------------------------------- 3. 封面查找
print("\n== 3. 封面查找：书籍目录 → 导出目录（书籍目录优先） ==")
check("两处都没有 → 找不到", jzcore.find_cover_image(p1, "第一本书", OUT), None)
cov_out = make_png(os.path.join(OUT, "第一本书.png"), 30, 40, (200, 10, 10))
check("只传书籍目录 → 仍找不到", jzcore.find_cover_image(p1, "第一本书"), None)
check("带导出目录 → 找到导出目录那张",
      jzcore.find_cover_image(p1, "第一本书", OUT), cov_out)
cov_lib = make_png(os.path.join(LIB, "第一本书.png"), 30, 40, (10, 200, 10))
check("两处都有 → 书籍目录优先",
      jzcore.find_cover_image(p1, "第一本书", OUT), cov_lib)
check("导出目录不存在也不报错",
      jzcore.find_cover_image(p2, "第二本书", os.path.join(BASE, "nope")), None)
check("导出目录 = 书籍目录", jzcore.find_cover_image(p1, "第一本书", LIB), cov_lib)
# 文件名与书名不一致时按「书名 + .cover」变体也能配上
p3 = os.path.join(LIB, "xx12345.txt")
open(p3, "w", encoding="utf-8").write("正文\n")
cov3 = make_png(os.path.join(OUT, "第三本书.cover.jpg"), 30, 40, (90, 90, 10))
check("按书名匹配 .cover 变体",
      jzcore.find_cover_image(p3, "第三本书", OUT), cov3)

# ---------------------------------------------------------------- 4. 网络封面
print("\n== 4. 网络封面下载（转格式 + 按文件名落盘） ==")
dest = os.path.join(OUT, "第一本书.jpg")
got = jzcore.download_cover_image(BASE_URL + "/1.png", dest)
truth("下载成功", got is not None)
truth("文件已落盘", os.path.exists(dest) and os.path.getsize(dest) > 0)
check("有 Pillow 时统一转 JPEG", got[2] if got else "",
      "image/jpeg" if HAS_PIL else "image/png")
if HAS_PIL:
    with open(dest, "rb") as f:
        check("落盘内容就是 JPEG", f.read(3), b"\xff\xd8\xff")
check("404 → None", jzcore.download_cover_image(BASE_URL + "/dead.jpg", dest), None)
check("网页链接 → None", jzcore.download_cover_image(BASE_URL + "/page", dest), None)
deep = os.path.join(BASE, "deep", "sub", "x.jpg")
truth("目标目录会自动创建",
      jzcore.download_cover_image(BASE_URL + "/2.png", deep) is not None)

# ---------------------------------------------------------------- 5. write_epub
print("\n== 5. write_epub：封面名按 MIME 归一 ==")
chs = [("第1章 开始", "正文一句话。")]
ep = os.path.join(BASE, "c1.epub")
png_bytes = open(cov_lib, "rb").read()
jzcore.write_epub(ep, "第一本书", "甲", chs,
                  cover=(png_bytes, "第一本书.png", "image/png", 30, 40))
with zipfile.ZipFile(ep) as z:
    names = z.namelist()
    opf = z.read("OEBPS/content.opf").decode("utf-8")
    page = z.read("OEBPS/cover.xhtml").decode("utf-8")
    cover_data = z.read("OEBPS/cover.png") if "OEBPS/cover.png" in names else None
check("封面文件名归一成 cover.png", "OEBPS/cover.png" in names, True)
check("不沿用传进来的 name", "OEBPS/第一本书.png" in names, False)
check("opf 引用归一后的名字", 'href="cover.png"' in opf, True)
check("cover.xhtml 指向封面", 'src="cover.png"' in page, True)
check("封面字节原样打进 zip", cover_data == png_bytes, True)

ep = os.path.join(BASE, "c2.epub")
jzcore.write_epub(ep, "空封面", "", chs,
                  cover=(b"", "cover.jpg", "image/jpeg", 0, 0))
with zipfile.ZipFile(ep) as z2:
    check("空字节按无封面处理", [n for n in z2.namelist() if "cover" in n], [])

# ---------------------------------------------------------------- 6. 导出页
print("\n== 6. 导出页：封面按钮 ==")
root = tk.Tk()
root.geometry("1100x740+20+20")
app = App(root)
app.dir_var.set(LIB)
app.out_var.set(OUT)
books = []
for p in (p1, p2):
    info = jzcore.scan_file(p)
    info["rel"] = os.path.basename(p)
    books.append(info)
app.books = books
app.reload_rows()
root.update()

S = app.S
check("导出页没有「封面」标签", hasattr(app, "lb_cover"), False)
check("按钮文案就是「封面」", app.btn_cover.cget("text"), "封面")
check("主题按钮还在（同款样式）", app.btn_theme.winfo_class(), "TButton")
check("空映射时按钮不带数量", app.cover_map, {})

app.fmt_vars["epub"].set(False)
app.refresh_epub_opts_state()
root.update()
check("未勾 EPUB → 封面按钮置灰", "disabled" in app.btn_cover.state(), True)
app.fmt_vars["epub"].set(True)
app.refresh_epub_opts_state()
root.update()
check("勾回 EPUB → 按钮可用", "disabled" in app.btn_cover.state(), False)

# ---------------------------------------------------------------- 7. 封面窗
print("\n== 7. 封面窗：卡片 / 右键菜单 / 换图 / 下载 ==")
cov_a = make_png(os.path.join(LIB, "第一本书.png"), 60, 80, (30, 120, 200))
warns_before = len(_warns)
picker = CoverPicker(root, books, {}, OUT, app.lang, S)
deadline = time.time() + 10
while time.time() < deadline:
    root.update()
    if all(picker._cards[i]["photo"] is not None for i in picker._cards):
        break
    time.sleep(0.02)
check("卡片数 = 书籍数", len(picker._cards), 2)
check("每张卡都算出并贴上了封面",
      [picker._cards[i]["photo"] is not None for i in (0, 1)], [True, True])
check("卡片书名", picker._cards[0]["title"].cget("text"), "第一本书")
check("卡片作者", picker._cards[0]["author"].cget("text"), "甲")

# 窗口里的封面必须就是 cover_for_book(auto) 的结果（同名图优先，否则默认封面）
expect = []
for p, title, author in ((p1, "第一本书", "甲"), (p2, "第二本书", "乙")):
    c = jzcore.cover_for_book(p, title, author, "auto", OUT)
    expect.append(c[0] if c else None)
check("封面窗用的是 cover_for_book(auto) 的结果",
      [picker.covers[_book_key(p1)][0] == expect[0],
       picker.covers[_book_key(p2)][0] == expect[1]], [True, True])

# 右键菜单：把 tk.Menu 换成记录器，只看它往菜单里加了哪几项
_menu_labels = []


class _Ev(object):
    x_root, y_root = 120, 140


class _MenuRec(object):
    def __init__(self, *a, **k):
        pass

    def add_command(self, label=None, command=None, **k):
        _menu_labels.append(label)

    def add_cascade(self, label=None, menu=None, **k):
        _menu_labels.append(label)

    def add_separator(self, *a, **k):
        _menu_labels.append("---")

    def tk_popup(self, *a, **k):
        pass

    def grab_release(self, *a, **k):
        pass

    def destroy(self):
        pass


_real_menu = tk.Menu
tk.Menu = _MenuRec
try:
    picker._menu(_Ev(), 0)
    picker._menu(_Ev(), 1)
finally:
    tk.Menu = _real_menu
# 本地封面的书：两项；内置封面的书：两项 + 子菜单（5 种风格）+ 一项
check("右键项数：本地 2 项、内置 2 + 5 + 1 项", len(_menu_labels), 10)
check("菜单第一项", _menu_labels[0], S["cover_pick_img"])
check("菜单第二项", _menu_labels[1], S["cover_dl"])
check("本地封面的书没有「更换默认封面」", _menu_labels[2], S["cover_pick_img"])
check("子菜单列出全部内置风格", _menu_labels[4:9],
      [jzcore.cover_style_name(s, app.lang) for s in jzcore.cover_style_ids()])
check("内置封面的书多出「更换默认封面」", _menu_labels[9], S["cover_new_default"])
check("本地封面的书不能换内置封面", picker._can_set_default(0), False)
check("内置封面的书能换内置封面", picker._can_set_default(1), True)

# ---------------------------------------------------------------- 7b 默认封面
print("\n== 7b. 底栏「默认封面」下拉框：统一换风格 ==")
check("底栏有下拉框", picker.cb_style.winfo_class(), "TCombobox")
check("下拉框是只读的", str(picker.cb_style.cget("state")), "readonly")
check("下拉项 = 全部内置风格（没有 6/7）",
      list(picker.cb_style.cget("values")),
      [jzcore.cover_style_name(s, app.lang) for s in jzcore.cover_style_ids()])
check("下拉项顺序即 COVER_STYLES",
      jzcore.cover_style_ids(),
      ["sujian", "indigo", "cinnabar", "ink", "minimal"])
check("默认风格是素笺", picker.style, jzcore.DEFAULT_COVER_STYLE)

p1_before = picker.covers[_book_key(p1)][0]
p2_before = picker.covers[_book_key(p2)][0]
picker.style_var.set(jzcore.cover_style_name("ink", app.lang))
picker._on_style_all()
deadline = time.time() + 15
while time.time() < deadline:
    root.update()
    got = picker.covers.get(_book_key(p2))
    if (got and got[0] != p2_before
            and picker.pins.get(_book_key(p2)) == "ink"):
        break
    time.sleep(0.02)
check("内置封面按新风格重画了", picker.covers[_book_key(p2)][0] != p2_before, True)
check("重画的是合法 JPEG", picker.covers[_book_key(p2)][0][:3], b"\xff\xd8\xff")
check("这本记录成「墨韵」", picker.pins.get(_book_key(p2)), "ink")
check("已有的本地封面不参与统换", picker.covers[_book_key(p1)][0], p1_before)
check("全局风格已记住", picker.result_style, "ink")
check("状态行提示统一换过", picker._status.cget("text"),
      S["cover_style_all"].format(jzcore.cover_style_name("ink", app.lang)))

# 单本换内置封面（右键子菜单）：只影响这一本
picker.set_default(1, "cinnabar")
check("单本换成朱印", picker.pins.get(_book_key(p2)), "cinnabar")
check("单本换风格不动别的书", picker.covers[_book_key(p1)][0], p1_before)
check("状态行提示单本换过", picker._status.cget("text"),
      S["cover_style_one"].format(jzcore.cover_style_name("cinnabar", app.lang)))
picker.set_default(0, "ink")            # 有本地封面的书：不生效
check("本地封面不会被单本换成内置", picker.covers[_book_key(p1)][0], p1_before)

# 选择本地图片：patch 文件选择器，只验「转格式 + 刷新卡片」
pick = make_png(os.path.join(BASE, "pick.png"), 90, 120, (200, 40, 40))
_old_pick = filedialog.askopenfilename
filedialog.askopenfilename = lambda **kw: pick
try:
    picker.pick_image(1)
finally:
    filedialog.askopenfilename = _old_pick
got = picker.covers[_book_key(p2)]
truth("本地图片已换到这本书上", got is not None)
check("换成 JPEG（有 Pillow）", got[2] if got else "",
      "image/jpeg" if HAS_PIL else "image/png")
truth("卡片缩略图已刷新", picker._cards[1]["photo"] is not None)
check("状态行显示文件名", picker._status.cget("text"), "pick.png")

# 下载网络封面：patch 链接输入框，其余走真下载 + 落盘
HITS[:] = []
picker._ask_url = lambda: BASE_URL + "/3.png"
picker.download(0)
deadline = time.time() + 10
while time.time() < deadline:
    root.update()
    if "已保存" in picker._status.cget("text"):
        break
    time.sleep(0.03)
check("下载请求已发出", HITS, ["/3.png"])
saved = os.path.join(OUT, "第一本书.jpg")
truth("按书籍文件名存到导出目录", os.path.exists(saved) and os.path.getsize(saved) > 0)
truth("状态行给出保存位置",
      os.path.basename(saved) in picker._status.cget("text"))
truth("卡片换成下载的图", picker._cards[0]["photo"] is not None)
check("下载过程没有弹警告", len(_warns), warns_before)

picker._cancel()
check("取消后 result 为空", picker.result, None)

# ---------------------------------------------------------------- 8. 导出
print("\n== 8. 确定后由「开始处理」写进 epub ==")
green = jzcore.prepare_cover_image(make_png(os.path.join(BASE, "g.png"),
                                            50, 70, (0, 200, 0)))
truth("测试封面准备完成", green is not None)


class _FakePicker(object):
    """替掉真窗口：只验主窗口怎么用封面窗的结果。"""

    ret = None

    def __init__(self, *a, **kw):
        pass

    def show(self):
        return _FakePicker.ret


_real_picker = D.CoverPicker
D.CoverPicker = _FakePicker
try:
    _FakePicker.ret = None
    app.cover_map = {_book_key(p2): green}      # 假设第二本之前设过
    app.refresh_info()
    root.update()
    check("已有设置时按钮显示数量", app.btn_cover.cget("text"),
          S["cover_btn_n"].format(1))

    app.choose_covers()                         # 取消
    check("取消不动已有设置", list(app.cover_map), [_book_key(p2)])
    check("取消后封面字节没变", app.cover_map[_book_key(p2)][0] == green[0], True)

    _FakePicker.ret = {_book_key(p1): green, _book_key(p2): green}
    app.choose_covers()
    check("确定后提交整份封面", sorted(app.cover_map),
          sorted([_book_key(p1), _book_key(p2)]))
    check("按钮显示已设 2 本", app.btn_cover.cget("text"),
          S["cover_btn_n"].format(2))
    app.poll()                                  # 日志走队列，刷一次再读
    root.update()
    truth("日志记下封面设置",
          "封面设置已更新：2 本" in app.logbox.get("1.0", "end-1c"))

    app.books[0]["sel"] = False                 # 只勾一本 → 数量跟着变
    app.refresh_info()
    root.update()
    check("勾选变化后数量跟着变", app.btn_cover.cget("text"),
          S["cover_btn_n"].format(1))
    app.books[0]["sel"] = True
    app.refresh_info()
finally:
    D.CoverPicker = _real_picker

OUT2 = os.path.join(BASE, "out_export")
app.out_var.set(OUT2)
app.mode_var.set("new")
app.fmt_vars["epub"].set(True)
app.fmt_vars["merge"].set(False)
app.fmt_vars["split"].set(False)
app.sum_var.set(False)
app.start_run()
deadline = time.time() + 60
while time.time() < deadline and app.busy:
    root.update()
    time.sleep(0.02)
root.update()
check("导出结束", app.busy, False)
eps = sorted(n for n in os.listdir(OUT2) if n.endswith(".epub"))
check("两本都导出了", eps, ["第一本书.epub", "第二本书.epub"])
for name in eps:
    with zipfile.ZipFile(os.path.join(OUT2, name)) as z:
        data = z.read("OEBPS/cover.jpg")
    check("%s 的封面就是封面窗里那份字节" % name, data == green[0], True)

# ---------------------------------------------------------------- 9. 进度
print("\n== 9. 插图下载：日志进度一行 + 插图进 epub ==")
p_img = os.path.join(LIB, "有图的书.txt")
with open(p_img, "w", encoding="utf-8") as f:
    f.write("有图的书\n作者：甲\n\n第1章 开始\n"
            + "\n".join([BASE_URL + "/", BASE_URL + "/book/"]
                        + [BASE_URL + "/%d.png" % i for i in range(1, N_IMG + 1)])
            + "\n")
img_book = jzcore.scan_file(p_img)
img_book["rel"] = "有图的书.txt"

for tag, rules in (("校验+下载合并", ["imgkeep", "imgcheck"]),
                   ("只下载", ["imgkeep"])):
    HITS[:] = []
    out_img = os.path.join(BASE, "out_img_" + ("a" if "imgcheck" in rules else "b"))
    app.books = [img_book]
    app.logbox.delete("1.0", "end")
    app.run_worker([img_book], ["epub"], "new", out_img, rules, None,
                   theme=jzcore.DEFAULT_THEME, covers=None, img_dl=True,
                   want_sum=False)
    root.update()
    app.poll()                      # 把队列里的日志（含进度行）刷进日志框
    root.update()
    log = app.logbox.get("1.0", "end-1c")
    prog = [ln for ln in log.splitlines() if "插图下载中" in ln]
    check("%s：进度只占一行" % tag, len(prog), 1)
    truth("%s：进度走到最后一张" % tag,
          bool(prog) and ("%d/%d" % (N_IMG, N_IMG) in prog[0]))
    truth("%s：汇总行记录了保存张数" % tag, ("插图已保存 %d 张" % N_IMG) in log)
    check("%s：首页/目录没被请求" % tag,
          any(h in ("/", "/book/") for h in HITS), False)
    truth("%s：插图按书名落到「插图/书名」" % tag,
          os.path.isdir(os.path.join(out_img, jzcore.IMG_DIRNAME, "有图的书")))
    with zipfile.ZipFile(os.path.join(out_img, "有图的书.epub")) as z:
        truth("%s：epub 里打进了插图" % tag,
              any(n.startswith("OEBPS/images/") for n in z.namelist()))

httpd.shutdown()
root.destroy()
print("\n失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
