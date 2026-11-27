/* 卷帙 DeShelf Web — Core 纯逻辑冒烟测试（node）
 * 从 web/DeShelf.html 抽取 CORE_BEGIN..CORE_END 段独立执行，
 * 校验编码识别/清洗/分章/EPUB/ZIP 与桌面版 Python 逻辑一致。
 * 用法: node tools/test_web_core.mjs   （须在 Juanzhi/ 下运行）
 */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { TextDecoder, TextEncoder } from "node:util";
import assert from "node:assert";

// ---------- polyfill 全局（node 需要时） ----------
if (!globalThis.TextDecoder) globalThis.TextDecoder = TextDecoder;
if (!globalThis.TextEncoder) globalThis.TextEncoder = TextEncoder;
if (typeof globalThis.Blob === "undefined") {
  const { Blob } = await import("node:buffer"); globalThis.Blob = Blob;
}
if (typeof globalThis.Response === "undefined") {
  const { Response } = await import("node:undici"); globalThis.Response = Response;
}
if (typeof globalThis.CompressionStream === "undefined") {
  const { CompressionStream } = await import("node:stream/web");
  globalThis.CompressionStream = CompressionStream;
}

const html = fs.readFileSync(path.join(import.meta.dirname, "..", "web", "DeShelf.html"), "utf8");
const m = html.match(/\/\*CORE_BEGIN\*\/([\s\S]*?)\/\*CORE_END\*\//);
assert(m, "未找到 CORE_BEGIN..CORE_END 段");
const factory = new Function(m[1] + "\n;return Core;");
const Core = factory();
let pass = 0, fail = 0;
function ok(name, cond, detail) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.error("  ✗ FAIL: " + name + (detail!==undefined ? "  | got: " + JSON.stringify(detail) : "")); }
}
function hex(bytes) { return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join(""); }
function gbkBytes(str) { // 常用字符查表编码（仅测试用）
  const table = {
    "测":"b2e2","试":"cad4","中":"d6d0","文":"cec4","章":"d5c2","节":"bdd9",
    "第":"b5da","章2":"","正":"d5fd","文2":"","的":"b5c4","一":"d2bb","。":"a1a3",
    "？":"a1bf","！":"a1be","：":"a3ba","，":"a3ac","　":"a1a1"
  };
  const out = [];
  for (const ch of str) {
    if (ch.charCodeAt(0) < 128) { out.push(ch.charCodeAt(0)); continue; }
    const h = table[ch]; assert(h && h.length === 4, "测试表缺字符: " + ch);
    out.push(parseInt(h.slice(0, 2), 16), parseInt(h.slice(2), 16));
  }
  return new Uint8Array(out);
}

console.log("== 编码识别 ==");
{
  const enc = new TextEncoder();
  ok("utf-8", Core.detectEnc(enc.encode("中文abc")) === "utf-8");
  ok("utf-8 BOM", Core.detectEnc(new Uint8Array([0xef,0xbb,0xbf,0x61])) === "utf-8-sig");
  ok("utf-16le BOM", Core.detectEnc(new Uint8Array([0xff,0xfe,0x61,0x00])) === "utf-16-le");
  ok("含 NUL → utf-16-le", Core.detectEnc(new Uint8Array([0x61,0x00,0x62])) === "utf-16-le");
  ok("gbk 回落", Core.detectEnc(gbkBytes("测试")) === "gbk");
  ok("gbk 解码", Core.decodeBytes(gbkBytes("测试中文"), "gbk") === "测试中文");
  const u16 = new Uint16Array([0x4e2d, 0x6587]); // 中文
  ok("utf-16le 解码", Core.decodeBytes(new Uint8Array(u16.buffer), "utf-16-le") === "中文");
  ok("utf-8-sig 解码去 BOM", Core.decodeBytes(new Uint8Array([0xef,0xbb,0xbf,0x61]), "utf-8-sig") === "a");
}

console.log("== 字符统计 ==");
ok("countChars", Core.countChars("a\nb\tc 　d\u00a0e") === 5);

console.log("== 清洗规则 ==");
{
  const sample = [
    "正文第一行内容。",
    "请收藏本站 https://example.com/book",
    "上一页 下一页",
    "第1章 开头",
    "abc，def！123",
    "",
    "",
    "  尾部有空格  ",
    ""
  ].join("\n");
  const r = Core.cleanText(sample, Core.DEFAULT_ON, true);
  const lines = r.text.split("\n");
  ok("删除 3 行", r.removed === 3, "got " + r.removed);
  ok("网址/宣传行已删", !r.text.includes("请收藏本站"));
  ok("导航残留已删", !r.text.includes("上一页"));
  ok("连续空行压缩为单行空", r.text.split("\n\n").length >= 1 && r.text.includes("第1章 开头\nabc"));
  ok("半角转换（只转数字字母，中文标点不动）", lines.includes("abc，def！123"));
  ok("行尾 trim", lines.includes("尾部有空格"));
  ok("首尾空行裁掉", r.text.startsWith("正文") && r.text.trimEnd().endsWith("尾部有空格"));
  ok("del 集合有记录", r.del.size >= 3);
  const r2 = Core.cleanText(sample, ["blank"], false);
  ok("blank 全删空行", !r2.text.includes("\n\n") && !r2.text.trimEnd().split("\n").some(l => l.trim() === ""), r2.text);
  const r3 = Core.cleanText("甲\n乙\n", ["indent"], false);
  ok("缩进两全角", r3.text.startsWith("　　甲"));
  const r4 = Core.cleanText("A：b（c）d，e。f「g」１２３ＡＢＣ\n", ["half"], false);
  ok("全角转半角仅动数字字母，中文标点保留", r4.text.split("\n")[0] === "A：b（c）d，e。f「g」123ABC", r4.text.split("\n")[0]);
}

console.log("== 行尾粘网址（盗版站常见形态，不能整段删掉） ==");
{
  const para = "她听我分析的头头是道，目光里写满了敬佩，等我说完后，歪着头看着桌上那把枪喃喃自语说：“这把枪怎么很面熟？”她忽然意识到了什么，瞪着我问：“你什么时候偷走的？”WwW.zhudao.com";
  const sample = [
    para,
    "zhudao.com 【猪猪岛】小说章节更新最快",
    "一秒记住【猪猪岛】手机版阅读网址：m.zhudao.com",
    "“你刚才倒下的时候。”",
    "把客人请到屋里坐下，倒了杯热茶。",
    "你上百度搜索一下就知道我说的是真的。",
    "他去过很多地方，比如那个叫 www.example.com 的站子，后来也走了很久很久才回来，路上的风景很好，天上的云很低，他一直记着那句话。",
  ].join("\n");
  const r = Core.cleanText(sample, ["url", "site", "trim"], true);
  const lines = r.text.split("\n");
  ok("正文段落保住（只裁网址）", lines[0] === para.replace("WwW.zhudao.com", ""), lines[0]);
  ok("网址打头的广告行整行删除", !r.text.includes("【猪猪岛】小说章节更新最快"));
  ok("推广语在前的短行整行删除", !r.text.includes("手机版阅读网址"));
  ok("cut 只记录了被裁的那一段", r.cut && r.cut.size === 1, r.cut && r.cut.size);
  ok("cut 位置落在网址开头", r.cut.get(para) === para.indexOf("WwW."), r.cut.get(para));
  ok("trimmed 计数为 1", r.trimmed === 1, r.trimmed);
  ok("“请到”不再误判整行删除", r.text.includes("把客人请到屋里"));
  ok("“百度搜索”不再误判整行删除", r.text.includes("你上百度搜索一下"));
  ok("网址夹在长句中间不动", r.text.includes("比如那个叫 www.example.com 的站子") && !r.cut.has(lines.find(l => l.includes("www.example.com"))));
  ok("正文一个字都没少", r.text.includes(para.slice(0, 40)));
}

console.log("== 分章 ==");
{
  const text = [
    "序章 一切的开始",
    "世界伊始，万物静默。",
    "第1章 相遇",
    "正文甲，两人相识。",
    "第 12 章 别离",
    "正文乙。",
    "尾声 再见",
    "正文丙。"
  ].join("\n");
  const chs = Core.splitChapters(text);
  ok("共 4 章", chs.length === 4, "got " + chs.length + " → " + JSON.stringify(chs.map(c=>c.t)));
  ok("首章=序章", chs[0].t === "序章 一切的开始");
  ok("次章=第1章", chs[1].t === "第1章 相遇");
  ok("第 12 章 匹配带空格", chs[2].t === "第 12 章 别离");
  ok("末章=尾声", chs[3].t === "尾声 再见");
  ok("章正文字数", Core.countChars(chs[1].b) === 9);
  ok("无标题时回落全文", Core.splitChapters("没有任何标题的一本书内容啊\n继续", "").length === 1);
  const c2 = Core.splitChapters(text, "^第\\d+章.*$");
  ok("自定义正则(仅第N章) → 2 章", c2.length === 2, "got " + c2.length);
  let threw = false;
  try { Core.splitChapters(text, "(["); } catch (e) { threw = true; }
  ok("非法正则抛错", threw);
}

console.log("== 分章：多级章节树（与桌面版一致） ==");
{
  /* 连续几行各是一个标题：各占一条，不能合并成「第一部 第一卷 第1章」 */
  const multi = Core.splitChapters([
    "第一部 风起云涌",
    "",
    "第一卷 新手村",
    "",
    "第1章 初出茅庐",
    "",
    "正文甲。",
    "",
    "第2章 名声鹊起",
    "",
    "正文乙。"
  ].join("\n"));
  ok("连续多级标题各占一条，不压成一行",
    multi.map(c => c.t).join("|") === "第一部 风起云涌|第一卷 新手村|第1章 初出茅庐|第2章 名声鹊起",
    multi.map(c => c.t).join("|"));
  ok("上级章节（部/卷）没有正文", multi[0].b === "" && multi[1].b === "",
    JSON.stringify(multi.map(c => c.b)));
  ok("正文归最里面那一级",
    multi[2].b.includes("正文甲") && multi[3].b.includes("正文乙"),
    JSON.stringify(multi.map(c => c.b)));

  /* 原文本身写在一行里：同样按序号位置拆成多条 */
  const inline = Core.splitChapters(
    "第一部 风起云涌 第一卷 新手村 第1章 初出茅庐\n正文甲。\n第2章 名声鹊起\n正文乙。");
  ok("一行写多级也拆成独立条目",
    inline.map(c => c.t).join("|") === "第一部 风起云涌|第一卷 新手村|第1章 初出茅庐|第2章 名声鹊起",
    inline.map(c => c.t).join("|"));
  ok("一行多级时成员层级正确", inline[2].b.includes("正文甲") && inline[0].b === "");

  /* 文末最后一个标题没有正文：标题仍要留在目录里（旧版会塞进上一章正文） */
  const tail = Core.splitChapters("第1章 起\n正文。\n第2章 终");
  ok("文末空标题单独成条",
    tail.length === 2 && tail[1].t === "第2章 终" && tail[1].b === "",
    JSON.stringify(tail));

  /* 标题里夹带的「第二部」不是上级章节，不能拆 */
  const film = Core.splitChapters("第3章 他还会有第二部电影吗？\n正文。");
  ok("标题里的「第二部」不拆", film.length === 1 && film[0].t === "第3章 他还会有第二部电影吗？",
    JSON.stringify(film.map(c => c.t)));

  /* 拆分工具本身：抽出的每段只含自己这一级 */
  ok("splitTitleLevels 三级",
    Core.splitTitleLevels("第一部 风起云涌 第一卷 新手村 第1章 初出茅庐").join("|")
      === "第一部 风起云涌|第一卷 新手村|第1章 初出茅庐",
    Core.splitTitleLevels("第一部 风起云涌 第一卷 新手村 第1章 初出茅庐").join("|"));
  ok("splitTitleLevels 单级原样",
    Core.splitTitleLevels("第3章 他还会有第二部电影吗？").join("|")
      === "第3章 他还会有第二部电影吗？",
    Core.splitTitleLevels("第3章 他还会有第二部电影吗？").join("|"));

  /* 拆出来的空章节不影响校验：部/卷/章三层，无异常 */
  const ck = Core.checkChapters(multi.map(c => c.t));
  ok("多级章节树识别为 3 级", ck.levels === 3, ck.levels);
  ok("多级章节树无校验异常", ck.bad === 0, JSON.stringify(ck.marks));
  ok("部/卷标出层级", ck.lv[1] === 1 && ck.lv[2] === 2, JSON.stringify(ck.lv));
}

console.log("== 指纹 ==");
ok("sha256('abc')", Core.sha256hex(new TextEncoder().encode("abc")) ===
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
ok("crc32('123456789')", Core.crc32(new TextEncoder().encode("123456789")) === 0xCBF43926);

console.log("== EPUB / ZIP ==");
// 简易 zip 读取器
function zipEntries(zip) {
  const dv = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
  let eocd = -1;
  for (let i = zip.length - 22; i >= 0 && i > zip.length - 65557; i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  assert(eocd >= 0, "EOCD 未找到");
  const count = dv.getUint16(eocd + 10, true), cdOff = dv.getUint32(eocd + 16, true);
  const out = [];
  let p = cdOff;
  for (let i = 0; i < count; i++) {
    assert(dv.getUint32(p, true) === 0x02014b50, "central 签名错误");
    const method = dv.getUint16(p + 10, true), crc = dv.getUint32(p + 16, true);
    const csize = dv.getUint32(p + 20, true), usize = dv.getUint32(p + 24, true);
    const nlen = dv.getUint16(p + 28, true), elen = dv.getUint16(p + 30, true),
          clen = dv.getUint16(p + 32, true), lho = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(zip.subarray(p + 46, p + 46 + nlen));
    const lv = new DataView(zip.buffer, zip.byteOffset + lho, 30);
    const dataStart = lho + 30 + lv.getUint16(26, true) + lv.getUint16(28, true);
    let data = zip.subarray(dataStart, dataStart + csize);
    if (method === 8) data = zlib.inflateRawSync(data);
    out.push({ name, method, crc, usize, data });
    p += 46 + nlen + elen + clen;
  }
  return out;
}
{
  const chs = [{t:"第一章 开篇",b:"正文甲。\n正文乙。"},{t:"第二章 结尾",b:"正文丙。"}];
  const epub = await Core.buildEpub({ title: "《测试书》", author: "某人", chapters: chs });
  const ents = zipEntries(epub);
  const names = ents.map(e => e.name);
  ok("epub 内含 mimetype", names[0] === "mimetype" && ents[0].method === 0);
  ok("mimetype 内容精确", new TextDecoder().decode(ents[0].data) === "application/epub+zip");
  for (const need of ["META-INF/container.xml","OEBPS/content.opf","OEBPS/toc.ncx",
      "OEBPS/nav.xhtml","OEBPS/style.css","OEBPS/c0001.xhtml","OEBPS/c0002.xhtml"])
    ok("含 " + need, names.includes(need));
  const opf = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/content.opf").data);
  ok("opf 含书名/作者", opf.includes("测试书") && opf.includes("某人"));
  ok("opf 是 EPUB3 并声明 nav 与 dcterms:modified",
    opf.includes('version="3.0"') && opf.includes('properties="nav"')
      && opf.includes("dcterms:modified"), opf.slice(0, 300));
  const c1 = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/c0001.xhtml").data);
  ok("xhtml 含标题与段落缩进", c1.includes("第一章 开篇") && c1.includes("<p>") && c1.includes("正文乙"));
  const enEnts = zipEntries(await Core.buildEpub({title:"B", author:"A", lang:"en",
    chapters:[{t:"第1章 空",b:""}]}));
  const enPage = new TextDecoder().decode(enEnts.find(e => e.name === "OEBPS/c0001.xhtml").data);
  ok("英文界面空白章文案", enPage.includes("(No text in this chapter)")
    && !enPage.includes("本章无正文"), enPage);
  const ncx = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/toc.ncx").data);
  ok("ncx 目录两章", ncx.includes("第二章 结尾"));
  ok("mimetype CRC 校验", ents[0].crc === Core.crc32(ents[0].data));
  const merged = Core.buildMergedTxt(chs);
  ok("合并 TXT 结构", merged.startsWith("第一章 开篇\n\n正文甲。") && merged.includes("第二章 结尾"));
  const szip = await Core.buildSplitZip("样例", chs);
  const sent = zipEntries(szip);
  ok("分章 zip 两文件", sent.length === 2);
  ok("分章 zip 中文文件名", sent.every(e => e.name.includes("样例/") && e.name.endsWith(".txt")));
}

console.log("== EPUB 多级目录（nav / NCX 嵌套） ==");
{
  const chs = [
    {t:"第一部 风起云涌",b:""},
    {t:"第一卷 新手村",b:""},
    {t:"第1章 初出茅庐",b:"正文甲。"},
    {t:"第2章 名声鹊起",b:"正文乙。"},
    {t:"第二卷 剑指中原",b:""},
    {t:"第1章 再起",b:"正文丙。"},
  ];
  /* 目录树本身：部 → 卷 → 章，节点指回章节页 */
  const nodes = Core.chapterTocNodes(chs.map(c => c.t));
  ok("chapterTocNodes 顶层只有一部", nodes.length === 1 && nodes[0].kids.length === 2,
    JSON.stringify(nodes.map(n => n.title)));
  ok("部下面挂两卷", nodes[0].kids.map(n => n.title).join("|") === "第一卷 新手村|第二卷 剑指中原",
    JSON.stringify(nodes[0].kids.map(n => n.title)));
  ok("卷下面挂章", nodes[0].kids[0].kids.map(n => n.title).join("|")
    === "第1章 初出茅庐|第2章 名声鹊起", JSON.stringify(nodes[0].kids[0].kids));
  ok("节点指回章节页", nodes[0].kids[0].kids[1].page === 4, nodes[0].kids[0].kids[1].page);
  const flat = Core.chapterTocNodes(["第1章 a", "第2章 b"]);
  ok("扁平书只有一层", flat.length === 2 && flat.every(n => n.kids.length === 0));

  /* 导出的 EPUB：nav 是多层 <ol>，NCX 是嵌套 navPoint */
  const ents = zipEntries(await Core.buildEpub({title:"多层书", author:"甲", chapters:chs}));
  const nav = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/nav.xhtml").data);
  const ncx = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/toc.ncx").data);
  ok("nav 写明 epub:type=toc", nav.includes('epub:type="toc"'));
  ok("nav 目录树 4 层 ol（根 + 部 + 两个卷）",
    (nav.match(/<ol>/g) || []).length === 4, (nav.match(/<ol>/g) || []).length);
  ok("nav 部条目下面挂着卷",
    /<li><a href="c0001\.xhtml">第一部 风起云涌<\/a>\s*<ol>/.test(nav), nav);
  ok("nav 卷条目下面挂着章",
    /<li><a href="c0002\.xhtml">第一卷 新手村<\/a>\s*<ol>/.test(nav), nav);
  ok("ncx navPoint 数 = 章数", (ncx.match(/<navPoint /g) || []).length === 6,
    (ncx.match(/<navPoint /g) || []).length);
  ok("ncx 嵌套：部的 navPoint 里含卷",
    /<navPoint id="np1" playOrder="1">[\s\S]*<navPoint id="np2" playOrder="2">/.test(ncx), ncx);
  ok("ncx playOrder 按先序递增",
    [1, 2, 3, 4, 5, 6].every(n => ncx.includes('playOrder="' + n + '"')));
}

console.log("== 插图链接粗筛（明显不是图的本地拦掉） ==");
{
  const acc = [
    "https://a.com/1.jpg",
    "https://a.com/pic.png?x=1",
    "http://a.com/showimg.php?id=9",
    "https://a.com/images?q=tbn:abc",
    "https://a.com/image/12345",
    "www.a.com/x.gif",
    "//cdn.a.com/x.webp",
    "https://a.com/pic/1.JPEG",
  ];
  const rej = [
    "https://zxcstxt.com/",
    "https://zxcstxt.com",
    "http://zxcstxt.com/book/",
    "https://a.com/index.html",
    "https://a.com/book.php",
    "https://a.com/x.JSP",
    "/img/1.jpg",          // 补不出完整地址
    "",
  ];
  const badAcc = acc.filter(u => !Core.imgWorthTrying(u));
  const badRej = rej.filter(u => Core.imgWorthTrying(u));
  ok("该放行的链接都放行", badAcc.length === 0, badAcc);
  ok("该拦掉的链接都拦掉", badRej.length === 0, badRej);
}

console.log("== 插图下载（伪造 fetch / Image） ==");
{
  const realFetch = globalThis.fetch, realImage = globalThis.Image, realLoc = globalThis.location;
  globalThis.location = { protocol: "file:", href: "file:///x" };
  globalThis.Image = class {                       // 只有 /probe-ok 能当图解码
    set referrerPolicy(v) { }
    set src(v) {
      const ok = String(v).includes("probe-ok");
      setTimeout(() => { if (ok) { this.naturalWidth = 8; this.onload && this.onload(); }
                         else this.onerror && this.onerror(); }, 0);
    }
  };
  const jpeg = Uint8Array.from([0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3]);
  let calls = [];
  globalThis.fetch = async (u) => {
    calls.push(String(u));
    if (String(u).includes("/page"))
      return new Response(new TextEncoder().encode("<html>x</html>"),
        { status: 200, headers: { "content-type": "text/html" } });
    if (String(u).includes("/dead"))
      return new Response(jpeg, { status: 404, headers: { "content-type": "text/plain" } });
    /* 模拟 CORS/混合内容：http 请求直接抛，https 能正常读 */
    if (String(u).startsWith("https://"))
      return new Response(jpeg, { status: 200, headers: { "content-type": "image/jpeg" } });
    throw new TypeError("Failed to fetch");
  };
  try {
    const links = Core.imageLinksInText('A <img src="//cdn.x.com/a.jpg"> B http://b.com/c.png');
    ok("认出协议相对 <img src>", links.includes("//cdn.x.com/a.jpg"), links);
    ok("认出裸链接", links.includes("http://b.com/c.png"), links);
    ok("不重复认被截断的短地址", !links.includes("x.com/a.jpg"), links);

    calls = [];
    let r = await Core.fetchImages("图 http://img.site.com/a.jpg 尾", { limit: 2 });
    ok("http 被掐后改试 https", calls.length === 2 && calls[1].startsWith("https://"), calls);
    ok("取到 1 张", r.images === 1 && r.map.size === 1, r.images);

    calls = [];
    r = await Core.fetchImages("图 https://x.com/probe-ok/page 尾", { limit: 2 });
    ok("返回网页不当图", r.images === 0, r.images);
    ok("探测通过计入 missed（跨域读不到字节）", r.missed === 1, r.missed);

    calls = [];
    r = await Core.fetchImages('A <img src="//cdn2.x.com/b.jpg"> B', { limit: 2 });
    ok("协议相对补成 https", calls[0] === "https://cdn2.x.com/b.jpg", calls);
    ok("协议相对能下载", r.images === 1, r.images);

    calls = [];
    r = await Core.fetchImages("图 https://x.com/dead.jpg 尾", { limit: 2 });
    ok("404 不换协议重试", calls.length === 1, calls);

    /* 粗筛：域名首页/目录页不发请求，也不占「检查条数」 */
    calls = [];
    r = await Core.fetchImages("首页 https://zxcstxt.com/ 目录 https://x.com/book/ 图 https://x.com/real.jpg",
      { limit: 3 });
    ok("首页/目录页不发请求", calls.length === 1 && String(calls[0]).includes("real.jpg"), calls);
    ok("检查条数只算真候选", r.checked === 1 && r.images === 1,
      { checked: r.checked, images: r.images });

    /* 进度回调：done 从 1 递增到 total（界面靠它显示「正在下第几张」） */
    const seen = [];
    r = await Core.fetchImages("图1 https://x.com/1.jpg 图2 https://x.com/2.jpg",
      { limit: 1, progress: (d, t) => seen.push(d + "/" + t) });
    ok("进度回调按完成条数递增", seen.join(",") === "1/2,2/2", seen);
    ok("进度回调不影响结果", r.images === 2, r.images);

    r = await Core.fetchImages("图1 https://x.com/1.jpg 图2 https://x.com/2.jpg", { limit: 2 });
    const imap = Core.imagesForEpub(r, "图1 https://x.com/1.jpg 图2 https://x.com/2.jpg");
    ok("epub 编号 001/002", [...imap.values()].map(v => v.name).join(",") === "001.jpg,002.jpg",
      [...imap.values()].map(v => v.name));

    /* 预取结果喂给清洗：<img src="//…"> 的写法要去重后仍能命中校验，
       否则整行会被当「含网址的行」删掉，图就白下载了 */
    const raw = "正文。http://a.com/x.jpg\n\n插图：<img src=\"//cdn.b.com/pic1.jpg\">\n";
    const pre = await Core.fetchImages(raw, { limit: 4 });
    const cleaned = Core.cleanText(raw, ["url", "imgkeep", "imgcheck"], false, null, pre.ctMap).text;
    ok("插图行不被当网址删掉", cleaned.includes('<img src="//cdn.b.com/pic1.jpg">'), cleaned);
    ok("两张图都进 epub", Core.imagesForEpub(pre, cleaned).size === 2,
      [...Core.imagesForEpub(pre, cleaned).keys()]);
  } finally {
    globalThis.fetch = realFetch; globalThis.Image = realImage; globalThis.location = realLoc;
  }
}

// ---------- 版面主题（样式必须内联进 HTML，且与 styles/*.css 完全一致） ----------
console.log("== 版面主题 ==");
{
  const dirs = ["styles", path.join("assets", "styles")];
  const dir = dirs.map(d => path.join(import.meta.dirname, "..", d))
    .find(d => fs.existsSync(d));
  const files = dir ? fs.readdirSync(dir).filter(f => f.endsWith(".css")).sort() : [];
  ok("找到样式目录", !!dir, dir);
  ok("内嵌主题数量与目录一致", Core.THEMES.length === files.length,
    { embedded: Core.THEMES.length, files: files.length });
  let same = true, bad = null;
  for (const f of files) {
    const disk = fs.readFileSync(path.join(dir, f), "utf8").replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
    const got = Core.THEME_CSS[f];
    if (got !== disk) { same = false; bad = f; break; }
  }
  ok("每套 CSS 与磁盘逐字节一致", same, bad);
  ok("默认主题存在", !!Core.THEME_CSS[Core.DEFAULT_THEME], Core.DEFAULT_THEME);
  ok("未知 id 回落到默认", Core.themeCss("nope.css") === Core.THEME_CSS[Core.DEFAULT_THEME]);
  const t = Core.themeById(Core.DEFAULT_THEME);
  ok("themeTitle 拆分中英", Core.themeTitle(t, false) !== Core.themeTitle(t, true), Core.themeTitle(t, false));
  const c = Core.parseThemeCss("/*! @theme-name: 我的墨绿 My Green\n * @description: 自用 */\nbody{margin:1em}",
    "my.css");
  ok("自定义 CSS 读到名字", c.named && c.name === "我的墨绿 My Green", c.name);
  ok("自定义 id 带前缀", c.id === "custom:my.css", c.id);
  const bare = Core.parseThemeCss("body{margin:1em}", "plain.css");
  ok("没写名字 → 用文件名", !bare.named && bare.name === "plain", bare.name);
  Core.addTheme(c);
  ok("addTheme 后可直接取样式", Core.themeCss("custom:my.css").includes("margin:1em"));
  ok("预览页含主题 CSS 与章名",
    Core.themePreviewHtml("body{color:red}", true).includes("color:red")
    && Core.themePreviewHtml("body{color:red}", true).includes("第一章 山雨"));
  ok("长正文比短正文长",
    Core.themePreviewHtml("", true).length > Core.themePreviewHtml("", false).length);
}

// 自定义 CSS 也要能整本导出（style.css 打进 zip 包）
function zipEntry(u8, name) {
  const buf = Buffer.from(u8);
  let p = 0;
  while ((p = buf.indexOf(Buffer.from([0x50, 0x4b, 0x03, 0x04]), p)) >= 0) {
    const method = buf.readUInt16LE(p + 8);
    const csize = buf.readUInt32LE(p + 18);
    const nlen = buf.readUInt16LE(p + 26);
    const xlen = buf.readUInt16LE(p + 28);
    const nm = buf.slice(p + 30, p + 30 + nlen).toString("utf8");
    if (nm === name) {
      const start = p + 30 + nlen + xlen;
      const data = buf.slice(start, start + csize);
      return method === 0 ? data : zlib.inflateRawSync(data);
    }
    p += 4;
  }
  return null;
}
{
  const custom = Core.parseThemeCss("body{margin:3em}\nh2{text-align:center}\np{text-indent:2em}",
    "e2e.css");
  Core.addTheme(custom);
  const zip = await Core.buildEpub({
    title: "T", author: "A", chapters: [{ t: "第1章", b: "正文" }],
    theme: custom.id, images: [],
  });
  const css = zipEntry(zip, "OEBPS/style.css");
  ok("自定义主题能导出 EPUB", zip.length > 400, zip.length);
  ok("导出的 style.css 就是所选自定义 CSS",
    !!css && css.toString("utf8") === custom.css);
  const builtin = await Core.buildEpub({
    title: "T", author: "A", chapters: [{ t: "第1章", b: "正文" }],
    theme: Core.DEFAULT_THEME, images: [],
  });
  const bc = zipEntry(builtin, "OEBPS/style.css");
  ok("内置主题导出的 style.css 与文件一致",
    !!bc && bc.toString("utf8") === Core.THEME_CSS[Core.DEFAULT_THEME]);

  /* 封面：epub 内部文件名按 MIME 归一，与传进来的 name 无关（与桌面版 write_epub 一致） */
  const pngBytes = Uint8Array.from([0x89, 0x50, 0x4E, 0x47, 1, 2, 3, 4]);
  const zc = await Core.buildEpub({
    title: "T", author: "A", chapters: [{ t: "第1章", b: "正文" }],
    theme: Core.DEFAULT_THEME, images: [],
    cover: { data: pngBytes, name: "斗破苍穹.webp", mime: "image/png" },
  });
  const coverEntry = zipEntry(zc, "OEBPS/cover.png");
  ok("封面文件名按 MIME 归一成 cover.png", !!coverEntry);
  ok("封面字节原样打进 zip",
    !!coverEntry && Buffer.compare(coverEntry, Buffer.from(pngBytes)) === 0);
  ok("不沿用传进来的原名", zipEntry(zc, "OEBPS/斗破苍穹.webp") === null);
  ok("opf 引用归一后的封面名",
    zipEntry(zc, "OEBPS/content.opf").toString("utf8").includes('href="cover.png"'));
  ok("cover.xhtml 指向归一后的封面",
    zipEntry(zc, "OEBPS/cover.xhtml").toString("utf8").includes('src="cover.png"'));
  const zn = await Core.buildEpub({
    title: "T", author: "A", chapters: [{ t: "第1章", b: "正文" }],
    theme: Core.DEFAULT_THEME, images: [],
    cover: { data: new Uint8Array(0), name: "cover.jpg", mime: "image/jpeg" },
  });
  ok("空封面字节按无封面处理", zipEntry(zn, "OEBPS/cover.xhtml") === null);
}

console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);
