/* 把一批文本行喂给 Web 版 CORE.cleanText，输出 JSON 结果。
 * 仅供 tools/test_clean_parity.py 做 Python / Web 一致性比对。
 * 用法:
 *   node tools/_dump_clean.mjs <输入.txt> <规则json> [自定义规则json]
 *   node tools/_dump_clean.mjs <汇总spec.json> --summary   （spec: {books,opt}）
 */
import fs from "node:fs";
import path from "node:path";

const html = fs.readFileSync(path.join(import.meta.dirname, "..", "web", "DeShelf.html"), "utf8");
const m = html.match(/\/\*CORE_BEGIN\*\/([\s\S]*?)\/\*CORE_END\*\//);
if (!m) { console.error("未找到 CORE 段"); process.exit(2); }
const Core = new Function(m[1] + "\n;return Core;")();

if (process.argv[3] === "--summary") {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  process.stdout.write(Core.buildCleanSummary(spec.books, spec.opt));
  process.exit(0);
}

const text = fs.readFileSync(process.argv[2], "utf8");
const rules = JSON.parse(process.argv[3]);
const custom = process.argv[4] ? JSON.parse(process.argv[4]) : null;
const r = Core.cleanText(text, rules, true, custom, null, true);
const cuts = [];
for (const [k, v] of r.cut) cuts.push([k, v]);
process.stdout.write(JSON.stringify({
  text: r.text, removed: r.removed, trimmed: r.trimmed, cuts,
  blank: r.blank, trace: r.trace
}));
