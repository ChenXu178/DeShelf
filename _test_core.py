# -*- coding: utf-8 -*-
"""卷帙核心逻辑自测：造样本 → 编码识别 / 清洗 / 分章 / EPUB / 元信息。"""
import atexit
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jzcore

# 样本建在系统临时目录里，跑完自动删干净，不再往仓库留 _sample* 目录
ROOT = tempfile.mkdtemp(prefix="deshelf_core_")
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)
# 顺手清掉旧版测试留下的样本目录（以前是挪成 _sample_HHMMSS，越攒越多）
for _name in os.listdir(HERE):
    if _name.startswith("_sample"):
        shutil.rmtree(os.path.join(HERE, _name), ignore_errors=True)

BODY_GBK = """斗破苍穹
作者：天蚕土豆
==================
第1章 陨落的天才

　　萧炎缓缓睁开双眼，望着头顶那片熟悉的纹路，嘴角泛起一丝苦涩。

欢迎访问www.example.com，请记住本站地址，更多免费小说等你来看！
请收藏本站，本章未完，下一页继续。

第2章 斗之力，三段！

　　“萧炎，斗之力，三段！”测验魔石碑之旁，一道中年男子的声音响起。

手机阅读请访问 m.example.com，笔趣阁无弹窗。
上一页 | 返回目录 | 加入书签

第一百二十三章 山洞

　　这里是第一百二十三章的内容，用来测试中文数字章节。

序章 开始

　　序章内容。
"""

BODY_UTF8 = """《诡秘之主》
作者：爱潜水的乌贼
第1章 绯红

　　周明瑞睁开眼，发现自己在一张老旧的桌子上。
http://www.xxx.net 小说下载网，TXT下载请到本站。
第2章 占卜家

　　灰雾之上，古老的宫殿静静矗立。
"""

BODY_UTF16 = """凡人修仙传
第1章 山村少年

　　韩立站在村口，望着远山。
第2章 七玄门

　　青牛镇，七玄门。
"""


def w(name, text, enc):
    p = os.path.join(ROOT, name)
    with open(p, "wb") as f:
        f.write(text.encode(enc))
    return p


fails = []


def check(label, got, want):
    ok = got == want
    print(("  [OK]  " if ok else "  [FAIL]") + " %s -> %r" % (label, got) + ("" if ok else " (期望 %r)" % (want,)))
    if not ok:
        fails.append(label)


print("== 1. 编码识别 ==")
p1 = w("斗破苍穹-天蚕土豆.txt", BODY_GBK, "gbk")
p2 = w("诡秘之主.txt", BODY_UTF8, "utf-8-sig")
p3 = w("凡人修仙传.txt", BODY_UTF16, "utf-16")
check("GBK 文件", jzcore.detect_bytes(open(p1, "rb").read()), "gbk")
check("UTF-8 BOM 文件", jzcore.detect_bytes(open(p2, "rb").read()), "utf-8-sig")
check("UTF-16 文件", jzcore.detect_bytes(open(p3, "rb").read()), "utf-16-le")

print("== 2. 元信息提取 ==")
for p in (p1, p2, p3):
    info = jzcore.scan_file(p)
    print("  %-24s 书名=%-10r 作者=%-8r 编码=%-10s 字数=%d" % (
        info["name"], info["title"], info["author"], info["enc"], info["chars"]))
check("书名(文件名带作者)", jzcore.scan_file(p1)["title"], "斗破苍穹")
check("作者(文件名带作者)", jzcore.scan_file(p1)["author"], "天蚕土豆")
check("书名(书名号)", jzcore.scan_file(p2)["title"], "诡秘之主")
check("作者(正文提取)", jzcore.scan_file(p2)["author"], "爱潜水的乌贼")

print("== 3. 清洗 ==")
raw = jzcore.decode(open(p1, "rb").read(), "gbk")
cleaned, removed = jzcore.clean_text(raw, jzcore.DEFAULT_ON)
print("  删除 %d 行，%d 字 -> %d 字" % (removed, len(raw), len(cleaned)))
check("网址行已清除", "www.example.com" in cleaned, False)
check("宣传行已清除", "请收藏本站" in cleaned, False)
check("导航行已清除", "返回目录" in cleaned, False)
check("正文保留", "萧炎缓缓睁开双眼" in cleaned, True)
check("连续空行已压缩", "\n\n\n" in cleaned, False)

print("== 4. 分章 ==")
chs = jzcore.split_chapters(cleaned)
print("  切出 %d 章：" % len(chs))
for t, b in chs:
    print("    - %s (%d 字)" % (t, len(b)))
check("章节数(1,2,123,序章+开篇)", len(chs), 5)
check("中文数字章节命中", any("一百二十三" in t for t, _ in chs), True)
check("序章命中", any(t.startswith("序章") for t, _ in chs), True)

print("== 4b. 多级章节树（部/卷/章各占一条）==")
# 连续几行各是一个标题：各占一条，不能合并成「第一部 第一卷 第1章」
multi = jzcore.split_chapters(
    "第一部 风起云涌\n\n第一卷 新手村\n\n第1章 初出茅庐\n\n正文甲。\n\n"
    "第2章 名声鹊起\n\n正文乙。\n")
check("连续多级标题各占一条", [t for t, _b in multi],
      ["第一部 风起云涌", "第一卷 新手村", "第1章 初出茅庐", "第2章 名声鹊起"])
check("上级章节没有正文", [multi[0][1], multi[1][1]], ["", ""])
check("正文归最里面那一级", ["正文甲" in multi[2][1], "正文乙" in multi[3][1]],
      [True, True])
# 原文本身写在一行里：按序号位置拆开
inline = jzcore.split_chapters(
    "第一部 风起云涌 第一卷 新手村 第1章 初出茅庐\n正文甲。\n第2章 名声鹊起\n正文乙。")
check("一行写多级也拆成独立条目", [t for t, _b in inline],
      ["第一部 风起云涌", "第一卷 新手村", "第1章 初出茅庐", "第2章 名声鹊起"])
check("一行多级时正文归最深一级", "正文甲" in inline[2][1], True)
check("split_title_levels 切三段",
      jzcore.split_title_levels("第一部 风起云涌 第一卷 新手村 第1章 初出茅庐"),
      ["第一部 风起云涌", "第一卷 新手村", "第1章 初出茅庐"])
check("单级标题不拆", jzcore.split_title_levels("第3章 他还会有第二部电影吗？"),
      ["第3章 他还会有第二部电影吗？"])
# 文末最后一个标题没有正文：标题仍留在目录里（旧版会塞进上一章正文）
tail = jzcore.split_chapters("第1章 起\n正文。\n第2章 终")
check("文末空标题单独成条", [(t, b) for t, b in tail],
      [("第1章 起", "正文。"), ("第2章 终", "")])
check("标题里的「第二部」不拆",
      jzcore.split_chapters("第3章 他还会有第二部电影吗？\n正文。")[0][0],
      "第3章 他还会有第二部电影吗？")

print("== 5. 自定义章节正则 ==")
chs2 = jzcore.split_chapters(cleaned, r"^#{1,3}\s*\S+")
print("  自定义正则切出 %d 章（预期 1，样本里无 # 标题）" % len(chs2))
check("自定义正则兜底为 1 章", len(chs2), 1)

print("== 6. EPUB 生成 ==")
ep = os.path.join(ROOT, "斗破苍穹.epub")
jzcore.write_epub(ep, "斗破苍穹", "天蚕土豆", chs)
check("文件已生成", os.path.exists(ep), True)
with zipfile.ZipFile(ep) as z:
    names = z.namelist()
    mi = z.getinfo("mimetype")
    check("mimetype 是第一个条目", names[0], "mimetype")
    check("mimetype 未压缩(STORED)", mi.compress_type, zipfile.ZIP_STORED)
    check("mimetype 内容", z.read("mimetype").decode(), "application/epub+zip")
    opf = z.read("OEBPS/content.opf").decode("utf-8")
    ncx = z.read("OEBPS/toc.ncx").decode("utf-8")
    nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
    # 封面页与 nav 导航文档不是章节页，按章节页单独计数
    htmls = sorted(n for n in names
                   if n.endswith(".xhtml") and not n.endswith(("cover.xhtml", "nav.xhtml")))
    first_body = z.read(htmls[1]).decode("utf-8")
check("章节 xhtml 数 = 章节数", len(htmls), len(chs))
check("OPF 含书名", "<dc:title>斗破苍穹</dc:title>" in opf, True)
check("OPF 含作者", "天蚕土豆" in opf, True)
check("EPUB3 包声明", 'version="3.0"' in opf, True)
check("OPF 声明 nav 导航文档", 'properties="nav"' in opf, True)
check("NCX 含目录项", ncx.count("<navPoint"), len(chs))
check("NCX 是合法 XML", ncx.startswith("<?xml") and "</ncx>" in ncx, True)
check("nav 是合法 XML 页面", nav.startswith("<?xml") and "</html>" in nav, True)
check("nav 写明 toc", 'epub:type="toc"' in nav, True)
check("正文写入 xhtml", "萧炎" in first_body, True)
check("xhtml 已转义/结构完整", first_body.startswith("<?xml") and "</html>" in first_body, True)

# 空白章（部/卷这类只有标题的章节）的占位文案跟着界面语言走
empty_chs = [("第1章 空", ""), ("第2章 有", "正文。")]
ep_zh = os.path.join(ROOT, "空白章-zh.epub")
ep_en = os.path.join(ROOT, "空白章-en.epub")
jzcore.write_epub(ep_zh, "空白章", "甲", empty_chs)
jzcore.write_epub(ep_en, "空白章", "甲", empty_chs, lang="en")
with zipfile.ZipFile(ep_zh) as z:
    page_zh = z.read("OEBPS/c0001.xhtml").decode("utf-8")
with zipfile.ZipFile(ep_en) as z:
    page_en = z.read("OEBPS/c0001.xhtml").decode("utf-8")
check("中文界面空白章文案", "（本章无正文）" in page_zh, True)
check("英文界面空白章文案", "(No text in this chapter)" in page_en, True)
check("英文界面不留中文占位", "本章无正文" in page_en, False)

print("== 7. 合并/拆分 TXT 导出 ==")
m1 = os.path.join(ROOT, "合并本.txt")
jzcore.save_txt(chs, m1, merge=True)
check("合并本已生成", os.path.exists(m1), True)
d1 = jzcore.save_txt(chs, os.path.join(ROOT, "分章本.txt"), merge=False)
check("分章目录已生成", os.path.isdir(d1), True)
files = sorted(os.listdir(d1))
print("  分章文件：", files)
check("分章文件数", len(files), len(chs))

print("== 8. 去重指纹 ==")
p_dup = w("斗破苍穹(副本).txt", BODY_GBK, "gbk")
check("同内容 md5 一致", jzcore.scan_file(p1)["md5"], jzcore.scan_file(p_dup)["md5"])
check("不同内容 md5 不同",
      jzcore.scan_file(p1)["md5"] != jzcore.scan_file(p2)["md5"], True)

print("== 9. 导出文件名格式 ==")
# 预设与自定义共用一套 book/author 占位符解析
check("作者名 - 书名", jzcore.apply_name_format("author - book", "斗破苍穹", "天蚕土豆"),
      "天蚕土豆 - 斗破苍穹")
check("[作者名] 书名", jzcore.apply_name_format("[author] book", "斗破苍穹", "天蚕土豆"),
      "[天蚕土豆] 斗破苍穹")
check("《书名》作者：作者名",
      jzcore.apply_name_format("《book》作者：author", "斗破苍穹", "天蚕土豆"),
      "《斗破苍穹》作者：天蚕土豆")
check("作者为空时不留空括号", jzcore.apply_name_format("[author] book", "斗破苍穹", ""),
      "斗破苍穹")
check("连续空格原样保留",
      jzcore.apply_name_format("[author]  book", "斗破苍穹", "天蚕土豆"),
      "[天蚕土豆]  斗破苍穹")
check("书名后连续空格也保留",
      jzcore.apply_name_format("《book》   author", "斗破苍穹", "天蚕土豆"),
      "《斗破苍穹》   天蚕土豆")
check("首尾空格不进入文件名",
      jzcore.apply_name_format("  book  ", "斗破苍穹", "天蚕土豆"), "斗破苍穹")
check("作者为空时连分隔符一起摘掉",
      jzcore.apply_name_format("[author]  book", "斗破苍穹", ""), "斗破苍穹")
check("作者为空时摘掉「作者：」标签",
      jzcore.apply_name_format("《book》作者：author", "斗破苍穹", ""), "《斗破苍穹》")
check("作者为空时摘掉尾部连字符",
      jzcore.apply_name_format("book - author", "斗破苍穹", ""), "斗破苍穹")
check("必须含 book 占位符", jzcore.has_book_token("author only"), False)
check("book 紧贴中文也能识别", jzcore.has_book_token("书名book"), True)
check("book 在英文单词里不算", jzcore.has_book_token("notebook"), False)
check("斜杠属非法文件名字符", jzcore.name_fmt_bad_chars("《book》 /author"), ["/"])
check("多个非法字符按序去重", jzcore.name_fmt_bad_chars("book:a*b?a"), [":", "*", "?"])
check("全角冒号竖线号合法", jzcore.name_fmt_bad_chars("《book》：author｜1"), [])
check("正常模板没有非法字符", jzcore.name_fmt_bad_chars("《book》·author"), [])

print("== 10. 章节序号解析 ==")
check("中文数字 两百五十一", jzcore.cn_to_int("两百五十一"), 251)
check("中文数字 一百零三", jzcore.cn_to_int("一百零三"), 103)
check("中文数字 十一", jzcore.cn_to_int("十一"), 11)
check("全角数字 ３１", jzcore.cn_to_int("３１"), 31)
check("认不出的数字", jzcore.cn_to_int("第"), None)
check("一行三级", jzcore.parse_chap_numbers("第一部 第二卷 第三十一章"),
      [(1, "部"), (2, "卷"), (31, "章")])
check("标题夹带上级不算层级", jzcore.parse_chap_numbers("第三十章 他还会有第二部电影吗？"),
      [(30, "章")])
check("正文句子不当上级(集)", jzcore.parse_chap_numbers("第二集的平均收视率，竟然涨到了1.81%！"), [])
check("正文句子不当上级(部)", jzcore.parse_chap_numbers("第一部开拓市场，第二部巩固市场，第三部……"), [])
check("西式卷行", jzcore.parse_chap_numbers("第二部：传奇之路 第三十章 他还会有"),
      [(2, "部"), (30, "章")])
check("番外自带号", jzcore.parse_chap_numbers("番外一 小剧场"), [(1, "番外")])
check("后记自带号", jzcore.parse_chap_numbers("后记一（十年后）"), [(1, "后记")])
check("后记无号", jzcore.parse_chap_numbers("后记终（十年后）"), [])
check("章标题不留空格", jzcore.parse_chap_numbers("第一章陨落的天才"), [(1, "章")])
check("纯数字标题", jzcore.parse_chap_numbers("12、标题"), [(12, "章")])
check("括号包裹", jzcore.parse_chap_numbers("【第1057章】大结局"), [(1057, "章")])

print("== 11. 章节树校验 ==")


def cks(titles, lang="zh"):
    return jzcore.check_chapters(titles, lang)


r = cks(["第%d章 t" % i for i in range(1, 31)])
check("单级连号 异常数", r["bad"], 0)
check("单级连号 层级", r["levels"], 1)

r = cks(["第%d章 t" % i for i in range(1, 31) if i != 25])
check("缺章 异常数", r["bad"], 1)
check("缺章 文案", r["marks"].get(25), "第25章缺失/顺序错误")

r = cks(["第1章 a", "第2章 b", "第2章 c", "第3章 d"])
check("连续重号 文案", r["marks"].get(3), "章节重复（第2章）")
check("连续重号 后续章不受影响", 4 in r["marks"], False)

r = cks(["第1章 a", "第2章 b", "第3章 c", "第2章 d", "第4章 e"])
check("隔远重号 文案", r["marks"].get(4), "章节重复（第2章）")
check("隔远重号 后续章正常", 5 in r["marks"], False)

# 第七八零八章 → 8：号写错，只报这一章，下一章按上一个好号算缺 708
r = cks(["第705章 a", "第706章 b", "第707章 c", "第七八零八章 d", "第709章 e"])
check("章号写错 文案", r["marks"].get(4), "章节号错误（第8章）")
check("章号写错不连累下一章", r["marks"].get(5), "第708章缺失/顺序错误")

r = cks(["第1章 a", "第2章 b", "第30章 c", "第1章 d"])
check("无分级回 1 只报顺序错误", r["marks"].get(4), "第1章顺序错误")

r = cks(["开篇", "第1章 a", "第2章 b"])
check("开篇不校验", r["bad"], 0)

r = cks(["第一卷", "第1章 a", "第2章 b", "第二卷", "第1章 c"])
check("两级 层级", r["levels"], 2)
check("两级 无异常", r["bad"], 0)
check("两级 卷行标级别", r["lv"].get(1), 1)
check("两级 章行不标级别", 2 in r["lv"], False)

r = cks(["第一部", "第一卷", "第1章 a", "第2章 b", "第二卷", "第1章 c"])
check("三级各成行 层级", r["levels"], 3)
check("三级各成行 部级", r["lv"].get(1), 1)
check("三级各成行 卷级", r["lv"].get(2), 2)

r = cks(["第一部 第二卷 第三十一章", "第一部 第二卷 第三十二章"])
check("一行三级 层级", r["levels"], 3)
check("一行三级 无异常", r["bad"], 0)

r = cks(["第%d章 t" % i for i in range(1, 57)] + ["第二卷"] + ["第1章 t", "第2章 t"])
check("跨卷重排 无异常", r["bad"], 0)
check("跨卷重排 层级", r["levels"], 2)

r = cks(["第1章 a", "第2章 b", "第二卷", "第三卷", "第1章 c"])
check("上级下面没子章节 → fail", r["marks"].get(3), "第2章序号提取失败")

r = cks(["第764章 t", "第765章 t", "无序号杂标题", "第766章 t"])
check("fail 提示按推算章号", r["marks"].get(3), "第766章序号提取失败")

r = cks(["第734章 t", "第735章 t", "特别篇 结局提前泄露", "第736章 t"])
check("番外组无号不报 fail", 3 in r["marks"], False)
check("番外组不影响正文连号", r["bad"], 0)

r = cks(["第%d章 t" % i for i in range(1, 11)] + ["后记一（十年后）", "后记终（十年后）"])
check("后记按番外处理 无异常", r["bad"], 0)
check("后记不占正文序号", r["total"], 12)

# 倒金字塔兜底：105 章里夹一个「第50章 第1节」，节被当子章节 → 该章 fail，树退回 1 级
r = cks(["第%d章 t" % i for i in range(1, 101)][:49] + ["第50章 第1节 小节"]
        + ["第%d章 t" % i for i in range(51, 101)])
check("倒金字塔兜底 层级", r["levels"], 1)
check("倒金字塔兜底 异常数", r["bad"], 1)

print("== 12. 章节树导出文本 ==")
titles = ["开篇", "第一卷 作家之路 第1章 骚年", "第2章 这个世界", "第二卷 绽放 第3章 写诗"]
rep = jzcore.chapter_tree_report(titles, None, ["书籍：样例"])
check("导出含标题行", rep.splitlines()[0], "章节树导出")
check("导出含书籍信息", "书籍：样例" in rep, True)
check("导出含各级统计", "第1级：" in rep and "第2级：" in rep, True)
check("无序号章记 0", "[0] 开篇" in rep, True)
check("卷行顶格", "\n[1] 第一卷 作家之路 第1章 骚年" in rep, True)
check("子章节缩进", "\n    [2] 第2章 这个世界" in rep, True)
check("换卷空一行", "\n\n[3] 第二卷 绽放 第3章 写诗" in rep, True)

rep_en = jzcore.chapter_tree_report(titles, None, ["Book: demo"], lang="en")
check("英文导出标题", rep_en.splitlines()[0], "Chapter tree export")
check("英文各级统计", "Chapters per level:" in rep_en and "Level 1:" in rep_en, True)
check("英文无序号", "[0] 开篇  ← no number | OK" in rep_en, True)

print("== 12b. EPUB 目录树（nav / NCX 嵌套）==")
multi = jzcore.split_chapters(
    "第一部 甲 第一卷 乙 第1章 丙\n正文。\n第2章 丁\n正文。\n"
    "第二卷 戊\n\n第1章 己\n正文。\n")
nodes = jzcore.chapter_toc_nodes([t for t, _b in multi])
check("顶层=部", [n["title"] for n in nodes], ["第一部 甲"])
check("部下面是两卷", [n["title"] for n in nodes[0]["kids"]],
      ["第一卷 乙", "第二卷 戊"])
check("卷下面是章", [n["title"] for n in nodes[0]["kids"][0]["kids"]],
      ["第1章 丙", "第2章 丁"])
check("第二卷也挂着章", [n["title"] for n in nodes[0]["kids"][1]["kids"]],
      ["第1章 己"])
check("节点指回章节页", nodes[0]["kids"][0]["kids"][1]["page"], 4)
check("扁平书只有一层", len(jzcore.chapter_toc_nodes(["第1章 a", "第2章 b"])[0]["kids"]), 0)

print()
print("失败项：%d" % len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
