# -*- coding: utf-8 -*-
"""卷帙 DeShelf — 本地文本整理核心逻辑层。

仅依赖 Python 标准库。默认不联网；只有用户勾选「插图链接校验」（逐条请求
响应头判断是不是插图、有没有失效）、「下载插图链接」（把插图存到本机输出目录），
或主动使用「下载网络封面」时才会联网，正文与文件内容一律不上传。
"""

import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

APP_CN = "卷帙"
APP_EN = "DeShelf"
APP_VER = "v1.6.0M"
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

# 正文里的字段标识。标识可以在行首，也可以跟在同一行前一个字段后面（用空白或分隔符隔开），
# 但前面必须是空白/分隔符，免得把「这本书的作者：某某」这类叙述句当成元信息。
_TITLE_LABELS = r"(?:书名|标题|题\s*目|小说名)"
_AUTHOR_LABELS = r"(?:作者|作\s*者)"
_FIELD_LABELS = r"(?:%s|%s)" % (_TITLE_LABELS, _AUTHOR_LABELS)
_LABEL_HEAD = r"(?:^|(?<=[\s\u3000,，;；、|｜/／]))"
_TITLE_IN_TEXT = re.compile(_LABEL_HEAD + _TITLE_LABELS + r"\s*[:：]\s*")
_AUTHOR_IN_TEXT = re.compile(_LABEL_HEAD + _AUTHOR_LABELS + r"\s*[:：]\s*")
# 同一行挤着多个字段时，值到此为止
_FIELD_END = re.compile(r"\s*%s\s*[:：]" % _FIELD_LABELS)
_BRACKET = re.compile(r"《(.+?)》")
_JUNK = re.compile(r"[（(].*?[]）)]|\[[^\]]*\]|\.txt$|\.TXT$", re.I)

# 文件名里常见的作者标识，可用 guess_meta_detail(author_keys=...) 替换
AUTHOR_KEYS = ("作者", "著者", "编者", "编著", "著")
# 零宽/BOM/方向控制符，常混在下载来的文件名里
_INVIS = re.compile("[\ufeff\u200b-\u200f\u2028\u2029\u2060]")
# 方括号里的名字：[作者]书名、书名[作者]；圆括号多是版本信息，不算
_BRACKET_AUTHOR = re.compile(r"[\[【]([^\[\]【】]{1,20})[\]】]")
# 版本 / 来源类标签，出现在方括号或标识后面时不是作者
_META_TAGS = {
    "全本", "全集", "全书", "完本", "完结", "完结本", "连载", "精校", "精校版",
    "校对", "校对版", "修订版", "珍藏版", "收藏版", "无删减", "未删节", "手打",
    "手打版", "全文", "全文字", "txt", "text", "下载", "免费", "最新章节",
}
# 占位词：出现了也不算识别出作者
_AUTHOR_BAD = {
    "未知", "佚名", "无名", "不详", "暂无", "无", "作者", "n/a", "na",
    "unknown", "null", "none",
}


def _author_keys_re(keys=None):
    """把标识元组编成正则分支，长标识在前（编著 先于 著）。"""
    return "|".join(re.escape(k) for k in sorted(keys or AUTHOR_KEYS, key=len, reverse=True))


def _author_re(keys=None):
    """「作者标识 + 作者名」的匹配式。

    标识后面必须跟冒号或者空白，否则「著作权法」「名著合集」会被误当成作者行；
    名字里碰到下一个「作者：」就停，免得「作者：甲作者：乙」拼成「甲作者」。
    """
    body = _author_keys_re(keys)
    return re.compile(
        r"(?:%s)\s*(?:[:：]\s*|\s+)"
        r"((?:(?!(?:%s)\s*[:：])[^\s\[\]【】()（）《》_\-—－:：,，。;；、])+)" % (body, body))


def _cut_field(s):
    """把字段值截到下一个「书名：」「作者：」等标识之前，并去掉残留分隔符。"""
    m = _FIELD_END.search(s)
    if m:
        s = s[:m.start()]
    return s.strip(" \t\u3000,，;；|｜/／、")


def _clean_author(s):
    """清洗作者串，去掉扩展名残留、书名号、多余空格与不可见字符。"""
    s = _INVIS.sub("", s or "")
    s = re.sub(r"(?:\.(?:txt|text))+$", "", s.strip(), flags=re.I)
    s = s.strip(" \t\u3000-—－_·.,，。;；:：、<>《》|｜/／\"'“”‘’")
    s = re.sub(r"\s+", " ", s).strip()
    if not s or len(s) > 20 or s.isdigit():
        return ""
    if s.lower() in _AUTHOR_BAD or s in _META_TAGS:
        return ""
    return s


def _clean_name(name):
    name = _JUNK.sub("", name)
    name = re.sub(r"[_\-—－]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def guess_meta_detail(filename, text, author_keys=None):
    """推断书名与作者，并给出各自的来源，无法识别时明确标为 "none"。

    author_keys 可替换文件名里的作者标识（默认 AUTHOR_KEYS）。
    返回 {"title", "author", "title_from", "author_from"}，
    来源取 "text"（正文明写）/ "filename"（文件名）/ "none"（没识别出来）。
    """
    title, author = "", ""
    title_from = author_from = "none"

    # 1) 正文优先：前 25 行里的「书名：」「作者：」，同一行有多个字段也能分别取到
    for line in (text or "").splitlines()[:25]:
        if not title:
            m = _TITLE_IN_TEXT.search(line)
            if m:
                cand = _cut_field(line[m.end():])
                if cand:
                    title, title_from = cand, "text"
        if not author:
            m = _AUTHOR_IN_TEXT.search(line)
            if m:
                cand = _clean_author(_cut_field(line[m.end():]))
                if cand:
                    author, author_from = cand, "text"

    # 2) 文件名：去掉 BOM/隐藏字符与所有 .txt 尾巴，只留主名
    base = _INVIS.sub("", os.path.basename(filename or ""))
    base = re.sub(r"(?:\.(?:txt|text))+$", "", base, flags=re.I)

    m = _BRACKET.search(base)
    if m and not title:
        cand = m.group(1).strip()
        if cand:
            title, title_from = cand, "filename"

    # 3) 文件名：方括号里的名字（[作者]书名 / 书名[作者]）
    rest = _BRACKET.sub("", base)
    for m in _BRACKET_AUTHOR.finditer(rest):
        cand = _clean_author(m.group(1))
        if cand:
            if not author:
                author, author_from = cand, "filename"
            rest = rest.replace(m.group(0), " ")
            break

    # 4) 文件名：「作者：xxx」等标识，只认第一个；正文已有作者时也照样剔出书名
    m = _author_re(author_keys).search(rest)
    if m:
        if not author:
            cand = _clean_author(m.group(1))
            if cand:
                author, author_from = cand, "filename"
        rest = rest.replace(m.group(0), " ")

    rest = _clean_name(rest)
    if rest:
        parts = [p for p in rest.split(" ") if p]
        if not title and parts:
            title, title_from = parts[0], "filename"
        if not author and len(parts) >= 2:
            cand = _clean_author(parts[-1])
            if cand and 1 < len(cand) <= 12:
                author, author_from = cand, "filename"

    return {"title": title.strip(), "author": author,
            "title_from": title_from, "author_from": author_from}


def guess_meta(filename, text):
    """从文件名与正文开头推断 (书名, 作者)，书名兜底为文件名本身。"""
    d = guess_meta_detail(filename, text)
    title = d["title"] or _clean_name(os.path.splitext(os.path.basename(filename or ""))[0])
    return (title.strip() or os.path.basename(filename or "")), d["author"]


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
# 从命中位置起“吃下整条网址”（含路径、查询串）：用来判断网址是不是孤零零占一行，
# 以及网址后面到底还剩多少正文。只认协议头的话，长网址会被当成一大段正文放过。
URL_BODY_RE = re.compile(
    r"(?:(?:https?|ftp)://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+"
    r"|[A-Za-z0-9\-]+\.(?:com|net|org|cn|cc|me|la|tv|info|xyz)\b"
    r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*",
    re.I,
)
# 正文里夹带的 HTML 标签（<img src="http://…">、<a href="…">、</a>、<br> 等）
HTML_TAG_RE = re.compile(r"<[A-Za-z/!][^<>]{0,2000}>")
# 强特征宣传词：正文里几乎不会出现，命中即可疑
SITE_RE = re.compile(
    r"(记住本站|收藏本站|本站地址|书籍地址|笔趣|顶点小说|手机阅读|"
    r"wap\.|txt下载|TXT下载|小说下载网|免费小说网|最新网址|首发网址|"
    r"天才一秒|无弹窗|更新最快|手打版|本章免费)",
    re.I,
)
# 说明：请记住 / 请收藏 / 请到 / 转载请 / 手机版 / 百度搜索 这些词在正常对话里也会出现
# （“把客人请到屋里”“你百度搜索一下”），所以不再作为单独判定广告的依据。
# 单独的 m. 同理去掉：它会把 "Mr." "com." 之类误判，手机域名靠 URL_RE 就能识别。

NAV_RE = re.compile(r"^\s*(上一页|下一页|上一章|下一章|返回目录|返回书城|加入书架|加入书签|"
                    r"推荐票|月票|投推荐|打赏|本章未完|未完待续|<--|-->|=====|-----)")
MOJI_RE = re.compile(r"[\ufffd\ue000-\uf8ff]|[\x00-\x08\x0b\x0c\x0e-\x1f]")

# 判定“这行是不是广告”用的尺子
AD_TAIL_MAX = 64    # 网址距离行尾超过这么多字，就不当成粘在段尾的广告
AD_MIN_BODY = 6     # 广告前面至少要有这么多字，才算“正文 + 广告尾巴”
AD_SHORT = 32       # 整行短于这个字数、前面又是推广语，就判为广告行
AD_TINY = 24        # 前面几乎没正文时，整行短于这个字数才丢
AD_AFTER = 10       # 网址后面还跟着这么多字，说明网址夹在句子中间
AD_HEAD_RE = re.compile(
    r"(记住|收藏|网址|本站|书站|手机阅读|手机版|最新章|一秒|更新最快|"
    r"推荐票|月票|笔趣阁|顶点|全文阅读|小说网|手打)"
)
# 推广套话的常用词。整行只剩这些词 + 网址时，它就是广告，不管网址有多长。
# 起因：`欢迎关注笔趣阁，畅享百万书库https://…（两百字符的图链）` 这类行，
# 按字数算的尺子把网址算进正文，于是只裁网址、把一句推广语留成正常段落。
_PROMO_WORDS = re.compile(
    r"欢迎(?:关注|访问|来到|光临|阅读|收藏)"
    r"|(?:感谢|请|求)?(?:关注|收藏|订阅|推荐|打赏|月票)"
    r"|畅享|海量|百万|书库|书站|本站|网址|域名|最新|首发|永久|记住"
    r"|手机|电脑|阅读|下载|更新|免费|无弹窗|全文|章节|一秒|天才"
    r"|笔趣|顶点|手打|本章|小说"
)
_SLIM_RE = re.compile(
    r"[\s\u3000，,。.！!？?、；;：:…\-—－_“”‘’\"'（）()《》〈〉【】\[\]·~@#%&*+=|/\\<>^_]"
)

# ---------------------------------------------------------------- 段落修复
# 盗版站抓下来的 txt 常按手机屏宽硬断：一段话被切成十几行，收尾引号还会被
# 挤成单独一行。用户看到的就是“一句没说完就换行”“引号自己占一行”。
_HEAD_BAN = set("，。、；：？！”’》」』）】,.;:?!")   # 几乎不会出现在正常行首
_QUOTE_END = set("”’\"'")
_BRACKET_END = set("」』）】》〉")
_OPEN_ANY = set("「『（(【《〈“‘")
_SENT_END = set("。！？…”』」）】.!?~—…：:")        # 一句/一段能正常收尾的字符
_ONLY_MAX = 3        # 整行只有标点，且不超过这么多字，才算“孤标点行”
_ONLY_PUNCT = re.compile(r"^[\s\u3000，。、；：？！…”’\"'「」『』（）()【】《》〈〉·—～]+$")
# 省略号、破折号：作家会故意让它们独占一行表示沉默/停顿，不能当坏行处理
_SOFT_ONLY = set("…·—～－–-—.")
# 逗号句号问号：绝不可能自己构成一个段落
_HARD_ONLY = set("，。、；：？！,.;:?!")
_SEP_LINE = re.compile(r"^\s*[=\-*_~·—─━※◇◆■□+]{3,}\s*$")
_HEAD_LINE = re.compile(
    r"^\s*(第\s*[0-9０-９零〇一二三四五六七八九十百千万两]{1,15}\s*[章节節回卷篇集部]"
    r"|序章|序言|楔子|引子|尾声|尾聲|后记|後記|番外|终章|終章|正文|目录|目錄)")
# 合并后一段超过这么多字，就认定那段不是“被切碎的段落”（多半是文件压根没有
# 分段信号），宁可不动 —— 281 个真实样本里 63% 的书没有空行分段。
UNWRAP_MAX = 3000


def _is_block_line(s):
    """章节标题、分隔线：不能参与合并，也不该被贴标点。"""
    if not s:
        return True
    if _SEP_LINE.match(s):
        return True
    t = s.strip("　 \t")
    return len(t) <= 50 and bool(_HEAD_LINE.match(t))


def _join_pair(prev, nxt):
    """把 nxt 接到 prev 后面：保留 prev 的缩进，丢掉 nxt 的行首空白。"""
    return prev.rstrip() + nxt.strip("　 \t")


def _only_kind(s):
    """整行只有标点时，判它属于哪一类。

    close = 只有收尾引号/括号（一定不可能另起一段，贴回永远是对的）
    hard  = 只有逗号句号问号（同上）
    soft  = 只有省略号/破折号（作家常用它单独一行表示沉默、停顿，**不动**）
    None  = 带「」这样成对写法，或参了别的字符（按段落处理，不动）
    """
    if any(ch in _OPEN_ANY for ch in s):
        return None
    if any(ch in _QUOTE_END or ch in _BRACKET_END for ch in s):
        return "close"
    core = [c for c in s if not c.isspace()]
    if core and all(c in _HARD_ONLY for c in core):
        return "hard"
    if core and all(c in _SOFT_ONLY for c in core):
        return "soft"
    return None


def fix_line_heads(lines):
    """标点单独占一行 / 跑到行首 → 接回上一行。返回 (新行, 修好的行数)。

    只动两种坏行：整行只有收尾引号或逗号句号的、行首就是标点的。
    **省略号/破折号独占一行一律不碰** —— 290 个真实样本里这类共 153 行，
    绝大多数是作者故意的（“……”单独一行表示沉默），贴上去等于改人家的排版。
    """
    out, n = [], 0
    for raw in lines:
        s = raw.strip()
        if not s or _is_block_line(s):
            out.append(raw)
            continue
        prev = out[-1] if out else ""
        if prev and not _is_block_line(prev.strip()):
            if len(s) <= _ONLY_MAX and _ONLY_PUNCT.match(s):
                if _only_kind(s) in ("close", "hard"):
                    # 收尾引号上一行已经有了，就别再叠一个
                    if not (s[-1] in _QUOTE_END and prev.rstrip().endswith(s[-1])):
                        out[-1] = prev.rstrip() + s
                        n += 1
                        continue
            elif s[0] in _HEAD_BAN:
                out[-1] = prev.rstrip() + s
                n += 1
                continue
        out.append(raw)
    return out, n


def scan_para_issues(lines):
    """不改文本，只估这两类毛病各有多少：标点独占一行、句中被硬断的段。

    规则默认是关的，关掉时上面那句“改了几处”就是 0，用户会以为文件没问题。
    所以额外跑一遍扫描，结果只用来提示“发现了 N 处，勾选第几条可以修”。
    """
    lone = 0
    prev = ""
    for raw in lines:
        s = raw.strip()
        if not s:
            prev = ""
            continue
        if (len(s) <= _ONLY_MAX and _ONLY_PUNCT.match(s)
                and _only_kind(s) in ("close", "hard")
                and prev and not _is_block_line(prev)):
            lone += 1
        prev = s

    blocks, bucket = 0, []

    def flush():
        nonlocal blocks, bucket
        if len(bucket) >= 4:
            total = sum(len(x) for x in bucket)
            no_end = sum(1 for x in bucket if x[-1] not in _SENT_END)
            if total >= 120 and no_end * 10 >= len(bucket) * 6:
                blocks += 1
        bucket = []

    for raw in list(lines) + [""]:
        s = raw.strip()
        if not s:
            flush()
            continue
        if _is_block_line(s):
            flush()
            continue
        bucket.append(s)
    flush()
    return {"lone": lone, "blocks": blocks}


def unwrap_paragraphs(lines, max_len=UNWRAP_MAX):
    """把空行之间被硬断的行接回去。返回 (新行, 合并处数, 跳过段数)。

    空行＝段落界，段内无条件全并 —— 不能靠“行尾有没有标点”判断，因为硬断点
    经常正好落在句号/问号后面（实测图2 那样会把整段并错）。
    """
    out, merged, skipped, block = [], 0, 0, []

    def flush():
        nonlocal block, merged, skipped
        if not block:
            return
        if len(block) > 1:
            total = sum(len(x.strip("　 \t")) for x in block)
            if total > max_len:
                skipped += 1
                out.extend(block)
                block = []
                return
            acc = block[0]
            for x in block[1:]:
                acc = _join_pair(acc, x)
                merged += 1
            out.append(acc)
        else:
            out.extend(block)
        block = []

    for raw in lines:
        s = raw.strip()
        if not s:
            flush()
            out.append(raw)
        elif _is_block_line(s):
            flush()                 # 标题单独成段，硬断点止于此
            out.append(raw)
        else:
            block.append(raw)
    flush()
    return out, merged, skipped


RULES = [
    {"id": "url", "name": "含网址的行", "name_en": "Lines with URLs",
     "tip": "删除只有网址的行；含网址的 HTML 标签整块清除；网址若粘在段尾，只裁掉网址本身，正文保留",
     "tip_en": "Removes URL-only lines (however long the image link), strips HTML tags that contain a URL, and trims only the URL when it is glued to a paragraph end"},
    {"id": "imgkeep", "name": "保留插图链接", "name_en": "Keep illustration links",
     "tip": "配图链接不再当广告删掉：按后缀认出 jpg/jpeg/png/webp/gif 的链接，"
            "「图片：https://…jpg」这种整行、以及粘在正文后面的图链都原样保留；"
            "若图链落在站点宣传行里，仍然随那一行一起删掉",
     "tip_en": "Illustration links are no longer deleted as ads: links ending in jpg/jpeg/png/webp/gif "
               "are recognised, so lines like \u201cimage: https://\u2026.jpg\u201d and links glued to a "
               "paragraph end are kept as-is. A link sitting on a site-promo line is still deleted with it"},
    {"id": "imgcheck", "name": "插图链接校验", "name_en": "Verify illustration links",
     "tip": "对行内所有链接（含没有图片后缀的）各联网请求一次校验：响应头 Content-Type 为 "
            "image/jpeg、image/png、image/gif、image/webp 的才算插图保留；返回网页的、"
            "已经失效的链接不保留（单条超时 6 秒）。须先开启「保留插图链接」",
     "tip_en": "Requests every link on a line (whether or not it has an image suffix) and keeps it only "
               "when the response Content-Type is image/jpeg, image/png, image/gif or image/webp; "
               "HTML pages and dead links are not kept (6 s timeout each). Requires "
               "\u201cKeep illustration links\u201d"},
    {"id": "site", "name": "站点宣传行", "name_en": "Site promo lines",
     "tip": "删除“请收藏本站”“笔趣阁”这类推广行；推广语贴在段尾时只裁掉那一截",
     "tip_en": "Removes promo lines; if the promo is glued to a paragraph end, only that part is trimmed"},
    {"id": "nav", "name": "翻页导航残留", "name_en": "Pagination leftovers",
     "tip": "删除“上一页”“本章未完”等导航整行", "tip_en": "Remove nav-only lines such as \u201cprev page\u201d / \u201cto be continued\u201d"},
    {"id": "moji", "name": "乱码行", "name_en": "Corrupted lines",
     "tip": "删除含替换符或不可见控制符的整行", "tip_en": "Remove lines with replacement or invisible control characters"},
    {"id": "punct", "name": "标点单独占一行（默认关）", "name_en": "Punctuation alone on a line",
     "tip": "整行只有一个收尾引号、句号或逗号的，接回上一行末尾。省略号/破折号独占一行（“……”“——”）是作家故意排的，不动。默认关闭，勾选才改",
     "tip_en": "A line holding only a closing quote or a comma / full stop is pulled back onto the previous line. Ellipsis-only lines such as \u201c\u2026\u201d are left alone \u2014 authors use them on purpose. Off by default"},
    {"id": "unwrap", "name": "合并句中断行（默认关）", "name_en": "Join mid-sentence line breaks",
     "tip": "按手机屏宽硬断的文件，一段话被切成好几行；勾选后以空行为段落界接回去。单段超过 3000 字的跳过不动，默认关闭",
     "tip_en": "For files hard-wrapped at phone width: joins the broken lines back together, using blank lines as paragraph breaks. Paragraphs over 3000 chars are left alone. Off by default"},
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
    {"id": "jsdup", "name": "简繁重复行（保留简体）",
     "name_en": "Duplicate simplified/traditional lines",
     "tip": "同一段正文同时有简体和繁体两份时，删掉繁体那份；相邻成对、整章重复都能认。全繁体的书不受影响，默认关闭",
     "tip_en": "When a paragraph exists in both simplified and traditional, drop the traditional copy. Handles alternating lines and whole duplicated chapters; traditional-only books are untouched. Off by default"},
]

DEFAULT_ON = ["url", "site", "nav", "moji", "blank2", "trim", "half"]


T2S_PAIRS = (
    "㑯㑔㑳㑇㑶㐹㓨刾㘚㘎㜄㚯㜏㛣㠏㟆㥮㤘㩜㨫㩳㧐㩵擜䁻䀥䃮鿎䊷䌶䋙䌺䋚䌻䋹䌿䋻䌾䍦䍠䎱䎬䙡䙌䜀䜧䝼䞍䥇䦂䥑鿏䥱䥾䦛䦶䦟䦷䯀䯅䰾鲃䱷䲣䱽䲝䲁鳚䲘鳤䴉鹮丟丢並并乾干亂乱亙亘亞亚佇伫佈布佔占併并來来侖仑侶侣侷局俁俣係系俔伣俠侠俥伡俬私倀伥倆俩倈俫倉仓"
    "個个們们倖幸倫伦倲㑈偉伟偑㐽側侧偵侦偽伪傌㐷傑杰傖伧傘伞備备傢家傭佣傯偬傳传傴伛債债傷伤傾倾僂偻僅仅僉佥僑侨僕仆僞伪僥侥僨偾僱雇價价儀仪儁俊儂侬億亿儈侩儉俭儎傤儐傧儔俦儕侪儘尽償偿優优儲储儷俪儸㑩儺傩儻傥儼俨兇凶兌兑兒儿兗兖內内兩两冊册冑胄"
    "冪幂凈净凍冻凜凛凱凯別别刪删剄刭則则剋克剎刹剗刬剛刚剝剥剮剐剴剀創创剷铲劃划劄札劇剧劉刘劊刽劌刿劍剑劏㓥劑剂劚㔉勁劲動动務务勛勋勝胜勞劳勢势勩勚勱劢勳勋勵励勸劝勻匀匭匦匯汇匱匮區区協协卹恤卻却卽即厙厍厠厕厤历厭厌厲厉厴厣參参叄叁叢丛吒咤吳吴"
    "吶呐呂吕咼呙員员唄呗唸念問问啓启啞哑啟启啢唡喎㖞喚唤喪丧喫吃喬乔單单喲哟嗆呛嗇啬嗊唝嗎吗嗚呜嗩唢嗶哔嘆叹嘍喽嘓啯嘔呕嘖啧嘗尝嘜唛嘩哗嘮唠嘯啸嘰叽嘵哓嘸呒嘽啴噁恶噓嘘噚㖊噝咝噠哒噥哝噦哕噯嗳噲哙噴喷噸吨噹当嚀咛嚇吓嚌哜嚐尝嚕噜嚙啮嚥咽嚦呖嚨咙"
    "嚮向嚲亸嚳喾嚴严嚶嘤囀啭囁嗫囂嚣囅冁囈呓囉啰囌苏囑嘱囪囱圇囵國国圍围園园圓圆圖图團团垻坝埡垭埰采執执堅坚堊垩堖垴堝埚堯尧報报場场塊块塋茔塏垲塒埘塗涂塚冢塢坞塤埙塵尘塹堑墊垫墜坠墮堕墰坛墳坟墶垯墻墙墾垦壇坛壋垱壎埙壓压壘垒壙圹壚垆壜坛壞坏壟垄"
    "壠垅壢坜壩坝壪塆壯壮壺壶壼壸壽寿夠够夢梦夥伙夾夹奐奂奧奥奩奁奪夺奬奖奮奋奼姹妝妆姍姗姦奸娛娱婁娄婦妇婭娅媧娲媯妫媰㛀媼媪媽妈嫋袅嫗妪嫵妩嫺娴嫻娴嫿婳嬀妫嬃媭嬈娆嬋婵嬌娇嬙嫱嬡嫒嬤嬷嬪嫔嬰婴嬸婶孃娘孋㛤孌娈孫孙學学孿孪宮宫寀采寢寝實实寧宁審审"
    "寫写寬宽寵宠寶宝將将專专尋寻對对導导尷尴屆届屍尸屓屃屜屉屢屡層层屨屦屬属岡冈峯峰峴岘島岛峽峡崍崃崑昆崗岗崙仑崢峥崬岽嵐岚嵗岁嵾㟥嶁嵝嶄崭嶇岖嶔嵚嶗崂嶠峤嶢峣嶧峄嶨峃嶮崄嶸嵘嶺岭嶼屿嶽岳巋岿巒峦巔巅巖岩巰巯巹卺帥帅師师帳帐帶带幀帧幃帏幓㡎幗帼"
    "幘帻幟帜幣币幫帮幬帱幷并幹干幾几庫库廁厕廂厢廄厩廈厦廎庼廕荫廚厨廝厮廟庙廠厂廡庑廢废廣广廩廪廬庐廳厅弒弑弔吊弳弪張张強强彆别彈弹彌弥彎弯彔录彙汇彠彟彥彦彫雕彲彨彿佛後后徑径從从徠徕復复徵征徹彻恆恒恥耻悅悦悞悮悵怅悶闷悽凄惡恶惱恼惲恽惻恻愛爱"
    "愜惬愨悫愴怆愷恺愾忾慄栗態态慍愠慘惨慚惭慟恸慣惯慤悫慪怄慫怂慮虑慳悭慶庆慺㥪慼戚慾欲憂忧憊惫憐怜憑凭憒愦憖慭憚惮憤愤憫悯憮怃憲宪憶忆懇恳應应懌怿懍懔懞蒙懟怼懣懑懤㤽懨恹懲惩懶懒懷怀懸悬懺忏懼惧懾慑戀恋戇戆戔戋戧戗戩戬戰战戱戯戲戏戶户扞捍拋抛"
    "拚拼挩捝挱挲挾挟捨舍捫扪捱挨捲卷掃扫掄抡掆㧏掗挜掙挣掛挂採采揀拣揚扬換换揮挥揯搄損损搖摇搗捣搧扇搵揾搶抢摑掴摜掼摟搂摯挚摳抠摶抟摺折摻掺撈捞撏挦撐撑撓挠撝㧑撟挢撣掸撥拨撫抚撲扑撳揿撻挞撾挝撿捡擁拥擄掳擇择擊击擋挡擓㧟擔担據据擠挤擡抬擣捣擬拟"
    "擯摈擰拧擱搁擲掷擴扩擷撷擺摆擻擞擼撸擽㧰擾扰攄摅攆撵攏拢攔拦攖撄攙搀攛撺攜携攝摄攢攒攣挛攤摊攪搅攬揽敎教敓敚敗败敘叙敵敌數数斂敛斃毙斆敩斕斓斬斩斷断於于旂旗旣既昇升時时晉晋晝昼暈晕暉晖暘旸暢畅暫暂曄晔曆历曇昙曉晓曏向曖暧曠旷曨昽曬晒書书會会"
    "朧胧朮术東东枴拐柵栅柺拐査查桿杆梔栀梘枧條条梟枭梲棁棄弃棊棋棖枨棗枣棟栋棡㭎棧栈棲栖棶梾椏桠椲㭏楊杨楓枫楨桢業业極极榘矩榦干榪杩榮荣榲榅榿桤構构槍枪槓杠槤梿槧椠槨椁槮椮槳桨槶椢槼椝樁桩樂乐樅枞樑梁樓楼標标樞枢樢㭤樣样樧榝樫㭴樳桪樸朴樹树樺桦"
    "樿椫橈桡橋桥機机橢椭橫横檁檩檉柽檔档檜桧檟槚檢检檣樯檮梼檯台檳槟檸柠檻槛櫃柜櫓橹櫚榈櫛栉櫝椟櫞橼櫟栎櫥橱櫧槠櫨栌櫪枥櫫橥櫬榇櫱蘖櫳栊櫸榉櫻樱欄栏欅榉權权欏椤欒栾欖榄欞棂欽钦歎叹歐欧歟欤歡欢歲岁歷历歸归歿殁殘残殞殒殤殇殨㱮殫殚殭僵殮殓殯殡殰㱩"
    "殲歼殺杀殻壳殼壳毀毁毆殴毿毵氂牦氈毡氌氇氣气氫氢氬氩氳氲氾泛汎泛汙污決决沒没沖冲況况泝溯洩泄洶汹浹浃涇泾涗涚涼凉淒凄淚泪淥渌淨净淩凌淪沦淵渊淶涞淺浅渙涣減减渢沨渦涡測测渾浑湊凑湞浈湧涌湯汤溈沩準准溝沟溫温溮浉溳涢溼湿滄沧滅灭滌涤滎荥滙汇滬沪"
    "滯滞滲渗滷卤滸浒滻浐滾滚滿满漁渔漊溇漚沤漢汉漣涟漬渍漲涨漵溆漸渐漿浆潁颍潑泼潔洁潙沩潚㴋潛潜潤润潯浔潰溃潷滗潿涠澀涩澆浇澇涝澐沄澗涧澠渑澤泽澦滪澩泶澮浍澱淀澾㳠濁浊濃浓濄㳡濕湿濘泞濚溁濛蒙濜浕濟济濤涛濧㳔濫滥濰潍濱滨濺溅濼泺濾滤瀂澛瀅滢瀆渎"
    "瀇㲿瀉泻瀋沈瀏浏瀕濒瀘泸瀝沥瀟潇瀠潆瀦潴瀧泷瀨濑瀰弥瀲潋瀾澜灃沣灄滠灑洒灕漓灘滩灝灏灡㳕灣湾灤滦灧滟灩滟災灾為为烏乌烴烃無无煉炼煒炜煙烟煢茕煥焕煩烦煬炀煱㶽熅煴熒荧熗炝熱热熲颎熾炽燁烨燈灯燉炖燒烧燙烫燜焖營营燦灿燬毁燭烛燴烩燶㶶燻熏燼烬燾焘"
    "爍烁爐炉爛烂爭争爲为爺爷爾尔牀床牆墙牘牍牴抵牽牵犖荦犛牦犢犊犧牺狀状狹狭狽狈猙狰猶犹猻狲獁犸獃呆獄狱獅狮獎奖獨独獪狯獫猃獮狝獰狞獱㺍獲获獵猎獷犷獸兽獺獭獻献獼猕玀猡現现琱雕琺珐琿珲瑋玮瑒玚瑣琐瑤瑶瑩莹瑪玛瑲玱璉琏璡琎璣玑璦瑷璫珰璯㻅環环璵玙"
    "璸瑸璽玺璿璇瓊琼瓏珑瓔璎瓚瓒甌瓯甕瓮產产産产畝亩畢毕畫画異异畵画當当疇畴疊叠痙痉痠酸痾疴瘂痖瘋疯瘍疡瘓痪瘞瘗瘡疮瘧疟瘮瘆瘲疭瘺瘘瘻瘘療疗癆痨癇痫癉瘅癒愈癘疠癟瘪癡痴癢痒癤疖癥症癧疬癩癞癬癣癭瘿癮瘾癰痈癱瘫癲癫發发皁皂皚皑皰疱皸皲皺皱盃杯盜盗"
    "盞盏盡尽監监盤盘盧卢盪荡眞真眥眦眾众睏困睜睁睞睐瞘眍瞜䁖瞞瞒瞶瞆瞼睑矇蒙矓眬矚瞩矯矫硃朱硜硁硤硖硨砗硯砚碕埼碩硕碭砀碸砜確确碼码碽䂵磑硙磚砖磠硵磣碜磧碛磯矶磽硗磾䃅礄硚礎础礙碍礦矿礪砺礫砾礬矾礱砻祕秘祿禄禍祸禎祯禕祎禡祃禦御禪禅禮礼禰祢禱祷"
    "禿秃秈籼稅税稈秆稏䅉稜棱稟禀種种稱称穀谷穇䅟穌稣積积穎颖穠秾穡穑穢秽穩稳穫获穭穞窩窝窪洼窮穷窯窑窵窎窶窭窺窥竄窜竅窍竇窦竈灶竊窃竪竖競竞筆笔筍笋筧笕筴䇲箇个箋笺箏筝箚札節节範范築筑篋箧篔筼篠筿篤笃篩筛篳筚簀箦簍篓簑蓑簞箪簡简簣篑簫箫簹筜簽签"
    "簾帘籃篮籌筹籔䉤籙箓籛篯籜箨籟籁籠笼籤签籩笾籪簖籬篱籮箩籲吁粵粤糉粽糝糁糞粪糧粮糰团糲粝糴籴糶粜糹纟糾纠紀纪紂纣約约紅红紆纡紇纥紈纨紉纫紋纹納纳紐纽紓纾純纯紕纰紖纼紗纱紘纮紙纸級级紛纷紜纭紝纴紡纺紬䌷紮扎細细紱绂紲绁紳绅紵纻紹绍紺绀紼绋紿绐"
    "絀绌終终絃弦組组絅䌹絆绊絎绗結结絕绝絛绦絝绔絞绞絡络絢绚給给絨绒絰绖統统絲丝絳绛絶绝絹绢綁绑綃绡綆绠綈绨綉绣綌绤綏绥綐䌼綑捆經经綜综綞缍綠绿綢绸綣绻綫线綬绶維维綯绹綰绾綱纲網网綳绷綴缀綵彩綸纶綹绺綺绮綻绽綽绰綾绫綿绵緄绲緇缁緊紧緋绯緑绿緒绪"
    "緓绬緔绱緗缃緘缄緙缂線线緝缉緞缎締缔緡缗緣缘緦缌編编緩缓緬缅緯纬緱缑緲缈練练緶缏緹缇緻致緼缊縈萦縉缙縊缢縋缒縐绉縑缣縕缊縗缞縛缚縝缜縞缟縟缛縣县縧绦縫缝縭缡縮缩縱纵縲缧縳䌸縴纤縵缦縶絷縷缕縹缥總总績绩繃绷繅缫繆缪繒缯織织繕缮繚缭繞绕繡绣繢缋"
    "繩绳繪绘繫系繭茧繮缰繯缳繰缲繳缴繸䍁繹绎繼继繽缤繾缱繿䍀纇颣纈缬纊纩續续纍累纏缠纓缨纔才纖纤纘缵纜缆缽钵罃䓨罈坛罌罂罎坛罰罚罵骂罷罢羅罗羆罴羈羁羋芈羣群羥羟羨羡義义羶膻習习翫玩翬翚翹翘翽翙耬耧耮耢聖圣聞闻聯联聰聪聲声聳耸聵聩聶聂職职聹聍聽听"
    "聾聋肅肃脅胁脈脉脛胫脣唇脩修脫脱脹胀腎肾腖胨腡脶腦脑腫肿腳脚腸肠膃腽膕腘膚肤膞䏝膠胶膩腻膽胆膾脍膿脓臉脸臍脐臏膑臘腊臚胪臟脏臠脔臢臜臥卧臨临臺台與与興兴舉举舊旧舖铺舘馆艙舱艤舣艦舰艫舻艱艰艷艳芻刍苧苎茲兹荊荆莊庄莖茎莢荚莧苋華华菴庵菸烟萇苌"
    "萊莱萬万萴荝萵莴葉叶葒荭葤荮葦苇葯药葷荤蒐搜蒓莼蒔莳蒕蒀蒞莅蒼苍蓀荪蓆席蓋盖蓮莲蓯苁蓴莼蓽荜蔔卜蔘参蔞蒌蔣蒋蔥葱蔦茑蔭荫蕁荨蕆蒇蕎荞蕒荬蕓芸蕕莸蕘荛蕢蒉蕩荡蕪芜蕭萧蕷蓣薀蕰薈荟薊蓟薌芗薑姜薔蔷薘荙薟莶薦荐薩萨薴苧薵䓓薹苔薺荠藍蓝藎荩藝艺藥药"
    "藪薮藭䓖藴蕴藶苈藹蔼藺蔺蘀萚蘄蕲蘆芦蘇苏蘊蕴蘋苹蘚藓蘞蔹蘢茏蘭兰蘺蓠蘿萝虆蔂處处虛虚虜虏號号虧亏虯虬蛺蛱蛻蜕蜆蚬蝕蚀蝟猬蝦虾蝨虱蝸蜗螄蛳螞蚂螢萤螮䗖螻蝼螿螀蟄蛰蟈蝈蟎螨蟣虮蟬蝉蟯蛲蟲虫蟶蛏蟻蚁蠁蚃蠅蝇蠆虿蠍蝎蠐蛴蠑蝾蠔蚝蠟蜡蠣蛎蠨蟏蠱蛊蠶蚕"
    "蠻蛮衆众衊蔑術术衕同衚胡衛卫衝冲袞衮袷夹裊袅裏里補补裝装裡里製制複复褌裈褘袆褲裤褳裢褸褛褻亵襇裥襉裥襏袯襖袄襝裣襠裆襤褴襪袜襬摆襯衬襲袭襴襕覈核見见覎觃規规覓觅視视覘觇覡觋覥觍覦觎親亲覬觊覯觏覲觐覷觑覺觉覽览覿觌觀观觴觞觶觯觸触訁讠訂订訃讣"
    "計计訊讯訌讧討讨訐讦訒讱訓训訕讪訖讫託托記记訛讹訝讶訟讼訢䜣訣诀訥讷訩讻訪访設设許许訴诉訶诃診诊註注証证詁诂詆诋詎讵詐诈詒诒詔诏評评詖诐詗诇詘诎詛诅詞词詠咏詡诩詢询詣诣試试詩诗詫诧詬诟詭诡詮诠詰诘話话該该詳详詵诜詼诙詿诖誄诔誅诛誆诓誇夸誌志"
    "認认誑诳誒诶誕诞誘诱誚诮語语誠诚誡诫誣诬誤误誥诰誦诵誨诲說说説说誰谁課课誶谇誹诽誼谊誾訚調调諂谄諄谆談谈諉诿請请諍诤諏诹諑诼諒谅論论諗谂諛谀諜谍諝谞諞谝諡谥諢诨諤谔諦谛諧谐諫谏諭谕諮咨諱讳諳谙諶谌諷讽諸诸諺谚諼谖諾诺謀谋謁谒謂谓謄誊謅诌謊谎"
    "謎谜謐谧謔谑謖谡謗谤謙谦謚谥講讲謝谢謠谣謡谣謨谟謫谪謬谬謭谫謳讴謹谨謾谩譁哗證证譎谲譏讥譖谮識识譙谯譚谭譜谱譟噪譫谵譭毁譯译議议譴谴護护譸诪譽誉譾谫讀读讅谉變变讋詟讌䜩讎雠讒谗讓让讕谰讖谶讚赞讜谠讞谳谿溪豈岂豎竖豐丰豔艳豬猪豶豮貍狸貓猫貙䝙"
    "貝贝貞贞貟贠負负財财貢贡貧贫貨货販贩貪贪貫贯責责貯贮貰贳貲赀貳贰貴贵貶贬買买貸贷貺贶費费貼贴貽贻貿贸賀贺賁贲賂赂賃赁賄贿賅赅資资賈贾賊贼賑赈賒赊賓宾賕赇賙赒賚赉賜赐賞赏賠赔賡赓賢贤賣卖賤贱賦赋賧赕質质賫赍賬账賭赌賰䞐賴赖賵赗賺赚賻赙購购賽赛"
    "賾赜贄贽贅赘贇赟贈赠贊赞贋赝贍赡贏赢贐赆贓赃贔赑贖赎贗赝贛赣贜赃赬赪趕赶趙赵趨趋趲趱跡迹踐践踰逾踴踊蹌跄蹕跸蹟迹蹠跖蹣蹒蹤踪蹺跷躂跶躉趸躊踌躋跻躍跃躎䟢躑踯躒跞躓踬躕蹰躚跹躡蹑躥蹿躦躜躪躏軀躯車车軋轧軌轨軍军軑轪軒轩軔轫軛轭軟软軤轷軫轸軲轱"
    "軸轴軹轵軺轺軻轲軼轶軾轼較较輅辂輇辁輈辀載载輊轾輒辄輓挽輔辅輕轻輛辆輜辎輝辉輞辋輟辍輥辊輦辇輩辈輪轮輬辌輯辑輳辏輸输輻辐輼辒輾辗輿舆轀辒轂毂轄辖轅辕轆辘轉转轍辙轎轿轔辚轟轰轡辔轢轹轤轳辦办辭辞辮辫辯辩農农迴回逕径這这連连週周進进遊游運运過过"
    "達达違违遙遥遜逊遞递遠远遡溯適适遲迟遶绕遷迁選选遺遗遼辽邁迈還还邇迩邊边邏逻邐逦郟郏郵邮鄆郓鄉乡鄒邹鄔邬鄖郧鄧邓鄭郑鄰邻鄲郸鄴邺鄶郐鄺邝酇酂酈郦醃腌醖酝醜丑醞酝醟蒏醣糖醫医醬酱醱酦釀酿釁衅釃酾釅酽釋释釐厘釒钅釓钆釔钇釕钌釗钊釘钉釙钋針针釣钓"
    "釤钐釦扣釧钏釩钒釵钗釷钍釹钕釺钎釾䥺鈀钯鈁钫鈃钘鈄钭鈅钥鈈钚鈉钠鈍钝鈎钩鈐钤鈑钣鈒钑鈔钞鈕钮鈞钧鈡钟鈣钙鈥钬鈦钛鈧钪鈮铌鈰铈鈳钶鈴铃鈷钴鈸钹鈹铍鈺钰鈽钸鈾铀鈿钿鉀钾鉅巨鉆钻鉈铊鉉铉鉋铇鉍铋鉑铂鉕钷鉗钳鉚铆鉛铅鉞钺鉢钵鉤钩鉦钲鉬钼鉭钽鉳锫鉶铏"
    "鉸铰鉺铒鉻铬鉿铪銀银銃铳銅铜銍铚銑铣銓铨銖铢銘铭銚铫銛铦銜衔銠铑銣铷銥铱銦铟銨铵銩铥銪铕銫铯銬铐銱铞銳锐銷销銹锈銻锑銼锉鋁铝鋃锒鋅锌鋇钡鋌铤鋏铗鋒锋鋙铻鋝锊鋟锓鋣铘鋤锄鋥锃鋦锔鋨锇鋩铓鋪铺鋭锐鋮铖鋯锆鋰锂鋱铽鋶锍鋸锯鋼钢錁锞錄录錆锖錇锫錈锩"
    "錏铔錐锥錒锕錕锟錘锤錙锱錚铮錛锛錟锬錠锭錡锜錢钱錦锦錨锚錩锠錫锡錮锢錯错録录錳锰錶表錸铼錼镎鍀锝鍁锨鍃锪鍅钫鍆钔鍇锴鍈锳鍊炼鍋锅鍍镀鍔锷鍘铡鍚钖鍛锻鍠锽鍤锸鍥锲鍩锘鍬锹鍰锾鍵键鍶锶鍺锗鍼针鍾钟鎂镁鎄锿鎇镅鎊镑鎌镰鎔镕鎖锁鎘镉鎚锤鎛镈鎡镃鎢钨"
    "鎣蓥鎦镏鎧铠鎩铩鎪锼鎬镐鎭镇鎮镇鎰镒鎲镋鎳镍鎵镓鎶鿔鎸镌鎿镎鏃镞鏇旋鏈链鏌镆鏍镙鏐镠鏑镝鏗铿鏘锵鏜镗鏝镘鏞镛鏟铲鏡镜鏢镖鏤镂鏨錾鏰镚鏵铧鏷镤鏹镪鏺䥽鏽锈鐃铙鐋铴鐐镣鐒铹鐓镦鐔镡鐘钟鐙镫鐝镢鐠镨鐥䦅鐦锎鐧锏鐨镄鐫镌鐮镰鐯䦃鐲镯鐳镭鐵铁鐶镮鐸铎"
    "鐺铛鐿镱鑄铸鑊镬鑌镔鑑鉴鑒鉴鑔镲鑕锧鑞镴鑠铄鑣镳鑥镥鑭镧鑰钥鑱镵鑲镶鑷镊鑹镩鑼锣鑽钻鑾銮鑿凿钁镢钂镋長长門门閂闩閃闪閆闫閈闬閉闭開开閌闶閎闳閏闰閑闲閒闲間间閔闵閘闸閡阂閣阁閤合閥阀閨闺閩闽閫阃閬阆閭闾閱阅閲阅閶阊閹阉閻阎閼阏閽阍閾阈閿阌闃阒"
    "闆板闇暗闈闱闊阔闋阕闌阑闍阇闐阗闒阘闓闿闔阖闕阙闖闯關关闞阚闠阓闡阐闢辟闤阛闥闼陘陉陝陕陞升陣阵陰阴陳陈陸陆陽阳隉陧隊队階阶隕陨際际隨随險险隯陦隱隐隴陇隸隶隻只雋隽雖虽雙双雛雏雜杂雞鸡離离難难雲云電电霑沾霢霡霧雾霽霁靂雳靄霭靆叇靈灵靉叆靚靓"
    "靜静靝靔靦腼靨靥鞏巩鞝绱鞦秋鞽鞒韁缰韃鞑韆千韉鞯韋韦韌韧韍韨韓韩韙韪韜韬韝鞲韞韫韻韵響响頁页頂顶頃顷項项順顺頇顸須须頊顼頌颂頎颀頏颃預预頑顽頒颁頓顿頗颇領领頜颌頡颉頤颐頦颏頭头頮颒頰颊頲颋頴颕頷颔頸颈頹颓頻频頽颓顆颗題题額额顎颚顏颜顒颙顓颛"
    "顔颜願愿顙颡顛颠類类顢颟顥颢顧顾顫颤顬颥顯显顰颦顱颅顳颞顴颧風风颭飐颮飑颯飒颱台颳刮颶飓颸飔颺飏颻飖颼飕飀飗飄飘飆飙飈飚飛飞飠饣飢饥飣饤飥饦飩饨飪饪飫饫飭饬飯饭飱飧飲饮飴饴飼饲飽饱飾饰飿饳餃饺餄饸餅饼餈糍餉饷養养餌饵餎饹餏饻餑饽餒馁餓饿餕馂"
    "餖饾餘余餚肴餛馄餜馃餞饯餡馅館馆餬糊餱糇餳饧餵喂餶馉餷馇餺馎餼饩餾馏餿馊饁馌饃馍饅馒饈馐饉馑饊馓饋馈饌馔饑饥饒饶饗飨饜餍饞馋饢馕馬马馭驭馮冯馱驮馳驰馴驯馹驲駁驳駐驻駑驽駒驹駔驵駕驾駘骀駙驸駛驶駝驼駟驷駡骂駢骈駭骇駰骃駱骆駸骎駿骏騁骋騂骍騅骓"
    "騌骔騍骒騎骑騏骐騖骛騙骗騤骙騧䯄騫骞騭骘騮骝騰腾騶驺騷骚騸骟騾骡驀蓦驁骜驂骖驃骠驄骢驅驱驊骅驌骕驍骁驏骣驕骄驗验驚惊驛驿驟骤驢驴驤骧驥骥驦骦驪骊驫骉骯肮髏髅髒脏體体髕髌髖髋髮发鬆松鬍胡鬚须鬢鬓鬥斗鬧闹鬨哄鬩阋鬮阄鬱郁鬹鬶魎魉魘魇魚鱼魛鱽魢鱾"
    "魨鲀魯鲁魴鲂魷鱿魺鲄鮁鲅鮃鲆鮊鲌鮋鲉鮍鲏鮎鲇鮐鲐鮑鲍鮒鲋鮓鲊鮚鲒鮜鲘鮝鲞鮞鲕鮣䲟鮦鲖鮪鲔鮫鲛鮭鲑鮮鲜鮳鲓鮶鲪鮺鲝鯀鲧鯁鲠鯇鲩鯉鲤鯊鲨鯒鲬鯔鲻鯕鲯鯖鲭鯗鲞鯛鲷鯝鲴鯡鲱鯢鲵鯤鲲鯧鲳鯨鲸鯪鲮鯫鲰鯰鲶鯴鲺鯷鳀鯽鲫鯿鳊鰁鳈鰂鲗鰃鳂鰆䲠鰈鲽鰉鳇鰌䲡鰍鳅"
    "鰏鲾鰐鳄鰒鳆鰓鳃鰛鳁鰜鳒鰟鳑鰠鳋鰣鲥鰥鳏鰧䲢鰨鳎鰩鳐鰭鳍鰮鳁鰱鲢鰲鳌鰳鳓鰵鳘鰷鲦鰹鲣鰺鲹鰻鳗鰼鳛鰾鳔鱂鳉鱅鳙鱈鳕鱉鳖鱒鳟鱔鳝鱖鳜鱗鳞鱘鲟鱝鲼鱟鲎鱠鲙鱣鳣鱤鳡鱧鳢鱨鲿鱭鲚鱯鳠鱷鳄鱸鲈鱺鲡鳥鸟鳧凫鳩鸠鳬凫鳲鸤鳳凤鳴鸣鳶鸢鳾䴓鴆鸩鴇鸨鴉鸦鴒鸰鴕鸵"
    "鴛鸳鴝鸲鴞鸮鴟鸱鴣鸪鴦鸯鴨鸭鴯鸸鴰鸹鴴鸻鴷䴕鴻鸿鴿鸽鵁䴔鵂鸺鵃鸼鵐鹀鵑鹃鵒鹆鵓鹁鵜鹈鵝鹅鵠鹄鵡鹉鵪鹌鵬鹏鵮鹐鵯鹎鵰雕鵲鹊鵷鹓鵾鹍鶄䴖鶇鸫鶉鹑鶊鹒鶓鹋鶖鹙鶘鹕鶚鹗鶡鹖鶥鹛鶩鹜鶪䴗鶬鸧鶯莺鶲鹟鶴鹤鶹鹠鶺鹡鶻鹘鶼鹣鶿鹚鷀鹚鷁鹢鷂鹞鷄鸡鷉䴘鷊鹝鷓鹧"
    "鷖鹥鷗鸥鷙鸷鷚鹨鷥鸶鷦鹪鷫鹔鷯鹩鷲鹫鷳鹇鷴鹇鷸鹬鷹鹰鷺鹭鷽鸴鸂㶉鸇鹯鸊䴙鸌鹱鸏鹲鸕鸬鸘鹴鸚鹦鸛鹳鸝鹂鸞鸾鹵卤鹹咸鹺鹾鹼碱鹽盐麗丽麥麦麩麸麪面麫面麯曲麴曲麵面麼么麽么黃黄黌黉點点黨党黲黪黴霉黶黡黷黩黽黾黿鼋鼂鼌鼉鼍鼕冬鼴鼹齊齐齋斋齎赍齏齑齒齿"
    "齔龀齕龁齗龂齙龅齜龇齟龃齠龆齡龄齣出齦龈齧啮齪龊齬龉齲龋齶腭齷龌龍龙龎厐龐庞龑䶮龔龚龕龛龜龟鿁䜤鿓鿒"
    # ---- 下列 547 对由 zhconv 的 zh2Hans 补齐（2026-11-16）----
    # 旧表漏了「妳→你」「暱→昵」「瞭→了」这类常用字，缺一个映射整行就对不上，
    # 简繁去重会成片失效（用户反馈「清洗后还有繁体残留」）。
    # 只用于比对，不改写正文；著/瞭 同时在 _AMBI 里，不参与繁体打分。
    "㒺罔㓂寇㕁却㕑厨㕘参㕥以㘔㗷㘭坳㝛宿㝠冥㠀岛㠯以㠶帆㡌帽㢘廉㤙恩㥦惬㨗捷㨪晃㨿据㩗携㩦携㪚散㪟敦㬉暖㬪叠㯭橹㱃饮㳒法㴱深㼝碗㽞留㿜瘪䈰筲䊀糊䗬蜂䘏恤䘑脉䘚卒䛐词"
    "䛡话䝔獾䠀蹚䠶射䥥镰䬃飒䭾驮䰟魂䳘鹅䶊衄丣卯乗乘乹干亁干亝斋亱夜亷廉亾亡俻备倐倏倣仿倸睬傚效僊仙働动儌侥兎兔兠兜冄冉冐冒冺泯凢凡凴凭刦劫刧劫刼劫剉锉剏创剙创剳札"
    "剹戮劒剑効效勅敕勌倦勦剿匟炕匲奁匳奁厀膝厰厂吚咿呌叫呪咒咊和哶咩唕唣唘启唚吣啎忤啑喋啗啖啣衔嗁啼嘑呼嘠嘎嘷嗥噉啖囓啮囙因圅函坿附垜垛垵埯塟葬塲场墖塔壻婿夘卯妬妒"
    "妳你妷侄姉姊姙妊姪侄姸妍婣姻婬淫媍妇媿愧嫰嫩嬝袅嬭奶嬾懒孼孽宂冗寃冤寑寝寳宝尅克尒尔尙尚尟鲜尠鲜屛屏屭屃岅坂峝峒嶃崭嶴岙巵卮帀匝帋纸帬裙幇帮幑徽幙幕幚帮庻庶庽寓"
    "廐厩廵巡廹迫廻回彞彝徃往徧遍怱匆怳恍恠怪恡吝悤匆惏婪惥恿惷蠢愽博慙惭慴慑慽戚憇憩戞戛戯戏戹厄抝拗挵弄捄救掽碰揑捏揫揪揷插揹背搆构搇揿搉榷搤扼搥捶搨拓搯掏搾榨摃扛"
    "撡操撦扯擕携擧举攩挡攷考敂叩敍叙敺驱旤祸旹时旾春昬昏暱昵曡叠朞期朢望朶朵杴锨枱台栁柳栞刊栢柏栰筏桒桑桮杯桺柳椗碇椶棕椷缄椾笺楥楦槕桌橜橛櫈凳櫺棂欝郁欵款歛敛歴历"
    "殀夭毧绒毬球氊毡氷冰汚污涖莅淛浙湼涅滛淫潄漱澁涩濇涩濶阔灋法灠漤烖灾煑煮煗暖熈熙燄焰爗烨牋笺牎窗牐闸牓榜牕窗牠它狥徇猂悍猨猿獘毙獧狷玅妙琖盏瑇玳瑯琅璢瑠甎砖甖罂"
    "甞尝甦苏甯宁畂亩畆亩畧略畮亩畱留疎疏疘肛疿痱痐蛔痲痳痺痹瘉愈瘖喑癄憔癅瘤癈废皐皋皜皓皷鼓盇盍盌碗眎视眡视睠眷睪睾瞇眯瞖翳瞭了矁瞅矙瞰砲炮碪砧磟碌礆硷祘算秊年秌秋"
    "秖只稉粳稬糯稭秸稾稿穤糯穨颓穽阱窓窗窰窑窻窗竝并竢俟筞策筩筒筯箸箒帚箠棰篛箬簒篡簮簪簷檐籐藤粃秕粧妆紥扎絏绁緐繁緜绵緥褓繐穗繖伞繙翻繦襁罇樽罋瓮罸罚羗羌羢绒翄翅"
    "翶翱耡锄肎肯肐胳肧胚胷胸脃脆脇胁脗吻腁胼膓肠臈腊臋臀臕膘臙胭臝裸臯皋舩船艢樯艪橹芲花茘荔荳豆菕芲萲萱著着葠参蓡参蔕蒂蕚萼蕿萱薳䓕藼萱蘐萱蘓苏蘤花蚘蛔蛕蛔蜋螂蜖蛔"
    "蜨蝶蝯猿蝱虻螎融螡蚊蟁蚊蟇蟆蠏蟹蠒茧蠭蜂衂衄衇脉衞卫衺邪袟帙袵衽裌袷裠裙褭袅襃褒襆幞襍杂覇霸覊羁覔觅覩睹觝抵詶酬誖悖謌歌譅䜧譌讹譔撰讁谪讐雠豓艳貛獾賉恤賛赞賷赍"
    "趂趁跥跺踁胫踫碰蹏蹄蹧糟蹵蹴躭耽躳躬躶裸輙辄輭软辠罪辢辣辤辞辳农迻移逈迥逥回逩奔逬迸遉侦遯遁酖鸩酧酬醆盏醕醇醯酰醻酬醼宴釬焊鉄铁銲焊鋂镅鍫锹鍳鉴鎗枪鎻锁鏚戚鐗锏"
    "鑀锿鑚钻鑛矿鑤刨鑵罐镟旋閙闹閧哄闚窥阨厄阬坑陗峭陜陕陻堙陿狭隂阴隄堤隖坞隣邻隷隶靭韧靱韧鞀鼗鞵鞋韈袜韤袜韮韭頟额頼赖顇悴顋腮顦憔飃飘飜翻飤饲餁饪餹糖餻糕餽馈饍膳"
    "饝馍駈驱騐验騣鬃驘骡骽腿骾鲠髈膀髥髯鬀剃鬉鬃鬦斗鬪斗鬰郁鴈雁鵞鹅鵶鸦鷈䴘鷰燕鷿䴙鸎莺鹻碱鼃蛙鼇鳌鼈鳖齇齄鿐䲤"
)

# 简繁两体都在用的字：参与归一、但不算繁体分，避免误删
_AMBI = set("乾著於籍瞭徵")
_T2S = None


def _t2s_map():
    """繁→简单字表，惰性构建一次（只用于比对，不改写正文）。"""
    global _T2S
    if _T2S is None:
        table = {}
        s = T2S_PAIRS
        for i in range(0, len(s) - 1, 2):
            table[s[i]] = s[i + 1]
        _T2S = table
    return _T2S


def _word_char(c):
    k = ord(c)
    if 0x4E00 <= k <= 0x9FFF or 0x3400 <= k <= 0x4DBF:
        return True
    if 0x30 <= k <= 0x39 or 0x41 <= k <= 0x5A or 0x61 <= k <= 0x7A:
        return True
    if 0xFF10 <= k <= 0xFF19 or 0xFF21 <= k <= 0xFF3A or 0xFF41 <= k <= 0xFF5A:
        return True
    return False


def _norm_key(s):
    """归一：繁→简 + 只留文字数字（标点空白不参与，繁体版换标点也认得出）。"""
    t = _t2s_map()
    return "".join(t.get(c, c) for c in s if _word_char(c))


def _trad_score(s):
    t = _t2s_map()
    return sum(1 for c in s if c in t and c not in _AMBI)


# 版本标记行：`##########  繁體版  ##########` 这种，整行只有装饰符号 + 一个版本字样。
# 简繁重复去完之后正文只剩一份，这行标记留着就是书里的一行垃圾，整行删掉。
# 只认「装饰符号 + 版本字样」的整行，正文一句话都不会被它碰到。
_VER_MARK = ("繁体版", "繁體版", "简体版", "簡體版", "繁体", "繁體",
             "简体", "簡體", "正体版", "正體版", "正体", "正體")
_VER_DECO = re.compile(r"[#=*\-_—─━~～·※◇◆■□¤°+｜|\s]")


def _is_ver_mark(s):
    """整行去掉装饰符号只剩一个版本字样 —— 站点给正文分版本用的分隔行。"""
    return len(s) <= 60 and _VER_DECO.sub("", s) in _VER_MARK


# 简繁去重的阈值：两端（Python / Web）必须完全一致，改数字要一起改。
_DD_ANCHOR   = 8     # 首/尾锚点取几个字（候选检索用）
_DD_MINLEN   = 8     # 单行模糊比对的最短归一化长度
_DD_FUZZY    = 0.9   # 单行模糊：bigram 包含率门槛
_DD_RATIO    = 1.6   # 长度比上限，防止长短悬殊的两行被误配
_DD_BLK_LEN  = 6     # 块内近似配对的最短长度
_DD_BLK_SIM  = 0.6   # 块内近似配对的包含率门槛
_DD_BLK_RUN  = 8     # 成块至少几行才认定为副本
_DD_BLK_VOTE = 4     # 偏移至少要几票才去试
_DD_BLK_TOP  = 8     # 最多试前几个偏移
_DD_BLK_EXT  = 30    # 块两端最多再扫几行


def _bi(k):
    """归一化字符串的二元组集合。"""
    if len(k) < 2:
        return {k} if k else set()
    return {k[i:i + 2] for i in range(len(k) - 1)}


def _over(a, b):
    """bigram 包含率（不是 Jaccard）：一边多插了几个乱码字，交集几乎不变，
    Jaccard 会被拉到及格线下，包含率才认得出「仍是同一句」。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def dedupe_script_dup(lines, gone_out=None):
    """同一段正文有简繁两份时删繁体那份，返回 (保留的行, 删掉的行)。

    gone_out 传入 set 时写入被删行在 lines 里的下标 —— 「清洗内容汇总」要靠它
    把删掉的位置换算成清洗后的行号。

    三步，两端一致：
      1) 繁→简归一后文本相同、字面不同、繁体字更多 → 删；
      2) 盗版站常在其中一份里乱插字（网址、乱码、伪字），归一后对不上，
         按 bigram 包含率认成同一句 → 删繁体那份；
      3) 整章「简体一份 + 繁体一份」时，连「螢幕/屏幕」这类两岸用词差异
         也会让单行比对失手，于是按偏移找出成对的整块，整块删繁体那份；
      另外 `##########  繁體版  ##########` 这类版本标记行整行删掉，
      块内两份字面一模一样的行只留一份。
    """
    n = len(lines)
    keys = [""] * n
    sc = [0] * n
    gone = set()
    for i in range(n):
        if lines[i] and _is_ver_mark(lines[i]):
            gone.add(i)             # 版本标记行：先去，别让它参与投票
    for i, s in enumerate(lines):
        if not s or i in gone:
            continue
        k = _norm_key(s)
        keys[i] = k
        if k:
            sc[i] = _trad_score(s)

    # ---- 1) 同一个归一化文本里，比最简那份更繁的行 ----
    lowest = {}
    for i in range(n):
        k = keys[i]
        if not k:
            continue
        b = lowest.get(k)
        if b is None or sc[i] < b:
            lowest[k] = sc[i]
    for i in range(n):
        k = keys[i]
        if k and lowest[k] < sc[i]:
            gone.add(i)

    gs = [None] * n
    for i in range(n):
        if len(keys[i]) >= _DD_BLK_LEN:
            gs[i] = _bi(keys[i])

    # ---- 2) 模糊：一边插了乱码，归一化文本对不上，但仍是同一句 ----
    index = {}
    for i in range(n):
        k = keys[i]
        if len(k) < _DD_MINLEN:
            continue
        for p in (k[:_DD_ANCHOR], k[-_DD_ANCHOR:]):
            index.setdefault(p, []).append(i)
    for i in range(n):
        k = keys[i]
        if len(k) < _DD_MINLEN or sc[i] <= 0:
            continue
        best, bj = 0.0, -1
        for j in index.get(k[:_DD_ANCHOR], ()) + index.get(k[-_DD_ANCHOR:], ()):
            if j == i or j in gone or sc[j] >= sc[i]:
                continue
            a, b = len(k), len(keys[j])
            if max(a, b) > min(a, b) * _DD_RATIO + 2:
                # 站点把乱码整段追加（或前置）在一行上时，长度会差出一大截，
                # 但短的那行仍是长那行的完整前缀/后缀 —— 认成同一句。
                sh, lg = (k, keys[j]) if a <= b else (keys[j], k)
                if not (lg.startswith(sh) or lg.endswith(sh)):
                    continue
            c = _over(gs[i], gs[j])
            if c > best or (c == best and (bj < 0 or j < bj)):
                best, bj = c, j
        if best >= _DD_FUZZY:
            gone.add(i)

    # ---- 3) 块对齐：按偏移投票找出成对的整块 ----
    pos = {}
    for i in range(n):
        k = keys[i]
        if len(k) < 4:
            continue
        pos.setdefault(k[:_DD_ANCHOR], []).append(i)
    votes = {}
    for ps in pos.values():
        m = len(ps)
        if m < 2 or m > 8:
            continue
        for a in range(m):
            for b in range(a + 1, m):
                d = ps[b] - ps[a]
                votes[d] = votes.get(d, 0) + 1
    order = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[:_DD_BLK_TOP]

    def near(t, d):
        """位置 t 与 t+d 是否算同一句（允许一边插了噪声字）。"""
        if t < 0 or t + d >= n:
            return False
        ka, kb = keys[t], keys[t + d]
        if not ka or not kb:
            return False
        if ka == kb:
            return True
        if len(ka) < _DD_BLK_LEN or len(kb) < _DD_BLK_LEN:
            return False
        if max(len(ka), len(kb)) > min(len(ka), len(kb)) * _DD_RATIO + 2:
            return False
        return _over(gs[t], gs[t + d]) >= _DD_BLK_SIM

    for d, sup in order:
        if sup < _DD_BLK_VOTE:
            break
        limit = n - d
        t = 0
        while t < limit:
            if not near(t, d):
                t += 1
                continue
            s0 = e0 = t
            while e0 + 1 < limit and near(e0 + 1, d):
                e0 += 1
            if e0 - s0 + 1 >= _DD_BLK_RUN:
                same = True
                for k in range(s0, e0 + 1):
                    if lines[k] != lines[k + d]:
                        same = False
                        break
                if not same:            # 两块字面完全一样 = 原文自身重复，不碰
                    lo, hi, c = s0, e0, 0
                    while lo > 0 and c < _DD_BLK_EXT and near(lo - 1, d):
                        lo -= 1
                        c += 1
                    c = 0
                    while hi + 1 < limit and c < _DD_BLK_EXT and near(hi + 1, d):
                        hi += 1
                        c += 1
                    ca = cb = 0
                    for k in range(lo, hi + 1):
                        if sc[k] > sc[k + d]:
                            ca += 1
                        elif sc[k + d] > sc[k]:
                            cb += 1
                    drop = 0 if ca >= cb else d      # 副本在哪一侧（两侧繁简打分拉平时用）
                    for k in range(lo, hi + 1):
                        if sc[k] > sc[k + d]:
                            gone.add(k)
                        elif sc[k + d] > sc[k]:
                            gone.add(k + d)
                        elif lines[k] == lines[k + d] and lines[k]:
                            gone.add(k + drop)       # 两边字面完全一样：只留一份
                    t = hi + 1
                    continue
            t = e0 + 1

    kept, dels = [], []
    for i, s in enumerate(lines):
        if i in gone:
            dels.append(s)
        else:
            kept.append(s)
    if gone_out is not None:
        gone_out.update(gone)
    return kept, dels


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


def _slim(s):
    """去掉空白与常见标点后的字符数，用来衡量这行还剩多少真内容。"""
    return len(_SLIM_RE.sub("", s))


def strip_url_tags(s):
    """清掉含网址的 HTML 标签，返回 (新文本, 是否命中, 被删标签在原行里的位置)。

    盗版站常把配图直接塞进正文（<img src="https://…jpg" alt='…'>），整串标签都是垃圾。
    命中时把这一行的标签全部去掉（否则会留下半截 </a>），标签外面的正文文字照样保留。
    第三项给预览标红用：标签是从行中间挖掉的，既不是整行删除也不是行尾裁剪。
    """
    tags = HTML_TAG_RE.findall(s)
    if not tags or not any(URL_RE.search(t) for t in tags):
        return s, False, ()
    spans = tuple((m.start(), m.end()) for m in HTML_TAG_RE.finditer(s))
    return HTML_TAG_RE.sub("", s), True, spans


def _residual(s):
    """去掉网址与 HTML 标签后还剩多少真内容：为 0 说明这行只有网址/标签。"""
    return _slim(HTML_TAG_RE.sub("", URL_BODY_RE.sub("", s)))


# ---------------------------------------------------------------- 插图链接
# 「保留插图链接」只认后缀，不联网；「插图链接校验」会真的请求一次看响应头。
# 所有联网判断都走 _img_fetch：校验只要响应头，下载才把正文读下来。
# 超时设得短：失效站不能把一次批量清洗卡在那里。
IMG_EXTS = ("jpg", "jpeg", "png", "webp", "gif")
IMG_MIMES = ("image/jpeg", "image/png", "image/gif", "image/webp")
IMG_TIMEOUT = 6.0
IMG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DeShelf/%s" % APP_VER
_IMG_SUFFIX = re.compile(r"\.(?:jpe?g|png|webp|gif)$", re.I)
_IMG_TRAIL = "'\"，。、；,;）)】"


def _img_suffix(url):
    """链接路径的后缀是不是常用图片格式（查询串、锚点不参与）。"""
    path = re.split(r"[?#]", url or "", 1)[0].rstrip("/")
    return bool(_IMG_SUFFIX.search(path))


def _img_full_url(url):
    """补全成可请求的地址：正文里的链接常写成 www.xxx.com/a.jpg。"""
    url = (url or "").strip().rstrip(_IMG_TRAIL)
    if re.match(r"^https?://", url, re.I):
        return url
    if url.startswith("//"):        # 协议相对地址：//cdn.xxx.com/a.jpg
        return "http:" + url
    if re.match(r"^(?:www\.|[a-z0-9\-]+\.)", url, re.I):
        return "http://" + url
    return ""


# 明确是网页的扩展名：book.php / index.html 这种没有参数的，一眼就知道不是图
_IMG_PAGE_EXT = (".htm", ".html", ".shtml", ".xhtml", ".php", ".asp", ".aspx",
                 ".jsp", ".jspx", ".do", ".action", ".cgi", ".pl", ".txt", ".exe")


def _img_worth_trying(url):
    """本地粗筛：明显不可能是图片的链接就别发请求了。

    一本书的正文里常有整篇的站点地址（https://www.xxxxx.com/、/book/1234/
    这种域名或目录首页），以前每条都要 HEAD/GET 一次，几百条能把导出拖很久。
    这里只拦「一眼假」的三种：
      ① 补不出完整地址的（相对路径）；
      ② 域名首页、目录页 —— 域名后面既没有文件名也没有查询参数；
      ③ 带网页后缀且没有参数的（index.html、book.php?id= 这种有参数的照试）。
    图床常见的不带图片后缀写法（/images?q=tbn:…、/showimg.php?id=9、
    /image/12345）都有参数或非网页后缀，一律放行 —— 宁可多请求一次，
    也不能把真插图漏掉。
    """
    full = _img_full_url(url)
    if not full:
        return False
    try:
        parts = urllib.parse.urlsplit(full)
    except ValueError:
        return False
    path = parts.path or ""
    if _IMG_SUFFIX.search(path):
        return True                     # 带图片后缀：候选
    if parts.query:
        return True                     # 有查询参数：图床常这么写，放行
    if not path or path.endswith("/"):
        return False                    # 域名首页 / 目录页：www.xxxxx.com/、/book/
    ext = os.path.splitext(path.rsplit("/", 1)[-1])[1].lower()
    return ext not in _IMG_PAGE_EXT    # 认不出的路径照旧试一次（可能是 /image/12345）


def _img_fetch(url, timeout=IMG_TIMEOUT, want_body=False, limit=0):
    """请求一次链接，返回 (归一化的 Content-Type, 正文)；失败一律返回 ("", b"")。

    校验与下载共用这一个出口，只是取的东西不同：
    want_body=False（校验）：先 HEAD，服务器不认 HEAD（403/405/501）时退回 GET，
                            拿到响应头就关连接，不会把整张图下下来；
    want_body=True （下载）：直接 GET，最多读 limit 字节正文。
    """
    full = _img_full_url(url)
    if not full:
        return "", b""
    headers = {"User-Agent": IMG_UA, "Accept": "image/*,*/*;q=0.8"}
    for method in (("GET",) if want_body else ("HEAD", "GET")):
        try:
            req = urllib.request.Request(full, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = resp.headers.get("Content-Type") or ""
                data = resp.read(limit + 1) if want_body else b""
            return ctype.split(";")[0].strip().lower(), data
        except urllib.error.HTTPError as e:
            # 只对“服务器不认 HEAD”的几种状态换 GET；404/500 之类就是失效
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return "", b""
        except Exception:
            return "", b""   # 超时、DNS 失败、连接被掐断 —— 按失效处理，不再拖时间
    return "", b""


def _img_content_type(url, timeout=IMG_TIMEOUT):
    """请求一次，返回归一化的 Content-Type；链接失效、超时、非 http 一律返回 ""。"""
    return _img_fetch(url, timeout)[0]


def _is_image_url(url, timeout=IMG_TIMEOUT):
    """请求一次看响应头，判断是不是插图（「插图链接校验」的判定）。"""
    return _img_content_type(url, timeout) in IMG_MIMES


def _line_links(s):
    """一行里的所有链接，返回 [(起, 止, 网址)]；网址去掉粘在末尾的标点。"""
    out = []
    for m in URL_BODY_RE.finditer(s or ""):
        url = m.group(0).rstrip(_IMG_TRAIL)
        if url:
            out.append((m.start(), m.end(), url))
    return out


def find_image_links(s, verify=False, timeout=IMG_TIMEOUT, cache=None):
    """找出一行里的插图链接，返回 [(起, 止, 网址)]。

    verify=False：只看后缀（jpg/jpeg/png/webp/gif），不发任何请求；
    verify=True ：行内每个链接（含没有图片后缀的）都请求一次，响应头 Content-Type
                  是 image/jpeg、image/png、image/gif、image/webp 才算插图；
                  返回网页的、失效的都不算 —— 顺带完成失效检测。
                  域名首页/目录页（www.xxxxx.com/、/book/）本地就判掉，不发请求。
    cache 传入 dict 可让同一条链接只判一次：键是 image_key(url)，值是布尔；
           verify_cache(prefetch_images(...)) 的结果可以直接传进来复用。
    """
    out = []
    for start, end, url in _line_links(s):
        if verify:
            key = image_key(url)
            hit = cache.get(key) if cache is not None else None
            if hit is None:
                # 首页/目录页一眼不是图，先本地拦掉再联网（同 prefetch_images）
                hit = _img_worth_trying(url) and _is_image_url(url, timeout)
                if cache is not None:
                    cache[key] = hit
            ok = hit
        else:
            ok = _img_suffix(url)
        if ok:
            out.append((start, end, url))
    return out


# ---------------------------------------------------------------- 插图下载
# 「下载插图链接」是唯一会把图片落到本机的选项：正文里的插图按出现顺序存成
# 001.jpg、002.png …，导出的 epub 再照同一份映射把链接换成 images/001.jpg。
IMG_DIRNAME = "插图"            # 输出目录下放插图的根目录
IMG_HREF_DIR = "images/"        # epub 内部的插图目录（相对 OEBPS）
IMG_DL_TIMEOUT = 20.0           # 单张图超时；比校验松，图片本身可能很大
IMG_MAX_BYTES = 16 * 1024 * 1024
IMG_MAX_TRIES = 300             # 一本书最多试这么多条链接（无后缀的也要请求一次）
IMG_PREFETCH_BYTES = 96 * 1024 * 1024   # 校验+下载合并时，预取图暂存在内存里的上限
_IMG_TAG_RE = re.compile(r"<img\b[^<>]*>", re.I)
_IMG_MIME_BY_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
_IMG_EXT_BY_MIME = {m: e for e, m in _IMG_MIME_BY_EXT.items()}
_IMG_EXT_BY_MIME["image/jpg"] = ".jpg"          # 非标准写法，个别站点这么发
_IMG_KNOWN_EXT = tuple(_IMG_MIME_BY_EXT)


def tag_attr(tag, name):
    """取标签里某个属性的值：双引号、单引号、不带引号三种写法都认。"""
    m = re.search(name + r"""\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>]+))""",
                  tag or "", re.I)
    return ((m.group(1) or m.group(2) or m.group(3) or "").strip()) if m else ""


def image_key(url):
    """链接归一化成映射键：补全协议、去掉正文里粘上的尾随标点，方便原样回找。"""
    return _img_full_url(url) or (url or "").strip().rstrip(_IMG_TRAIL)


def image_mime(name):
    return _IMG_MIME_BY_EXT.get(os.path.splitext(name or "")[1].lower(), "image/jpeg")


def html_image_sources(s):
    """取出一行里 <img src="…"> 的链接。

    这类链接不看后缀：站内图片常写成 showimg.php?id=123，按后缀永远认不出。
    """
    out = []
    for tag in _IMG_TAG_RE.findall(s or ""):
        url = tag_attr(tag, "src")
        if url:
            out.append(url)
    return out


def image_links_in_text(text):
    """按出现顺序返回整篇正文里的全部链接（去重），作为插图下载的候选。

    这里不按后缀挑：图床常写 /images?q=tbn:… 这种没有后缀的地址，后缀永远认不出。
    是不是图由下载时的响应头 / 文件头判（见 _download_image），认不出的自然被丢掉。
    <img src> 里的链接也算候选 —— 它常不带后缀，且不一定出现在正文文字里。
    """
    seen = set()
    out = []
    for line in (text or "").splitlines():
        found = [u for _s, _e, u in _line_links(line)]
        found.extend(html_image_sources(line))
        for u in found:
            k = image_key(u)
            if k and k not in seen:
                seen.add(k)
                out.append(u)
    return out


def _sniff_image_ext(data):
    """按文件头认格式：比 Content-Type 可靠（不少站点直接返回 octet-stream）。"""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ""


def _image_ext(url, ctype, data):
    """确认这次响应确实是图，并给出后缀；不是图返回 ""。

    先看文件头（最可靠），再看响应头，最后才看链接后缀。
    """
    if not data or len(data) > IMG_MAX_BYTES:
        return ""
    ext = _sniff_image_ext(data)
    if ext:
        return ext
    # 文件头认不出时只信 Content-Type：返回网页、防盗链提示的都按失败处理
    if not ctype.startswith("image/"):
        return ""
    ext = _IMG_EXT_BY_MIME.get(ctype, "")
    if ext:
        return ext
    full = _img_full_url(url)
    ext = os.path.splitext(re.split(r"[?#]", full, 1)[0])[1].lower()
    return ext if ext in _IMG_KNOWN_EXT else ""


def _fetch_image(url, timeout=IMG_DL_TIMEOUT):
    """请求一次并判断是不是插图，返回 (Content-Type, 字节, 后缀)。

    不是图（网页、失效、超大）时字节为空串。校验与下载合并时，
    「字节非空」就是「这是插图」的判据。
    """
    ctype, data = _img_fetch(url, timeout, want_body=True, limit=IMG_MAX_BYTES)
    ext = _image_ext(url, ctype, data)
    if not ext:
        return ctype, b"", ""
    return ctype, data, ext


def _download_image(url, timeout=IMG_DL_TIMEOUT):
    """下载一张插图，返回 (字节, 后缀)。

    超时、404、连不上、超过体积上限、以及“200 但返回的是网页”一律返回 (None, "")，
    由调用方跳过这一张 —— 一张图失败不该毁掉整本书的导出。
    """
    _ctype, data, ext = _fetch_image(url, timeout)
    return (data, ext) if data else (None, "")


def _to_jpeg(data, ext, quality=88):
    """jpg/jpeg/png 以外的格式（webp、gif、bmp）统一转成 jpg，返回 (字节, 后缀)。

    转换直接借用 prepare_cover_image（它内部就是 PIL 转 JPEG）；没有 Pillow 时
    它返回 None，这里就保留原格式 —— 格式支持面窄总比把图丢了强。
    """
    if ext in (".jpg", ".jpeg", ".png"):
        return data, ext
    path = None
    got = None
    try:
        fd, path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        got = prepare_cover_image(path, quality=quality)
    except Exception:
        got = None
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    if not got:
        return data, ext
    return got[0], ".jpg"


def prefetch_images(text, timeout=IMG_DL_TIMEOUT, stats=None, progress=None):
    """把正文候选链接各请求一次，返回 {链接键: (Content-Type, 字节, 后缀)}。

    「插图链接校验」与「下载插图链接」同时开着时用它：一趟请求既拿到图，
    又给出「这是不是插图」的判定，避免校验一次、下载再一次。
    字节为空即不是图。结果可交给 verify_cache / save_images 使用。
    stats 若传入 dict，会写入 links（检查条数）、images（认出张数）、bytes（暂存字节）。
    progress 传入回调时，每处理完一条链接调用一次 progress(已完成, 总数)：
             一张图可能 20 秒才超时，界面上有进度才不会让人以为程序卡住。
    首页/目录页这类一眼不是图的链接先本地拦掉（见 _img_worth_trying），
    既不浪费请求，也不占用 IMG_MAX_TRIES 的尝试名额。
    """
    urls = [u for u in image_links_in_text(text) if _img_worth_trying(u)][:IMG_MAX_TRIES]
    total = len(urls)
    out = {}
    held = 0
    for i, url in enumerate(urls, 1):
        if held >= IMG_PREFETCH_BYTES:
            # 图太多的书不硬撑内存：剩下的照旧由清洗校验、由下载另取一次
            break
        hit = _fetch_image(url, timeout)
        held += len(hit[1])
        out[image_key(url)] = hit
        _img_progress(progress, i, total)
    if stats is not None:
        stats["links"] = len(out)
        stats["images"] = sum(1 for v in out.values() if v[1])
        stats["bytes"] = held
    return out


def _img_progress(progress, done, total):
    """进度回调的唯一出口：回调是界面代码，出什么错都不该毁掉导出。"""
    if progress is None:
        return
    try:
        progress(done, total)
    except Exception:
        pass


def verify_cache(prefetch):
    """把预取结果转成「插图链接校验」的缓存：命中就不再联网。

    值是布尔（是不是图），键与 find_image_links 的缓存一致（image_key）。
    """
    return {k: bool(v[1]) for k, v in (prefetch or {}).items()}


def save_images(prefetch, text, dest_dir, stats=None):
    """按 text 里插图出现的顺序，把已预取的图片落盘，返回 {链接键: 本地路径}。

    只写清洗后仍留在正文里的图：被当广告删掉的行，它的图不再占编号。
    jpg/png 以外（webp、gif、bmp）转成 jpg 再存。
    stats 若传入 dict，会写入 links（候选链接数）与 saved（实际保存张数）。
    """
    urls = image_links_in_text(text)
    if stats is not None:
        stats["links"] = len(urls)
        stats["saved"] = 0
    if not urls or not prefetch:
        return {}
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return {}
    out = {}
    n = 0
    for url in urls:
        key = image_key(url)
        hit = prefetch.get(key)
        if not hit or not hit[1]:
            continue
        data, ext = _to_jpeg(hit[1], hit[2])     # webp/gif/bmp 统一转 jpg
        n += 1
        path = os.path.join(dest_dir, "%03d%s" % (n, ext))
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            n -= 1
            continue
        out[key] = path
    if stats is not None:
        stats["saved"] = len(out)
    return out


def download_images(text, dest_dir, timeout=IMG_DL_TIMEOUT, stats=None, progress=None):
    """把正文里的插图按出现顺序下载到 dest_dir，返回 {链接键: 本地路径}。

    候选是行内全部链接（见 image_links_in_text），真图假图由响应头决定。
    dest_dir 通常是「输出目录/插图/书名」，文件按 001.jpg、002.png … 顺序编号，
    同一条链接只下一次。jpg/png 以外（webp、gif、bmp）转成 jpg 再存，
    阅读器支持面更宽。下载失败的链接不进返回值，正文里那条链接就保持原样。
    stats 若传入 dict，会写入 links（候选链接数）与 saved（实际保存张数）。
    progress 传入回调时，每试完一条链接调用一次 progress(已试, 总试数)：
             一本书几百张图时，界面靠它显示「正在下第几张」。
    首页/目录页这类一眼不是图的链接先本地拦掉，不浪费请求（同 prefetch_images）。
    """
    urls = [u for u in image_links_in_text(text) if _img_worth_trying(u)]
    if stats is not None:
        stats["links"] = len(urls)
        stats["saved"] = 0
    if not urls:
        return {}
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return {}
    out = {}
    total = min(len(urls), IMG_MAX_TRIES)
    n = 0
    tries = 0
    for url in urls:
        # 满篇推广链接的书不该把导出卡在这里：试到上限就收手
        if tries >= IMG_MAX_TRIES:
            break
        tries += 1
        data, ext = _download_image(url, timeout)
        if data:
            data, ext = _to_jpeg(data, ext)      # webp/gif/bmp 统一转 jpg
            path = os.path.join(dest_dir, "%03d%s" % (n + 1, ext))
            try:
                with open(path, "wb") as f:
                    f.write(data)
                n += 1
                out[image_key(url)] = path
            except OSError:
                pass                             # 写不进去就跳过这一张
        _img_progress(progress, tries, total)
    if stats is not None:
        stats["saved"] = len(out)
    return out


def _promo_only_line(s):
    """整行除了推广套话和网址，几乎不剩正文。

    `欢迎关注笔趣阁，畅享百万书库https://…` 这种行里网址能有两百个字符，
    按字数判断会被当成“长正文”；这里先把网址、HTML 标签、推广套话都剥掉，
    再看还剩几个字 —— 剩不下东西就是广告行。
    """
    txt = HTML_TAG_RE.sub("", URL_BODY_RE.sub("", s or "")).strip()
    if not txt or _slim(txt) > AD_SHORT:
        return False
    if not (_PROMO_WORDS.search(txt) or SITE_RE.search(txt)):
        return False
    rest = _PROMO_WORDS.sub("", SITE_RE.sub("", txt))
    # 门槛压得很低（≤3 字）：像「他打开了网址https://…」这种真句子要留下，
    # 只有剥完推广词几乎不剩字（“欢迎关注笔趣阁，畅享百万书库”）才整行删。
    return _slim(rest) <= 3


def _ad_split(s, use_url, use_site, why=None):
    """判定一行里的广告，返回 (动作, 位置)。

    动作：
      keep — 不当作广告（正文恰好撞到关键词，或网址夹在句子中间）
      cut  — 只从位置处裁掉行尾那一截，前面的正文保留
      drop — 整行都是广告，丢弃

    很多盗版站把网址直接粘在段落末尾（“……偷走的？”WwW.xxx.com），
    旧逻辑按整行删除，会把整本书的正文一起删光，所以这里要分情况。

    why 传入 dict 时会写入 {"rule": "url" | "site"}：这一行到底是命中
    「含网址的行」还是「站点宣传行」被处理掉的，汇总要用它标清理原因。
    """
    mu = URL_RE.search(s) if use_url else None
    ms = SITE_RE.search(s) if use_site else None
    if not mu and not ms:
        return "keep", 0
    site_first = bool(ms) and (not mu or ms.start() <= mu.start())
    if why is not None:
        why["rule"] = "site" if site_first else "url"
    if site_first:
        start, end = ms.start(), ms.end()
    else:
        start = mu.start()
        mf = URL_BODY_RE.match(s, start)   # 吃下整条网址，别只算协议头
        end = mf.end() if mf else mu.end()
    head = s[:start]
    body = _slim(head)          # 这段广告前面还剩多少真内容
    total = _slim(s)            # 整行有多少真内容
    tail = s[end:]              # 整条网址后面剩下的部分
    tail_slim = _slim(tail)
    # 推广套话 + 网址、剥掉网址后没剩正文：整行就是广告。
    # 必须挡在下面「正文 + 贴行尾网址 → 只裁网址」之前，否则会留下一句推广语。
    if _promo_only_line(s):
        return "drop", 0
    if site_first:
        # 命中的是推广语：短行整行删；长行只在推广语贴着行尾时裁掉
        if total < AD_SHORT:
            return "drop", 0
        if body >= AD_MIN_BODY and len(s) - start <= AD_TAIL_MAX:
            return "cut", start
        return "keep", 0
    # 命中的是网址
    if _residual(s) == 0:
        return "drop", 0            # 整行只有网址（长图链常见）
    if AD_HEAD_RE.search(head) and total < AD_SHORT:
        return "drop", 0            # 网址前面是推广语、整行很短 → 广告行
    if tail_slim == 0 and _residual(s) < AD_MIN_BODY and not _HEAD_LINE.search(s):
        return "drop", 0            # “图片：https://…”：除网址外只剩几个字的标签，整行是广告
    if body >= AD_MIN_BODY and tail_slim == 0:
        return "cut", start         # 网址贴着行尾（多长都算），前面的正文保留
    if body < AD_MIN_BODY:
        if body == 0 and (total < AD_TINY or AD_HEAD_RE.search(head + tail)):
            return "drop", 0        # 网址打头、整行就是广告（前后都是推广语）
        # 网址前面只有几个字（“欢迎访问”），后面又接着推广语、且不长
        # → 整行仍是广告。只靠“前面有没有正文”判会漏掉这一类。
        if AD_HEAD_RE.search(tail) and tail_slim <= AD_TAIL_MAX:
            return "drop", 0
        return "keep", 0            # 其余是正文里夹着网址，宁可不动
    # 正文 + 贴行尾的广告尾巴（后面没有接着正文）→ 只裁尾巴
    if tail_slim <= AD_AFTER and len(s) - start <= AD_TAIL_MAX:
        return "cut", start
    # 网址夹在长句中间 → 不动
    return "keep", 0


def clean_text(text, enabled, stats=None, custom=None, img_cache=None, want_del=False,
               want_trace=False):
    """按启用的规则清洗文本，返回 (新文本, 删除行数)。

    stats 若传入 dict，会写入 trimmed（只裁了行尾广告、正文得以保留的行数）、
    img（被当作插图保留的行数）、blank（删掉的空行数，含掐掉的首尾空行）。
    custom 是自定义规则列表（见 compile_custom），在内置规则之后执行。
    img_cache 传入 dict 可复用「插图链接校验」的判定（见 verify_cache）：
    命中时不再联网 —— 「下载插图链接」同时开着时，导出流程就是这样把
    校验与下载合并成一趟请求的。
    want_del=True 时额外在 stats 里写入预览标红所需的三项（与 Web 版一致）：
    del（被整行删掉的原行集合）、cut（原行 → 行尾网址开始的位置）、
    mark（原行 → 行内被挖掉的若干区间）。
    want_trace=True 时额外在 stats 里写入 trace：按出现顺序记录的清理明细
    [{"kind", "line", "text", "rule", "label"}]。line 是这条内容在**原文**里的
    行号（从 1 开始；开了「合并句中断行」时按合并后的行算），kind 见
    TRACE_KINDS，text 是被清理掉的那段文字，rule 是命中的内置规则 id
    （url / site / nav / moji / jsdup / custom），label 只给自定义规则用
    （规则名或正则）。纯空格与空行不留记录。它只服务于「清洗内容汇总」的
    误删排查，平时不生成。
    """
    on = set(enabled or [])
    cust = compile_custom(custom)
    # 预览标红用：只有预览会传 want_del，批量清洗不记录，省内存也省时间
    del_lines = set() if want_del else None
    cut_map = {} if want_del else None
    mark_map = {} if want_del else None
    removed = 0
    trimmed = 0
    glued = 0
    merged = 0
    wrap_skip = 0
    blank_n = 0        # 删掉的空行数：不逐条进明细，只在汇总里单独计数
    trace = [] if want_trace else None

    def _note(kind, txt, line, rule="", label=""):
        """记一条清理明细。line 是原文行号；rule 是命中的内置规则 id，
        自定义规则记 kind=custom + label（规则名或正则），汇总据此写明
        「为什么被清理」。"""
        if trace is None:
            return
        t = (txt or "").strip()
        if t:
            trace.append({"kind": kind, "text": t, "line": line,
                          "rule": rule, "label": label})

    # 段落修复放在所有逐行规则之前：后面那些规则（网址、导航、空行）看到合并
    # 后的行才判得准，否则“本节未完”这类被切碎的广告行会漏。
    if "punct" in on or "unwrap" in on:
        lines = text.splitlines()
        if "punct" in on:
            lines, glued = fix_line_heads(lines)
        if "unwrap" in on:
            lines, merged, wrap_skip = unwrap_paragraphs(lines)
        text = "\n".join(lines)
    prev_blank = False
    use_url = "url" in on
    use_site = "site" in on
    # 插图两条规则挂在「含网址的行」下面：网址规则没开时它们无从谈起，直接不生效。
    # imgcheck 还必须同时开着 imgkeep —— 校验只是把“按后缀认”换成“按响应头认”。
    use_img = "imgkeep" in on and (use_url or use_site)
    use_imgchk = use_img and "imgcheck" in on
    img_cache = {} if img_cache is None else img_cache   # 同一条链接只判一次
    img_kept = 0                    # 被当作插图保留的行数
    # out_src 与 out 一一对应：记每行来自原文的第几行（简繁去重要靠它回找行号）
    out, out_src = [], []
    for i_raw, raw in enumerate(text.splitlines(), 1):
        s = raw
        lead = 0
        if "trim" in on:
            lead = len(raw) - len(raw.lstrip())   # 行首抹掉的空白：行内位置要加回它
            s = s.strip()
        if "half" in on:
            s = to_halfwidth(s)                   # 全角转半角一对一，长度不变
        cut = 0
        drop = False
        protect = False
        rule = ""              # 命中哪条内置规则（汇总里的「清理原因」）
        label = ""             # 自定义规则的说明（规则名或正则）
        if use_img:
            links = find_image_links(s, use_imgchk, IMG_TIMEOUT, img_cache)
            if links:
                if use_site and SITE_RE.search(s) and _residual(s) < AD_TINY:
                    # 图链落在站点宣传行里（除链接外没几个字）：跟着整行当广告删掉
                    drop = True
                    rule = "site"
                else:
                    # 这一行是插图：原样保留，不再让网址/广告规则去裁它
                    protect = True
                    img_kept += 1
        if drop:
            removed += 1
            if want_del:
                del_lines.add(raw)
            _note("drop", s, i_raw, rule)
            continue
        if use_url and not protect:
            # 含网址的 HTML 标签整块清掉，标签外的文字保留
            s_before = s
            s, tag_hit, tag_spans = strip_url_tags(s)
            if tag_hit:
                if not s.strip(" \u3000"):
                    removed += 1
                    if want_del:
                        del_lines.add(raw)
                    _note("drop", s_before, i_raw, "url")
                    continue
                if tag_spans:
                    # 标签是从行中间挖掉的：正文还在，只记被挖掉的那几段
                    _note("tag", "".join(s_before[a:z] for a, z in tag_spans),
                          i_raw, "url")
                if want_del and tag_spans:
                    # 记下被挖掉的那几段，预览要标红
                    cur = mark_map.setdefault(raw, [])
                    for a, z in tag_spans:
                        cur.append((a + lead, z + lead))
                if "trim" in on:
                    s = s.strip()
        if (use_url or use_site) and not protect:
            why = {}
            act, pos = _ad_split(s, use_url, use_site, why)
            rule = why.get("rule", rule)
            if act == "drop":
                drop = True
            elif act == "cut":
                cut = pos
        if not drop and not cut:
            if "nav" in on and NAV_RE.search(s):
                drop = True
                rule = "nav"
            elif "moji" in on and MOJI_RE.search(s):
                drop = True
                rule = "moji"
        if drop:
            removed += 1
            if want_del:
                del_lines.add(raw)
            _note("drop", s, i_raw, rule, label)
            continue
        if cut:
            # 裁掉的是行尾那截广告：留下的是 s[:cut]，被清洗掉的就是余下部分
            s_head, s_tail = s[:cut], s[cut:]
            s = s_head.rstrip(" \u3000，,、；;：:")
            if not _slim(s):
                removed += 1
                if want_del:
                    del_lines.add(raw)
                _note("drop", s_head + s_tail, i_raw, rule, label)
                continue
            trimmed += 1
            _note("cut", s_tail, i_raw, rule, label)
            if want_del:
                cut_map[raw] = cut + lead
        # 自定义规则：drop 整行丢弃，cut 只挖掉命中的片段（挖空了交给空行规则处理）
        if cust:
            hit_rm = ""
            for rx, act, note in cust:
                m = rx.search(s)
                if not m:
                    continue
                if act == "cut":
                    hit_rm = m.group(0)
                    s = s[:m.start()] + s[m.end():]
                    label = note
                    rule = "custom"
                else:
                    drop = True
                    rule = "custom"
                    label = note
                break
            if drop:
                removed += 1
                if want_del:
                    del_lines.add(raw)
                _note("drop", s, i_raw, rule, label)
                continue
            if hit_rm:
                _note("custom", hit_rm, i_raw, rule, label)
        if "blank" in on and not s:
            removed += 1
            blank_n += 1
            if want_del:
                del_lines.add(raw)
            continue
        if "blank2" in on and not s:
            if prev_blank:
                removed += 1
                blank_n += 1
                if want_del:
                    del_lines.add(raw)
                continue
            prev_blank = True
            out.append("")
            out_src.append(i_raw)
            continue
        prev_blank = False
        if "indent" in on and s:
            s = "　　" + s
        out.append(s)
        out_src.append(i_raw)
    # 简繁重复行：放在缩进之后、掐首尾空行之前，与 Web 版顺序一致
    jsdup_n = 0
    js_gone = set()          # 简繁去重删掉的行在 out 里的下标
    if "jsdup" in on and out:
        kept, dels = dedupe_script_dup(out, js_gone)
        if dels:
            jsdup_n = len(dels)
            removed += jsdup_n
            if want_del:
                del_lines.update(dels)
            if trace is not None:
                for j in sorted(js_gone):
                    _note("jsdup", out[j], out_src[j], "jsdup")
            out = kept
            out_src = [src for k, src in enumerate(out_src) if k not in js_gone]
    # 去掉首尾空行：用指针扫描避免 pop(0) 在大文本上的 O(n²)
    start = 0
    while start < len(out) and not out[start]:
        start += 1
    end = len(out)
    while end > start and not out[end - 1]:
        end -= 1
    if start or end != len(out):
        blank_n += start + (len(out) - end)   # 掐掉的首尾空行也算删掉的空行
        out = out[start:end]
        out_src = out_src[start:end]
    if trace is not None:
        # 明细里的 line 直接就是原文行号，只需按行号排一下（简繁去重的条目是
        # 循环结束后补记的，位置要回到文件顺序上）
        trace.sort(key=lambda r: r["line"])
    if stats is not None:
        stats["removed"] = removed
        stats["trimmed"] = trimmed
        stats["jsdup"] = jsdup_n
        stats["merged"] = merged
        stats["glued"] = glued
        stats["wrap_skip"] = wrap_skip
        stats["img"] = img_kept
        stats["blank"] = blank_n
        if want_del:
            stats["del"] = del_lines
            stats["cut"] = cut_map
            stats["mark"] = mark_map
        if trace is not None:
            stats["trace"] = trace
            stats["trace_n"] = len(trace)
    return "\n".join(out) + ("\n" if out else ""), removed


# ---------------------------------------------------------------- 清洗内容汇总
# 「导出分发」点「开始处理」后可以落一份汇总：按书籍分类列出被清洗掉的内容，
# 每条带清洗后的行号与命中的规则。用途单一 —— 回查“是不是把正文误删了”。

SUMMARY_NAME = "清洗内容汇总.txt"

# 清理明细的类型（clean_text 的 stats["trace"][i]["kind"]）
TRACE_KINDS = ("drop", "cut", "tag", "custom", "jsdup")

_TRACE_LABEL = {
    "zh": {"drop": "整行删除", "cut": "行尾裁剪", "tag": "HTML 标签",
           "custom": "自定义规则", "jsdup": "简繁重复"},
    "en": {"drop": "line removed", "cut": "tail trimmed", "tag": "HTML tag",
           "custom": "custom rule", "jsdup": "script duplicate"},
}

_SUM_LABEL = {
    "zh": {
        "head": APP_CN + " " + APP_EN + " · 清洗内容汇总",
        "when": "生成时间：%s",
        "rules": "清洗规则：%s",
        "custom_rules": "自定义规则：%s",
        "none": "（未启用任何规则）",
        "doc": ("说明：本文件按书籍分类汇总「开始处理」时被清洗掉的内容，用于回查误删。\n"
                "　　　原文行号 = 该内容在原文件里的行号（从 1 开始；开了「合并句中断行」"
                "按合并后的行算）；\n"
                "　　　清理原因 = 命中的那条规则（自定义规则给出规则名或正则）；\n"
                "　　　空格与空行不逐条列出，只统计删除数量。"),
        "total": "共 %d 本书 · 清理 %d 条 · 删除空行 %d 行",
        "book": "[%d/%d] 《%s》%s",
        "author": " · %s",
        "file": "源文件：%s",
        "lines": "%d 行 → 清洗后 %d 行 · 清理 %d 条 · 删除空行 %d 行",
        "lines_na": "清理 %d 条 · 删除空行 %d 行",
        "col": ("原文行号", "清理原因", "类型", "被清理的内容"),
        "stat": "原因统计：%s",
        "stat_item": "%s %d 条",
        "stat_blank": "空行 %d 行",
        "custom": "自定义规则「%s」",
        "unknown": "（未标注原因）",
        "empty": "（无清理记录）",
        "skip": "（未记录明细：%s）",
    },
    "en": {
        "head": APP_CN + " " + APP_EN + " · Cleanup Summary",
        "when": "Generated: %s",
        "rules": "Rules: %s",
        "custom_rules": "Custom rules: %s",
        "none": "(no rule enabled)",
        "doc": ("Note: this file groups everything removed by \u201cStart\u201d, by book, so you can "
                "check whether real text was deleted by mistake.\n"
                "      Src line = line number in the ORIGINAL text (1-based; with "
                "\u201cjoin wrapped lines\u201d on, lines are counted after joining);\n"
                "      Reason = the rule that removed it (custom rules show their name "
                "or pattern);\n"
                "      blank lines and whitespace are not listed one by one, only counted."),
        "total": "%d book(s) · %d record(s) · %d blank line(s) removed",
        "book": "[%d/%d] %s%s",
        "author": " by %s",
        "file": "File: %s",
        "lines": "%d lines \u2192 %d after cleaning · %d record(s) · %d blank line(s) removed",
        "lines_na": "%d record(s) · %d blank line(s) removed",
        "col": ("Src line", "Reason", "Kind", "Removed content"),
        "stat": "By reason: %s",
        "stat_item": "%s \u00d7%d",
        "stat_blank": "blank lines \u00d7%d",
        "custom": "custom rule \u201c%s\u201d",
        "unknown": "(reason not recorded)",
        "empty": "(nothing removed)",
        "skip": "(detail not recorded: %s)",
    },
}

_SUM_SEP = "=" * 78
_SUM_SUB = "-" * 78

# 汇总表格的列宽（按显示宽度算，中文占两格）
_SUM_W_LINE = 8
_SUM_W_REASON = 22
_SUM_W_KIND = 10


def _pad_label(s, width=12, min_sep=1):
    """按显示宽度补空格（中文算两格），让汇总里的各列对得齐。

    min_sep 是内容超出列宽时至少留的空格数；表头行自己带了列间隔，传 0。
    """
    s = s or ""
    w = sum(2 if ord(c) > 0x2E80 else 1 for c in s)
    return s + " " * max(min_sep, width - w)


def _sum_row(line, reason, kind, text):
    return "%*d  %s%s%s" % (_SUM_W_LINE, line, _pad_label(reason, _SUM_W_REASON),
                            _pad_label(kind, _SUM_W_KIND), text)


def _reason_text(e, name_of, kinds, L):
    """一条明细的「清理原因」：自定义规则用规则名/正则，内置规则用规则名。

    老数据没有 rule 字段时退回按类型说明，保证每条都有原因可看。
    """
    label = (e.get("label") or "").strip()
    if label:
        return L["custom"] % label
    rid = e.get("rule") or ""
    if rid == "custom":
        return kinds.get("custom", "")
    if rid and name_of.get(rid):
        return name_of[rid]
    return kinds.get(e.get("kind"), "") or L["unknown"]


def _sum_stats(entries, name_of, kinds, L, blank=0):
    """按清理原因汇总条数：返回「站点宣传行 3 条 · 含网址的行 1 条 · 空行 2 行」。"""
    counts = {}
    for e in entries:
        k = _reason_text(e, name_of, kinds, L)
        counts[k] = counts.get(k, 0) + 1
    items = [L["stat_item"] % (k, n)
             for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    if blank:
        items.append(L["stat_blank"] % blank)
    return " · ".join(items)


def summary_text(books, rules=None, lang="zh", when=None, custom=None):
    """把按书籍分类的清理记录拼成汇总文本（见 write_clean_summary）。

    books: [{"title", "author", "file", "lines_before", "lines_after", "blank",
             "entries": [{"kind", "line", "text", "rule", "label"}], "note"}]；
    entries 可直接用 clean_text(stats) 里的 stats["trace"]（rule/label 就是
    命中的规则），blank 用 stats["blank"]（删掉的空行数，只统计数量）。
    rules 是启用的内置规则 id；custom 是自定义规则列表，只用于在抬头列出
    「规则名(正则)」，方便把每条明细的原因对回具体规则。
    """
    L = _SUM_LABEL.get(lang) or _SUM_LABEL["zh"]
    kinds = _TRACE_LABEL.get(lang) or _TRACE_LABEL["zh"]
    by_id = {r["id"]: (r["name_en"] if lang == "en" else r["name"]) for r in RULES}
    # 抬头把规则标识一并列出：明细里的原因名能对回这里的 id
    names = ["%s (%s)" % (by_id.get(i, i), i) for i in (rules or [])]
    custs = ["%s (%s)" % ((r.get("name") or "").strip() or r.get("pattern", ""),
                          r.get("pattern", ""))
             for r in (custom or [])
             if isinstance(r, dict) and r.get("enabled") is not False
             and (r.get("pattern") or "").strip()]
    all_entries = [e for b in books for e in (b.get("entries") or ())]
    total = len(all_entries)
    blank_all = sum(int(b.get("blank") or 0) for b in books)

    out = [L["head"],
           L["when"] % (when or time.strftime("%Y-%m-%d %H:%M:%S")),
           L["rules"] % (", ".join(names) if names else L["none"])]
    if custs:
        out.append(L["custom_rules"] % ", ".join(custs))
    out += ["",
            L["doc"],
            "",
            L["total"] % (len(books), total, blank_all)]
    if total or blank_all:
        out.append(L["stat"] % _sum_stats(all_entries, by_id, kinds, L, blank_all))
    out.append("")
    for i, b in enumerate(books, 1):
        entries = b.get("entries") or []
        title = b.get("title") or ""
        author = b.get("author") or ""
        blank = int(b.get("blank") or 0)
        out.append(_SUM_SEP)
        out.append(L["book"] % (i, len(books), title, (L["author"] % author) if author else ""))
        if b.get("file"):
            out.append(L["file"] % b["file"])
        lb, la = b.get("lines_before"), b.get("lines_after")
        if lb is None or la is None:
            out.append(L["lines_na"] % (len(entries), blank))
        else:
            out.append(L["lines"] % (lb, la, len(entries), blank))
        stat = _sum_stats(entries, by_id, kinds, L, blank)
        if stat:
            out.append(L["stat"] % stat)
        out.append(_SUM_SUB)
        if b.get("note"):
            out.append(L["skip"] % b["note"])
        if not entries:
            out.append(L["empty"])
        else:
            out.append("  " + _pad_label(L["col"][0], _SUM_W_LINE, 0) + "  "
                       + _pad_label(L["col"][1], _SUM_W_REASON)
                       + _pad_label(L["col"][2], _SUM_W_KIND) + L["col"][3])
            for e in entries:
                txt = (e.get("text") or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
                out.append(_sum_row(int(e.get("line") or 1),
                                    _reason_text(e, by_id, kinds, L),
                                    kinds.get(e.get("kind"), e.get("kind") or ""),
                                    txt))
        out.append("")
    return "\n".join(out) + "\n"


def write_clean_summary(path, books, rules=None, lang="zh", custom=None):
    """写「清洗内容汇总.txt」，返回 (路径, 条目数)。

    按书籍分类、逐条记清洗后的行号、清理原因（命中的规则）与被清理的文字，
    并按原因统计条数，只用于分析误删；条目为空的书也会留一段说明。
    """
    data = summary_text(books, rules, lang, custom=custom)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
    return path, sum(len(b.get("entries") or ()) for b in books)


# ---------------------------------------------------------------- 自定义规则包

RULES_PACK_FORMAT = "deshelf-rules"
RULES_PACK_VERSION = 1


def compile_custom(rules):
    """把自定义规则编译成 [(正则, 动作, 说明)]，无效项直接跳过（不抛异常）。

    动作：drop = 命中就删掉整行；cut = 只删掉命中的片段，其余保留。
    说明用于「清洗内容汇总」标清理原因：规则有名字就用名字，没有就用正则本身。
    """
    out = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        if r.get("enabled") is False:
            continue
        pat = (r.get("pattern") or "").strip()
        if not pat:
            continue
        flags = 0
        if "i" in (r.get("flags") or ""):
            flags |= re.I
        if "m" in (r.get("flags") or ""):
            flags |= re.M
        note = (r.get("name") or "").strip() or pat
        try:
            out.append((re.compile(pat, flags),
                        "cut" if r.get("action") == "cut" else "drop",
                        note[:60]))
        except re.error:
            continue
    return out


def export_rules_pack(enabled, custom, name=""):
    """把当前规则状态打包成可分享的 dict（内置开关 + 自定义规则）。"""
    ids = set(enabled or [])
    builtin = [r["id"] for r in RULES if r["id"] in ids]
    return {
        "format": RULES_PACK_FORMAT,
        "version": RULES_PACK_VERSION,
        "name": name or "我的清洗规则",
        "app": APP_CN + " " + APP_EN + " " + APP_VER,
        "builtin": builtin,
        "custom": [dict(r) for r in (custom or []) if isinstance(r, dict)],
    }


def parse_rules_pack(data):
    """校验并解析规则包，返回 (builtin_ids, custom_list, name)。

    只认 deshelf-rules；内置 id 不认识的忽略，避免旧包在新版里报错。
    """
    if not isinstance(data, dict):
        raise ValueError("规则包内容不是 JSON 对象")
    if data.get("format") != RULES_PACK_FORMAT:
        raise ValueError("不是卷帙规则包：缺少 format=%s" % RULES_PACK_FORMAT)
    known = set(r["id"] for r in RULES)
    ids = [i for i in (data.get("builtin") or []) if i in known]
    cust = []
    bad = 0
    for r in (data.get("custom") or []):
        if not isinstance(r, dict):
            bad += 1
            continue
        if not (r.get("pattern") or "").strip():
            bad += 1
            continue
        try:
            re.compile(r["pattern"])
        except re.error:
            bad += 1
            continue
        item = {"name": str(r.get("name") or "")[:40],
                "pattern": r["pattern"],
                "action": "cut" if r.get("action") == "cut" else "drop",
                "flags": "".join(c for c in str(r.get("flags") or "") if c in "im"),
                "enabled": r.get("enabled") is not False}
        cust.append(item)
    return ids, cust, str(data.get("name") or ""), bad


def load_rules_pack(path):
    """从文件读规则包，返回 (builtin_ids, custom_list, name, bad)。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError("读不了规则包：%s" % e)
    return parse_rules_pack(data)


def save_rules_pack(path, enabled, custom, name=""):
    pack = export_rules_pack(enabled, custom, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(pack, f, ensure_ascii=False, indent=1)
    return path


def custom_to_text(custom):
    """把自定义规则写成一行一条的文本，方便用户直接编辑和分享。

    格式：`动作||正则||说明`（说明可空）。动作 drop = 整行删除，cut = 只删命中片段；
    想忽略大小写写成 `drop i`；行首加 # 表示这条临时停用。
    用 || 而不是空格分隔，是为了正则里的前导空格、制表符能原样往返。
    """
    lines = ["# 每行一条：动作||正则||说明（说明可空）",
             "# drop = 整行删除，cut = 只删掉命中的片段；忽略大小写写成 drop i",
             "# 行首加 # 表示这条暂时不用"]
    for r in custom or []:
        if not isinstance(r, dict):
            continue
        act = "cut" if r.get("action") == "cut" else "drop"
        fl = "".join(c for c in str(r.get("flags") or "") if c in "im")
        if fl:
            act += " " + fl
        if r.get("enabled") is False:
            act = "#" + act
        lines.append("%s||%s||%s" % (act, r.get("pattern", ""), r.get("name", "")))
    return "\n".join(lines) + "\n"


def text_to_custom(text):
    """把上面那种文本解析回规则列表；坏行跳过并计数，返回 (rules, skipped)。"""
    rules = []
    bad = 0
    for ln in (text or "").splitlines():
        raw = ln.rstrip()
        if not raw.strip():
            continue
        enabled = True
        if raw.lstrip().startswith("#"):
            trial = raw.lstrip()[1:].lstrip()
            # 只有「#drop||…」这种才是被停用的规则，普通注释行一律跳过
            if re.match(r"^(drop|cut)(?:\s+[imsx]{1,3})?\|\|", trial, re.I):
                enabled = False
                raw = trial
            else:
                continue            # 纯注释行
        raw = raw.strip()
        if "||" in raw:
            parts = raw.split("||")
            head = parts[0].strip()
            pat = parts[1] if len(parts) > 1 else ""
            note = parts[2].strip() if len(parts) > 2 else ""
        else:
            # 手写兼容：`drop 正则`，正则里的空格会被吃掉，建议用 ||
            m = re.match(r"^(drop|cut)\b\s*(.*)$", raw, re.I)
            if not m:
                bad += 1
                continue
            head, pat, note = m.group(1), m.group(2), ""
        m2 = re.match(r"^(drop|cut)(?:\s+([imsx]{1,3}))?$", head, re.I)
        if not m2 or not pat.strip():
            bad += 1
            continue
        try:
            re.compile(pat)
        except re.error:
            bad += 1
            continue
        rules.append({"name": note.strip()[:40], "pattern": pat,
                      "action": m2.group(1).lower(),
                      "flags": (m2.group(2) or "").lower(),
                      "enabled": enabled})
    return rules, bad



# ---------------------------------------------------------------- 分章

CHAPTER_PATTERNS = [
    r"第\s*[0-9０-９零〇一二三四五六七八九十百千万两]{1,15}\s*[章节節回卷篇集部]\s*[^\n]{0,40}",
    r"(?:^|\s)(?:卷|Chapter|CHAPTER|chapter)\s*[0-9０-９零〇一二三四五六七八九十百千万]{1,15}[^\n]{0,40}",
    r"(?:序章|序言|楔子|引子|尾声|後记|后记|番外|终章|結局|结局|完本)[^\n]{0,40}",
]
MAX_TITLE_LEN = 50
# 标题与正文挤在同一行时整行更长，单独放宽
MAX_INLINE_LEN = 90
# 被拆出来当标题的那截最多这么长（再长就不像标题了）
INLINE_MAX_HEAD = 30
# 冒号后至少这么长，才认作同行正文
INLINE_MIN_TAIL = 12
_INLINE_SPLIT = re.compile(r"^(.{1,40}?)[：:]\s*(.+)$")
# 盗版站把换行转成了字面 \r\n 塞在行里，判据与标题都要先剥掉
_LITERAL_ESC = re.compile(r"\\[rn]")
# 短正文（「不改稿，就退稿。」）：以句末标点收尾就算，副标题通常不带句号
_INLINE_TAIL = re.compile(r"[。！？…”」]$")


def _is_inline_body(t):
    if len(t) >= INLINE_MIN_TAIL:
        return True
    return len(t) >= 6 and bool(_INLINE_TAIL.search(t))

# 自定义章节正则的「常用写法」：界面里的模板表。桌面版直接读这里，
# 网页版在 DeShelf.html 里另存一份 JS 数组，两边内容由 test_clean_parity 比对。
# 元组 = (中文说明, English label, 正则)；正则只需能命中标题那一行（匹配从行首开始）。
CHAP_TPL = [
    ("第1章 / 第十二节 / 第三回（最常用）",
     "Chapter 1 / 第十二节 / 第三回 (most common)",
     r"第[0-9０-９零〇一二三四五六七八九十百千两]+[章节回卷篇集部]"),
    ("第一折 / 第五折（自定义量词）",
     "第一折 / 第五折 (custom counter)",
     r"第[0-9０-９零〇一二三四五六七八九十百千两]+折"),
    ("卷一 第3回（卷和回混排）",
     "卷一 第3回 (volumes and chapters mixed)",
     r"(卷[0-9０-９一二三四五六七八九十]+|第[0-9０-９一二三四五六七八九十]+回)"),
    ("01 / 02 纯数字起行",
     "01 / 02 plain numbers at line start",
     r"[0-9]{1,4}[、.．:： ]"),
    ("一、二、三、中文序号",
     "一、 二、 Chinese ordinals",
     r"[一二三四五六七八九十百千]+[、.．]"),
    ("Chapter 1 / CHAPTER 12（英文）",
     "Chapter 1 / CHAPTER 12 (English)",
     r"(Chapter|CHAPTER|chapter)\s*[0-9]+"),
    ("【第3章】/ 【第3話】（带方括号）",
     "【第3章】/ 【第3話】 (bracketed)",
     r"【?第[0-9０-９一二三四五六七八九十百千]+[话話章节節回]】?"),
    ("宽版兜底：第X章 ＋ 序章/楔子/尾声/番外",
     "Catch-all: 第X章 plus 序章/楔子/尾声/番外",
     r"(第[0-9０-９零〇一二三四五六七八九十百千两]{1,15}[章节節回卷篇集部]"
     r"|序章|序言|楔子|引子|尾声|尾聲|后记|後記|终章|終章|番外)"),
]

# 开头这几行算元信息：只由它们组成的「开篇」不单独成章
_META_LINE = re.compile(r"^(?:书名|标题|题\s*目|小说名|作\s*者|著\s*者|简介|内容简介|内容介绍)\s*[:：]")


def split_chapters(text, custom=None):
    """切分章节，返回 [(标题, 正文)]。

    custom 非空时只使用自定义正则，否则使用内置中文规则库。
    """
    return [(t, b) for t, b, _ln in split_chapters_located(text, custom)]


def split_chapters_located(text, custom=None):
    """同 split_chapters，但每章多带一个「起始行号」（0 基，原文行号）。

    正文预览要按原文行号定位章节、并逐行原样显示（空行、缩进都不能动），
    所以不能再拿「章节正文的行数」去累加——正文被 strip 过、章与章之间的
    空行也不在正文里。起始行号在切分时顺手记下最准。

    多级章节树的每一级都是独立条目，绝不压成一行：一行里写了「第一部 …
    第一卷 … 第1章 …」会拆成三条；连续几行各是一个标题时也各占一条。
    上级条目（部/卷）没有自己的正文，正文归最里面那一级；标题不会丢。
    """
    if custom:
        try:
            re.compile(custom)
        except re.error:
            raise ValueError("自定义章节正则无效，请检查语法")
        pats = [custom]
    else:
        pats = CHAPTER_PATTERNS
    chapters = []  # [(标题, 正文, 起始行号)]
    cur_title = "开篇"
    cur_start = 0
    buf = []
    for i, raw in enumerate(text.splitlines()):
        s = _LITERAL_ESC.sub("", raw.strip())
        hit = None
        tail = ""
        # 以句号结尾的通常是正文而非标题，避免“序章内容。”这类误判
        if s and len(s) <= MAX_TITLE_LEN and not s.endswith("。"):
            for p in pats:
                if re.match(p, s):
                    hit = s
                    break
        # 标题与正文挤在同一行（「第2章 《华侨文阵》：她身处的是1965年的唐人街。」）：
        # 这类行以句号结尾，走上面那条会被当成正文、整章并进前一章。
        # 判据：冒号后有一截（>=8 字）以句末标点收尾 -> 前半当标题、后半留给正文。
        if hit is None and len(s) <= MAX_INLINE_LEN:
            mm = _INLINE_SPLIT.match(s)
            if mm and len(mm.group(1).strip()) <= INLINE_MAX_HEAD:
                _t2 = mm.group(2)
                if _is_inline_body(_t2):
                    head = mm.group(1).strip()
                    for p in pats:
                        if re.match(p, head):
                            hit = head
                            tail = _t2.strip()
                            break
        if hit is not None:
            body = "\n".join(buf).strip()
            # 上一章：有正文就收下；没正文但本来就是标题（连续标题）也单独成条 ——
            # 绝不把多级标题压成一行。「开篇」的空占位不留。
            if body or cur_title != "开篇":
                chapters.append((cur_title, body, cur_start))
            # 一行里写了多级（「第一部 风起云涌 第一卷 新手村 第1章 初出茅庐」）：
            # 每级各占一条，正文行归最里面那一级；上级没有自己的正文行。
            heads = split_title_levels(hit)
            for h in heads[:-1]:
                chapters.append((h, "", i))
            cur_title = heads[-1] if heads else hit
            cur_start = i
            buf = []
            # 同行正文归到这一章，缩进照原文留
            if tail:
                buf.append(raw[:len(raw) - len(raw.lstrip())] + tail)
        else:
            buf.append(raw)
    body = "\n".join(buf).strip()
    if body:
        chapters.append((cur_title, body, cur_start))
    elif cur_title not in ("开篇",):
        # 最后一章只有标题、没有正文：标题仍要留在目录里
        chapters.append((cur_title, "", cur_start))
    # 「开篇」只装着书名/作者/简介这类元信息时不留成章：epub 的 metadata 已有这些
    if chapters and chapters[0][0] == "开篇":
        keep = [ln for ln in chapters[0][1].splitlines()
                if ln.strip() and not _META_LINE.match(ln.strip())]
        if not keep:
            chapters.pop(0)
    if not chapters:
        chapters = [("全文", text.strip(), 0)]
    return chapters


# ---------------------------------------------------------------- 章节序号校验
# 「智能分章」列表底部的「校验」栏：把每章标题解析成序号，按**本书实际出现的
# 数字变化**动态分层（不预设「部 > 卷 > 章」的固定层级 —— 每本书写法不同），
# 再从后往前复核每一层是否连号；缺章/顺序错误就写进校验栏。
# 番外类章节单独成组计算，不计入正文序列。

# 番外/外传/后记：名字里带这些词的章节单独成数组（可能夹在正文中间，也可能自带序号）
CHAPTER_EXTRA_RE = re.compile(r"番外|外传|外傳|特别篇|特別篇|后记|後記")

_CK_LABEL = {
    "zh": {"ok": "正常",
           "fail": "第{0}章序号提取失败",
           "gap": "第{0}章缺失/顺序错误",
           "gap2": "第{0}-{1}章缺失/顺序错误",
           "dup": "章节重复（第{0}章）",
           "order": "第{0}章顺序错误",
           "badnum": "章节号错误（第{0}章）",
           "sum": "共{0}个异常"},
    "en": {"ok": "OK",
           "fail": "Chapter {0}: number not recognised",
           "gap": "Chapter {0} missing or out of order",
           "gap2": "Chapters {0}-{1} missing or out of order",
           "dup": "Duplicate chapter ({0})",
           "order": "Chapter {0} out of order",
           "badnum": "Wrong chapter number ({0})",
           "sum": "{0} issue(s)"},
}

# split_chapters 造出来的占位标题：不提取序号，也不算 fail
CHAPTER_HOLD_TITLES = ("开篇", "全文")

_CN_DIGIT = {"〇": 0, "零": 0, "○": 0, "一": 1, "二": 2, "两": 2, "兩": 2,
             "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
# 序号里可能出现的数字字符（阿拉伯、全角、中文）
_NUM_CHARS = "0-9０-９〇零○一二三四五六七八九十百千万亿两兩"
# 章节量词（部 篇 集 卷 章 节 節 回 话 話 折）只用来认「这个号属于哪一类」，
# 不预设层级高低；「第一部分」是段落小标题，不算量词。


def cn_to_int(s):
    """中文 / 全角 / 阿拉伯混写的数字串 → int；认不出返回 None。

    支持 〇零○、两、十百千万亿，以及「十」开头的省略写法（十一 = 11、
    两百五十一 = 251、一百零三 = 103）。
    """
    s = (s or "").strip()
    if not s:
        return None
    t = "".join(chr(ord(c) - 0xFEE0) if 0xFF10 <= ord(c) <= 0xFF19 else c for c in s)
    if t.isdigit():
        return int(t)
    total = section = num = 0
    seen = False
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
            seen = True
        elif ch in _CN_UNIT:
            u = _CN_UNIT[ch]
            if u >= 10000:                  # 万 / 亿：先结算当前小节
                section += num
                total += (section or 1) * u
                section = num = 0
            else:
                if not num and not seen:
                    num = 1                 # 「十一」的省略写法
                section += num * u
                num = 0
            seen = True
        elif "0" <= ch <= "9":
            num = num * 10 + int(ch)
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + section + num


# 番外自带的序号：「番外一」「番外 12」「特别篇 3」「后记一」
_EXTRA_NO_RE = re.compile(
    r"(?P<u>番外|外传|外傳|特别篇|特別篇|后记|後記)\s*(?P<n>[0-9０-９]{1,6}"
    r"|[〇零○一二三四五六七八九十百千]{1,8})")
# 标题里的序号写法：「第X章」「卷三」「Chapter 12」
# 「第一部分」是章节内部的段落小标题（常见于作者感言），不是「第一部」，排除掉。
_CHAP_NO_RE = re.compile(
    r"第\s*(?P<n1>[%s]{1,12})\s*(?P<u1>部(?!分)|[篇集卷章节節回话話折])"
    r"|(?P<u2>[部篇集卷])\s*(?P<n2>[%s]{1,12})"
    r"|(?P<u3>Chapter|CHAPTER|chapter|Chap\.?|CHAP\.?)\s*(?P<n3>[0-9０-９]{1,6})"
    % (_NUM_CHARS, _NUM_CHARS))
# 纯数字起行：「12、」「01 」「十二、」
_LEAD_NO_RE = re.compile(
    r"^\s*(?P<n>[0-9０-９]{1,6}|[〇零○一二三四五六七八九十百千]{1,8})\s*(?:[、.．,，:：\s]|$)")
# 「第一部分：xxx」：章节内部的小标题，不是「第一部」，标题以此开头就不校验序号
_PART_HEAD_RE = re.compile(
    r"^\s*第\s*[0-9０-９〇零○一二三四五六七八九十百千万两]{1,12}\s*部分")
# 序号只认「结构位置」上的：标题开头、分隔符之后，或紧接上一个已识别的序号。
# 「第三十章 他还会有第二部电影吗？」里的「第二部」夹在文字中，不算上级层；
# 「第三十章 他还会有 第二部」「第二部：传奇之路 第三十章 …」这类才算。
_SEP_CHARS = set(
    " \t\r\n\u3000,，.。、：:；;!！?？·|/-\\—–~～#*_+=<>《》【】[]（）()「」『』\"'“”‘’")
# 「章」类量词：标题开头不留空格也认（「第一章陨落的天才」）。
# 「卷册」类量词（部/卷/集/篇）必须右侧有分隔符或到标题结尾才算，
# 否则「第二集的平均收视率涨到了1.81%！」这种正文句子会被当成上级章节。
_CHAP_LIKE_UNITS = set("章节節回话話折")


def chapter_number_spans(title):
    """从一个章节标题里取出全部序号及其位置，返回 [(起, 止, 值, 单位字)]。

    规则与 parse_chap_numbers 完全一致，只是多带序号在（strip 过的）标题里
    的起止下标，供 split_title_levels 按层级把一行标题切成多段。抽不到返回 []。
    """
    s = _LITERAL_ESC.sub("", title or "").strip()
    if not s:
        return []
    head = s[:40]                            # 只扫标题前 40 字，别把正文数字当序号
    m = _EXTRA_NO_RE.search(head)            # 「番外一」「后记一」：自己的号，优先认
    if m and (m.start() == 0 or head[m.start() - 1] in _SEP_CHARS):
        v = cn_to_int(m.group("n"))
        if v is not None:
            # 单位字用标记词本身：番外/后记各成一条
            return [(m.start(), m.end(), v, m.group("u"))]
    cands = []
    for m in _CHAP_NO_RE.finditer(head):
        if m.group("u1"):
            v, u = cn_to_int(m.group("n1")), m.group("u1")
        elif m.group("u2"):
            v, u = cn_to_int(m.group("n2")), m.group("u2")
        else:
            v, u = cn_to_int(m.group("n3")), "章"
        if v is not None:
            cands.append((m.start(), m.end(), v, u))
    out, last = [], -1
    for i, (st, en, v, u) in enumerate(cands):
        # 左边：标题开头、分隔符之后，或紧接上一个序号
        if not (st == 0 or st == last or head[st - 1] in _SEP_CHARS):
            continue                         # 夹在文字里，不是序号
        # 右边：都要以分隔符/结尾收束，或紧接下一个序号，否则
        # 「第二百四十五章 第二部科幻片」里的“第二部”会被当成上级层。
        # 只有「章」类量词在标题开头时豁免（「第一章陨落的天才」很常见）。
        right_ok = (en >= len(head) or head[en] in _SEP_CHARS
                    or (i + 1 < len(cands) and cands[i + 1][0] == en))
        if not right_ok and not (st == 0 and u in _CHAP_LIKE_UNITS):
            continue
        out.append((st, en, v, u))
        last = en
    if not out:                              # 「12、」「十二、」这类没有量词的写法
        m = _LEAD_NO_RE.match(head)
        if m:
            v = cn_to_int(m.group("n"))
            if v is not None:
                out.append((m.start(), m.end(), v, "章"))
    return out


def parse_chap_numbers(title):
    """从一个章节标题里取出全部序号，返回 [(值, 单位字)]，按出现顺序。

    一行里可以有多级（「第一部 第二卷 第三十一章」→ 三个号）。抽不到返回 []。
    单位字只是「这个号属于哪一类」的标识，不参与层级排序 —— 层级由
    check_chapters 按本书实际的数字变化动态推断。
    """
    return [(v, u) for _st, _en, v, u in chapter_number_spans(title)]


def split_title_levels(title):
    """把一行标题按层级序号切成多段，每段只装自己这一级。
    只有一个序号（普通章节）或抽不到序号时原样返回一段，不受影响。
    序号前零星不属于序号的文字（如「【免费】第1章 …」）跟着第一段走，不丢字。
    """
    s = _LITERAL_ESC.sub("", title or "").strip()
    spans = chapter_number_spans(s)
    if len(spans) <= 1:
        return [s] if s else []
    segs = []
    for i, (st, _en, _v, _u) in enumerate(spans):
        begin = 0 if i == 0 else st
        end = spans[i + 1][0] if i + 1 < len(spans) else len(s)
        seg = s[begin:end].strip()
        if seg:
            segs.append(seg)
    return segs or [s]


def is_extra_title(title):
    """番外 / 外传 / 特别篇：单独成组，不参与正文序号校验。"""
    return bool(CHAPTER_EXTRA_RE.search(title or ""))


class _Lv(object):
    """章节树里的一条「层」。

    层由本书实际出现的数字变化动态建立：单位字只是这一层的名字，
    parent 指向更外层（可能在建层之后才被回填），last 记这一层最近的号。
    """
    __slots__ = ("unit", "parent", "last", "nodes", "inline")

    def __init__(self, unit, parent=None, inline=False):
        self.unit = unit
        self.parent = parent
        self.last = None
        self.nodes = 0          # 挂在这一层上的章节数（0 = 只是某行的上级，自己没有章节行）
        self.inline = inline    # 这一层是标题里写出来的（「第一部 第二卷 第三十一章」），不能剪掉


def _lv_ctx(lv):
    """这一章所属上级的「身份」：各级最近的号组成元组。

    换卷/换部后元组就变了 —— 判断「是否跨了上级」靠它，而不是靠父节点是谁：
    一行三级（第一部 第二卷 第三十一章）的上级根本没有自己的章节行。
    """
    keys = []
    p = lv.parent if lv is not None else None
    while p is not None and len(keys) < 8:      # 深度封顶：防御任何意外的环
        keys.append((p.unit, p.last))
        p = p.parent
    return tuple(keys)


def _lv_has_child(levels, lv):
    """这一层下面是否已经挂了别的层。"""
    for x in levels.values():
        if x is not None and x.parent is lv:
            return True
    return False


def _add_node(node_list, ch, value, lv, vals=None):
    """把一章登记进 node_list，返回该节点（方便补充信息）。"""
    if lv is not None:
        lv.nodes += 1
    nd = {"ch": ch, "value": value, "level": lv, "ctx": _lv_ctx(lv),
          "vals": vals or ([value] if value is not None else [])}
    node_list.append(nd)
    return nd


def _infer_and_check(items, marks, holes, L, skip=(), expect=None):
    """对一组章节（正文或番外）推断层级，再从后往前复核，异常写进 marks。

    items: [(章序, [(值, 单位字)])]，按文档顺序；toks 为空表示序号提取失败。
    marks: {章序: 文案}，只写异常章。
    holes: 番外占掉的正文号（正文因此出现空洞时不算缺章）。
    skip: 不参与校验的章序（「开篇」「全文」这类占位标题）。
    expect: {章序: 推算章号}，组内连上一章都找不到时用它兜底（番外组常用）。
    返回 (树层级数, {章序: 层级}, 真挂着子章节的章序集合)。
    """
    nodes = []          # 每章一个节点：{"ch", "value", "level", "ctx"}
    levels = {}         # 单位字 -> 层
    leaf = None         # 最内层（「章」所在层）
    breaks = []         # [(节点下标, 层, 是否强判)]：推断出来的父层，供空层回退
    quiet = set(skip)   # 不写 fail、也不参与连号判断的章（占位标题、章内小标题）

    fail_run = 0                            # 连续多少个没有序号的章
    for idx, (ch, toks) in enumerate(items):
        if not toks:
            # 抽不到序号：fail，同时作为序列断点。按上一章推算它「本该是第几章」，
            # 报错时用这个号（第808条切分记录其实是第766章）而不是切分序号。
            nd = _add_node(nodes, ch, None, None)
            if leaf is not None and leaf.last is not None:
                nd["expect"] = leaf.last + 1 + fail_run
            fail_run += 1
            continue
        fail_run = 0
        if len(toks) > 1:
            # 行内自带多级：标题的书写顺序就是由外到内的层级顺序
            prev_lv = None
            for v, u in toks:
                lv = levels.get(u)
                if lv is None:
                    lv = _Lv(u, prev_lv, True)      # 标题里写明的层：不许剪枝
                    levels[u] = lv
                elif (prev_lv is not None and lv is not prev_lv and lv.parent is None
                      and lv.nodes and not _lv_has_child(levels, lv)):
                    # 把已有的层挂到这一行的上级下面。限制：
                    # 同一行重复同一个量词（标题被并成一行）不能自己当自己的父层；
                    # 这层得真有自己的章节行、且还没挂过子层，否则几个杂标题就能
                    # 把层与层首尾相接，把整棵树的层级越推越高（出现 9 级空层）。
                    lv.parent = prev_lv
                lv.last = v
                prev_lv = lv
            leaf = prev_lv
            # 只有「写在这一行里、且不是本章自己那层」的上级层才算 inline：
            # 它们没有自己的章节行，但确实是书里写出来的结构，不能剪枝。
            for _v, _u in toks[:-1]:
                lv2 = levels.get(_u)
                if lv2 is not None and lv2 is not leaf:
                    lv2.inline = True
            _add_node(nodes, ch, toks[-1][0], leaf, [v for v, _u in toks])
            continue
        v, u = toks[0]
        if leaf is None:                    # 全文第一处序号：建立最内层
            leaf = _Lv(u)
            levels[u] = leaf
            leaf.last = v
            _add_node(nodes, ch, v, leaf)
            continue
        known = levels.get(u)               # 这个单位字已经有自己的层：先回到那一层
        if known is not None and known is not leaf:
            # 例：第一卷 → 第1章 → 第二卷。不能因为 2 == 1+1 就把「卷」当成章
            known.last = v
            _add_node(nodes, ch, v, known)
            continue
        if leaf.last is not None and v == leaf.last + 1:      # 序号连续
            leaf.last = v
            _add_node(nodes, ch, v, leaf)
            continue
        if known is not None:               # 同一层里不连续：交给后面的复核报错
            known.last = v
            _add_node(nodes, ch, v, known)
            continue
        # 新单位字：要么是更内层（从 0/1 重排），要么是更外层（分级）
        nxt = items[idx + 1][1] if idx + 1 < len(items) else []
        nxt_v = nxt[0][0] if nxt else None
        nxt_u = nxt[0][1] if nxt else None
        if v in (0, 1):
            # 先看是不是「更外层」：卷/部这类标记常常插在正文中间，且前面已经连了
            # 一大段章（如「第60章」之后来「第一卷…」）。这时它只能在上层，不能把
            # 前面 60 章都变成它的子章节 —— 否则会出现「1203 章 / 9 卷」这种倒金字塔。
            if (leaf.nodes >= 5 and leaf.last is not None
                    and v <= max(3, leaf.last // 2)):
                lv = _Lv(u, leaf.parent)
                leaf.parent = lv
                levels[u] = lv
                lv.last = v
                _add_node(nodes, ch, v, lv)
                breaks.append((len(nodes) - 1, lv, True))
                continue
            # 要成「更内层」，后面得真有内容跟上：同单位接 v+1（第二篇→第三篇），
            # 或更下一级从 0/1 开始（第一卷→第1章）。都不满足就只是章内小标题
            # （如「第一篇《问道》…」），按无需校验处理，也不让它长出一层。
            if nxt_v is None or not ((nxt_u == u and nxt_v == v + 1)
                                     or (nxt_u != u and nxt_v in (0, 1))):
                quiet.add(ch)
                _add_node(nodes, ch, None, None)
                continue
            lv = _Lv(u, leaf)
            levels[u] = lv
            lv.last = v
            leaf = lv
            _add_node(nodes, ch, v, lv)
            continue
        if leaf.last is not None and (
                v <= max(3, leaf.last // 2)                  # 量级骤降：56 → 2
                or (nxt_v is not None and nxt_v == v + 1)):   # 下一章正好是 v+1
            lv = _Lv(u, leaf.parent)
            leaf.parent = lv
            levels[u] = lv
            lv.last = v
            _add_node(nodes, ch, v, lv)
            breaks.append((len(nodes) - 1, lv, False))
            continue
        # 认不出层级：就当最内层的一章，交给后面的复核报缺章/顺序错误
        leaf.last = v
        _add_node(nodes, ch, v, leaf)

    # 空层回退：判为「上级」的层要站得住脚，否则按 fail 处理并把这一层摘掉。
    # 靠「0/1 重排」推断出的层（strict）全书至少得有 2 章挂上来，孤零零一章的
    # 多半是正文里的杂标题；靠「量级骤降」推断的层只要有章节挂在它下面就算数。
    for pos, lv, strict in breaks:
        cnt = 0
        for nd in nodes:
            if nd["level"] is lv:
                cnt += 1
        if strict:
            keep = cnt >= 2
        else:
            keep = False
            for nd in nodes[pos + 1:]:
                p = nd["level"]
                p = p.parent if p is not None else None
                hop = 0
                while p is not None and hop < 8:
                    if p is lv:
                        keep = True
                        break
                    p = p.parent
                    hop += 1
                if keep:
                    break
        if keep:
            continue
        for nd in nodes:
            if nd["level"] is lv:
                for x in nd.get("vals") or ():
                    holes.add(x)                # 号还在，只是不当层级：别让邻章报缺号
                nd["value"] = None
                nd["level"] = None
        # 从树上摘掉，否则它会白白把下方所有章节的层级顶高
        for x in levels.values():
            if x is not None and x.parent is lv:
                x.parent = lv.parent
        for u, x in list(levels.items()):
            if x is lv:
                levels.pop(u, None)

    # 金字塔兜底：正常的章节树由外向内逐级变多。若某一层比它的上级还少一个数量级
    # （如「第1级 1203 章 / 第2级 9 章」），说明这层的标题根本不该算子章节 ——
    # 这些章按 fail 处理，并把这一层从树上摘掉，让父层恢复原状。
    for _round in range(3):
        counts = {}
        for nd in nodes:
            lv = nd["level"]
            if lv is not None:
                counts[lv] = counts.get(lv, 0) + 1
        bad = [lv for lv, c in counts.items()
               if lv.parent is not None and counts.get(lv.parent)
               and c * 10 <= counts[lv.parent]]
        if not bad:
            break
        for lv in bad:
            for nd in nodes:
                if nd["level"] is lv:
                    for x in nd.get("vals") or ():
                        holes.add(x)            # 号还在，只是不该当子章节
                    nd["value"] = None
                    nd["level"] = None
                    marks.pop(nd["ch"], None)
            for x in levels.values():
                if x is not None and x.parent is lv:
                    x.parent = lv.parent
            for u, x in list(levels.items()):
                if x is lv:
                    levels.pop(u, None)

    # 空层剪枝：没有任何章节挂在上面的层只是「某行的上级」，留着只会把下面
    # 所有章节的层级白白顶高（导出里就会出现「开头没分级却缩进了两格」）。
    for _round in range(4):
        counts = {}
        for nd in nodes:
            if nd["level"] is not None:
                counts[nd["level"]] = counts.get(nd["level"], 0) + 1
        empties = [lv for lv in levels.values()
                   if not counts.get(lv) and not lv.inline]
        if not empties:
            break
        for lv in empties:
            for x in levels.values():
                if x is not None and x.parent is lv:
                    x.parent = lv.parent
            for u, x in list(levels.items()):
                if x is lv:
                    levels.pop(u, None)

    # 上级章节必须真挂着子章节：同一层里，下一个同级章节出现之前如果没有
    # 任何子层章节，说明这个「卷/部」下面是空的 —— 按 fail 处理。
    kids = {}
    for lv in levels.values():
        if lv.parent is not None:
            kids.setdefault(lv.parent, []).append(lv)
    waiting = {}                            # 层 -> 还没等到子章节的那个节点
    for nd in nodes:
        lv = nd["level"]
        if lv is None:
            continue
        p = lv.parent                      # 这一章是子层章节：清掉所有祖先层的等待
        hop = 0
        while p is not None and hop < 8:
            wp = waiting.pop(p, None)
            if wp is not None:
                wp["kids"] = wp.get("kids", 0) + 1      # 记下它确实有子章节
            p = p.parent
            hop += 1
        prev_nd = waiting.pop(lv, None)
        if prev_nd is not None:            # 同级下一章都来了，它下面还是空的
            for x in prev_nd.get("vals") or ():
                holes.add(x)
            prev_nd["value"] = None
            prev_nd["level"] = None
            marks.pop(prev_nd["ch"], None)
        if kids.get(lv):
            waiting[lv] = nd
    for lv, nd in waiting.items():
        for x in nd.get("vals") or ():
            holes.add(x)
        nd["value"] = None
        nd["level"] = None
        marks.pop(nd["ch"], None)

    # 从后往前复核：每一层要么连号，要么在跨上级后从 0/1 重新递增
    by_level = {}
    for nd in nodes:
        if nd["level"] is not None:
            by_level.setdefault(nd["level"], []).append(nd)
    for lv, seq in by_level.items():
        # 先挑出「章号写错」的章：号和上一章差得离谱，而下一章又接着上一章往下数。
        # 例：705、706、707、**8**、709 —— 8 是 708 写错，只报这一章，别连累 709。
        for i in range(1, len(seq) - 1):
            cur, prev, nxt = seq[i], seq[i - 1], seq[i + 1]
            cv, pv, nv = cur["value"], prev["value"], nxt["value"]
            if cv is None or pv is None or nv is None or cv in (0, 1):
                continue                    # 从 0/1 重排交给后面的规则
            if abs(cv - pv - 1) >= 3 and 0 <= nv - pv - 1 <= 3:
                marks.setdefault(cur["ch"], L["badnum"].format(cv))
                cur["value"] = None         # 当断点：后面的章不再参考它
                cur["prev_good"] = pv       # 但下一章还得跟「上一章的好号」比
        # 再查重号：同一层、同一上级下号只能出现一次，隔多远重复都算章节重复。
        # 重复的那一章按断点处理，免得后面的章被它连累成「缺章/顺序错误」。
        seen = {}
        for nd in seq:
            v = nd["value"]
            if v is None or v in (0, 1):
                continue                    # 0/1 属于「从头上分」，交给下面的顺序错误规则
            k = (nd["ctx"], v)
            if k in seen:
                marks.setdefault(nd["ch"], L["dup"].format(v))
                nd["value"] = None
            else:
                seen[k] = nd["ch"]
        for i in range(len(seq) - 1, 0, -1):
            cur, prev = seq[i], seq[i - 1]
            cv, pv = cur["value"], prev["value"]
            if pv is None:
                pv = prev.get("prev_good")  # 上一章号写错：跟它之前的那个好号比
                if pv is None:
                    continue                # fail / 重号 是断点，不让前后连坐
            if cv is None:
                continue
            if cv == pv + 1:
                continue                    # ① 序号连续
            if cur["ctx"] != prev["ctx"] and cv in (0, 1):
                continue                    # ② 跨上级后从 0/1 重新递增
            if cv == pv:
                marks[cur["ch"]] = L["dup"].format(cv)      # 连着两章同一个号
                continue
            if cv in (0, 1):
                marks[cur["ch"]] = L["order"].format(cv)    # 没分级却从头重排
                continue
            if cv > pv + 1:
                if all(x in holes for x in range(pv + 1, cv)):
                    continue                # 缺的那些号其实是番外，不算缺章
                lo, hi = pv + 1, cv - 1
                marks[cur["ch"]] = (L["gap2"] if hi > lo else L["gap"]).format(lo, hi)
            else:
                marks[cur["ch"]] = L["gap"].format(cv)

    for nd in nodes:
        if nd["value"] is None and nd["ch"] not in marks and nd["ch"] not in quiet:
            # 报「本该是第几章」：被降级的用它自己的章号，纯 fail 的按上一章 +1，
            # 组内没有上一章时用全书文档顺序推算的号，都没有才退回切分序号。
            vals = nd.get("vals") or []
            n = vals[0] if vals else (nd.get("expect")
                                      or (expect or {}).get(nd["ch"]))
            marks[nd["ch"]] = L["fail"].format(nd["ch"] if n is None else n)

    # 每一章在树里的层级（1 = 最外层），供界面标注「第N级」。
    # 只数「前面真出现过章节」的上级层：上级章节还没出现时，这一章就是顶格，
    # 不然会出现「开头没有任何分级，却缩进两格」的假层级。
    levels, depths, seen_lv, parents = 1, {}, {}, set()
    for nd in nodes:
        lv = nd["level"]
        if lv is None:
            continue
        d, p, hop = 1, lv.parent, 0
        while p is not None and hop < 8:
            if p.inline or p in seen_lv:    # 标题里写出来的上级层也算一级
                d += 1
            p = p.parent
            hop += 1
        depths[nd["ch"]] = d
        if nd.get("kids"):
            parents.add(nd["ch"])           # 真挂着子章节的「卷/部」
        seen_lv[lv] = nd
        if d > levels:
            levels = d
    return levels, depths, parents


def check_chapters(titles, lang="zh"):
    """校验章节序号，返回 {"total", "marks", "bad", "summary", "ok", "tree",
    "levels", "lv", "depths"}。

    titles 是 split_chapters 的标题列表（顺序即章序，从 1 开始）。
    marks: {章序: 异常文案}，只含异常章；没有 key 的章在校验栏显示「正常」。
    番外类章节单独成组计算，不占正文的章序号；带上序号的番外同样会被校验。
    levels 是章节树的层级数（1 = 只有「章」一层），tree 是树里的章节数；
    lv 只收录**非最里层**的章：{章序: 层级}，界面拿它在校验栏标「第N级」；
    depths 收录全部章节的层级，供「导出章节树」按缩进排版。
    """
    L = _CK_LABEL.get(lang) or _CK_LABEL["zh"]
    titles = list(titles or ())
    if len(titles) <= 1:                    # 没切出章节（只有「全文」/「开篇」）：无从校验
        return {"total": len(titles), "marks": {}, "bad": 0, "ok": L["ok"],
                "summary": L["ok"], "tree": len(titles), "levels": 1,
                "lv": {}, "depths": {}}
    main, extra, holes, skip, toks_of = [], [], set(), set(), {}
    for i, t in enumerate(titles, 1):
        st = (t or "").strip()
        if st in CHAPTER_HOLD_TITLES or _PART_HEAD_RE.match(st):
            # 「开篇」「全文」是分章占位标题、「第一部分：xxx」是章内小标题：
            # 都不提取序号，也不算 fail，且不影响前后章节的连号判断
            skip.add(i)
            main.append((i, []))
            toks_of[i] = []
            continue
        toks = parse_chap_numbers(t)
        toks_of[i] = toks
        if is_extra_title(t):
            extra.append((i, toks))
            if toks:
                holes.add(toks[-1][0])      # 番外占掉的号：正文出现空洞时不报缺章
        else:
            main.append((i, toks))
    # 全书文档顺序上的「推算章号」：某章抽不到序号时按前一章 +1 顶上。番外自成
    # 一组、组内没有上一章，全靠这张表兜底（组内的推算优先，见 _infer_and_check）。
    expect, last_no, run = {}, None, 0
    for i in range(1, len(titles) + 1):
        if i in skip:
            continue
        toks = toks_of.get(i) or []
        if toks:
            last_no, run = toks[-1][0], 0
        elif last_no is not None:
            expect[i] = last_no + 1 + run
            run += 1
    marks = {}
    # 番外/后记里没带号的那几章（「后记终」之类）本来就不在正文序列里，不报 fail
    extra_skip = {i for i, toks in extra if not toks}
    lv_main, dep_main, kid_main = _infer_and_check(main, marks, holes, L, skip, expect)
    lv_extra, dep_extra, kid_extra = _infer_and_check(extra, marks, set(), L,
                                                      extra_skip, expect)
    # 最里层不标层级；也只有真挂着子章节的「卷/部」才标，普通章不标
    lv = {}
    for ch in kid_main:
        if dep_main.get(ch, 0) < lv_main:
            lv[ch] = dep_main[ch]
    for ch in kid_extra:
        if dep_extra.get(ch, 0) < lv_extra:
            lv[ch] = dep_extra[ch]
    bad = len(marks)
    depths = dict(dep_main)
    depths.update(dep_extra)
    return {"total": len(titles), "marks": marks, "bad": bad,
            "ok": L["ok"], "summary": L["ok"] if not bad else L["sum"].format(bad),
            "tree": len(main) + len(extra), "levels": max(lv_main, lv_extra),
            "lv": lv, "depths": depths}


def _report_meta(titles, depths):
    """导出用的「显示层级」与「序号计数」。

    显示层级取这一行**最外层**序号的层级：「第二卷 绽放的生命！ 第101章 …」这种
    把卷写在章前面的行，按级首行顶格排，它下面的子章节再缩进一级。
    序号计数只数解析出序号的章，所以「开篇」这类无序号章记 0，正文从 1 起。
    """
    meta, seq = [], 0
    for i, t in enumerate(titles, 1):
        toks = parse_chap_numbers(t)
        d = depths.get(i)
        if d is None:
            meta.append((0, 0, toks))
        else:
            seq += 1
            meta.append((max(1, d - max(0, len(toks) - 1)), seq, toks))
    return meta


_RP_LABEL = {
    "zh": {"title": "章节树导出",
           "per_level": "各级章节数：",
           "level": "  第%d级：%d 章",
           "nolevel": "  无层级（序号提取失败 / 占位标题）：%d 章",
           "hint": "章节树（缩进 = 层级；[n] 为参与编号的章序，无序号章记 0；"
                   "← 后为标题里解析出的序号链 | 校验结果）：",
           "lv": "第%d级",
           "nochain": "无序号",
           "ok": "正常"},
    "en": {"title": "Chapter tree export",
           "per_level": "Chapters per level:",
           "level": "  Level %d: %d chapter(s)",
           "nolevel": "  No level (number not parsed / placeholder): %d chapter(s)",
           "hint": "Chapter tree (indent = level; [n] = chapter index, 0 = unnumbered; "
                   "← parsed number chain | check result):",
           "lv": "Level %d",
           "nochain": "no number",
           "ok": "OK"},
}


def chapter_tree_report(titles, ck=None, head=(), indent="    ", lang="zh"):
    """把章节树摊成可排查的纯文本（「导出章节树」用）。

    head 是调用方给的表头行（书名、源文件…）；正文按层级缩进，每行给
    [序号]标题 ← 解析出的序号链 | 层级/校验结果，方便顺序号对不上时逐层看。
    跨层级（换卷/换部）之间空一行，便于肉眼分段。lang 决定表头与标签的语言。
    """
    R = _RP_LABEL.get(lang) or _RP_LABEL["zh"]
    titles = list(titles or ())
    if ck is None:
        ck = check_chapters(titles, lang)
    marks = ck.get("marks") or {}
    lvmap = ck.get("lv") or {}
    depths = ck.get("depths") or {}
    ok = ck.get("ok") or R["ok"]
    meta = _report_meta(titles, depths)
    lines = [R["title"]] + ["%s" % h for h in head]
    lines.append("")
    counts, nolevel = {}, 0
    for disp, _num, _toks in meta:
        if not disp:
            nolevel += 1
        else:
            counts[disp] = counts.get(disp, 0) + 1
    lines.append(R["per_level"])
    for d in sorted(counts):
        lines.append(R["level"] % (d, counts[d]))
    if nolevel:
        lines.append(R["nolevel"] % nolevel)
    lines.append("")
    lines.append(R["hint"])
    prev = None
    for i, (disp, num, toks) in enumerate(meta, 1):
        if prev is not None and disp < prev:
            lines.append("")                    # 层级回退 = 换卷 / 换部：空一行分段
        prev = disp
        chain = " / ".join("%d%s" % (v, u) for v, u in toks) or R["nochain"]
        msg = marks.get(i)
        if msg:
            state = ((R["lv"] % lvmap[i]) + " " if i in lvmap else "") + msg
        elif i in lvmap:
            state = "%s %s" % (R["lv"] % lvmap[i], ok)
        else:
            state = ok
        lines.append("%s[%d] %s  ← %s | %s"
                     % (indent * (disp - 1) if disp else "", num,
                        (titles[i - 1] or "").strip(), chain, state))
    return "\n".join(lines) + "\n"


def chapter_toc_nodes(titles):
    """把章节标题整理成嵌套的目录树（EPUB 的 nav / NCX 共用）。

    返回顶层节点列表，节点形如 {"title", "page", "kids"}，page 是 1 基的
    章节页序号。层级用 check_chapters 推断的 depths，与「导出章节树」是同一
    套判断，所以阅读器侧边栏的嵌套顺序和源文档的部/卷/章结构一致。
    序号抽不到的占位章按顶层算；层级不跳级（新层最多比上一章深一层），
    免得目录里凭空少一层、子节点挂到看不见的地方去。
    """
    titles = list(titles or ())
    if not titles:
        return []
    depths = check_chapters(titles).get("depths") or {}
    roots, stack = [], []  # stack: [(层深, 该层的子节点列表)]
    for i, (disp, _num, _toks) in enumerate(_report_meta(titles, depths), 1):
        d = disp or 1
        if stack:
            d = min(d, stack[-1][0] + 1)
        d = max(1, d)
        while stack and stack[-1][0] >= d:
            stack.pop()
        node = {"title": (titles[i - 1] or "").strip(), "page": i, "kids": []}
        (stack[-1][1] if stack else roots).append(node)
        stack.append((d, node["kids"]))
    return roots


def _ncx_points(nodes, ind, seq):
    """把目录树摊成嵌套的 <navPoint>：子层写进父层里，playOrder 按先序递增。"""
    pad = "  " * ind
    out = []
    for nd in nodes:
        seq[0] += 1
        n = seq[0]
        out.append('%s<navPoint id="np%d" playOrder="%d">' % (pad, n, n))
        out.append("%s  <navLabel><text>%s</text></navLabel>"
                   % (pad, _esc(nd["title"])))
        out.append('%s  <content src="c%04d.xhtml"/>' % (pad, nd["page"]))
        if nd["kids"]:
            out.extend(_ncx_points(nd["kids"], ind + 1, seq))
        out.append("%s</navPoint>" % pad)
    return out


def _nav_list(nodes, ind):
    """把目录树摊成嵌套的 <ol>（EPUB3 nav 导航文档用）。"""
    pad = "  " * ind
    out = [pad + "<ol>"]
    for nd in nodes:
        href = "c%04d.xhtml" % nd["page"]
        title = _esc(nd["title"])
        if nd["kids"]:
            out.append('%s  <li><a href="%s">%s</a>' % (pad, href, title))
            out.extend(_nav_list(nd["kids"], ind + 2))
            out.append("%s  </li>" % pad)
        else:
            out.append('%s  <li><a href="%s">%s</a></li>' % (pad, href, title))
    out.append(pad + "</ol>")
    return out


# ---------------------------------------------------------------- 导出

# 「文件名」下拉框：预设项与自定义格式共用同一套占位符解析（book=书名、author=作者名）。
# 占位符两侧不能紧贴 ASCII 字母数字，免得 notebook 里的 book 被替换；
# 中文、标点、空白一律算分隔，方便写「《book》作者：author」这类中式格式。
_NAME_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(book|author)(?![A-Za-z0-9_])")


def has_book_token(fmt):
    """格式里是否含 book 占位符（自定义格式必须含，否则命名里没有书名）。"""
    return any(m.group(1) == "book" for m in _NAME_TOKEN.finditer(fmt or ""))


# Windows 文件名里不能出现的半角字符。全角「：」「＜」等是合法的，别误伤。
NAME_ILLEGAL = '\\/:*?"<>|'


def name_fmt_bad_chars(fmt):
    """格式里出现的非法文件名字符（去重、按出现顺序），空列表表示没问题。"""
    bad = []
    for c in fmt or "":
        if c in NAME_ILLEGAL and c not in bad:
            bad.append(c)
    return bad


# 占位符周围的分隔符（空白、连接符、括号、作者标签），取值缺失时跟着一起摘掉
_NAME_EDGE = r"[\s\-—_·|,，.。:：]"
_NAME_LABEL = r"(?:作者|著者|著|by)?"


def _drop_empty_token(fmt, token):
    """把取值为空的占位符连同它的装饰整体删掉，不留「[ ] 书名」「- 书名」「《书名》作者」。

    只删占位符自己那一小段：用户写的多个空格是格式的一部分，不能在全文里压缩。
    """
    pat = (r"%(e)s*%(lab)s%(e)s*[\[【《(（]?%(e)s*"
           r"(?<![A-Za-z0-9_])%(tok)s(?![A-Za-z0-9_])"
           r"%(e)s*[\]】》）)]?%(e)s*"
           % {"e": _NAME_EDGE, "lab": _NAME_LABEL, "tok": token})
    return re.sub(pat, "", fmt, flags=re.I)


def apply_name_format(fmt, title, author, fallback="未命名"):
    """把 book/author 换成书名/作者名，返回可直接当文件（夹）名的字符串。

    用户写的空格原样保留（连续空格也得留着）；只有占位符取值为空时，才把它周围的
    空括号、「作者：」标签与分隔符摘掉，免得出现「[ ] 书名」「- 书名」这种半句。
    """
    t = (title or "").strip()
    a = (author or "").strip()
    fmt = fmt or ""
    if not a:
        fmt = _drop_empty_token(fmt, "author")
    if not t:
        fmt = _drop_empty_token(fmt, "book")
    out = _NAME_TOKEN.sub(lambda m: t if m.group(1) == "book" else a, fmt)
    out = re.sub(r"\[\s*\]|【\s*】|《\s*》|\(\s*\)|（\s*）", "", out)   # 兜底：残留空括号
    out = out.strip()                                   # 首尾空白在 Windows 文件名里非法
    out = out.strip(" -—_·:：|/\\、,，.。").strip()
    return out or t or fallback


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


# ---------------------------------------------------------------- EPUB 版面主题

# 主题不内置在代码里：styles 下的每个 .css 就是一套版面，文件名（含扩展名）
# 即主题 id，例如 "01-minimal.css"。CSS 头部用注释声明自身信息：
#   /*!
#   * @theme-name: 素笺白 Minimal White
#   * @theme-version: 1.0
#   * @description: 纯白无彩色的极简排版……
#   */
# 版本号只作记录，界面不展示。
STYLE_SUBDIR = os.path.join("styles")
DEFAULT_THEME = "01-minimal.css"
# 自定义 CSS（用户从别处导入的）不放进 styles 目录，用前缀 + 绝对路径当 id
CUSTOM_PREFIX = "custom:"
# 主题预览图（tools/gen_theme_previews.py 的默认尺寸）：给得大一点是为了
# 高分屏下也清楚；界面按固定框等比缩小显示，不会因为图大而撑变形。
THEME_PREVIEW_SIZE = (540, 880)
THEME_THUMB_SUFFIX = ".png"        # 预览图与 CSS 同名：01-minimal.css -> 01-minimal.png
# 头部字段写成 `@theme-name:`，说明行则是 `@description:`，两种都认
_THEME_META_RE = re.compile(r"@(?:theme-)?([A-Za-z]+)\s*:\s*([^\r\n*]+)")


def app_root():
    """程序根目录：源码运行时是本文件所在目录，PyInstaller 运行时是解包目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def styles_dir():
    """styles 的绝对路径（不保证存在）。

    优先 EXE 同级的 styles：主题是纯数据，用户想自己加一套 CSS
    直接放进去即可；其次才用打包进程序里的内置副本。
    """
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(app_root())
    for r in roots:
        d = os.path.join(r, STYLE_SUBDIR)
        if os.path.isdir(d):
            return d
    return os.path.join(roots[0], STYLE_SUBDIR)


def parse_theme(css, fid=""):
    """从 CSS 头部注释读出主题信息，返回 {id, name, version, desc, css, named}。

    读不到 @theme-name 时退回文件名，保证任何合法 CSS 都能当主题用；
    named 标记有没有真的读到名字（自定义 CSS 靠它决定显不显示「自定义CSS」）。
    """
    meta = {}
    for key, val in _THEME_META_RE.findall(css or ""):
        meta.setdefault(key.lower(), val.strip())
    name = meta.get("name")
    if not name:
        # 自定义主题的 id 是 custom:<路径>，退回文件名而不是整串 id
        base = fid[len(CUSTOM_PREFIX):] if fid.startswith(CUSTOM_PREFIX) else fid
        name = os.path.splitext(os.path.basename(base))[0] if base else fid
    return {
        "id": fid,
        "name": name,
        "named": bool(meta.get("name")),
        "version": meta.get("version") or "",
        "desc": meta.get("description") or "",
        "css": css or "",
    }


def read_css(path):
    """读一个 CSS 文件；UTF-8（含 BOM）读不通就按 GBK 再试一次。读不到返回 None。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (OSError, UnicodeError):
            continue
    return None


def custom_theme_id(path):
    """自定义 CSS 的主题 id：路径前面加个前缀，和内置主题（纯文件名）区分开。"""
    return CUSTOM_PREFIX + os.path.abspath(path)


def is_custom_theme(tid):
    return str(tid or "").startswith(CUSTOM_PREFIX)


def custom_theme_path(tid):
    return str(tid)[len(CUSTOM_PREFIX):]


def load_theme(tid):
    """按 id 取主题（内置 = styles 下的文件名，自定义 = custom:<路径>）。

    找不到 / 文件读不出来返回 None。
    """
    if is_custom_theme(tid):
        path = custom_theme_path(tid)
        css = read_css(path)
        if css is None:
            return None
        t = parse_theme(css, tid)
        t["path"] = path
        t["preview"] = ""
        t["stale"] = False
        t["custom"] = True
        return t
    for t in list_themes():
        if t["id"] == tid:
            return t
    return None


def theme_thumb_path(css_path):
    """CSS 对应的同名预览图路径：01-minimal.css -> 01-minimal.png。"""
    return os.path.splitext(css_path)[0] + THEME_THUMB_SUFFIX


def list_themes():
    """扫描 styles 目录，按文件名排序返回主题列表；目录不存在返回空列表。

    每个主题额外带上：
      path       CSS 绝对路径
      preview    同名预览图的绝对路径（没有图时是空串）
      stale      有图但图比 CSS 旧（改过 CSS 没重新生成）
    """
    d = styles_dir()
    try:
        names = sorted(n for n in os.listdir(d)
                       if n.lower().endswith(".css")
                       and os.path.isfile(os.path.join(d, n)))
    except OSError:
        return []
    out = []
    for n in names:
        path = os.path.join(d, n)
        css = read_css(path)
        if css is None:
            continue
        t = parse_theme(css, n)
        t["path"] = path
        png = theme_thumb_path(path)
        if os.path.isfile(png):
            t["preview"] = png
            t["stale"] = _older_than(png, path)
        else:
            t["preview"] = ""
            t["stale"] = False
        out.append(t)
    return out


def _older_than(a, b):
    """a 的修改时间早于 b（读不到时间就当没旧）。"""
    try:
        return os.path.getmtime(a) < os.path.getmtime(b)
    except OSError:
        return False


def theme_css(tid):
    """按 id 读取主题的 CSS 正文；找不到就退回默认主题，再不行给一个空样式。

    自定义 CSS（custom:<路径>）直接读那个文件，导出 EPUB 时原样打进 style.css。
    """
    if is_custom_theme(tid):
        css = read_css(custom_theme_path(tid))
        if css is not None:
            return css
    d = styles_dir()
    for name in (os.path.basename(str(tid or "")), DEFAULT_THEME):
        if not name:
            continue
        css = read_css(os.path.join(d, name))
        if css is not None:
            return css
    return '@charset "utf-8";\n'


# ---------------------------------------------------------------- 主题预览图
#
# 一套 CSS 长什么样，只能看渲染结果。预览页按 write_epub 写进 xhtml 的结构拼
# （h2 章名 + <p> 正文 + div.pic/img.pic/p.cap 插图块），截图交给无头浏览器。
# 列表用的缩略图由 tools/gen_theme_previews.py 预先烙成同名 .png，
# 程序里只有左侧大图才现渲。

# 插图用内联 SVG 占位：不必带图片文件，也能看出各主题对 div.pic / img.pic 的处理
_PREVIEW_IMG = ("data:image/svg+xml;charset=utf-8,"
                "%3Csvg xmlns='http://www.w3.org/2000/svg' width='720' height='460'%3E"
                "%3Crect width='720' height='460' fill='%23c9d2da'/%3E"
                "%3Ccircle cx='556' cy='118' r='56' fill='%23e7ecf0'/%3E"
                "%3Cpath d='M0 372 L196 236 L384 306 L556 198 L720 322 L720 460 L0 460 Z'"
                " fill='%23a7b5c1'/%3E"
                "%3C/svg%3E")

# 两套示例正文：列表缩略图要短（一屏就能看出章名、正文、插图、图注），
# 左侧大图要长（视口动辄 880~1448 高，正文太短下半页就空了）。
_PREVIEW_BODY = """  <p>黄昏时山道上起了雾，挑担的人把担子换到另一边肩头，一级一级往下走。石阶被雨水浸得发暗，鞋底踩上去，能听见细小的水声。</p>
  <p>溪水从石缝里穿出来，声音不大，却盖过了远处的雷。树下有人歇脚，把斗笠摘下来搁在膝上，帽檐还在一滴一滴地落水。</p>
  <p>“再走半个时辰就到镇上了。”他说，“这雨最多下到掌灯时分。”</p>
  <div class="pic"><img class="pic" src="%s" alt=""/></div>
  <p class="cap">图一 · 山道、溪桥与雨中的石阶</p>
  <p>雾一路漫上来，把山下的屋脊、田埂和那条浅溪都收拢在里头。等到掌灯时分，镇上的人家亮起第一盏灯，顺着石阶往下看，像一粒落进灰白里的琥珀。</p>""" % _PREVIEW_IMG

_PREVIEW_BODY_LONG = """  <p>黄昏时山道上起了雾，挑担的人把担子换到另一边肩头，一级一级往下走。石阶被雨水浸得发暗，鞋底踩上去，能听见细小的水声。</p>
  <p>溪水从石缝里穿出来，声音不大，却盖过了远处的雷。树下有人歇脚，把斗笠摘下来搁在膝上，帽檐还在一滴一滴地落水。</p>
  <p>“再走半个时辰就到镇上了。”他说，“这雨最多下到掌灯时分。”</p>
  <div class="pic"><img class="pic" src="%s" alt=""/></div>
  <p class="cap">图一 · 山道、溪桥与雨中的石阶</p>
  <p>雾一路漫上来，把山下的屋脊、田埂和那条浅溪都收拢在里头。等到掌灯时分，镇上的人家亮起第一盏灯，顺着石阶往下看，像一粒落进灰白里的琥珀。</p>
  <p>桥是老石桥，桥面的石板被磨得中间凹下去，雨天里积着浅浅一线水。过桥时他放轻了脚步，怕担子晃，也怕踩滑了。</p>
  <p>桥头有一间茶棚，竹帘半卷。掌柜的正往炉子里添炭，见他进来也不多话，只把一碗热茶推过来，茶面上浮着两片碎叶。</p>
  <p>“今年的雨来得早。”掌柜的说。</p>
  <p>“早。”他把斗笠靠在门边，“田里的稻子还差半个月。”</p>
  <p>雨声在竹帘外面铺开，像有人在远处筛豆子。棚角堆着半旧的箩筐，绳索上挂着一串晒干的红辣椒，颜色在昏灯下显得沉。</p>
  <p>喝完茶，雨果然小了。他重新挑起担子走出茶棚，石阶尽头是镇子的灯，一盏接一盏，把水洼照亮。</p>
  <p>后来他常想起那一晚：山道、溪桥、半碗剩茶，还有雨里那盏始终没有熄的灯。</p>""" % _PREVIEW_IMG


def theme_preview_html(css, width, full=False):
    """把一套 CSS 套进与 write_epub 相同的页面结构，供截图预览。

    full=True 用长正文（左侧大图），否则用短正文（列表缩略图）。
    末尾补一条预览专用规则：无头浏览器的排版视口是默认宽度（不是截图宽度），
    不把 html 宽度定死，正文就会按更宽的行长排版、右边被截掉。
    """
    fix = "html{width:%dpx !important;overflow-x:hidden;}" % int(width)
    return (
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        "  <title>版面主题预览</title>\n"
        "  <style>\n%s\n%s\n  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <h2>第一章 山雨</h2>\n"
        "%s\n"
        "</body>\n"
        "</html>\n"
    ) % (css, fix, _PREVIEW_BODY_LONG if full else _PREVIEW_BODY)


class NoBrowser(Exception):
    """本机找不到可用的浏览器，没法把 HTML 渲成图。"""


def make_renderer(outdir):
    """建一个 html2image 实例：Chrome / Edge / Chromium 依次尝试。

    每次 screenshot 都会新起一次无头浏览器（一张约 2~3 秒），所以能省的启动
    步骤都省掉；outdir 是截图落地目录，save_as 只给文件名即可。
    三个都找不到时抛 NoBrowser，由调用方决定怎么提示。
    """
    from html2image import Html2Image
    flags = ["--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=1",       # 一个截图像素对应一个 CSS 像素
             "--default-background-color=FFFFFFFF",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--disable-sync",
             "--disable-background-networking", "--disable-component-update",
             "--disable-features=Translate,BackForwardCache"]
    err = None
    for browser in ("chrome", "edge", "chromium"):
        try:
            return Html2Image(output_path=outdir, browser=browser,
                              custom_flags=list(flags), disable_logging=True)
        except Exception as e:                  # 没装这个浏览器 -> 换下一个
            err = e
    raise NoBrowser(str(err) or "no browser found")


def render_theme_thumb(theme, size=None, renderer=None):
    """把一套主题渲成同名预览图，返回图片路径。

    theme 是 list_themes() 的一项；size 默认 THEME_PREVIEW_SIZE；
    renderer 传上一次的实例可省掉重新探测浏览器的开销。
    """
    w, h = size or THEME_PREVIEW_SIZE
    css_path = theme["path"]
    out = theme_thumb_path(css_path)
    r = renderer or make_renderer(os.path.dirname(css_path))
    r.screenshot(html_str=theme_preview_html(theme["css"], w),
                 save_as=os.path.basename(out), size=(int(w), int(h)))
    return out


# ---------------------------------------------------------------- EPUB 封面

COVER_SIZE = (600, 800)              # 3:4，与常见阅读器缩略图比例一致
_COVER_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")

# 系统里的中文字体，按风格分三档：楷体最像线装书（竖排书名），黑体给现代
# 极简风，宋体留作后备。不把字体打进 EXE：楷体 11 MB、雅黑 19 MB，而 Windows
# 必然装了其中至少一种；全找不到时封面照做，只是不写字（几何版），不报错。
_COVER_FONTS = {
    "kai": (
        "C:/Windows/Fonts/simkai.ttf",        # 楷体
        "C:/Windows/Fonts/STKAITI.TTF",       # 华文楷体
        "C:/Windows/Fonts/msyh.ttc",          # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",        # 黑体
        "C:/Windows/Fonts/simsun.ttc",        # 宋体
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ),
    "hei": (
        "C:/Windows/Fonts/simhei.ttf",        # 黑体
        "C:/Windows/Fonts/msyh.ttc",          # 微软雅黑
        "C:/Windows/Fonts/STXIHEI.TTF",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ),
    "song": (
        "C:/Windows/Fonts/simsun.ttc",        # 宋体
        "C:/Windows/Fonts/STSONG.TTF",        # 华文宋体
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ),
}

_cover_font_cache = {}


def _load_font(size, kind="kai"):
    """按风格加载中文字体，返回 PIL 字体对象；都不可用返回 None。"""
    key = (kind, size)
    if key in _cover_font_cache:
        return _cover_font_cache[key]
    font = None
    try:
        from PIL import ImageFont
    except Exception:
        _cover_font_cache[key] = None
        return None
    for path in _COVER_FONTS.get(kind) or _COVER_FONTS["kai"]:
        try:
            if not os.path.exists(path):
                continue
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    _cover_font_cache[key] = font
    return font


def _book_stem(path):
    base = os.path.basename(path or "")
    base = re.sub(r"(?:\.(?:txt|text))+$", "", base, flags=re.I)
    return base.strip()


def _cover_images_in(folder):
    """目录里的图片 → {小写主名: 路径}，专供按主名回找封面用。"""
    try:
        names = os.listdir(folder)
    except OSError:
        return {}
    imgs = {}
    for n in names:
        stem, ext = os.path.splitext(n)
        if ext.lower() in _COVER_IMG_EXTS and stem.strip():
            imgs.setdefault(stem.strip().lower(), os.path.join(folder, n))
    return imgs


def find_cover_image(txt_path, title="", outdir=""):
    """找这本书同名的图片当封面（就是用户说的「当前目录下的同名图片」）。

    扫两处：书籍所在目录、导出目录（设置了才有）。同名图两处都存在时以
    书籍目录为准 —— 导出目录多半放的是「下载网络封面」下来的图，
    用户自己在书旁边放的图才是最准的那张。
    只认同名：<主名>.jpg / <主名>.cover.jpg / <书名>.jpg。
    不拿目录里随便一张 cover.jpg 兜底 —— 一个目录几十本书时会被全串成同一张。
    """
    keys = []
    for cand in (_book_stem(txt_path), (title or "").strip()):
        cand = cand.strip().lower()
        if not cand:
            continue
        keys += [cand, cand + ".cover", cand + "-cover", cand + "_cover"]
    if not keys:
        return None
    folders = []
    for folder in (os.path.dirname(os.path.abspath(txt_path or ".")), outdir):
        folder = os.path.abspath(folder) if folder else ""
        if not folder or not os.path.isdir(folder):
            continue
        # 导出目录就是书籍目录时不必再扫一遍
        if any(os.path.normcase(folder) == os.path.normcase(f) for f in folders):
            continue
        folders.append(folder)
    for folder in folders:
        imgs = _cover_images_in(folder)
        for k in keys:
            hit = imgs.get(k)
            if hit:
                return hit
    return None


def prepare_cover_image(path, max_side=1600, quality=88):
    """把找到的封面图统一转成 JPEG，返回 (data, name, media_type, w, h)。

    阅读器对 webp/gif/bmp 支持参差，统一 JPEG 最省事；顺带把超大图缩到
    max_side 内，免得一张封面把 epub 撑到几 MB。PIL 不可用时 jpg/png 原样嵌入。
    """
    try:
        from PIL import Image
    except Exception:
        Image = None
    if Image is not None:
        try:
            im = Image.open(path)
            im.load()
            if im.mode != "RGB":
                im = im.convert("RGB")
            w, h = im.size
            if max(w, h) > max_side:
                k = float(max_side) / max(w, h)
                im = im.resize((max(1, int(w * k)), max(1, int(h * k))),
                               Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality, optimize=True)
            return buf.getvalue(), "cover.jpg", "image/jpeg", im.size[0], im.size[1]
        except Exception:
            pass
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if not data:
        return None
    jpg = ext in (".jpg", ".jpeg")
    return (data, "cover.jpg" if jpg else "cover.png",
            "image/jpeg" if jpg else "image/png", 0, 0)


# 内置封面风格：(id, 中文名, 英文名)。顺序即界面下拉框里的顺序；第一种是
# 旧版那套「宣纸 + 楷体」，默认就是它，老用户升级后看到的封面不变。
COVER_STYLES = (
    ("sujian", "素笺", "Paper"),
    ("indigo", "靛蓝", "Indigo"),
    ("cinnabar", "朱印", "Vermilion"),
    ("ink", "墨韵", "Ink"),
    ("minimal", "极简", "Minimal"),
)
DEFAULT_COVER_STYLE = COVER_STYLES[0][0]


def cover_style_ids():
    """全部内置风格的 id，顺序与界面下拉框一致。"""
    return [s[0] for s in COVER_STYLES]


def cover_style_name(style_id, lang="zh"):
    """风格 id → 界面显示名；认不出的 id 按默认风格显示。"""
    en = str(lang or "").lower().startswith("en")
    for sid, cn, en_name in COVER_STYLES:
        if sid == style_id:
            return en_name if en else cn
    return cover_style_name(DEFAULT_COVER_STYLE, lang)


def cover_style_id(name, lang="zh"):
    """界面显示名 → 风格 id（下拉框回读用）；认不出就返回默认 id。"""
    for sid in cover_style_ids():
        if cover_style_name(sid, lang) == name:
            return sid
    return DEFAULT_COVER_STYLE


def _draw_vcol(d, text, cx, y0, font, fill, lh=1.15):
    """竖排一列：逐字水平居中地往下画，返回下一行的 y。"""
    y = y0
    size = font.size
    for ch in text:
        try:
            tw = d.textlength(ch, font=font)
        except Exception:
            tw = size
        d.text((cx - tw / 2.0, y), ch, font=font, fill=fill)
        y += size * lh
    return y


def _vlayout(text, box_w, box_h, hi=112, lo=22, lh=1.15, ratio=1.35):
    """竖排字号与列数：短书名一列到底（别拆成 3+1），一列放不下才从右往左折。"""
    n = max(1, len(text))
    for s in range(hi, lo, -2):
        if n * s * lh <= box_h and s * ratio <= box_w:
            return s, n, 1
    for s in range(hi, lo, -2):
        per = max(1, int(box_h / (s * lh)))
        cols = -(-n // per)
        if cols * s * ratio <= box_w:
            return s, per, cols
    per = max(1, int(box_h / (lo * lh)))
    return lo, per, -(-n // per)


def _draw_vtitle(d, text, box, fill, kind="kai", hi=112, lh=1.15, ratio=1.35,
                 right_edge=None):
    """在 box=(左, 上, 右, 下) 里竖排书名，返回排版信息（没字体时返回 None）。

    right_edge 给了就靠右排（书名整体贴右边，左侧留白给作者/界栏），
    否则在 box 里水平居中。
    """
    left, top, right, bottom = box
    size, per, cols = _vlayout(text, right - left, bottom - top,
                               hi=hi, lh=lh, ratio=ratio)
    font = _load_font(size, kind)
    if font is None:
        return None
    col_w = size * ratio
    if right_edge is None:
        total = cols * col_w - (col_w - size)
        x_right = (left + right) / 2.0 + total / 2.0 - size / 2.0
    else:
        x_right = right_edge - size / 2.0
        need = x_right - (cols - 1) * col_w - size / 2.0
        if need < left + 12:                 # 折列时别把最左一列挤出画面
            x_right += left + 12 - need
    block_h = min(per, len(text)) * size * lh
    y0 = top + ((bottom - top) - block_h) / 2.0
    for ci in range(cols):
        chunk = text[ci * per:(ci + 1) * per]
        if chunk:
            _draw_vcol(d, chunk, x_right - ci * col_w, y0, font, fill, lh)
    return {"size": size, "font": font, "per": per, "cols": cols,
            "x_right": x_right, "y0": y0, "block_h": block_h}


def _hwidth(d, text, font, track=0):
    """横排整行宽度（含字间距），算不出来就按字号估。"""
    try:
        return (sum(d.textlength(c, font=font) for c in text)
                + track * (len(text) - 1))
    except Exception:
        return len(text) * (font.size + track)


def _draw_htext(d, text, cx, y, font, fill, track=0):
    """横排画一行并水平居中，track 是字间距（极简风格的疏排）。"""
    x = cx - _hwidth(d, text, font, track) / 2.0
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        try:
            x += d.textlength(ch, font=font) + track
        except Exception:
            x += font.size + track


def _fit_hfont(d, text, max_w, kind="kai", hi=34, lo=15, track=0):
    """横排文字：在 max_w 内找最大字号，返回字体（没字体返回 None）。"""
    for s in range(hi, max(lo, 8) - 1, -1):
        f = _load_font(s, kind)
        if f is None:
            return None
        if _hwidth(d, text, f, track) <= max_w:
            return f
    return _load_font(lo, kind)


def _draw_author(d, text, cx, y, max_w, fill, kind="kai", hi=32, lo=16, track=0):
    """横排作者名：超宽自动缩字号，居中画在 y 行。"""
    font = _fit_hfont(d, text, max_w, kind, hi, lo, track)
    if font is not None:
        _draw_htext(d, text, cx, y, font, fill, track)


def _vgradient(size, top, bottom):
    """竖向渐变底：逐行画线，600x800 也就几毫秒，不必引第三方库。"""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", size, top)
    d = ImageDraw.Draw(im)
    steps = float(max(1, h - 1))
    for y in range(h):
        t = y / steps
        d.line([0, y, w, y], fill=(
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t)))
    return im


def _cover_sujian(text, author, size):
    """素笺：宣纸底 + 双层旧金细框 + 竖排楷体书名，书名上下各一道鱼尾金线。"""
    from PIL import Image, ImageDraw
    W, H = size
    PAPER, INK = (246, 241, 228), (47, 42, 36)
    GOLD, GRAY = (198, 180, 148), (120, 110, 96)
    im = Image.new("RGB", size, PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([18, 18, W - 19, H - 19], outline=GOLD, width=2)
    d.rectangle([30, 30, W - 31, H - 31], outline=GOLD, width=1)

    # 书名区上留 150、下留 190：作者行在 H-128，下方的鱼尾线不能压到它
    info = _draw_vtitle(d, text, (130, 150, W - 130, H - 190), INK, "kai", hi=112)
    if info:
        px_ = info["size"]
        half = px_ * 0.62
        cx = info["x_right"]
        d.line([cx - half, info["y0"] - px_ * 0.55,
                cx + half, info["y0"] - px_ * 0.55], fill=GOLD, width=2)
        d.line([cx - half, info["y0"] + info["block_h"] + px_ * 0.38,
                cx + half, info["y0"] + info["block_h"] + px_ * 0.38],
               fill=GOLD, width=2)
    if author:
        _draw_author(d, author, W / 2.0, H - 128, W - 150, GRAY)
    return im


def _cover_indigo(text, author, size):
    """靛蓝：深靛蓝渐变 + 冷灰细框 + 米白竖排书名，左侧一道竖金线当界栏。"""
    from PIL import ImageDraw
    W, H = size
    im = _vgradient(size, (34, 50, 78), (13, 20, 34))
    d = ImageDraw.Draw(im)
    d.rectangle([34, 34, W - 35, H - 35], outline=(92, 112, 146), width=1)
    d.rectangle([44, 44, W - 45, H - 45], outline=(64, 80, 110), width=1)

    info = _draw_vtitle(d, text, (0, 96, W, H - 200), (240, 232, 214),
                        "kai", hi=100, right_edge=W - 88)
    if info:
        px_ = info["size"]
        x = info["x_right"] - px_ * 0.95
        d.line([x, info["y0"] - px_ * 0.26, x,
                info["y0"] + info["block_h"] + px_ * 0.26],
               fill=(146, 122, 84), width=2)
        if author:
            font = _load_font(30, "kai")
            if font is not None:
                _draw_vcol(d, author, 108, info["y0"] + px_ * 1.9,
                           font, (150, 164, 188))
    return im


def _cover_cinnabar(text, author, size):
    """朱印：米色纸面，右侧朱红色条内竖排反白书名，左侧竖排作者加「著」。"""
    from PIL import Image, ImageDraw
    W, H = size
    im = Image.new("RGB", size, (243, 236, 224))
    d = ImageDraw.Draw(im)
    bx0, bx1 = W - 224, W - 58
    d.rectangle([bx0, 58, bx1, H - 58], fill=(152, 52, 42))

    _draw_vtitle(d, text, (bx0 + 12, 84, bx1 - 12, H - 84),
                 (246, 238, 226), "kai", hi=74)
    if author:
        font = _load_font(34, "kai")
        if font is not None:
            y = _draw_vcol(d, author, 112, 130, font, (56, 46, 38))
            small = _load_font(22, "kai")
            if small is not None:
                _draw_vcol(d, "著", 112, y + 14, small, (154, 140, 120))
    return im


def _cover_ink(text, author, size):
    """墨韵：近黑渐变 + 模糊墨晕 + 极暗细框 + 暖白竖排书名。"""
    from PIL import Image, ImageDraw, ImageFilter
    W, H = size
    im = _vgradient(size, (36, 35, 33), (11, 11, 12))
    wash = Image.new("L", size, 0)
    wd = ImageDraw.Draw(wash)
    wd.ellipse([-W * 0.25, H * 0.18, W * 0.85, H * 1.05], fill=110)
    wd.ellipse([W * 0.45, -H * 0.12, W * 1.25, H * 0.55], fill=70)
    wash = wash.filter(ImageFilter.GaussianBlur(90))
    im = Image.composite(Image.new("RGB", size, (58, 55, 50)), im, wash)

    d = ImageDraw.Draw(im)
    d.rectangle([42, 42, W - 43, H - 43], outline=(78, 73, 64), width=1)
    info = _draw_vtitle(d, text, (0, 96, W, H - 200), (230, 224, 211),
                        "kai", hi=104, right_edge=W - 106)
    if info:
        px_ = info["size"]
        cx, half = info["x_right"], px_ * 0.34
        d.line([cx - half, info["y0"] - px_ * 0.28,
                cx + half, info["y0"] - px_ * 0.28],
               fill=(150, 126, 86), width=2)
        y_bot = info["y0"] + info["block_h"] + px_ * 0.16
        d.line([cx - half, y_bot, cx + half, y_bot],
               fill=(150, 126, 86), width=2)
    if author:
        _draw_author(d, author, W / 2.0, H - 132, W - 150,
                     (138, 130, 118), track=6)
    return im


def _cover_minimal(text, author, size):
    """极简：米白底 + 黑体疏排横书书名，下面一行小字作者。"""
    from PIL import Image, ImageDraw
    W, H = size
    im = Image.new("RGB", size, (247, 246, 243))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, H - 1], outline=(228, 226, 220), width=1)

    # 字距按字号比例算，所以字号得连字距一起试，不能先定字号再排
    size_px, font = 96, None
    while size_px > 22:
        font = _load_font(size_px, "hei")
        if font is None:
            break
        if _hwidth(d, text, font, size_px * 0.12) <= W - 200:
            break
        size_px -= 4
    if font is not None:
        cy = H * 0.46
        _draw_htext(d, text, W / 2.0, cy - size_px / 2.0, font,
                    (32, 31, 30), size_px * 0.12)
        if author:
            _draw_author(d, author, W / 2.0, cy + size_px * 0.92, W - 240,
                         (122, 118, 112), "hei", hi=26, lo=14, track=8)
    return im


_COVER_DRAW = {
    "sujian": _cover_sujian,
    "indigo": _cover_indigo,
    "cinnabar": _cover_cinnabar,
    "ink": _cover_ink,
    "minimal": _cover_minimal,
}


def make_cover(title, author="", size=COVER_SIZE, style=DEFAULT_COVER_STYLE):
    """按风格画一张内置封面（默认「素笺」：宣纸底 + 旧金细框 + 竖排楷体书名）。

    style: COVER_STYLES 里的 id；认不出（旧配置、手改过的值）就画默认风格。
    返回 (data, "cover.jpg", "image/jpeg", w, h)；PIL 不可用返回 None
    （该 epub 就不带封面，与旧版行为一致，不抛异常）。
    """
    try:
        from PIL import Image                # noqa: F401  （只用来探活）
    except Exception:
        return None
    text = (title or "未命名").strip() or "未命名"
    author = (author or "").strip()
    draw = _COVER_DRAW.get(style) or _COVER_DRAW[DEFAULT_COVER_STYLE]
    im = draw(text, author, size)
    if im is None:
        return None
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90, optimize=True)
    return buf.getvalue(), "cover.jpg", "image/jpeg", size[0], size[1]


def cover_for_book(txt_path, title, author="", mode="auto", outdir="",
                   style=DEFAULT_COVER_STYLE):
    """按模式为这本书准备封面，返回 (data, name, mime, w, h) 或 None。

    mode: "none" 不带封面 / "default" 只生成内置封面 /
          "auto"（默认）先找同名图片，找不到再按 style 生成内置封面
    outdir: 导出目录；给了就一起扫同名图（书籍目录优先，见 find_cover_image）
    style: 内置封面风格 id（见 COVER_STYLES），只影响「找不到同名图」那一步
    """
    if mode == "none":
        return None
    if mode != "default":
        found = find_cover_image(txt_path, title, outdir)
        if found:
            got = prepare_cover_image(found)
            if got:
                return got
    return make_cover(title, author, style=style)


def download_cover_image(url, dest_path, timeout=IMG_DL_TIMEOUT):
    """下载一张网络封面：转成 JPEG 后写到 dest_path。

    返回 prepare_cover_image 的元组 (data, name, mime, w, h)；下载失败、
    链接返回的不是图片、写盘失败一律返回 None，由界面提示用户重试。
    请求走插图下载同一套逻辑（超时、体积上限、按文件头认格式）。
    """
    data, ext = _download_image(url, timeout)
    if not data:
        return None
    tmp = None
    got = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=ext or ".jpg")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        got = prepare_cover_image(tmp)
    except Exception:
        got = None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if not got:
        return None
    folder = os.path.dirname(dest_path)
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(got[0])
    except OSError:
        return None
    return got


CONTAINER = """<?xml version='1.0' encoding='utf-8'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# epub 里的封面文件名按 MIME 归一：封面可能是用户自选的图、网上下载的图，
# 原名带着书名或奇怪后缀（.webp/.bmp），装进 zip 容易被阅读器当成图片以外的东西。
_COVER_EXT_BY_MIME = {"image/png": ".png", "image/gif": ".gif",
                      "image/webp": ".webp", "image/bmp": ".bmp"}

_COVER_PAGE = """<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <title>封面</title>
  <style type="text/css">html,body{margin:0;padding:0;height:100%;}
div.cover{height:100%;text-align:center;}
div.cover img{max-width:100%;max-height:100%;}</style>
</head>
<body>
  <div class="cover"><img src="__COVER_SRC__" alt="封面"/></div>
</body>
</html>
"""


def _esc_attr(s):
    """属性值转义：除了 & < >，引号也要转，否则 alt 里的引号会把标签截断。"""
    return _esc(s or "").replace('"', "&quot;")


def _img_tag_html(href, alt=""):
    return '<img class="pic" src="%s" alt="%s"/>' % (href, _esc_attr(alt))


_PH_RE = re.compile(r"\x00\d+\x00")


def _put_back(esc, slots):
    """把占位符换回 <img> 标签。占位符里带 \x00，_esc 不会动它。

    slots 是 [(本地路径, alt)]：夹在正文里的插图只把 alt 留在 alt 属性上，
    图注另起一段会把一句话割断。
    """
    for i, (href, alt) in enumerate(slots):
        esc = esc.replace("\x00%d\x00" % i, _img_tag_html(href, alt))
    return esc


def _pic_block(slots):
    """插图独占一段：图在上，HTML 写法里的 alt 当图注显示在图下方。"""
    parts = []
    for href, alt in slots:
        cap = '<p class="cap">%s</p>' % _esc(alt) if alt else ""
        parts.append('    <div class="pic">%s%s</div>' % (_img_tag_html(href, alt), cap))
    return "\n".join(parts)


def _drop_url_tags(s):
    """删掉仍然含网址的 HTML 残标签：插图换成本地文件后，外层 <a href> 已无意义。"""
    def rep(m):
        return "" if URL_RE.search(m.group(0)) else m.group(0)
    return HTML_TAG_RE.sub(rep, s)


def _para_with_images(line, images):
    """一行正文 → epub 里的 html，插图链接已换成 images/xxx。

    两种写法都认：`<img src="https://…/a.jpg" alt="…">` 整串标签换成本地插图
    （alt 原样保留，独占一段时还会当图注显示在图下方），以及粘在正文里或独占一行
    的裸链接。行内没有已下载的插图时返回 None，调用方按普通段落输出 ——
    这样不开「下载插图链接」时 epub 与旧版逐字节相同。
    """
    if not images:
        return None
    slots = []

    def put(url, alt=""):
        href = images.get(image_key(url))
        if not href:
            return None
        slots.append((href, alt))
        return "\x00%d\x00" % (len(slots) - 1)

    def rep_tag(m):
        tag = m.group(0)
        url = tag_attr(tag, "src")
        if not url:
            return tag
        got = put(url, tag_attr(tag, "alt"))
        return tag if got is None else got

    s = _IMG_TAG_RE.sub(rep_tag, line)
    # <a href="原链接"><img …></a> 这类包装：图已经换成本地文件，那个指着原网址的
    # 标签留着只会被转义成源码。必须在处理裸链接之前删，否则 href 会被再换成一张图。
    s = _drop_url_tags(s)
    out = []
    pos = 0
    for m in URL_BODY_RE.finditer(s):
        url = m.group(0).rstrip(_IMG_TRAIL)
        got = put(url)
        if got is None:
            continue
        out.append(s[pos:m.start()])
        out.append(got)
        pos = m.start() + len(url)
    if pos:
        out.append(s[pos:])
        s = "".join(out)
    if not slots:
        return None
    # 去掉插图后这行只剩「图片：」这类标签文字时，让插图独占一段
    plain = _PH_RE.sub("", HTML_TAG_RE.sub("", s))
    if _slim(plain) == 0:
        return _pic_block(slots)
    return "    <p>%s</p>" % _put_back(_esc(s), slots)


# EPUB 里写给读者的固定文案，跟界面语言走（见 write_epub 的 lang 参数）
_EPUB_LABEL = {
    "zh": {"empty": "（本章无正文）"},
    "en": {"empty": "(No text in this chapter)"},
}


def write_epub(path, title, author, chapters, cover=None, theme=DEFAULT_THEME,
               images=None, lang="zh"):
    """用标准库 zipfile 手写 EPUB 3（nav 导航文档 + NCX 双份，兼容旧阅读器）。

    目录按源文档的章节树逐级嵌套：nav.xhtml 写多层 <ol>，toc.ncx 写嵌套
    navPoint，阅读器侧边栏可一层层展开；层级取自 chapter_toc_nodes，与
    「导出章节树」用的是同一套判断。

    lang: 界面语言（"zh"/"en"），只影响书里写死的提示文案，比如空白章那句
          「本章无正文」在英文界面下写成英文

    cover: cover_for_book / make_cover / prepare_cover_image 的返回值，
           None 表示不带封面（与旧版输出一致）；epub 内部文件名按 MIME
           统一成 cover.jpg / cover.png，与传进来的 name 无关
    theme: assets/styles 下的 CSS 文件名（主题 id），只影响 style.css；
           文件不存在时退回默认主题 01-minimal.css
    images: download_images 的返回值 {链接键: 本地图片路径}；None / 空表示不带插图，
           给了就把正文里的插图链接换成 images/xxx 并把图片一起打进 epub
    """
    uid = "urn:uuid:" + str(uuid.uuid4())
    # EPUB3 的 metadata 必须带 dcterms:modified（格式固定为 UTC 的 ISO 8601）
    modified = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    title = title or "未命名"
    author = author or "佚名"
    L = _EPUB_LABEL.get(lang) or _EPUB_LABEL["zh"]
    # 先把图片读进内存：读失败的直接不算，正文里那条链接就保持原样
    img_files = []                 # [(epub 内文件名, mime, 字节)]
    img_map = {}                   # 链接键 -> epub 内 href
    for key, local in (images or {}).items():
        try:
            with open(local, "rb") as f:
                data = f.read()
        except (OSError, TypeError):
            continue
        name = os.path.basename(str(local))
        if not data or not name:
            continue
        img_files.append((name, image_mime(name), data))
        img_map[key] = IMG_HREF_DIR + name
    pages = []
    for i, (ctitle, body) in enumerate(chapters, 1):
        paras = []
        for p in body.splitlines():
            p = p.strip()
            if p:
                paras.append(_para_with_images(p, img_map)
                             or ("    <p>%s</p>" % _esc(p)))
        pages.append((i, ctitle, "\n".join(paras) or "    <p>%s</p>" % L["empty"]))

    manifest = []
    spine = []
    for i, _ctitle, _ in pages:
        manifest.append('    <item id="c%d" href="c%04d.xhtml" media-type="application/xhtml+xml"/>' % (i, i))
        spine.append('    <itemref idref="c%d"/>' % i)
    # 目录树：nav（EPUB3）与 NCX（EPUB2）都按它逐级嵌套
    toc_nodes = chapter_toc_nodes([ctitle for _i, ctitle, _ in pages])
    for k, (iname, imime, _data) in enumerate(img_files, 1):
        manifest.append('    <item id="im%d" href="%s%s" media-type="%s"/>'
                        % (k, IMG_HREF_DIR, iname, imime))

    has_cover = bool(cover and cover[0])
    cover_name = ""
    cover_meta = ""
    spine_cover = ""
    guide = ""
    if has_cover:
        cdata = cover[0]
        cmime = (cover[2] if len(cover) > 2 else "") or "image/jpeg"
        cover_name = "cover" + _COVER_EXT_BY_MIME.get(cmime, ".jpg")
        # EPUB2 认 <meta name="cover">；EPUB3 认 properties="cover-image"，
        # 两个都写，老阅读器和新阅读器都能取到缩略图。
        cover_meta = '    <meta name="cover" content="cover-img"/>\n'
        manifest.insert(0, '    <item id="cover-img" href="%s" media-type="%s" '
                           'properties="cover-image"/>' % (cover_name, cmime))
        manifest.insert(1, '    <item id="cover" href="cover.xhtml" '
                           'media-type="application/xhtml+xml"/>')
        spine_cover = '    <itemref idref="cover"/>\n'
        guide = ('  <guide>\n'
                 '    <reference type="cover" title="封面" href="cover.xhtml"/>\n'
                 '  </guide>\n')

    opf = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n'
        "    <dc:title>%s</dc:title>\n"
        "    <dc:creator opf:role=\"aut\">%s</dc:creator>\n"
        "    <dc:language>zh-CN</dc:language>\n"
        "    <dc:identifier id=\"BookId\">%s</dc:identifier>\n"
        '    <meta property="dcterms:modified">%s</meta>\n'
        "%s"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="css" href="style.css" media-type="text/css"/>\n'
        "%s\n"
        "  </manifest>\n"
        '  <spine toc="ncx">\n%s%s\n  </spine>\n'
        "%s"
        "</package>\n"
    ) % (_esc(title), _esc(author), uid, modified, cover_meta,
         "\n".join(manifest), spine_cover, "\n".join(spine), guide)

    ncx = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-01-01">\n'
        "  <head><meta name=\"dtb:uid\" content=\"%s\"/></head>\n"
        "  <docTitle><text>%s</text></docTitle>\n"
        "  <navMap>\n%s\n  </navMap>\n</ncx>\n"
    ) % (uid, _esc(title), "\n".join(_ncx_points(toc_nodes, 2, [0])))

    # EPUB3 导航文档：目录本身就是一棵 <ol> 嵌套树，阅读器侧边栏据此逐级展开
    nav = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">\n'
        "<head>\n  <meta charset=\"utf-8\"/>\n  <title>目录</title>\n</head>\n"
        "<body>\n"
        '  <nav epub:type="toc" id="toc">\n'
        "    <h1>目录</h1>\n"
        "%s\n"
        "  </nav>\n"
        "</body>\n</html>\n"
    ) % "\n".join(_nav_list(toc_nodes, 2))

    with zipfile.ZipFile(path, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
        css = theme_css(theme)
        if img_files:
            # 主题自己写了插图规则就一字不动，只给没写的补最小兜底：
            # 通用的图注/卡片样式会盖掉各主题调过的版面。
            if "img.pic" not in css:
                css += "\nimg.pic{max-width:100%;height:auto;}\n"
            if "div.pic" not in css:
                css += "div.pic{margin:1em 0;text-align:center;}\n"
            if "p.cap" not in css:
                css += ("p.cap{font-size:.85em;color:#666666;margin:.3em 0 0;"
                        "text-indent:0;}\n")
        z.writestr("OEBPS/style.css", css, zipfile.ZIP_DEFLATED)
        if has_cover:
            z.writestr("OEBPS/" + cover_name, cdata, zipfile.ZIP_DEFLATED)
            z.writestr("OEBPS/cover.xhtml",
                       _COVER_PAGE.replace("__COVER_SRC__", cover_name),
                       zipfile.ZIP_DEFLATED)
        for iname, _imime, idata in img_files:
            z.writestr("OEBPS/" + IMG_HREF_DIR + iname, idata, zipfile.ZIP_DEFLATED)
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
