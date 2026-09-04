# 卷帙 DeShelf

> 本地 TXT 整理工具 — 扫描 · 清洗 · 分章 · 导出
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

---

## English

> Local TXT organizing tool — scan · clean · split · export
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

---

© 永远的兰兰 · Lanlan Eternal
