"use strict";
const $ = (id) => document.getElementById(id);
let TOKEN = "", CFG = {}, files = [], cur = null, dirty = false;

const esc = (s) => s.replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

async function api(path, opts = {}) {
  const o = {method: opts.method || "GET", headers: {}};
  if (opts.body) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  if (o.method !== "GET") o.headers["X-KB-Token"] = TOKEN;
  const r = await fetch(path, o);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.error || r.statusText); e.status = r.status; throw e; }
  return j;
}
function status(msg, err) { const s = $("status"); s.textContent = msg; s.className = err ? "err" : ""; }

/* ---------- markdown ---------- */
const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i;  // what /api/image serves
function safeDecode(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
// Routes: "#/<path>" opens a file, "?line=N" also jumps to source line N, "?h=<id>" to a heading.
// "#search=<q>" lists search hits, "#changes" lists changed files, "#diff/<path>" shows one diff.
function fileHash(path, line, anchor) {
  return "#/" + encodeURI(path).replace(/[?#]/g, encodeURIComponent) +
    (line ? "?line=" + line : anchor ? "?h=" + encodeURIComponent(anchor) : "");
}
// GitHub-style heading id: lower case, punctuation dropped, spaces to hyphens.
const slug = (t) => t.trim().toLowerCase().replace(/[^\p{L}\p{N} _-]/gu, "").replace(/ /g, "-");
function resolveRel(base, href) {
  const parts = (href.startsWith("/") ? href.slice(1) : base.split("/").slice(0, -1).join("/") + "/" + href).split("/");
  const out = [];
  for (const p of parts) { if (p === "..") out.pop(); else if (p && p !== ".") out.push(p); }
  return out.join("/");
}
function wikiTarget(name) {
  const n = name.trim().toLowerCase().replace(/\.md$/, "");
  const f = files.find((f) => f.path.toLowerCase().replace(/\.md$/, "") === n) ||
            files.find((f) => f.path.toLowerCase().replace(/\.md$/, "").split("/").pop() === n);
  return f && f.path;
}
function inline(src, base) {
  const stash = [];
  const keep = (h) => "\u0000" + (stash.push(h) - 1) + "\u0000";
  let s = src.replace(/(`+)([\s\S]*?[^`])\1(?!`)/g, (_, __, c) => keep("<code>" + esc(c.trim()) + "</code>"));
  s = esc(s);
  s = s.replace(/\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]+))?\]\]/g, (m, t, h, label) => {
    const p = wikiTarget(t.replace(/&amp;/g, "&"));
    return p ? keep('<a href="' + esc(fileHash(p, 0, h && slug(h))) + '">' + (label || t) + "</a>") : keep('<span class="muted" title="missing">' + (label || t) + "</span>");
  });
  // Images first, so the link rule below does not take "[alt](src)" out of "![alt](src)".
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (m, alt, src) => {
    alt = alt.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[+i].replace(/<[^>]*>/g, ""));  // already escaped
    src = src.replace(/&amp;/g, "&");
    // The CSP allows only same-origin images, so remote images become links.
    if (/^https?:/i.test(src)) return keep('<a href="' + esc(src) + '" target="_blank" rel="noopener noreferrer">' + (alt || esc(src)) + "</a>");
    if (/^[a-z][a-z0-9+.-]*:/i.test(src) || src.startsWith("#") || src.startsWith("//")) return alt;
    const p = resolveRel(base, safeDecode(src.split(/[?#]/)[0]));
    if (!IMAGE_EXT.test(p)) return alt;
    return keep('<img src="/api/image?path=' + esc(encodeURIComponent(p)) + '" alt="' + alt + '" loading="lazy">');
  });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (m, text, href) => {
    href = href.replace(/&amp;/g, "&");
    if (/^(https?:|mailto:)/i.test(href)) return keep('<a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + text + "</a>");
    if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return text;
    const [file, h] = href.split("#");
    const p = file ? resolveRel(base, safeDecode(file)) : base;
    return files.some((f) => f.path === p) ? keep('<a href="' + esc(fileHash(p, 0, h && safeDecode(h))) + '">' + text + "</a>") : text;
  });
  s = s.replace(/&lt;(https?:\/\/[^\s&]+)&gt;/g, (m, u) => keep('<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(u) + "</a>"));
  s = s.replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (m, a, b) => "<strong>" + (a || b) + "</strong>")
       .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, "$1<em>$2</em>")
       .replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g, "$1<em>$2</em>")
       .replace(/~~([^~]+)~~/g, "<del>$1</del>");
  // Stashed HTML can hold placeholders itself (a linked image, code in link text), so expand recursively.
  const unstash = (t) => t.replace(/\u0000(\d+)\u0000/g, (_, i) => unstash(stash[+i]));
  return unstash(s);
}
function cells(line) { return line.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|")); }
// Each top-level block (and list item / table row) carries data-line = its 1-based source line,
// so a search hit can scroll to the block that holds its line. `off` = lines before `text`.
function markdown(text, base, off = 0) {
  let fm = "";
  const m = off ? null : text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (m) {
    fm = '<details class="fm" data-line="1"><summary>frontmatter</summary><pre>' + esc(m[1]) + "</pre></details>";
    text = text.slice(m[0].length); off = m[0].split("\n").length - 1;
  }
  const L = text.split("\n"), out = [];
  let i = 0, pStart = 0;
  const para = [];
  const at = (n) => ' data-line="' + (off + n + 1) + '"';
  const flush = () => { if (para.length) { out.push("<p" + at(pStart) + ">" + inline(para.join(" "), base) + "</p>"); para.length = 0; } };
  while (i < L.length) {
    const line = L[i], start = i;
    let f = line.match(/^\s*(```+|~~~+)\s*(\S*)/);
    if (f) {
      flush(); const buf = []; i++;
      while (i < L.length && !L[i].trim().startsWith(f[1])) buf.push(L[i++]);
      i++; out.push("<pre" + at(start) + "><code>" + esc(buf.join("\n")) + "</code></pre>"); continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    let h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (h) { flush(); out.push("<h" + h[1].length + at(start) + ">" + inline(h[2], base) + "</h" + h[1].length + ">"); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr" + at(start) + ">"); i++; continue; }
    if (/^\s*>/.test(line)) {
      flush(); const buf = [];
      while (i < L.length && /^\s*>/.test(L[i])) buf.push(L[i++].replace(/^\s*> ?/, ""));
      out.push("<blockquote" + at(start) + ">" + markdown(buf.join("\n"), base, off + start) + "</blockquote>"); continue;
    }
    if (line.includes("|") && i + 1 < L.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(L[i + 1])) {
      flush(); const head = cells(line); i += 2; const rows = [];
      while (i < L.length && L[i].trim() && L[i].includes("|")) rows.push({n: i, c: cells(L[i++])});
      out.push("<table" + at(start) + "><thead><tr>" + head.map((c) => "<th>" + inline(c, base) + "</th>").join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr" + at(r.n) + ">" + r.c.map((c) => "<td>" + inline(c, base) + "</td>").join("") + "</tr>").join("") + "</tbody></table>");
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      flush(); const items = [];
      while (i < L.length) {
        const mm = L[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)/);
        if (mm) items.push({ind: mm[1].replace(/\t/g, "  ").length, ol: /\d/.test(mm[2]), t: mm[3], n: off + i + 1});
        else if (L[i].trim() && /^\s+\S/.test(L[i]) && items.length) items[items.length - 1].t += " " + L[i].trim();
        else break;
        i++;
      }
      out.push(list(items, base)); continue;
    }
    if (!para.length) pStart = i;
    para.push(line.trim()); i++;
  }
  flush();
  return fm + out.join("\n");
}
function list(items, base) {
  let html = "", stack = [];
  for (const it of items) {
    while (stack.length && it.ind < stack[stack.length - 1].ind) { html += "</li></" + stack.pop().tag + ">"; }
    const tag = it.ol ? "ol" : "ul", top = stack[stack.length - 1];
    if (!top || it.ind > top.ind) { html += "<" + tag + ">"; stack.push({ind: it.ind, tag}); }
    else html += "</li>";
    let t = it.t, box = t.match(/^\[([ xX])\]\s+(.*)/);
    if (box) t = (box[1] === " " ? "☐ " : "☑ ") + box[2];
    html += '<li data-line="' + it.n + '">' + inline(t, base);
  }
  while (stack.length) html += "</li></" + stack.pop().tag + ">";
  return html;
}
function csvTable(text) {
  const rows = []; let row = [], f = "", q = false, ln = 1, start = 1;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "\n") ln++;
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n") { row.push(f); row.n = start; rows.push(row); row = []; f = ""; start = ln; }
    else if (c !== "\r") f += c;
  }
  if (f || row.length) { row.push(f); row.n = start; rows.push(row); }
  if (!rows.length) return "";
  const tr = (r) => '<tr data-line="' + r.n + '">';
  return "<table><thead>" + tr(rows[0]) + rows[0].map((c) => "<th>" + esc(c) + "</th>").join("") + "</tr></thead><tbody>" +
    rows.slice(1).map((r) => tr(r) + r.map((c) => "<td>" + esc(c) + "</td>").join("") + "</tr>").join("") + "</tbody></table>";
}
function render(path, text) {
  if (/\.md$/i.test(path)) return markdown(text, path);
  if (/\.csv$/i.test(path)) return csvTable(text);
  return "<pre><code>" + text.split("\n").map((l, n) => '<span data-line="' + (n + 1) + '">' + esc(l) + "</span>").join("\n") + "</code></pre>";
}

// Give rendered headings unique ids (for "#anchor" links and the outline) and return them.
function headings(root) {
  const seen = {}, out = [];
  root.querySelectorAll("h1,h2,h3,h4").forEach((h) => {
    let id = slug(h.textContent) || "section";
    if (seen[id] !== undefined) id += "-" + ++seen[id]; else seen[id] = 0;
    h.id = id; out.push({id, level: +h.tagName[1], text: h.textContent});
  });
  return out;
}
function paint(path, text) {
  const v = $("view");
  v.innerHTML = render(path, text);
  const hs = /\.md$/i.test(path) ? headings(v) : [];
  $("toc").innerHTML = hs.length >= 3 ? "<b>On this page</b>" + hs.filter((h) => h.level > 1 && h.level < 4).map((h) =>
    '<a href="' + esc(fileHash(path, 0, h.id)) + '" class="l' + h.level + '">' + esc(h.text) + "</a>").join("") : "";
  $("toc").hidden = !$("toc").innerHTML || !$("editor").hidden;
  if (cur && cur.path === path && cur.back && !$("panes").classList.contains("split")) v.insertAdjacentHTML("beforeend", cur.back);
}

/* ---------- tree ---------- */
function buildTree() {
  const q = $("filter").value.trim().toLowerCase(), root = {d: {}, f: []};
  for (const f of files) {
    if (q && !f.path.toLowerCase().includes(q)) continue;
    let n = root; const parts = f.path.split("/");
    for (const p of parts.slice(0, -1)) n = n.d[p] || (n.d[p] = {d: {}, f: []});
    n.f.push(f);
  }
  const draw = (n, open) => {
    let h = "";
    for (const k of Object.keys(n.d).sort()) h += "<details" + (open ? " open" : "") + "><summary>" + esc(k) + "</summary>" + draw(n.d[k], open) + "</details>";
    for (const f of n.f) h += '<a href="' + fileHash(f.path) + '" data-p="' + esc(f.path) + '" class="' + (f.readonly ? "ro " : "") + '">' + esc(f.path.split("/").pop()) + "</a>";
    return h;
  };
  $("tree").innerHTML = draw(root, !!q);
  markCur();
}
function markCur() {
  document.querySelectorAll("#tree a").forEach((a) => {
    const on = cur && a.dataset.p === cur.path; a.classList.toggle("cur", on);
    if (on) for (let p = a.parentElement; p && p.id !== "tree"; p = p.parentElement) if (p.tagName === "DETAILS") p.open = true;
  });
}

/* ---------- file view/edit ---------- */
let split = false;  // edit mode: rendered preview beside the editor
function setMode(edit) {
  if (!cur) return;  // no file open (start page, search results)
  const canPreview = /\.(md|csv)$/i.test(cur.path);
  if (!edit && dirty) paint(cur.path, $("editor").value);  // View shows the edited text, saved or not
  $("panes").classList.toggle("split", edit && split && canPreview);
  $("view").hidden = edit && !(split && canPreview); $("editor").hidden = !edit;
  $("save").hidden = !edit || cur.readonly; $("preview").hidden = !edit || !canPreview;
  $("preview").classList.toggle("on", split);
  $("toc").hidden = edit || !$("toc").innerHTML;
  $("toggle").textContent = edit ? "View" : "Edit";
  if (edit) {
    if (split && canPreview) paint(cur.path, $("editor").value);
    $("editor").focus();
    if (cur.line) { caretToLine($("editor"), cur.line); cur.line = 0; }
  }
}
// Put the caret at the start of 1-based line n and scroll it into view (about a third down).
function caretToLine(ta, n) {
  const v = ta.value, lines = v.split("\n");
  const pos = lines.slice(0, Math.max(0, Math.min(n, lines.length) - 1)).reduce((a, l) => a + l.length + 1, 0);
  // Measure the height of the text before the line (wrapped lines included) by loading only that text.
  ta.value = v.slice(0, pos); ta.scrollTop = 0;
  const before = ta.scrollHeight; ta.value = v;
  ta.scrollTop = before > ta.clientHeight ? before - ta.clientHeight / 3 : 0;  // scrollHeight >= clientHeight
  ta.setSelectionRange(pos, pos);
}
function flash(el) {
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 2600);
}
// Scroll the view to the deepest rendered block whose source starts at or before line n, and flash it.
function showLine(n) {
  let hit = null;
  for (const el of $("view").querySelectorAll("[data-line]")) { if (+el.dataset.line <= n) hit = el; else break; }  // document order = line order
  if (!hit) return;
  if (hit.tagName === "DETAILS") hit.open = true;
  hit.scrollIntoView({block: "center"}); flash(hit);
}
function showAnchor(id) {
  const el = [...$("view").querySelectorAll("[id]")].find((e) => e.id === id || e.id === slug(id));
  if (el) { el.scrollIntoView({block: "start"}); flash(el); }
}
function remember(path) {
  try {
    const r = JSON.parse(localStorage.getItem("kb-recent") || "[]").filter((p) => p !== path);
    localStorage.setItem("kb-recent", JSON.stringify([path, ...r].slice(0, 8)));
  } catch (e) { /* storage blocked: no recent list */ }
}
function recent() {
  try { return JSON.parse(localStorage.getItem("kb-recent") || "[]").filter((p) => files.some((f) => f.path === p)); }
  catch (e) { return []; }
}
function conflict(on) { $("conflict").hidden = !on; }
async function openFile(path, line, anchor) {
  if (cur && path === cur.path && (dirty || (anchor && !$("view").hidden))) {
    // Same file: keep unsaved edits and just move to the line or heading.
    if (anchor) showAnchor(anchor); else if (line && !$("view").hidden) showLine(line);
    return;
  }
  try {
    const f = await api("/api/file?path=" + encodeURIComponent(path));
    cur = f; cur.line = line || 0; cur.back = ""; dirty = false;
    $("bar").hidden = false; $("crumb").textContent = path + (f.readonly ? "  (read-only)" : "");
    $("del").hidden = f.readonly;
    $("editor").value = f.content; $("editor").readOnly = f.readonly; $("editor").setSelectionRange(0, 0);
    paint(path, f.content); $("view").scrollTop = 0;
    status(""); conflict(false); setMode(false); markCur(); remember(path);
    if (anchor) showAnchor(anchor); else if (line) showLine(line);
    if (/\.md$/i.test(path)) loadBacklinks(path);
  } catch (e) { page('<p class="muted">' + esc(path) + ": " + esc(e.message) + "</p>"); }
}
async function loadBacklinks(path) {
  const hits = await api("/api/backlinks?path=" + encodeURIComponent(path)).catch(() => []);
  if (!cur || cur.path !== path) return;
  const byFile = {};
  for (const h of hits) (byFile[h.path] = byFile[h.path] || []).push(h);
  const names = Object.keys(byFile);
  cur.back = '<section class="backlinks"><h4>Linked from ' + names.length + " file" + (names.length === 1 ? "" : "s") + "</h4>" +
    (names.length ? names.map((p) => '<a href="' + esc(fileHash(p, byFile[p][0].line)) + '"><code>' + esc(p) + "</code></a>").join("")
      : '<p class="muted">No other file links here.</p>') + "</section>";
  if (!$("panes").classList.contains("split")) $("view").insertAdjacentHTML("beforeend", cur.back);
}
async function save(force) {
  if (!cur || cur.readonly) return;
  try {
    const content = $("editor").value;
    if (force) cur.version = (await api("/api/file?path=" + encodeURIComponent(cur.path))).version;
    const r = await api("/api/file", {method: "PUT", body: {path: cur.path, content, version: cur.version}});
    cur.version = r.version; cur.content = content; dirty = false; conflict(false);
    paint(cur.path, content); status("Saved " + new Date().toLocaleTimeString());
  } catch (e) { status(e.message, true); conflict(e.status === 409); }
}
async function del() {
  if (!cur || cur.readonly) return;
  if (!confirm("Delete " + cur.path + "?\n\nA file that was never committed to git cannot be recovered.")) return;
  try {
    await api("/api/file", {method: "DELETE", body: {path: cur.path, version: cur.version}});
    dirty = false; cur = null; await reloadTree(); location.hash = "";
  } catch (e) { status(e.message, true); }
}
async function reloadTree() { files = await api("/api/tree"); buildTree(); }

/* ---------- pages: start, search, changes, diff ---------- */
function page(html) {
  cur = null; dirty = false; conflict(false);
  $("bar").hidden = true; $("editor").hidden = true; $("toc").hidden = true; $("view").hidden = false;
  $("panes").classList.remove("split");
  $("view").innerHTML = html; $("view").scrollTop = 0; markCur();
}
const fileLink = (p, label) => '<a class="hit" href="' + esc(fileHash(p)) + '"><code>' + esc(label || p) + "</code></a>";
async function home() {
  const r = recent();
  let h = "<h1>" + esc(CFG.title) + "</h1><p class=\"muted\">" + files.length + " files. Pick one on the left, search above (press <kbd>/</kbd>), or click <b>+ New</b>.</p>";
  if (r.length) h += "<h2>Recently opened</h2>" + r.map((p) => fileLink(p)).join("");
  page(h);
  if (!CFG.git) return;
  const c = await api("/api/changes").catch(() => []);
  if (c.length && !cur && !location.hash.slice(1)) $("view").insertAdjacentHTML("beforeend",
    '<h2>Uncommitted changes</h2><p>' + c.length + ' file(s) differ from the last commit. <a href="#changes">Review them</a>.</p>');
}
async function doSearch(q) {
  $("search").value = q;
  if (q.trim().length < 2) return page('<p class="muted">Type at least 2 characters.</p>');
  const hits = await api("/api/search?q=" + encodeURIComponent(q.trim()));
  const re = new RegExp("(" + q.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
  page("<h2>" + hits.length + " result(s) for “" + esc(q.trim()) + "”" + (hits.length >= 200 ? " (first 200 shown)" : "") + "</h2>" + hits.map((h) =>
    '<a class="hit" href="' + esc(fileHash(h.path, h.line)) + '"><code>' + esc(h.path) + (h.line ? ":" + h.line : "") + "</code><br>" +
    esc(h.text).replace(re, "<b>$1</b>") + "</a>").join(""));
}
async function showChanges() {
  let c;
  try { c = await api("/api/changes"); } catch (e) { return page('<p class="muted">' + esc(e.message) + "</p>"); }
  page("<h2>Uncommitted changes</h2>" + (c.length ? "<p class=\"muted\">Files that differ from the last commit. Commit them with git when you are done.</p>" +
    c.map((x) => '<div class="chg"><span class="st ' + x.status + '">' + x.status + "</span> " +
      (x.viewable ? '<a href="#diff/' + esc(encodeURI(x.path)) + '"><code>' + esc(x.path) + "</code></a>" : "<code>" + esc(x.path) + "</code>") + "</div>").join("")
    : '<p class="muted">Nothing to commit: the working tree matches the last commit.</p>'));
}
async function showDiff(path) {
  let d;
  try { d = (await api("/api/diff?path=" + encodeURIComponent(path))).diff; } catch (e) { return page('<p class="muted">' + esc(e.message) + "</p>"); }
  const lines = d.split("\n").map((l) => {
    const cls = /^(\+\+\+|---)/.test(l) ? "meta" : l[0] === "+" ? "add" : l[0] === "-" ? "del" : l.startsWith("@@") ? "hunk" : /^(diff|index|new|deleted)/.test(l) ? "meta" : "";
    return cls ? '<span class="' + cls + '">' + esc(l) + "</span>" : esc(l);
  }).join("\n");
  const exists = files.some((f) => f.path === path);
  page('<p><a href="#changes">← All changes</a>' + (exists ? " · " + '<a href="' + esc(fileHash(path)) + '">Open file</a>' : "") + "</p><h2><code>" + esc(path) + "</code></h2>" +
    (d.trim() ? '<pre class="diff"><code>' + lines + "</code></pre>" : '<p class="muted">No changes.</p>'));
}

function route() {
  const h = location.hash, m = h.match(/^#\/(.*?)(?:\?(line|h)=([^&]*))?$/);
  const p = m && safeDecode(m[1]);
  if (dirty && cur && p !== cur.path) {
    if (!confirm("Discard unsaved changes?")) { history.replaceState(null, "", fileHash(cur.path)); return; }
    dirty = false;
  }
  if (p) return openFile(p, m[2] === "line" ? +m[3] : 0, m[2] === "h" ? safeDecode(m[3]) : "");
  let r;
  if ((r = h.match(/^#search=(.*)$/))) return doSearch(safeDecode(r[1]));
  if (h === "#changes") return showChanges();
  if ((r = h.match(/^#diff\/(.*)$/))) return showDiff(safeDecode(r[1]));
  home();
}
const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

/* ---------- theme ---------- */
const THEMES = {auto: "Theme: auto", light: "Theme: light", dark: "Theme: dark"};
function theme(t) {
  if (!THEMES[t]) t = "auto";
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  $("theme").title = THEMES[t] + " (click to change)"; $("theme").textContent = THEMES[t];
  try { localStorage.setItem("kb-theme", t); } catch (e) { /* not remembered */ }
}
const savedTheme = () => { try { return localStorage.getItem("kb-theme") || "auto"; } catch (e) { return "auto"; } };

function today() { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
async function newFile() {
  const p = (prompt("New file path (e.g. folder/topic.md):") || "").trim(); if (!p) return;
  let content = "";
  if (/\.md$/i.test(p)) {
    content = "# " + p.split("/").pop().replace(/\.md$/i, "") + "\n\n";
    if (CFG.template) {
      try {
        const t = (await api("/api/file?path=" + encodeURIComponent(CFG.template))).content;
        const folder = p.includes("/") ? p.split("/")[0] : "";
        content = t.replace(/YYYY-MM-DD/g, today()).replace(/^(category:\s*)<[^>\n]*>/m, (m, k) => folder ? k + folder : m);
      } catch (e) { /* no template: keep the heading */ }
    }
  }
  try {
    await api("/api/new", {method: "POST", body: {path: p, content}});
    await reloadTree(); await openFile(p); history.pushState(null, "", fileHash(p)); setMode(true);
  } catch (e) { alert(e.message); }
}
function output(title, text) {
  $("out-title").textContent = title; $("out-text").textContent = text;
  if ($("out").showModal) $("out").showModal(); else alert(title + "\n\n" + text);
}

async function init() {
  theme(savedTheme());
  CFG = await api("/api/config");
  TOKEN = CFG.token; $("title").textContent = CFG.title; document.title = CFG.title;
  $("changes").hidden = !CFG.git;
  CFG.actions.forEach((a) => {
    const b = document.createElement("button"); b.textContent = a;
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await api("/api/action", {method: "POST", body: {name: a}});
        output(a + " (exit " + r.code + ")", r.output || "(no output)");
        await reloadTree();
        if (cur && !dirty) { const p = cur.path; cur = null; openFile(p); }
      } catch (e) { output(a, e.message); } finally { b.disabled = false; }
    };
    $("actions").appendChild(b);
  });
  await reloadTree(); route();
}
$("filter").oninput = buildTree;
$("reload").onclick = async () => { await reloadTree(); if (!cur && !location.hash.slice(1)) home(); };
$("search").onkeydown = (e) => { if (e.key === "Enter") go("#search=" + encodeURIComponent($("search").value.trim())); };
$("menu").onclick = () => $("side").classList.toggle("hidden");
// On a narrow screen the sidebar covers the page: start with it closed and close it once a file is picked.
const narrow = window.matchMedia("(max-width: 700px)");
if (narrow.matches) $("side").classList.add("hidden");
$("tree").addEventListener("click", (e) => { if (narrow.matches && e.target.closest("a")) $("side").classList.add("hidden"); });
$("toggle").onclick = () => setMode($("editor").hidden);
$("preview").onclick = () => { split = !split; setMode(true); };
$("save").onclick = () => save(false);
$("overwrite").onclick = () => { if (confirm("Replace the newer file on disk with your text?")) save(true); };
$("takedisk").onclick = () => { if (!confirm("Discard your edits and load the file from disk?")) return; const p = cur.path; dirty = false; cur = null; openFile(p); };
$("del").onclick = del;
$("changes").onclick = () => go("#changes");
$("new").onclick = newFile;
$("theme").onclick = () => theme({auto: "light", light: "dark", dark: "auto"}[savedTheme()] || "auto");
$("out-close").onclick = () => $("out").close();
let previewTimer = 0;
$("editor").oninput = () => {
  dirty = true; status("Unsaved changes");
  if ($("panes").classList.contains("split")) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => { const v = $("view"), top = v.scrollTop; paint(cur.path, $("editor").value); v.scrollTop = top; }, 250);
  }
};
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(false); }
  else if (e.key === "/" && !e.ctrlKey && !e.metaKey && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) { e.preventDefault(); $("search").focus(); $("search").select(); }
});
window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
window.addEventListener("hashchange", route);
// A link to the hash already in the address bar fires no hashchange (e.g. the same search hit twice,
// or the last-opened file after a search), so open it directly.
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#"]');
  if (a && a.getAttribute("href") === location.hash && !e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); route(); }
});
init();
