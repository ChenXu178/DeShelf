# -*- coding: utf-8 -*-
"""卷帙 DeShelf — 本地文本整理工具（桌面版，中英双语界面）

扫描 → 清洗 → 分章 → 导出，全程在本机完成，不发起任何网络请求。
界面语言：默认跟随系统；菜单「语言 / Language」可即时切换（窗口内重建）并记忆。
"""

import os
import queue
import subprocess
import threading
import time
import traceback
from collections import Counter
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

try:
    import ctypes
except ImportError:              # 非 Windows / 精简解释器：全部 DPI 调用自动降级
    ctypes = None

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
LINE = "#D3D8DE"   # 细线：太白的分组框在白底上看不出来
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

# ---- 开屏海报配色（书卷风深底 + 金线）----
SPLASH_W, SPLASH_H = 560, 340
SPLASH_BG = "#202838"
SPLASH_GOLD = "#C9A24B"
SPLASH_INK = "#F1E7CE"
SPLASH_GRAY = "#9AA5B6"
SPLASH_DIM = "#7C8695"
SPLASH_LINE = "#465061"

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

【小提示】
  · 双击书库中的行可切换勾选；右键可打开文件位置。
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

[Tips]
  · Double-click a library row to toggle selection; right-click for file actions.
  · Scan results are cached in .deshelf_index.json next to the folder —
    reopening loads instantly.
  · Send EPUBs to your phone and open them in any local-import reader.
"""

DISC_ZH = """免责声明

卷帙 DeShelf 是一款纯本地的文本整理工具：它不联网、不下载、不上传、
不提供也不存储任何书籍内容，仅对用户本机已有的文件做清洗、分章与格式转换。

用户应确保其处理的文件拥有合法来源并仅用于个人学习研究，
因使用本工具产生的任何版权或法律问题，由使用者自行承担。

本软件按「现状」提供，作者不对数据丢失或损坏承担责任。
请在执行「原地覆盖」前确认已做好备份。
"""

DISC_EN = """Disclaimer

DeShelf is a purely local text-organizing tool: it does not connect to the
network, download, upload, host or store any book content. It only cleans,
splits and converts files that already exist on the user's own machine.

Users are responsible for ensuring the files they process have a legal
source and are used for personal study only. Any copyright or legal issue
arising from the use of this tool is the sole responsibility of the user.

The software is provided “as is”. The author accepts no liability for data
loss or damage. Please confirm you have a backup before using “Overwrite”.
"""


ABOUT_ZH = """版权与许可 · Copyright & License

卷帙 DeShelf {ver}
本地 TXT 整理工具：扫描 · 清洗 · 分章 · 导出 EPUB / TXT。
纯离线运行——不联网、不上传、不下载任何书籍内容，全部处理只在这台电脑上完成。

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
· Python 3.12 —— PSF License Agreement
· Tcl/Tk（tkinter）—— BSD-style License
· Pillow（PIL）—— MIT-CMU License
· OpenCC 简繁对照表 —— Apache License 2.0（仅用于比对，不改写正文）

封面使用的楷体是 Windows 自带字体（simkai.ttf）：本软件不打包、不分发任何
字体文件；换到其它系统会自动回退到可用字体。
各组件的完整许可声明见仓库根目录的 THIRD-PARTY-NOTICES.md。

【免责】
软件按「现状」提供，不附带任何明示或暗示的担保。清洗与分章规则可能误删或
误判内容；桌面版「原地覆盖」会自动生成 .bak 备份，但仍建议处理前自行备份。
因使用本工具造成的数据丢失、版权或法律纠纷，由使用者自行承担。
"""

ABOUT_EN = """Copyright & License

DeShelf {ver}
A local TXT organizer: scan · clean · split · export EPUB / TXT.
Fully offline — no network, no uploads, no downloads of any book content.

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
· Python 3.12 — PSF License Agreement
· Tcl/Tk (tkinter) — BSD-style License
· Pillow (PIL) — MIT-CMU License
· OpenCC character tables — Apache License 2.0 (comparison only; text is never rewritten)

The cover uses KaiTi shipped with Windows (simkai.ttf): no font file is bundled
or redistributed — other systems fall back to an available font.
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
        "lib_hint": "  双击行可切换勾选，右键可打开文件位置",
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
        "clean_hint": "  对第一本勾选的书试跑，左边原文、右边清洗后",
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
        "chap_res": "点「试分章节」查看结果",
        "chap_all_done": "试分 {0} 本：共 {1} 章，异常 {2} 本（见日志）",
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
        "f_theme": "版面主题", "f_cover": "封面",
        "cov_auto": "自动：优先同名图片", "cov_default": "生成默认封面",
        "cov_none": "不加封面",
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
                      "纯离线运行，不联网、不下载、不上传任何内容。",
        "about_repo": "GitHub 主页 / 查看最新版：\nhttps://github.com/podcatcher962/DeShelf/releases",
        "usage_title": "使用说明", "disclaimer_title": "免责声明",
        "help_text": HELP_ZH, "disclaimer_text": DISC_ZH,
        "about_win": "版权与许可", "about_sub": "纯本地离线工具 · 扫描 · 清洗 · 分章 · 导出",
        "about_body": ABOUT_ZH,
        "b_copy_about": "复制说明全文", "b_copy_mit": "复制 MIT 全文",
        # 右键菜单
        "m_open_loc": "打开文件位置", "m_open_note": "用记事本打开",
        "m_copy_path": "复制完整路径",
        "m_remove_book": "从列表移除（不删文件）",
        "log_book_removed": "  已从列表移除：{0}",
        # 通用
        "unnamed": "未命名",
        # 开屏
        "sp_tag": "扫描 · 清洗 · 分章 · 导出",
        "sp_bottom": "{0} · 纯本地离线工具 · 点击或按任意键跳过",
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
        "lib_hint": "  Double-click a row to toggle; right-click for file actions",
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
        "clean_hint": "  Dry-run on the first selected book: original left, cleaned right",
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
        "chap_res": "Click \u201cTry Split\u201d to preview",
        "chap_all_done": "Tried {0} books: {1} chapters in total, {2} failed (see log)",
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
        "f_theme": "Layout", "f_cover": "Cover",
        "cov_auto": "Auto: same-name image first", "cov_default": "Generate default cover",
        "cov_none": "No cover",
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
                      "Fully offline — no network, no upload, nothing leaves your computer.",
        "about_repo": "GitHub homepage / latest release:\nhttps://github.com/podcatcher962/DeShelf/releases",
        "usage_title": "User Guide", "disclaimer_title": "Disclaimer",
        "help_text": HELP_EN, "disclaimer_text": DISC_EN,
        "about_win": "Copyright & License",
        "about_sub": "Fully offline · scan · clean · split · export",
        "about_body": ABOUT_EN,
        "b_copy_about": "Copy the full text", "b_copy_mit": "Copy the MIT text",
        "m_open_loc": "Open file location", "m_open_note": "Open with Notepad",
        "m_copy_path": "Copy full path",
        "m_remove_book": "Remove from list (file kept)",
        "log_book_removed": "  Removed from list: {0}",
        "unnamed": "Untitled",
        "sp_tag": "Scan · Clean · Split · Export",
        "sp_bottom": "{0} · Fully offline · Click or press any key to skip",
    },
}


def _sys_lang():
    """按 Windows 界面语言判断默认界面语言（不抛异常）。"""
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return ZH if (lid & 0x3FF) == 0x04 else EN   # 0x0804/0x0404/0x0004 = Chinese
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


# ============================================================ DPI / 屏幕几何
_SCALE = 1.0        # 96 DPI 逻辑像素 → 当前 DPI 物理像素的倍率（125% = 1.25）


def px(v):
    """96 DPI 下的逻辑像素 → 当前 DPI 下的物理像素。

    界面里所有写死的像素尺寸（窗口大小、行高、列宽、内边距、画布坐标）
    都必须经过这里换算，否则开启系统缩放后只有字号变大、布局不变。
    """
    return int(round(v * _SCALE))


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
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:   # S_OK
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
    if not (60.0 <= dpi <= 480.0):        # 取值异常时退回 96 DPI
        dpi = 96.0
    # 只放大不缩小：84 DPI 之类的老屏 / 非 Windows 平台保持设计尺寸，
    # 免得为了「适配」反而把界面整体压小。
    _SCALE = max(1.0, dpi / 96.0)
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)   # 1 point = dpi/72 px
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
    · 用工作区而不是整屏，任务栏不会把视觉中心顶高；
    · 开屏与主窗走同一函数，两者中心重合、切换时不会跳动。
    """
    try:
        win.update_idletasks()
    except Exception:
        pass
    W, H = px(w), px(h)
    area = _work_area()
    if area:
        aw, ah, ax, ay = area
    else:
        try:
            aw, ah, ax, ay = win.winfo_screenwidth(), win.winfo_screenheight(), 0, 0
        except Exception:
            return None
    W = max(1, min(W, aw - px(24)))       # 小屏 + 高缩放时别超出可见区域
    H = max(1, min(H, ah - px(24)))
    x = ax + (aw - W) // 2
    y = ay + (ah - H) // 2
    win.geometry("%dx%d+%d+%d" % (W, H, x, y))
    return W, H


class App:
    def __init__(self, root):
        self.root = root
        self.books = []
        self.q = queue.Queue()
        self.busy = False
        self.cancel = False
        self.cfg = jzcore.load_config()
        self.lang = pick_lang()
        self.S = TEXTS[self.lang]
        last = self.cfg.get("lastdir", "")
        self.dir_var = tk.StringVar(value=last)
        self.out_var = tk.StringVar(value=self.cfg.get("outdir", ""))
        self.custom_re = tk.StringVar()
        self.mode_var = tk.StringVar(value=self.cfg.get("mode", "new") or "new")
        self.rule_vars = {r["id"]: tk.BooleanVar(value=r["id"] in jzcore.DEFAULT_ON)
                          for r in jzcore.RULES}
        # 自定义规则（来自规则包导入 / 自定义编辑），随配置持久化
        self.custom_rules = [r for r in (self.cfg.get("custom_rules") or [])
                             if isinstance(r, dict)]
        self.fmt_vars = {"epub": tk.BooleanVar(value=True),
                         "merge": tk.BooleanVar(value=False),
                         "split": tk.BooleanVar(value=False)}
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
        # 「保留插图链接」打开才允许勾选
        for _rid in ("url", "imgkeep"):
            self.rule_vars[_rid].trace_add(
                "write", lambda *a: self.refresh_rule_state())
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

        # 内层宽度跟随画布（否则文字按请求宽度排版、右边被切）
        def _on_cv_conf(e):
            cv.itemconfigure(cv_win, width=e.width)
            self.root.after(30, lambda: _sync(*cv.yview()))

        def _on_inner_conf(_e):
            cv.configure(scrollregion=cv.bbox("all"))
            self.root.after(30, lambda: _sync(*cv.yview()))

        cv.bind("<Configure>", _on_cv_conf)
        inner.bind("<Configure>", _on_inner_conf)

        def _wheel(e):
            try:
                first, last = cv.yview()
            except Exception:
                return
            if first <= 0.0 and last >= 1.0:      # 内容不满一屏：不拦滚轮
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
        ttk.Button(bar, text=S["b_preview"], style="Accent.TButton",
                   command=self.preview_clean).pack(side="left")
        self.btn_clean_apply = ttk.Button(bar, text=S["b_clean_apply"],
                                          style="Go.TButton",
                                          command=self.start_clean)
        self.btn_clean_apply.pack(side="left", padx=(px(6), 0))
        ttk.Label(bar, text=S["clean_hint"], foreground="#666666").pack(side="left")
        self.cmp_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.cmp_var, foreground="#2E7D32").pack(side="right")
        box = ttk.Frame(right)
        box.pack(fill="both", expand=True, pady=px(4))
        self.txt_before = self._mk_text(box, S["col_pre"])
        self.txt_after = self._mk_text(box, S["col_post"])

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
        self.tv_chap = ttk.Treeview(wrap, columns=("no", "title", "chars"),
                                    show="headings", height=8)
        for c, w, t in (("no", px(60), "#"), ("title", px(520), S["col_chap_title"]),
                        ("chars", px(100), S["col_chars"])):
            self.tv_chap.heading(c, text=t)
            self.tv_chap.column(c, width=w, anchor="w" if c == "title" else "center")
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
        ttk.Checkbutton(row, text=S["f_epub"],
                        variable=self.fmt_vars["epub"]).pack(side="left", padx=(0, px(16)))
        ttk.Checkbutton(row, text=S["f_merge"],
                        variable=self.fmt_vars["merge"]).pack(side="left", padx=(0, px(16)))
        ttk.Checkbutton(row, text=S["f_split"],
                        variable=self.fmt_vars["split"]).pack(side="left")
        # EPUB 排版主题与封面：只影响导出的 epub，不改正文
        row2 = ttk.Frame(g2)
        row2.pack(fill="x", padx=px(10), pady=(0, px(6)))
        en = self.lang == EN
        ttk.Label(row2, text=S["f_theme"]).pack(side="left")
        self.theme_names = [(t["name_en"] if en else t["name"]) for t in jzcore.THEMES]
        self.cb_theme = ttk.Combobox(row2, state="readonly", width=13,
                                     values=self.theme_names)
        self.cb_theme.pack(side="left", padx=(px(4), 0))
        ttk.Label(row2, text=S["f_cover"]).pack(side="left", padx=(px(16), 0))
        self.cover_names = [S["cov_auto"], S["cov_default"], S["cov_none"]]
        self.cb_cover = ttk.Combobox(row2, state="readonly", width=20,
                                     values=self.cover_names)
        self.cb_cover.pack(side="left", padx=(px(4), 0))
        self._restore_epub_opts()
        self.cb_theme.bind("<<ComboboxSelected>>", lambda _e: self._save_epub_opts())
        self.cb_cover.bind("<<ComboboxSelected>>", lambda _e: self._save_epub_opts())

        g3 = ttk.LabelFrame(f, text=S["grp_out"], style="Card.TLabelframe")
        g3.pack(fill="x", padx=px(8), pady=px(6))
        r = ttk.Frame(g3)
        r.pack(fill="x", padx=px(10), pady=px(6))
        ttk.Entry(r, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=(0, px(4)))
        ttk.Button(r, text=S["browse"], command=self.pick_out).pack(side="left")

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
        """按配置恢复主题/封面选择（配置里存 id，界面上显示名字）。"""
        tid = self.cfg.get("theme") or "classic"
        idx = [t["id"] for t in jzcore.THEMES].index(tid) \
            if tid in [t["id"] for t in jzcore.THEMES] else 0
        try:
            self.cb_theme.current(idx)
        except Exception:
            pass
        cm = self.cfg.get("cover") or "auto"
        key = {"auto": 0, "default": 1, "none": 2}.get(cm, 0)
        try:
            self.cb_cover.current(key)
        except Exception:
            pass

    def epub_opts(self):
        """主线程取当前选择，返回 (theme_id, cover_mode)，可直接传给后台线程。"""
        try:
            ti = self.cb_theme.current()
            theme = jzcore.THEMES[ti]["id"] if 0 <= ti < len(jzcore.THEMES) else "classic"
        except Exception:
            theme = "classic"
        try:
            ci = self.cb_cover.current()
        except Exception:
            ci = 0
        cover = {0: "auto", 1: "default", 2: "none"}.get(ci, "auto")
        return theme, cover

    def _save_epub_opts(self):
        theme, cover = self.epub_opts()
        self.cfg["theme"] = theme
        self.cfg["cover"] = cover
        jzcore.save_config(self.cfg)

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

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.logbox.insert("end", payload + "\n")
                    self.logbox.see("end")
                elif kind == "book":
                    self.add_book(payload)
                elif kind == "chaprow":
                    # 批量试分逐本回填：先写回书籍章数（①书库同步），再追加③页结果行
                    n, b, cnt = payload
                    self._set_book_chaps(b, cnt)
                    if hasattr(self, "tv_chap"):
                        self.tv_chap.insert("", "end",
                                            values=(n, b["title"] or os.path.splitext(b["name"])[0],
                                                    str(cnt)))
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
        for b in (getattr(self, "btn_chap_try", None), getattr(self, "btn_chap_all", None)):
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
        self.reload_rows()          # books 数据在内存，整表重灌（含勾选状态）
        self._fill_chap_pick()      # 重建后重填「试分书籍」下拉
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
        _center_win(w, 640, 520)          # 说明窗同样按 DPR 缩放并居中
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
        info.setdefault("chapters", -1)      # 章数字段：-1 = 尚未试分
        self.books.append(info)
        rel = info.get("rel", os.path.basename(info["path"]))
        self.tv.insert("", "end", iid=str(idx), values=(
            "✓" if info["sel"] else "", info["title"], info["author"],
            "{:,}".format(info["chars"]), info["enc"], self.chap_cell(info),
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
                "{:,}".format(b["chars"]), b["enc"], self.chap_cell(b),
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
        m.add_command(label=S["m_copy_path"],
                      command=lambda: self.copy_path(b["path"]))
        m.add_separator()
        m.add_command(label=S["m_remove_book"],
                      command=lambda: self.remove_book(b))
        m.tk_popup(event.x_root, event.y_root)

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
        """立刻落盘索引：手动添加/删除书籍后，下次打开不用重扫也能看到。"""
        try:
            jzcore.save_index(root, {
                "root": root, "scanned": time.time(),
                "books": [{k: v for k, v in b.items() if k != "path"}
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
            jzcore.save_index(root, {
                "root": root, "scanned": time.time(),
                "books": [{k: v for k, v in b.items() if k != "path"} for b in self.books]})
        elif kind == "run":
            _s, ok, fail, outdir = payload
            self.reload_rows()          # 回写实际切分章数/字数后重灌书库列表
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
            _s, ok_n, sum_n, bad, cancelled = payload
            self.refresh_chap_col()
            self.chap_var.set(S["chap_all_done"].format(ok_n, sum_n, bad))
            st = S["st_chap_done"].format(ok_n, sum_n, bad)
            self.status_var.set(st + (S["log_stopped"] if cancelled else ""))
            self.log(S["log_chap_done"].format(ok_n, bad, sum_n)
                     + (S["log_stopped"] if cancelled else ""))

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
            if row is None:
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
        if cb is not None:
            on = bool(self.rule_vars["imgkeep"].get())
            cb.state(["!disabled"] if on else ["disabled"])
            lab = self._rule_tip_by_id.get("imgcheck")
            if lab is not None:
                lab.configure(foreground="#777777" if on else "#B4B4B4")
        cv = getattr(self, "_rules_canvas", None)
        inner = getattr(self, "_rule_inner", None)
        if cv is not None and inner is not None:
            try:
                cv.update_idletasks()
                cv.configure(scrollregion=cv.bbox("all"))
            except Exception:
                pass

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
            cleaned, removed = jzcore.clean_text(text, rules, stats, self.custom_rules)
        except Exception as e:
            messagebox.showerror(S["d_preview_fail"], str(e))
            return
        for t, s in ((self.txt_before, text), (self.txt_after, cleaned)):
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.insert("1.0", "\n".join(s.splitlines()[:400]))
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
                text, removed = jzcore.clean_text(text, rules, None, self.custom_rules)
                b["_clean"] = text          # 清洗快照：分章/导出优先使用（与 Web 版一致）
                b["chars"] = len(text)
                b["chapters"] = -1          # 正文已变，旧章数作废（与 Web 版一致）
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
        """这本书用的分章正则：自己有就用自己的，否则用全局（或调用方传入的 fallback）。

        后台线程不能读 tk 变量，所以调用方必须把全局值经 fallback 传进来。
        """
        own = (b.get("chap_re") or "").strip()
        if own:
            return own
        return fallback if fallback is not None else (self.custom_re.get().strip() or None)

    def sync_book_re(self):
        """切换「试分书籍」时：先把上一步编辑存回原书，再载入新书的规则。"""
        self.store_book_re()
        b = self.picked_book()
        self._re_book = b
        self.book_re_var.set((b.get("chap_re") or "") if b else "")
        self.refresh_re_state()

    def store_book_re(self):
        """把输入框内容写回当前书（空则清掉，回到用全局）。"""
        b = self._re_book
        if not b:
            return
        val = ""
        try:
            val = self.book_re_var.get().strip()
        except Exception:
            return
        if val:
            b["chap_re"] = val
        else:
            b.pop("chap_re", None)
        self.refresh_re_state()

    def clear_book_re(self):
        self.book_re_var.set("")
        self.store_book_re()

    def refresh_re_state(self):
        try:
            b = self._re_book
            self.re_state.set(self.S["book_re_on"] if (b and b.get("chap_re")) else "")
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
        elif idx == 0:
            self.refresh_chap_col()

    def preview_chap(self):
        S = self.S
        self._chap_cols(False)
        b = self.picked_book()
        if not b:
            messagebox.showinfo(S["d_no_sel"], S["d_no_sel_msg"])
            return
        self.store_book_re()
        custom = self.custom_re.get().strip() or None
        custom = self._re_for(b, custom)
        try:
            text = b.get("_clean")
            if text is None:
                text = jzcore.load_text(b["path"])
                rules = self.active_rules()
                if rules:
                    text, _r = jzcore.clean_text(text, rules, None, self.custom_rules)
            chapters = jzcore.split_chapters(text, custom)
        except ValueError as e:
            messagebox.showerror(S["d_re_bad"], str(e))
            return
        except Exception as e:
            messagebox.showerror(S["d_chap_fail"], str(e))
            return
        for i in self.tv_chap.get_children():
            self.tv_chap.delete(i)
        for i, (t, body) in enumerate(chapters[:2000], 1):
            self.tv_chap.insert("", "end", values=(i, t, "{:,}".format(len(body))))
        total = sum(len(x[1]) for x in chapters)
        self.chap_var.set(S["chap_sum"].format(b["title"], len(chapters), "{:,}".format(total)))
        self._set_book_chaps(b, len(chapters))      # 写回书籍状态 → ① 书库「章节」列同步
        self.log("《%s》试分 %d 章" % (b["title"], len(chapters)))

    def _chap_cols(self, batch):
        """分章表格列头：False=单本预览(章序/标题/字数)，True=批量试分(序号/书名/章节)。"""
        S = self.S
        self.tv_chap.heading("no", text="#")
        self.tv_chap.heading("title", text=S["col_c_book"] if batch else S["col_chap_title"])
        self.tv_chap.heading("chars", text=S["col_c_chaps"] if batch else S["col_chars"])
        self.tv_chap.column("title", width=px(320) if batch else px(520))
        self.tv_chap.column("chars", width=px(140) if batch else px(100))
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
            jzcore.split_chapters("", custom)       # 空文本秒过，仅校验自定义正则语法
        except ValueError as e:
            messagebox.showerror(S["d_re_bad"], str(e))
            return
        self._chap_cols(True)
        for i in self.tv_chap.get_children():
            self.tv_chap.delete(i)
        self.set_busy(True)
        self.cancel = False
        self.status_var.set(S["prog_chap"].format(0, len(sel), sel[0]["title"]))
        self.log(S["log_chap_start"].format(len(sel), len(rules),
                                            custom or S["log_chap_builtin"]))
        threading.Thread(target=self.chap_worker,
                         args=(sel, custom, rules), daemon=True).start()

    def chap_worker(self, sel, custom, rules):
        S = self.S
        total = len(sel)
        ok_n = sum_n = bad = 0
        for i, b in enumerate(sel, 1):
            if self.cancel:
                break
            name = b["title"] or os.path.splitext(b["name"])[0]
            self.q.put(("prog", (i - 1, total, S["prog_chap"].format(i, total, name))))
            try:
                text = b.get("_clean")
                if text is None:
                    text = jzcore.load_text(b["path"])
                    if rules:
                        text, _r = jzcore.clean_text(text, rules, None, self.custom_rules)
                chapters = jzcore.split_chapters(
                    text, self._re_for(b, custom))   # 本书有自己的规则就用自己的
            except Exception as e:
                bad += 1
                self.q.put(("log", S["log_chap_book_fail"].format(i, total, name, e)))
                continue
            ok_n += 1
            sum_n += len(chapters)
            self.q.put(("chaprow", (ok_n, b, len(chapters))))   # 主线程写回章数 + 追加结果行
            self.q.put(("log", S["log_chap_per_book"].format(
                i, total, name, len(chapters), "{:,}".format(len(text)))))
        self.q.put(("prog", (total, total, S["prog_done"])))
        self.q.put(("done", ("chap", ok_n, sum_n, bad, self.cancel)))

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
        theme, cover_mode = self.epub_opts()
        self._save_epub_opts()
        threading.Thread(target=self.run_worker,
                         args=(sel, fmts, mode, outdir, rules, custom,
                               theme, cover_mode),
                         daemon=True).start()

    def run_worker(self, sel, fmts, mode, outdir, rules, custom,
                   theme="classic", cover_mode="auto"):
        S = self.S
        ok = fail = 0
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
                # 原地覆盖始终从磁盘原文按当前规则重洗写回；其余模式优先用内存清洗快照
                if mode == "inplace":
                    text = jzcore.load_text(b["path"])
                    removed = 0
                    if rules:
                        text, removed = jzcore.clean_text(text, rules, None, self.custom_rules)
                else:
                    text = b.get("_clean")
                    removed = 0
                    if text is None:
                        text = jzcore.load_text(b["path"])
                        if rules:
                            text, removed = jzcore.clean_text(text, rules, None, self.custom_rules)
                chapters = jzcore.split_chapters(text, self._re_for(b, custom))
                b["chapters"] = len(chapters)       # 实际切分结果回写，供①书库展示
                title = b["title"] or os.path.splitext(b["name"])[0]
                base = safe_name(title, fallback=S["unnamed"])
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
                        try:
                            cover = jzcore.cover_for_book(
                                b["path"], title, b.get("author", ""), cover_mode)
                        except Exception:
                            cover = None
                        jzcore.write_epub(self.uniq(outdir, base + ".epub"),
                                          title, b["author"], chapters,
                                          cover=cover, theme=theme)
                    # “输出到新目录”落盘的 TXT 与合并 TXT 内容等价，避免生成重复文件
                    if "merge" in fmts and mode != "new":
                        jzcore.save_txt(chapters, self.uniq(outdir, base + ".txt"), merge=True)
                    if "split" in fmts:
                        jzcore.save_txt(chapters, self.uniq(outdir, base + ".txt"), merge=False)
                self.q.put(("log", S["log_per_book"].format(i, total, title, len(chapters), removed)))
                ok += 1
            except Exception as e:
                fail += 1
                self.q.put(("log", S["log_book_fail"].format(i, total, b["title"], e)))
                self.q.put(("log", traceback.format_exc(limit=1).strip()))
        self.q.put(("prog", (total, total, S["prog_done"])))
        final = outdir if mode != "inplace" else (outdir or S["log_out_final"])
        self.q.put(("done", ("run", ok, fail, final)))

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
    文案按界面语言渲染（构造时传入 lang）。
    """

    def __init__(self, root, lang=None):
        self.root = root
        self._fade_job = None
        self._skipped = False
        self._fade_done = None
        self._hold_then = None
        self._then = None
        self.S = TEXTS[lang or pick_lang()]
        win = tk.Toplevel(root)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=SPLASH_BG)
        # 画布随窗口尺寸自适应：_paint 按画布实际尺寸等比缩放并居中绘制
        c = self.cv = tk.Canvas(win, width=px(SPLASH_W), height=px(SPLASH_H),
                                bg=SPLASH_BG, highlightthickness=0, bd=0)
        c.pack(fill="both", expand=True)
        self._paint(c)
        c.bind("<Configure>", lambda _e: self._paint(c))
        _center_win(win, SPLASH_W, SPLASH_H)      # 严格水平 + 垂直居中
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
        self._paint(c)                            # 映射后按真实像素再绘一次

    def _paint(self, c):
        """在 560x340 的设计坐标系里绘制，再按画布实际尺寸等比缩放并居中。

        所有坐标经 X()/Y() 平移缩放，文字用负字号（像素）跟随 k，
        因此窗口尺寸或 DPR 如何变化，海报内容始终水平垂直居中且不拉伸。
        """
        S = self.S
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 2 or H < 2:                        # 尚未映射：先用设计尺寸
            W, H = px(SPLASH_W), px(SPLASH_H)
        k = min(W / float(SPLASH_W), H / float(SPLASH_H))   # 等比，不拉伸版式
        ox = (W - SPLASH_W * k) / 2.0             # 水平居中偏移
        oy = (H - SPLASH_H * k) / 2.0             # 垂直居中偏移

        def X(x):
            return ox + x * k

        def Y(y):
            return oy + y * k

        def P(v):                                 # 线宽 / 字号（像素）
            return max(1, int(round(v * k)))

        g, ln = SPLASH_GOLD, SPLASH_LINE
        cx = X(SPLASH_W / 2.0)
        # 细金外框
        c.create_rectangle(X(11), Y(11), X(SPLASH_W - 11), Y(SPLASH_H - 11),
                           outline=g, width=P(2))
        # 四角回形小装饰（沿框延伸的短金线）
        L = 22
        for x0, y0, dx, dy in ((11, 11, 1, 0), (11, 11, 0, 1),
                               (SPLASH_W - 11, 11, -1, 0), (SPLASH_W - 11, 11, 0, 1),
                               (11, SPLASH_H - 11, 1, 0), (11, SPLASH_H - 11, 0, -1),
                               (SPLASH_W - 11, SPLASH_H - 11, -1, 0),
                               (SPLASH_W - 11, SPLASH_H - 11, 0, -1)):
            c.create_line(X(x0), Y(y0), X(x0 + dx * L), Y(y0 + dy * L),
                          fill=g, width=P(3))
        # 主标题「卷帙」：楷体大字（负字号 = 像素，避免被 tk scaling 二次放大）
        c.create_text(cx, Y(88), text=APP_CN, font=("KaiTi", -P(77)),
                      fill=SPLASH_INK, anchor="n")
        # 英文名（字母间隔拉宽，模拟字距）
        c.create_text(cx, Y(172), text=" ".join(APP_EN), font=(FONT[0], -P(17)),
                      fill=SPLASH_GOLD, anchor="n")
        # 一句定位
        c.create_text(cx, Y(212), text=S["sp_tag"],
                      font=(FONT[0], -P(15)), fill=SPLASH_GRAY, anchor="n")
        # 分隔线 + 底部信息
        c.create_line(X(SPLASH_W / 2.0 - 90), Y(250),
                      X(SPLASH_W / 2.0 + 90), Y(250), fill=ln, width=P(1))
        c.create_text(cx, Y(272), text=S["sp_bottom"].format(APP_VER),
                      font=(FONT[0], -P(12)), fill=SPLASH_DIM, anchor="n")

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
    _center_win(root, 1080, 760)      # 与开屏海报同一套居中对齐逻辑


def main():
    _set_dpi_aware()                 # 必须在 tk.Tk() 之前：Tk 只初始化一次缩放
    root = tk.Tk()
    _init_metrics(root)              # 必须在任何控件/画布创建之前
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
