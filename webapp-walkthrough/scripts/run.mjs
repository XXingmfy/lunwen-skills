import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import { homedir } from "node:os";

const HOME = homedir().replace(/\\/g, "/");
const ROOT = `${HOME}/ego-walkthrough`;
const WORK = await readFile(`${ROOT}/active.txt`, "utf8")
  .then((s) => s.trim().replace(/\\/g, "/"))
  .catch(() => `${ROOT}/current`);
const RUN = `${WORK}/run`;
const FRAMES = `${RUN}/frames`;
const SHOTS = `${RUN}/shots`;

const cfg = JSON.parse(await readFile(`${WORK}/config.json`, "utf8"));
const readMaybe = async (p) => {
  try {
    return JSON.parse(await readFile(p, "utf8"));
  } catch {
    return null;
  }
};
const lesson = await readMaybe(`${WORK}/lesson.json`);
const plan = await readMaybe(`${WORK}/plan.json`);

await rm(RUN, { recursive: true, force: true });
await mkdir(FRAMES, { recursive: true });
await mkdir(SHOTS, { recursive: true });

const task = await taskSpace(`${cfg.spaceName || "walkthrough-run"}-${Date.now()}`);
const page = task.page("p1");

const log = (m) => console.log(`[run] ${m}`);
const BASE = (lesson?.baseUrl || cfg.baseUrl || "").replace(/\/$/, "");
const VW = lesson?.viewport?.width || cfg.recorder?.width || 1440;
const VH = lesson?.viewport?.height || cfg.recorder?.height || 860;
const settle = cfg.settleMs || 900;

const absUrl = (u) => {
  if (!u) return BASE;
  if (/^https?:\/\//.test(u)) return u;
  return BASE + (u.startsWith("/") ? u : `/${u}`);
};

/* ------------------------------------------------------------------ *
 * 录制底座：定时 Page.captureScreenshot 抽帧（按变化去重，稳定可靠）
 * ------------------------------------------------------------------ */
const state = { t0: Date.now(), frames: 0, frameIndex: [], lastHash: null };

async function captureOnce() {
  try {
    const r = await page.cdp("Page.captureScreenshot", {
      format: "jpeg",
      quality: cfg.recorder?.jpegQuality || 70,
    });
    if (!r || !r.data) return;
    const buf = Buffer.from(r.data, "base64");
    const h = createHash("md5").update(buf).digest("hex");
    if (h === state.lastHash) return;
    state.lastHash = h;
    state.frames += 1;
    const name = `f${String(state.frames).padStart(6, "0")}.jpg`;
    await writeFile(`${FRAMES}/${name}`, buf);
    state.frameIndex.push({ t: Date.now() - state.t0, file: `frames/${name}`, w: VW, h: VH });
  } catch (e) {
    /* 导航中等瞬时失败忽略 */
  }
}

async function hold(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    await captureOnce();
    const remain = end - Date.now();
    if (remain <= 0) break;
    await page.waitForTimeout(Math.min(170, remain));
  }
}

/* ------------------------------------------------------------------ *
 * 教学层：光标 / 元素高亮 / 点击涟漪 / 章节卡 / 字幕条
 * ------------------------------------------------------------------ */
async function injectOverlay() {
  await page.evaluate(() => {
    if (document.getElementById("wt-ui")) return;
    const style = document.createElement("style");
    style.id = "wt-ui-style";
    style.textContent = `
      #wt-ui{position:fixed;inset:0;pointer-events:none;z-index:2147483600;font-family:'Microsoft YaHei','PingFang SC',sans-serif;}
      #wt-lower{position:absolute;left:26px;bottom:26px;display:flex;align-items:center;gap:14px;background:linear-gradient(90deg,rgba(15,23,42,.95),rgba(37,99,235,.90));color:#fff;padding:13px 20px;border-radius:14px;box-shadow:0 10px 34px rgba(0,0,0,.42);max-width:74%;}
      #wt-chap{background:#fff;color:#1d4ed8;font-weight:700;font-size:14px;padding:6px 12px;border-radius:10px;white-space:nowrap;}
      #wt-step{font-size:19px;font-weight:700;line-height:1.25;max-width:54vw;}
      #wt-sub{font-size:12.5px;opacity:.85;margin-top:5px;}
      #wt-tips{margin-top:6px;font-size:12.5px;color:#fde68a;}
      #wt-cursor{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;background:rgba(37,99,235,.30);border:3px solid #2563eb;box-shadow:0 0 0 6px rgba(37,99,235,.18);transition:left .22s ease,top .22s ease;display:none;}
      #wt-hl{position:absolute;border:2px dashed #f59e0b;border-radius:9px;box-shadow:0 0 0 4px rgba(245,158,11,.20),0 0 26px rgba(245,158,11,.55);display:none;}
      #wt-card{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:radial-gradient(1200px 620px at 50% 38%,rgba(37,99,235,.45),rgba(8,12,26,.95));}
      #wt-card-inner{text-align:center;color:#fff;}
      #wt-card-no{font-size:19px;letter-spacing:8px;color:#93c5fd;font-weight:700;}
      #wt-card-title{font-size:46px;font-weight:800;margin:16px 0 12px;}
      #wt-card-sum{font-size:18px;color:#cbd5e1;max-width:70vw;line-height:1.55;}
      #wt-ripple{position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:#f59e0b;opacity:0;display:none;}
    `;
    document.head.appendChild(style);
    const ui = document.createElement("div");
    ui.id = "wt-ui";
    ui.innerHTML = `
      <div id="wt-card"><div id="wt-card-inner">
        <div id="wt-card-no"></div><div id="wt-card-title"></div><div id="wt-card-sum"></div>
      </div></div>
      <div id="wt-hl"></div>
      <div id="wt-ripple"></div>
      <div id="wt-cursor"></div>
      <div id="wt-lower"><div id="wt-chap"></div>
        <div><div id="wt-step"></div><div id="wt-sub"></div><div id="wt-tips"></div></div>
      </div>`;
    document.body.appendChild(ui);
  });
}

async function setLowerThird(chapNo, chapTitle, stepTitle, idx, total, tips) {
  await page.evaluate(
    (a) => {
      const q = (id) => document.getElementById(id);
      if (!q("wt-ui")) return;
      q("wt-lower").style.display = "flex";
      q("wt-chap").textContent = "第 " + a.chapNo + " 章";
      q("wt-step").textContent = a.stepTitle || "";
      q("wt-sub").textContent = (a.chapTitle || "") + " · 功能点 " + a.idx + " / " + a.total;
      q("wt-tips").textContent = a.tips ? "💡 " + a.tips : "";
    },
    { chapNo, chapTitle, stepTitle, idx, total, tips: tips || "" }
  );
}

async function showChapterCard(chapNo, chapTitle, summary, totalChapters) {
  await page.evaluate(
    (a) => {
      const q = (id) => document.getElementById(id);
      if (!q("wt-ui")) return;
      q("wt-lower").style.display = "none";
      q("wt-card-no").textContent = "第 " + a.chapNo + " 章 / 共 " + a.total + " 章";
      q("wt-card-title").textContent = a.title || "";
      q("wt-card-sum").textContent = a.summary || "";
      q("wt-card").style.display = "flex";
    },
    { chapNo, title: chapTitle, summary, total: totalChapters }
  );
}

async function hideChapterCard() {
  await page.evaluate(() => {
    const c = document.getElementById("wt-card");
    if (c) c.style.display = "none";
    const l = document.getElementById("wt-lower");
    if (l) l.style.display = "flex";
  });
}

async function moveCursor(r) {
  await page.evaluate(
    (a) => {
      const c = document.getElementById("wt-cursor");
      if (!c) return;
      c.style.display = "block";
      c.style.left = a.x + "px";
      c.style.top = a.y + "px";
    },
    { x: r.x, y: r.y }
  );
}

async function highlightRect(r) {
  await page.evaluate(
    (a) => {
      const h = document.getElementById("wt-hl");
      if (!h) return;
      h.style.display = "block";
      h.style.left = a.left - 6 + "px";
      h.style.top = a.top - 6 + "px";
      h.style.width = a.width + 12 + "px";
      h.style.height = a.height + 12 + "px";
    },
    { left: r.left, top: r.top, width: r.width, height: r.height }
  );
}

async function clearHighlight() {
  await page.evaluate(() => {
    const h = document.getElementById("wt-hl");
    if (h) h.style.display = "none";
  });
}

async function clickRipple(r) {
  await page.evaluate(
    (a) => {
      const el = document.getElementById("wt-ripple");
      if (!el) return;
      el.style.display = "block";
      el.style.left = a.x + "px";
      el.style.top = a.y + "px";
      el.style.transition = "none";
      el.style.transform = "scale(.4)";
      el.style.opacity = ".95";
      requestAnimationFrame(() => {
        el.style.transition = "transform .55s ease, opacity .55s ease";
        el.style.transform = "scale(3.4)";
        el.style.opacity = "0";
      });
    },
    { x: r.x, y: r.y }
  );
}

async function findRect(spec) {
  return await page.evaluate((spec) => {
    const vis = (n) => n && n.getClientRects().length > 0 && n.offsetParent !== null;
    const norm = (s) => (s || "").replace(/\s+/g, "").toLowerCase();
    let n = null;
    if (spec.selector) {
      n = [...document.querySelectorAll(spec.selector)].filter(vis)[0] || null;
    } else if (spec.firstInput) {
      n =
        [...document.querySelectorAll("input[type=text],input:not([type]),textarea")].filter(vis)[0] ||
        null;
    } else if (spec.text) {
      const all = [
        ...document.querySelectorAll(
          "button,.el-button,[role=button],a,.el-menu-item,.el-sub-menu__title,.el-tabs__item,.el-select,.el-input,label,span,div"
        ),
      ].filter(vis);
      const t = norm(spec.text);
      n =
        all.find((x) => norm(x.textContent) === t) ||
        all.find((x) => norm(x.textContent).includes(t) && x.querySelectorAll("*").length <= 6) ||
        null;
    }
    if (!n) return null;
    const r = n.getBoundingClientRect();
    return {
      x: r.left + r.width / 2,
      y: r.top + r.height / 2,
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
      tag: n.tagName,
      text: (n.textContent || "").trim().slice(0, 40),
    };
  }, spec);
}

/* ------------------------------------------------------------------ *
 * 页面结构提取（写入 steps.jsonl，供讲解/清单使用）
 * ------------------------------------------------------------------ */
const extract = () =>
  page.evaluate(() => {
    const text = (n) => (n.textContent || "").trim().replace(/\s+/g, " ");
    const visible = (n) => n.getClientRects().length > 0;
    return {
      title: document.title,
      heads: [...document.querySelectorAll("h1,h2,.page-title")]
        .filter(visible)
        .map(text)
        .slice(0, 4),
      tables: [...document.querySelectorAll("table")].filter(visible).map((t) => ({
        cols: [...t.querySelectorAll("thead th")].map(text).slice(0, 8),
        rows: t.querySelectorAll("tbody tr").length,
      })),
      kpis: [...document.querySelectorAll(".stat-card,.kpi,.metric")]
        .filter(visible)
        .map(text)
        .slice(0, 8),
      fields: [...document.querySelectorAll("input,select,textarea")]
        .filter(visible)
        .map((i) => i.getAttribute("placeholder") || i.name || i.id || i.type)
        .slice(0, 8),
      buttons: [...document.querySelectorAll("button,.el-button")]
        .filter(visible)
        .map(text)
        .filter(Boolean)
        .slice(0, 12),
      bodyLen: (document.body.innerText || "").trim().length,
    };
  });

/* ------------------------------------------------------------------ *
 * 动作执行
 * ------------------------------------------------------------------ */
async function doAction(act, rec) {
  if (act.type === "goto") {
    await page.goto(absUrl(act.url));
    await page.waitForLoadState();
    await page.waitForTimeout(act.ms || 500);
    await injectOverlay();
  } else if (act.type === "fill") {
    const spec = act.selector ? { selector: act.selector } : { firstInput: true };
    const r = await findRect(spec);
    if (r) {
      await moveCursor(r);
      await highlightRect(r);
    }
    const sel = act.selector || "input[type=text],input:not([type]),textarea";
    const val = String(act.value == null ? "" : act.value);
    await page.fill(sel, "");
    if (val.length > 44) {
      await page.fill(sel, val);
    } else {
      for (const ch of val) {
        await page.keyboard.type(ch);
        await hold(55);
      }
    }
    rec.filled = { field: act.selector || "input", value: val };
    await hold(280);
  } else if (act.type === "click") {
    const findSpec = act.findSelector
      ? { selector: act.findSelector }
      : act.text
        ? { text: act.text }
        : { selector: act.selector };
    const r = await findRect(findSpec);
    if (r) {
      await moveCursor(r);
      await highlightRect(r);
      await clickRipple(r);
    }
    await page.click(act.text ? `text=${act.text}` : act.selector, {
      label: act.label || "点击" + (act.text || ""),
    });
    rec.clicked = act.text || act.selector;
    await page.waitForTimeout(act.ms || settle);
  } else if (act.type === "press") {
    await page.keyboard.press(act.key);
    await hold(act.ms || 400);
  } else if (act.type === "hover") {
    const spec = act.text ? { text: act.text } : { selector: act.selector };
    const r = await findRect(spec);
    if (r) await moveCursor(r);
    await page.hover(act.text ? `text=${act.text}` : act.selector, { label: "悬停查看" });
    await hold(act.ms || 400);
  } else if (act.type === "scroll") {
    await page.mouse.wheel(0, act.dy || 600, { label: "向下浏览" });
    await hold(act.ms || 500);
  } else if (act.type === "wait") {
    await hold(act.ms || 700);
  }
}

/* ------------------------------------------------------------------ *
 * 启动录制底座
 * ------------------------------------------------------------------ */
await page.goto(BASE || cfg.baseUrl);
await page.waitForLoadState();
await page.cdp("Page.bringToFront").catch(() => {});
await page
  .cdp("Emulation.setDeviceMetricsOverride", {
    width: VW,
    height: VH,
    deviceScaleFactor: 1,
    mobile: false,
  })
  .catch(() => {});

const steps = [];

/* ================================================================== *
 * 模式 A：教学脚本（lesson.json）
 * ================================================================== */
if (lesson && Array.isArray(lesson.chapters) && lesson.chapters.length) {
  const featureTotal = lesson.chapters.reduce(
    (n, c) => n + (c.steps || []).filter((s) => s.kind !== "card").length,
    0
  );
  let featureDone = 0;
  const cardMs = lesson.cardMs || 2100;
  log(`teaching mode: ${lesson.chapters.length} chapters / ${featureTotal} feature points`);

  for (let ci = 0; ci < lesson.chapters.length; ci += 1) {
    const chapter = lesson.chapters[ci];
    const chapNo = ci + 1;
    const firstUrlStep = (chapter.steps || []).find((s) => s.url);

    // 章节卡：先导航到本章首个页面做背景，再盖章节卡
    if (chapter.card !== false) {
      try {
        if (firstUrlStep) {
          await page.goto(absUrl(firstUrlStep.url));
          await page.waitForLoadState();
          await page.waitForTimeout(350);
        }
        await injectOverlay();
      } catch (e) {
        /* 背景导航失败不影响章节卡 */
      }
      const tCard = Date.now() - state.t0;
      await showChapterCard(chapNo, chapter.title, chapter.summary || "", lesson.chapters.length);
      await hold(cardMs);
      await hideChapterCard();
      let curl = "";
      try {
        curl = await page.url();
      } catch {}
      steps.push({
        i: steps.length + 1,
        chapter: chapter.title,
        chapterNo: chapNo,
        module: chapter.title,
        tab: "",
        title: "本章导览",
        card: true,
        narration: chapter.summary || `接下来进入第${chapNo}章，${chapter.title}。`,
        t: tCard,
        dur: Date.now() - state.t0 - tCard,
        url: curl,
        content: null,
        issues: [],
      });
      log(`chapter ${chapNo} card: ${chapter.title}`);
    }

    for (const st of chapter.steps || []) {
      if (st.kind === "card") continue;
      featureDone += 1;
      const relStart = Date.now() - state.t0;
      const rec = {
        i: steps.length + 1,
        chapter: chapter.title,
        chapterNo: chapNo,
        module: chapter.title,
        tab: st.title || "",
        title: st.title || "",
        narration: st.narration || "",
        tips: st.tips || "",
        card: false,
        t: relStart,
        dur: 0,
        url: "",
        content: null,
        filled: null,
        clicked: null,
        shot: null,
        issues: [],
      };
      try {
        if (st.url) {
          await page.goto(absUrl(st.url));
          await page.waitForLoadState();
          await page.waitForTimeout(st.settleMs || settle);
        }
        await injectOverlay();
        await setLowerThird(chapNo, chapter.title, st.title || "", featureDone, featureTotal, st.tips);

        for (const act of st.actions || []) {
          await doAction(act, rec);
        }
        await clearHighlight();
        if (st.highlight) {
          const r = await findRect(st.highlight);
          if (r) {
            await moveCursor(r);
            await highlightRect(r);
          }
        }
        await hold(st.holdMs || settle);
        rec.content = await extract();

        const shotName = `s${String(steps.length + 1).padStart(3, "0")}.png`;
        await page.screenshot({ path: `${SHOTS}/${shotName}` });
        rec.shot = `shots/${shotName}`;

        if (rec.content && rec.content.bodyLen < 80) {
          rec.issues.push({ level: "error", msg: "页面正文内容过少，疑似白屏" });
        }
      } catch (error) {
        rec.issues.push({ level: "error", msg: String(error.message || error).slice(0, 300) });
        log(`step failed ${chapter.title}/${st.title}: ${error.message}`);
      }
      rec.dur = Date.now() - state.t0 - relStart;
      try {
        rec.url = await page.url();
      } catch {}
      steps.push(rec);
      log(`${chapter.title}/${st.title} ${rec.dur}ms issues=${rec.issues.length}`);
    }
  }
} else if (plan && Array.isArray(plan.modules)) {
  /* ================================================================ *
   * 模式 B：旧版自动走查（plan.json，向后兼容）
   * ================================================================ */
  if (cfg.login && cfg.login.required) {
    log("login");
    await page.fill(cfg.login.usernameSelector, cfg.login.username);
    await page.fill(cfg.login.passwordSelector, cfg.login.password);
    await page.click(`text=${cfg.login.submitText}`, { label: "登录系统" });
    await page.waitForLoadState();
    await page.waitForTimeout(1200);
  }

  async function clickByText(label, kind = "button") {
    const picked = await page.evaluate(
      ({ label, kind }) => {
        const sel =
          kind === "tab" ? ".tab,[role=tab],.el-tabs__item,.ant-tabs-tab" : "button,.btn,[role=button]";
        const nodes = [...document.querySelectorAll(sel)].filter(
          (n) => n.getClientRects().length > 0 && (n.textContent || "").trim().replace(/\s+/g, " ") === label
        );
        if (!nodes.length) return null;
        window.__wt = (window.__wt || 0) + 1;
        const mark = String(window.__wt);
        nodes[0].setAttribute("data-wt", mark);
        nodes[0].scrollIntoView({ block: "center", inline: "center" });
        return { mark, text: (nodes[0].textContent || "").trim() };
      },
      { label, kind }
    );
    if (!picked) return null;
    await page.click(`[data-wt="${picked.mark}"]`, { label: kind === "tab" ? `切换${label}` : `点击${label}` });
    return picked.text;
  }

  async function fillFirstInput(value) {
    const hit = await page.evaluate(() => {
      const nodes = [...document.querySelectorAll("input[type=text],input:not([type]),textarea")].filter(
        (n) => n.getClientRects().length > 0 && !n.readOnly && !n.disabled
      );
      if (!nodes.length) return null;
      window.__wt = (window.__wt || 0) + 1;
      const mark = String(window.__wt);
      nodes[0].setAttribute("data-wt", mark);
      nodes[0].scrollIntoView({ block: "center", inline: "center" });
      return { mark, name: nodes[0].getAttribute("placeholder") || nodes[0].name || "input" };
    });
    if (!hit) return null;
    await page.click(`[data-wt="${hit.mark}"]`, { label: "聚焦查询框" });
    if (cfg.humanize === false) {
      await page.fill(`[data-wt="${hit.mark}"]`, value);
      return hit.name;
    }
    for (const ch of value) {
      await page.keyboard.type(ch);
      await hold(80);
    }
    return hit.name;
  }

  const safeButtons = cfg.safeButtons || ["查询", "搜索"];
  const denyButtons = cfg.denyButtons || ["删除", "登出", "退出"];
  log(`modules: ${plan.modules.length}`);

  for (const mod of plan.modules) {
    if (mod.error) {
      steps.push({
        i: steps.length + 1,
        module: mod.menuText,
        tab: "",
        title: mod.menuText,
        t: Date.now() - state.t0,
        dur: 0,
        url: mod.href || "",
        content: null,
        issues: [{ level: "error", msg: `入口打开失败: ${mod.error}` }],
      });
      continue;
    }
    const tabs = mod.tabs.length ? mod.tabs : [{ index: 0, label: "默认页" }];
    for (const tab of tabs) {
      const relStart = Date.now() - state.t0;
      const step = {
        i: steps.length + 1,
        module: mod.menuText,
        tab: tab.label,
        title: tab.label,
        t: relStart,
        dur: 0,
        url: mod.href,
        content: null,
        filled: null,
        clicked: null,
        shot: null,
        issues: [],
      };
      try {
        if (tab.index === 0) {
          await page.goto(mod.href);
          await page.waitForLoadState();
        } else {
          const hit = await clickByText(tab.label, "tab");
          if (!hit) step.issues.push({ level: "warn", msg: `未找到选项卡「${tab.label}」` });
        }
        await hold(settle);
        step.content = await extract();

        const query = (cfg.queryByModule && cfg.queryByModule[mod.menuText]) || cfg.testQuery || "E2E演示";
        const field = await fillFirstInput(query);
        if (field) {
          step.filled = { field, value: query };
          await hold(400);
          let target = null;
          for (const label of safeButtons) {
            if (denyButtons.includes(label)) continue;
            target = await clickByText(label);
            if (target) break;
          }
          step.clicked = target || null;
          if (target) await hold(settle);
        }
        const shotName = `s${String(steps.length + 1).padStart(3, "0")}.png`;
        await page.screenshot({ path: `${SHOTS}/${shotName}` });
        step.shot = `shots/${shotName}`;
        if (step.content && step.content.bodyLen < 80) {
          step.issues.push({ level: "error", msg: "页面正文内容过少，疑似白屏" });
        }
      } catch (error) {
        step.issues.push({ level: "error", msg: String(error.message || error).slice(0, 300) });
        log(`step failed ${mod.menuText}/${tab.label}: ${error.message}`);
      }
      step.dur = Date.now() - state.t0 - relStart;
      try {
        step.url = await page.url();
      } catch {}
      steps.push(step);
      log(`${mod.menuText}/${tab.label} ${step.dur}ms issues=${step.issues.length}`);
    }
  }
} else {
  throw new Error("既没有 lesson.json（教学脚本），也没有 plan.json（走查计划）");
}

/* ------------------------------------------------------------------ *
 * 收尾 + 落盘
 * ------------------------------------------------------------------ */
await hold(700);
await page.cdp("Emulation.clearDeviceMetricsOverride").catch(() => {});

const chapterCount = lesson?.chapters?.length || new Set(steps.map((s) => s.module)).size;
const featureCount = lesson
  ? lesson.chapters.reduce((n, c) => n + (c.steps || []).filter((s) => s.kind !== "card").length, 0)
  : steps.length;

const meta = {
  system: cfg.systemName || lesson?.systemName || "系统演示",
  baseUrl: BASE || cfg.baseUrl,
  mode: lesson ? "teaching" : "walkthrough",
  startedAt: new Date(state.t0).toISOString(),
  endedAt: new Date().toISOString(),
  totalMs: Date.now() - state.t0,
  frameCount: state.frames,
  moduleCount: chapterCount,
  chapterCount,
  featureCount,
  tabCount: steps.length,
  issueCount: steps.reduce((n, s) => n + s.issues.filter((i) => i.level === "error").length, 0),
  workdir: RUN,
};

await writeFile(`${RUN}/frames/index.json`, JSON.stringify({ frames: state.frameIndex }, null, 2), "utf8");
await writeFile(`${RUN}/steps.jsonl`, steps.map((s) => JSON.stringify(s)).join("\n"), "utf8");
await writeFile(`${RUN}/meta.json`, JSON.stringify(meta, null, 2), "utf8");
if (lesson) await writeFile(`${RUN}/lesson.used.json`, JSON.stringify(lesson, null, 2), "utf8");

console.log(
  JSON.stringify({
    ok: true,
    mode: meta.mode,
    frames: meta.frameCount,
    steps: meta.tabCount,
    chapters: chapterCount,
    features: featureCount,
    durationSec: +(meta.totalMs / 1000).toFixed(1),
    issues: meta.issueCount,
    workdir: RUN,
  })
);

await task.finish({ keep: [] });
