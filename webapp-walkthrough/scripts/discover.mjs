import { readFile, writeFile, mkdir } from "node:fs/promises";
import { homedir } from "node:os";

const HOME = homedir().replace(/\\/g, "/");
const ROOT = `${HOME}/ego-walkthrough`;
const WORK = await readFile(`${ROOT}/active.txt`, "utf8")
  .then((s) => s.trim().replace(/\\/g, "/"))
  .catch(() => `${ROOT}/current`);
const cfg = JSON.parse(await readFile(`${WORK}/config.json`, "utf8"));

const task = await taskSpace(`${cfg.spaceName || "walkthrough-discover"}-${Date.now()}`);
const page = task.page("p1");

const log = (m) => console.log(`[discover] ${m}`);

await page.goto(cfg.baseUrl);
await page.waitForLoadState();
await page.cdp("Page.bringToFront").catch(() => {});

if (cfg.login && cfg.login.required) {
  log("login required");
  await page.fill(cfg.login.usernameSelector, cfg.login.username);
  await page.fill(cfg.login.passwordSelector, cfg.login.password);
  await page.click(`text=${cfg.login.submitText}`, { label: "登录系统" });
  await page.waitForLoadState();
  await page.waitForTimeout(1500);
  log("logged in");
}

const menuSelector = cfg.menuSelector || "aside a, nav a, [role=menuitem]";

// 展开折叠式子菜单（Element Plus .el-sub-menu__title / Ant .ant-menu-submenu-title），
// 否则二级菜单项在发现阶段不可见会被漏掉。
if (cfg.expandSubmenus !== false) {
  try {
    const expanded = await page.evaluate(() => {
      const titles = [
        ...document.querySelectorAll(".el-sub-menu__title,.ant-menu-submenu-title"),
      ].filter((n) => n.getClientRects().length > 0);
      let count = 0;
      for (const t of titles) {
        const parent = t.closest(".el-sub-menu,.ant-menu-submenu");
        const isOpen = parent && (parent.classList.contains("is-opened") || parent.classList.contains("ant-menu-submenu-open"));
        if (!isOpen) {
          t.click();
          count += 1;
        }
      }
      return count;
    });
    if (expanded) {
      log(`expanded ${expanded} submenu(s)`);
      await page.waitForTimeout(500);
    }
  } catch (e) {
    log(`expand submenu skipped: ${e.message}`);
  }
}

const menus = await page.evaluate((sel) => {
  const seen = new Set();
  return [...document.querySelectorAll(sel)]
    .filter((n) => n.offsetParent !== null || n.getClientRects().length > 0)
    .map((n) => {
      const text = (n.textContent || "").trim().replace(/\s+/g, " ");
      const href =
        n.getAttribute("href") ||
        (n.querySelector && n.querySelector("a") && n.querySelector("a").getAttribute("href")) ||
        "";
      return { text, href };
    })
    .filter((m) => {
      if (!m.text || m.text.length > 24) return false;
      const key = m.text + "|" + m.href;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}, menuSelector);

log(`menus: ${menus.length}`);

const tabsOnPage = () =>
  page.evaluate((sel) => {
    if (!sel) return [];
    return [...document.querySelectorAll(sel)]
      .filter((n) => n.getClientRects().length > 0)
      .map((n) => (n.textContent || "").trim().replace(/\s+/g, " "));
  }, cfg.tabSelector || "");

const modules = [];
const limit = Math.min(menus.length, cfg.maxModules || 12);

for (let i = 0; i < limit; i += 1) {
  const menu = menus[i];
  const skip = (cfg.skipPaths || []).some((p) => menu.href && menu.href.includes(p));
  if (skip) {
    log(`skip ${menu.text}`);
    continue;
  }
  try {
    if (menu.href) {
      const url = menu.href.startsWith("http")
        ? menu.href
        : cfg.baseUrl.replace(/\/$/, "") + (menu.href.startsWith("/") ? menu.href : `/${menu.href}`);
      await page.goto(url);
    } else {
      await page.click(`text=${menu.text}`, { label: `进入${menu.text}` });
    }
    await page.waitForLoadState();
    await page.waitForTimeout(cfg.settleMs || 900);

    const tabs = (await tabsOnPage()).slice(0, 10);
    const labels = tabs.length ? tabs : ["默认页"];

    modules.push({
      index: modules.length,
      menuText: menu.text,
      href: await page.url(),
      tabs: labels.map((label, ti) => ({ index: ti, label })),
    });
    log(`${menu.text}: ${labels.length} tab(s) ${labels.join(" / ")}`);
  } catch (error) {
    modules.push({
      index: modules.length,
      menuText: menu.text,
      href: menu.href,
      tabs: [],
      error: String(error.message || error),
    });
    log(`FAILED ${menu.text}: ${error.message}`);
  }
}

const plan = {
  system: cfg.systemName,
  baseUrl: cfg.baseUrl,
  generatedAt: new Date().toISOString(),
  modules,
};
await mkdir(WORK, { recursive: true });
await writeFile(`${WORK}/plan.json`, JSON.stringify(plan, null, 2), "utf8");

console.log(JSON.stringify({
  ok: true,
  modules: modules.length,
  tabs: modules.reduce((n, m) => n + m.tabs.length, 0),
  plan: `${WORK}/plan.json`,
}));

await task.finish({ keep: [] });
