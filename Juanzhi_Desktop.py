# -*- coding: utf-8 -*-
"""卷帙 DeShelf — 本地文本整理工具（桌面版，中英双语界面）

扫描 → 清洗 → 分章 → 导出，正文与文件只在本机处理、不上传；
仅当用户勾选「插图链接校验」「下载插图链接」或使用「下载网络封面」时才联网取图。
界面语言：默认跟随系统；菜单「语言 / Language」可即时切换（窗口内重建）并记忆。
"""

import base64
import hashlib
import io
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import traceback
from collections import Counter
from tkinter import filedialog, font as tkfont, messagebox, ttk
import tkinter as tk

try:
    import ctypes
except ImportError:  # 非 Windows / 精简解释器：全部 DPI 调用自动降级
    ctypes = None

try:  # 主题缩略图要平滑缩放；没有 Pillow 也能跑（整数抽样）
    from PIL import Image as _PILImage
except Exception:
    _PILImage = None

import jzcore

APP_CN = jzcore.APP_CN
APP_EN = jzcore.APP_EN
APP_VER = jzcore.APP_VER
AUTHOR = "© 永远的兰兰 · Lanlan Eternal"
# 底色与卡片都往白里调：tkinter 画不出圆角和阴影，底色一深就成了
# 「白块贴在灰板上」，反而更花。留 3 个色阶的差足够分出层，
# 又不会在卡片缝隙和大片空白处露出显眼的灰。
BG = "#F5F6F8"
CARD = "#FFFFFF"
LINE = "#D3D8DE"  # 细线：太白的分组框在白底上看不出来
INK = "#232629"
MUTED = "#5F6670"
BLUE = "#2F6FB0"
BLUE_D = "#24598F"
GREEN = "#2E8B57"
GREEN_D = "#237043"
RED = "#C0392B"
HOVER = "#E8EBEF"
PRESS = "#DDE2E7"
FONT = ("Microsoft YaHei UI", 9)
FONT_S = ("Microsoft YaHei UI", 8)
FONT_B = ("Microsoft YaHei UI", 9, "bold")
MONO = ("Consolas", 9)

# 运行日志里「插图下载中 3/57」的刷新间隔（秒）：太密会把界面刷成幻灯片，
# 太稀又会让人以为卡住了；首条和末条一定输出，不受这个间隔限制。
IMG_PROG_GAP = 0.3

# ============================================================ 语言
ZH = "zh"
EN = "en"

HELP_ZH = """卷帙 DeShelf 使用说明

【1 扫描入库】
  选择一个目录后点「扫描」，程序会递归查找其中所有 .txt 文件，
  自动识别编码（GBK / UTF-8 / UTF-16）、统计字数、按内容指纹标出重复文件。
  原文件始终保持原地不动，卷帙只记录索引，不会把书搬进自己的库。

【2 批量清洗】
  勾选需要的规则，点「预览效果」可以对比清洗前后的文本。
  常用组合：含网址的行 + 站点宣传行 + 翻页导航残留 + 乱码行 + 压缩连续空行。
  「删除所有空行」与「压缩连续空行」建议二选一，前者把全文压成不分段的一片。
  勾选「含网址的行」后，下面会多出「保留插图链接」「插图链接校验」两条：
  前者按后缀（jpg/jpeg/png/webp/gif）留下正文里的配图链接，后者还会逐条请求一次，
  只保留响应头 Content-Type 确实是图片的链接（返回网页的、失效的照样删掉）；
  图链如果落在站点宣传行里，随那一行一起删。

【3 智能分章】
  内置中文网文章节规则库，可识别「第1章 / 第一百二十三章 / 卷三 / 序章 / 番外」等写法。
  如果书的标题写法不在里面（比如「第一折」「01」「卷一 第3回」），整本会被当成一章，
  这时才需要自己填「章节正则」：

  · 上面那格（章节正则）对所有书生效；下面那格（本书专用规则）只对「试分书籍」里
    选中的那本生效，优先级更高。一旦填了自定义正则，内置规则库就不再参与，
    所以规则要把这本书的每种标题写法都盖住。
  · 判定方式：只看行首；行长不超过 50 字、且不以「。」结尾的行才算标题；
    命中的整行原文就是章节标题（不用在正则里写「提取」）。
  · 不会写不要紧：点输入框右边的「常用写法」，里面按「书的写法」列了 8 条现成的，
    选中一条点「填入」，回分章页点「试分章节」看章节列表；数不对就换一条再试。

  三个常见坑：
    只写 [0-9] —— 正文里「1998 年…」开头的行会被切成标题，记得带上「章/回/折」这类字；
    只写「第[0-9]+章」—— 书里混着「第一章」就漏，字符集里 0-9 与 零一二三… 都要有；
    本书专用规则别填到上面那格 —— 那会影响所有书。

【4 导出分发】
  清洗结果去向：
    输出到新目录 — 原文件一个字节都不动，最安全
    原地覆盖 — 先备份为 .bak 再写回，省空间但有风险
    仅导出 — 不落盘整理后的 TXT，只生成导出文件
  导出格式可多选：EPUB（兼容绝大多数阅读器）、合并 TXT、分章 TXT。
  文件名决定导出文件（EPUB、合并 TXT、分章 TXT 目录）叫什么：
  保持原样（默认，用书名）/ 作者名 - 书名 / [作者名] 书名 / 《书名》作者：作者名 /
  自定义格式。自定义格式用 book 表示书名、author 表示作者名，必须含 book，
  例如《book》 author；生成的名称会自动去掉 \\ / : * ? " < > | 等非法字符。
  「下载插图链接」需先在批量清洗里勾「保留插图链接」，否则一直置灰：
  勾上后正文里的插图会下载到「输出目录/插图/书名」，按 001、002… 顺序命名
  （webp/gif/bmp 会转成 jpg 再存，阅读器支持面更宽）；
  没有图片后缀的链接（如 images?q=tbn:…）也会请求一次，是不是图以响应头为准；
  同时导出 EPUB 时，插图会一并打包进 epub，正文里的链接（含 <img> 标签写法）
  自动替换成 epub 内的插图路径；<img … alt="…"> 的 alt 会原样保留，
  并在插图下方作为图注显示。
  若清洗页的「插图链接校验」也勾着，开始处理时两者合并成一趟请求：取图的同时
  就完成校验，不会同一批链接先校验一遍、下载时再请求一遍。
  「生成清洗内容汇总」（默认勾选）会在输出目录写一份「清洗内容汇总.txt」：
  按书籍分类列出被清洗掉的每一段文字，并标出它在原文件里的行号，
  以及这条内容命中的是哪条规则（自定义规则写明规则名或正则）；
  空行不逐条列出，只统计删掉了几行。用来回查有没有把正文当广告误删 ——
  与清洗页的标红预览是一回事，只是留成文件，便于按书逐条核对。

【小提示】
  · 双击书库中的行可切换勾选；右键可修改书名 / 作者、打开文件位置。
  · 扫描结果会缓存在目录下的 .deshelf_index.json，下次打开秒载入。
  · 导出到手机后，用支持本地导入的阅读器打开 EPUB 即可带目录阅读。
"""

HELP_EN = """DeShelf User Guide

[1] Scan Library
  Pick a folder and click Scan. DeShelf recursively finds every .txt file,
  detects the encoding (GBK / UTF-8 / UTF-16), counts characters and flags
  duplicates by content fingerprint. Your originals never move — only an
  index is stored.

[2] Batch Clean
  Tick the rules you need and hit Preview to compare before/after text.
  A common combo: URL lines + site promos + pagination leftovers +
  corrupted lines + collapse blank runs.
  “Delete all blank lines” and “Collapse blank runs” are alternatives —
  pick one; the former squeezes the whole book into an unbroken block.
  Ticking “Lines with URLs” reveals two more: “Keep illustration links” keeps
  picture links by suffix (jpg/jpeg/png/webp/gif), and “Verify illustration links”
  additionally requests each link and keeps only those whose Content-Type really
  is an image (HTML pages and dead links are still deleted). A link sitting on a
  site-promo line is removed with that line.

[3] Smart Chapter Split
  Built-in Chinese web-novel patterns match lines like 第1章 / 第一百二十三章 /
  卷三 / 序章 / 番外. If a book uses something else (e.g. 第一折 / 01 / 卷一 第3回)
  the whole file becomes one chapter — that is when a custom chapter regex is needed:

  · The upper box applies to every book; the lower box applies only to the book picked
    in “Book to split”, and wins over the upper one. Once any custom regex is filled in,
    the built-in library is no longer used — so the pattern must cover every heading form
    the book uses.
  · A line qualifies when it matches from its start, is at most 50 characters long and
    does not end with “。”; the whole line becomes the chapter title (no capture groups
    needed).
  · Not sure how to write one? Press “Templates” next to the box — eight ready-made
    patterns listed by “Book looks like”. Pick one, press Fill, then “Try Split”.

  Three traps:
    [0-9] alone — body lines starting with “1998 …” become titles; keep 章/回/折 in it;
    第[0-9]+章 alone — misses 第一章; include both 0-9 and 零一二三…;
    do not put a per-book rule in the upper (global) box — it would hit every book.

[4] Export
  Where cleaned text goes:
    New folder  — originals stay byte-identical, safest
    Overwrite   — .bak backup first, saves space but touches files
    Export only — keep no cleaned TXT, just generated files
  Formats (multi-select): EPUB (TOC, most readers), merged TXT,
  per-chapter TXT.
  “File name” names the exported files
  (EPUB, merged TXT, per-chapter folder): keep as is (default, the title) /
  Author - Title / [Author] Title / 《Title》by Author / custom format.
  A custom format uses book for the title and author for the author and must
  contain book, e.g. 《book》 author; \\ / : * ? " < > | are stripped.
  “Download illustration links” stays greyed out until “Keep illustration
  links” is ticked on the cleaning page. Once ticked, illustrations are saved
  to “output folder/插图/book title” as 001, 002… (webp/gif/bmp are converted
  to jpg); links without an image suffix (e.g. images?q=tbn:…) are requested
  too — the Content-Type decides;
  when EPUB is also exported
  they are packed into the epub and the links in the text (including <img>
  tags) are replaced with the in-epub image paths. The alt text of an
  <img alt="…"> is kept and printed as a caption under the picture.
  If “Verify illustration links” is on as well, the two share a single
  request per link — downloading decides verification, no double fetch.
  “Write a cleanup summary” (on by default) saves “清洗内容汇总.txt” in the
  output folder: per book, every removed piece of text, its line number in the
  ORIGINAL text, and which rule removed it (custom rules show their name or
  pattern). Blank lines are not listed one by one, only counted, so you can
  check that no real paragraph was deleted as an ad.

[Tips]
  · Double-click a library row to toggle selection; right-click to edit the title / author
    or for file actions.
  · Scan results are cached in .deshelf_index.json next to the folder —
    reopening loads instantly.
  · Send EPUBs to your phone and open them in any local-import reader.
"""

DISC_ZH = """免责声明

卷帙 DeShelf 是一款以本地处理为主的文本整理工具：默认不联网、不上传，
也不提供、不存储任何书籍内容，仅对用户本机已有的文件做清洗、分章与格式转换。
只有你主动勾选「插图链接校验」「下载插图链接」，或使用「下载网络封面」时，
程序才会按你给出的链接联网取回插图信息或图片本身，且只保存在你自己的电脑上。

用户应确保其处理的文件拥有合法来源并仅用于个人学习研究，
因使用本工具产生的任何版权或法律问题，由使用者自行承担。

本软件按「现状」提供，作者不对数据丢失或损坏承担责任。
请在执行「原地覆盖」前确认已做好备份。
"""

DISC_EN = """Disclaimer

DeShelf is a local-first text-organizing tool: by default it does not connect
to the network or upload anything, and it never hosts or stores book content.
It only cleans, splits and converts files that already exist on your machine.
Network access happens solely when you tick “Verify illustration links” or
“Download illustration links”, or use “Download cover from URL” — it then
fetches image info or the images themselves and keeps them on your computer.

Users are responsible for ensuring the files they process have a legal
source and are used for personal study only. Any copyright or legal issue
arising from the use of this tool is the sole responsibility of the user.

The software is provided “as is”. The author accepts no liability for data
loss or damage. Please confirm you have a backup before using “Overwrite”.
"""

ABOUT_ZH = """版权与许可 · Copyright & License

卷帙 DeShelf {ver}
本地 TXT 整理工具：扫描 · 清洗 · 分章 · 导出 EPUB / TXT。
正文与文件只在本机处理、不上传；仅在你勾选插图校验 / 下载插图，
或使用「下载网络封面」时，才按你给出的链接联网取图。

【作者与署名】
© 2026 永远的兰兰 (Lanlan Eternal)
https://github.com/podcatcher962/DeShelf

【开源许可：MIT License】
本软件以 MIT 许可发布。任何人均可免费使用、复制、修改、合并、发布、再授权
乃至销售本软件的副本，包括商业用途；不用付费，也不用事先告知作者。

MIT 只有一条硬性条件——保留作者署名：
· 任何副本或实质性部分中，必须保留版权声明与完整的 MIT 许可文本
  （即源码仓库根目录的 LICENSE 文件；点下方「复制 MIT 全文」可取原文）。
· 你可以改代码、改软件名、闭源分发，但不能删掉
  「Copyright (c) 2026 Lanlan Eternal」，也不能把作者改成自己的名字后
  声称原创。
· 二次分发（含打包进你自己的产品）时，请在「关于」页或随附文档中
  保留本署名与 MIT 许可全文。

引用或推荐时建议注明：
卷帙 DeShelf © 2026 永远的兰兰 (Lanlan Eternal)，MIT License。

【第三方组件】
运行时（随 EXE 一并打包）：
· Python 3.15 —— PSF License Agreement
· Tcl/Tk 9.0（tkinter）—— BSD-style License（图形界面）
· Pillow（PIL）—— MIT-CMU License（封面绘制、主题缩略图）
· html2image —— MIT License（把版面主题渲成预览图）
  随之打包的依赖：requests、websocket-client（Apache-2.0）；
  urllib3、charset-normalizer（MIT）；certifi（MPL-2.0）；idna（BSD-3-Clause）
构建期（不参与运行）：
· PyInstaller —— GPL-2.0 with bootloader exception
  该例外允许把打包出的程序以 MIT 等任意许可分发，成品 EXE 不受 GPL 约束。
比对数据（只用来判断两行是否为同一段，不改写正文）：
· OpenCC 繁→简对照表 —— Apache License 2.0
· zhconv 的 zh2Hans 字表 —— GPL-2.0-or-later（仅取其中 547 对单字映射）

主题预览由你本机已装的 Chrome / Edge / Chromium 渲染一张截图，浏览器本身
不由本软件打包或分发。封面与界面所用楷体是 Windows 自带字体（simkai.ttf）：
本软件不打包、不分发任何字体文件；换到其它系统会自动回退到可用字体。
各组件的完整许可声明见仓库根目录的 THIRD-PARTY-NOTICES.md。

【免责】
软件按「现状」提供，不附带任何明示或暗示的担保。清洗与分章规则可能误删或
误判内容；桌面版「原地覆盖」会自动生成 .bak 备份，但仍建议处理前自行备份。
因使用本工具造成的数据丢失、版权或法律纠纷，由使用者自行承担。
"""

ABOUT_EN = """Copyright & License

DeShelf {ver}
A local TXT organizer: scan · clean · split · export EPUB / TXT.
Text and files are processed on your machine and never uploaded; the network
is used only for opted-in illustration verification / download or
“Download cover from URL”.

[ Author & attribution ]
© 2026 Lanlan Eternal
https://github.com/podcatcher962/DeShelf

[ License: MIT ]
This software is released under the MIT License. Anyone may use, copy, modify,
merge, publish, sublicense and/or sell copies of it — including commercially —
free of charge and without asking the author first.

MIT has exactly one hard requirement: keep the author's attribution.
· Every copy, or substantial portion of the Software, must retain the copyright
  notice and the full MIT permission notice (the LICENSE file at the repository
  root; “Copy the MIT text” below gives you the exact wording).
· You may change the code, rename the app, or ship it closed-source — but you
  may not remove “Copyright (c) 2026 Lanlan Eternal”, and you may not put your
  own name on it and claim it as original work.
· When redistributing (including bundling it into your own product), keep this
  attribution and the MIT text in the About screen or the bundled docs.

Suggested credit: DeShelf © 2026 Lanlan Eternal, MIT License.

[ Third-party components ]
Runtime (bundled into the EXE):
· Python 3.15 — PSF License Agreement
· Tcl/Tk 9.0 (tkinter) — BSD-style License (GUI)
· Pillow (PIL) — MIT-CMU License (covers and theme thumbnails)
· html2image — MIT License (renders CSS layout themes to preview images)
  its bundled dependencies: requests, websocket-client (Apache-2.0);
  urllib3, charset-normalizer (MIT); certifi (MPL-2.0); idna (BSD-3-Clause)
Build time only (not part of the runtime):
· PyInstaller — GPL-2.0 with bootloader exception, which lets the built EXE be
  distributed under any licence, MIT included.
Comparison data (only to decide whether two lines are the same passage; the
text itself is never rewritten):
· OpenCC traditional→simplified table — Apache License 2.0
· zhconv zh2Hans table — GPL-2.0-or-later (547 single-character pairs only)

Theme previews are rendered by the Chrome / Edge / Chromium already installed on
your machine; no browser is bundled or redistributed. The KaiTi font used by
covers and the UI ships with Windows (simkai.ttf): no font file is bundled or
redistributed, and other systems fall back to an available font.
Full notices: THIRD-PARTY-NOTICES.md at the repository root.

[ Disclaimer ]
Provided “as is”, without warranty of any kind. Cleaning and chapter rules may
drop or misjudge content; “Overwrite” on the desktop always writes a .bak
backup, but please keep your own backup anyway. Any data loss, copyright or
legal issue arising from use of this tool is the user's responsibility.
"""

MIT_TEXT = """MIT License

Copyright (c) 2026 Lanlan Eternal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

TEXTS = {
    ZH: {
        # 窗口 / 菜单
        "w_title": "%s %s %s",
        "m_file": "文件", "m_lib": "书库", "m_lang": "语言 Language", "m_help": "帮助",
        "m_pick_dir": "选择目录…", "m_rescan": "重新扫描",
        "m_rescan_fresh": "重新扫描（忽略缓存）", "m_quit": "退出",
        "m_sel_all": "全选", "m_sel_none": "全不选", "m_invert": "反选",
        "m_sel_dup": "只选重复文件", "m_export_csv": "导出书单 CSV",
        "m_usage": "使用说明", "m_disclaimer": "免责声明", "m_about": "关于",
        "lang_busy": "正在处理中",
        "lang_busy_msg": "请等待当前任务完成后再切换语言。",
        # 顶部栏
        "lib_dir": "书库目录：", "browse": "浏览…", "scan": "扫描",
        "b_add_files": "添加文件…", "d_pick_files": "选择要加入书库的文本文件",
        "b_rescan": "重新扫描",
        "flt_txt": "文本文件", "flt_all": "所有文件",
        "st_add_files": "已添加 {0} 个文件{1}",
        "log_add_files": "  已添加 {0} 个文件；跳过 {1} 个（重复或读不了）",
        "log_root_fallback": "  未选书库目录，已改用该文件所在目录：{0}",
        "log_add_skip_only": "（跳过 {0} 个）",
        "stop": "停止",
        # 页标签
        "tab1": " 1 扫描入库 ", "tab2": " 2 批量清洗 ",
        "tab3": " 3 智能分章 ", "tab4": " 4 导出分发 ",
        # 页1 书库
        "lib_hint": "  双击行可切换勾选，右键可修改书名/作者、打开文件位置",
        "lib_info": "共 {0} 本 · 已选 {1} 本",
        "lib_info_dup": " · 重复 {0} 本",
        "col_title": "书名", "col_author": "作者", "col_chars": "字数",
        "col_enc": "编码", "col_chap": "章节", "col_size": "大小", "col_rel": "相对路径",
        # 页2 清洗
        "grp_rules": "清洗规则（共 {0} 条 · 可滚动）", "b_all_rules": "全选规则", "b_def_rules": "恢复默认",
        "rule_more": "▼ 下面还有 {0} 条没显示，用滚轮往下翻",
        "b_imp_rules": "导入规则…", "b_exp_rules": "导出规则…", "b_edit_rules": "自定义…",
        "d_ok": "确定", "d_cancel": "取消",
        "custom_hint": "每行一条：动作||正则||说明（说明可空）。drop = 删掉整行，cut = 只删掉命中的片段；想忽略大小写写成 drop i；行首加 # 表示这条暂时不用。",
        "log_rules_loaded": "已载入规则包「{2}」：内置 {0} 条、自定义 {1} 条",
        "log_rules_bad": "；跳过 {0} 条无效规则",
        "log_rules_saved": "规则已导出到 {0}",
        "log_rules_edit": "自定义规则已更新：{0} 条",
        "b_preview": "预览效果",
        "b_clean_apply": "应用到所选书籍",
        "d_rule_none": "未选择清洗规则", "d_rule_none_msg": "请至少勾选一条清洗规则后再应用。",
        "prog_clean": "清洗 {0}/{1}：《{2}》",
        "st_clean_done": "已清洗 {0} 本 · 共删除 {1} 行",
        "log_clean_done": "批量清洗完成：{0} 本 · 删除 {1} 行",
        "clean_hint": "  对第一本勾选的书试跑：左边原文（被清洗的部分标红）、右边清洗后",
        "col_pre": "清洗前", "col_post": "清洗后",
        "cmp_var": "删除 {0} 行，{1} → {2} 字",
        "cmp_var_cut": "删除 {0} 行、另 {3} 行只裁了行尾网址，{1} → {2} 字",
        "cmp_jsdup": "（其中简繁重复 {0} 行）",
        "cmp_img": "，保留插图链接 {0} 行",
        "cmp_merge": "，合并断行 {0} 处",
        "cmp_glue": "，标点接回上一行 {0} 处",
        "cmp_wrap_skip": "（{0} 段过长未合并）",
        "cmp_hint_lone": "；另有 {0} 处标点独占一行，勾选「标点单独占一行」可修",
        "cmp_hint_wrap": "；另有 {0} 段疑似句中硬断，勾选「合并句中断行」可合并",
        # 页3 分章
        "re_label": "章节正则（留空使用内置中文规则库）：",
        "b_try": "试分章节",
        "b_try_all": "试分全部选中",
        "lab_chap_pick": "试分书籍：",
        "chap_pick_hint": "选单本试分；「试分全部选中」处理①书库勾选的全部书",
        "chap_hint": "内置可识别：第1章 / 第一百二十三章 / 卷三 / Chapter 5 / 序章 / 楔子 / 番外 / 后记；"
                     "填写自定义正则后将只使用自定义规则。不会写？点右边「常用写法」挑一条。",
        # 「常用写法」窗口
        "re_help": "常用写法",
        "re_help_title": "自定义章节正则 · 常用写法",
        "re_help_intro": (
            "什么时候要填：内置只认「第X章/节/回」「卷X」「序章/楔子/尾声/番外」。如果这本书的标题是"
            "「第一折」「01」「卷一 第3回」这类写法，内置认不出，整本就会被当成一章。\n\n"
            "两个框的区别：上面那格对所有书生效；下面那格只对「试分书籍」里选中的那本生效，优先用它。"
            "只要填了自定义正则，内置规则库就不再参与——所以规则要把这本书的每种标题写法都盖住。\n\n"
            "判定方式：只看行首；行长不超过 50 字、且不以「。」结尾的行才算标题；命中的整行原文就是章节标题。\n\n"
            "怎么用：下面按「书的写法」挑一条 → 点「填入」→ 回分章页点「试分章节」看结果，"
            "章节数不对就换一条，或者照着改字符集。"),
        "re_tpl_col": "书的写法",
        "re_tpl_re": "填这条正则",
        "re_fill_global": "填入上面的全局正则",
        "re_fill_book": "填入本书专用规则",
        "re_no_book": "先在「试分书籍」里选一本书，再填本书专用规则。",
        "re_close": "关闭",
        "col_chap_title": "章节标题",
        "col_c_book": "书名", "col_c_chaps": "章节",
        "col_chap_check": "校验",
        "chap_ck_bad": " · 校验异常 {0} 处",
        "chap_ck_books": " · 校验异常 {0} 本",
        "chap_tree": " · 章节树 {0} 级",
        "chap_ck_lv": "第{0}级",
        "b_chap_tree": "导出章节树",
        "tr_book": "书籍：{0}",
        "tr_src": "源文件：{0}",
        "tr_split": "切分：{0} 章 · 正文 {1} 字 · 章节树 {2} 级",
        "tr_check": "校验：{0}",
        "tree_suffix": "_章节树",
        "d_export_ok": "导出成功",
        "d_export_ok_msg": "章节树已导出到：\n{0}",
        "d_export_fail": "导出失败",
        "d_tree_outdir": "未设置输出目录",
        "d_tree_outdir_msg": "请先到「导出分发」页选择输出目录，再导出章节树。",
        "log_tree_export": "已导出章节树：{0}",
        # 分章列表右键：删章只记在本书的删除清单里，源文件不动
        "m_chap_del": "从目录删除该章节",
        "m_chap_del_undo": "恢复已删除的章节",
        "d_chap_del": "删除章节",
        "d_chap_del_msg": "确定把「{1}」从《{0}》的目录里去掉吗？\n\n"
                          "这一章的标题和正文会并到上一章正文末尾"
                          "（它是第一章时并到下一章开头），正文不会丢失；"
                          "源文件也不改动，右键菜单「恢复已删除的章节」可随时撤销。",
        "d_chap_del_last": "全书只剩这一条目录了：删掉就没有章节承载正文了。\n"
                           "要合并正文请先改分章规则或重新扫描。",
        "log_chap_del": "已从目录去掉「{0}」，正文并入相邻章，本书剩余 {1} 章",
        "log_chap_del_undo": "已恢复《{0}》被删除的 {1} 章",
        "log_chap_del_reset": "分章规则已变更，之前的删章记录已清空（章节列表按新规则重排）",
        "chap_del_sum": " · 已从目录去掉 {0} 章",
        "chap_res": "点「试分章节」查看结果",
        "chap_all_done": "试分 {0} 本：共 {1} 章，异常 {2} 本（见日志）",
        "chap_dbl_hint": "　双击任意一行进入该书单本试分",
        # 双击某一章 → 逐行正文窗口（只渲染目标章附近的若干行，滚动续载）
        "chap_win_title": "正文预览 · {0}",
        "chap_win_meta": "{0} · 第 {1}/{2} 章 · 全书 {3} 行",
        "chap_win_loaded": "已载入第 {0}–{1} 行 / 共 {2} 行",
        # 预览窗口底栏：选中一行后才能复制/建章
        "chap_win_copy": "复制",
        "chap_win_new": "创建章节",
        "chap_win_copied": "已复制",
        "chap_new_title": "创建章节",
        "chap_new_hint": "章节标题",
        "chap_new_empty": "章节标题不能为空。",
        "log_chap_add": "已在《{0}》第 {1} 行创建章节「{2}」，本书现有 {3} 章",
        "chap_read_hint": "　双击任意一章查看正文",
        "chap_sum": "《{0}》共切出 {1} 章，正文合计 {2} 字",
        "prog_chap": "试分中 {0}/{1}：《{2}》",
        "st_chap_done": "试分完成：{0} 本成功 · 共 {1} 章 · 异常 {2} 本",
        # 页4 导出
        "grp_where": "清洗结果的去向",
        "r_new": "输出到新目录（原文件不动，推荐）",
        "r_inplace": "原地覆盖（先备份为 .bak）",
        "r_none": "仅导出，不保存整理后的 TXT",
        "grp_fmt": "导出格式（可多选）",
        "f_epub": "EPUB（带目录，推荐）",
        "f_merge": "合并 TXT（整本一个文件）",
        "f_split": "分章 TXT（一章一个文件）",
        # 「文件名」下拉框：除「保持原样」外，选项都映射成一个 book/author 模板
        "f_name": "文件名",
        "name_keep": "保持原样",
        "name_author_title": "作者名 - 书名",
        "name_bracket": "[作者名] 书名",
        "name_book_author": "《书名》作者：作者名",
        "name_custom": "自定义格式",
        "name_pat_book_author": "《book》作者：author",
        "name_custom_title": "自定义文件名格式",
        "name_custom_hint": "用 book 代表书名、author 代表作者名，例如：《book》author\n"
                            "格式必须包含 book 占位符，且不能出现 \\ / : * ? \" < > |\n"
                            "这些文件名非法字符。",
        "name_custom_bad": "格式里必须包含 book 占位符。",
        "name_custom_bad_char": "文件名里不能使用这些字符：{0}",
        "name_custom_demo": "《book》author",
        "name_fmt_label": "格式模板",
        "name_preview": "预览：{0}",
        "name_preview_title": "示例书名",
        "name_preview_author": "示例作者",
        "f_theme": "版面主题",
        "theme_pick": "选择版面主题",
        "theme_pick_hint": "点击右侧缩略图切换左侧预览；"
                           "确定后用于导出 EPUB。",
        "theme_rendering": "正在渲染预览…",
        "theme_fail": "无法渲染预览：{0}",
        "theme_no_img": "无预览图",
        "theme_img_bad": "预览图打不开",
        "theme_stale": "预览图待更新",
        "theme_vp_w": "宽", "theme_vp_h": "高", "theme_vp_apply": "应用",
        "theme_import": "导入自定义CSS", "theme_custom": "自定义CSS",
        "theme_custom_pick": "选择自定义 CSS 文件",
        "theme_custom_bad": "这个 CSS 读不出来：{0}",
        "theme_all_files": "所有文件",
        "theme_need_browser": "预览需要浏览器\n请安装 Chrome 或 Edge 后重试",
        "theme_no_browser_title": "缺少可用的浏览器",
        "theme_no_browser": "渲染主题预览需要本机安装 Chrome / Edge 等 "
                            "Chromium 内核的浏览器。\n\n"
                            "请安装其中一个后重新打开这个窗口。\n"
                            "若浏览器装在别处，可设置环境变量\n"
                            "HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP=1\n"
                            "HTML2IMAGE_CHROME_EXE=<浏览器完整路径>",
        "theme_none": "没有在 styles 下找到任何 .css 主题文件。",
        "cov_none": "无封面",
        # 封面设置窗口：逐本设置导出封面（右键菜单换图）
        "cover_btn": "封面",
        "cover_btn_n": "已设置 {0} 本",
        "cover_pick": "设置导出封面",
        "cover_pick_hint": "右键封面：选择本地图片 / 下载网络封面；"
                           "确定后按这里的封面导出 EPUB。",
        "cover_pick_img": "选择封面图片",
        "cover_dl": "下载网络封面",
        # 内置封面：底栏下拉框统一换风格，右键给单本换
        "cover_default": "默认封面",
        "cover_new_default": "更换默认封面",
        "cover_style_all": "内置封面已统一为「{0}」",
        "cover_style_one": "内置封面已换成「{0}」",
        "cover_url_title": "下载网络封面",
        "cover_url_hint": "图片链接",
        "cover_url_bad": "请先填入图片链接。",
        "cover_dl_wait": "正在下载封面…",
        "cover_dl_ok": "封面已保存到：{0}",
        "cover_dl_fail": "封面下载失败：链接不是图片，或者打不开。",
        "cover_pick_fail": "这张图片读不出来，换一张试试。",
        "cover_preparing": "正在准备封面…",
        "cover_img_bad": "封面图打不开",
        "cover_img_filter": "图片文件",
        "cover_no_books": "没有已勾选的书籍",
        "cover_no_books_msg": "请先在书库中勾选要导出的书，再设置封面。",
        "log_cover_set": "封面设置已更新：{0} 本",
        "f_imgdl": "下载插图链接",
        "f_summary": "生成清洗内容汇总（按书籍分类，含原文行号）",
        "grp_out": "输出目录",
        "b_go": "开始处理",
        "out_note": "处理期间请勿关闭窗口。大批量任务建议先选少量书试跑。",
        "out_suffix": "_卷帙整理",
        # 日志 / 状态
        "grp_log": "运行日志", "st_ready": "就绪", "stopping": "正在停止…",
        "log_scan_start": "开始扫描：{0}",
        "log_found": "发现 {0} 个文本文件，开始读取…",
        "log_skip": "  跳过 {0}（{1}）",
        "prog_scan": "扫描中 {0}/{1}",
        "log_idx_load": "已从索引载入 {0} 本（{1}）{2}",
        "log_idx_stale": "，{0} 本已失效建议重新扫描",
        "log_idx_missing": "提示：索引中有 {0} 个文件已不存在，建议点「重新扫描」。",
        "st_scan_done": "扫描完成：{0} / {1} 本",
        "log_scan_done": "扫描完成，共 {0} 本。{1}",
        "log_stopped": "（已停止）",
        "log_run_done": "处理完成：成功 {0} 本，失败 {1} 本",
        "st_run_done": "处理完成：成功 {0} 本，失败 {1} 本",
        "prog_run": "处理中 {0}/{1}：{2}",
        "prog_done": "处理完成",
        "log_per_book": "[{0}/{1}] {2}：{3} 章，清洗删除 {4} 行",
        "log_book_fail": "[{0}/{1}] {2} 失败：{3}",
        "log_img_prog": "  插图下载中《{0}》：{1}/{2}",
        "log_img_prefetch": "  插图链接：检查 {0} 条，认出 {1} 张",
        "log_img_save": "  插图已保存 {0} 张 → {1}",
        "log_img_skip": "  另有 {0} 条链接不是图片或打不开，已跳过",
        "log_img_fail": "  插图下载失败：{0}",
        "log_summary_ok": "清洗内容汇总已写入 {0}（{1} 本 · {2} 条 · 删除空行 {3} 行）",
        "log_summary_fail": "清洗内容汇总写入失败：{0}",
        "log_summary_noout": "未设置输出目录，已跳过清洗内容汇总",
        "sum_note_snapshot": "沿用清洗页的快照，没有逐条明细（重新批量清洗后再处理即可记录）",
        "sum_note_fail": "处理失败：{0}",
        "log_outdir_fail": "无法创建输出目录：{0}",
        "log_open_fail": "无法打开资源管理器：{0}",
        "log_file_fail": "无法打开文件：{0}",
        "log_csv_ok": "书单已导出：{0}",
        "log_dup_sel": "已选中 {0} 个重复文件，可在书库中取消保留项的勾选后清理。",
        "log_out_final": "原地覆盖",
        "log_chap_start": "开始批量试分：共 {0} 本 · 清洗规则 {1} 条 · 章节规则 {2}",
        "log_chap_builtin": "内置规则库",
        "log_chap_per_book": "[{0}/{1}]《{2}》切出 {3} 章，正文 {4} 字",
        "log_chap_book_fail": "[{0}/{1}]《{2}》试分失败：{3}",
        "log_chap_done": "批量试分完成：{0} 本成功 · {1} 本异常 · 共 {2} 章",
        "book_re": "本书规则", "book_re_clr": "改用全局",
        "book_re_on": "✔ 本书用专用规则", "book_re_hint": "留空 = 用上面的全局正则",
        # 对话框
        "d_info": "提示", "d_warn": "警告", "d_error": "错误", "d_confirm": "确认",
        "d_close": "关闭",
        "d_dir_invalid": "目录无效", "d_dir_invalid_msg": "请先选择一个存在的目录。",
        "d_no_sel": "未选择", "d_no_sel_msg": "请先在书库中勾选至少一本书。",
        "d_no_dup": "没有重复", "d_no_dup_msg": "当前书库中未发现内容完全相同的文件。",
        "d_no_out": "缺少输出目录", "d_no_out_msg": "请先选择输出目录。",
        "d_nothing": "无事可做",
        "d_nothing_msg": "你选择了「仅导出」却又没有勾选任何导出格式。",
        "d_confirm_ip": "确认原地覆盖",
        "d_confirm_ip_msg": "将把清洗后的内容写回 {0} 个原文件，每个原文件会先备份为 .bak。\n\n"
                            "此操作会改动你的原始文件，确定继续吗？",
        "d_re_bad": "正则无效", "d_re_bad_msg": "自定义章节正则无效，请检查语法。",
        "d_preview_fail": "预览失败", "d_chap_fail": "分章失败",
        "d_export_fail": "导出失败",
        # CSV
        "csv_hdr": "书名,作者,字数,编码,大小,相对路径",
        "csv_name": "书单.csv", "csv_type": "CSV 文件",
        # 关于 / 帮助
        "about_title": "关于 %s %s",
        "about_what": "本地文本整理工具：扫描 · 清洗 · 分章 · 导出\n"
                      "文件只在本机处理、不上传；仅在你勾选插图校验 / 下载插图时联网取图。",
        "about_repo": "GitHub 主页 / 查看最新版：\nhttps://github.com/podcatcher962/DeShelf/releases",
        "usage_title": "使用说明", "disclaimer_title": "免责声明",
        "help_text": HELP_ZH, "disclaimer_text": DISC_ZH,
        "about_win": "版权与许可",
        "about_sub": "本地处理 · 扫描 · 清洗 · 分章 · 导出 · 可选联网取图",
        "about_body": ABOUT_ZH,
        "b_copy_about": "复制说明全文", "b_copy_mit": "复制 MIT 全文",
        # 右键菜单
        "m_open_loc": "打开文件位置", "m_open_note": "用记事本打开",
        "m_copy_path": "复制完整路径",
        "m_remove_book": "从列表移除（不删文件）",
        "m_edit_title": "修改书名", "m_edit_author": "修改作者",
        "d_edit_title": "修改书名", "d_edit_author": "修改作者",
        "edit_hint_title": "确定后立即更新列表与索引；留空则显示文件名。",
        "edit_hint_author": "确定后立即更新列表与索引；留空表示作者未知。",
        "log_meta_saved": "  已更新{0}：{1}",
        "st_meta_saved": "已更新{0}：{1}",
        "meta_untitled": "（使用文件名）", "meta_no_author": "（未知）",
        "log_book_removed": "  已从列表移除：{0}",
        # 通用
        "unnamed": "未命名",
    },
    EN: {
        "w_title": "%s %s %s",
        "m_file": "File", "m_lib": "Library", "m_lang": "Language 语言", "m_help": "Help",
        "m_pick_dir": "Choose folder…", "m_rescan": "Rescan",
        "m_rescan_fresh": "Rescan (ignore cache)", "m_quit": "Exit",
        "m_sel_all": "Select all", "m_sel_none": "Select none", "m_invert": "Invert",
        "m_sel_dup": "Select duplicates only", "m_export_csv": "Export list as CSV",
        "m_usage": "User guide", "m_disclaimer": "Disclaimer", "m_about": "About",
        "lang_busy": "Busy",
        "lang_busy_msg": "Please wait for the current task to finish before switching language.",
        "lib_dir": "Library folder:", "browse": "Browse…", "scan": "Scan",
        "b_add_files": "Add files…", "d_pick_files": "Choose text files to add",
        "b_rescan": "Rescan",
        "flt_txt": "Text files", "flt_all": "All files",
        "st_add_files": "Added {0} file(s){1}",
        "log_add_files": "  Added {0} file(s); skipped {1} (duplicate or unreadable)",
        "log_root_fallback": "  No library folder set — using the file's folder: {0}",
        "log_add_skip_only": " ({0} skipped)",
        "stop": "Stop",
        "tab1": " 1 Scan Library ", "tab2": " 2 Batch Clean ",
        "tab3": " 3 Split Chapters ", "tab4": " 4 Export ",
        "lib_hint": "  Double-click a row to toggle; right-click to edit title/author or open the file",
        "lib_info": "{0} books · {1} selected",
        "lib_info_dup": " · {0} duplicated",
        "col_title": "Title", "col_author": "Author", "col_chars": "Chars",
        "col_enc": "Encoding", "col_chap": "Chap", "col_size": "Size", "col_rel": "Path",
        "grp_rules": "Cleaning rules ({0} · scrollable)", "b_all_rules": "Check all", "b_def_rules": "Reset",
        "rule_more": "▼ {0} more rule(s) below — scroll down",
        "b_imp_rules": "Import…", "b_exp_rules": "Export…", "b_edit_rules": "Custom…",
        "d_ok": "OK", "d_cancel": "Cancel",
        "custom_hint": "One rule per line: action||regex||note. drop = remove the whole line, cut = remove only the match; add i after the action to ignore case; start with # to disable.",
        "log_rules_loaded": "Loaded rule pack \"{2}\": {0} built-in, {1} custom",
        "log_rules_bad": "; skipped {0} invalid rules",
        "log_rules_saved": "Rules exported to {0}",
        "log_rules_edit": "Custom rules updated: {0}",
        "b_preview": "Preview",
        "b_clean_apply": "Apply to selected books",
        "d_rule_none": "No cleaning rule", "d_rule_none_msg": "Tick at least one cleaning rule first.",
        "prog_clean": "Cleaning {0}/{1}: {2}",
        "st_clean_done": "Cleaned {0} books · {1} lines removed",
        "log_clean_done": "Batch clean done: {0} books · {1} lines removed",
        "clean_hint": "  Dry-run on the first selected book: original left (removed parts in red), cleaned right",
        "col_pre": "Original", "col_post": "Cleaned",
        "cmp_var": "{0} lines removed, {1} → {2} chars",
        "cmp_var_cut": "{0} lines removed, {3} more only had a trailing URL trimmed, {1} → {2} chars",
        "cmp_jsdup": " ({0} of them were script duplicates)",
        "cmp_img": ", {0} illustration links kept",
        "cmp_merge": ", {0} line breaks joined",
        "cmp_glue": ", {0} punctuation marks pulled back up",
        "cmp_wrap_skip": " ({0} paragraphs left alone: too long)",
        "cmp_hint_lone": "; {0} more lines hold punctuation only \u2014 tick \u201cPunctuation alone on a line\u201d to fix",
        "cmp_hint_wrap": "; {0} more paragraphs look hard-wrapped \u2014 tick \u201cJoin mid-sentence line breaks\u201d to merge",
        "re_label": "Chapter regex (blank = built-in Chinese rules):",
        "b_try": "Try Split",
        "b_try_all": "Try Split (all selected)",
        "lab_chap_pick": "Book to split:",
        "chap_pick_hint": "Pick a book here; \"Try Split (all selected)\" acts on every book ticked in ①Library",
        "chap_hint": "Built-in patterns match 第1章 / 第一百二十三章 / 卷三 / Chapter 5 / "
                     "序章 / 楔子 / 番外 / 后记; a custom regex replaces the built-ins. "
                     "Need help? Press “Templates”.",
        "re_help": "Templates",
        "re_help_title": "Custom chapter regex · templates",
        "re_help_intro": (
            "When you need this: the built-ins only know 第X章/节/回, 卷X and 序章/楔子/尾声/番外. "
            "If the book uses 第一折 / 01 / 卷一 第3回 and so on, they miss it and the whole file "
            "becomes a single chapter.\n\n"
            "Two boxes: the upper one applies to every book; the lower one applies only to the book "
            "picked in “Book to split” and wins over the upper one. Once any custom regex is filled in, "
            "the built-in library is no longer used — so the pattern must cover every heading form.\n\n"
            "A line qualifies when it matches from its start, is at most 50 characters long and does not "
            "end with “。”; the whole line becomes the chapter title.\n\n"
            "How to use: pick a template below → press Fill → back on the chapter pane press "
            "“Try Split”; if the chapter count looks wrong, try another one or adjust the classes."),
        "re_tpl_col": "Book looks like",
        "re_tpl_re": "Use this regex",
        "re_fill_global": "Fill global regex",
        "re_fill_book": "Fill this book's rule",
        "re_no_book": "Pick a book under “Book to split” first, then fill the per-book rule.",
        "re_close": "Close",
        "col_chap_title": "Chapter Title",
        "col_c_book": "Book", "col_c_chaps": "Chapters",
        "col_chap_check": "Check",
        "chap_ck_bad": " · {0} check issue(s)",
        "chap_ck_books": " · {0} book(s) with issues",
        "chap_tree": " · {0}-level chapter tree",
        "chap_ck_lv": "Level {0}",
        "b_chap_tree": "Export tree",
        "tr_book": "Book: {0}",
        "tr_src": "Source: {0}",
        "tr_split": "Split: {0} chapters · {1} chars · chapter tree {2} level(s)",
        "tr_check": "Check: {0}",
        "tree_suffix": "_chapter_tree",
        "d_export_ok": "Exported",
        "d_export_ok_msg": "Chapter tree exported to:\n{0}",
        "d_export_fail": "Export failed",
        "d_tree_outdir": "No output folder",
        "d_tree_outdir_msg": "Please choose an output folder on the \u201cExport\u201d page first.",
        "log_tree_export": "Chapter tree exported: {0}",
        "m_chap_del": "Remove this chapter from TOC",
        "m_chap_del_undo": "Restore deleted chapters",
        "d_chap_del": "Delete chapter",
        "d_chap_del_msg": "Remove \u201c{1}\u201d from the TOC of \u201c{0}\u201d?\n\n"
                          "Its title and text are appended to the end of the previous chapter "
                          "(to the start of the next one when it is the first chapter), so no "
                          "text is lost. The source file is untouched \u2014 use \u201cRestore "
                          "deleted chapters\u201d in the right-click menu to undo.",
        "d_chap_del_last": "This is the only TOC entry left: removing it would leave no chapter "
                           "to carry the text.\nChange the chapter rule or rescan first.",
        "log_chap_del": "Removed \u201c{0}\u201d from the TOC (text merged into a neighbour), "
                        "{1} chapter(s) left",
        "log_chap_del_undo": "Restored {1} deleted chapter(s) of \u201c{0}\u201d",
        "log_chap_del_reset": "Chapter rule changed \u2014 previous chapter deletions were cleared "
                              "(the list is rebuilt with the new rule)",
        "chap_del_sum": " \u00b7 {0} removed from TOC",
        "chap_res": "Click \u201cTry Split\u201d to preview",
        "chap_all_done": "Tried {0} books: {1} chapters in total, {2} failed (see log)",
        "chap_dbl_hint": "  double-click a row to open that book",
        "chap_win_title": "Text preview \u00b7 {0}",
        "chap_win_meta": "{0} \u00b7 chapter {1}/{2} \u00b7 {3} lines in total",
        "chap_win_loaded": "Lines {0}\u2013{1} of {2} loaded",
        "chap_win_copy": "Copy",
        "chap_win_new": "New chapter",
        "chap_win_copied": "Copied",
        "chap_new_title": "Create chapter",
        "chap_new_hint": "Chapter title",
        "chap_new_empty": "The chapter title cannot be empty.",
        "log_chap_add": "Created chapter \u201c{2}\u201d at line {1} of \u201c{0}\u201d; "
                        "{3} chapter(s) now",
        "chap_read_hint": "  double-click a chapter to read its text",
        "chap_sum": "\u201c{0}\u201d: {1} chapters, {2} chars total",
        "prog_chap": "Splitting {0}/{1}: {2}",
        "st_chap_done": "Split done: {0} books · {1} chapters · {2} failed",
        "log_chap_start": "Batch split started: {0} books · {1} cleaning rules · chapter regex: {2}",
        "log_chap_builtin": "built-in rule set",
        "log_chap_per_book": "[{0}/{1}] {2}: {3} chapters, {4} chars",
        "log_chap_book_fail": "[{0}/{1}] {2} failed: {3}",
        "log_chap_done": "Batch split done: {0} books ok · {1} failed · {2} chapters in total",
        "book_re": "This book", "book_re_clr": "Use global",
        "book_re_on": "✔ Own rule for this book", "book_re_hint": "Empty = use the global regex above",
        "grp_where": "Where Cleaned Text Goes",
        "r_new": "Output to a new folder (originals untouched, recommended)",
        "r_inplace": "Overwrite in place (.bak backup first)",
        "r_none": "Export only — don't save cleaned TXT",
        "grp_fmt": "Export Formats (multi-select)",
        "f_epub": "EPUB (with TOC, recommended)",
        "f_merge": "Merged TXT (one file per book)",
        "f_split": "Per-chapter TXT (one file per chapter)",
        "f_name": "File name",
        "name_keep": "Keep as is",
        "name_author_title": "Author - Title",
        "name_bracket": "[Author] Title",
        "name_book_author": "《Title》by Author",
        "name_custom": "Custom format",
        "name_pat_book_author": "《book》by author",
        "name_custom_title": "Custom File Name Format",
        "name_custom_hint": "Use book for the title and author for the author, "
                            "e.g. 《book》by author\nThe format must contain the book "
                            "placeholder and must not use \\ / : * ? \" < > |\n"
                            "these illegal file-name characters.",
        "name_custom_bad": "The format must contain the book placeholder.",
        "name_custom_bad_char": "These characters cannot be used in a file name: {0}",
        "name_custom_demo": "《book》by author",
        "name_fmt_label": "Format template",
        "name_preview": "Preview: {0}",
        "name_preview_title": "Sample Title",
        "name_preview_author": "Sample Author",
        "f_theme": "Layout",
        "theme_pick": "Choose Layout Theme",
        "theme_pick_hint": "Click a thumbnail to preview it on the left; "
                           "the choice is used for EPUB export.",
        "theme_rendering": "Rendering preview…",
        "theme_fail": "Cannot render the preview: {0}",
        "theme_no_img": "No preview image",
        "theme_img_bad": "Preview image unreadable",
        "theme_stale": "preview out of date",
        "theme_vp_w": "W", "theme_vp_h": "H", "theme_vp_apply": "Apply",
        "theme_import": "Import custom CSS", "theme_custom": "Custom CSS",
        "theme_custom_pick": "Choose a custom CSS file",
        "theme_custom_bad": "This CSS can't be read: {0}",
        "theme_all_files": "All files",
        "theme_need_browser": "Preview needs a browser\n"
                              "install Chrome or Edge and retry",
        "theme_no_browser_title": "No browser found",
        "theme_no_browser": "Rendering theme previews needs a Chromium-based "
                            "browser (Chrome / Edge).\n\nInstall one and reopen "
                            "this window.\nIf it lives elsewhere, set\n"
                            "HTML2IMAGE_TOGGLE_ENV_VAR_LOOKUP=1\n"
                            "HTML2IMAGE_CHROME_EXE=<full path to the browser>",
        "theme_none": "No .css theme files found under styles.",
        "cov_none": "No cover",
        "cover_btn": "Cover",
        "cover_btn_n": "{0} cover(s) set",
        "cover_pick": "Set Export Covers",
        "cover_pick_hint": "Right-click a cover: choose a local image / download from URL; "
                           "EPUB export uses exactly these covers.",
        "cover_pick_img": "Choose cover image",
        "cover_dl": "Download cover from URL",
        "cover_default": "Default cover",
        "cover_new_default": "Change default cover",
        "cover_style_all": "Built-in covers set to \"{0}\"",
        "cover_style_one": "Built-in cover set to \"{0}\"",
        "cover_url_title": "Download Cover",
        "cover_url_hint": "Image URL",
        "cover_url_bad": "Enter an image URL first.",
        "cover_dl_wait": "Downloading cover…",
        "cover_dl_ok": "Cover saved to: {0}",
        "cover_dl_fail": "Download failed: the link is not an image, or cannot be opened.",
        "cover_pick_fail": "This image cannot be read - try another one.",
        "cover_preparing": "Preparing cover…",
        "cover_img_bad": "Cover image unreadable",
        "cover_img_filter": "Image files",
        "cover_no_books": "No books selected",
        "cover_no_books_msg": "Select the books to export in the library first.",
        "log_cover_set": "Covers updated: {0}",
        "f_imgdl": "Download illustration links",
        "f_summary": "Write a cleanup summary (by book, with original line numbers)",
        "grp_out": "Output Folder",
        "b_go": "Start",
        "out_note": "Keep the window open while processing. For large batches, try a few books first.",
        "out_suffix": "_DeShelf",
        "grp_log": "Log", "st_ready": "Ready", "stopping": "Stopping…",
        "log_scan_start": "Scanning: {0}",
        "log_found": "Found {0} text files, reading…",
        "log_skip": "  Skipped {0} ({1})",
        "prog_scan": "Scanning {0}/{1}",
        "log_idx_load": "Loaded {0} books from index ({1}){2}",
        "log_idx_stale": ", {0} stale — rescan advised",
        "log_idx_missing": "{0} files in the index no longer exist — click \u201cRescan\u201d.",
        "st_scan_done": "Scan done: {0}/{1}",
        "log_scan_done": "Scan finished: {0} books.{1}",
        "log_stopped": " (stopped)",
        "log_run_done": "Done: {0} ok, {1} failed",
        "st_run_done": "Done: {0} ok, {1} failed",
        "prog_run": "Processing {0}/{1}: {2}",
        "prog_done": "Done",
        "log_per_book": "[{0}/{1}] {2}: {3} chapters, {4} lines removed",
        "log_book_fail": "[{0}/{1}] {2} failed: {3}",
        "log_img_prog": "  Downloading illustrations for \"{0}\": {1}/{2}",
        "log_img_prefetch": "  Illustration links: {0} checked, {1} image(s) found",
        "log_img_save": "  {0} illustration(s) saved to {1}",
        "log_img_skip": "  {0} link(s) were not images or unreachable — skipped",
        "log_img_fail": "  Illustration download failed: {0}",
        "log_summary_ok": "Cleanup summary written to {0} ({1} book(s) · {2} record(s) · "
                          "{3} blank line(s) removed)",
        "log_summary_fail": "Cannot write the cleanup summary: {0}",
        "log_summary_noout": "No output folder set — cleanup summary skipped",
        "sum_note_snapshot": "reused the snapshot from the Batch Clean tab — no per-item detail "
                             "(clean the books again to record it)",
        "sum_note_fail": "processing failed: {0}",
        "log_outdir_fail": "Cannot create output folder: {0}",
        "log_open_fail": "Cannot open Explorer: {0}",
        "log_file_fail": "Cannot open file: {0}",
        "log_csv_ok": "List exported: {0}",
        "log_dup_sel": "Selected {0} duplicates — uncheck the copies you keep, then process.",
        "log_out_final": "overwritten in place",
        "d_info": "Info", "d_warn": "Warning", "d_error": "Error", "d_confirm": "Confirm",
        "d_close": "Close",
        "d_dir_invalid": "Invalid Folder", "d_dir_invalid_msg": "Please choose an existing folder.",
        "d_no_sel": "Nothing Selected", "d_no_sel_msg": "Select at least one book in the library first.",
        "d_no_dup": "No Duplicates",
        "d_no_dup_msg": "No content-identical files found in the library.",
        "d_no_out": "Output Folder Needed", "d_no_out_msg": "Please choose an output folder.",
        "d_nothing": "Nothing to Do",
        "d_nothing_msg": "You picked \u201cExport only\u201d but selected no format.",
        "d_confirm_ip": "Confirm Overwrite",
        "d_confirm_ip_msg": "Cleaned text will be written back to {0} original files, each backed "
                            "up as .bak first.\n\nThis modifies your original files. Continue?",
        "d_re_bad": "Invalid Regex", "d_re_bad_msg": "Custom chapter regex is invalid — check the syntax.",
        "d_preview_fail": "Preview Failed", "d_chap_fail": "Split Failed",
        "d_export_fail": "Export Failed",
        "csv_hdr": "Title,Author,Chars,Encoding,Size,Path",
        "csv_name": "library_list.csv", "csv_type": "CSV files",
        "about_title": "About %s %s",
        "about_what": "A local TXT organizer: scan · clean · split · export\n"
                      "Files never leave your computer; the network is used only "
                      "for opt-in illustration check / download.",
        "about_repo": "GitHub homepage / latest release:\nhttps://github.com/podcatcher962/DeShelf/releases",
        "usage_title": "User Guide", "disclaimer_title": "Disclaimer",
        "help_text": HELP_EN, "disclaimer_text": DISC_EN,
        "about_win": "Copyright & License",
        "about_sub": "Local by default · scan · clean · split · export · opt-in image download",
        "about_body": ABOUT_EN,
        "b_copy_about": "Copy the full text", "b_copy_mit": "Copy the MIT text",
        "m_open_loc": "Open file location", "m_open_note": "Open with Notepad",
        "m_copy_path": "Copy full path",
        "m_remove_book": "Remove from list (file kept)",
        "m_edit_title": "Edit title", "m_edit_author": "Edit author",
        "d_edit_title": "Edit title", "d_edit_author": "Edit author",
        "edit_hint_title": "Saved to the list and index on OK; leave blank to show the file name.",
        "edit_hint_author": "Saved to the list and index on OK; leave blank if unknown.",
        "log_meta_saved": "  {0} updated: {1}",
        "st_meta_saved": "{0} updated: {1}",
        "meta_untitled": "(file name)", "meta_no_author": "(unknown)",
        "log_book_removed": "  Removed from list: {0}",
        "unnamed": "Untitled",
    },
}


def _sys_lang():
    """按 Windows 界面语言判断默认界面语言（不抛异常）。"""
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return ZH if (lid & 0x3FF) == 0x04 else EN  # 0x0804/0x0404/0x0004 = Chinese
    except Exception:
        return ZH


def pick_lang():
    """优先级：环境变量 JUANZHI_LANG > 配置文件 lang > 系统语言。"""
    env = os.environ.get("JUANZHI_LANG")
    if env in (ZH, EN):
        return env
    cfg = jzcore.load_config()
    if cfg.get("lang") in (ZH, EN):
        return cfg["lang"]
    return _sys_lang()


def safe_name(s, maxlen=60, fallback="未命名"):
    s = (s or "").strip()
    s = "".join(c for c in s if c not in '\\/:*?"<>|\r\n\t')
    s = s.strip(" .")
    return (s or fallback)[:maxlen]


def _short_num(v):
    """保留一位小数；整数不显示 .0（2.0万 → 2万）。"""
    s = "%.1f" % v
    return s[:-2] if s.endswith(".0") else s


def fmt_count(n, lang=ZH):
    """书库「字数」列的人读写法。

    中文按「万 / 亿」计（214.7万、1.2亿，列头已写明「字数」，不再重复「字」），
    英文按 K / M 缩写（2.1M）；阈值以下保留千位分隔（9,999），免得短数字被
    缩写出 0.5万 这种更差精度的写法。
    """
    if n is None:
        return "-"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n < 0:
        return "-"
    if lang == ZH:
        if n >= 99995000:
            # 9999.5 万往上四舍五入会顶到 10000 万，此时按「亿」写更好读
            return _short_num(n / 100000000.0) + "亿"
        if n >= 10000:
            return _short_num(n / 10000.0) + "万"
    else:
        if n >= 1000000:
            return _short_num(n / 1000000.0) + "M"
        if n >= 1000:
            # 999,950 以上四舍五入会变成 1000.0K，直接进位成 1M 更好读
            if n >= 999950:
                return _short_num(n / 1000000.0) + "M"
            return _short_num(n / 1000.0) + "K"
    return "{:,}".format(n)


# ============================================================ DPI / 屏幕几何
_SCALE = 1.0  # 96 DPI 逻辑像素 → 当前 DPI 物理像素的倍率（125% = 1.25）


def px(v):
    """96 DPI 下的逻辑像素 → 当前 DPI 下的物理像素。

    界面里所有写死的像素尺寸（窗口大小、行高、列宽、内边距、画布坐标）
    都必须经过这里换算，否则开启系统缩放后只有字号变大、布局不变。
    """
    return int(round(v * _SCALE))


def _wrap_label(e):
    """Label 的 wraplength 跟随自身宽度：窗口变窄时自动折行，而不是被切掉。

    用法：lab.bind("<Configure>", _wrap_label)；不需要时给 lab 一个
    wraplength 常量即可，别指望 pack 会自动换行。
    """
    e.widget.configure(wraplength=max(px(120), e.width - px(8)))


def _ellipsize(text, font, max_px):
    """把 text 截到 max_px 像素以内，放不下就用「…」收尾（始终单行）。

    按真实字体逐字量（font.measure），中英文混排、全角标点都不会算歪；
    二分找「连同省略号仍放得下」的最长前缀。max_px 连一个省略号都放不下时
    返回空串，免得挤出一个残缺的符号。
    """
    if not text or max_px <= 0:
        return ""
    try:
        if font.measure(text) <= max_px:
            return text
        dot = font.measure("…")
        if dot > max_px:
            return ""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid]) + dot <= max_px:
                lo = mid
            else:
                hi = mid - 1
    except tk.TclError:
        return text
    cut = text[:lo].rstrip()
    return (cut + "…") if cut else ""


def _set_dpi_aware():
    """声明进程 DPI 感知。**必须**在 tk.Tk() 之前调用。

    Tk 只在初始化时按当时的屏幕 DPI 计算一次 tk scaling 并缓存；
    若像旧代码那样在 Tk() 之后才 SetProcessDpiAwareness(1)，进程此时已
    变为 DPI 感知（窗口不再被系统位图放大），而 Tk 仍按 96 DPI 出图，
    于是 125%/150% 下文字与控件全部偏小。

    这里选 System DPI Aware 而非 Per-Monitor：Tk 8.6 不处理
    WM_DPICHANGED，声明 Per-Monitor 后把窗口拖到另一块不同 DPI 的屏幕
    会停留在旧的缩放倍率上，反而更糟。
    """
    if ctypes is None or os.name != "nt":
        return
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:  # S_OK
            return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _init_metrics(root):
    """读取真实 DPI，校准点字号（tk scaling）与像素尺寸（px）的倍率。

    点字号由 tk scaling 缩放、像素尺寸由 px() 缩放，两者用同一个 DPI
    基准，所以字体与控件保持设计稿的相对比例，不会互相挤压。
    """
    global _SCALE
    try:
        dpi = float(root.winfo_fpixels("1i"))
    except Exception:
        dpi = 0.0
    if not (60.0 <= dpi <= 480.0):  # 取值异常时退回 96 DPI
        dpi = 96.0
    # 只放大不缩小：84 DPI 之类的老屏 / 非 Windows 平台保持设计尺寸，
    # 免得为了「适配」反而把界面整体压小。
    _SCALE = max(1.0, dpi / 96.0)
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)  # 1 point = dpi/72 px
    except Exception:
        pass
    return _SCALE


def _work_area():
    """主显示器工作区（物理像素，已剔除任务栏）；失败返回 None。"""
    if ctypes is None or os.name != "nt":
        return None
    try:
        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        r = _RECT()
        # SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            if r.right > r.left and r.bottom > r.top:
                return r.right - r.left, r.bottom - r.top, r.left, r.top
    except Exception:
        pass
    return None


def _center_win(win, w, h):
    """把窗口严格居中到主显示器工作区（水平 + 垂直）。

    w/h 以 96 DPI 逻辑像素传入，内部按 DPR 换算并按工作区夹取：
    · 不再有硬编码的 -12 偏移，所以是真正的几何居中；
    · 用工作区而不是整屏，任务栏不会把视觉中心顶高。

    这里**只算几何、不处理任何事件**：旧版开头调用了 update_idletasks()，
    而 Tk 在第一次空闲处理时就会把顶层窗口映射到屏幕，于是窗口先以窗口
    管理器的默认位置出现在左上（屏幕中央偏上）再被 geometry() 挪到中间，
    用户就能看到一次明显的跳动。首次显示前要居中的窗口应由调用方先
    withdraw()，居中的几何落定后再 deiconify()（见 main()）。
    """
    W, H = px(w), px(h)
    area = _work_area()
    if area:
        aw, ah, ax, ay = area
    else:
        try:
            aw, ah, ax, ay = win.winfo_screenwidth(), win.winfo_screenheight(), 0, 0
        except Exception:
            return None
    W = max(1, min(W, aw - px(24)))  # 小屏 + 高缩放时别超出可见区域
    H = max(1, min(H, ah - px(24)))
    x = ax + (aw - W) // 2
    y = ay + (ah - H) // 2
    win.geometry("%dx%d+%d+%d" % (W, H, x, y))
    return W, H


# ============================================================ 版面主题选择
#
# 主题就是 styles 目录下的 .css。列表里的缩略图是现成的同名 .png，
# 打开窗口即出图、不用等浏览器；左侧大图才在选中时现渲，渲过就缓存，
# 再点同一套主题瞬间出图。

# 预览图比例：540:880，与同名预览图的默认尺寸一致
THEME_IMG_RATIO = 880.0 / 540.0
# 左栏（大图预览）占窗口宽度的比例，夹在下面两个值之间
THEME_LEFT_RATIO = 0.36
THEME_LEFT_MIN, THEME_LEFT_MAX = 280, 620
# 右栏固定两列：窗口拉宽时列宽（也就是缩略图）直接变大，不再分新列
THEME_COLS = 2
THEME_CARD_PAD = 10  # 卡片内部：图与卡片边框的留白（单边）
THEME_CARD_GAP = 8  # 网格单元格的最小间距（实际间距由 GRID_MARGIN 决定）
THEME_GRID_MARGIN = 14  # 列表与窗口边缘的留白（卡片之间是它的两倍）
THEME_PREVIEW_W, THEME_PREVIEW_H = 372, 478  # 左栏大图的初始尺寸


def _to_int(s):
    """宽松地把输入框里的文字转成正整数，转不了返回 0。"""
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return 0


def theme_label(t, lang):
    """@theme-name 是「中文 English」两段，按界面语言取对应的一半。"""
    if not t:
        return ""
    name = (t.get("name") or t.get("id") or "").strip()
    m = re.match(r"^([^\x00-\x7f]+)\s+([\x20-\x7e].*)$", name)
    if m:
        return m.group(2) if lang == EN else m.group(1)
    return name


def theme_title(t, S, lang):
    """界面上给用户看的主题名：自定义 CSS 没写 @theme-name 就用通用名。"""
    if not t:
        return S["theme_custom"]
    if t.get("custom") and not t.get("named"):
        return S["theme_custom"]
    return theme_label(t, lang) or S["theme_custom"]


def _load_source(path):
    """把预览图读成「可反复缩放」的源：Pillow 有就用它，没有就退回 tk 图。"""
    if not path:
        return None
    if _PILImage is not None:
        try:
            im = _PILImage.open(path)
            im.load()
            return ("pil", im.convert("RGB"))
        except Exception:
            pass
    try:
        return ("tk", tk.PhotoImage(file=path))
    except Exception:
        return None


def _scaled_photo(src, w, h, fast=False):
    """按 (w, h) 出一张 tk 图：Pillow 平滑缩放，没装就只能整数抽样。

    fast=True 时改用双线性（拖分隔条时每帧都要重算，没空做 LANCZOS）。
    """
    if src is None:
        return None
    kind, obj = src
    w, h = max(1, int(w)), max(1, int(h))
    if kind == "pil":
        filt = (getattr(_PILImage, "BILINEAR", 2) if fast
                else getattr(_PILImage, "LANCZOS", 1))
        try:
            im = obj.resize((w, h), filt)
            try:  # ImageTk 最快；被裁掉时退回 PNG 数据
                from PIL import ImageTk
                return ImageTk.PhotoImage(im)
            except Exception:
                buf = io.BytesIO()
                im.save(buf, format="PNG", compress_level=1)
                return tk.PhotoImage(
                    data=base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception:
            return None
    k = max(1, -(-obj.width() // w), -(-obj.height() // h))  # 向上取整
    return obj.subsample(k, k) if k > 1 else obj


def _cache_dir():
    """截图缓存放系统临时目录：同一套 CSS 只渲一次，再开窗口瞬间出图。"""
    d = os.path.join(tempfile.gettempdir(), "deshelf-theme-cache")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _cache_path(html, size):
    """缓存名 = 预览页 HTML + 尺寸的摘要：模板或 CSS 一变，旧图自动失效。"""
    key = "%dx%d|%s" % (size[0], size[1], html)
    name = hashlib.md5(key.encode("utf-8")).hexdigest()
    return os.path.join(_cache_dir(), name + ".png")


def _prune_cache(limit=160):
    """缓存无限长下去会占空间：文件太多就整体清空，重渲一次也不贵。"""
    d = _cache_dir()
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".png")]
    except OSError:
        return
    if len(files) <= limit:
        return
    for p in files:
        try:
            os.remove(p)
        except OSError:
            pass


# ============================================================ 导出封面
#
# 导出页不再给「封面策略」下拉框：点按钮开一个窗口，把本次要导出的书逐本列出来，
# 每本书的封面默认走 cover_for_book(auto)：用户挑过的图优先，其次是同名图片，
# 都没有就按内置风格现画（底栏「默认封面」下拉框统一换风格，右键「更换默认封面」
# 给单本换）。确定后整份封面交回主窗口，开始处理时按这份映射原样写进 epub。

COVER_THUMB_W, COVER_THUMB_H = 132, 184  # 网格里每本书的缩略图上限
COVER_CARD_PAD = 8  # 卡片内留白（单边）
COVER_GRID_GAP = 12  # 卡片之间 / 与窗口边缘的留白
COVER_PICKER_W, COVER_PICKER_H = 900, 720  # 窗口初始尺寸
COVER_URL_W = 560  # 网络封面输入框窗口宽度


def _join_blocks(*parts):
    """把几段正文（标题、前/后一章的正文）用空行接起来，去掉多余的首尾空行。

    「删除章节」只删目录条目：被删章的「标题+正文」就靠它并进上一章正文末尾
    （书开头被删则并到下一章开头），正文一个字都不丢。
    """
    return "\n\n".join(p.strip("\n") for p in parts if p and p.strip())


def _book_key(path):
    """封面映射的键：同一本书换个相对/绝对写法也能对上。"""
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return str(path or "")


def _manual_rec(line, title, orig, rows):
    """一条「用户手动创建章节」的索引记录（随书条目落盘，见 jzcore.MANUAL_KEYS）。"""
    try:
        line = int(line)
    except (TypeError, ValueError):
        line = 0
    try:
        rows = int(rows)
    except (TypeError, ValueError):
        rows = 0
    return {"line": max(0, line), "title": (title or "").strip(),
            "text": (orig or "").strip(), "rows": max(0, rows)}


def _chap_protect(adds):
    """手工章节标题行的原文（已 strip）：清洗规则不许删这几行。"""
    return [r.get("text") for r in (adds or ()) if r.get("text")]


def _remap_del(old, new, dels):
    """把删章下标从旧切分结果平移到新结果上（新建章节会让后面的章整体后移）。

    old / new 都是 [(标题, 正文, 起始行号)]。手工建章只会往列表里插条目，
    原有章的顺序与标题都不变，所以按标题顺序配对；不按行号配对是因为手工
    章节的标题行会被清洗规则特意保住，前后两次切分的行号可能整体差一行。
    配不上的（那一章正好被手工章节顶掉了）就丢掉这条删除记录。
    """
    pos, where = 0, {}
    for i, (t, _bd, _ln) in enumerate(old):
        for j in range(pos, len(new)):
            if new[j][0] == t:
                where[i] = j
                pos = j + 1
                break
    return sorted({where[i] for i in dels if i in where})


def _source_from_bytes(data, name="cover.jpg"):
    """把内存里的封面字节读成「可反复缩放」的源，交给 _fit_photo。"""
    if not data:
        return None
    if _PILImage is not None:
        try:
            im = _PILImage.open(io.BytesIO(data))
            im.load()
            return ("pil", im.convert("RGB"))
        except Exception:
            pass
    try:  # 没有 Pillow：落个临时文件让 tk 自己认（只认 PNG/GIF）
        path = os.path.join(_cache_dir(), "cover-view" + os.path.splitext(name)[1])
        with open(path, "wb") as f:
            f.write(data)
        return ("tk", tk.PhotoImage(file=path))
    except Exception:
        return None


def _fit_photo(src, w, h):
    """封面等比缩进 (w, h) 的框里、四周补白：书封比例不一，硬拉伸会变形。"""
    if src is None:
        return None
    w, h = max(1, int(w)), max(1, int(h))
    kind, obj = src
    if kind == "pil":
        try:
            im = obj.copy()
            im.thumbnail((w, h), getattr(_PILImage, "LANCZOS", 1))
            box = _PILImage.new("RGB", (w, h), "#FFFFFF")
            box.paste(im, ((w - im.size[0]) // 2, (h - im.size[1]) // 2))
            try:
                from PIL import ImageTk
                return ImageTk.PhotoImage(box)
            except Exception:
                buf = io.BytesIO()
                box.save(buf, format="PNG", compress_level=1)
                return tk.PhotoImage(
                    data=base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception:
            return None
    k = max(1, -(-obj.width() // w), -(-obj.height() // h))  # 向上取整
    return obj.subsample(k, k) if k > 1 else obj


class ThemePicker:
    """主题选择窗口：左侧大图预览，右侧网格列出全部主题的缩略图。

    右侧读同名的 .png（tools/gen_theme_previews.py 生成），窗口一开就是成品；
    固定两列、尺寸不写死：窗口拉宽，缩略图跟着变宽，左栏大图按可用空间等比放大。
    左侧大图才在选中时交给后台线程现渲（渲过就缓存），所以点开不假死，
    快速连点也只保留最后一次的结果。
    """

    def __init__(self, parent, themes, current, lang, S):
        self.themes = list(themes)  # 复制一份：导入自定义 CSS 会往里加
        self.lang = lang
        self.S = S
        self.result = None
        self.cur = current
        self._by_id = {t["id"]: t for t in themes}
        self._cards = {}
        self._src = {}  # id -> 可反复缩放的源图
        self._ph = {}  # id -> ((w, h), tk 图)，按当前尺寸缓存
        self._pv_path = ""  # 左侧大图的渲染结果
        self._pv_shown = None  # ((w, h), tk 图)
        self._pv_src = None  # 大图的解码缓存（拖动时反复缩放用）
        self._pv_src_path = ""
        self._pv_size = (px(THEME_PREVIEW_W), px(THEME_PREVIEW_H))
        self._grid_key = None
        self._img_key = None  # 缩略图当前是按哪个尺寸 + 画质贴的
        self._layout_job = None
        self._busy = False
        self._left_user_w = 0  # 用户拖过分隔条后左栏的宽度（0=按比例自动）
        self._drag = None  # 拖分隔条时的起点 (x_root, 左栏宽)
        self._grid_job = None  # 拖动停顿后跟右栏尺寸的定时器
        self._warned = False  # 没装浏览器的提示只弹一次
        self._jobs = queue.Queue()
        self._done = queue.Queue()
        self._seq = 0
        self._dead = False
        _prune_cache()
        self._build(parent)  # 缩略图在这一步直接读 .png，不等渲染
        # 配置里存的是自定义 CSS：把它也放进列表，方便直接沿用
        if jzcore.is_custom_theme(current):
            t = jzcore.load_theme(current)
            if t is not None:
                self._add_card(t)
        threading.Thread(target=self._worker, daemon=True).start()
        self._select(current)

    # -------------------------------------------------------- 界面
    def _build(self, parent):
        S = self.S
        win = self._win = tk.Toplevel(parent)
        win.title(S["theme_pick"])
        win.transient(parent)
        win.configure(bg=BG)
        win.resizable(True, True)
        win.minsize(px(760), px(520))
        win.protocol("WM_DELETE_WINDOW", self._cancel)
        win.bind("<Escape>", lambda _e: self._cancel())
        _center_win(win, 980, 720)

        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(10))
        ttk.Button(bar, text=S["d_ok"], style="Accent.TButton",
                   command=self._ok).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], style="Soft.TButton",
                   command=self._cancel).pack(side="right", padx=px(6))
        # 导入自定义 CSS：放在「取消」左边（side=right 是从右往左堆）
        ttk.Button(bar, text=S["theme_import"], style="Soft.TButton",
                   command=self.import_css).pack(side="right", padx=(px(6), px(14)))
        ttk.Label(bar, text=S["theme_pick_hint"], foreground=MUTED,
                  font=FONT_S).pack(side="left")

        body = ttk.Frame(win)
        body.pack(side="top", fill="both", expand=True)

        # ---- 左：选中主题的大图预览（宽高在 _layout_left 里按窗口算）----
        left = self._left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(px(12), px(8)), pady=px(8))
        left.pack_propagate(False)
        left.configure(width=px(THEME_PREVIEW_W + 20))
        box = self._pv_box = tk.Frame(left, width=px(THEME_PREVIEW_W),
                                      height=px(THEME_PREVIEW_H),
                                      bg="#FFFFFF", highlightthickness=1,
                                      highlightbackground=LINE, bd=0)
        box.pack_propagate(False)
        box.pack()
        self.pv_hint = tk.Label(box, text=S["theme_rendering"], bg="#FFFFFF",
                                fg=MUTED, font=FONT_S, justify="center")
        self.pv_hint.place(relx=.5, rely=.5, anchor="center")
        self.pv_img = tk.Label(box, bd=0, bg="#FFFFFF")

        # 预览视口：改宽高就换一种设备的排版结果（手机 / Kindle / 桌面…）
        self.vp_w_var = tk.StringVar()
        self.vp_h_var = tk.StringVar()
        self._vp = tuple(jzcore.THEME_PREVIEW_SIZE)
        self._vp_text()
        row = self._vp_row = ttk.Frame(left)
        row.pack(pady=(px(10), 0))  # 默认居中，跟上面的预览图对齐
        ttk.Label(row, text=S["theme_vp_w"], foreground=MUTED,
                  font=FONT_S).pack(side="left")
        ew = ttk.Entry(row, textvariable=self.vp_w_var, width=5,
                       justify="center")
        ew.pack(side="left", padx=(px(4), px(2)))
        ttk.Label(row, text="×", foreground=MUTED,
                  font=FONT_S).pack(side="left")
        eh = ttk.Entry(row, textvariable=self.vp_h_var, width=5,
                       justify="center")
        eh.pack(side="left", padx=(px(2), px(2)))
        ttk.Label(row, text="px", foreground=MUTED,
                  font=FONT_S).pack(side="left")
        ttk.Button(row, text=S["theme_vp_apply"], style="Soft.TButton",
                   command=self._apply_viewport).pack(side="left", padx=(px(6), 0))
        for e in (ew, eh):
            e.bind("<Return>", lambda _e: self._apply_viewport())

        # ---- 分隔条：可左右拖动，实时调整左右两栏的宽度比例 ----
        sp = self._split = tk.Frame(body, width=px(9), bg=BG,
                                    cursor="sb_h_double_arrow")
        sp.pack(side="left", fill="y")
        sp.pack_propagate(False)
        line = self._split_line = tk.Frame(sp, bg=LINE, cursor="sb_h_double_arrow")
        line.place(relx=.5, rely=.5, anchor="center", width=px(3),
                   relheight=0.96)
        for w in (sp, line):
            w.bind("<Button-1>", self._split_press)
            w.bind("<B1-Motion>", self._split_move)
            w.bind("<ButtonRelease-1>", self._split_release)
            w.bind("<Double-Button-1>", self._split_reset)
            w.bind("<Enter>", lambda _e: self._split_line.configure(bg=BLUE))
            w.bind("<Leave>", self._split_leave)

        # ---- 右：全部主题的缩略图网格（可滚动）----
        wrap = ttk.Frame(body)
        wrap.pack(side="left", fill="both", expand=True, padx=(px(8), px(12)),
                  pady=px(8))
        vsb = ttk.Scrollbar(wrap, orient="vertical")
        vsb.pack(side="right", fill="y")
        cv = self._cv = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0,
                                  yscrollincrement=px(18))
        vsb.configure(command=cv.yview)
        cv.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(cv)
        self._cv_win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=vsb.set)
        cv.bind("<Configure>", self._on_cv_resize)
        cv.bind("<MouseWheel>", self._wheel)
        # 两列等宽：卡片在其中居中，左右留白自然对称
        for c in range(THEME_COLS):
            inner.grid_columnconfigure(c, weight=1, uniform="theme")
        # 卡片之间的缝隙也要能滚：缝隙归属 inner，单独绑一次
        inner.bind("<MouseWheel>", self._wheel)
        inner.bind("<Configure>",
                   lambda _e: cv.configure(scrollregion=cv.bbox("all")))

        self._inner = inner
        for t in self.themes:
            self._cards[t["id"]] = self._make_card(inner, t)

        win.bind("<Configure>", self._schedule_layout)
        self._schedule_layout()

    def _add_card(self, t):
        """往列表里补一张卡（导入自定义 CSS 用）。"""
        if t["id"] not in self._by_id:
            self.themes.append(t)
            self._by_id[t["id"]] = t
        self._cards[t["id"]] = self._make_card(self._inner, t)
        self._grid_key = None
        self._img_key = None
        self._layout_now(False)

    def _make_card(self, inner, t):
        """一张主题卡：缩略图 + 名称 + 说明（尺寸稍后由 _relayout 统一设）。"""
        gap, pad = px(THEME_CARD_GAP), px(THEME_CARD_PAD)
        card = tk.Frame(inner, bg=CARD, highlightthickness=2,
                        highlightbackground=LINE, bd=0)
        # padx 只是下限（实际由列宽居中决定），pady 决定行距与上下留白
        card.grid(row=0, column=0, padx=gap, pady=px(THEME_GRID_MARGIN),
                  sticky="n")
        box = tk.Frame(card, bg="#FFFFFF", highlightthickness=1,
                       highlightbackground=LINE, bd=0,
                       width=px(160), height=px(260))
        box.pack_propagate(False)  # 尺寸由布局定，图片只往里缩/放
        box.pack(padx=pad, pady=(px(8), px(4)))
        img = tk.Label(box, bd=0, bg="#FFFFFF")
        hint = tk.Label(box, bg="#FFFFFF", fg=MUTED, font=FONT_S,
                        justify="center", wraplength=px(140))
        hint.place(relx=.5, rely=.5, anchor="center")
        name = tk.Label(card, text=theme_title(t, self.S, self.lang), bg=CARD,
                        fg=INK, font=FONT_B, anchor="w", justify="left",
                        wraplength=px(160))
        name.pack(fill="x", padx=pad)
        desc_lb = tk.Label(card, text=self._card_desc(t), bg=CARD, fg=MUTED,
                           font=FONT_S, anchor="w", justify="left",
                           wraplength=px(160))
        desc_lb.pack(fill="x", padx=pad, pady=(0, px(8)))
        self._bind_card(card, t["id"])
        return {"frame": card, "box": box, "img": img, "hint": hint,
                "name": name, "desc": desc_lb, "photo": None}

    def _card_desc(self, t):
        desc = t.get("desc") or ""
        if t.get("stale"):
            desc = (desc + "  ·  " if desc else "") + self.S["theme_stale"]
        if t.get("custom") and not desc:  # 自定义 CSS 没写说明：退一步显示文件名
            desc = os.path.basename(t.get("path") or "")
        return desc

    def _bind_card(self, w, tid):
        """卡片整块可点（连同里面的图片和文字），滚轮也照常滚。"""
        w.bind("<Button-1>", lambda _e, t=tid: self._select(t))
        w.bind("<MouseWheel>", self._wheel)
        try:
            for c in w.winfo_children():
                self._bind_card(c, tid)
        except tk.TclError:
            pass

    def _wheel(self, e):
        """滚轮：一格滚 3 个单位（触控板的小 delta 会按 1 个走）。"""
        try:
            first, last = self._cv.yview()
        except Exception:
            return
        if first <= 0.0 and last >= 1.0:  # 内容不满一屏：不拦滚轮
            return
        delta = getattr(e, "delta", 0) or 0
        step = max(1, int(abs(delta) / 40))
        self._cv.yview_scroll(-step if delta > 0 else step, "units")

    # -------------------------------------------------------- 随窗口重排
    def _on_cv_resize(self, e):
        self._cv.itemconfigure(self._cv_win, width=e.width)
        self._schedule_layout()

    def _schedule_layout(self, _e=None):
        """窗口拖动时 Configure 会连发很多次：等它停下来再算一次。"""
        if self._layout_job is not None:
            try:
                self._win.after_cancel(self._layout_job)
            except Exception:
                pass
            self._layout_job = None
        try:
            self._layout_job = self._win.after(120, self._relayout)
        except tk.TclError:
            pass

    def _relayout(self):
        self._layout_job = None
        if self._drag:  # 拖动期间由 _split_move 一帧帧负责
            return
        self._layout_now(False)

    def _layout_now(self, fast, images=True):
        """立刻重排一次。

        fast=True 用于拖分隔条：不等几何落定（差一帧的量测无所谓），图片走
        双线性、且由调用方抽帧；images=False 时连图都不重算，只挪框。
        """
        if self._busy or not self._alive():
            return
        self._busy = True
        try:
            self._layout_left()
            if not fast:
                self._win.update_idletasks()  # 几何落定后再量右栏宽度
            self._layout_grid(fast, images)
        except tk.TclError:
            pass
        finally:
            self._busy = False

    # -------------------------------------------------------- 分隔条拖动
    def _split_press(self, e):
        self._drag = (e.x_root, self._left.winfo_width())
        self._split_line.configure(bg=BLUE)

    def _split_move(self, e):
        """拖动中只挪分隔条和左栏大图：这一步很轻，能跟住鼠标。

        右侧十张卡片的尺寸留到「停一下」或松手时再跟——每帧重排十张大图
        会把拖动拖成幻灯片。
        """
        if not self._drag:
            return
        x0, w0 = self._drag
        self._left_user_w = max(px(200), w0 + (e.x_root - x0))
        if not self._busy:
            self._busy = True
            try:
                self._layout_left(True)
            except tk.TclError:
                pass
            finally:
                self._busy = False
        self._later_grid(160)

    def _later_grid(self, ms):
        """拖动停顿 ms 毫秒后把右栏跟上（连续拖动时会不断被推迟）。"""
        if self._grid_job:
            try:
                self._win.after_cancel(self._grid_job)
            except Exception:
                pass
            self._grid_job = None
        try:
            self._grid_job = self._win.after(ms, self._drag_grid)
        except tk.TclError:
            pass

    def _drag_grid(self):
        self._grid_job = None
        if self._drag:
            self._layout_now(True, True)

    def _split_release(self, _e=None):
        if not self._drag:
            return
        self._drag = None
        if self._grid_job:
            try:
                self._win.after_cancel(self._grid_job)
            except Exception:
                pass
            self._grid_job = None
        self._split_line.configure(bg=LINE)
        # 松手后按最终宽度重算一遍：大图、缩略图都回到 LANCZOS 画质
        self._pv_shown = None
        self._layout_now(False)

    def _split_reset(self, _e=None):
        """双击分隔条：回到按窗口比例自动分配的宽度。"""
        self._drag = None
        self._left_user_w = 0
        self._layout_now(False)

    def _split_leave(self, e):
        if self._drag:
            return
        # 指针进到中间那条线也会收到 Leave，此时不算真的离开
        try:
            x = self._win.winfo_pointerx() - self._split.winfo_rootx()
        except tk.TclError:
            x = -1
        if 0 <= x <= self._split.winfo_width():
            return
        self._split_line.configure(bg=LINE)

    def _layout_left(self, fast=False):
        """左栏宽度：拖过分隔条就用手动值，否则按窗口比例；大图按视口比例填充。"""
        win = self._win
        lo = px(200)
        hi = max(lo + px(120), win.winfo_width() - px(340))
        if self._left_user_w:
            lw = max(lo, min(hi, int(self._left_user_w)))
            self._left_user_w = lw
        else:
            lw = int(max(px(300), win.winfo_width()) * THEME_LEFT_RATIO)
            lw = max(px(THEME_LEFT_MIN), min(px(THEME_LEFT_MAX), lw))
        lh = self._left.winfo_height()
        if lh < px(160):  # 还没完成布局，先按窗口估
            lh = max(px(300), win.winfo_height() - px(120))
        row_h = self._vp_row.winfo_reqheight()
        avail_h = max(px(150), lh - row_h - px(16))  # 视口输入框 + 间距
        vw, vh = self._vp
        ratio = float(vh) / float(vw)
        pv_h = avail_h
        pv_w = int(pv_h / ratio)
        max_w = max(px(100), lw - px(8))
        if pv_w > max_w:  # 高度够了但宽度到顶，改由宽度定
            pv_w = max_w
            pv_h = int(pv_w * ratio)
        lw = max(lw, pv_w + px(10), self._vp_row.winfo_reqwidth())
        self._left.configure(width=lw)
        if (pv_w, pv_h) != self._pv_size:
            self._pv_size = (pv_w, pv_h)
            self._pv_box.configure(width=pv_w, height=pv_h)
        self._show_preview(fast)

    def _layout_grid(self, fast=False, images=True):
        """右栏固定两列：可用宽度变了，列宽（和缩略图）跟着一起变。"""
        cols = THEME_COLS
        # 两列等宽居中：两侧各留 m，两张卡中间自然就是 2m
        m = px(THEME_GRID_MARGIN)
        avail = self._cv.winfo_width() - 4 * m
        if avail < px(200):
            return
        card_w = avail // cols
        thumb_w = max(px(80), card_w - px(2 * THEME_CARD_PAD) - px(6))
        thumb_h = int(thumb_w * THEME_IMG_RATIO)
        key = (cols, thumb_w, thumb_h)
        if key != self._grid_key:
            self._grid_key = key
            for i, t in enumerate(self.themes):
                card = self._cards[t["id"]]
                card["frame"].grid_configure(row=i // cols, column=i % cols)
                card["box"].configure(width=thumb_w, height=thumb_h)
                card["name"].configure(wraplength=thumb_w)
                card["desc"].configure(wraplength=thumb_w)
        if not images:
            return
        if self._img_key == (key, fast):  # 这批尺寸 + 这个画质已经贴过了
            return
        self._img_key = (key, fast)
        self._fill_thumbs(fast)

    def _fill_thumbs(self, fast=False):
        """按当前尺寸把每张缩略图贴/换上去；读不到图就在框里写提示。"""
        _cols, w, h = self._grid_key
        for t in self.themes:
            card = self._cards[t["id"]]
            photo = self._photo(t, w, h, fast)
            if photo is not None:
                card["photo"] = photo
                card["hint"].place_forget()
                card["img"].configure(image=photo)
                card["img"].place(relx=.5, rely=.5, anchor="center")
            else:
                card["img"].place_forget()
                card["hint"].configure(
                    text=(self.S["theme_no_img"] if not t.get("preview")
                          else self.S["theme_img_bad"]))
                card["hint"].place(relx=.5, rely=.5, anchor="center")

    def _photo(self, t, w, h, fast=False):
        """按目标像素取缩略图；同一尺寸 + 同一画质只缩一次。"""
        got = self._ph.get(t["id"])
        if got and got[0] == (w, h, fast):
            return got[1]
        photo = _scaled_photo(self._source(t), w, h, fast)
        self._ph[t["id"]] = ((w, h, fast), photo)
        return photo

    def _source(self, t):
        """源图只解码一次，之后反复缩放都很快。"""
        tid = t["id"]
        if tid not in self._src:
            self._src[tid] = _load_source(t.get("preview") or "")
        return self._src[tid]

    # -------------------------------------------------------- 视口尺寸
    def _vp_text(self):
        """把当前视口写回输入框（也用于输错后回滚）。"""
        self.vp_w_var.set(str(self._vp[0]))
        self.vp_h_var.set(str(self._vp[1]))

    def _apply_viewport(self):
        """按输入框的宽高重新排版预览：换设备（手机 / Kindle / 桌面）就看一眼。"""
        w = _to_int(self.vp_w_var.get())
        h = _to_int(self.vp_h_var.get())
        if not w or not h:
            self._vp_text()  # 输错了就恢复成上一次的值
            return
        w = max(200, min(3000, w))
        h = max(200, min(3000, h))
        if (w, h) == self._vp:
            self._vp_text()
            return
        self._vp = (w, h)
        self._vp_text()
        self._schedule_layout()  # 比例变了，左栏也要重排
        self._select(self.cur)  # 按新视口重渲一张（有缓存就秒出）

    # -------------------------------------------------------- 导入自定义 CSS
    def import_css(self):
        """选一个外部 CSS 当主题：读到什么就用什么，渲完预览立刻生效。"""
        S = self.S
        path = filedialog.askopenfilename(
            parent=self._win, title=S["theme_custom_pick"],
            filetypes=[("CSS", "*.css"), (S["theme_all_files"], "*.*")])
        if not path:
            return
        css = jzcore.read_css(path)
        if css is None:
            messagebox.showerror(S["d_warn"], S["theme_custom_bad"].format(path),
                                 parent=self._win)
            return
        tid = jzcore.custom_theme_id(path)
        t = self._by_id.get(tid)
        if t is None:
            t = jzcore.parse_theme(css, tid)
            t["path"] = os.path.abspath(path)
            t["preview"] = ""
            t["stale"] = False
            t["custom"] = True
            self._add_card(t)
        else:  # 同一个文件又导了一次：按新内容刷新
            new = jzcore.parse_theme(css, tid)
            t["css"] = css
            t["name"] = new["name"]
            t["named"] = new["named"]
            t["desc"] = new["desc"]
            card = self._cards[tid]
            card["name"].configure(text=theme_title(t, S, self.lang))
            card["desc"].configure(text=self._card_desc(t))
            self._img_key = None
            self._ph.pop(tid, None)
            self._src.pop(tid, None)
        self._select(tid)

    # -------------------------------------------------------- 选择与渲染
    def _select(self, tid):
        if tid not in self._by_id:
            return
        t = self._by_id[tid]
        self.cur = tid
        self._seq += 1
        for k, card in self._cards.items():
            card["frame"].configure(highlightbackground=BLUE if k == tid else LINE)
        try:  # 标题跟着所选主题走
            self._win.title(theme_title(t, self.S, self.lang))
        except tk.TclError:
            pass
        self.pv_img.place_forget()
        self._pv_path = ""
        self._pv_shown = None
        self.pv_hint.configure(text=self.S["theme_rendering"])
        self.pv_hint.place(relx=.5, rely=.5, anchor="center")
        # 按当前视口现渲一张，显示时再缩放到左栏大小
        self._jobs.put((tid, t["css"], tuple(self._vp), self._seq))

    def _worker(self):
        """后台渲染线程：渲左侧大图；同一套 CSS 渲过就命中缓存，不启浏览器。"""
        hti = None
        while True:
            item = self._jobs.get()
            if item is None:  # 窗口已关
                break
            tid, css, size, seq = item
            if seq != self._seq:
                continue  # 已被后续选择顶替，别再浪费一次启动
            # 左侧大图用长正文：视口有多高都能填满，看得出版面节奏
            html = jzcore.theme_preview_html(css, size[0], full=True)
            path, err, nobrowser = None, "", False
            cached = _cache_path(html, size)
            try:
                if os.path.isfile(cached) and os.path.getsize(cached) > 0:
                    path = cached
                else:
                    if hti is None:
                        hti = jzcore.make_renderer(os.path.dirname(cached))
                    path = hti.screenshot(html_str=html,
                                          save_as=os.path.basename(cached),
                                          size=size)[0]
            except jzcore.NoBrowser:
                nobrowser = True  # 交给界面弹窗提示，不抛异常
            except Exception as e:
                err = str(e)
            self._done.put((tid, seq, path, err, nobrowser))

    def _pump(self):
        """主线程取渲染结果贴图；tk 控件只在这一侧碰。"""
        if not self._alive():
            return
        try:
            while True:
                tid, seq, path, err, nobrowser = self._done.get_nowait()
                if nobrowser:
                    self._warn_no_browser()
                # seq 也要对上：改视口时旧视口的图可能晚到，别把新的顶掉
                if tid == self.cur and seq == self._seq:
                    self._set_preview(path, err, nobrowser)
        except queue.Empty:
            pass
        try:
            self._win.after(80, self._pump)
        except tk.TclError:
            pass

    def _warn_no_browser(self):
        """只在第一次弹窗：没装浏览器时别每次点主题都弹一遍。"""
        if self._warned:
            return
        self._warned = True
        try:
            messagebox.showwarning(self.S["theme_no_browser_title"],
                                   self.S["theme_no_browser"],
                                   parent=self._win)
        except tk.TclError:
            pass

    def _set_preview(self, path, err, nobrowser=False):
        if not path:
            self.pv_hint.configure(
                text=(self.S["theme_need_browser"] if nobrowser
                      else self.S["theme_fail"].format(err or "")))
            return
        self._pv_path = path
        t = self._by_id.get(self.cur)
        if t is not None and t.get("custom") and t.get("preview") != path:
            # 自定义 CSS 没有预生成图：直接拿这张渲染结果当卡片缩略图
            t["preview"] = path
            self._src.pop(t["id"], None)
            self._ph.pop(t["id"], None)
            self._img_key = None
            self._layout_grid(False, True)
        self._pv_shown = None
        self._show_preview()

    def _show_preview(self, fast=False):
        """把渲染结果按左栏当前尺寸缩放后贴上去（尺寸没变就不重算）。"""
        if not self._pv_path:
            return
        size = self._pv_size
        if self._pv_shown and self._pv_shown[0] == size:
            return
        if self._pv_src_path != self._pv_path:  # 源图只解码一次，拖动时不必反复读盘
            self._pv_src = _load_source(self._pv_path)
            self._pv_src_path = self._pv_path
        photo = _scaled_photo(self._pv_src, size[0], size[1], fast)
        if photo is None:
            self.pv_hint.configure(text=self.S["theme_fail"].format(""))
            return
        self._pv_shown = (size, photo)
        self.pv_hint.place_forget()
        self.pv_img.configure(image=photo)
        self.pv_img.place(relx=.5, rely=.5, anchor="center")

    def _alive(self):
        if self._dead:
            return False
        try:
            return bool(self._win.winfo_exists())
        except tk.TclError:
            return False

    # -------------------------------------------------------- 结果
    def _ok(self):
        self.result = self.cur
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self._dead = True
        self._jobs.put(None)  # 渲染线程干完手上那张就退出
        try:
            self._win.destroy()
        except tk.TclError:
            pass

    def show(self):
        try:
            self._win.after(80, self._pump)
            self._win.grab_set()
            self._win.wait_window()
        except tk.TclError:
            pass
        finally:
            self._dead = True
            self._jobs.put(None)
        return self.result


class CoverPicker:
    """导出封面设置窗：网格列出本次要导出的书，右键逐本换封面。

    打开先逐本准备封面（后台线程算一张贴一张，几百本也不会把界面冻住）：
    用户挑过的图 / 下载来的图优先，其次是同名本地图，都没有就按内置风格现画。
    右键菜单三项：「选择封面图片」挑本地图，只把 prepare_cover_image 的结果
    留在内存里；「下载网络封面」填链接自动下载，转成 JPEG 后按书籍文件名存进
    导出目录；没有本地同名封面的书还多一项「更换默认封面」，收着全部内置
    风格，只改这一本。底栏「默认封面」下拉框则把所有内置封面的书统一换风格。
    确定后整份映射交回主窗口，导出 EPUB 时按这里看到的封面原样写进书里。
    """

    def __init__(self, parent, books, covers, outdir, lang, S,
                 style=None, pins=None):
        self.books = list(books)
        self.outdir = (outdir or "").strip()
        self.lang = lang
        self.S = S
        self.result = None
        self.covers = dict(covers or {})  # {书籍路径键: cover_for_book 元组}
        # 内置封面：全局默认风格 + 每本书画它时用的风格（重开窗口据此还原）
        self.style = (style if style in jzcore.cover_style_ids()
                      else jzcore.DEFAULT_COVER_STYLE)
        self.pins = dict(pins or {})  # {书籍键: 内置风格 id}
        self.result_style = self.style
        self.result_pins = dict(self.pins)
        self._style_by_name = {jzcore.cover_style_name(sid, lang): sid
                               for sid in jzcore.cover_style_ids()}
        self._origin = {}  # 序号 -> "local" / "builtin" / "user"
        self._gen = 0  # 批次号：换了风格就作废旧批次的结果
        self._cards = {}  # 序号 -> 卡片控件
        self._thumb = (px(COVER_THUMB_W), px(COVER_THUMB_H))
        self._card_w = self._thumb[0] + 2 * px(COVER_CARD_PAD)
        self._cols = 0
        self._tasks = queue.Queue()  # 待出封面的书：(批次, 序号, 强制风格)
        self._q = queue.Queue()  # 后台线程算好的封面
        self._dlq = queue.Queue()  # 后台线程下载回来的封面
        self._dead = False
        self._build(parent)
        threading.Thread(target=self._worker, daemon=True).start()
        for i in range(len(self.books)):
            self._tasks.put((0, i, None))
        self._poll()

    # -------------------------------------------------------- 界面
    def _build(self, parent):
        S = self.S
        win = self._win = tk.Toplevel(parent)
        win.title(S["cover_pick"])
        win.transient(parent)
        win.configure(bg=BG)
        win.resizable(True, True)
        win.minsize(px(520), px(420))
        win.protocol("WM_DELETE_WINDOW", self._cancel)
        win.bind("<Escape>", lambda _e: self._cancel())
        _center_win(win, COVER_PICKER_W, COVER_PICKER_H)

        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(10))
        ttk.Button(bar, text=S["d_ok"], style="Accent.TButton",
                   command=self._ok).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], style="Soft.TButton",
                   command=self._cancel).pack(side="right", padx=px(6))
        # 取消左边：默认封面下拉框，一次改掉所有「没有本地封面」的书
        self.style_var = tk.StringVar(
            value=jzcore.cover_style_name(self.style, self.lang))
        self.cb_style = ttk.Combobox(
            bar, state="readonly", width=10, textvariable=self.style_var,
            values=[jzcore.cover_style_name(sid, self.lang)
                    for sid in jzcore.cover_style_ids()])
        self.cb_style.pack(side="right", padx=(px(10), 0))
        self.cb_style.bind("<<ComboboxSelected>>", self._on_style_all)
        ttk.Label(bar, text=S["cover_default"]).pack(side="right")
        # 下载/读图的即时反馈：不弹窗也能看到结果（失败仍走警告框）
        self._status = ttk.Label(win, text="", foreground=MUTED, font=FONT_S)
        self._status.pack(side="bottom", fill="x", padx=px(12))
        # 操作提示放顶部并跟随窗口宽度折行：塞在底栏里，窗口一窄就被挤掉半句
        tip = ttk.Label(win, text=S["cover_pick_hint"], foreground=MUTED,
                        font=FONT_S, justify="left")
        tip.pack(side="top", fill="x", padx=px(12), pady=(px(8), 0))
        tip.bind("<Configure>", _wrap_label)

        wrap = ttk.Frame(win)
        wrap.pack(side="top", fill="both", expand=True,
                  padx=(px(12), px(4)), pady=(px(10), 0))
        vsb = ttk.Scrollbar(wrap, orient="vertical")
        vsb.pack(side="right", fill="y")
        cv = self._cv = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0,
                                  yscrollincrement=px(18))
        vsb.configure(command=cv.yview)
        cv.configure(yscrollcommand=vsb.set)
        cv.pack(side="left", fill="both", expand=True)
        inner = self._inner = ttk.Frame(cv)
        self._cv_win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.bind("<Configure>", self._on_cv_resize)
        cv.bind("<MouseWheel>", self._wheel)
        inner.bind("<MouseWheel>", self._wheel)
        inner.bind("<Configure>",
                   lambda _e: cv.configure(scrollregion=cv.bbox("all")))

        for i, b in enumerate(self.books):
            self._cards[i] = self._make_card(i, b)
        self._arrange()

    def _make_card(self, i, b):
        """一本书一张卡：封面在上，书名、作者依次往下（整块可右键）。"""
        S = self.S
        pad, gap = px(COVER_CARD_PAD), px(COVER_GRID_GAP)
        tw, th = self._thumb
        card = tk.Frame(self._inner, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE, bd=0)
        card.grid(row=0, column=0, padx=gap // 2, pady=gap // 2, sticky="n")
        box = tk.Frame(card, bg="#FFFFFF", bd=0, width=tw, height=th)
        box.pack_propagate(False)  # 尺寸固定，图片只往里缩
        box.pack(padx=pad, pady=(pad, px(4)))
        img = tk.Label(box, bd=0, bg="#FFFFFF")
        hint = tk.Label(box, bg="#FFFFFF", fg=MUTED, font=FONT_S,
                        text=S["cover_preparing"], justify="center",
                        wraplength=tw - px(10))
        hint.place(relx=.5, rely=.5, anchor="center")
        title = tk.Label(card, text=b.get("title") or b.get("name") or "",
                         bg=CARD, fg=INK, font=FONT_B, anchor="w",
                         justify="left", wraplength=tw)
        title.pack(fill="x", padx=pad)
        author = tk.Label(card, text=b.get("author") or "",
                          bg=CARD, fg=MUTED, font=FONT_S, anchor="w",
                          justify="left", wraplength=tw)
        author.pack(fill="x", padx=pad, pady=(0, pad))
        for w in (card, box, img, hint, title, author):
            w.bind("<Button-3>", lambda e, k=i: self._menu(e, k))
            w.bind("<MouseWheel>", self._wheel)
        return {"frame": card, "box": box, "img": img, "hint": hint,
                "title": title, "author": author, "photo": None}

    def _menu(self, e, i):
        """右键菜单：换成本地图片、从网络下载，或（没有本地封面时）换内置风格。"""
        S = self.S
        m = tk.Menu(self._win, tearoff=0)
        m.add_command(label=S["cover_pick_img"],
                      command=lambda: self.pick_image(i))
        m.add_command(label=S["cover_dl"],
                      command=lambda: self.download(i))
        if self._can_set_default(i):  # 有同名本地图的书不给这一项
            sub = tk.Menu(m, tearoff=0)
            for sid in jzcore.cover_style_ids():
                sub.add_command(label=jzcore.cover_style_name(sid, self.lang),
                                command=lambda s=sid, k=i: self.set_default(k, s))
            m.add_cascade(label=S["cover_new_default"], menu=sub)
        try:
            m.tk_popup(e.x_root, e.y_root)
        except tk.TclError:
            pass

    # -------------------------------------------------------- 自动封面
    def _worker(self):
        """后台线程：按任务队列逐本出封面（打开时排一轮，换风格再排一轮）。"""
        while not self._dead:
            try:
                gen, i, style = self._tasks.get(timeout=0.1)
            except queue.Empty:
                continue
            if self._dead:
                return
            if gen < self._gen:  # 已被后来的「统一换风格」作废
                continue
            self._q.put((gen, i, self._prepare(i, style)))

    def _prepare(self, i, style):
        """算一本书这次该用的封面，返回 (封面元组, 来源, 内置风格)。

        来源：user=用户挑过/下载过，local=同名本地图，builtin=内置现画。
        风格换了（style 给了）就把内置封面按新风格重画，别的来源一律不动。
        """
        b = self.books[i]
        key = _book_key(b.get("path"))
        # 同名本地图永远最优先，与 cover_for_book 的 "auto" 一个口径
        found = None
        try:
            found = jzcore.find_cover_image(b.get("path") or "",
                                            b.get("title") or "", self.outdir)
        except Exception:
            found = None
        if found:
            try:
                got = jzcore.prepare_cover_image(found)
            except Exception:
                got = None
            if got:
                return got, "local", None
        pin = self.pins.get(key)
        if pin:
            if style is None:
                got = self.covers.get(key)
                if got is not None:  # 重开窗口：上次画好的直接用
                    return got, "builtin", pin
            return self._make_default(b, style or pin), "builtin", style or pin
        got = self.covers.get(key)
        if got is not None:
            return got, "user", None
        used = style or self.style
        return self._make_default(b, used), "builtin", used

    def _make_default(self, b, sid):
        """按内置风格画一本书的封面；画不出来（没装 Pillow）返回 None。"""
        try:
            return jzcore.make_cover(b.get("title") or "", b.get("author") or "",
                                     style=sid)
        except Exception:
            return None

    def _poll(self):
        """主线程收后台结果：封面一张张贴，下载结果落到卡片上。"""
        if self._dead:
            return
        try:
            while True:
                gen, i, res = self._q.get_nowait()
                if gen != self._gen:  # 旧批次：风格已经换过，丢弃
                    continue
                got, origin, pin = res
                self._origin[i] = origin
                key = _book_key(self.books[i].get("path"))
                if pin:
                    self.pins[key] = pin
                else:
                    self.pins.pop(key, None)
                self._show(i, got)
        except queue.Empty:
            pass
        try:
            while True:
                i, got, dest = self._dlq.get_nowait()
                if got:
                    self._set_user_cover(i, got)
                    self._status.configure(text=self.S["cover_dl_ok"].format(dest))
                else:
                    self._status.configure(text="")
                    messagebox.showwarning(self.S["d_warn"],
                                           self.S["cover_dl_fail"],
                                           parent=self._win)
        except queue.Empty:
            pass
        try:
            self._win.after(80, self._poll)
        except tk.TclError:
            pass

    def _show(self, i, got):
        """自动封面到位：有图就贴，没有（没装 Pillow 又找不到同名图）写「无封面」。"""
        card = self._cards.get(i)
        if card is None:
            return
        if got and got[0]:
            self._set_cover(i, got)
            return
        card["img"].place_forget()
        card["hint"].configure(text=self.S["cov_none"], fg=MUTED)
        card["hint"].place(relx=.5, rely=.5, anchor="center")

    def _set_user_cover(self, i, got):
        """用户自己挑的图（本地选图 / 网络下载）：以后统一换风格不再碰它。"""
        self.pins.pop(_book_key(self.books[i].get("path")), None)
        self._origin[i] = "user"
        self._set_cover(i, got)

    def _set_cover(self, i, got):
        """把一本书的封面换成新图：记进映射并刷新卡片缩略图。"""
        b = self.books[i]
        self.covers[_book_key(b.get("path"))] = got
        card = self._cards.get(i)
        if card is None:
            return
        photo = _fit_photo(_source_from_bytes(got[0], got[1]), *self._thumb)
        card["photo"] = photo  # 保住引用，否则 tk 图会被回收掉
        if photo is not None:
            card["hint"].place_forget()
            card["img"].configure(image=photo)
            card["img"].place(relx=.5, rely=.5, anchor="center")
        else:
            card["img"].place_forget()
            card["hint"].configure(text=self.S["cover_img_bad"], fg=RED)
            card["hint"].place(relx=.5, rely=.5, anchor="center")

    # -------------------------------------------------------- 内置封面
    def _can_set_default(self, i):
        """有同名本地图的书不参与「更换默认封面」：本地图永远优先。"""
        if i in self._origin:
            return self._origin[i] != "local"
        b = self.books[i]
        try:
            return not jzcore.find_cover_image(b.get("path") or "",
                                               b.get("title") or "",
                                               self.outdir)
        except Exception:
            return True

    def _on_style_all(self, _e=None):
        """底栏下拉框换风格：所有内置封面的书统一重画，用户挑的图不动。"""
        sid = self._style_by_name.get(self.style_var.get())
        if not sid or sid == self.style:
            return
        self.style = sid
        self.result_style = sid
        self._gen += 1  # 换风格了：旧批次的结果全部作废
        for i in range(len(self.books)):
            origin = self._origin.get(i)
            if origin == "builtin":
                self._tasks.put((self._gen, i, sid))  # 内置封面按新风格重画
            elif origin is None:
                self._tasks.put((self._gen, i, None))  # 还没出图：按新默认重算
        self._status.configure(text=self.S["cover_style_all"].format(
            jzcore.cover_style_name(sid, self.lang)))

    def set_default(self, i, sid):
        """右键给这一本换内置封面：只改这一本，不动其他书。"""
        if not self._can_set_default(i):
            return
        got = self._make_default(self.books[i], sid)
        if not got:
            return
        key = _book_key(self.books[i].get("path"))
        self.pins[key] = sid
        self._origin[i] = "builtin"
        self._set_cover(i, got)
        self._status.configure(text=self.S["cover_style_one"].format(
            jzcore.cover_style_name(sid, self.lang)))

    # -------------------------------------------------------- 换封面
    def pick_image(self, i):
        """从本地挑一张图：只转格式留在内存里，不往磁盘写文件。"""
        S = self.S
        # 只列常见图片格式：选到别的文件也读不出来，不如直接把范围框死
        path = filedialog.askopenfilename(
            parent=self._win, title=S["cover_pick_img"],
            filetypes=[(S["cover_img_filter"],
                        "*.jpg *.jpeg *.png *.gif *.webp *.bmp")])
        if not path:
            return
        got = jzcore.prepare_cover_image(path)
        if not got:
            messagebox.showwarning(S["d_warn"], S["cover_pick_fail"],
                                   parent=self._win)
            return
        self._set_user_cover(i, got)
        self._status.configure(text=os.path.basename(path))

    def download(self, i):
        """下载网络封面：先要链接，确认后下载、转 JPEG，按书籍文件名存进导出目录。"""
        S = self.S
        if not self.outdir:
            messagebox.showwarning(S["d_no_out"], S["d_no_out_msg"],
                                   parent=self._win)
            return
        url = self._ask_url()
        if not url:
            return
        dest = self._cover_dest(self.books[i])
        self._status.configure(text=S["cover_dl_wait"])
        threading.Thread(target=self._dl_worker, args=(i, url, dest),
                         daemon=True).start()

    def _dl_worker(self, i, url, dest):
        try:
            got = jzcore.download_cover_image(url, dest)
        except Exception:
            got = None
        self._dlq.put((i, got, dest))

    def _cover_dest(self, b):
        """导出目录下的封面文件：文件名取书籍文件名，统一 .jpg。"""
        stem = os.path.splitext(b.get("name") or os.path.basename(b.get("path") or ""))[0]
        stem = safe_name(stem, maxlen=80, fallback=self.S["unnamed"])
        return os.path.join(self.outdir, stem + ".jpg")

    def _ask_url(self):
        """图片链接输入框：确认返回链接，取消返回 None。"""
        S = self.S
        w = tk.Toplevel(self._win)
        w.title(S["cover_url_title"])
        w.transient(self._win)
        w.configure(bg=BG)
        w.resizable(False, False)
        got = {"url": None}
        bar = ttk.Frame(w)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(10))

        def _ok(_e=None):
            url = var.get().strip()
            if not url:
                messagebox.showwarning(S["d_warn"], S["cover_url_bad"], parent=w)
                return
            got["url"] = url
            w.destroy()

        ttk.Button(bar, text=S["d_ok"], style="Accent.TButton",
                   command=_ok).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], style="Soft.TButton",
                   command=w.destroy).pack(side="right", padx=px(6))
        row = ttk.Frame(w)
        row.pack(fill="x", padx=px(12), pady=px(12))
        ttk.Label(row, text=S["cover_url_hint"]).pack(side="left")
        var = tk.StringVar()
        e = ttk.Entry(row, textvariable=var, width=52)
        e.pack(side="left", fill="x", expand=True, padx=(px(6), 0))
        e.bind("<Return>", _ok)
        w.bind("<Escape>", lambda _e: w.destroy())
        e.focus_set()
        w.update_idletasks()
        _center_win(w, COVER_URL_W,
                    int(round(w.winfo_reqheight() / max(_SCALE, 0.01))))
        w.grab_set()
        self._win.wait_window(w)
        return got["url"]

    # -------------------------------------------------------- 随窗口重排
    def _on_cv_resize(self, e):
        try:
            self._cv.itemconfigure(self._cv_win, width=e.width)
        except tk.TclError:
            return
        self._arrange(e.width)

    def _arrange(self, width=None):
        """按可用宽度算几列；列数变了才重排一次网格。"""
        if self._dead:
            return
        try:
            w = width or self._cv.winfo_width()
        except tk.TclError:
            return
        gap = px(COVER_GRID_GAP)
        cols = max(1, int(max(1, w) // (self._card_w + gap)))
        if cols == self._cols:
            return
        old, self._cols = self._cols, cols
        for c in range(max(cols, old)):
            on = c < cols
            self._inner.grid_columnconfigure(
                c, weight=1 if on else 0, uniform="cover" if on else "")
        for i in sorted(self._cards):
            self._cards[i]["frame"].grid_configure(
                row=i // cols, column=i % cols)

    def _wheel(self, e):
        """滚轮：一格滚 3 个单位（触控板的小 delta 会按 1 个走）。"""
        try:
            first, last = self._cv.yview()
        except Exception:
            return
        if first <= 0.0 and last >= 1.0:  # 内容不满一屏：不拦滚轮
            return
        delta = getattr(e, "delta", 0) or 0
        step = max(1, int(abs(delta) / 40))
        self._cv.yview_scroll(-step if delta > 0 else step, "units")

    # -------------------------------------------------------- 结果
    def _ok(self):
        self.result = dict(self.covers)
        self.result_style = self.style
        self.result_pins = dict(self.pins)
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self._dead = True
        try:
            self._win.destroy()
        except tk.TclError:
            pass

    def show(self):
        try:
            self._win.grab_set()
            self._win.wait_window()
        except tk.TclError:
            pass
        finally:
            self._dead = True
        return self.result


# ============================================================ 分章正文预览
#
# 双击分章列表里的一章 → 开窗逐行看原文。窗口里的一行就是原文 splitlines()
# 的一行：不 strip、不折叠、不跳空行，行号也是原文行号，所以预览与源文本
# 严格逐行对应，空行/缩进/行尾空白/特殊空白字符全部原样保留。
# 整本书几十万字一次性塞进 Text 会卡，因此只放「双击那一章附近」的一段：
# 打开时先垫 CHAP_VIEW_BACK 行、往下铺 CHAP_VIEW_CHUNK 行，滚到顶/底再各补
# 一段，续载按原文行号算，不会错位。

CHAP_VIEW_CHUNK = 600   # 每次续载多少行
CHAP_VIEW_BACK = 120    # 打开时在目标章上方先垫多少行（能看到上一章结尾）
CHAP_VIEW_EDGE = 0.01   # 距顶/底多近就触发续载（占当前已载入内容的比例）


class ChapterReader:
    """逐行正文窗口：按需插入原文行、滚动续载，打开即定位到指定章。

    底栏「复制」「创建章节」两个按钮跟着行选中走：没选中任何一行时置灰，
    选中一行就能把这一行原文复制走，或者以它当标题行新建一章
    （on_create 由主界面提供，负责记账、落盘、重刷列表）。
    """

    def __init__(self, master, book, text, starts, target=0, S=None, on_create=None):
        self.S = S or TEXTS[ZH]
        self.book = book
        # 手动创建的章节标题就落在这一行（0 基原文行号），on_create 用它定位
        self.on_create = on_create
        # 原文逐行原样留着：不 strip、不合并空行，空行也各占一行、也有行号
        self.lines = text.splitlines() or [""]
        self.rows = len(self.lines)
        # 各章起始行（0 基原文行号）：用于定位，也用来认出「哪一行是章节标题」
        self.starts = [min(max(int(x), 0), self.rows - 1)
                       for x in (starts or [0])] or [0]
        self._title_rows = set(self.starts)  # 只染色，不改原文一个字
        self._lo = self._hi = 0     # 已插入控件的行范围 [lo, hi)
        self._loading = False
        self._closed = False        # 窗口已关：延迟续载的回调直接作废
        self._pending = None
        self._pos = (0.0, 1.0)
        self._target = 0            # 双击的那一章（布局完成后还要再居中一次）
        self._centered = False
        self._center_hooked = False
        self._build(master, book)
        self.jump_to(target)

    # -------------------------------------------------------- 界面
    def _build(self, master, book):
        S = self.S
        name = book.get("title") or os.path.splitext(book.get("name") or "")[0] or ""
        win = self.win = tk.Toplevel(master)
        win.title(S["chap_win_title"].format(name))
        win.transient(master)
        win.configure(bg=BG)
        win.minsize(px(560), px(420))
        _center_win(win, 920, 720)
        win.bind("<Escape>", lambda _e: self._close())

        # 底栏与提示先占位，正文区再吃剩余高度（否则会被挤没）
        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", padx=px(10), pady=px(10))
        ttk.Button(bar, text=S["re_close"], style="Soft.TButton",
                   command=self._close).pack(side="right")
        # 复制 / 创建章节：贴在「关闭」左边，未选中任何行时一律置灰
        self.btn_new = ttk.Button(bar, text=S["chap_win_new"], style="Accent.TButton",
                                  state="disabled", command=self._create)
        self.btn_new.pack(side="right", padx=(px(6), px(16)))
        self.btn_copy = ttk.Button(bar, text=S["chap_win_copy"], style="Soft.TButton",
                                   state="disabled", command=self._copy)
        self.btn_copy.pack(side="right", padx=(0, 0))
        self.stat = tk.Label(bar, text="", bg=BG, fg=MUTED, font=FONT_S, anchor="w")
        self.stat.pack(side="left")

        head = tk.Frame(win, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        head.pack(fill="x", padx=px(10), pady=(px(10), px(6)))
        tk.Label(head, text=name, bg=CARD, fg=INK, font=FONT_B, anchor="w",
                 padx=px(10), pady=px(3)).pack(fill="x")
        self.meta = tk.Label(head, text="", bg=CARD, fg=MUTED, font=FONT_S,
                             anchor="w", padx=px(10), pady=px(3))
        self.meta.pack(fill="x")

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=px(10), pady=(0, px(4)))
        # 正文一律同一套字体/行距，不做标题加粗、不加段间距：原文什么样就显示什么样
        self.txt = tk.Text(body, wrap="word", font=FONT, bg="#FFFFFF", fg=INK,
                           relief="flat", borderwidth=0, highlightthickness=1,
                           highlightbackground=LINE, highlightcolor=BLUE,
                           insertwidth=0, cursor="arrow", padx=px(8), pady=px(6),
                           height=10, width=40)
        # 行号列（灰、等宽）：折行后第二行起用 lmargin2 缩进，看起来仍是「一列」
        self.txt.tag_configure("num", foreground="#A8ADB4", font=MONO)
        self.txt.tag_configure("body", lmargin2=px(52))
        # 章节标题行只换字体/颜色做高亮：不加 spacing，段间距仍与原文一致
        self.txt.tag_configure("title", font=FONT_B, foreground=BLUE)
        # 行选中：只设底色。用内置 sel 标记会触发 Tk 反复重排文本（每点一次
        # 总高度都在涨、画面慢慢漂），自定义 tag 没有这个毛病
        self.txt.tag_configure("rowsel", background="#D8E4F2")
        self.txt.configure(state="disabled")
        self.txt.bind("<MouseWheel>", self._wheel)
        # 单击选中整行（列表式交互）：默认的字符级选区和插入光标在这里都别要；
        # 双击/三击也不让它退回「选词/选段」，否则整行选中会被默认绑定拆掉。
        # 按住左键拖动一律拦掉：Text 的 <B1-Motion> 会自己拉一条字符选区出来
        self.txt.bind("<Button-1>", self._click_row)
        self.txt.bind("<Double-1>", self._click_row)
        self.txt.bind("<Triple-1>", self._click_row)
        self.txt.bind("<B1-Motion>", self._no_drag)
        self.txt.bind("<Shift-Button-1>", self._no_drag)
        self.txt.bind("<Control-Button-1>", self._no_drag)
        self.sb = ttk.Scrollbar(body, orient="vertical", command=self._yview)
        self.txt.configure(yscrollcommand=self._on_scroll)
        self.sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

    # -------------------------------------------------------- 行数据
    def _walk(self, a, b):
        """[a, b) 行：按原文原样给出，一行一项（空行给空串，不跳过、不合并）。

        章节标题行多带一个 "title" 标签，只影响字体与颜色，文本还是原文那一行。
        """
        for r in range(max(0, a), min(b, self.rows)):
            yield r, self.lines[r], "title" if r in self._title_rows else "body"

    def _emit(self, a, b, prepend=False):
        """把 [a, b) 行写进控件：整段拼成一次 insert，减少 Tcl 往返（大块才不卡）。

        正文严格照原文插入：不 rstrip、不丢空行，行首缩进、行尾空白、制表符
        与全角空格都原样写进去；行号只是我们在行首加的列表栏，不改正文。
        """
        args = []
        for n, line, kind in self._walk(a, b):
            args.append("{:>6}  ".format(n + 1))
            args.append(("num",))
            args.append(line + "\n")
            args.append((kind,))
        if args:
            self.txt.insert("1.0" if prepend else "end", *args)

    # -------------------------------------------------------- 装载 / 定位
    def jump_to(self, pos):
        """打开时定位到第 pos 章：先只装载这一章附近的一段，再把它滚到窗口中间。"""
        pos = min(max(int(pos), 0), len(self.starts) - 1)
        target = self.starts[pos]
        a = max(0, target - CHAP_VIEW_BACK)
        b = min(self.rows, a + CHAP_VIEW_CHUNK)
        self._load(a, b, before=False)
        self._center_on(target)
        # 标题栏里的章名直接取原文那一行：与正文逐字一致，不做二次拼装
        self.meta.configure(text=self.S["chap_win_meta"].format(
            self.lines[target].strip() or "—", pos + 1, len(self.starts),
            "{:,}".format(self.rows)))
        self._safe(self.txt.focus_set)

    def _center_on(self, target):
        """把目标章滚到窗口垂直中间（上下各留半屏），而不是贴在首行。"""
        self._target = target
        idx = max(1, target - self._lo + 1)
        self._safe(lambda: self.txt.yview("%d.0" % idx))
        if self._center_now(idx):
            self._centered = True
            return
        # 刚建好的窗口还没完成布局（控件高度是 1）：等拿到真实尺寸再对一次
        if not self._center_hooked:
            self._center_hooked = True
            self._safe(lambda: self.txt.bind("<Configure>", self._center_evt, add="+"))

    def _center_evt(self, _e=None):
        if self._centered or self._closed:
            return
        if self._center_now(max(1, self._target - self._lo + 1)):
            self._centered = True
            self._safe(lambda: self.txt.unbind("<Configure>"))

    def _center_now(self, idx):
        """按「显示行」对半屏：长段落折行后一行逻辑行占好几行像素，按逻辑行会滚过头。"""
        try:
            h = self.txt.winfo_height()
            if h <= 1:
                return False
            n = self.txt.count("@0,0", "@0,%d" % (h - 1), "displaylines")
            half = (int(n[0]) if n else 0) // 2
            if half <= 0:
                return False
            self.txt.yview(self.txt.index("%d.0 - %d display lines" % (idx, half)))
        except (tk.TclError, ValueError):
            return False
        return True

    def _load(self, a, b, before):
        """插入 [a, b) 行：before=True 往上方补，False 往下方补。"""
        if a >= b or self._loading or self._closed:
            return
        self._loading = True
        top = 0
        try:
            if before:
                # 记下原来贴顶的逻辑行：插到它上方后要把它顶回原位，画面才不跳
                try:
                    top = int(self.txt.index("@0,0").split(".")[0])
                except (tk.TclError, ValueError):
                    top = 0
            self.txt.configure(state="normal")
            self._emit(a, b, prepend=before)
            self.txt.configure(state="disabled")
            if before:
                added = self._lo - a
                self._lo = a
                self._safe(lambda: self.txt.yview("%d.0" % (top + added)))
            else:
                if self._hi <= self._lo:  # 控件还是空的：第一次装载
                    self._lo = a
                self._hi = b
            self._update_stat()
        finally:
            self._loading = False
        # 内容还没铺满一屏时不会产生滚动，这里主动再补一块，直到铺满
        try:
            first, last = self.txt.yview()
        except tk.TclError:
            return
        self._pos = (first, last)
        if last >= 1.0 - CHAP_VIEW_EDGE and self._hi < self.rows:
            self._later(self._maybe_load, 20)

    def _update_stat(self):
        self.stat.configure(text=self.S["chap_win_loaded"].format(
            self._lo + 1, self._hi, self.rows))

    # -------------------------------------------------------- 滚动续载
    def _on_scroll(self, first, last):
        try:
            self.sb.set(first, last)
        except tk.TclError:
            return
        self._pos = (float(first), float(last))
        if self._pending is None and not self._loading:
            self._pending = self._later(self._maybe_load, 40)

    def _maybe_load(self):
        self._pending = None
        if self._loading or self._closed:
            return
        first, last = self._pos
        # 先看下方：内容不满一屏时 first=0/last=1，也该继续往下铺
        if last >= 1.0 - CHAP_VIEW_EDGE and self._hi < self.rows:
            self._load(self._hi, min(self.rows, self._hi + CHAP_VIEW_CHUNK), before=False)
        elif first <= CHAP_VIEW_EDGE and self._lo > 0:
            self._load(max(0, self._lo - CHAP_VIEW_CHUNK), self._lo, before=True)

    def _click_row(self, e):
        """单击选中整行（列表式交互）：折行的行连带它折下去的几行一起选中。"""
        try:
            line = int(self.txt.index("@%d,%d" % (e.x, e.y)).split(".")[0])
            self.txt.tag_remove("rowsel", "1.0", "end")
            self.txt.tag_add("rowsel", "%d.0" % line, "%d.0" % (line + 1))
            # 插入标记跟着落在这行：获得焦点时 Tk 会 see(insert)，不先挪过来
            # 的话点一行就被滚走；顺带方向键/翻页也从这一行继续
            self.txt.mark_set("insert", "%d.0" % line)
            self.txt.focus_set()
            self._sel_changed(True)   # 选中了：复制 / 创建章节 解除置灰
        except (tk.TclError, ValueError):
            pass
        return "break"  # 不落到默认绑定：否则会变成字符级选择 + 插入光标

    def _sel_changed(self, on):
        """按「有没有选中行」启停底栏两个按钮（置灰 = 点了也不响应）。"""
        state = "normal" if on else "disabled"
        for btn in (getattr(self, "btn_copy", None), getattr(self, "btn_new", None)):
            try:
                btn.configure(state=state)
            except (AttributeError, tk.TclError):
                pass

    def _sel_row(self):
        """当前选中行在原文里的行号（0 基）；一行都没选返回 None。

        选中只落在控件里某一行上，续载往上垫行后控件行号会变，所以要减掉
        已载入范围的下界，换回原文行号。
        """
        try:
            rng = self.txt.tag_ranges("rowsel")
        except tk.TclError:
            return None
        if not rng:
            return None
        try:
            row = self._lo + int(str(rng[0]).split(".")[0]) - 1
        except (ValueError, IndexError):
            return None
        return row if 0 <= row < self.rows else None

    def _copy(self):
        """把选中的那一行原文复制到剪贴板（行号栏是界面自己加的，不带）。"""
        row = self._sel_row()
        if row is None:
            return
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(self.lines[row])
        except tk.TclError:
            return
        # 按钮上闪一下「已复制」：底栏左侧要显示已载入行数，不跟它抢位置
        try:
            self.btn_copy.configure(text=self.S["chap_win_copied"], state="disabled")
            self._safe(lambda: self.win.after(900, self._copy_reset))
        except tk.TclError:
            pass

    def _copy_reset(self):
        if self._closed:
            return
        try:
            self.btn_copy.configure(text=self.S["chap_win_copy"])
        except tk.TclError:
            return
        self._sel_changed(self._sel_row() is not None)

    def _create(self):
        """以选中行当章节标题行新建一章：标题可改，正文取到下一章开头。"""
        row = self._sel_row()
        if row is None or self.on_create is None:
            return
        orig = self.lines[row].strip()
        title = self._ask_title(orig)
        if not title:
            return
        try:
            ok = self.on_create(self.book, row, title, orig, self.rows)
        except Exception as e:  # 分章规则写坏了也不该把窗口留在半死状态
            messagebox.showerror(self.S["d_chap_fail"], str(e), parent=self.win)
            return
        if ok:
            self._close()   # 建完就关窗，列表已由主界面重刷

    def _ask_title(self, default):
        """章节标题输入框：默认填选中那行的原文，确认返回去空白的标题。"""
        S = self.S
        w = tk.Toplevel(self.win)
        w.title(S["chap_new_title"])
        w.transient(self.win)
        w.configure(bg=BG)
        w.resizable(False, False)
        got = {"title": None}
        bar = ttk.Frame(w)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(10))

        def _ok(_e=None):
            val = var.get().strip()
            if not val:
                messagebox.showwarning(S["d_warn"], S["chap_new_empty"], parent=w)
                return
            got["title"] = val
            w.destroy()

        ttk.Button(bar, text=S["d_ok"], style="Accent.TButton",
                   command=_ok).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], style="Soft.TButton",
                   command=w.destroy).pack(side="right", padx=px(6))
        row = ttk.Frame(w)
        row.pack(fill="x", padx=px(12), pady=px(12))
        ttk.Label(row, text=S["chap_new_hint"]).pack(side="left")
        var = tk.StringVar(value=default)
        e = ttk.Entry(row, textvariable=var, width=40)
        e.pack(side="left", fill="x", expand=True, padx=(px(6), 0))
        e.bind("<Return>", _ok)
        w.bind("<Escape>", lambda _e: w.destroy())
        e.focus_set()
        e.select_range(0, "end")   # 默认文本整段选中：直接输入就是覆盖
        w.update_idletasks()
        _center_win(w, 460, int(round(w.winfo_reqheight() / max(_SCALE, 0.01))))
        w.grab_set()
        self.win.wait_window(w)
        return got["title"]

    def _no_drag(self, _e=None):
        """拖动/带修饰键的点击：一律不进入字符级选择，选行只认单击。"""
        self._safe(lambda: self.txt.tag_remove("sel", "1.0", "end"))
        return "break"

    def _wheel(self, e):
        """滚轮：一格走 3 行（触控板的小 delta 按 1 格算），并让续载逻辑有机会触发。"""
        try:
            self.txt.yview_scroll(-3 if (getattr(e, "delta", 0) or 0) > 0 else 3,
                                  "units")
        except tk.TclError:
            pass
        return "break"

    def _yview(self, *args):
        self._safe(lambda: self.txt.yview(*args))

    # -------------------------------------------------------- 杂项
    def _later(self, func, ms):
        """窗口可能已经关掉：after 也要包一层，别让 TclError 冒到主循环。"""
        try:
            return self.win.after(ms, func)
        except tk.TclError:
            return None

    def _safe(self, func):
        try:
            func()
        except tk.TclError:
            pass

    def _close(self):
        self._closed = True
        if self._pending is not None:
            try:
                self.win.after_cancel(self._pending)
            except Exception:
                pass
            self._pending = None
        self._safe(self.win.destroy)


class App:
    def __init__(self, root):
        self.root = root
        self.books = []
        # 封面设置窗的结果：{书籍路径键: cover_for_book 元组}，只在本进程有效
        self.cover_map = {}
        # 内置封面：全局默认风格 + 哪几本用的是内置封面（键 -> 风格 id），
        # 重开封面窗时据此还原「这本是内置画出来的」，用户挑的图不受影响
        self.cover_style = jzcore.DEFAULT_COVER_STYLE
        self.cover_pins = {}
        self.q = queue.Queue()
        self.busy = False
        self.cancel = False
        # 后台线程改了书籍字典（分章规则 / 删章）需要落盘索引的标记
        self._idx_dirty = False
        self.cfg = jzcore.load_config()
        self.lang = pick_lang()
        self.S = TEXTS[self.lang]
        # 主题按钮：宽度固定，名字长了按宽度加省略号（见 _fit_theme_btn）
        self._theme_text = ""        # 当前主题的完整名字
        self._btn_font = None        # 量文字宽度用的字体（懒加载）
        self._theme_fitting = False  # 改文字时防 <Configure> 递归
        last = self.cfg.get("lastdir", "")
        self.dir_var = tk.StringVar(value=last)
        self.out_var = tk.StringVar(value=self.cfg.get("outdir", ""))
        # 全局分章正则：所有书共用（本书没写专用规则时用它）。改一下就标记
        # 索引待落盘 —— 它跟着 .deshelf_index.json 顶层 chap_re 走，不在书条目里。
        self.custom_re = tk.StringVar()
        self.custom_re.trace_add("write", lambda *_a: setattr(self, "_idx_dirty", True))
        self.mode_var = tk.StringVar(value=self.cfg.get("mode", "new") or "new")
        self.rule_vars = {r["id"]: tk.BooleanVar(value=r["id"] in jzcore.DEFAULT_ON)
                          for r in jzcore.RULES}
        # 自定义规则（来自规则包导入 / 自定义编辑），随配置持久化
        self.custom_rules = [r for r in (self.cfg.get("custom_rules") or [])
                             if isinstance(r, dict)]
        self.fmt_vars = {"epub": tk.BooleanVar(value=True),
                         "merge": tk.BooleanVar(value=False),
                         "split": tk.BooleanVar(value=False)}
        # 「下载插图链接」默认不勾且置灰，等批量清洗勾了「保留插图链接」才放开
        self.img_dl_var = tk.BooleanVar(value=False)
        # 「生成清洗内容汇总」默认开：只写一个 txt，用来回查被清洗掉的内容
        self.sum_var = tk.BooleanVar(value=bool(self.cfg.get("summary", True)))
        self.status_var = tk.StringVar(value=self.S["st_ready"])
        self.prog_var = tk.DoubleVar(value=0)

        root.title(self.S["w_title"] % (APP_CN, APP_EN, APP_VER))
        root.geometry("%dx%d" % (px(1080), px(760)))
        root.minsize(px(900), px(620))
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
            if not self.out_var.get():
                self.out_var.set(d.rstrip("\\/") + self.S["out_suffix"])
            self.load_index(d)

    # ------------------------------------------------------------ 界面
    def _style(self):
        """卡片式扁平皮肤。

        tkinter 画不了圆角和阴影，能做的是把「凹陷灰框 + 一样重的按钮」换成
        「浅底 + 1px 描边 + 分层按钮」，观感立刻从 Win98 拉到现代系统工具。
        色值故意和网页版同一套，两端看起来才像同一个软件。
        """
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        px1 = px(1)
        st.configure(".", background=BG, font=FONT, foreground=INK)

        # ---- 容器 ----
        # 所有容器底层一律铺白：卡片是白的，控件若还留着灰底，就会在卡片里
        # 冒出一个个灰方块——这正是「背景颜色不统一」的来源。
        for name in ("TFrame", "Card.TFrame", "TLabel", "Card.TLabel",
                     "TCheckbutton", "Card.TCheckbutton",
                     "TRadiobutton", "Card.TRadiobutton"):
            st.configure(name, background=CARD)
        st.configure("TLabel", foreground=INK)
        st.configure("Muted.TLabel", foreground=MUTED)
        st.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
        st.configure("Title.TLabel", background=CARD, foreground=INK, font=FONT_B)

        # ---- 分组框：去凹槽，改成 1px 描边的卡片 ----
        st.configure("Card.TLabelframe", background=CARD, bordercolor=LINE,
                     borderwidth=px1, relief="solid")
        st.configure("Card.TLabelframe.Label", background=CARD, foreground=MUTED,
                     font=FONT_S)

        # ---- 按钮：默认描边白底，主按钮实心蓝，行动按钮实心绿 ----
        st.configure("TButton", background="#FFFFFF", foreground=INK,
                     bordercolor="#C3C8CE", lightcolor="#FFFFFF",
                     darkcolor="#FFFFFF", focuscolor="#FFFFFF",
                     padding=(px(10), px(4)), relief="flat",
                     borderwidth=px1)
        st.map("TButton",
               background=[("disabled", "#F2F3F5"), ("pressed", PRESS),
                           ("active", HOVER)],
               lightcolor=[("pressed", PRESS), ("active", HOVER)],
               darkcolor=[("pressed", PRESS), ("active", HOVER)],
               foreground=[("disabled", "#A8ADB4")],
               bordercolor=[("active", "#B4B9BF")])

        for name, bg, bg_d in (("Accent.TButton", BLUE, BLUE_D),
                               ("Go.TButton", GREEN, GREEN_D)):
            st.configure(name, background=bg, foreground="#FFFFFF",
                         bordercolor=bg_d, lightcolor=bg, darkcolor=bg,
                         focuscolor=bg, padding=(px(14), px(5)))
            st.map(name,
                   background=[("disabled", "#B9C4CF"), ("pressed", bg_d),
                               ("active", bg_d)],
                   foreground=[("disabled", "#F0F2F4")])

        # 浅蓝描边：次级但重要的按键（全选/试分全部/规则包等），
        # 白底太素、实心又抢主按钮的戏
        st.configure("Soft.TButton", background="#D7E6F8", foreground="#174D85",
                     bordercolor="#9DC0E4", lightcolor="#D7E6F8",
                     darkcolor="#D7E6F8", focuscolor="#D7E6F8",
                     padding=(px(10), px(4)))
        st.map("Soft.TButton",
               background=[("disabled", "#EDF1F5"), ("pressed", "#BCD4EF"),
                           ("active", "#C8DEF6")],
               lightcolor=[("pressed", "#BCD4EF"), ("active", "#C8DEF6")],
               darkcolor=[("pressed", "#BCD4EF"), ("active", "#C8DEF6")],
               foreground=[("disabled", "#9BAAB8")],
               bordercolor=[("active", "#7FA9D6")])

        # ---- 页签：选中项白底并往下压 2px，像贴在内容上 ----
        # 页签条本身也用白底，否则顶栏白 → 页签灰 → 内容白，窗口被切成三截。
        st.configure("TNotebook", background=CARD, bordercolor=LINE,
                     borderwidth=px1, tabmargins=(px(2), px(3), px(2), 0))
        st.configure("TNotebook.Tab", background="#E9EDF2", foreground=MUTED,
                     bordercolor=LINE, padding=(px(14), px(5)),
                     lightcolor="#E9EDF2", darkcolor="#E9EDF2")
        st.map("TNotebook.Tab",
               background=[("selected", CARD), ("active", "#F1F4F8")],
               foreground=[("selected", INK)],
               expand=[("selected", (0, 0, 0, px(2)))])

        # ---- 表格 ----
        st.configure("Treeview", background=CARD, fieldbackground=CARD,
                     foreground=INK, rowheight=px(26), bordercolor=LINE,
                     borderwidth=px1, font=FONT, lightcolor=LINE, darkcolor=LINE)
        st.configure("Treeview.Heading", background="#E7EAED", foreground="#3C4147",
                     font=FONT_B, relief="flat", padding=(px(6), px(5)),
                     bordercolor=LINE)
        st.map("Treeview.Heading", background=[("active", "#DFE3E7")])
        st.map("Treeview", background=[("selected", "#D6E4F2")],
               foreground=[("selected", INK)])

        # ---- 输入类 ----
        st.configure("TEntry", fieldbackground="#FFFFFF", foreground=INK,
                     bordercolor=LINE, lightcolor="#FFFFFF", darkcolor="#FFFFFF",
                     insertcolor=INK, padding=(px(6), px(3)))
        st.map("TEntry", bordercolor=[("focus", BLUE)],
               lightcolor=[("focus", BLUE)])
        st.configure("TCombobox", fieldbackground="#FFFFFF", background=CARD,
                     foreground=INK, bordercolor=LINE, arrowcolor=MUTED,
                     padding=(px(5), px(3)))
        st.map("TCombobox", bordercolor=[("focus", BLUE)],
               fieldbackground=[("readonly", "#FFFFFF")],
               foreground=[("readonly", INK)])
        st.configure("TSpinbox", fieldbackground="#FFFFFF", bordercolor=LINE,
                     arrowcolor=MUTED, padding=(px(4), px(3)))

        # ---- 进度条 / 滚动条 / 分隔线 ----
        st.configure("TProgressbar", troughcolor="#EBEEF2", background=BLUE,
                     bordercolor="#EBEEF2", lightcolor=BLUE, darkcolor=BLUE,
                     thickness=px(10))
        st.configure("TScrollbar", background="#D3D7DC", troughcolor=BG,
                     bordercolor=BG, arrowcolor=MUTED, width=px(12),
                     lightcolor="#D3D7DC", darkcolor="#D3D7DC")
        st.map("TScrollbar", background=[("active", "#C3C8CE")])
        st.configure("TSeparator", background=LINE)

        # 下拉列表（这是原生 Listbox，只能走 option 数据库）
        try:
            self.root.option_add("*TCombobox*Listbox.background", "#FFFFFF")
            self.root.option_add("*TCombobox*Listbox.foreground", INK)
            self.root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
            self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
            self.root.option_add("*TCombobox*Listbox.borderWidth", px1)
        except tk.TclError:
            pass

    def _cardify(self, w):
        """卡片内的 ttk 控件切到 Card.* 变体，否则灰底方块会糊在白卡上。

        注意 ttk 控件的 winfo_class() 是 TFrame / TLabel / TCheckbutton，
        不是 Frame / Label —— 早先按后者判断，这个函数一直是空转的，
        所以卡片里永远是灰底，整个窗口看着一块白一块灰。
        """
        try:
            kids = w.winfo_children()
        except tk.TclError:
            return
        for c in kids:
            cls = c.winfo_class()
            if cls in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton"):
                try:
                    cur = str(c.cget("style") or "")
                except tk.TclError:
                    cur = "x"
                if not cur:
                    try:
                        c.configure(style="Card." + cls)
                    except tk.TclError:
                        pass
            elif cls in ("Frame", "Label", "Canvas", "Text"):
                # 原生控件没有 style，直接刷底色
                try:
                    c.configure(bg=CARD)
                except tk.TclError:
                    pass
                if cls == "Canvas":
                    try:
                        c.configure(highlightthickness=0)
                    except tk.TclError:
                        pass
            self._cardify(c)

    def _menu(self):
        S = self.S
        m = tk.Menu(self.root)
        self.root.configure(menu=m)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label=S["m_pick_dir"], command=self.pick_dir)
        fm.add_command(label=S["m_rescan"], command=self.do_scan)
        fm.add_command(label=S["m_rescan_fresh"], command=lambda: self.do_scan(fresh=True))
        fm.add_separator()
        fm.add_command(label=S["m_quit"], command=self.on_close)
        m.add_cascade(label=S["m_file"], menu=fm)
        sm = tk.Menu(m, tearoff=0)
        sm.add_command(label=S["m_sel_all"], command=lambda: self.set_all(True))
        sm.add_command(label=S["m_sel_none"], command=lambda: self.set_all(False))
        sm.add_command(label=S["m_invert"], command=self.invert_sel)
        sm.add_separator()
        sm.add_command(label=S["m_sel_dup"], command=self.sel_dup)
        sm.add_command(label=S["m_export_csv"], command=self.export_list)
        m.add_cascade(label=S["m_lib"], menu=sm)
        lm = tk.Menu(m, tearoff=0)
        self._lang_rb = tk.StringVar(value=self.lang)
        lm.add_radiobutton(label="中文", value=ZH, variable=self._lang_rb,
                           command=lambda: self.switch_lang(ZH))
        lm.add_radiobutton(label="English", value=EN, variable=self._lang_rb,
                           command=lambda: self.switch_lang(EN))
        m.add_cascade(label=S["m_lang"], menu=lm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label=S["m_usage"],
                       command=lambda: self.show_text(S["usage_title"], S["help_text"]))
        hm.add_command(label=S["m_disclaimer"],
                       command=lambda: self.show_text(S["disclaimer_title"], S["disclaimer_text"]))
        hm.add_separator()
        hm.add_command(label=S["m_about"], command=self.show_about)
        m.add_cascade(label=S["m_help"], menu=hm)

    def _top(self, root):
        S = self.S
        f = ttk.Frame(root, padding=(px(10), px(7)), style="Card.TFrame")
        f.pack(fill="x", padx=px(8), pady=(px(6), px(6)))
        # 语言开关直接放在界面上：中文界面显示「EN」，英文界面显示「中文」。
        # 只挂在菜单里的话，不懂中文的人根本找不到「语言」那一项。
        ttk.Button(f, text=("EN" if self.lang == ZH else "中文"),
                   style="Soft.TButton",
                   command=lambda: self.switch_lang(EN if self.lang == ZH else ZH)
                   ).pack(side="right", padx=(px(6), 0))
        ttk.Label(f, text=S["lib_dir"]).pack(side="left")
        e = ttk.Entry(f, textvariable=self.dir_var)
        e.pack(side="left", fill="x", expand=True, padx=px(4))
        e.bind("<Return>", lambda _e: self.do_scan())
        ttk.Button(f, text=S["browse"], style="Soft.TButton",
                   command=self.pick_dir).pack(side="left")
        ttk.Button(f, text=S["b_add_files"], style="Accent.TButton",
                   command=self.pick_files).pack(side="left", padx=(px(4), 0))
        ttk.Button(f, text=S["scan"], style="Accent.TButton",
                   command=self.do_scan).pack(side="left", padx=(px(4), 0))
        ttk.Button(f, text=S["b_rescan"],
                   command=lambda: self.do_scan(fresh=True)).pack(side="left", padx=px(4))
        self.btn_stop = ttk.Button(f, text=S["stop"], command=self.do_stop, state="disabled")
        self.btn_stop.pack(side="left")
        self._cardify(f)

    def _tabs(self, root):
        S = self.S
        nb = ttk.Notebook(root)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=px(8), pady=(0, px(4)))
        # 每页也铺白底：页里放的卡片本来就是白的，页底留灰只会在卡片周围
        # 露出一圈灰边，看着像没铺满。
        self.tab_lib = ttk.Frame(nb, style="Card.TFrame")
        self.tab_clean = ttk.Frame(nb, style="Card.TFrame")
        self.tab_chap = ttk.Frame(nb, style="Card.TFrame")
        self.tab_out = ttk.Frame(nb, style="Card.TFrame")
        nb.add(self.tab_lib, text=S["tab1"])
        nb.add(self.tab_clean, text=S["tab2"])
        nb.add(self.tab_chap, text=S["tab3"])
        nb.add(self.tab_out, text=S["tab4"])
        self._build_lib()
        self._build_clean()
        self._build_chap()
        self._build_out()
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_lib(self):
        S = self.S
        f = self.tab_lib
        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=px(2), pady=(px(8), px(6)))
        for txt, cmd in ((S["m_sel_all"], lambda: self.set_all(True)),
                         (S["m_sel_none"], lambda: self.set_all(False)),
                         (S["m_invert"], self.invert_sel),
                         (S["m_sel_dup"], self.sel_dup)):
            ttk.Button(bar, text=txt, style="Soft.TButton",
                       command=cmd).pack(side="left", padx=(0, px(4)))
        ttk.Label(bar, text=S["lib_hint"], foreground=MUTED).pack(side="left", padx=px(6))
        self.info_var = tk.StringVar(value=S["lib_info"].format(0, 0))
        ttk.Label(bar, textvariable=self.info_var, foreground=MUTED).pack(side="right")

        cols = ("sel", "title", "author", "chars", "enc", "chap", "size", "rel")
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True, padx=px(2), pady=(0, px(4)))
        self.tv = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        heads = {"sel": "✓", "title": S["col_title"], "author": S["col_author"],
                 "chars": S["col_chars"], "enc": S["col_enc"], "chap": S["col_chap"],
                 "size": S["col_size"], "rel": S["col_rel"]}
        widths = {"sel": px(32), "title": px(190), "author": px(100), "chars": px(80),
                  "enc": px(76), "chap": px(56), "size": px(78), "rel": px(320)}
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
        S = self.S
        f = self.tab_clean
        left = ttk.LabelFrame(f, text=S["grp_rules"].format(len(jzcore.RULES)),
                              width=px(304), style="Card.TLabelframe")
        left.pack(side="left", fill="y", padx=(px(6), px(4)), pady=px(6))
        left.pack_propagate(False)

        # 规则列表单独滚动、底部按钮固定：
        # 一屏放不下时不至于把最后几条（简繁重复行等）整条裁掉且无处可看。
        bf = ttk.Frame(left)
        bf.pack(side="bottom", fill="x", padx=px(8), pady=px(8))
        ttk.Button(bf, text=S["b_all_rules"],
                   command=lambda: self.set_rules(True)).pack(side="left")
        ttk.Button(bf, text=S["b_def_rules"],
                   command=lambda: self.set_rules(None)).pack(side="left", padx=px(4))
        bf2 = ttk.Frame(left)
        bf2.pack(side="bottom", fill="x", padx=px(8))
        ttk.Button(bf2, text=S["b_imp_rules"], style="Soft.TButton",
                   command=self.import_rules).pack(side="left")
        ttk.Button(bf2, text=S["b_exp_rules"], style="Soft.TButton",
                   command=self.export_rules).pack(side="left", padx=px(3))
        ttk.Button(bf2, text=S["b_edit_rules"],
                   command=self.edit_custom).pack(side="left")

        wrap = ttk.Frame(left)
        wrap.pack(side="top", fill="both", expand=True)
        vsb = ttk.Scrollbar(wrap, orient="vertical")
        vsb.pack(side="right", fill="y")
        cv = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0,
                       yscrollincrement=px(16))
        vsb.configure(command=cv.yview)
        cv.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(cv)
        cv_win = cv.create_window((0, 0), window=inner, anchor="nw")
        self._rules_canvas = cv
        self._rule_inner = inner

        en = self.lang == EN
        self._rule_cbs = []
        self._rule_rows = []
        self._rule_frames = {}
        self._rule_cb_by_id = {}
        self._rule_tip_by_id = {}
        for r in jzcore.RULES:
            name = r["name_en"] if en else r["name"]
            tip = r["tip_en"] if en else r["tip"]
            row = ttk.Frame(inner)
            cb = ttk.Checkbutton(row, text=name, variable=self.rule_vars[r["id"]])
            cb.pack(anchor="w", padx=px(8), pady=(px(3), 0))
            lab = ttk.Label(row, text="    " + tip, foreground="#777777",
                            font=FONT_S, wraplength=px(236))
            lab.pack(anchor="w", padx=px(8))
            row.pack(anchor="w", fill="x")
            self._rule_frames[r["id"]] = row
            self._rule_rows.append(row)
            self._rule_cbs.append(cb)
            self._rule_cb_by_id[r["id"]] = cb
            self._rule_tip_by_id[r["id"]] = lab
        # 插图两条规则跟着「含网址的行」显隐；「插图链接校验」还要等
        # 「保留插图链接」打开才允许勾选。
        # 变量上的 trace 回调不随界面重建消失：先摘掉上一轮挂的，否则切几次语言后
        # 每勾一下都会把 refresh_rule_state 重复调上好几遍（还可能点到已销毁的控件）。
        for _vid, _name in getattr(self, "_rule_traces", ()):
            try:
                self.rule_vars[_vid].trace_remove("write", _name)
            except Exception:
                pass
        self._rule_traces = [
            (_rid, self.rule_vars[_rid].trace_add(
                "write", lambda *a: self.refresh_rule_state()))
            for _rid in ("url", "imgkeep")
        ]
        self.refresh_rule_state()

        # 「下面还有 N 条」提示：光有滚动条不够，一屏只显示 6~8 条时
        # 用户会以为规则就这么多（v1.3.4 的简繁选项就是这样被忽视的）。
        self.rule_hint = ttk.Label(left, text="", foreground="#C05621",
                                   font=FONT_S, wraplength=px(272))
        self.rule_hint.pack(side="bottom", fill="x", padx=px(8), pady=(0, px(2)))

        def _hidden_count():
            try:
                _f, last = cv.yview()
                h = inner.winfo_height()
            except Exception:
                return 0
            if h <= 1:
                return 0
            bottom = last * h
            return sum(1 for w in self._rule_rows
                       if w.winfo_manager() and w.winfo_y() + px(4) > bottom)

        def _sync(first, last):
            vsb.set(first, last)
            n = _hidden_count()
            self.rule_hint.configure(
                text=S["rule_more"].format(n) if n else "")

        cv.configure(yscrollcommand=_sync)

        def _later_sync():
            # 界面可能在 30ms 内被「切换语言」整棵重建：旧画布已销毁就别再碰它
            if not self._alive(cv):
                return
            try:
                _sync(*cv.yview())
            except tk.TclError:
                pass

        # 内层宽度跟随画布（否则文字按请求宽度排版、右边被切）
        def _on_cv_conf(e):
            cv.itemconfigure(cv_win, width=e.width)
            self.root.after(30, _later_sync)

        def _on_inner_conf(_e):
            cv.configure(scrollregion=cv.bbox("all"))
            self.root.after(30, _later_sync)

        cv.bind("<Configure>", _on_cv_conf)
        inner.bind("<Configure>", _on_inner_conf)

        def _wheel(e):
            try:
                first, last = cv.yview()
            except Exception:
                return
            if first <= 0.0 and last >= 1.0:  # 内容不满一屏：不拦滚轮
                return
            step = -1 if e.delta > 0 else 1
            cv.yview_scroll(step * max(1, abs(int(e.delta / 120))), "units")

        def _bind_wheel(w):
            w.bind("<MouseWheel>", _wheel)
            try:
                kids = w.winfo_children()
            except Exception:
                return
            for c in kids:
                _bind_wheel(c)

        _bind_wheel(cv)
        _bind_wheel(inner)
        self._cardify(left)

        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=px(4), pady=px(6))
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        btnrow = ttk.Frame(bar)
        btnrow.pack(fill="x")
        ttk.Button(btnrow, text=S["b_preview"], style="Accent.TButton",
                   command=self.preview_clean).pack(side="left")
        self.btn_clean_apply = ttk.Button(btnrow, text=S["b_clean_apply"],
                                          style="Go.TButton",
                                          command=self.start_clean)
        self.btn_clean_apply.pack(side="left", padx=(px(6), 0))
        self.cmp_var = tk.StringVar(value="")
        # 预览统计可能很长（删除行数、合并断行、插图链接…），同样按可用宽度折行；
        # 折行后必须左对齐，右对齐会让第二行起每行都顶着右边，看起来像排版错乱
        cmp_lab = ttk.Label(btnrow, textvariable=self.cmp_var, foreground="#2E7D32",
                            justify="left", anchor="w")
        cmp_lab.pack(side="left", fill="x", expand=True, padx=(px(8), 0))
        cmp_lab.bind("<Configure>", _wrap_label)
        # 提示文字单独占一行，并按可用宽度自动换行：跟按钮挤在同一行时，
        # 窗口一窄就被切掉，用户得拉宽窗口才看得到后半句。
        self.hint_lab = ttk.Label(bar, text=S["clean_hint"], foreground="#666666",
                                  justify="left", anchor="w")
        self.hint_lab.pack(fill="x", pady=(px(2), 0))
        self.hint_lab.bind("<Configure>", _wrap_label)
        box = ttk.Frame(right)
        box.pack(fill="both", expand=True, pady=px(4))
        self.txt_before = self._mk_text(box, S["col_pre"])
        self.txt_after = self._mk_text(box, S["col_post"])
        # 预览时被清洗掉的内容标红：整行删除的整行标红，行内挖掉的只标那一段
        self.txt_before.tag_configure("del", foreground=RED)

    def _mk_text(self, parent, title):
        f = ttk.LabelFrame(parent, text=title, style="Card.TLabelframe")
        f.pack(side="left", fill="both", expand=True, padx=px(2))
        # width 必须给小值：pack 按顺序满足请求宽度，80 字符会吃满空间导致两栏不等分
        t = tk.Text(f, wrap="none", font=MONO, width=30, height=10, bg="#FFFFFF",
                    relief="flat", borderwidth=0, highlightthickness=1,
                    highlightbackground=LINE, highlightcolor=BLUE)
        sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, px(4)), pady=px(4))
        t.pack(fill="both", expand=True, padx=px(4), pady=px(4))
        self._cardify(f)
        return t

    def _build_chap(self):
        S = self.S
        f = self.tab_chap
        top = ttk.Frame(f)
        top.pack(fill="x", padx=px(8), pady=(px(8), px(4)))
        ttk.Label(top, text=S["re_label"]).pack(side="left")
        e = ttk.Entry(top, textvariable=self.custom_re)
        e.pack(side="left", fill="x", expand=True, padx=px(4))
        ttk.Button(top, text=S["re_help"], style="Soft.TButton",
                   command=self.show_re_help).pack(side="left", padx=(0, px(6)))
        self.btn_chap_try = ttk.Button(top, text=S["b_try"], style="Accent.TButton",
                                       command=self.preview_chap)
        self.btn_chap_try.pack(side="left")
        self.btn_chap_all = ttk.Button(top, text=S["b_try_all"],
                                       style="Soft.TButton",
                                       command=self.preview_chap_all)
        self.btn_chap_all.pack(side="left", padx=(px(6), 0))
        pick = ttk.Frame(f)
        pick.pack(fill="x", padx=px(8), pady=(px(2), 0))
        ttk.Label(pick, text=S["lab_chap_pick"]).pack(side="left")
        self.chap_pick_text = tk.StringVar()
        self.cb_chap = ttk.Combobox(pick, textvariable=self.chap_pick_text,
                                    state="readonly", width=46)
        self.cb_chap.pack(side="left", padx=px(4))
        # 把这本书的章节树（含层级、解析出的序号链、校验结果）导出成文本，便于排查
        self.btn_chap_tree = ttk.Button(pick, text=S["b_chap_tree"],
                                        style="Soft.TButton",
                                        command=self.export_chap_tree)
        self.btn_chap_tree.pack(side="left", padx=(0, px(6)))
        ttk.Label(pick, text=S["chap_pick_hint"], foreground="#666666",
                  font=FONT_S).pack(side="left")
        # 每本书可以有自己的分章正则：留空就用上面的全局正则
        prow = ttk.Frame(f)
        prow.pack(fill="x", padx=px(8), pady=(px(4), 0))
        ttk.Label(prow, text=S["book_re"]).pack(side="left")
        self.book_re_var = tk.StringVar(value="")
        e_book = ttk.Entry(prow, textvariable=self.book_re_var)
        e_book.pack(side="left", fill="x", expand=True, padx=px(4))
        ttk.Button(prow, text=S["book_re_clr"],
                   command=self.clear_book_re).pack(side="left")
        self.re_state = tk.StringVar(value="")
        ttk.Label(prow, textvariable=self.re_state, foreground="#2E7D32",
                  font=FONT_S).pack(side="left", padx=px(6))
        e_book.bind("<Return>", lambda _e: self.store_book_re())
        e_book.bind("<FocusOut>", lambda _e: self.store_book_re())
        self.cb_chap.bind("<<ComboboxSelected>>", lambda _e: self.sync_book_re())
        self._re_book = None
        ttk.Label(f, text=S["chap_hint"],
                  foreground="#666666", font=FONT_S).pack(anchor="w", padx=px(8))
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True, padx=px(8), pady=px(4))
        self.tv_chap = ttk.Treeview(wrap, columns=("no", "title", "chars", "check"),
                                    show="headings", height=8)
        for c, w, t in (("no", px(60), "#"), ("title", px(420), S["col_chap_title"]),
                        ("chars", px(100), S["col_chars"]),
                        ("check", px(240), S["col_chap_check"])):
            self.tv_chap.heading(c, text=t)
            self.tv_chap.column(c, width=w,
                                anchor="w" if c == "title" else "center")
        # 校验不过的章整行标红（Treeview 只能按行着色）；正常的行保持默认色
        self.tv_chap.tag_configure("bad", foreground=RED)
        # 批量试分的结果行：双击进入这本书的单本试分
        self._chap_rows = {}
        # 表格里当前展示的是哪本书的单本结果（删章按它走，不看下拉框现选）
        self._chap_view_book = None
        self._chap_row_index = {}  # 行 → 完整切分结果里的下标（删章即记这个）
        self.tv_chap.bind("<Double-1>", self.on_chap_double)
        # 右键单章菜单：删除这一章（只影响当前这本书）
        self.tv_chap.bind("<Button-3>", self.popup_chap)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tv_chap.yview)
        self.tv_chap.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv_chap.pack(side="left", fill="both", expand=True)
        self.chap_var = tk.StringVar(value=S["chap_res"])
        ttk.Label(f, textvariable=self.chap_var).pack(anchor="w", padx=px(8), pady=(0, px(6)))

    def _build_out(self):
        S = self.S
        f = self.tab_out
        g1 = ttk.LabelFrame(f, text=S["grp_where"], style="Card.TLabelframe")
        g1.pack(fill="x", padx=px(8), pady=(px(10), px(6)))
        for v, t in (("new", S["r_new"]), ("inplace", S["r_inplace"]), ("none", S["r_none"])):
            ttk.Radiobutton(g1, text=t, value=v, variable=self.mode_var,
                            command=self.sync_out).pack(anchor="w", padx=px(10), pady=px(2))

        g2 = ttk.LabelFrame(f, text=S["grp_fmt"], style="Card.TLabelframe")
        g2.pack(fill="x", padx=px(8), pady=px(6))
        row = ttk.Frame(g2)
        row.pack(fill="x", padx=px(10), pady=px(4))
        ttk.Checkbutton(row, text=S["f_epub"], variable=self.fmt_vars["epub"],
                        command=self.refresh_epub_opts_state
                        ).pack(side="left", padx=(0, px(16)))
        ttk.Checkbutton(row, text=S["f_merge"],
                        variable=self.fmt_vars["merge"]).pack(side="left", padx=(0, px(16)))
        ttk.Checkbutton(row, text=S["f_split"],
                        variable=self.fmt_vars["split"]).pack(side="left")
        # 「文件名」：保持原样以外的选项都换算成 book/author 模板，与自定义格式同一套解析
        ttk.Label(row, text=S["f_name"]).pack(side="left", padx=(px(12), 0))
        self._custom_fmt = self.cfg.get("name_fmt_custom") or ""
        self._name_idx = 0
        self.cb_name = ttk.Combobox(row, state="readonly")
        self.cb_name.pack(side="left", padx=(px(4), 0))
        self._refresh_name_box()  # 填选项 + 按最长一项算宽度
        self._restore_name_opt()
        self.cb_name.bind("<<ComboboxSelected>>", self._on_name_sel)
        # EPUB 排版主题与封面：只影响导出的 epub，不改正文
        row2 = ttk.Frame(g2)
        row2.pack(fill="x", padx=px(10), pady=(0, px(6)))
        # 主题来自 styles 目录：按钮点开选图窗口，这里只显示当前主题名
        self.lb_theme = ttk.Label(row2, text=S["f_theme"])
        self.lb_theme.pack(side="left")
        self.themes = jzcore.list_themes()
        self.theme_by_id = {t["id"]: t for t in self.themes}
        self.theme_id = jzcore.DEFAULT_THEME
        self.btn_theme = ttk.Button(row2, text="", width=10,
                                    style="Soft.TButton",
                                    command=self.choose_theme)
        self.btn_theme.pack(side="left", padx=(px(4), 0))
        # 主题名长短不一：按钮宽度固定，文字按实际宽度截断加省略号（见 _fit_theme_btn）
        self.btn_theme.bind("<Configure>", self._fit_theme_btn)
        # 封面与主题同一套按钮样式：点开窗口逐本设置，不再用下拉框选策略
        self.btn_cover = ttk.Button(row2, text=S["cover_btn"], width=10,
                                    style="Soft.TButton",
                                    command=self.choose_covers)
        self.btn_cover.pack(side="left", padx=(px(16), 0))
        # 插图下载：只影响 epub 打包与「插图/书名」目录，不改正文
        self.cb_imgdl = ttk.Checkbutton(row2, text=S["f_imgdl"], variable=self.img_dl_var)
        self.cb_imgdl.pack(side="left", padx=(px(16), 0))
        self.refresh_imgdl_state()
        self._restore_epub_opts()
        self.refresh_epub_opts_state()

        g3 = ttk.LabelFrame(f, text=S["grp_out"], style="Card.TLabelframe")
        g3.pack(fill="x", padx=px(8), pady=px(6))
        r = ttk.Frame(g3)
        r.pack(fill="x", padx=px(10), pady=px(6))
        ttk.Entry(r, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=(0, px(4)))
        ttk.Button(r, text=S["browse"], style="Soft.TButton", command=self.pick_out).pack(side="left")
        # 汇总文件只落到输出目录，不改正文；用来回查“被清洗掉的是不是正文”
        self.cb_sum = ttk.Checkbutton(g3, text=S["f_summary"],
                                      variable=self.sum_var,
                                      command=self._save_sum_opt)
        self.cb_sum.pack(anchor="w", padx=px(10), pady=(0, px(6)))

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=px(8), pady=px(10))
        self.btn_go = ttk.Button(bar, text=S["b_go"], style="Go.TButton", command=self.start_run)
        self.btn_go.pack(side="left")
        self.pb = ttk.Progressbar(bar, variable=self.prog_var, maximum=100)
        self.pb.pack(side="left", fill="x", expand=True, padx=px(10))
        ttk.Label(f, text=S["out_note"],
                  foreground="#777777", font=FONT_S).pack(anchor="w", padx=px(8))
        for g in (g1, g2, g3):
            self._cardify(g)

    def _restore_epub_opts(self):
        """按配置恢复版面主题（存 CSS 文件名）和内置封面的默认风格。"""
        self.theme_id = self._valid_theme(self.cfg.get("theme"))
        style = self.cfg.get("cover_style")
        self.cover_style = (style if style in jzcore.cover_style_ids()
                            else jzcore.DEFAULT_COVER_STYLE)
        self._refresh_theme_btn()
        self._refresh_cover_btn()

    def _valid_theme(self, tid):
        """配置里的主题可能已被删除/移走：自定义 CSS 看文件还在不在，内置看列表。"""
        if jzcore.is_custom_theme(tid):
            return tid if jzcore.load_theme(tid) else jzcore.DEFAULT_THEME
        ids = [t["id"] for t in self.themes]
        if tid in ids:
            return tid
        if jzcore.DEFAULT_THEME in ids:
            return jzcore.DEFAULT_THEME
        return ids[0] if ids else jzcore.DEFAULT_THEME

    def _refresh_theme_btn(self):
        """按钮上显示当前主题名；太长就省略号截断（完整名字在选主题窗口里看）。"""
        t = self.theme_by_id.get(self.theme_id)
        if t is None:  # 自定义 CSS 不在内置列表里
            t = jzcore.load_theme(self.theme_id)
        self._theme_text = (theme_title(t, self.S, self.lang) if t
                            else self.S["f_theme"])
        self._fit_theme_btn()

    def _theme_btn_font(self):
        """主题按钮用的字体：与 ttk 基础样式同一套，量文字宽度才准。"""
        if getattr(self, "_btn_font", None) is None:
            try:
                self._btn_font = tkfont.Font(root=self.root, font=FONT)
            except Exception:
                self._btn_font = tkfont.nametofont("TkDefaultFont")
        return self._btn_font

    def _fit_theme_btn(self, _e=None):
        """按按钮当前宽度把主题名收进一行：塞不下就用「…」截断。

        按钮宽度是固定的（width=10 个字），换文案不会反过来改宽度，所以这里
        不会来回抖；换 DPI / 布局变化时靠 <Configure> 再量一次。
        """
        btn = getattr(self, "btn_theme", None)
        if not self._alive(btn) or getattr(self, "_theme_fitting", False):
            return
        text = getattr(self, "_theme_text", "")
        try:
            w = btn.winfo_width()
            if w <= 1:                      # 还没布局：先按请求宽度估
                w = btn.winfo_reqwidth()
            # 去掉左右内边距（Soft.TButton: px(10)）和描边，再留一点余量
            avail = w - 2 * px(10) - px(4)
            shown = _ellipsize(text, self._theme_btn_font(), avail)
            if btn.cget("text") != shown:
                self._theme_fitting = True  # 改文字可能触发 Configure，防递归
                try:
                    btn.configure(text=shown)
                finally:
                    self._theme_fitting = False
        except tk.TclError:
            pass

    def choose_theme(self):
        """弹出主题选择窗口：左侧预览、右侧缩略图网格，确定后写进配置。"""
        S = self.S
        # 每次打开都重扫一遍：用户往 styles 里丢一个新 CSS 不必重启程序
        self.themes = jzcore.list_themes() or self.themes
        self.theme_by_id = {t["id"]: t for t in self.themes}
        if not self.themes and not jzcore.is_custom_theme(self.theme_id):
            messagebox.showwarning(S["d_warn"], S["theme_none"])
            return
        got = ThemePicker(self.root, self.themes, self.theme_id,
                          self.lang, S).show()
        if got:
            self.theme_id = got
            self._refresh_theme_btn()
            self._save_epub_opts()

    def choose_covers(self):
        """弹出封面设置窗口：网格列出已勾选的书，右键逐本换封面。

        确定后把整份封面（字节已备好）留在 self.cover_map 里，开始处理时
        按它写进 epub —— 与窗口里看到的封面完全一致。窗口里选的默认封面
        风格和「哪几本是内置封面」也一并带回来，下次打开照原样还原。
        """
        S = self.S
        sel = [b for b in self.books if b["sel"]]
        if not sel:
            messagebox.showinfo(S["cover_no_books"], S["cover_no_books_msg"])
            return
        picker = CoverPicker(self.root, sel, self.cover_map,
                             self.out_var.get().strip(), self.lang, S,
                             style=self.cover_style, pins=self.cover_pins)
        got = picker.show()
        if got is None:  # 取消：保留原来的设置
            return
        self.cover_map = got
        self.cover_style = getattr(picker, "result_style", self.cover_style)
        self.cover_pins = getattr(picker, "result_pins", self.cover_pins)
        self._refresh_cover_btn()
        self._save_epub_opts()
        n = sum(1 for b in sel if _book_key(b["path"]) in self.cover_map)
        self.log(S["log_cover_set"].format(n))

    def _refresh_cover_btn(self):
        """按钮上直接写「已设置 N 本」，一眼能看出封面配好没有。"""
        btn = getattr(self, "btn_cover", None)
        if not self._alive(btn):
            return
        n = sum(1 for b in self.books if b.get("sel")
                and _book_key(b.get("path")) in self.cover_map)
        try:
            btn.configure(text=(self.S["cover_btn_n"].format(n) if n
                                else self.S["cover_btn"]))
        except tk.TclError:
            pass

    def epub_theme(self):
        """主线程取当前版面主题（封面另有 cover_map，见 choose_covers）。"""
        return self._valid_theme(self.theme_id)

    def _save_epub_opts(self):
        self.cfg["theme"] = self.epub_theme()
        self.cfg["cover_style"] = self.cover_style
        jzcore.save_config(self.cfg)

    def _save_sum_opt(self):
        self.cfg["summary"] = bool(self.sum_var.get())
        jzcore.save_config(self.cfg)

    # ------------------------------------------------------------ 文件名格式
    def name_pats(self):
        """「文件名」每项对应的模板：空串=保持原样，None=自定义格式。"""
        return ["", "author - book", "[author] book",
                self.S["name_pat_book_author"], None]

    def _refresh_name_box(self):
        """重填下拉项：自定义格式那一项显示用户填的模板，宽度按最长一项算。

        字符宽固定写死会把中文「《书名》作者：作者名」截断，所以按字体实测像素换算；
        自定义模板可能很长，宽度封顶 24 字，免得把整行撑破。
        """
        S = self.S
        self.name_labels = [S["name_keep"], S["name_author_title"], S["name_bracket"],
                            S["name_book_author"], self._custom_fmt or S["name_custom"]]
        self.cb_name.configure(values=self.name_labels)
        fnt = tkfont.Font(font=ttk.Style().lookup("TCombobox", "font") or "TkTextFont")
        unit = max(fnt.measure("0"), 1)
        widest = max(fnt.measure(t) for t in self.name_labels)
        self.cb_name.configure(width=min(int(widest / unit) + 1, 24))

    def _restore_name_opt(self):
        """恢复上次的文件名格式：认得出是预设就选预设，否则落到「自定义格式」。"""
        fmt = self.cfg.get("name_fmt") or ""
        idx = 0
        if fmt:
            try:
                idx = self.name_pats().index(fmt)
            except ValueError:
                idx = len(self.name_labels) - 1
                self._custom_fmt = fmt
                self._refresh_name_box()  # 老配置只存了模板，补进下拉项再选中
        self._name_idx = idx
        try:
            self.cb_name.current(idx)
        except Exception:
            pass

    def _on_name_sel(self, _e=None):
        """选中「自定义格式」时弹窗取模板；取消则退回上一次的选择。"""
        try:
            idx = self.cb_name.current()
        except Exception:
            idx = 0
        if idx < 0:
            return
        fmt = self.name_pats()[idx]
        if fmt is None:
            fmt = self.ask_name_fmt()
            if fmt is None:
                try:
                    self.cb_name.current(self._name_idx)
                except Exception:
                    pass
                return
            self._custom_fmt = fmt
            self._refresh_name_box()  # 下拉框里直接显示用户填的格式
        self._name_idx = idx
        try:
            self.cb_name.set(self.name_labels[idx])
        except Exception:
            pass
        self.cfg["name_fmt"] = fmt
        self.cfg["name_fmt_custom"] = self._custom_fmt
        jzcore.save_config(self.cfg)

    def ask_name_fmt(self):
        """自定义文件名格式输入框：必须含 book 占位符、不含非法字符，确认返回模板，取消返回 None。"""
        S = self.S
        win_w = 560
        w = tk.Toplevel(self.root)
        w.title(S["name_custom_title"])
        w.transient(self.root)
        w.configure(bg=BG)
        w.resizable(False, False)
        # 底栏先占位，正文再往上排；提示卡 fill="x" 才会铺满，不然文字挤在左边一条
        bar = ttk.Frame(w)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(10))
        ttk.Button(bar, text=S["d_ok"], style="Accent.TButton",
                   command=lambda: _ok()).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], style="Soft.TButton",
                   command=w.destroy).pack(side="right", padx=px(6))

        tip = tk.Label(w, text=S["name_custom_hint"], bg=CARD, fg=MUTED, font=FONT_S,
                       justify="left", anchor="w", wraplength=px(win_w - 54),
                       highlightthickness=1, highlightbackground=LINE,
                       padx=px(10), pady=px(8))
        tip.pack(fill="x", padx=px(12), pady=(px(12), px(8)))

        ttk.Label(w, text=S["name_fmt_label"]).pack(anchor="w", padx=px(12))
        var = tk.StringVar(value=self._custom_fmt or S["name_custom_demo"])
        e = ttk.Entry(w, textvariable=var, font=FONT)
        e.pack(fill="x", padx=px(12), pady=(px(2), 0))
        # 输入合法时这里给一句预览，出错时同一行变红字，窗口不会忽高忽低
        status = tk.Label(w, bg=BG, fg=MUTED, font=FONT_S, anchor="w", justify="left",
                          wraplength=px(win_w - 24))
        status.pack(fill="x", padx=px(14), pady=(px(6), 0))
        got = {"fmt": None}

        def _err(val):
            bad = jzcore.name_fmt_bad_chars(val)
            if bad:
                return S["name_custom_bad_char"].format(" ".join(bad))
            if not jzcore.has_book_token(val):
                return S["name_custom_bad"]
            return ""

        def _refresh(*_a):
            val = var.get().strip()
            msg = _err(val)
            if msg:
                status.configure(fg=RED, text=msg)
            elif not val:
                status.configure(fg=MUTED, text="")
            else:
                status.configure(fg=GREEN, text=S["name_preview"].format(
                    jzcore.apply_name_format(val, S["name_preview_title"],
                                             S["name_preview_author"], "")))

        def _ok(_e=None):
            val = var.get().strip()
            msg = _err(val)  # 非法：留在窗里改，不丢用户输入
            if msg:
                status.configure(fg=RED, text=msg)
                e.focus_set()
                return
            got["fmt"] = val
            w.destroy()

        var.trace_add("write", _refresh)
        _refresh()
        e.bind("<Return>", _ok)
        w.bind("<Escape>", lambda _e: w.destroy())
        e.focus_set()
        e.select_range(0, "end")
        # 高度按内容实测：中英文提示行数不同，写死高度不是留白就是挤压
        w.update_idletasks()
        _center_win(w, win_w, int(round(w.winfo_reqheight() / max(_SCALE, 0.01))))
        w.grab_set()
        self.root.wait_window(w)
        return got["fmt"]

    def name_format(self):
        """主线程取当前文件名模板：空串=保持原样，可直接传给后台线程。"""
        try:
            idx = self.cb_name.current()
        except Exception:
            return ""
        pats = self.name_pats()
        if not (0 <= idx < len(pats)):
            return ""
        return self._custom_fmt if pats[idx] is None else (pats[idx] or "")

    def _log(self, root):
        S = self.S
        f = ttk.LabelFrame(root, text=S["grp_log"], height=px(130),
                           style="Card.TLabelframe")
        f.pack(fill="x", padx=px(8), pady=(0, px(4)))
        f.pack_propagate(False)
        self.logbox = tk.Text(f, height=7, font=FONT_S, bg="#FFFFFF",
                              relief="flat", borderwidth=0, highlightthickness=1,
                              highlightbackground=LINE, highlightcolor=BLUE)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, px(4)), pady=px(4))
        self.logbox.pack(fill="both", expand=True, padx=px(4), pady=px(4))
        self._cardify(f)

    def _status(self, root):
        """状态栏：不用 sunken（那是 3D 凹槽感），改成一条细横线压住。"""
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=px(8), pady=(0, px(6)))
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, px(3)))
        ttk.Label(bar, textvariable=self.status_var, anchor="w",
                  foreground=MUTED, font=FONT_S,
                  padding=(px(2), 0)).pack(fill="x")

    # ------------------------------------------------------------ 基础操作
    def log(self, msg):
        self.q.put(("log", msg))

    def log_progress(self, msg):
        """把日志最后一行原地改成 msg（插图下载进度）：几百张图也只占一行。

        进度行用 tag 标记，下次刷新就按 tag 范围整行删掉重写，于是「3/57」会一路
        走到「57/57」，不会把日志刷满、把前面的处理记录顶出视野。
        """
        box = self.logbox
        try:
            rng = box.tag_ranges("logprog")
            if rng:
                box.delete(rng[0], rng[1])
            box.insert("end", msg + "\n", ("logprog",))
            box.see("end")
        except tk.TclError:
            pass

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    # 普通日志接在进度行后面：进度行就此定住，不再被改写
                    self.logbox.tag_remove("logprog", "1.0", "end")
                    self.logbox.insert("end", payload + "\n")
                    self.logbox.see("end")
                elif kind == "logprog":
                    self.log_progress(payload)
                elif kind == "book":
                    self.add_book(payload)
                elif kind == "chaprow":
                    # 批量试分逐本回填：先写回书籍章数（①书库同步），再追加③页结果行
                    # 校验栏只放这本书的汇总；正常的书不着色，只有异常的书整行标红
                    n, b, cnt, ck_txt, ck_bad = payload
                    self._set_book_chaps(b, cnt)
                    if hasattr(self, "tv_chap"):
                        iid = self.tv_chap.insert(
                            "", "end", tags=("bad",) if ck_bad else (),
                            values=(n, b["title"] or os.path.splitext(b["name"])[0],
                                    str(cnt), ck_txt))
                        self._chap_rows[iid] = b  # 双击这一行 → 单本试分这本书
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
        # 分章页按钮同步禁用：批量试分/分章与导出、清洗共用同一套后台任务与「停止」
        for b in (getattr(self, "btn_chap_try", None), getattr(self, "btn_chap_all", None),
                  getattr(self, "btn_chap_tree", None)):
            if b is not None:
                b.configure(state="disabled" if busy else "normal")

    def do_stop(self):
        self.cancel = True
        self.status_var.set(self.S["stopping"])

    def switch_lang(self, lang):
        """窗口内即时切换语言：就地销毁并重建全部界面控件（数据留在 self.books）。"""
        if lang == self.lang:
            return
        if self.busy:
            messagebox.showinfo(self.S["lang_busy"], self.S["lang_busy_msg"])
            return
        try:
            cur_tab = self.nb.index(self.nb.select())
        except Exception:
            cur_tab = 0
        old_log = ""
        try:
            old_log = self.logbox.get("1.0", "end-1c")
        except Exception:
            pass
        for w in self.root.winfo_children():
            w.destroy()
        # 切语言并保存记忆
        self.lang = lang
        self.S = TEXTS[lang]
        self.cfg["lang"] = lang
        jzcore.save_config(self.cfg)
        # 就地重建（各 _build 方法幂等；复用 __init__ 创建的 var，勾选/输入值天然保留）
        self.root.title(self.S["w_title"] % (APP_CN, APP_EN, APP_VER))
        self._style()
        self._menu()
        self._top(self.root)
        self._tabs(self.root)
        self._log(self.root)
        self._status(self.root)
        self.status_var.set(self.S["st_ready"])
        self.reload_rows()  # books 数据在内存，整表重灌（含勾选状态）
        self._fill_chap_pick()  # 重建后重填「试分书籍」下拉
        try:
            self.nb.select(cur_tab)
        except Exception:
            self.nb.select(0)
        if old_log:
            self.logbox.insert("end", old_log + "\n")
        self.log("✓ Language switched / 语言已切换：%s" % ("English" if lang == EN else "中文"))

    def on_close(self):
        cfg = self.cfg
        cfg["lastdir"] = self.dir_var.get()
        cfg["outdir"] = self.out_var.get()
        cfg["mode"] = self.mode_var.get()
        jzcore.save_config(cfg)
        # 全局分章规则 / 删章记录改过但还没落盘（比如只改了规则没试分）就补一次
        if self._idx_dirty:
            self._save_books_index()
        self.root.destroy()

    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or None)
        if d:
            self.dir_var.set(d)
            self.out_var.set(d.rstrip("\\/") + self.S["out_suffix"])
            self.do_scan()

    def pick_out(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or self.dir_var.get() or None)
        if d:
            self.out_var.set(d)

    def sync_out(self):
        if not self.out_var.get() and self.dir_var.get():
            self.out_var.set(self.dir_var.get().rstrip("\\/") + self.S["out_suffix"])

    def show_text(self, title, body):
        S = self.S
        w = tk.Toplevel(self.root)
        w.title(title)
        _center_win(w, 640, 520)  # 说明窗同样按 DPR 缩放并居中
        # 按钮先占位：正文 expand=True 会把后 pack 的按钮挤成 0 高
        ttk.Button(w, text=S["d_close"],
                   command=w.destroy).pack(side="bottom", pady=px(8))
        t = tk.Text(w, wrap="word", font=FONT, padx=px(12), pady=px(10),
                    relief="flat", borderwidth=0, highlightthickness=0)
        t.insert("1.0", body)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=px(6), pady=(px(6), 0))

    def show_about(self):
        """版权与许可：MIT 全文、署名要求、第三方组件、免责。
        用带滚动的窗口而不是 messagebox——内容长了 messagebox 会截断。"""
        S = self.S
        w = tk.Toplevel(self.root)
        w.title(S["about_win"])
        w.configure(bg=BG)
        w.transient(self.root)
        _center_win(w, 700, 600)

        head = tk.Frame(w, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        head.pack(fill="x", padx=px(10), pady=(px(10), px(6)))
        tk.Label(head, text=S["about_title"] % (APP_CN, APP_EN + " " + APP_VER),
                 bg=CARD, fg=INK, font=FONT_B).pack(anchor="w", padx=px(12),
                                                    pady=(px(9), px(1)))
        tk.Label(head, text=S["about_sub"], bg=CARD, fg=MUTED,
                 font=FONT_S).pack(anchor="w", padx=px(12), pady=(0, px(9)))

        full = S["about_body"].format(ver=APP_VER)

        # 底栏先 pack(side="bottom") 占位，再让正文 expand 吃掉剩余高度
        bar = tk.Frame(w, bg=BG)
        bar.pack(side="bottom", fill="x", padx=px(10), pady=px(10))
        ttk.Button(bar, text=S["b_copy_about"], style="Soft.TButton",
                   command=lambda: self._clip(full)).pack(side="left")
        ttk.Button(bar, text=S["b_copy_mit"], style="Soft.TButton",
                   command=lambda: self._clip(MIT_TEXT)).pack(side="left", padx=px(6))
        ttk.Button(bar, text=S["d_close"],
                   command=w.destroy).pack(side="right")

        body = tk.Frame(w, bg=BG)
        body.pack(fill="both", expand=True, padx=px(10))
        txt = tk.Text(body, wrap="word", font=FONT, bg="#FFFFFF", fg=INK,
                      relief="flat", borderwidth=0, highlightthickness=1,
                      highlightbackground=LINE, highlightcolor=BLUE,
                      padx=px(12), pady=px(10), spacing3=px(2))
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", full)
        txt.configure(state="disabled")

    def _clip(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    # ------------------------------------------------------------ 书库
    def add_book(self, info):
        idx = len(self.books)
        info.setdefault("chapters", -1)  # 章数字段：-1 = 尚未试分
        self.books.append(info)
        rel = info.get("rel", os.path.basename(info["path"]))
        self.tv.insert("", "end", iid=str(idx), values=(
            "✓" if info["sel"] else "", info["title"], info["author"],
            fmt_count(info["chars"], self.lang), info["enc"], self.chap_cell(info),
            jzcore.human_size(info["size"]), rel))
        self.refresh_info()

    def refresh_info(self):
        n = len(self.books)
        m = sum(1 for b in self.books if b["sel"])
        d = self.dup_count()
        s = self.S["lib_info"].format(n, m)
        if d:
            s += self.S["lib_info_dup"].format(d)
        self.info_var.set(s)
        self._refresh_cover_btn()  # 勾选变了，封面按钮上的「已设置 N 本」跟着变

    def chap_cell(self, b):
        """书库「章节」列的显示值：未试分显示 -，试分后显示已切出的章数。

        章数唯一来源是书籍字典的 chapters 字段（scan_file 预置 -1），
        ③ 分章页试分后写回这里，① 书库列表据此渲染，两页共用同一份状态。
        """
        try:
            n = int(b.get("chapters", -1))
        except (TypeError, ValueError):
            n = -1
        return str(n) if n >= 0 else "-"

    def _set_book_chaps(self, b, n):
        """把试分结果写回书籍状态，并即时刷新①书库对应行的「章节」单元格。"""
        b["chapters"] = n
        try:
            iid = str(self.books.index(b))
        except ValueError:
            return
        if self.tv.exists(iid):
            self.tv.set(iid, "chap", self.chap_cell(b))

    def refresh_chap_col(self):
        """按 books 快照重灌全部「章节」单元格（切回①书库时与分章页对齐）。"""
        for i, b in enumerate(self.books):
            iid = str(i)
            if self.tv.exists(iid):
                self.tv.set(iid, "chap", self.chap_cell(b))

    def reload_rows(self):
        """按 books 快照整表重灌（批量清洗改 chars 后刷新书库列表）。"""
        for row in self.tv.get_children():
            self.tv.delete(row)
        for i, b in enumerate(self.books):
            self.tv.insert("", "end", iid=str(i), values=(
                "✓" if b["sel"] else "", b["title"], b["author"],
                fmt_count(b["chars"], self.lang), b["enc"], self.chap_cell(b),
                jzcore.human_size(b["size"]), b.get("rel", os.path.basename(b["path"]))))

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
        S = self.S
        c = Counter(b["md5"] for b in self.books)
        dups = {k for k, v in c.items() if v > 1}
        if not dups:
            messagebox.showinfo(S["d_no_dup"], S["d_no_dup_msg"])
            return
        for i, b in enumerate(self.books):
            b["sel"] = b["md5"] in dups
            self.tv.set(str(i), "sel", "✓" if b["sel"] else "")
        self.refresh_info()
        self.log(S["log_dup_sel"].format(sum(1 for b in self.books if b["sel"])))

    def popup(self, event):
        S = self.S
        row = self.tv.identify_row(event.y)
        if not row:
            return
        self.tv.selection_set(row)
        b = self.books[int(row)]
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label=S["m_open_loc"],
                      command=lambda: self.open_folder(b["path"]))
        m.add_command(label=S["m_open_note"],
                      command=lambda: self.open_file(b["path"]))
        m.add_separator()
        m.add_command(label=S["m_edit_title"],
                      command=lambda: self.edit_book_meta(b, "title"))
        m.add_command(label=S["m_edit_author"],
                      command=lambda: self.edit_book_meta(b, "author"))
        m.add_separator()
        m.add_command(label=S["m_copy_path"],
                      command=lambda: self.copy_path(b["path"]))
        m.add_separator()
        m.add_command(label=S["m_remove_book"],
                      command=lambda: self.remove_book(b))
        m.tk_popup(event.x_root, event.y_root)

    def edit_book_meta(self, b, field):
        """右键「修改书名 / 修改作者」：弹窗手动改一个字段。

        输入框预填当前识别结果；点「确定」（或回车）才写回书籍字典、列表单元格
        和 .deshelf_index.json，点「取消」/Esc/关窗保持原样。书名留空表示回退到
        文件名显示（导出时同样回退），作者留空表示未知。
        """
        S = self.S
        is_title = field == "title"
        label = S["col_title"] if is_title else S["col_author"]
        w = tk.Toplevel(self.root)
        w.title(S["d_edit_title"] if is_title else S["d_edit_author"])
        w.transient(self.root)
        w.configure(bg=BG)
        w.resizable(False, False)

        # 底栏先占位，正文再往上排（与程序内其他弹窗一致）
        bar = ttk.Frame(w)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(10))
        got = {"val": None}

        var = tk.StringVar(value=b.get(field) or "")
        e = ttk.Entry(w, textvariable=var, font=FONT, width=42)
        e.pack(fill="x", padx=px(12), pady=(px(12), 0))
        tip = tk.Label(w, text=S["edit_hint_title"] if is_title else S["edit_hint_author"],
                       bg=BG, fg=MUTED, font=FONT_S, justify="left", anchor="w",
                       wraplength=px(360))
        tip.pack(fill="x", padx=px(14), pady=(px(6), px(4)))

        def _ok(_e=None):
            got["val"] = var.get().strip()
            w.destroy()

        ttk.Button(bar, text=S["d_ok"], style="Accent.TButton",
                   command=_ok).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], style="Soft.TButton",
                   command=w.destroy).pack(side="right", padx=px(6))
        e.bind("<Return>", _ok)
        w.bind("<Escape>", lambda _e: w.destroy())
        e.focus_set()
        e.select_range(0, "end")
        # 高度按内容实测：中英文提示行数不同，写死高度不是留白就是挤压
        w.update_idletasks()
        _center_win(w, 420, int(round(w.winfo_reqheight() / max(_SCALE, 0.01))))
        w.grab_set()
        self.root.wait_window(w)
        if got["val"] is None:
            return  # 取消：什么都不动
        val = got["val"]
        if val == (b.get(field) or ""):
            return  # 没改动：不写索引也不刷日志
        b[field] = val
        # 用 is 定位行号：dict == dict 可能在内容相同时命中别的书
        idx = next((i for i, x in enumerate(self.books) if x is b), -1)
        if idx >= 0 and self.tv.exists(str(idx)):
            self.tv.set(str(idx), field, val)
        d = self.dir_var.get().strip()
        if d and os.path.isdir(d):
            self.save_index_now(d)
        shown = val or (S["meta_untitled"] if is_title else S["meta_no_author"])
        self.status_var.set(S["st_meta_saved"].format(label, shown))
        self.log(S["log_meta_saved"].format(label, shown))

    def remove_book(self, b):
        """只从列表里移除，不动磁盘文件（手滑添加的文件靠这个收拾）。"""
        S = self.S
        try:
            self.books.remove(b)
        except ValueError:
            return
        self.reload_rows()
        self.mark_dup()
        d = self.dir_var.get().strip()
        if d and os.path.isdir(d):
            self.save_index_now(d)
        self.log(S["log_book_removed"].format(b.get("title") or b.get("path", "")))

    def open_folder(self, path):
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except OSError:
            self.log(self.S["log_open_fail"].format(path))

    def open_file(self, path):
        try:
            os.startfile(path)
        except OSError:
            self.log(self.S["log_file_fail"].format(path))

    def copy_path(self, path):
        self.root.clipboard_clear()
        self.root.clipboard_append(path)

    def export_list(self):
        S = self.S
        if not self.books:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[(S["csv_type"], "*.csv")],
                                         initialfile=S["csv_name"])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(S["csv_hdr"] + "\n")
                for b in self.books:
                    f.write('"%s","%s",%d,%s,%d,"%s"\n' % (
                        b["title"].replace('"', '""'), b["author"].replace('"', '""'),
                        b["chars"], b["enc"], b["size"], b.get("rel", "").replace('"', '""')))
            self.log(S["log_csv_ok"].format(p))
        except OSError as e:
            messagebox.showerror(S["d_export_fail"], str(e))

    # ------------------------------------------------------------ 扫描
    def pick_files(self):
        """单独挑几个 txt 进书库，不必先选目录整目录扫（对齐网页版「选择 TXT 文件」）。"""
        S = self.S
        if self.busy:
            return
        ps = filedialog.askopenfilenames(
            title=S["d_pick_files"],
            filetypes=[(S["flt_txt"], "*.txt *.text"), (S["flt_all"], "*.*")])
        if not ps:
            return
        self.add_files(list(ps))

    def add_files(self, paths):
        S = self.S
        root = self.dir_var.get().strip()
        if not root or not os.path.isdir(root):
            root = os.path.dirname(os.path.abspath(paths[0]))
            self.dir_var.set(root)
            self.log(S["log_root_fallback"].format(root))
        have = set()
        for b in self.books:
            try:
                have.add(os.path.normcase(os.path.abspath(b["path"])))
            except KeyError:
                pass
        added = skipped = 0
        for p in paths:
            ap = os.path.abspath(p)
            if os.path.normcase(ap) in have:
                skipped += 1
                continue
            try:
                info = jzcore.scan_file(ap)
            except Exception as e:
                self.log(S["log_skip"].format(os.path.basename(p), e))
                skipped += 1
                continue
            info["rel"] = os.path.relpath(ap, root)
            info["sel"] = True
            self.add_book(info)
            have.add(os.path.normcase(ap))
            added += 1
        if added:
            self.mark_dup()
            self.save_index_now(root)
        self.log(S["log_add_files"].format(added, skipped))
        extra = S["log_add_skip_only"].format(skipped) if skipped and not added else ""
        self.status_var.set(S["st_add_files"].format(added, extra))

    def save_index_now(self, root):
        """立刻落盘索引：手动添加/删除书籍后，下次打开不用重扫也能看到。

        全局分章规则（所有书共用）写在顶层 chap_re，书条目里只留本书自己的
        book_re / chap_del，两者互不影响。_chap_re 这类下划线开头的字段是
        运行期状态（上次切分用的规则、清洗快照等），不写进索引。
        """
        self._idx_dirty = False
        try:
            jzcore.save_index(root, {
                "root": root, "scanned": time.time(),
                "chap_re": self.custom_re.get().strip(),  # 全局规则：所有书共用
                "books": [{k: v for k, v in b.items()
                           if k != "path" and k != "_chap_re"}
                          for b in self.books]})
        except OSError:
            pass

    def do_scan(self, fresh=False):
        S = self.S
        d = self.dir_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showwarning(S["d_dir_invalid"], S["d_dir_invalid_msg"])
            return
        if self.busy:
            return
        if not fresh and self.load_index(d):
            return
        self.clear_books()
        self.set_busy(True)
        self.cancel = False
        self.log(S["log_scan_start"].format(d))
        threading.Thread(target=self.scan_worker, args=(d,), daemon=True).start()

    def clear_books(self):
        self.books = []
        for i in self.tv.get_children():
            self.tv.delete(i)
        self.refresh_info()

    def scan_worker(self, root):
        S = self.S
        files = []
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.lower().endswith((".txt", ".text")):
                    files.append(os.path.join(dp, f))
        files.sort()
        total = len(files)
        self.q.put(("log", S["log_found"].format(total)))
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
                self.q.put(("log", S["log_skip"].format(os.path.basename(p), e)))
            if i % 5 == 0 or i == total:
                self.q.put(("prog", (i, total, S["prog_scan"].format(i, total))))
        self.q.put(("done", ("scan", root, got, total)))

    def load_index(self, root):
        S = self.S
        data = jzcore.load_index(root)
        books = data.get("books") or []
        if not books:
            return False
        # 全局分章规则存在索引顶层（所有书共用），打开书库时恢复回输入框；
        # 旧索引若把它塞进了书条目，按「本书规则」迁移，别污染全局规则
        if "chap_re" in data:
            self.custom_re.set(data.get("chap_re") or "")
        self._idx_dirty = False  # 刚读进来的东西不用再写回去
        self.clear_books()
        missing = 0
        for b in books:
            old_re = b.pop("chap_re", None)  # 旧字段：本书规则
            if old_re and not b.get("book_re"):
                b["book_re"] = old_re
            b.pop("chap_re_used", None)  # 旧字段：生效规则由 book_re/顶层 chap_re 算
            # 手工建章的记录（原文行号 + 章节名）：脏数据一律丢掉，别让切分崩
            adds = jzcore.manual_records(b.pop("chap_add", None))
            if adds:
                b["chap_add"] = adds
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
        if not self.out_var.get():
            self.out_var.set(root.rstrip("\\/") + S["out_suffix"])
        stale_n = sum(1 for b in self.books if b.get("stale"))
        extra = S["log_idx_stale"].format(stale_n) if stale_n else ""
        self.log(S["log_idx_load"].format(
            len(self.books), time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("scanned", 0))), extra))
        if missing:
            self.log(S["log_idx_missing"].format(missing))
        return True

    def mark_dup(self):
        c = Counter(b["md5"] for b in self.books)
        for i, b in enumerate(self.books):
            if c[b["md5"]] > 1:
                self.tv.item(str(i), tags=("dup",))

    def on_done(self, payload):
        S = self.S
        kind = payload[0]
        self.set_busy(False)
        self.prog_var.set(0)
        if kind == "scan":
            _s, root, got, total = payload
            self.mark_dup()
            self.status_var.set(S["st_scan_done"].format(got, total))
            self.log(S["log_scan_done"].format(got, S["log_stopped"] if self.cancel else ""))
            self.save_index_now(root)  # 与手动增删书同一套写法（含顶层全局规则）
        elif kind == "run":
            _s, ok, fail, outdir = payload
            self.reload_rows()  # 回写实际切分章数/字数后重灌书库列表
            self.mark_dup()
            self.status_var.set(S["st_run_done"].format(ok, fail))
            self.log(S["log_run_done"].format(ok, fail) + "，输出目录 %s" % outdir)
            if outdir and os.path.isdir(outdir) and not self.cancel:
                try:
                    os.startfile(outdir)
                except OSError:
                    pass
        elif kind == "clean":
            _s, ok, rm_sum, cancelled = payload
            self.reload_rows()
            self.status_var.set(S["st_clean_done"].format(ok, "{:,}".format(rm_sum)))
            self.log(S["log_clean_done"].format(ok, "{:,}".format(rm_sum))
                     + (S["log_stopped"] if cancelled else ""))
        elif kind == "chap":
            _s, ok_n, sum_n, bad, cancelled, ck_bad = payload
            self.refresh_chap_col()
            extra = S["chap_ck_books"].format(ck_bad) if ck_bad else ""
            self.chap_var.set(S["chap_all_done"].format(ok_n, sum_n, bad) + extra
                              + S["chap_dbl_hint"])
            st = S["st_chap_done"].format(ok_n, sum_n, bad)
            self.status_var.set(st + (S["log_stopped"] if cancelled else ""))
            self.log(S["log_chap_done"].format(ok_n, bad, sum_n) + extra
                     + (S["log_stopped"] if cancelled else ""))
        # 后台线程只改书籍字典（分章规则 / 删章记录），落盘统一回主线程做
        if self._idx_dirty:
            self._save_books_index()

    # ------------------------------------------------------------ 预览
    def first_selected(self):
        for b in self.books:
            if b["sel"]:
                return b
        return None

    def active_rules(self):
        return [i for i, v in self.rule_vars.items() if v.get()]

    # ------------------------------------------------------------ 规则联动
    # 插图两条规则是「含网址的行」的子项：没勾网址规则时它们没意义，不显示；
    # 「插图链接校验」是「保留插图链接」的加强版，前一条没开就不允许勾。
    _IMG_SUB_RULES = ("imgkeep", "imgcheck")

    def _rule_visible(self, rid):
        if rid in self._IMG_SUB_RULES:
            return bool(self.rule_vars["url"].get())
        return True

    def refresh_rule_state(self):
        """按「含网址的行」「保留插图链接」的勾选状态，显隐、启停插图两条规则。"""
        frames = getattr(self, "_rule_frames", None)
        if not frames:
            return
        prev = None
        for r in jzcore.RULES:
            row = frames.get(r["id"])
            if not self._alive(row):
                continue
            if not self._rule_visible(r["id"]):
                row.pack_forget()
                continue
            if not row.winfo_manager():
                if prev is None:
                    row.pack(anchor="w", fill="x")
                else:
                    row.pack(anchor="w", fill="x", after=prev)
            prev = row
        cb = self._rule_cb_by_id.get("imgcheck")
        if self._alive(cb):
            on = bool(self.rule_vars["imgkeep"].get())
            cb.state(["!disabled"] if on else ["disabled"])
            lab = self._rule_tip_by_id.get("imgcheck")
            if self._alive(lab):
                lab.configure(foreground="#777777" if on else "#B4B4B4")
        cv = getattr(self, "_rules_canvas", None)
        inner = getattr(self, "_rule_inner", None)
        if self._alive(cv) and self._alive(inner):
            try:
                cv.update_idletasks()
                cv.configure(scrollregion=cv.bbox("all"))
            except Exception:
                pass
        self.refresh_imgdl_state()

    @staticmethod
    def _alive(w):
        """控件是否还在：切换语言会把整棵界面树销毁后重建，旧引用会先失效一阵。"""
        try:
            return w is not None and bool(w.winfo_exists())
        except Exception:
            return False

    def refresh_imgdl_state(self):
        """「下载插图链接」跟随清洗页的「保留插图链接」：没开就置灰且强制不勾。

        正文里没有插图链接可下时，这个选项只会让用户以为下了东西，所以默认关死；
        关掉前一条时顺手清空勾选，免得上演“灰着却勾着”的坑。
        注意：切语言时清洗页先建、导出页后建，这一步可能发生在「下载插图链接」
        还没重建出来的时候，旧控件又已销毁 —— 所以必须先确认控件还活着。
        """
        cb = getattr(self, "cb_imgdl", None)
        if not self._alive(cb):
            return
        on = bool(self.rule_vars["imgkeep"].get())
        cb.state(["!disabled"] if on else ["disabled"])
        if not on and self.img_dl_var.get():
            self.img_dl_var.set(False)

    def img_download(self):
        """主线程取当前选择：清洗规则没开「保留插图链接」时一律按不下载处理。"""
        return bool(self.img_dl_var.get()) and bool(self.rule_vars["imgkeep"].get())

    def refresh_epub_opts_state(self):
        """版面主题 / 封面只作用于 EPUB：没勾「导出 EPUB」时整组置灰。

        值本身留着（取消勾选再勾回来不用重选），只是不让改。
        """
        on = bool(self.fmt_vars["epub"].get())
        for w in (getattr(self, "lb_theme", None),
                  getattr(self, "btn_theme", None), getattr(self, "btn_cover", None)):
            if self._alive(w):
                w.state(["!disabled"] if on else ["disabled"])

    def set_rules(self, val):
        for r in jzcore.RULES:
            v = self.rule_vars[r["id"]]
            v.set(val if val is not None else r["id"] in jzcore.DEFAULT_ON)

    def set_rule_ids(self, ids):
        """按 id 列表设置内置规则勾选（规则包导入用）。"""
        want = set(ids or [])
        for r in jzcore.RULES:
            self.rule_vars[r["id"]].set(r["id"] in want)

    def _save_custom(self):
        self.cfg["custom_rules"] = list(self.custom_rules)
        jzcore.save_config(self.cfg)

    def import_rules(self):
        S = self.S
        p = filedialog.askopenfilename(
            title=S["b_imp_rules"],
            filetypes=[("卷帙规则包", "*.json"), ("所有文件", "*.*")])
        if not p:
            return
        try:
            ids, cust, name, bad = jzcore.load_rules_pack(p)
        except ValueError as e:
            messagebox.showerror(S["d_error"], str(e))
            return
        self.set_rule_ids(ids)
        self.custom_rules = cust
        self._save_custom()
        msg = S["log_rules_loaded"].format(len(ids), len(cust), name or "-")
        if bad:
            msg += S["log_rules_bad"].format(bad)
        self.log(msg)
        messagebox.showinfo(S["d_info"], msg)

    def export_rules(self):
        S = self.S
        p = filedialog.asksaveasfilename(
            title=S["b_exp_rules"], defaultextension=".json",
            initialfile="卷帙规则包.json",
            filetypes=[("卷帙规则包", "*.json")])
        if not p:
            return
        try:
            jzcore.save_rules_pack(p, self.active_rules(), self.custom_rules)
        except OSError as e:
            messagebox.showerror(S["d_error"], str(e))
            return
        msg = S["log_rules_saved"].format(p)
        self.log(msg)
        messagebox.showinfo(S["d_info"], msg)

    def edit_custom(self):
        """弹窗编辑自定义规则：一行一条，``动作||正则||说明``。"""
        S = self.S
        w = tk.Toplevel(self.root)
        w.title(S["b_edit_rules"])
        _center_win(w, 760, 520)
        ttk.Label(w, text=S["custom_hint"], foreground="#666666", font=FONT_S,
                  wraplength=px(720), justify="left").pack(anchor="w", padx=px(10),
                                                           pady=(px(8), px(4)))
        t = tk.Text(w, wrap="none", font=MONO, bg="#FFFFFF", relief="solid", bd=1)
        t.pack(fill="both", expand=True, padx=px(10), pady=px(4))
        t.insert("1.0", jzcore.custom_to_text(self.custom_rules))
        bar = ttk.Frame(w)
        bar.pack(fill="x", padx=px(10), pady=px(10))

        def _ok():
            rules, bad = jzcore.text_to_custom(t.get("1.0", "end"))
            self.custom_rules = rules
            self._save_custom()
            msg = S["log_rules_edit"].format(len(rules))
            if bad:
                msg += S["log_rules_bad"].format(bad)
            self.log(msg)
            w.destroy()

        ttk.Button(bar, text=S["d_ok"], command=_ok).pack(side="right")
        ttk.Button(bar, text=S["d_cancel"], command=w.destroy).pack(side="right", padx=px(6))

    def _fill_before(self, text, stats):
        """左栏原文：被清洗掉的内容标红（与 Web 版预览同一套标记）。

        整行被删的整行标红；行内只挖掉一段的（HTML 标签、行尾网址）只标那一段，
        其余正文保持原色，所以「划线的是垃圾、没标的是正文」一眼能分清。
        """
        t = self.txt_before
        t.configure(state="normal")
        t.delete("1.0", "end")
        dels = stats.get("del") or set()
        cuts = stats.get("cut") or {}
        marks = stats.get("mark") or {}
        for line in text.splitlines()[:400]:
            if line in dels:
                t.insert("end", line + "\n", "del")
                continue
            ranges = list(marks.get(line, ()))
            if line in cuts:
                ranges.append((cuts[line], len(line)))
            if not ranges:
                t.insert("end", line + "\n")
                continue
            ranges.sort()
            pos = 0
            for start, end in ranges:
                a = min(max(start, pos), len(line))
                z = min(max(end, a), len(line))
                if a > pos:
                    t.insert("end", line[pos:a])
                if z > a:
                    t.insert("end", line[a:z], "del")
                pos = z
            t.insert("end", line[pos:] + "\n")
        t.configure(state="disabled")

    def preview_clean(self):
        S = self.S
        b = self.first_selected()
        if not b:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        try:
            text = jzcore.load_text(b["path"])
            rules = self.active_rules()
            stats = {}
            cleaned, removed = jzcore.clean_text(text, rules, stats, self.custom_rules,
                                                 want_del=True)
        except Exception as e:
            messagebox.showerror(S["d_preview_fail"], str(e))
            return
        self._fill_before(text, stats)
        t = self.txt_after
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", "\n".join(cleaned.splitlines()[:400]))
        t.configure(state="disabled")
        cut = stats.get("trimmed", 0)
        key = "cmp_var_cut" if cut else "cmp_var"
        dup = stats.get("jsdup", 0)
        merged = stats.get("merged", 0)
        glued = stats.get("glued", 0)
        wrap_skip = stats.get("wrap_skip", 0)
        msg = S[key].format(removed, len(text), len(cleaned), cut)
        if dup:
            msg += S["cmp_jsdup"].format(dup)
        img_kept = stats.get("img", 0)
        if img_kept:
            msg += S["cmp_img"].format(img_kept)
        if merged:
            msg += S["cmp_merge"].format(merged)
        if glued:
            msg += S["cmp_glue"].format(glued)
        if wrap_skip:
            msg += S["cmp_wrap_skip"].format(wrap_skip)
        # 两条段落修复默认关：关着也要告诉用户文件里有几处，否则他会以为没问题
        if "punct" not in rules or "unwrap" not in rules:
            scan = jzcore.scan_para_issues(text.splitlines())
            if "punct" not in rules and scan["lone"]:
                msg += S["cmp_hint_lone"].format(scan["lone"])
            if "unwrap" not in rules and scan["blocks"]:
                msg += S["cmp_hint_wrap"].format(scan["blocks"])
        self.cmp_var.set(msg)
        self.log("《%s》规则 %d 条，删除 %d 行，只裁行尾 %d 行，简繁重复 %d 行，合并断行 %d 处"
                 % (b["title"], len(rules), removed, cut, dup, merged))

    def start_clean(self):
        """批量清洗：对勾选书籍按当前规则清洗，结果缓存到内存供后续分章/导出复用。"""
        S = self.S
        sel = [b for b in self.books if b["sel"]]
        if not sel:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        if not self.active_rules():
            messagebox.showinfo(S["d_rule_none"], S["d_rule_none_msg"])
            return
        if self.busy:
            return
        # 规则必须在主线程预取：tk 变量在线程内读取会 RuntimeError
        rules = self.active_rules()
        self.set_busy(True)
        self.cancel = False
        threading.Thread(target=self.clean_worker, args=(sel, rules), daemon=True).start()

    def clean_worker(self, sel, rules):
        S = self.S
        total = len(sel)
        ok = rm_sum = 0
        for i, b in enumerate(sel, 1):
            if self.cancel:
                break
            self.q.put(("prog", (i - 1, total, S["prog_clean"].format(i, total, b["title"]))))
            try:
                text = jzcore.load_text(b["path"])
                b["_clean_before"] = len(text.splitlines())  # 汇总里显示「原 N 行 → 洗后 M 行」
                st = {}
                # 手工建章的标题行不许被洗掉：否则那一章在清洗后的正文里失锚
                text, removed = jzcore.clean_text(
                    text, rules, st, self.custom_rules, want_trace=True,
                    protect_lines=_chap_protect(jzcore.manual_records(b.get("chap_add"))))
                b["_clean"] = text  # 清洗快照：分章/导出优先使用（与 Web 版一致）
                # 清理明细随快照一起留着：「导出分发」的清洗内容汇总直接复用它，
                # 免得为了出一份汇总把已经洗过的正文再洗一遍
                b["_clean_trace"] = st.get("trace") or []
                b["_clean_blank"] = st.get("blank", 0)  # 汇总里的「删除空行 N 行」
                b["chars"] = len(text)
                b["chapters"] = -1  # 正文已变，旧章数作废（与 Web 版一致）
                rm_sum += removed
                ok += 1
            except Exception as e:
                self.q.put(("log", S["log_book_fail"].format(i, total, b["title"], e)))
        self.q.put(("prog", (total, total, S["prog_done"])))
        self.q.put(("done", ("clean", ok, rm_sum, self.cancel)))

    def _fill_chap_pick(self):
        """同步「试分书籍」下拉：列出书库全部书；保持当前选中，失效则默认勾选首本。"""
        names = [(b["title"] or os.path.splitext(b["name"])[0]) for b in self.books]
        try:
            self.cb_chap["values"] = names
        except Exception:
            return
        cur = self.chap_pick_text.get()
        if cur not in names:
            fb = self.first_selected()
            cur = (fb["title"] or os.path.splitext(fb["name"])[0]) if fb else (names[0] if names else "")
        self.chap_pick_text.set(cur or "")

    def _re_for(self, b, fallback=None):
        """这本书实际生效的分章正则，按顺序取：

        1. 本书规则 b["book_re"]（只对这一本生效，随书条目落盘）；
        2. 全局规则 self.custom_re（所有书共用，随索引顶层 chap_re 落盘）；
        3. 都没有 → 内置默认规则库（返回 None，split_chapters 内部用内置规则）。
        后台线程不能读 tk 变量，所以调用方必须把全局值经 fallback 传进来。
        """
        own = (b.get("book_re") or "").strip()
        if own:
            return own
        return fallback if fallback is not None else (self.custom_re.get().strip() or None)

    def sync_book_re(self):
        """切换「试分书籍」时：先把上一步编辑存回原书，再载入新书的规则。"""
        self.store_book_re()
        b = self.picked_book()
        self._re_book = b
        self.book_re_var.set((b.get("book_re") or "") if b else "")
        self.refresh_re_state()

    def store_book_re(self):
        """把「本书规则」输入框写回它对应的那本书（空则清掉，回到用全局规则）。

        只动书条目里的 book_re：全局规则是 self.custom_re（索引顶层 chap_re），
        所有书共用，这里一个字都不改。
        本书规则一改，章节列表就按新规则重排：旧的删章下标随即作废。
        """
        # 只认 _re_book（输入框当前展示的是哪本书）：没对齐时写回等于拿旧内容
        # 覆盖别的书，宁可不动 —— 对齐由 sync_book_re / _re_align 负责
        b = self._re_book
        if not b:
            return
        val = ""
        try:
            val = self.book_re_var.get().strip()
        except Exception:
            return
        if val == (b.get("book_re") or ""):
            self.refresh_re_state()
            return  # 没改动：不写索引、不清记录
        if val:
            b["book_re"] = val
        else:
            b.pop("book_re", None)  # 切回全局规则
        # 列表随规则重排：按下标记的删章记录跟着作废
        if b.pop("chap_del", None):
            self.log(self.S["log_chap_del_reset"])
        self._save_books_index()
        self.refresh_re_state()

    def _re_align(self, b):
        """切分前把「本书规则」输入框对齐到这本书，避免张冠李戴。

        对的就是这本 → 把可能的改动写回去；还没对齐（刚打开程序/刚载入索引）
        → 先把书里存的规则载入输入框，绝不能反过来拿输入框的旧内容覆盖它。
        """
        if self._re_book is b:
            self.store_book_re()
            return
        self._re_book = b
        self.book_re_var.set((b.get("book_re") or "") if b else "")
        self.refresh_re_state()

    def clear_book_re(self):
        self.book_re_var.set("")
        self.store_book_re()

    def refresh_re_state(self):
        try:
            b = self._re_book
            self.re_state.set(self.S["book_re_on"] if (b and b.get("book_re")) else "")
        except Exception:
            pass

    def show_re_help(self):
        """「常用写法」：把常见的章节标题写法连正则列出来，选中一条直接填进对应的框。"""
        S = self.S
        w = tk.Toplevel(self.root)
        w.title(S["re_help_title"])
        w.configure(bg=BG)
        w.transient(self.root)
        _center_win(w, 820, 640)

        # 底栏先占位，再让列表 expand 吃剩余高度（否则按钮被挤没）
        bar = tk.Frame(w, bg=BG)
        bar.pack(side="bottom", fill="x", padx=px(10), pady=px(10))
        ttk.Button(bar, text=S["re_close"], command=w.destroy).pack(side="right")
        ttk.Button(bar, text=S["re_fill_book"], style="Soft.TButton",
                   command=lambda: fill(False)).pack(side="right", padx=px(6))
        ttk.Button(bar, text=S["re_fill_global"], style="Accent.TButton",
                   command=lambda: fill(True)).pack(side="right")

        tip = tk.Label(w, text=S["re_help_intro"], bg=CARD, fg=INK, font=FONT_S,
                       justify="left", anchor="w", wraplength=px(770),
                       highlightthickness=1, highlightbackground=LINE,
                       padx=px(10), pady=px(8))
        tip.pack(fill="x", padx=px(10), pady=(px(10), px(6)))

        body = ttk.Frame(w)
        body.pack(fill="both", expand=True, padx=px(10), pady=(0, px(4)))
        tv = ttk.Treeview(body, columns=("use", "re"), show="headings", height=10)
        tv.heading("use", text=S["re_tpl_col"])
        tv.heading("re", text=S["re_tpl_re"])
        tv.column("use", width=px(250), anchor="w", stretch=False)
        tv.column("re", width=px(500), anchor="w")
        sb = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        lang_i = 0 if self.lang == ZH else 1
        for t in jzcore.CHAP_TPL:
            tv.insert("", "end", values=(t[lang_i], t[2]))
        kids = tv.get_children()
        if kids:
            tv.selection_set(kids[0])
            tv.focus(kids[0])
        tv.bind("<Double-1>", lambda _e: fill(True))

        def fill(glob):
            sel = tv.selection()
            if not sel:
                return
            pat = tv.item(sel[0], "values")[1]
            if glob:
                self.custom_re.set(pat)
                w.destroy()
                return
            b = self.picked_book()
            if not b:
                messagebox.showinfo(S["re_help_title"], S["re_no_book"], parent=w)
                return
            self._re_book = b
            self.book_re_var.set(pat)
            self.store_book_re()
            w.destroy()

    def picked_book(self):
        """单本试分目标 = 下拉所选；下拉无有效值时回退勾选首本。"""
        self._fill_chap_pick()
        t = self.chap_pick_text.get()
        for b in self.books:
            if (b["title"] or os.path.splitext(b["name"])[0]) == t:
                return b
        return self.first_selected()

    def _on_tab_changed(self, _e=None):
        """切换页签时对齐两页共享状态：③ 同步试分下拉，① 重刷「章节」列。"""
        try:
            idx = self.nb.index("current")
        except Exception:
            return
        if idx == 2:
            self._fill_chap_pick()
            self.sync_book_re()  # 「本书规则」输入框对齐到下拉选中的那本书
        elif idx == 0:
            self.refresh_chap_col()

    def _chap_build(self, b):
        """按当前规则切这本书，返回 (完整切分结果, 生效的章节正则, 各章起始行, 原文)。

        起始行是每章标题在原文里的行号（0 基），正文预览按它定位并按原文
        逐行显示（空行、缩进、特殊空白一律原样保留，不做任何压缩）。
        这里不剔除「已删除的章节」：删除记录随时会变，统一由 _chap_final 处理。
        用户手动创建的章节（b["chap_add"]）在这里并进切分结果：清洗时先护住
        它们标题行的原文，再按记录里的行号（洗过牌就按内容）落位。
        """
        self._re_align(b)
        custom = self._re_for(b, self.custom_re.get().strip() or None)
        if self._chap_rule_sync(b, custom):
            self.log(self.S["log_chap_del_reset"])
        if self._idx_dirty:
            self._save_books_index()  # 全局规则改过：顺手把顶层 chap_re 写回索引
        adds = jzcore.manual_records(b.get("chap_add"))
        text = b.get("_clean")
        if text is None:
            text = jzcore.load_text(b["path"])
            rules = self.active_rules()
            if rules:
                text, _r = jzcore.clean_text(text, rules, None, self.custom_rules,
                                            protect_lines=_chap_protect(adds))
        located = jzcore.split_chapters_located(
            text, custom, jzcore.manual_lines(adds, text))
        chapters = [(t, body) for t, body, _ln in located]
        starts = [ln for _t, _body, ln in located]
        return chapters, custom, starts, text

    def _chap_rule_sync(self, b, custom, save=True):
        """记住这本书的列表是按哪条规则切出来的（只在内存，不写索引）。

        生效规则本来就能由 book_re / 顶层 chap_re / 内置规则算出来，不用另存；
        但「删除章节」记的是下标，规则一换下标就指向别的章，所以拿上一次切分
        用的规则比一下，变了才把删除记录清掉。
        只碰内存标记和 chap_del：全局规则与本书 book_re 都不改。
        save=False 供后台线程用：线程里不碰 tk，落盘交给主线程（见 on_done）。
        """
        used = (custom or "").strip()
        prev = b.get("_chap_re")  # 上次切分用的规则，私有字段，不落盘
        b["_chap_re"] = used
        if prev is None or prev == used:
            return False  # 首次切分（含刚载入索引）：按现规则认，删章记录仍有效
        had_del = bool(b.pop("chap_del", None))
        if had_del:
            if save:
                self._save_books_index()
            else:
                self._idx_dirty = True
        return had_del

    def _chap_apply_del(self, b, chapters):
        """只从目录里去掉被删的章，正文一条不丢地并进相邻章节。

        规则：有上一章 → 「标题 + 正文」追加到上一章正文末尾；
        书开头就被删（没有上一章）→ 接到下一章正文开头（仍按阅读顺序）；
        只有标题没有正文的上级章节条目 → 直接去掉，不往正文里塞标题；
        极端情况整本条目都被删（界面上会拦住最后一条）→ 收成一章保住正文。
        返回 (目录里的章节, 各自在原切分结果里的下标)：
        下标只用于把表格行对回原书，同名的章互不牵连（见 _chap_rule_sync）。
        """
        dels = {int(x) for x in (b.get("chap_del") or [])
                if isinstance(x, int) and not isinstance(x, bool)}
        if not dels:
            return list(chapters), list(range(len(chapters)))
        kept, idx, pending = [], [], []
        for i, (title, body) in enumerate(chapters):
            if i in dels:
                if not body.strip():
                    # 只有标题、没有正文（「部/卷」这类上级章节条目）：
                    # 目录里删掉即可，没有正文要并进邻章，别把标题混进正文。
                    continue
                # 标题 + 正文按原文那样紧挨着（空行留给「与上一章正文之间」）
                block = title + "\n" + body.strip("\n")
                if kept:
                    kept[-1] = (kept[-1][0], _join_blocks(kept[-1][1], block))
                else:
                    pending.append(block)  # 还没有上一章：攒着，等下一章开头再放
                continue
            if pending:
                body = _join_blocks(*(pending + [body]))
                pending = []
            kept.append((title, body))
            idx.append(i)
        if not kept:
            # 全书条目都被删：正文不能跟着消失，用第一章的标题收成一章
            first = chapters[0][0]
            rest = [_join_blocks(t, bd) for t, bd in chapters[1:]]
            kept = [(first, _join_blocks(chapters[0][1], *rest))]
            idx = [0]
        return kept, idx

    def _chap_final(self, b, full):
        """由完整切分结果得到「最终章节」：(chapters, ck, 去掉了几个目录条目, 各章下标)。

        列表、导出章节树、EPUB/分章 TXT 都走这一个出口，所以目录与列表永远一致。
        """
        chapters, idx = self._chap_apply_del(b, full)
        ck = jzcore.check_chapters([t for t, _body in chapters], self.lang)
        return chapters, ck, len(full) - len(chapters), idx

    def export_chap_tree(self):
        """把下拉框选中这本书的章节树导出到书库目录：原名_章节树.txt。"""
        S = self.S
        b = self.picked_book()
        if not b:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        outdir = self.out_var.get().strip()  # 导出到「导出分发」页选的输出目录
        if not outdir:
            messagebox.showwarning(S["d_tree_outdir"], S["d_tree_outdir_msg"])
            return
        cache = self._chap_cache_get(
            b, self._re_for(b, self.custom_re.get().strip() or None))
        try:
            # 刚用同一本书、同一正则、同一界面语言、同一批手工章节切过就直接复用
            if cache:
                full = cache["full"]
            else:
                full, _custom, _starts, _text = self._chap_build(b)
            chapters, ck, gone, idx = self._chap_final(b, full)
        except ValueError as e:
            messagebox.showerror(S["d_re_bad"], str(e))
            return
        except Exception as e:
            messagebox.showerror(S["d_export_fail"], str(e))
            return
        # 底部章节列表还是空的（没先点「试分章节」），或者展示的是别的书：顺手把这次
        # 切出来的结果列出来，免得导出了文件、界面上却一片空白看不出切成了什么
        if (not self.tv_chap.get_children()
                or (not getattr(self, "_chap_batch", False)
                    and getattr(self, "_chap_view_path", None) != b["path"])):
            self._fill_chap_table(b, chapters, ck, gone, idx)
        titles = [t for t, _body in chapters]
        total = sum(len(x[1]) for x in chapters)
        head = (S["tr_book"].format(b["title"] or b["name"]),
                S["tr_src"].format(b["path"]),
                S["tr_split"].format(len(chapters), "{:,}".format(total), ck["levels"]),
                S["tr_check"].format(ck["summary"]))
        body = jzcore.chapter_tree_report(titles, ck, head, lang=self.lang)
        name = os.path.splitext(b["name"] or os.path.basename(b["path"]))[0]
        bad = '\\/:*?"<>|'
        name = "".join("_" if c in bad else c for c in name).strip() or "book"
        # 统一成同一套分隔符：输出目录可能是 C:/a/b，拼上文件名会变成 C:/a/b\x.txt
        outdir = os.path.normpath(outdir)
        out = os.path.normpath(os.path.join(outdir, name + S["tree_suffix"] + ".txt"))
        try:
            os.makedirs(outdir, exist_ok=True)  # 输出目录还没建就建出来
            with open(out, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(body)
        except Exception as e:
            messagebox.showerror(S["d_export_fail"], str(e))
            return
        self.log(S["log_tree_export"].format(out))
        messagebox.showinfo(S["d_export_ok"], S["d_export_ok_msg"].format(out))

    def on_chap_double(self, evt=None):
        """双击一行：批量列表 → 切到这本书的单本试分；单本列表 → 看这一章正文。"""
        iid = ""
        if evt is not None:
            iid = self.tv_chap.identify_row(evt.y)
        if not iid:
            sel = self.tv_chap.selection()
            iid = sel[0] if sel else ""
        if not iid:
            return
        if not getattr(self, "_chap_batch", False):
            # 行序就是章节在 _chap_final 结果里的序（同名章靠行序区分，不看标题）
            try:
                pos = int(self.tv_chap.index(iid))
            except (ValueError, tk.TclError):
                return
            self.show_chap_content(pos)
            return
        b = (getattr(self, "_chap_rows", None) or {}).get(iid)
        if not b:
            return
        # 下拉框同步成这本书，再按单本流程试分（直接传书对象，避免同名书串台）
        self.chap_pick_text.set(b["title"] or os.path.splitext(b["name"])[0])
        self.sync_book_re()
        self.preview_chap(b)

    def _chap_add_sig(self, b):
        """手工章节的指纹：新建/改名/删掉都会变，用来作废切分缓存。"""
        return tuple((r["line"], r["title"])
                     for r in jzcore.manual_records(b.get("chap_add")))

    def _chap_cache_get(self, b, custom):
        """能复用的切分缓存：同一本、同一正则、同一语言、同一批手工章节。"""
        cache = getattr(self, "_chap_cache", None)
        if (cache and cache.get("path") == b["path"]
                and cache.get("lang") == self.lang
                and cache.get("custom") == custom
                and cache.get("add") == self._chap_add_sig(b)
                and "starts" in cache):
            return cache
        return None

    def _chap_cache_put(self, b, custom, full, starts, text):
        self._chap_cache = {"path": b["path"], "custom": custom, "lang": self.lang,
                            "full": full, "starts": starts, "text": text,
                            "add": self._chap_add_sig(b)}

    def _chap_source(self, b):
        """当前表格对应的章节 + 各章在原文里的起始行 + 原文全文。

        有缓存就复用，不为双击重读全书；删章只改目录，起始行按下标取，
        所以预览窗口里的行号始终是原文行号。
        """
        custom = self._re_for(b, self.custom_re.get().strip() or None)
        cache = self._chap_cache_get(b, custom)
        if cache:
            full, starts, text = cache["full"], cache["starts"], cache["text"]
        else:
            full, custom, starts, text = self._chap_build(b)
            self._chap_cache_put(b, custom, full, starts, text)
        chapters, _ck, _gone, idx = self._chap_final(b, full)
        return chapters, [starts[i] for i in idx], text

    def show_chap_content(self, pos):
        """双击某一章 → 打开逐行正文窗口，定位到这一章（只载入附近的行）。

        正文窗口只渲染目标章上下若干行，滚动时再向上/下补，避免整本书一次性
        插进 Text：几十万字的书开窗也不会卡顿。
        """
        S = self.S
        b = self._chap_view_book or self.picked_book()
        if not b:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        try:
            chapters, starts, text = self._chap_source(b)
        except ValueError as e:
            messagebox.showerror(S["d_re_bad"], str(e))
            return
        except Exception as e:
            messagebox.showerror(S["d_chap_fail"], str(e))
            return
        if not chapters or not starts or not text:
            return
        # 同一时间只留一个正文窗口：再双击直接换成新的一章，不堆一屏子窗口
        old = getattr(self, "_chap_win", None)
        if old is not None:
            try:
                old._close()
            except Exception:
                pass
        try:
            self._chap_win = ChapterReader(self.root, b, text, starts, pos, S,
                                           on_create=self.create_chapter)
        except tk.TclError:
            self._chap_win = None

    def create_chapter(self, b, line, title, orig, rows):
        """正文预览里「创建章节」：把第 line 行当标题行，新建一章。

        line 是预览里那一行的原文行号（0 基），orig 是它当时的原文，rows 是
        全书行数 —— 三个一起记进索引：清洗规则一改行号会平移，靠 orig 才能
        重新对位（见 jzcore.manual_lines）。确认后立刻落盘、重刷章节列表与
        章节树，预览窗口由调用方关闭。返回 True 表示已建好。
        """
        S = self.S
        name = (title or "").strip()
        if not name:
            return False
        # 新建前先记住旧切分结果：删章下标要跟着整体平移，不能一建章就丢记录
        custom = self._re_for(b, self.custom_re.get().strip() or None)
        cache = self._chap_cache_get(b, custom)
        if cache:
            old = [(t, bd, s) for (t, bd), s in zip(cache["full"], cache["starts"])]
        else:
            chapters, custom, starts, _text = self._chap_build(b)
            old = [(t, bd, s) for (t, bd), s in zip(chapters, starts)]
        rec = _manual_rec(line, name, orig, rows)
        adds = [r for r in jzcore.manual_records(b.get("chap_add"))
                if r["line"] != rec["line"]]  # 同一行只留一条：再建一次就是改名
        adds.append(rec)
        b["chap_add"] = jzcore.manual_records(adds)
        full, custom, starts, text = self._chap_build(b)
        if b.get("chap_del"):
            new = [(t, bd, s) for (t, bd), s in zip(full, starts)]
            b["chap_del"] = _remap_del(old, new, {int(x) for x in b["chap_del"]})
        self._chap_cache_put(b, custom, full, starts, text)
        self._save_books_index()      # 立刻落盘：重开程序仍然认这一章
        self._chap_refresh(b)         # 列表 + 章节树 + 校验栏一起重刷
        self.log(S["log_chap_add"].format(b["title"] or b["name"],
                                          int(line) + 1, name,
                                          len(self.tv_chap.get_children())))
        return True

    def preview_chap(self, book=None):
        S = self.S
        self._chap_cols(False)
        b = book or self.picked_book()
        if not b:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        try:
            full, custom, starts, text = self._chap_build(b)
            chapters, ck, gone, idx = self._chap_final(b, full)
        except ValueError as e:
            messagebox.showerror(S["d_re_bad"], str(e))
            return
        except Exception as e:
            messagebox.showerror(S["d_chap_fail"], str(e))
            return
        # 缓存完整切分结果：删章重刷 / 导出章节树 / 正文预览都不必再读盘切一遍
        # （换书/换正则/换语言/换手工章节后自动失效）
        self._chap_cache_put(b, custom, full, starts, text)
        self._fill_chap_table(b, chapters, ck, gone, idx)

    def _fill_chap_table(self, b, chapters, ck, gone=0, idx=None):
        """把单本试分结果写进底部表格 + 汇总行（「试分章节」与「导出章节树」共用）。

        idx 是每行在完整切分结果里的下标（删章按它记，不看标题）。
        """
        S = self.S
        self._chap_cols(False)
        for i in self.tv_chap.get_children():
            self.tv_chap.delete(i)
        self._chap_view_path = b["path"]  # 表格里当前展示的是哪本书
        self._chap_view_book = b
        self._chap_row_index = {}  # 行 → 完整切分结果里的下标
        # 校验：异常章整行标红并在「校验」栏写原因，正常的照原样显示；
        # 二级以上（含）的章节树，上级章节（非最里层）在校验栏标出自己处在第几级
        marks, lvmap = ck["marks"], ck["lv"]
        depths = ck.get("depths") or {}
        for i, (t, body) in enumerate(chapters[:2000], 1):
            msg = marks.get(i)
            lv = lvmap.get(i)
            # 上级章节连「正常」也带上级别：第1级 正常 / 第1级 第2章缺失/顺序错误
            text = msg or ck["ok"]
            if lv:
                text = S["chap_ck_lv"].format(lv) + " " + text
            # 按章节树层级缩进：部 → 卷 → 章 逐级右移，嵌套关系一眼可见
            # （多级标题在切分时已拆成独立条目，这里只需按深度缩进）
            depth = depths.get(i) or 1
            shown = ("    " * (depth - 1) + t) if depth > 1 else t
            iid = self.tv_chap.insert("", "end", tags=("bad",) if msg else (),
                                      values=(i, shown, "{:,}".format(len(body)), text))
            self._chap_row_index[iid] = idx[i - 1] if idx else i - 1
        total = sum(len(x[1]) for x in chapters)
        # 汇总行带上「已删除 N 章」，免得用户以为是自己把书切坏了
        self.chap_var.set(S["chap_sum"].format(b["title"], len(chapters), "{:,}".format(total))
                          + (S["chap_ck_bad"].format(ck["bad"]) if ck["bad"] else "")
                          + (S["chap_del_sum"].format(gone) if gone else "")
                          + S["chap_read_hint"])
        self._set_book_chaps(b, len(chapters))  # 写回书籍状态 → ① 书库「章节」列同步
        # 日志给全本书的章节树概况：多少级、多少章（章数就是切出的章数）
        self.log("《%s》试分 %d 章%s%s" % (b["title"], len(chapters),
                                         S["chap_tree"].format(ck["levels"]),
                                         S["chap_ck_bad"].format(ck["bad"]) if ck["bad"] else ""))

    def popup_chap(self, event):
        """分章列表右键菜单：删除选中的这一章（只作用于当前这本书）。"""
        S = self.S
        if getattr(self, "_chap_batch", False):
            return  # 批量试分的一行是一本书，没有单章可删
        row = self.tv_chap.identify_row(event.y)
        if not row:
            return
        self.tv_chap.selection_set(row)
        # 标题列按层级缩进过：确认框/日志里用去掉缩进的原标题
        title = (self.tv_chap.set(row, "title") or "").strip()
        # 认表格里正在展示的那本书：下拉框可能已经切到别的书但没重试分，
        # 直接按下拉框取会把这章记到另一本书头上
        b = self._chap_view_book or self.picked_book()
        idx = (getattr(self, "_chap_row_index", None) or {}).get(row)
        if not b or not title or idx is None:
            return
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label=S["m_chap_del"],
                      command=lambda: self.del_chapter(b, idx, title))
        if b.get("chap_del"):
            m.add_separator()
            m.add_command(label=S["m_chap_del_undo"],
                          command=lambda: self.undel_chapters(b))
        m.tk_popup(event.x_root, event.y_root)

    def del_chapter(self, b, idx, title):
        """把一章从目录里去掉（正文并进邻章）：只记下标，源文件一个字都不动。

        按下标（不是标题）记，同名章节不会一起被删。
        """
        S = self.S
        book = b["title"] or os.path.splitext(b["name"])[0]
        # 只剩一条目录时删了就没地方承载正文了（并进邻章也无邻章可并）
        if len(self.tv_chap.get_children()) <= 1:
            messagebox.showinfo(S["d_chap_del"], S["d_chap_del_last"],
                                parent=self.root)
            return
        if not messagebox.askyesno(S["d_chap_del"],
                                   S["d_chap_del_msg"].format(book, title),
                                   parent=self.root):
            return
        dels = {x for x in (b.get("chap_del") or [])
                if isinstance(x, int) and not isinstance(x, bool)}
        dels.add(int(idx))
        b["chap_del"] = sorted(dels)
        self._save_books_index()  # 与「修改书名」一致：立刻落盘，重开仍在
        left = self._chap_refresh(b)
        self.log(S["log_chap_del"].format(title, left))

    def undel_chapters(self, b):
        """恢复本书被删除的全部章节（源文件本来就完好，只是被清单挡住了）。"""
        S = self.S
        n = len(b.get("chap_del") or [])
        if not n:
            return
        b.pop("chap_del", None)
        self._save_books_index()
        self._chap_refresh(b)
        self.log(S["log_chap_del_undo"].format(b["title"] or b["name"], n))

    def _chap_refresh(self, b):
        """按最新删除记录重刷底部表格：有缓存就复用，不为删一章重读整本书。"""
        cache = self._chap_cache_get(
            b, self._re_for(b, self.custom_re.get().strip() or None))
        full = cache.get("full") if cache else None
        if full is None:
            self.preview_chap(b)
            return len(self.tv_chap.get_children())
        chapters, ck, gone, idx = self._chap_final(b, full)
        self._fill_chap_table(b, chapters, ck, gone, idx)
        return len(chapters)

    def _save_books_index(self):
        """书籍字典里改了内容（删章 / 分章规则）就立刻落盘索引，下次打开仍生效。"""
        self._idx_dirty = False
        d = self.dir_var.get().strip()
        if d and os.path.isdir(d):
            self.save_index_now(d)

    def _chap_cols(self, batch):
        """分章表格列头：False=单本预览(章序/标题/字数/校验)，True=批量试分(序号/书名/章节/校验)。"""
        S = self.S
        self.tv_chap.heading("no", text="#")
        self.tv_chap.heading("title", text=S["col_c_book"] if batch else S["col_chap_title"])
        self.tv_chap.heading("chars", text=S["col_c_chaps"] if batch else S["col_chars"])
        self.tv_chap.heading("check", text=S["col_chap_check"])
        self.tv_chap.column("title", width=px(320) if batch else px(420))
        self.tv_chap.column("chars", width=px(140) if batch else px(100))
        self.tv_chap.column("check", width=px(170) if batch else px(240))
        self._chap_batch = batch

    def preview_chap_all(self):
        """批量试分：对书库中所有勾选的书籍逐本切章，结果按 序号/书名/章节 列出。

        与「导出分发」一致：真实切章放到后台线程，进度经队列回传主线程，
        底栏 status_var 实时刷新，运行日志逐本输出一行；「停止」按钮可中断。
        """
        S = self.S
        sel = [b for b in self.books if b["sel"]]
        if not sel:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        if self.busy:
            return
        # 正则/清洗规则必须在主线程预取：tk 变量在线程内读取会 RuntimeError
        custom = self.custom_re.get().strip() or None
        rules = self.active_rules()
        try:
            jzcore.split_chapters("", custom)  # 空文本秒过，仅校验自定义正则语法
        except ValueError as e:
            messagebox.showerror(S["d_re_bad"], str(e))
            return
        self._chap_cols(True)
        for i in self.tv_chap.get_children():
            self.tv_chap.delete(i)
        self._chap_rows = {}  # 行 → 书：双击回填单本试分用
        self.set_busy(True)
        self.cancel = False
        self.status_var.set(S["prog_chap"].format(0, len(sel), sel[0]["title"]))
        self.log(S["log_chap_start"].format(len(sel), len(rules),
                                            custom or S["log_chap_builtin"]))
        threading.Thread(target=self.chap_worker,
                         args=(sel, custom, rules), daemon=True).start()

    def chap_worker(self, sel, custom, rules):
        S = self.S
        # 空串（而不是 None）传给 _re_for：后台线程不许回落到读 tk 变量
        custom = custom or ""
        total = len(sel)
        ok_n = sum_n = bad = ck_bad = 0
        for i, b in enumerate(sel, 1):
            if self.cancel:
                break
            name = b["title"] or os.path.splitext(b["name"])[0]
            self.q.put(("prog", (i - 1, total, S["prog_chap"].format(i, total, name))))
            try:
                adds = jzcore.manual_records(b.get("chap_add"))
                text = b.get("_clean")
                if text is None:
                    text = jzcore.load_text(b["path"])
                    if rules:
                        text, _r = jzcore.clean_text(
                            text, rules, None, self.custom_rules,
                            protect_lines=_chap_protect(adds))
                # 本书有自己的规则就用自己的；规则变了先作废旧的删章下标
                re_used = self._re_for(b, custom)
                self._chap_rule_sync(b, re_used, save=False)
                full = jzcore.split_chapters(
                    text, re_used, jzcore.manual_lines(adds, text))
                # 手动删掉的章只去掉目录条目（正文并进邻章），批量章数与导出一致
                chapters, _kept = self._chap_apply_del(b, full)
                gone = len(full) - len(chapters)
                ck = jzcore.check_chapters([t for t, _body in chapters], self.lang)
            except Exception as e:
                bad += 1
                self.q.put(("log", S["log_chap_book_fail"].format(i, total, name, e)))
                continue
            ok_n += 1
            sum_n += len(chapters)
            if ck["bad"]:
                ck_bad += 1
            # 主线程写回章数 + 追加结果行（批量只给汇总，不列每章详情）
            self.q.put(("chaprow", (ok_n, b, len(chapters), ck["summary"], ck["bad"])))
            # 日志带本书的章节树概况：多少级、多少章（章数由 {3} 给出）
            self.q.put(("log", S["log_chap_per_book"].format(
                i, total, name, len(chapters), "{:,}".format(len(text)))
                        + S["chap_tree"].format(ck["levels"])
                        + (S["chap_del_sum"].format(gone) if gone else "")))
        self.q.put(("prog", (total, total, S["prog_done"])))
        self.q.put(("done", ("chap", ok_n, sum_n, bad, self.cancel, ck_bad)))

    # ------------------------------------------------------------ 执行
    def start_run(self):
        S = self.S
        sel = [b for b in self.books if b["sel"]]
        if not sel:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        fmts = [k for k, v in self.fmt_vars.items() if v.get()]
        mode = self.mode_var.get()
        outdir = self.out_var.get().strip()
        if mode in ("new", "none") and not outdir:
            messagebox.showwarning(S["d_no_out"], S["d_no_out_msg"])
            return
        # 原地覆盖清洗不需要输出目录；但只要勾了导出格式，仍必须有输出目录
        if mode == "inplace" and fmts and not outdir:
            messagebox.showwarning(S["d_no_out"], S["d_no_out_msg"])
            return
        if mode == "none" and not fmts:
            messagebox.showwarning(S["d_nothing"], S["d_nothing_msg"])
            return
        if mode == "inplace":
            if not messagebox.askyesno(
                    S["d_confirm_ip"],
                    S["d_confirm_ip_msg"].format(len(sel))):
                return
        if self.busy:
            return
        self.set_busy(True)
        self.cancel = False
        # 规则/正则必须在主线程预取：tk 变量在线程内读取会 RuntimeError
        rules = self.active_rules()
        custom = self.custom_re.get().strip() or None
        theme = self.epub_theme()
        self._save_epub_opts()
        # 封面在封面窗里定好了：后台线程只查表，不再自己挑图
        covers = dict(self.cover_map)
        img_dl = self.img_download()
        want_sum = bool(self.sum_var.get())
        name_fmt = self.name_format()
        threading.Thread(target=self.run_worker,
                         args=(sel, fmts, mode, outdir, rules, custom,
                               theme, covers, img_dl, want_sum, name_fmt),
                         daemon=True).start()

    def run_worker(self, sel, fmts, mode, outdir, rules, custom,
                   theme=jzcore.DEFAULT_THEME, covers=None, img_dl=False,
                   want_sum=True, name_fmt=""):
        S = self.S
        custom = custom or ""  # 同上：后台线程不读 tk 变量
        # 封面窗没开过时按当前默认风格现画（普通字符串，跨线程读安全）
        cover_style = getattr(self, "cover_style", jzcore.DEFAULT_COVER_STYLE)
        ok = fail = 0
        # 清洗内容汇总：按书累积清理明细，全部处理完再一次性落盘
        groups = [] if want_sum else None
        if mode != "inplace" and outdir:
            try:
                os.makedirs(outdir, exist_ok=True)
            except OSError as e:
                self.q.put(("log", S["log_outdir_fail"].format(e)))
                self.q.put(("done", ("run", 0, len(sel), outdir)))
                return
        total = len(sel)
        for i, b in enumerate(sel, 1):
            if self.cancel:
                break
            self.q.put(("prog", (i - 1, total, S["prog_run"].format(i, total, b["title"]))))
            try:
                # 这本书的插图日志先攒着，等「[i/N] 书名…」那行之后再一起打
                notes = []
                # 原地覆盖始终从磁盘原文按当前规则重洗写回；其余模式优先用内存清洗快照
                raw = None
                text = None
                removed = 0
                st = {} if want_sum else None
                trace = None
                blank_n = 0
                if mode == "inplace":
                    raw = jzcore.load_text(b["path"])
                else:
                    text = b.get("_clean")
                    if text is None:
                        raw = jzcore.load_text(b["path"])
                    else:
                        # 清洗页已经洗过：直接复用当时记下的清理明细，与快照一致
                        trace = b.get("_clean_trace")
                        blank_n = int(b.get("_clean_blank") or 0)
                # 「插图链接校验」和「下载插图链接」同开时只跑一趟网络：先把候选链接
                # 各取一次（字节非空即插图），判定结果喂给清洗，清洗环节不再联网
                prefetch = None
                if img_dl and outdir and raw is not None and "imgcheck" in rules:
                    pst = {}
                    p_title = (b.get("title")
                               or os.path.splitext(b.get("name") or "")[0]
                               or S["unnamed"])
                    prefetch = jzcore.prefetch_images(
                        raw, stats=pst, progress=self.img_progress(p_title))
                    notes.append(S["log_img_prefetch"].format(
                        pst.get("links", 0), pst.get("images", 0)))
                adds = jzcore.manual_records(b.get("chap_add"))
                if raw is not None:
                    text = raw
                    if rules:
                        text, removed = jzcore.clean_text(
                            text, rules, st, self.custom_rules,
                            jzcore.verify_cache(prefetch) if prefetch else None,
                            want_trace=want_sum,
                            protect_lines=_chap_protect(adds))
                        if want_sum:
                            trace = st.get("trace")
                            blank_n = st.get("blank", 0)
                re_used = self._re_for(b, custom)
                self._chap_rule_sync(b, re_used, save=False)  # 规则变了先作废删章下标
                # 手工建章按记录的行号并回切分结果：导出与预览看到的是同一套目录
                full = jzcore.split_chapters(text, re_used,
                                             jzcore.manual_lines(adds, text))
                # 「试分章节」里右键删掉的章只在目录里消失，正文已并进邻章，
                # TOC 与列表保持一致
                chapters, _kept = self._chap_apply_del(b, full)
                gone = len(full) - len(chapters)
                b["chapters"] = len(chapters)  # 实际切分结果回写，供①书库展示
                title = b["title"] or os.path.splitext(b["name"])[0]
                if name_fmt:
                    # 「文件名」选的是预设或自定义模板：book/author 换成书名/作者名
                    base = safe_name(
                        jzcore.apply_name_format(name_fmt, title, b.get("author") or "",
                                                 S["unnamed"]),
                        maxlen=80, fallback=S["unnamed"])
                else:
                    base = safe_name(title, fallback=S["unnamed"])
                # 插图先落到「输出目录/插图/书名」，epub 再照这份映射打包
                images = (self.fetch_images(text, outdir, base, prefetch, notes,
                                            title=title)
                          if (img_dl and outdir) else None)
                # 落盘的「整理后 TXT」是整本清洗原文（删章只作用于章节树：
                # EPUB 目录 / 分章 TXT 不再收录被删的章，源文件和整本 TXT 保持原样）
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
                        # 封面窗里定过的直接用那份字节；没定过（没开过窗口）
                        # 才回退：同名图优先，没有就按当前默认风格现画
                        cover = (covers or {}).get(_book_key(b["path"]))
                        if cover is None:
                            try:
                                cover = jzcore.cover_for_book(
                                    b["path"], title, b.get("author", ""),
                                    "auto", outdir, cover_style)
                            except Exception:
                                cover = None
                        jzcore.write_epub(self.uniq(outdir, base + ".epub"),
                                          title, b["author"], chapters,
                                          cover=cover, theme=theme,
                                          images=images, lang=self.lang)
                    # “输出到新目录”落盘的 TXT 与合并 TXT 内容等价，避免生成重复文件
                    if "merge" in fmts and mode != "new":
                        jzcore.save_txt(chapters, self.uniq(outdir, base + ".txt"), merge=True)
                    if "split" in fmts:
                        # 分章落的是同名目录，重名判定要连目录一起看，否则两本书会写进同一格
                        jzcore.save_txt(chapters,
                                        self.uniq(outdir, base + ".txt", also_dir=True),
                                        merge=False)
                self.q.put(("log", S["log_per_book"].format(i, total, title, len(chapters), removed)
                           + (S["chap_del_sum"].format(gone) if gone else "")))
                for m in notes:
                    self.q.put(("log", m))
                if want_sum:
                    groups.append({
                        "title": title,
                        "author": b.get("author") or "",
                        "file": b.get("rel") or b.get("name") or b["path"],
                        "lines_before": (len(raw.splitlines()) if raw is not None
                                         else b.get("_clean_before")),
                        "lines_after": len(text.splitlines()),
                        "blank": blank_n,
                        "entries": trace or [],
                        "note": "" if (trace is not None or not rules)
                        else S["sum_note_snapshot"],
                    })
                ok += 1
            except Exception as e:
                fail += 1
                self.q.put(("log", S["log_book_fail"].format(i, total, b["title"], e)))
                self.q.put(("log", traceback.format_exc(limit=1).strip()))
                if want_sum:
                    groups.append({
                        "title": b.get("title") or b.get("name") or "",
                        "author": b.get("author") or "",
                        "file": b.get("rel") or b.get("name") or b.get("path") or "",
                        "entries": (),
                        "note": S["sum_note_fail"].format(e),
                    })
        if want_sum:
            self._write_summary(groups, outdir, rules)
        self.q.put(("prog", (total, total, S["prog_done"])))
        final = outdir if mode != "inplace" else (outdir or S["log_out_final"])
        self.q.put(("done", ("run", ok, fail, final)))

    def _write_summary(self, groups, outdir, rules):
        """把本次处理清洗掉的内容汇总成「输出目录/清洗内容汇总.txt」。

        写失败只记一行日志：汇总只是排查误删的辅助文件，不该让整批处理报错。
        """
        S = self.S
        if not outdir:
            self.q.put(("log", S["log_summary_noout"]))
            return
        if not groups:
            return
        try:
            path, n = jzcore.write_clean_summary(
                os.path.join(outdir, jzcore.SUMMARY_NAME), groups,
                rules=rules, lang="en" if self.lang == EN else "zh",
                custom=self.custom_rules)
        except OSError as e:
            self.q.put(("log", S["log_summary_fail"].format(e)))
            return
        blank_all = sum(int(g.get("blank") or 0) for g in groups)
        self.q.put(("log", S["log_summary_ok"].format(path, len(groups), n, blank_all)))

    def img_progress(self, title):
        """插图下载进度回调：把「第几张/共几张」原地刷到日志最后一行。

        jzcore 每处理完一条链接调一次；一张图最长要等 20 秒超时，日志里有这行
        才能分清「正在下图」和「程序卡死」。按 IMG_PROG_GAP 节流（首条与末条
        一定输出），后台线程只往队列塞事件，不碰任何 tk 控件。
        """
        S = self.S
        last = [0.0]

        def report(done, total):
            now = time.time()
            if 1 < done < total and now - last[0] < IMG_PROG_GAP:
                return
            last[0] = now
            self.q.put(("logprog", S["log_img_prog"].format(title, done, total)))

        return report

    def fetch_images(self, text, outdir, base, prefetch=None, notes=None, title=""):
        """把一本书的插图下载到「输出目录/插图/书名」，返回 {链接: 本地路径}。

        目录按书名复用：同一本书重跑只是覆盖同名编号文件，不会堆出「书名 (1)」。
        prefetch 是清洗前那趟请求的结果（见 jzcore.prefetch_images）：给了它就直接
        落盘，不再联网，避免同一批链接被请求两次。
        notes 传入 list 时，成功/跳过的统计攒进去由调用方统一输出；报错仍即时打。
        """
        S = self.S
        dest = os.path.join(outdir, jzcore.IMG_DIRNAME, base)
        st = {}
        try:
            if prefetch is not None:
                got = jzcore.save_images(prefetch, text, dest, st)
            else:
                got = jzcore.download_images(text, dest, stats=st,
                                             progress=self.img_progress(title or base))
        except Exception as e:
            self.q.put(("log", S["log_img_fail"].format(e)))
            return None
        msgs = []
        if got:
            msgs.append(S["log_img_save"].format(len(got), dest))
        skip = st.get("links", 0) - len(got or {})
        if skip > 0:
            msgs.append(S["log_img_skip"].format(skip))
        if notes is None:
            for m in msgs:
                self.q.put(("log", m))
        else:
            notes.extend(msgs)
        return got or None

    def uniq(self, outdir, filename, also_dir=False):
        """取一个不撞名的文件名；also_dir=True 时连同同名目录一起检查（分章 TXT）。"""
        stem, ext = os.path.splitext(filename)
        n = 0
        while True:
            name = filename if n == 0 else "%s (%d)%s" % (stem, n, ext)
            p = os.path.join(outdir, name)
            taken = os.path.exists(p) or (
                    also_dir and os.path.exists(os.path.join(outdir, os.path.splitext(name)[0])))
            if not taken:
                return p
            n += 1


def _boot(root):
    App(root)
    _center_win(root, 1080, 760)


def main():
    _set_dpi_aware()  # 必须在 tk.Tk() 之前：Tk 只初始化一次缩放
    root = tk.Tk()
    # 先撤窗再建界面：Tk 在第一次空闲处理时就会把主窗映射到屏幕，而建控件的
    # 过程中本来就有 update_idletasks()（规则滚动区、主题按钮量宽等都会调），
    # 所以不撤窗的话窗口会先按窗口管理器的默认位置露一次面，再被 _center_win()
    # 挪到中间——这就是「启动时先显示、再移动到居中」的来源。
    # 撤窗期间照常建控件和布局（都不要求窗口已映射），居中几何算好后 deiconify()，
    # 窗口第一次出现在屏幕上时尺寸与位置已经落定，不会再有可见位移。
    root.withdraw()
    _init_metrics(root)  # 必须在任何控件/画布创建之前
    _boot(root)  # 直接进入主界面：不再有开屏等待
    root.deiconify()  # 建完再露面：首次显示即为最终居中位置
    root.mainloop()


if __name__ == "__main__":
    main()
