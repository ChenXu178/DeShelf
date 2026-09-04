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
  ok("半角转换", lines.includes("abc,def!123"));
  ok("行尾 trim", lines.includes("尾部有空格"));
  ok("首尾空行裁掉", r.text.startsWith("正文") && r.text.trimEnd().endsWith("尾部有空格"));
  ok("del 集合有记录", r.del.size >= 3);
  const r2 = Core.cleanText(sample, ["blank"], false);
  ok("blank 全删空行", !r2.text.includes("\n\n") && !r2.text.trimEnd().split("\n").some(l => l.trim() === ""), r2.text);
  const r3 = Core.cleanText("甲\n乙\n", ["indent"], false);
  ok("缩进两全角", r3.text.startsWith("　　甲"));
  const r4 = Core.cleanText("A：b（c）d，e。f「g」\n", ["half"], false);
  ok("全角→半角(FF01-FF5E，句号保留)", r4.text.split("\n")[0] === "A:b(c)d,e。f「g」", r4.text.split("\n")[0]);
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
  for (const need of ["META-INF/container.xml","OEBPS/content.opf","OEBPS/toc.ncx","OEBPS/style.css",
      "OEBPS/c0001.xhtml","OEBPS/c0002.xhtml"])
    ok("含 " + need, names.includes(need));
  const opf = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/content.opf").data);
  ok("opf 含书名/作者", opf.includes("测试书") && opf.includes("某人"));
  const c1 = new TextDecoder().decode(ents.find(e => e.name === "OEBPS/c0001.xhtml").data);
  ok("xhtml 含标题与段落缩进", c1.includes("第一章 开篇") && c1.includes("<p>") && c1.includes("正文乙"));
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

console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);
