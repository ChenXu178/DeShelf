/* 卷帙 DeShelf Web — GitHub Pages 在线版冒烟（Edge headless + CDP，零 npm 依赖）
 * 验证 https 部署下：页面加载无 JS 报错、规则网格、双语切换、
 *       目录授权模式可用性（https 安全上下文）、About 弹窗。末尾截图。
 * 用法: node tools/smoke_web_online.mjs
 */
import { spawn } from "node:child_process";

const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const URL = "https://podcatcher962.github.io/DeShelf/web/DeShelf.html";
const PORT = 9334;
const PROFILE = (process.env.TEMP || "/tmp") + "/deshelf_online_" + Date.now();

const results = [];
function ok(name, cond, extra) {
  if (cond) { results.push("✓ " + name); console.log("  ✓ " + name); }
  else { results.push("✗ " + name); console.error("  ✗ FAIL: " + name + (extra !== undefined ? " | " + extra : "")); }
}

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
  const put = await fetch("http://127.0.0.1:" + PORT + "/json/new?" + encodeURIComponent(URL), { method: "PUT" });
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
      if (/busuanzi/i.test(txt)) return;   // 第三方访问统计脚本加载噪音，不算应用错误
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
  await sleep(3000); // 等 boot + https 加载

  console.log("— 在线版冒烟: " + URL);

  // 1. 初始渲染（https）
  let r = await evalv("({rules:document.querySelectorAll('.rule').length, h2:document.querySelector('#pane0 h2').textContent, title:document.title, proto:location.protocol})");
  ok("https 安全上下文加载", r.val && r.val.proto === "https:", JSON.stringify(r.err || r.val));
  ok("标题=卷帙 DeShelf · Web", r.val && /DeShelf/.test(r.val.title), r.err || (r.val && r.val.title));
  ok("规则网格 9 条", r.val && r.val.rules === 9, JSON.stringify(r.err || r.val));
  ok("中文面板渲染", r.val && /书库/.test(r.val.h2), r.err || (r.val && r.val.h2));
  ok("无初始化 JS 报错", errors.length === 0, errors.join(" | "));

  // 2. 目录授权模式可用性（关键：https 下 showDirectoryPicker 应存在 → 模式A可用）
  //    注意 btnScan(重新扫描) HTML 初始 disabled，须先授权目录才启用 —— 断言"初始禁用"是设计预期
  r = await evalv("({canDir:!!(window.showDirectoryPicker), pickDisabled:document.getElementById('btnPickDir').disabled, scanDisabled:document.getElementById('btnScan').disabled, hint:document.getElementById('modeHint').textContent.slice(0,40)})");
  ok("目录授权 API 可用(canDir)", r.val && r.val.canDir === true, JSON.stringify(r.err || r.val));
  ok("选文件夹主入口可用", r.val && r.val.pickDisabled === false, JSON.stringify(r.err || r.val));
  ok("重扫按钮初始禁用(设计)", r.val && r.val.scanDisabled === true, JSON.stringify(r.err || r.val));

  // 3. 语言切换
  await evalv("document.getElementById('btnLang').click()");
  await sleep(500);
  r = await evalv("({h2:document.querySelector('#pane0 h2').textContent, btn:document.getElementById('btnLang').textContent})");
  ok("切到英文界面", r.val && /Library/i.test(r.val.h2), JSON.stringify(r.err || r.val));
  await evalv("document.getElementById('btnLang').click()");
  await sleep(300);

  // 4. About 弹窗（弹窗标题在 .dlg .dh）
  r = await evalv("(async()=>{document.getElementById('btnAbout').click();await new Promise(r2=>setTimeout(r2,300));const t=document.querySelector('.dlg .dh');const v=t?t.textContent:'';const c=document.querySelector('.dlg .x');if(c)c.click();return v;})()");
  ok("关于弹窗可开可关", r.val && /卷帙|DeShelf/.test(r.val), JSON.stringify(r.err || r.val));

  // 5. 截图（复用 _ui_shot.png 名以匹配 .gitignore）
  await evalv("document.querySelectorAll('.step')[0] ? null : null");
  const shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot.result && shot.result.data) {
    const fs = await import("node:fs");
    fs.writeFileSync("web/_ui_shot.png", Buffer.from(shot.result.data, "base64"));
    ok("在线首屏截图已存", true);
  } else { ok("在线首屏截图已存", false, JSON.stringify(shot.err || {})); }

  const fail = results.filter(r2 => r2.startsWith("✗")).length;
  console.log("结果: " + (results.length - fail) + "/" + results.length + " 通过");
  process.exitCode = fail ? 1 : 0;
} catch (e) {
  console.error("冒烟异常:", e.message);
  process.exitCode = 1;
} finally {
  edge.kill();
}
