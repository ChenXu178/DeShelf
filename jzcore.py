# -*- coding: utf-8 -*-
"""卷帙 DeShelf — 本地文本整理核心逻辑层。

仅依赖 Python 标准库，不发起任何网络请求，只处理用户本机已有的文件。
"""

import hashlib
import json
import os
import re
import uuid
import zipfile

APP_CN = "卷帙"
APP_EN = "DeShelf"
APP_VER = "v1.3.2"
INDEX_NAME = ".deshelf_index.json"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".deshelf_config.json")

# ---------------------------------------------------------------- 编码识别

def detect_bytes(data):
    """根据字节内容猜测编码，返回可传给 decode 的名称。"""
    if data[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if data[:2] == b"\xff\xfe":
        return "utf-16-le"
    if data[:2] == b"\xfe\xff":
        return "utf-16-be"
    if b"\x00" in data[:2000]:
        return "utf-16-le"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    return "gbk"


def decode(data, enc):
    try:
        return data.decode(enc, errors="replace")
    except (UnicodeError, LookupError):
        return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 元信息

_TITLE_IN_TEXT = re.compile(r"^\s*(?:书名|标题|题目|小说名)\s*[:：]\s*(.+?)\s*$")
_AUTHOR_IN_TEXT = re.compile(r"^\s*(?:作者|作\s*者)\s*[:：]\s*(.+?)\s*$")
_BRACKET = re.compile(r"《(.+?)》")
_JUNK = re.compile(r"[（(].*?[]）)]|\[[^\]]*\]|\.txt$|\.TXT$", re.I)


def _clean_name(name):
    name = _JUNK.sub("", name)
    name = re.sub(r"[_\-—－]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def guess_meta(filename, text):
    """从文件名与正文开头推断 (书名, 作者)。"""
    base = os.path.splitext(os.path.basename(filename))[0]
    title, author = "", ""

    head = "\n".join(text.splitlines()[:25])
    for line in head.splitlines():
        m = _TITLE_IN_TEXT.match(line)
        if m and not title:
            title = m.group(1).strip()
        m = _AUTHOR_IN_TEXT.match(line)
        if m and not author:
            author = m.group(1).strip()

    m = _BRACKET.search(base)
    if m and not title:
        title = m.group(1).strip()

    rest = _BRACKET.sub("", base)
    rest = _clean_name(rest)
    if rest:
        parts = [p for p in rest.split(" ") if p]
        if not title:
            title = parts[0]
        if not author and len(parts) >= 2:
            cand = parts[-1]
            if 1 < len(cand) <= 12 and not cand.isdigit():
                author = cand

    if not title:
        title = _clean_name(base) or base
    return title.strip(), author.strip()


def count_chars(text):
    """统计非空白字符数（比逐字符循环快得多）。"""
    return len(text) - sum(text.count(c) for c in "\n\r\t 　\xa0")


def load_text(path):
    """按需读取全文。批量场景下不要长期持有返回值，避免内存堆积。"""
    with open(path, "rb") as f:
        data = f.read()
    return decode(data, detect_bytes(data))


def scan_file(path, with_text=False):
    """读取一个文件的元信息（默认不保留全文，避免几百本撑爆内存）。

    一次读入同时得到 md5 / 体积 / 编码 / 字数，不重复 IO。
    """
    with open(path, "rb") as f:
        data = f.read()
    enc = detect_bytes(data)
    text = decode(data, enc)
    info = {
        "path": path,
        "name": os.path.basename(path),
        "size": len(data),
        "md5": hashlib.md5(data).hexdigest(),
        "enc": enc,
        "chars": count_chars(text),
        "mtime": os.path.getmtime(path),
        "chapters": -1,
        "sel": True,
    }
    title, author = guess_meta(path, text)
    info["title"] = title
    info["author"] = author
    if with_text:
        info["text"] = text
    return info


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 清洗规则

URL_RE = re.compile(r"(https?://|www\.|ftp://|[a-z0-9\-]+\.(com|net|org|cn|cc|me|la|tv|info|xyz)\b)", re.I)
SITE_RE = re.compile(
    r"(请记住|记住本站|请收藏|收藏本站|本站地址|书籍地址|笔趣|顶点小说|手机阅读|手机版|"
    r"wap\.|m\.|txt下载|TXT下载|小说下载网|免费小说网|最新网址|首发网址|百度搜索|"
    r"天才一秒|无弹窗|更新最快|手打版|转载请|本章免费|请到)",
)
NAV_RE = re.compile(r"^\s*(上一页|下一页|上一章|下一章|返回目录|返回书城|加入书架|加入书签|"
                    r"推荐票|月票|投推荐|打赏|本章未完|未完待续|<--|-->|=====|-----)")
MOJI_RE = re.compile(r"[\ufffd\ue000-\uf8ff]|[\x00-\x08\x0b\x0c\x0e-\x1f]")

RULES = [
    {"id": "url", "name": "含网址的行", "name_en": "Lines with URLs",
     "tip": "删除出现 http / www / 域名的整行", "tip_en": "Remove whole lines containing http / www / domains"},
    {"id": "site", "name": "站点宣传行", "name_en": "Site promo lines",
     "tip": "删除“请收藏本站”“笔趣阁”这类推广整行", "tip_en": "Remove promo lines like \u201cbookmark us\u201d or scraper-site names"},
    {"id": "nav", "name": "翻页导航残留", "name_en": "Pagination leftovers",
     "tip": "删除“上一页”“本章未完”等导航整行", "tip_en": "Remove nav-only lines such as \u201cprev page\u201d / \u201cto be continued\u201d"},
    {"id": "moji", "name": "乱码行", "name_en": "Corrupted lines",
     "tip": "删除含替换符或不可见控制符的整行", "tip_en": "Remove lines with replacement or invisible control characters"},
    {"id": "blank", "name": "删除所有空行", "name_en": "Delete all blank lines",
     "tip": "不留任何空行（与下一项二选一）", "tip_en": "Remove every blank line (pick either this or the next)"},
    {"id": "blank2", "name": "压缩连续空行", "name_en": "Collapse blank runs",
     "tip": "多个空行合并为一个，保留段落间隔", "tip_en": "Merge consecutive blanks into one, keep paragraph spacing"},
    {"id": "trim", "name": "去除行首尾空白", "name_en": "Trim line ends",
     "tip": "清掉每行开头结尾的空格与制表符", "tip_en": "Strip spaces & tabs at the start/end of every line"},
    {"id": "half", "name": "全角转半角", "name_en": "Full-width to half-width",
     "tip": "只转全角数字与字母，中文标点保持原样", "tip_en": "Convert full-width digits & letters only; keep Chinese punctuation"},
    {"id": "indent", "name": "段落首行缩进两格", "name_en": "Indent paragraphs",
     "tip": "给每个非空段落开头补两个全角空格", "tip_en": "Prepend two full-width spaces to each non-empty paragraph"},
]

DEFAULT_ON = ["url", "site", "nav", "moji", "blank2", "trim", "half"]


def to_halfwidth(s):
    """只把全角数字与全角字母转成半角；中文标点（，。：；！？等）一律不动。"""
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def clean_text(text, enabled):
    """按启用的规则清洗文本，返回 (新文本, 删除行数)。"""
    on = set(enabled or [])
    removed = 0
    out = []
    prev_blank = False
    for raw in text.splitlines():
        s = raw
        if "trim" in on:
            s = s.strip()
        if "half" in on:
            s = to_halfwidth(s)
        drop = False
        if "url" in on and URL_RE.search(s):
            drop = True
        elif "site" in on and SITE_RE.search(s):
            drop = True
        elif "nav" in on and NAV_RE.search(s):
            drop = True
        elif "moji" in on and MOJI_RE.search(s):
            drop = True
        if drop:
            removed += 1
            continue
        if "blank" in on and not s:
            removed += 1
            continue
        if "blank2" in on and not s:
            if prev_blank:
                removed += 1
                continue
            prev_blank = True
            out.append("")
            continue
        prev_blank = False
        if "indent" in on and s:
            s = "　　" + s
        out.append(s)
    # 去掉首尾空行：用指针扫描避免 pop(0) 在大文本上的 O(n²)
    start = 0
    while start < len(out) and not out[start]:
        start += 1
    end = len(out)
    while end > start and not out[end - 1]:
        end -= 1
    if start or end != len(out):
        out = out[start:end]
    return "\n".join(out) + ("\n" if out else ""), removed


# ---------------------------------------------------------------- 分章

CHAPTER_PATTERNS = [
    r"第\s*[0-9０-９零〇一二三四五六七八九十百千万两]{1,15}\s*[章节節回卷篇集部]\s*[^\n]{0,40}",
    r"(?:^|\s)(?:卷|Chapter|CHAPTER|chapter)\s*[0-9０-９零〇一二三四五六七八九十百千万]{1,15}[^\n]{0,40}",
    r"(?:序章|序言|楔子|引子|尾声|後记|后记|番外|终章|結局|结局|完本)[^\n]{0,40}",
]
MAX_TITLE_LEN = 50


def split_chapters(text, custom=None):
    """切分章节，返回 [(标题, 正文)]。

    custom 非空时只使用自定义正则，否则使用内置中文规则库。
    """
    if custom:
        try:
            re.compile(custom)
        except re.error:
            raise ValueError("自定义章节正则无效，请检查语法")
        pats = [custom]
    else:
        pats = CHAPTER_PATTERNS
    chapters = []
    cur_title = "开篇"
    buf = []
    for raw in text.splitlines():
        s = raw.strip()
        hit = None
        # 以句号结尾的通常是正文而非标题，避免“序章内容。”这类误判
        if s and len(s) <= MAX_TITLE_LEN and not s.endswith("。"):
            for p in pats:
                if re.match(p, s):
                    hit = s
                    break
        if hit is not None:
            body = "\n".join(buf).strip()
            if body:
                chapters.append((cur_title, body))
                cur_title = hit
            else:
                # 连续标题或误判：合并标题，绝不丢弃已有的标题文字
                cur_title = hit if cur_title == "开篇" else cur_title + " " + hit
            buf = []
        else:
            buf.append(raw)
    body = "\n".join(buf).strip()
    if body:
        chapters.append((cur_title, body))
    elif chapters and cur_title not in ("开篇",):
        chapters[-1] = (chapters[-1][0], chapters[-1][1] + "\n" + cur_title)
    if not chapters:
        chapters = [("全文", text.strip())]
    return chapters


# ---------------------------------------------------------------- 导出

def save_txt(chapters, path, merge=True):
    if merge:
        parts = []
        for title, body in chapters:
            parts.append(title)
            parts.append(body)
        data = "\n\n".join(p for p in parts if p) + "\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        return path
    base, ext = os.path.splitext(path)
    os.makedirs(base, exist_ok=True)
    width = max(4, len(str(len(chapters))))
    for i, (title, body) in enumerate(chapters, 1):
        safe = re.sub(r'[\\/:*?"<>|]', "_", title)[:60] or ("第%04d章" % i)
        fp = os.path.join(base, "%0*d_%s.txt" % (width, i, safe))
        with open(fp, "w", encoding="utf-8", newline="\n") as f:
            f.write(title + "\n\n" + body + "\n")
    return base


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


CSS = """body{margin:1.2em 1em;line-height:1.75;}
h2{font-size:1.25em;margin:1.4em 0 .8em;text-align:center;font-weight:normal;}
p{margin:0 0 .6em;text-indent:2em;font-size:1em;}
"""

CONTAINER = """<?xml version='1.0' encoding='utf-8'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def write_epub(path, title, author, chapters):
    """用标准库 zipfile 手写 EPUB 2.0（含 toc.ncx，兼容绝大多数阅读器）。"""
    uid = "urn:uuid:" + str(uuid.uuid4())
    title = title or "未命名"
    author = author or "佚名"
    pages = []
    for i, (ctitle, body) in enumerate(chapters, 1):
        paras = []
        for p in body.splitlines():
            p = p.strip()
            if p:
                paras.append("    <p>%s</p>" % _esc(p))
        pages.append((i, ctitle, "\n".join(paras) or "    <p>（本章无正文）</p>"))

    manifest = []
    spine = []
    navpoints = []
    for i, ctitle, _ in pages:
        manifest.append('    <item id="c%d" href="c%04d.xhtml" media-type="application/xhtml+xml"/>' % (i, i))
        spine.append('    <itemref idref="c%d"/>' % i)
        navpoints.append(
            '    <navPoint id="np%d" playOrder="%d">\n'
            "      <navLabel><text>%s</text></navLabel>\n"
            '      <content src="c%04d.xhtml"/>\n'
            "    </navPoint>" % (i, i, _esc(ctitle), i)
        )

    opf = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n'
        "    <dc:title>%s</dc:title>\n"
        "    <dc:creator opf:role=\"aut\">%s</dc:creator>\n"
        "    <dc:language>zh-CN</dc:language>\n"
        "    <dc:identifier id=\"BookId\">%s</dc:identifier>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="css" href="style.css" media-type="text/css"/>\n'
        "%s\n"
        "  </manifest>\n"
        '  <spine toc="ncx">\n%s\n  </spine>\n'
        "</package>\n"
    ) % (_esc(title), _esc(author), uid, "\n".join(manifest), "\n".join(spine))

    ncx = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-01-01">\n'
        "  <head><meta name=\"dtb:uid\" content=\"%s\"/></head>\n"
        "  <docTitle><text>%s</text></docTitle>\n"
        "  <navMap>\n%s\n  </navMap>\n</ncx>\n"
    ) % (uid, _esc(title), "\n".join(navpoints))

    with zipfile.ZipFile(path, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", CSS, zipfile.ZIP_DEFLATED)
        for i, ctitle, html_body in pages:
            page = (
                "<?xml version='1.0' encoding='utf-8'?>\n"
                '<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">\n'
                "<head>\n  <meta charset=\"utf-8\"/>\n"
                "  <title>%s</title>\n"
                '  <link rel="stylesheet" type="text/css" href="style.css"/>\n'
                "</head>\n<body>\n  <h2>%s</h2>\n%s\n</body>\n</html>\n"
            ) % (_esc(ctitle), _esc(ctitle), html_body)
            z.writestr("OEBPS/c%04d.xhtml" % i, page, zipfile.ZIP_DEFLATED)
    return path


# ---------------------------------------------------------------- 索引

def index_path(root):
    return os.path.join(root, INDEX_NAME)


def load_index(root):
    p = index_path(root)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_index(root, data):
    try:
        with open(index_path(root), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n
