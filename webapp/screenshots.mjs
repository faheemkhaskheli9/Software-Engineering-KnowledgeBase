// Regenerate the web app guide's screenshots from the real app.
//
//   node webapp/screenshots.mjs            (needs Node 18+ and the playwright package)
//
// Starts server.py on a free port against this repo, drives it in headless Chromium and writes PNGs
// to config.json's "screenshots.out" folder. It creates one scratch file (deleted at the end) and runs
// the first header action, so start from a clean, committed working tree: the "Changes" shots list
// every uncommitted file.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const CFG = JSON.parse(fs.readFileSync(path.join(HERE, "config.json"), "utf8"));
const S = CFG.screenshots || {};
const OUT = process.env.SHOTS_OUT || path.join(ROOT, S.out || "docs/screenshots");  // SHOTS_OUT: a trial run elsewhere
const PREFIX = S.prefix || "";
const SCRATCH = S.scratch || "scratch-note.md";

// playwright is usually installed globally (npm i -g playwright); a local install works too.
async function loadPlaywright() {
  try { return await import("playwright"); } catch (e) { /* try the global one */ }
  const { execSync } = await import("node:child_process");
  const global = path.join(execSync("npm root -g").toString().trim(), "playwright", "index.mjs");
  try { return await import(global); } catch (e) {
    throw new Error("playwright not found: npm i -g playwright && npx playwright install chromium");
  }
}
const freePort = () => new Promise((ok) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => ok(p)); }); });

const { chromium } = await loadPlaywright();
const port = await freePort();
const py = process.platform === "win32" ? "python" : "python3";
const srv = spawn(py, [path.join(HERE, "server.py"), "--port", String(port)], {stdio: "ignore"});
const base = `http://localhost:${port}/`;
for (let i = 0; i < 50; i++) { try { await fetch(base + "api/config"); break; } catch (e) { await new Promise((r) => setTimeout(r, 100)); } }

const exe = ["/opt/pw-browsers/chromium", process.env.CHROMIUM_PATH].find((p) => p && fs.existsSync(p) && fs.statSync(p).isFile());
const browser = await chromium.launch(exe ? {executablePath: exe} : {});
const ctx = await browser.newContext({viewport: {width: 1400, height: 860}, colorScheme: "light", deviceScaleFactor: 1});
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
let answer = "";
page.on("dialog", (d) => d.accept(d.type() === "prompt" ? answer : undefined));
// Shots go to a temp folder first, so the Changes shots do not list half-written PNGs.
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "kb-shots-"));
const taken = [];
const shot = async (name, opts = {}) => {
  await page.waitForTimeout(350);
  await page.screenshot({path: path.join(TMP, PREFIX + name + ".png"), ...opts});
  taken.push(PREFIX + name + ".png");
};
const go = async (hash) => { await page.goto(base + hash); await page.waitForTimeout(700); };
const scratchFull = path.join(ROOT, SCRATCH);

try {
  if (fs.existsSync(scratchFull)) throw new Error(SCRATCH + " already exists; remove it first");
  // Visit a few files so the start page has a "Recently opened" list.
  for (const p of [...(S.recent || []), S.sample].filter(Boolean)) await go("#/" + p);
  await go("#");
  await shot("home");

  await go("#/" + S.sample);
  await shot("file");
  await page.evaluate(() => { const v = document.getElementById("view"); v.scrollTop = v.scrollHeight; });
  await shot("backlinks");
  if (await page.locator(".fm summary").count()) {
    await go("#/" + S.sample);
    await page.click(".fm summary");
    await shot("frontmatter");
  }
  await go("#/" + S.sample);
  const tocLinks = page.locator("#toc a");
  if (await tocLinks.count() > 2) { await tocLinks.nth(2).click(); await page.waitForTimeout(150); await shot("outline"); }

  await go("#");
  await page.fill("#filter", S.filter || "a");
  await shot("filter");
  await page.fill("#filter", "");

  await page.fill("#search", S.search || "the");
  await page.press("#search", "Enter");
  await page.waitForTimeout(600);
  await shot("search");

  // Edit with the live preview, then drop the edit without saving.
  await go("#/" + S.sample);
  await page.click("#toggle");
  await page.click("#preview");
  // Edit the first "# " heading line, so the preview shows the change at the top.
  await page.evaluate(() => {
    const e = document.getElementById("editor"), m = e.value.match(/^# .*$/m);
    const at = m ? m.index + m[0].length : 0;
    e.setSelectionRange(at, at); e.blur(); e.focus();
  });
  await page.keyboard.type(" (edited)");
  await page.waitForTimeout(500);
  await shot("edit-preview");
  await page.evaluate("dirty = false");

  // A scratch file: create from the template, save, conflict, review the diff, delete.
  answer = SCRATCH;
  await go("#");
  await page.click("#new");
  await page.waitForTimeout(800);
  await shot("new-file");
  await page.evaluate(() => { const e = document.getElementById("editor"); e.setSelectionRange(e.value.length, e.value.length); });
  await page.keyboard.type("\nA scratch note to show saving.\n");
  await page.keyboard.press("Control+s");
  await shot("edit-saved");
  await page.keyboard.type("Another line.\n");
  const t = new Date(Date.now() + 5000);
  fs.utimesSync(scratchFull, t, t);  // as if another editor saved it
  await page.keyboard.press("Control+s");
  await shot("conflict");
  await page.click("#takedisk");
  await page.waitForTimeout(500);

  await go("#changes");
  await shot("changes");
  await go("#diff/" + SCRATCH);
  await shot("diff");
  await go("#/" + SCRATCH);
  await page.click("#del");
  await page.waitForTimeout(500);

  const actions = page.locator("#actions button");
  if (await actions.count()) {
    await go("#");
    await actions.first().click();
    await page.waitForSelector("#out[open]", {timeout: 120000});
    await shot("action");
    await page.click("#out-close");
  }

  await go("#/" + S.sample);
  await page.click("#menu");
  await shot("sidebar-hidden");
  await page.click("#menu");

  await page.click("#theme");  // follow system -> light
  await page.click("#theme");  // light -> dark
  await go("#/" + S.sample);
  await shot("dark");
  await page.click("#theme");  // back to follow system

  // Repo-specific pages: "extra": [{"name": "glossary", "path": "glossary.md"}, ...]
  for (const x of S.extra || []) { await go("#/" + x.path); await shot(x.name); }

  await page.setViewportSize({width: 390, height: 800});
  await page.reload();
  await go("#/" + S.sample);
  await shot("narrow");
  await page.click("#menu");
  await shot("narrow-menu");
  if (errors.length) throw new Error("page errors: " + errors.join("; "));
  fs.mkdirSync(OUT, {recursive: true});
  for (const f of taken) {
    fs.copyFileSync(path.join(TMP, f), path.join(OUT, f));
    console.log("wrote", path.relative(process.cwd(), path.join(OUT, f)));
  }
} finally {
  if (fs.existsSync(scratchFull)) fs.unlinkSync(scratchFull);
  fs.rmSync(TMP, {recursive: true, force: true});
  await browser.close();
  srv.kill();
}
