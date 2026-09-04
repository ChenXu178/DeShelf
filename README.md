# 卷帙 DeShelf

> 本地 TXT 整理工具 — 扫描 · 清洗 · 分章 · **导出 EPUB / TXT**
>
> **v1.3** · 智能分章新增批量操作（Web：全部书籍一键分章并保存；EXE：试分全部选中）· 语言切换后自动重启应用 · 在线版日志栏默认展开
>
> **v1.2** · 新增中英双语界面（跟随系统语言，菜单可切换）· 记忆上次输出目录与模式 · 修复原地覆盖缺输出目录时静默跳过的校验
>
> **v1.1** · 新增启动开屏海报（淡入淡出，点击可跳过）· 主窗口居中

[中文](#中文) | [English](#english)

---

## 中文

### 它解决什么问题

你硬盘上躺着几百本从各处下载的 TXT：编码有的是 GBK 有的是 UTF-8，打开全是乱码；正文里夹着
"请收藏本站""本章未完"这类推广行；章节没有目录，丢进阅读器里是一整坨；同一个文件还下重了好几份。

卷帙就是把这批"野生 TXT"变成能直接读的书的流水线工具。它**不下载、不上传、不联网**，
只处理你本机已有的文件。

### 功能

| 步骤 | 做什么 |
|---|---|
| **1 扫描入库** | 递归扫描目录，自动识别编码（GBK / UTF-8 / UTF-8 BOM / UTF-16），统计字数，按内容 MD5 标出重复文件 |
| **2 批量清洗** | 勾选规则后一键清洗：网址行、站点宣传行、翻页导航残留、乱码行、空行压缩、全角转半角、段落缩进。可先预览前后对比 |
| **3 智能分章** | 内置中文网文章节规则库，也支持自定义正则。分完直接在列表里看章节目录 |
| **4 导出分发** | 导出 EPUB（带完整目录）、合并 TXT、分章 TXT。清洗结果可选择输出到新目录、原地覆盖（先备份 .bak）或不落盘 |

其它：目录记忆、扫描索引缓存（秒开）、书单导出 CSV、按内容指纹找出重复文件。

### 为什么要转 EPUB

EPUB 是卷帙的主要输出格式，也是给电纸书/阅读器看书的推荐格式：

| 好处 | 说明 |
|---|---|
| 电纸书即插即用 | 文石 / 掌阅 / Kobo / 微信读书 / Apple Books 等均直接支持，打开就有章节目录、可跳章 |
| 可划线做笔记 | 支持高亮与批注留心得（笔记存在阅读器侧，换设备不丢） |
| 体积小近一半 | EPUB 是 zip 压缩容器，同一本书通常比 TXT 小 40%~55%，省电纸书存储 |
| 排版规范 | 段落缩进、标题层级完整保留，调字号自动重排，永不失真不乱码 |
| 开放标准 | EPUB 2.0 为 W3C 国际标准，不会过期，任何设备可长期阅读 |

**推荐流程**：卷帙把野生 TXT 清洗分章 → 导出最终版 EPUB → 放进电纸书精读做笔记。

### 和其它工具的区别

| | 卷帙 | Calibre | epubBuilder | 手机阅读 App |
|---|---|---|---|---|
| 批量处理整个目录 | ✅ 一次几百本 | ⚠️ 偏单本管理 | ❌ 一次做一本 | — |
| 中文编码自动识别 | ✅ 不用手填 | ❌ 默认 UTF-8，需手动指定 GBK | ✅ | 部分支持 |
| 广告行批量清洗 | ✅ 规则化 | ❌ | ❌ | 手动替换规则 |
| 不复制原文件 | ✅ 只写索引，原地不动 | ❌ 会复制进自己的书库 | ✅ | — |
| 带目录 EPUB 导出 | ✅ | ✅ | ✅ | — |
| 体积 | ~14 MB 单文件 | 100 MB+ 安装包 | 13 MB | — |

**卷帙不做阅读器。** 手机上看书交给成熟的阅读 App，卷帙只负责让书变得能顺畅导入。

### 安装

到 [Releases](https://github.com/podcatcher962/DeShelf/releases) 页下载 `DeShelf.exe`（软件中文名「卷帙」，Release 资产统一用英文名以兼容各平台下载），双击运行即可，无需安装 Python。

同页也可下载 **Web 版** `DeShelf.html`（或取源码 `web/DeShelf.html`）：双击本地用，或在线直接打开 👉 **https://podcatcher962.github.io/DeShelf/**

### 使用流程

1. 点「浏览…」选中你的小说目录 → 点「扫描」
2. 在「批量清洗」勾选规则 → 点「预览效果」确认
3. 在「智能分章」点「试分章节」看章节数对不对
4. 在「导出分发」选择去向与格式 → 点「开始处理」

### 技术说明

- Python 3 + Tkinter，单文件 EXE，**零第三方依赖**
- EPUB 由标准库 `zipfile` 手写（EPUB 2.0 + toc.ncx，兼容绝大多数阅读器）
- 编码识别不依赖 chardet：BOM 判断 → UTF-8 严格解码 → 含 NUL 字节判 UTF-16 → 回落 GBK
- 扫描结果缓存在目录下的 `.deshelf_index.json`，校验 mtime 与体积判断缓存是否过期
- 批量处理在后台线程执行，界面不卡，可随时停止

### 免责声明

卷帙是一款纯本地文本整理工具：不联网、不下载、不上传、不提供也不存储任何书籍内容，
仅对用户本机已有的文件做清洗、分章与格式转换。使用者应确保所处理文件来源合法，
因使用本工具产生的任何版权或法律问题由使用者自行承担。软件按"现状"提供，
作者不对数据丢失或损坏承担责任；使用"原地覆盖"前请先确认备份。

### 卷帙 Web 版（同一份 HTML · 本地或在线双栖）

除桌面 EXE 外，卷帙还提供**单文件 HTML 版** `DeShelf.html`（78 KB，单击即用、零依赖），
支持两种使用方式：

| 方式 | 怎么用 | 适用范围 |
|---|---|---|
| **本地双击** | 双击 `DeShelf.html` 在 Chrome / Edge 打开 | 全部功能（含目录授权模式） |
| **在线版** | 传到任意 https 静态托管（如 GitHub Pages）后用网址打开 | 全部功能（数据仍留在你的浏览器里） |

**两种模式**自动检测浏览器能力：

| 模式 | 需要 | 能做什么 |
|---|---|---|
| 🅰️ **目录模式**（推荐） | Chrome / Edge · HTTPS 或本地文件 | 点「选择文件夹」授权整目录，扫描+缓存+批量保存到原目录（与桌面版 EXE 共享 `.deshelf_index.json`） |
| 🅱️ **文件模式** | 任何现代浏览器 | 把 TXT 文件或文件夹拖进网页，逐文件处理后下载到本机；无法原地写回 |

**在线版为什么安全**：`DeShelf.html` 是一个**纯前端**程序，打开后所有处理都在你浏览器里跑，
**不会上传任何文件、不与任何服务器通讯**。把这份 HTML 放到 GitHub Pages 等 https 静态托管只是给你一个访问入口，
服务器只负责把 HTML 文件送给你，之后的所有读写都发生在你的电脑里。换设备就失效（你的书不在服务器上），
这也是它能做成在线版的根本原因——无版权风险。

**在线版地址（GitHub Pages 托管）**：👉 **https://podcatcher962.github.io/DeShelf/** —— 与本地双击是同一份 HTML，打开即用，无需下载安装。

**桌面 vs Web 该选哪个**：

| | 桌面版 EXE | Web 版 HTML |
|---|---|---|
| 大书库（几百本）批量处理 | ✅ 推荐 | 浏览器内存有限 |
| 原地覆盖 + `.bak` 备份 | ✅ | ❌（下载副本） |
| 整目录写回（覆盖式） | ✅ | ❌（仅下载） |
| 跨平台（Windows / macOS / Linux / 手机） | 仅 Windows | ✅ 任何带现代浏览器的设备 |
| 中文 GBK 自动识别 | ✅ | ✅ |
| 联机分享 / 在线使用 | ❌ | ✅ |
| 离线纯本地 | ✅ | ✅ |

如果只是想把几本 TXT 整理成能直接塞进电纸书的 EPUB，**Web 版完全够用**，连 Python 都不用装。
需要批量"原地覆盖写回"原始文件时用桌面版 EXE。

**自检通过**：
- 核心纯逻辑 46/46 单测（编码识别 / 清洗 9 条规则 / 分章 / EPUB / ZIP）
- 真实浏览器冒烟 18/18（Edge headless · 页面初始化 / 双语切换 / 文件入库 / 清洗 / 分章 / 导出）
- 双语词典 125 键 + 125 键完全对齐

---

## English

> Local TXT organizing tool — scan · clean · split · **export EPUB / TXT**
>
> **v1.3** · smart chapter splitting now batch-capable (Web: chapter & save all books at once; EXE: try-split all selected) · language switch auto-restarts the app · online edition log panel open by default
>
> **v1.2** · bilingual UI (follows system language, switchable in the menu) · remembers last output folder & mode · fixed silent export skip when no output folder was set for in-place mode
>
> **v1.1** · new animated launch poster (fade in/out, click to skip) · centered main window

### What it does

You have hundreds of downloaded TXT files: mixed GBK / UTF-8 encodings that show up as mojibake,
promotional lines like "please bookmark this site" sprinkled through the text, no chapter structure,
and the same book downloaded twice.

DeShelf turns that pile of raw TXT into books you can actually read. It **never connects to the
network** — no downloading, no uploading. It only touches files already on your machine.

### Features

| Step | What happens |
|---|---|
| **1 Scan** | Recursively scans a folder, auto-detects encoding (GBK / UTF-8 / UTF-8 BOM / UTF-16), counts characters, flags duplicates by content MD5 |
| **2 Clean** | Rule-based batch cleaning: URL lines, site promo lines, page-nav leftovers, mojibake lines, blank-line compression, full-width to half-width, paragraph indent. Preview before applying |
| **3 Chapters** | Built-in regex library for Chinese web-novel chapter headings, custom regex supported, live chapter preview |
| **4 Export** | EPUB with a real table of contents, merged TXT, or one file per chapter. Cleaned text can go to a new folder, overwrite in place (with `.bak` backup), or not be saved at all |

Also: remembers the last folder, caches the scan index for instant reload, exports the book list as CSV,
finds duplicates by content fingerprint.

### Why EPUB

EPUB is DeShelf's primary output format and the recommended way to read on e-readers / reading apps:

| Benefit | Detail |
|---|---|
| E-reader ready | Works out of the box on Boox, iReader, Kobo, WeRead, Apple Books, etc. — opens with a real table of contents and chapter jumps |
| Highlight & annotate | Full support for highlighting and margin notes (notes live in the reader, so they survive file changes) |
| Roughly half the size | EPUB is a zip container — the same book is typically 40–55% smaller than TXT |
| Clean typography | Paragraph indents and heading levels are preserved; text reflows at any font size — no mojibake, no distortion |
| Open standard | EPUB 2.0 is a W3C standard that will never go stale |

**Recommended workflow**: clean & split your raw TXT in DeShelf → export the final EPUB → read and annotate on your e-reader.

### How it differs

| | DeShelf | Calibre | epubBuilder | Reading apps |
|---|---|---|---|---|
| Batch process a whole folder | ✅ hundreds at once | ⚠️ single-book oriented | ❌ one book at a time | — |
| Automatic Chinese encoding detection | ✅ no manual input | ❌ defaults to UTF-8 | ✅ | partial |
| Batch ad-line cleaning | ✅ rule-based | ❌ | ❌ | manual rules |
| Leaves originals in place | ✅ index only | ❌ copies into its own library | ✅ | — |
| EPUB with TOC | ✅ | ✅ | ✅ | — |
| Size | ~14 MB single file | 100 MB+ installer | 13 MB | — |

**DeShelf is not a reader.** Hand the finished EPUB to whichever reading app you like.

### Install

Grab `DeShelf.exe` from the [Releases](https://github.com/podcatcher962/DeShelf/releases) page (the app is named 卷帙 in Chinese; release assets use the English name for cross-platform download) and double-click it. No Python required.

The **Web version** `DeShelf.html` is also on the same Release page (source: `web/DeShelf.html`). Double-click it for local use, or open the online copy at 👉 **https://podcatcher962.github.io/DeShelf/**

### Workflow

1. Browse to your novels folder → **Scan**
2. Tick the cleaning rules → **Preview**
3. **Try split** in the Chapters tab to check the chapter count
4. Choose destination and formats → **Start**

### Technical notes

- Python 3 + Tkinter, single-file EXE, **zero third-party dependencies**
- EPUB is written by hand with the standard-library `zipfile` (EPUB 2.0 + toc.ncx)
- Encoding detection without chardet: BOM check → strict UTF-8 decode → NUL byte test for UTF-16 → fall back to GBK
- Scan results cached in `.deshelf_index.json`, invalidated by mtime and size
- Batch jobs run on a worker thread; the UI stays responsive and can be stopped at any time

### Disclaimer

DeShelf is a purely local text-processing utility. It does not connect to the network, does not
download or upload anything, and neither provides nor stores any book content — it only cleans,
splits and converts files that already exist on the user's machine. Users are responsible for
ensuring they have the legal right to process their files. Provided "as is"; the author is not
liable for any data loss. Back up before using in-place overwrite.

### DeShelf Web (single-file HTML · local or online)

In addition to the desktop EXE, 卷帙 ships a **single-file HTML** called `DeShelf.html`
(78 KB, double-click to run, zero dependencies) — usable two ways:

| Mode | How | Scope |
|---|---|---|
| **Local double-click** | Open `DeShelf.html` in Chrome / Edge | All features (including directory mode) |
| **Online version** | Host it on any https static site (e.g. GitHub Pages) and open the URL | All features (data still stays in your browser) |

Two internal modes are auto-detected based on browser capability:

| Mode | Needs | What it can do |
|---|---|---|
| 🅰️ **Directory mode** (recommended) | Chrome / Edge · HTTPS or local file | Click "Choose Folder" to authorize a whole directory: scan, write an index cache, batch-save results into the same directory (shares `.deshelf_index.json` with the desktop EXE) |
| 🅱️ **File mode** | Any modern browser | Drop TXT files or a folder into the page; each book is processed and downloaded to your machine. No in-place writes |

**Why the online version is safe**: `DeShelf.html` is **purely client-side**. After opening,
all processing runs inside your browser — **no files are uploaded, no server communication**.
Putting it on GitHub Pages or any https static host only gives you a URL to load it. From that point on,
all reads and writes happen on your own computer. Switch devices and the access vanishes (your books
aren't on any server) — that is exactly why this design can be safely hosted online with no copyright risk.

**Online edition (hosted on GitHub Pages)**: 👉 **https://podcatcher962.github.io/DeShelf/** — the exact same HTML as the local file; open and use, no install needed.

**Desktop vs Web — which to pick**:

| | Desktop EXE | Web HTML |
|---|---|---|
| Big batch (hundreds of files) | ✅ Recommended | Limited by browser memory |
| In-place overwrite + `.bak` backup | ✅ | ❌ (downloads only) |
| Whole-directory in-place rewrite | ✅ | ❌ (downloads only) |
| Cross-platform (Win/macOS/Linux/phone) | Windows only | ✅ Any device with a modern browser |
| Auto GBK detection | ✅ | ✅ |
| Share / online use | ❌ | ✅ |
| 100% offline | ✅ | ✅ |

For most "I have a few TXT files and want a readable EPUB for my e-reader" jobs, **Web is enough** —
no Python, no install. Reach for the desktop EXE only when you need to batch-overwrite original files in place.

**Self-tests passing**:
- 46/46 core unit tests (encoding / 9 cleaning rules / chapters / EPUB / ZIP)
- 18/18 real-browser smoke (Edge headless: init / language / file import / clean / chapters / export)
- 125 keys × 2 in the bilingual dictionary, fully aligned

---

© 永远的兰兰 · Lanlan Eternal
