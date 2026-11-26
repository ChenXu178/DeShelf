/* 卷帙 DeShelf Web — 真实浏览器冒烟（Edge headless + CDP，零 npm 依赖）
 * 验证：页面初始化无 JS 报错、双语切换、规则网格、帮助弹窗、
 *       文件入库、清洗预览、分章、章节树校验栏、导出章节树、
 *       批量分章汇总与双击回填、导出流程、拖拽函数。
 * 用法: node tools/smoke_web_browser.mjs
 */
import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const FILE_URL = "file:///" + path.resolve("web/DeShelf.html").replace(/\\/g, "/");
/* 端口现取现用：固定 9333 时连跑两次会撞上前一个还没退干净的实例，报 0 通过 */
const PORT = await new Promise(res => {
  const s = net.createServer();
  s.on("error", () => res(9333));
  s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); });
});
const PROFILE = path.join(process.env.TEMP || "/tmp", "deshelf_smoke_" + Date.now());

const results = [];
function ok(name, cond, extra) {
  if (cond) { results.push("✓ " + name); console.log("  ✓ " + name); }
  else { results.push("✗ " + name + (extra !== undefined ? "  | " + extra : "")); console.error("  ✗ FAIL: " + name + (extra !== undefined ? " | " + extra : "")); }
}

// ---------- 启动 Edge ----------
const args = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-extensions", "--remote-debugging-port=" + PORT, "--user-data-dir=" + PROFILE, "about:blank"];
const edge = spawn(EDGE, args, { stdio: "ignore" });

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
async function waitFor(url, tries = 60) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(url); if (r.ok) return true; } catch (_) {}
    await sleep(500);
  }
  return false;
}
try {
  if (!(await waitFor("http://127.0.0.1:" + PORT + "/json/version"))) throw new Error("CDP 端口未就绪");
  // 新建页面并导航
  const put = await fetch("http://127.0.0.1:" + PORT + "/json/new?" + encodeURIComponent(FILE_URL), { method: "PUT" });
  const target = await put.json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let seq = 0; const pend = new Map(); const errors = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
    else if (m.method === "Runtime.exceptionThrown") {
      const d = m.params.exceptionDetails;
      errors.push("exception: " + (d.exception ? d.exception.description : d.text));
    } else if (m.method === "Log.entryAdded" && m.params.entry.level === "error") {
      const txt = m.params.entry.text || "";
      const url = m.params.entry.url || "";
      if (/busuanzi|ibruce/i.test(txt) || /busuanzi|ibruce/i.test(url)) return;  // 访问计数器，离线必 404
      // 离线/无网时第三方脚本的加载失败只走 Log 域，应用自身的异常走 Runtime.exceptionThrown，
      // 所以这里可以安全地忽略「资源加载失败」，否则每次离线跑都会误报
      if (/Failed to load resource/i.test(txt) &&
          /ERR_FILE_NOT_FOUND|ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|ERR_CONNECTION/i.test(txt)) return;
      errors.push("console.error: " + txt);
    }
  };
  function send(method, params = {}) {
    return new Promise(res => { const i = ++seq; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  }
  async function evalv(expression) {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.result && r.result.exceptionDetails) {
      return { err: r.result.exceptionDetails.exception ? r.result.exceptionDetails.exception.description : r.result.exceptionDetails.text };
    }
    return { val: r.result && r.result.result ? r.result.result.value : undefined };
  }
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Page.enable");
  // 等 boot：轮询规则网格是否渲染出来（机器忙时固定 2.5 秒可能不够）
  for (let i = 0; i < 40; i++) {
    const w = await evalv("document.querySelectorAll('.rule').length");
    if (w.val) break;
    await sleep(250);
  }
  await sleep(300);

  // 1. 初始渲染
  let r = await evalv("({rules:document.querySelectorAll('.rule').length, n:Core.RULES.length, h2:document.querySelector('#pane0 h2').textContent, nav:document.querySelector('#stepNav .st b').textContent})");
  ok("规则网格条数与 RULES 一致", r.val && r.val.rules === r.val.n, JSON.stringify(r.err || r.val));
  ok("中文标题渲染", r.val && /书库/.test(r.val.h2 || ""), r.err || (r.val && r.val.h2));
  ok("无初始化报错", errors.length === 0, errors.join(" | "));

  // 2. 语言切换
  await evalv("document.getElementById('btnLang').click()");
  await sleep(400);
  r = await evalv("({h2:document.querySelector('#pane0 h2').textContent, btn:document.getElementById('btnLang').textContent, rules:document.querySelector('.rule .t').textContent})");
  ok("切到英文界面", r.val && /Library/.test(r.val.h2 || ""), JSON.stringify(r.err || r.val));
  await evalv("document.getElementById('btnLang').click()");
  await sleep(300);

  // 3. 帮助/关于弹窗
  await evalv("document.getElementById('btnHelp').click()");
  await sleep(300);
  r = await evalv("({dlg:!!document.querySelector('.dlg'), t:document.querySelector('.dlg .dh')?document.querySelector('.dlg .dh').childNodes[0].textContent:''})");
  ok("帮助弹窗打开", r.val.dlg && /帮助/.test(r.val.t), JSON.stringify(r.val));
  await evalv("document.querySelector('.dlg .x').click()");
  await sleep(200);
  r = await evalv("!document.querySelector('.dlg')");
  ok("弹窗可关闭", r.val === true);

  // 3b. 截图改在分章批量测试后（7d），此处仅回书库页
  await evalv("window.goStep(0)");

  // 4. 注入文件入库（等效拖拽）
  const bookText = "书名：《冒烟测试书》\n作者：测试君\n\n序章 引子\n这是序章正文内容。\n\n"
    + "第1章 开端\n请收藏本站 www.example.com\n正文甲第一段。\n"
    + '<a href="https://example.com">网站</a>\n\n第2章 发展\n上一页\n正文乙第二段。\n\n第3章 终章\n（乱码\uFFFD测试行）\n正文丙第三段，收尾。\n';
  r = await evalv(`(async () => {
    const f = new File([${JSON.stringify(bookText)}], "冒烟测试书.txt", {type:"text/plain"});
    await window.dropFilesToLib([f], false);
    await new Promise(r2=>setTimeout(r2,1200));
    const rows = document.querySelectorAll('#libTbl tr');
    return { rows: rows.length - 1, name: rows[1] ? rows[1].children[1].textContent : '' , st: document.querySelector('#libInfo').textContent};
  })()`);
  ok("注入文件入库成功", r.val && r.val.rows === 1, JSON.stringify(r.err || r.val));
  ok("书名识别", r.val && /冒烟测试书/.test(r.val.name), JSON.stringify(r.val));

  // 4b. 插图规则联动：含网址的行 → 显隐；保留插图链接 → 校验可勾
  r = await evalv(`(() => {
    const q = rid => document.querySelector('.rule[data-rid="'+rid+'"]');
    const vis = rid => { const e=q(rid); return !!e && e.style.display!=='none'; };
    const dis = rid => { const e=q(rid); return !!e && e.querySelector('input').disabled; };
    const flip = (rid,v) => { const i=q(rid).querySelector('input'); i.checked=v; i.dispatchEvent(new Event('change')); };
    const out = {visKeep:vis('imgkeep'), visChk:vis('imgcheck'), disChk:dis('imgcheck')};
    flip('url',false);
    out.hidden = !vis('imgkeep') && !vis('imgcheck');
    flip('url',true);
    flip('imgkeep',true);
    out.enabled = !dis('imgcheck');
    flip('imgkeep',false);   /* 复位，别影响后面的清洗用例 */
    out.disBack = dis('imgcheck');
    return out;
  })()`);
  ok("插图两条可见、校验默认禁用", r.val && r.val.visKeep && r.val.visChk && r.val.disChk, JSON.stringify(r.err || r.val));
  ok("取消「含网址的行」后两条隐藏", r.val && r.val.hidden, JSON.stringify(r.err || r.val));
  ok("勾「保留插图链接」后校验可勾、取消后复位禁用", r.val && r.val.enabled && r.val.disBack, JSON.stringify(r.err || r.val));

  // 5. 清洗预览（需先载入所选书文本）
  r = await evalv(`(async () => {
    await window.previewClean();
    await new Promise(r2=>setTimeout(r2,600));
    const panes = document.querySelectorAll('#cleanPane .pane');
    const pre = document.querySelector('#cleanPane .pane pre');
    return {panes: panes.length, hasDel: !!document.querySelector('#cleanPane .del'),
            leftHtml: pre ? pre.innerHTML : '', info: document.querySelector('#cleanInfo').textContent};
  })()`);
  ok("清洗预览双栏渲染", r.val && r.val.panes === 2, JSON.stringify(r.err || r.val));
  /* 行内被清掉的 HTML 标签要标红：<a href="…">网站</a> → 两段标签划线、"网站"不划线 */
  ok("行内被清掉的 HTML 标签在预览里标红",
     r.val && /<span class="del">&lt;a href=/.test(r.val.leftHtml)
       && /<\/span>网站<span class="del">&lt;\/a&gt;<\/span>/.test(r.val.leftHtml),
     (r.val && r.val.leftHtml || "").slice(0, 300));

  // 6. 应用清洗（带异常栈诊断）
  r = await evalv(`(async () => {
    window.__dbg='';
    try{ await window.applyClean(); }
    catch(e){ window.__dbg=(e.stack||e.message)+' | '+(e&&e.message); }
    await new Promise(r2=>setTimeout(r2,600));
    return {msg: document.querySelector('#cleanInfo').textContent, err: window.__dbg};
  })()`);
  console.log("  · 清洗诊断:", JSON.stringify(r.val || r.err));
  ok("清洗应用完成", r.val && /清洗/.test(r.val.msg) && !/删除 0 行/.test(r.val.msg) && !r.val.err, JSON.stringify(r.err || r.val));

  // 7b. 分阶段探针：定位正则/清洗/导出错误的真实来源
  const probe = await evalv(`(async () => {
    const o = {};
    try { o.regValue = document.querySelector('#chapRegex').value; o.regLen = document.querySelector('#chapRegex').value.length; } catch(e){ o.r1 = e.message; }
    // File 构造探针（独立于 app 逻辑）
    try {
      const f0 = new File(["书名：X 内容ABC测试"], "x.txt", {type:"text/plain"});
      const ab = await f0.arrayBuffer();
      o.fileProbe = ab.byteLength;
      o.fileText = new TextDecoder().decode(ab);
    } catch(e){ o.fileErr = (e && e.message); }
    try {
      const b = (window.selectedBooks ? window.selectedBooks() : [])[0];
      if (!b) { o.phase = 'noBook'; return o; }
      o.phase = 'haveBook';
      try { o.t = await window.bookText(b); o.tlen = o.t.length; o.head = o.t.slice(0, 80); } catch(e){ o.phase = 'bookText ERR: ' + e.message; return o; }
      try { await window.previewClean(); } catch(e){ o.phase = 'preview ERR: ' + e.message; return o; }
      o.phase = 'preview ok';
    } catch(e){ o.phase = 'outer ERR: ' + e.message; }
    return o;
  })()`);
  console.log("  · 探针:", JSON.stringify(probe.val || probe.err, null, 1));
  let dbg = await evalv(`(async () => {
    window.goStep(2);
    await new Promise(r2=>setTimeout(r2,300));
    const sel=document.querySelector('#chapBook');
    const snap={selVal:sel?sel.value:'x', n:sel?sel.options.length:0,
      opt0:sel&&sel.options[0]?(sel.options[0].value+'|'+sel.options[0].textContent):'-',
      txtLen:(window.bookText&&true)?-1:0};
    window.__dbg='';
    try{ await window.tryChapters(); }
    catch(e){ window.__dbg=(e.stack||e.message)+'\\n'+(e&&e.message); }
    await new Promise(r2=>setTimeout(r2,400));
    snap.err=window.__dbg;
    snap.chs=document.querySelectorAll('#chapList .ch').length;
    snap.info=document.querySelector('#chapInfo').textContent;
    return snap;
  })()`);
  console.log("  · 分章诊断:", JSON.stringify(dbg.val||dbg.err, null, 1));
  ok("分章 select 有书", dbg.val && dbg.val.n === 1 && dbg.val.selVal === "0", JSON.stringify(dbg.val||dbg.err));
  // 样本含「书名/作者」元信息行：v1.4.0 起纯元信息的「开篇」不再单独成章，
  // 所以这里是 4 章、首章就是正文第一个标题（与桌面版 python 行为一致）
  ok("分章识别出 4 章", dbg.val && dbg.val.chs === 4, JSON.stringify(dbg.val));
  let titles = await evalv(`window._lastTry ? window._lastTry.chs.map(c=>c.t) : []`);
  ok("首章是正文标题而非开篇", titles.val && titles.val[0] === "序章 引子", JSON.stringify(titles.val));
  ok("含序章与第3章", titles.val && titles.val.includes("序章 引子") && titles.val.includes("第3章 终章"), JSON.stringify(titles.val));

  // 7b2. 章节树校验栏：无序号章标红、正常章显示「正常」、底部带异常计数
  r = await evalv(`(() => {
    const rows = Array.from(document.querySelectorAll('#chapList .ch'));
    const cell = n => (rows[n-1] ? rows[n-1].querySelector('.ck') : null);
    return {n:rows.length,
      bad:document.querySelectorAll('#chapList .ch.bad').length,
      first:cell(1) ? cell(1).textContent : '',
      second:cell(2) ? cell(2).textContent : '',
      info:document.querySelector('#chapInfo').textContent};
  })()`);
  ok("校验栏每行都有结果", r.val && r.val.n === 4 && r.val.second !== '', JSON.stringify(r.err || r.val));
  ok("无序号章报序号提取失败并标红",
    r.val && /序号提取失败/.test(r.val.first) && r.val.bad === 1, JSON.stringify(r.val));
  ok("正常章显示「正常」、底部带异常计数",
    r.val && r.val.second === '正常' && /校验异常 1/.test(r.val.info), JSON.stringify(r.val));

  if (dbg.val && dbg.val.chs > 0) {
    await evalv(`window.applyChapters()`);
  }

  // 7c. 批量一键分章（v1.3 新功能）：整库按钮应把结果保存到各书
  r = await evalv(`(async () => {
    document.getElementById('btnChapAll').click();
    await new Promise(r2=>setTimeout(r2,1200));
    return {info: document.querySelector('#chapAllInfo').textContent,
            sel: document.querySelector('#chapBook option') ? document.querySelector('#chapBook option').textContent : ''};
  })()`);
  ok("批量一键分章完成", r.val && /完成/.test(r.val.info), JSON.stringify(r.err || r.val));
  ok("分章结果已保存到书(下拉带章数)", r.val && /\[\d+章\]/.test(r.val.sel), JSON.stringify(r.val));

  // 7c2. 批量结果列表：一行一本书只给校验汇总；双击进入该书单本试分
  r = await evalv(`(() => {
    const row = document.querySelector('#chapList .ch.bk');
    return {n:document.querySelectorAll('#chapList .ch.bk').length,
      ck:row ? row.querySelector('.ck').textContent : '',
      bad:document.querySelectorAll('#chapList .ch.bk.bad').length,
      info:document.querySelector('#chapAllInfo').textContent};
  })()`);
  ok("批量列表一行一本书", r.val && r.val.n === 1, JSON.stringify(r.err || r.val));
  ok("批量行只显示校验汇总（正常 / 共N个异常）",
    r.val && /^(正常|共\d+个异常)$/.test(r.val.ck) && r.val.bad === 1, JSON.stringify(r.val));
  ok("批量提示带异常本数与双击提示",
    r.val && /校验异常 1 本/.test(r.val.info) && /双击/.test(r.val.info), JSON.stringify(r.val));

  r = await evalv(`(async () => {
    const bk = document.querySelector('#chapList .ch.bk');
    if (!bk) return {bk:0};
    bk.dispatchEvent(new MouseEvent('dblclick', {bubbles:true}));
    await new Promise(r2=>setTimeout(r2,1200));
    return {bk:document.querySelectorAll('#chapList .ch.bk').length,
      rows:document.querySelectorAll('#chapList .ch').length,
      info:document.querySelector('#chapInfo').textContent,
      sel:document.querySelector('#chapBook').value,
      head:document.querySelector('#chapList .ch .ck') ? document.querySelector('#chapList .ch .ck').textContent : ''};
  })()`);
  ok("双击批量行 → 切到该书单本试分",
    r.val && r.val.bk === 0 && r.val.rows === 4 && r.val.sel === "0", JSON.stringify(r.err || r.val));
  ok("双击后回到章节明细（校验列仍在）",
    r.val && /识别|chapters found/.test(r.val.info) && r.val.head !== '', JSON.stringify(r.val));

  // 7d. 截图（分章页：批量按钮 + 日志默认展开）用于 UI 复查
  try {
    await sleep(400);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    if (shot.result && shot.result.data) {
      fs.writeFileSync("web/_ui_shot.png", Buffer.from(shot.result.data, "base64"));
      console.log("  分章页截图已存 web/_ui_shot.png");
    }
  } catch (e) { console.error("截图失败:", e.message); }

  // 7e. 导出章节树：文件名后缀与内容随语言走，下载用桩函数接住
  r = await evalv(`(async () => {
    const old = window.dlBytes;
    window.__dl = null;
    window.dlBytes = (name, data, mime) => { window.__dl = {name:name, data:data, mime:mime}; };
    const grab = () => window.__dl ? {
      name: window.__dl.name,
      head: String(window.__dl.data).split('\\n')[0],
      hasLevel: /各级章节数：|Chapters per level:/.test(window.__dl.data),
      hasZero: /\\[0\\] /.test(window.__dl.data),
      hasRow: /\\n\\[\\d+\\] /.test(window.__dl.data),
      hasFail: /序号提取失败|number not recognised/.test(window.__dl.data)
    } : null;
    await window.tryChapters();
    await new Promise(r2=>setTimeout(r2,400));
    document.getElementById('btnChapTree').click();
    await new Promise(r2=>setTimeout(r2,700));
    const zh = grab();
    document.getElementById('btnLang').click();          /* → English */
    await new Promise(r2=>setTimeout(r2,500));
    await window.tryChapters();
    await new Promise(r2=>setTimeout(r2,500));
    document.getElementById('btnChapTree').click();
    await new Promise(r2=>setTimeout(r2,700));
    const en = grab();
    document.getElementById('btnLang').click();          /* → 中文 */
    await new Promise(r2=>setTimeout(r2,500));
    window.dlBytes = old;
    return {zh:zh, en:en, lang:CUR};
  })()`);
  console.log("  · 章节树导出:", JSON.stringify(r.err || r.val));
  ok("中文导出：文件名 _章节树.txt", r.val && r.val.zh && /_章节树\.txt$/.test(r.val.zh.name), JSON.stringify(r.val && r.val.zh));
  ok("中文导出：表头与各级统计齐全",
    r.val && r.val.zh && r.val.zh.head === '章节树导出' && r.val.zh.hasLevel, JSON.stringify(r.val && r.val.zh));
  ok("中文导出：含章节明细与校验结果",
    r.val && r.val.zh && r.val.zh.hasRow && r.val.zh.hasFail, JSON.stringify(r.val && r.val.zh));
  ok("英文导出：文件名 _chapter_tree.txt", r.val && r.val.en && /_chapter_tree\.txt$/.test(r.val.en.name), JSON.stringify(r.val && r.val.en));
  ok("英文导出：表头与各级统计为英文",
    r.val && r.val.en && r.val.en.head === 'Chapter tree export' && r.val.en.hasLevel, JSON.stringify(r.val && r.val.en));
  ok("导出后语言复位为中文", r.val && r.val.lang === 'zh', JSON.stringify(r.val && r.val.lang));

  // 8. 导出（EPUB+合并TXT；headless 下载只触发不落盘）
  r = await evalv(`(async () => {
    window.goStep(3);
    await new Promise(r2=>setTimeout(r2,200));
    const selBefore = document.querySelector('#outSelInfo').textContent;
    document.getElementById('fmtEpub').checked = true;
    document.getElementById('fmtTxt').checked = true;
    document.getElementById('fmtSplit').checked = false;
    window.__dbg='';
    try{ await window.runExport(); }
    catch(e){ window.__dbg=(e.stack||e.message)+' | '+(e&&e.message); }
    await new Promise(r2=>setTimeout(r2,3000));
    const rows = document.querySelectorAll('#outTbl tr');
    return {sel: selBefore, out: document.querySelector('#outMsg').textContent, rows: rows.length-1,
      st: rows[1]?rows[1].children[1].textContent:'', err: window.__dbg};
  })()`);
  console.log("  · 导出诊断:", JSON.stringify(r.val && r.val.err ? r.val.err : (r.val && {out:r.val.out, st:r.val.st})));
  ok("导出面板显示已选 1 本", r.val && /1/.test(r.val.sel), JSON.stringify(r.err || r.val));
  ok("导出完成无失败", r.val && r.val.out && /成功 1 · 失败 0/.test(r.val.out) && r.val.rows >= 1 && !r.val.err, JSON.stringify(r.err || r.val));
  ok("结果行状态正常", r.val && /epub/i.test(r.val.st), JSON.stringify(r.val));

  // 8b. 「常用写法」窗口：8 条模板，能填进全局正则 / 本书专用
  r = await evalv(`(async () => {
    window.goStep(2);
    await new Promise(r2=>setTimeout(r2,250));
    document.getElementById('chapReHelp').click();
    await new Promise(r2=>setTimeout(r2,250));
    const rows = document.querySelectorAll('.dlg tbody tr').length;
    const radios = document.querySelectorAll('.dlg input[name=tplsel]').length;
    document.querySelectorAll('.dlg input[name=tplsel]')[1].checked = true;   /* 第一折 */
    document.querySelector('.dlg [data-fill=global]').click();
    await new Promise(r2=>setTimeout(r2,200));
    const g = document.getElementById('chapRegex').value;
    const closed = !document.querySelector('.dlg');
    document.getElementById('chapReHelp').click();
    await new Promise(r2=>setTimeout(r2,200));
    document.querySelectorAll('.dlg input[name=tplsel]')[0].checked = true;
    document.querySelector('.dlg [data-fill=book]').click();
    await new Promise(r2=>setTimeout(r2,200));
    const bk = document.getElementById('bookRegex').value;
    const onBook = !!(window.chapBookObj && window.chapBookObj().chapRe);
    /* 收尾：两格清空，别留给下次打开 */
    document.getElementById('chapRegex').value = '';
    document.getElementById('bookRegex').value = '';
    window.storeBookRegex();
    return {rows, radios, g, closed, bk, onBook};
  })()`);
  ok("常用写法列出 8 条模板", r.val && r.val.rows === 8 && r.val.radios === 8, JSON.stringify(r.err || r.val));
  ok("模板填入全局正则生效", r.val && /折/.test(r.val.g) && r.val.closed, JSON.stringify(r.val));
  ok("模板填入本书专用生效", r.val && /章/.test(r.val.bk) && r.val.onBook, JSON.stringify(r.val));

  // 8c. 清洗内容汇总：明细随清洗快照缓存，汇总文本按书籍分类并带原文行号与规则
  r = await evalv(`(() => {
    const b = St.books[0];
    const el = document.getElementById('optSum');
    const tr = b._cleanTrace || [];
    const txt = Core.buildCleanSummary([{title:b.title||b.name,author:b.author||'',
      file:b.rel||b.name,linesBefore:b._cleanBefore,linesAfter:Core.lineCount(b._clean),
      blank:b._cleanBlank||0,entries:tr,note:''}],
      {rules:activeRuleIds(),lang:CUR,custom:St.customRules,when:'2026-01-01 00:00:00'});
    return {el:!!el,on:!!(el&&el.checked),n:tr.length,
      kind:tr.length?tr[0].kind:'',rule:tr.length?tr[0].rule:'',line:tr.length?tr[0].line:0,
      hasHead:txt.indexOf('清洗内容汇总')>=0,
      hasCol:txt.indexOf('原文行号')>=0&&txt.indexOf('清理原因')>=0,
      hasRule:/站点宣传行|含网址的行|翻页导航残留|乱码行/.test(txt),
      hasStat:txt.indexOf('原因统计：')>=0,
      hasBlank:txt.indexOf('删除空行')>=0};
  })()`);
  console.log("  · 汇总诊断:", JSON.stringify(r.err || r.val));
  ok("默认勾选「生成清洗内容汇总」", r.val && r.val.el && r.val.on, JSON.stringify(r.val));
  ok("清洗明细随快照缓存（含原文行号与规则）",
    r.val && r.val.n > 0 && r.val.rule && r.val.line >= 1, JSON.stringify(r.val));
  ok("汇总含书头/列名/原因/空行统计",
    r.val && r.val.hasHead && r.val.hasCol && r.val.hasRule && r.val.hasStat && r.val.hasBlank,
    JSON.stringify(r.val));

  // 8d. 版面主题：卡片列表 + 大图预览 + 视口尺寸 + 确定后生效
  r = await evalv(`(async () => {
    document.getElementById('btnTheme').click();
    await new Promise(r2=>setTimeout(r2,500));
    const cards=[...document.querySelectorAll('.tp-card')];
    const fr=cards[0]&&cards[0].querySelector('iframe');
    return {cards:cards.length,n:Core.THEMES.length,
      cssOk:!!(fr&&fr.srcdoc&&fr.srcdoc.indexOf(Core.THEME_CSS[Core.THEMES[0].id])>=0),
      big:!!document.getElementById('tpFrame'),
      split:!!document.getElementById('tpSplit'),
      imp:!!document.querySelector('.dlg [data-imp]'),
      title:(document.querySelector('.dlg .dh')||{textContent:''}).textContent};
  })()`);
  ok("主题选择器：卡片数与内嵌主题一致", r.val && r.val.ok !== false
    && r.val.cards === r.val.n && r.val.n >= 10, JSON.stringify(r.err || r.val));
  ok("主题选择器：卡片内嵌主题 CSS", r.val && r.val.cssOk, JSON.stringify(r.val));
  ok("主题选择器：大图预览 + 分隔条 + 导入按钮",
    r.val && r.val.big && r.val.split && r.val.imp, JSON.stringify(r.val));

  r = await evalv(`(async () => {
    const cards=[...document.querySelectorAll('.tp-card')];
    const pick=Core.THEMES[2];
    cards[2].click();
    await new Promise(r2=>setTimeout(r2,300));
    const on=document.querySelector('.tp-card.on');
    const big=document.getElementById('tpFrame');
    const nameOk=(document.querySelector('.dlg .dh')||{textContent:''}).textContent.indexOf(Core.themeTitle(pick,CUR==='en'))>=0;
    document.getElementById('tpW').value='360';
    document.getElementById('tpH').value='640';
    document.getElementById('tpApply').click();
    await new Promise(r2=>setTimeout(r2,300));
    return {sel:on&&on.dataset.id, want:pick.id, nameOk,
      bigCss:!!(big&&big.srcdoc&&big.srcdoc.indexOf(pick.css)>=0),
      w:big&&big.style.width, h:big&&big.style.height};
  })()`);
  ok("主题选择器：点击卡片即切换并更新标题", r.val && r.val.sel === r.val.want && r.val.nameOk,
    JSON.stringify(r.err || r.val));
  ok("主题选择器：大图按所选主题重渲", r.val && r.val.bigCss, JSON.stringify(r.val));
  ok("主题选择器：视口尺寸生效", r.val && r.val.w === '360px' && r.val.h === '640px',
    JSON.stringify(r.val));

  r = await evalv(`(async () => {
    document.querySelector('.dlg [data-ok]').click();
    await new Promise(r2=>setTimeout(r2,300));
    const want=Core.THEMES[2];
    const btn=document.getElementById('btnTheme').textContent;
    return {btn, saved:cfgKey('theme'), want:want.id,
      nameOk:btn===Core.themeTitle(want,CUR==='en'),
      closed:!document.querySelector('.dlg'),
      css:Core.themeCss(themeId())===want.css};
  })()`);
  ok("主题选择器：确定后写回配置并更新按钮",
    r.val && r.val.saved === r.val.want && r.val.closed && r.val.css && r.val.nameOk,
    JSON.stringify(r.err || r.val));

  // 8e. 封面设置窗：网格卡片（封面/书名/作者）+ 右键菜单 + 本地图片 + 确定提交
  r = await evalv(`(async () => {
    document.getElementById('btnCover').click();
    await new Promise(r2=>setTimeout(r2,1500));
    const cards=[...document.querySelectorAll('.cv-card')];
    const c0=cards[0];
    const out={n:cards.length,sel:St.books.filter(b=>b.sel).length,
      name:!!(c0&&c0.querySelector('.cv-name').textContent.trim()),
      auth:!!(c0&&c0.querySelector('.cv-auth')),
      hasImg:!!(c0&&c0.querySelector('.cv-shot img')),
      tip:(document.querySelector('.cv-tip')||{textContent:''}).textContent.length>0};
    c0.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,
      clientX:120,clientY:120}));
    const menu=document.getElementById('cvMenu');
    out.menu=menu?menu.children.length:0;
    out.menuText=menu?menu.textContent:'';
    out.wantPick=T('coverPickImg');out.wantDl=T('coverDl');
    return out;
  })()`);
  ok("封面窗：卡片数 = 已选书籍数", r.val && r.val.n === r.val.sel && r.val.n === 1,
    JSON.stringify(r.err || r.val));
  ok("封面窗：卡片含封面图 / 书名 / 作者", r.val && r.val.hasImg && r.val.name && r.val.auth,
    JSON.stringify(r.val));
  ok("封面窗：右键菜单为「选择封面图片 / 下载网络封面」", r.val && r.val.menu === 2
    && r.val.menuText.indexOf(r.val.wantPick) >= 0
    && r.val.menuText.indexOf(r.val.wantDl) >= 0, JSON.stringify(r.val));

  // 8e1b. 菜单项可点：点「下载网络封面」弹出链接输入框，取消后回到封面窗
  r = await evalv(`(async () => {
    const menu=document.getElementById('cvMenu');
    const item=menu?[...menu.children][1]:null;
    if(!item) return {noMenu:true};
    item.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
    item.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    await new Promise(r2=>setTimeout(r2,300));
    const inp=document.getElementById('cvUrl');
    const dlgs=[...document.querySelectorAll('.dlg')];
    const top=dlgs[dlgs.length-1];
    const out={menuClosed:!document.getElementById('cvMenu'),dialog:!!inp,
      cards:dlgs.length,placeholder:inp?inp.placeholder:''};
    const c=top?top.querySelector('[data-c]'):null;
    if(c)c.click();
    await new Promise(r2=>setTimeout(r2,250));
    out.closedAfterCancel=!document.getElementById('cvUrl');
    out.coverStillOpen=!!document.querySelector('.cv-card');
    return out;
  })()`);
  ok("封面窗：菜单「下载网络封面」弹出链接输入框", r.val && r.val.menuClosed
    && r.val.dialog && r.val.placeholder.indexOf('http') === 0, JSON.stringify(r.err || r.val));
  ok("封面窗：取消链接输入框后回到封面窗", r.val && r.val.closedAfterCancel
    && r.val.coverStillOpen, JSON.stringify(r.val));

  // 8e1c. 跨域（CORS）挡下封面下载时：说明原因并引导用桌面版
  r = await evalv(`(async () => {
    const c0=document.querySelector('.cv-card');
    const realF=Core.fetchImageBytes, realP=Core.probeImage;
    Core.fetchImageBytes=async()=>null;      /* 模拟：字节读不到 */
    Core.probeImage=async()=>"probe";        /* 模拟：<img> 能显示，说明图是活的 */
    await cpDownload(c0,'https://cdn.example.com/cover.jpg');
    await new Promise(r2=>setTimeout(r2,300));
    Core.fetchImageBytes=realF;Core.probeImage=realP;
    const dlgs=[...document.querySelectorAll('.dlg')];
    const top=dlgs[dlgs.length-1];
    const txt=top?top.textContent:'';
    const out={title:top?(top.querySelector('.dh')||{}).textContent:'',
      hasCors:/CORS|跨域/.test(txt), hasDesktop:/桌面版|desktop app/i.test(txt),
      logged:logBox.textContent.indexOf('cover.jpg')>=0};
    const btn=top?top.querySelector('[data-ok]'):null;
    if(btn)btn.click();
    await new Promise(r2=>setTimeout(r2,250));
    out.closed=!(top&&document.body.contains(top));
    out.coverStillOpen=!!document.querySelector('.cv-card');
    return out;
  })()`);
  ok("封面下载被跨域拦下：提示原因并引导用桌面版", r.val && r.val.hasCors
    && r.val.hasDesktop && r.val.closed && r.val.coverStillOpen, JSON.stringify(r.err || r.val));

  // 8e2. 换成本地图片：转 JPEG、刷新缩略图、记进工作副本
  r = await evalv(`(async () => {
    const c0=document.querySelector('.cv-card');
    const cv=document.createElement('canvas');cv.width=90;cv.height=120;
    const g=cv.getContext('2d');g.fillStyle='#c0392b';g.fillRect(0,0,90,120);
    const blob=await new Promise(r2=>cv.toBlob(r2,'image/png'));
    const f=new File([blob],'my-cover.png',{type:'image/png'});
    const got=await cpSetCoverFile(c0,f);
    const cov=CP.tmp.get(c0.dataset.k);
    const img=c0.querySelector('.cv-shot img');
    return {got:!!got,mime:cov&&cov.mime,w:cov&&cov.w,h:cov&&cov.h,
      isJpeg:!!(cov&&cov.mime==='image/jpeg'),
      blobImg:!!(img&&String(img.src).startsWith('blob:'))};
  })()`);
  ok("封面窗：自选图片转成 JPEG 并刷新缩略图", r.val && r.val.got && r.val.isJpeg
    && r.val.w === 90 && r.val.h === 120 && r.val.blobImg, JSON.stringify(r.err || r.val));

  // 8e3. 确定后提交：封面映射落定、按钮变成「封面（已设 1 本）」
  r = await evalv(`(async () => {
    document.querySelector('.dlg [data-ok]').click();
    await new Promise(r2=>setTimeout(r2,300));
    const b=St.books[0];
    const cov=St.coverMap.get(bookKey(b));
    const same=await coverFor(b);
    return {closed:!document.querySelector('.cv-card'),n:St.coverMap.size,
      btn:document.getElementById('btnCover').textContent,
      hasCov:!!cov, sameBytes:!!(cov&&same&&same.data===cov.data)};
  })()`);
  ok("封面窗：确定后关闭并提交封面", r.val && r.val.closed && r.val.n === 1 && r.val.hasCov,
    JSON.stringify(r.err || r.val));
  ok("封面窗：按钮显示已设数量", r.val && /1/.test(r.val.btn), JSON.stringify(r.val));

  // 8e4. 导出的 EPUB 用的是封面窗里那份图（文件名按 MIME 归一成 cover.jpg）
  r = await evalv(`(async () => {
    const real=window.dlBytes; let cap=null;
    window.dlBytes=(n,d)=>{ if(/\\.epub$/i.test(n)) cap=d; };
    document.getElementById('fmtEpub').checked=true;
    document.getElementById('fmtTxt').checked=false;
    document.getElementById('fmtSplit').checked=false;
    try{ await window.runExport(); }catch(e){}
    await new Promise(r2=>setTimeout(r2,1500));
    window.dlBytes=real;
    let hasName=false,hasXhtml=false;
    if(cap&&cap.length){
      const s=new TextDecoder('latin1').decode(cap);
      hasName=s.indexOf('OEBPS/cover.jpg')>=0;
      hasXhtml=s.indexOf('OEBPS/cover.xhtml')>=0;
    }
    return {bytes:cap?cap.length:0,hasName,hasXhtml};
  })()`);
  ok("导出 EPUB 带上封面窗设置的封面", r.val && r.val.bytes > 400 && r.val.hasName && r.val.hasXhtml,
    JSON.stringify(r.err || r.val));

  // 8f. 没勾「导出 EPUB」时，版面主题 / 封面整组置灰
  r = await evalv(`(async () => {
    const ep=document.getElementById('fmtEpub');
    const st=()=>[document.getElementById('btnTheme').disabled,
                  document.getElementById('btnCover').disabled];
    ep.checked=false;ep.dispatchEvent(new Event('change'));
    const off=st();
    ep.checked=true;ep.dispatchEvent(new Event('change'));
    return {off,on:st()};
  })()`);
  ok("未勾 EPUB 时版面主题/封面置灰",
    r.val && r.val.off[0] === true && r.val.off[1] === true, JSON.stringify(r.err || r.val));
  ok("勾回 EPUB 后恢复可编辑",
    r.val && r.val.on[0] === false && r.val.on[1] === false, JSON.stringify(r.val));

  // 8g. 运行日志：插图下载进度原地刷新（几百张图也只占一行）
  r = await evalv(`(() => {
    log('──进度测试开始──');
    logProgress('插图下载中 1/3');
    logProgress('插图下载中 2/3');
    logProgress('插图下载中 3/3');
    const lines=logBox.textContent.split('\\n').filter(x=>x.indexOf('插图下载中')>=0);
    log('──进度测试结束──');
    return {n:lines.length,last:lines[0]||'',
      ended:logBox.textContent.indexOf('──进度测试结束──')>=0,
      after:logBox.textContent.split('\\n').filter(x=>x.indexOf('插图下载中')>=0).length};
  })()`);
  ok("运行日志：插图进度只占一行且走到最后一张", r.val && r.val.n === 1
    && /3\/3/.test(r.val.last) && r.val.after === 1 && r.val.ended,
    JSON.stringify(r.err || r.val));

  // 收尾：恢复默认主题，避免影响后续人工使用
  await evalv("St.theme=Core.DEFAULT_THEME;cfgSet('theme',Core.DEFAULT_THEME);refreshThemeBtn();");

  // 9. 全部捕获的 JS 错误汇总
  ok("全程无 JS 运行时错误", errors.length === 0, errors.join(" | "));

  await send("Page.close");
  ws.close();
} catch (e) {
  console.error("冒烟运行失败：", e.message);
  process.exitCode = 1;
} finally {
  try { edge.kill(); } catch (_) {}
}
const failed = results.filter(x => x.startsWith("✗")).length;
console.log("\n冒烟结果：" + (results.length - failed) + " 通过 / " + failed + " 失败");
process.exit(failed ? 1 : 0);
