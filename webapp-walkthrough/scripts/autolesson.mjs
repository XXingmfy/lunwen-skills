import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";

const HOME = homedir().replace(/\\/g, "/");
const ROOT = `${HOME}/ego-walkthrough`;
const WORK = await readFile(`${ROOT}/active.txt`, "utf8")
  .then((s) => s.trim().replace(/\\/g, "/"))
  .catch(() => `${ROOT}/current`);
const cfg = JSON.parse((await readFile(`${WORK}/config.json`, "utf8")).replace(/^\uFEFF/, ""));
const task = await taskSpace(`autolesson-${Date.now()}`);
const page = task.page("p1");
const log = (m) => console.log(`[autolesson] ${m}`);

await page.goto(cfg.baseUrl);
await page.waitForLoadState().catch(() => {});
await page.waitForTimeout(900);

// 清掉可能残留的登录态，确保能看到并录制登录流程（ego 专用 profile，不影响用户浏览器）
await page.evaluate(() => {
  try {
    localStorage.clear();
    sessionStorage.clear();
  } catch (e) {}
}).catch(() => {});
await page.reload().catch(() => {});
await page.waitForLoadState().catch(() => {});
await page.waitForTimeout(900);

const needLogin = await page.evaluate(() => !!document.querySelector("input[type=password]"));
if (needLogin) {
  const user = (cfg.autoLogin && cfg.autoLogin.username) || "admin";
  const pass = (cfg.autoLogin && cfg.autoLogin.password) || "123456";
  const marks = await page.evaluate(() => {
    const vis = (n) => n.getClientRects().length > 0;
    const inputs = [...document.querySelectorAll("input")].filter(vis);
    const pwd = inputs.find((i) => i.type === "password");
    const usr = inputs.find((i) => i.type !== "password");
    const out = {};
    let k = 0;
    const mark = (el) => {
      k += 1;
      el.setAttribute("data-lg", String(k));
      return String(k);
    };
    if (usr) out.usr = mark(usr);
    if (pwd) out.pwd = mark(pwd);
    const btns = [...document.querySelectorAll("button,.el-button,[role=button]")].filter(vis);
    const b = btns.find((x) => /登\s*录|登录|sign\s*in|login/i.test(x.textContent || "")) || btns[0];
    if (b) out.btn = mark(b);
    return out;
  });
  if (marks.usr) await page.fill(`[data-lg="${marks.usr}"]`, user);
  if (marks.pwd) await page.fill(`[data-lg="${marks.pwd}"]`, pass);
  if (marks.btn) await page.click(`[data-lg="${marks.btn}"]`, { label: "登录" });
  await page.waitForTimeout(2200);
  log("login attempted");
}

// 展开折叠子菜单
await page.evaluate(() => {
  const t = [...document.querySelectorAll(".el-sub-menu__title,.ant-menu-submenu-title")].filter(
    (n) => n.getClientRects().length > 0
  );
  for (const x of t) {
    const p = x.closest(".el-sub-menu,.ant-menu-submenu");
    const open = p && (p.classList.contains("is-opened") || p.classList.contains("ant-menu-submenu-open"));
    if (!open) x.click();
  }
});
await page.waitForTimeout(700);

const menus = await page.evaluate(() => {
  const vis = (n) => n.getClientRects().length > 0;
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const nodes = [
    ...document.querySelectorAll("aside .el-menu-item, aside a, nav a, .el-menu-item"),
  ].filter(vis);
  const out = [];
  const seen = new Set();
  for (const n of nodes) {
    const text = norm(n.textContent);
    if (!text || text.length > 24) continue;
    if (/退出|登出|注销|帮助/.test(text)) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    out.push({ text, href: n.getAttribute("href") || "" });
  }
  return out;
});
log(`menus: ${menus.length}`);

const items = [];
for (const m of menus) {
  try {
    const mark = await page.evaluate(({ text }) => {
      const vis = (n) => n.getClientRects().length > 0;
      const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
      const nodes = [
        ...document.querySelectorAll("aside .el-menu-item, aside a, nav a, .el-menu-item"),
      ]
        .filter(vis)
        .filter((n) => norm(n.textContent) === text);
      if (!nodes.length) return null;
      window.__al = (window.__al || 0) + 1;
      const k = String(window.__al);
      nodes[0].setAttribute("data-al", k);
      return k;
    }, { text: m.text });
    if (!mark) {
      items.push({ title: m.text, url: "", error: "not found" });
      continue;
    }
    await page.click(`[data-al="${mark}"]`, { label: "进入" + m.text });
    await page.waitForTimeout(1100);
    const info = await page.evaluate(() => {
      const vis = (n) => n.getClientRects().length > 0;
      const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
      const titleEl = document.querySelector(".page-title,h1,h2");
      const buttons = [...document.querySelectorAll("button,.el-button")]
        .filter(vis)
        .map((b) => norm(b.textContent))
        .filter(Boolean)
        .slice(0, 10);
      const tables = [...document.querySelectorAll("table")]
        .filter(vis)
        .map((t) => t.querySelectorAll("tbody tr").length);
      return { url: location.href, pageTitle: titleEl ? norm(titleEl.textContent) : "", buttons, tables };
    });
    items.push({ title: m.text, ...info });
    log(`${m.text} -> ${info.url}`);
  } catch (e) {
    items.push({ title: m.text, url: "", error: String(e.message || e) });
  }
}

await writeFile(
  `${WORK}/discover.json`,
  JSON.stringify({ baseUrl: cfg.baseUrl, needLogin, items }, null, 2),
  "utf8"
);
console.log(JSON.stringify({ ok: true, count: items.length, file: `${WORK}/discover.json` }));
await task.finish({ keep: [] });
