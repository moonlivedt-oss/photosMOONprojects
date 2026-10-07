#!/usr/bin/env node
// ============================================================
//  Собирает в эту папку копии всех картинок из проектов D:\Desktop\components,
//  разложенные по смыслу, и строит Галерея.html для просмотра.
//
//  Запуск: Обновить.cmd (или node _обновить.js). Можно запускать сколько угодно раз:
//  - копирует только изменившееся;
//  - новые картинки, которые не подошли ни под одно правило, попадают в «99 Прочее»,
//    так что ничего не теряется;
//  - удаляет только свои копии, у которых пропал оригинал (список — в _источники.json).
//    Свои файлы, положенные сюда руками, не трогает.
//
//  Это КОПИИ: правьте оригиналы в проектах (путь к оригиналу — в галерее под картинкой),
//  потом запустите Обновить.cmd.
// ============================================================
"use strict";
var fs = require("fs");
var path = require("path");

var HERE = __dirname;
var ROOT = path.join(HERE, "..");
var MANIFEST = path.join(HERE, "_источники.json");
var IMG = /\.(png|jpe?g|gif|webp|svg|ico|bmp|avif)$/i;
// Не картинки проекта, а производные: сборки, тестовые снимки, зависимости, выпуски.
var SKIP_DIRS = /(^|[\\/])(node_modules|\.git|\.vscode-test|build|dist|__pycache__|__screenshots__|[^\\/]*-snapshots|test-results)([\\/]|$)/i;
// Сама эта папка (как бы её ни переименовали) — иначе копии скопируются сами в себя, в «99 Прочее».
var SELF = path.basename(HERE);

function rel(p) { return path.relative(ROOT, p).replace(/\\/g, "/"); }
function exists(p) { try { fs.statSync(p); return true; } catch (e) { return false; } }
function list(dir, re) {
  if (!exists(dir)) return [];
  return fs.readdirSync(dir).filter(function (n) { return (re || IMG).test(n) && fs.statSync(path.join(dir, n)).isFile(); })
    .sort(function (a, b) { return a.localeCompare(b, "ru", { numeric: true }); }).map(function (n) { return path.join(dir, n); });
}
function walk(dir, out) {
  out = out || [];
  if (!exists(dir) || SKIP_DIRS.test(rel(dir) + "/") || rel(dir).split("/")[0] === SELF) return out;
  fs.readdirSync(dir, { withFileTypes: true }).forEach(function (e) {
    var p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (IMG.test(e.name)) out.push(p);
  });
  return out;
}
function pad(n) { return (n < 10 ? "0" : "") + n; }
function safe(s) { return String(s).replace(/[<>:"/\\|?*]/g, "-").trim(); }

// ---------------- правила: оригинал -> куда в этой папке ----------------
var plan = [];          // { src, dst (относительно HERE), section, group }
var taken = {};         // оригиналы, уже разложенные правилами
function put(src, section, group, name) {
  if (!exists(src) || taken[src]) return;
  taken[src] = true;
  var dst = path.join(section, group || "", name || path.basename(src));
  plan.push({ src: src, dst: dst, section: section, group: group || "" });
}
function putAll(files, section, group, rename) {
  files.forEach(function (f) { put(f, section, group, rename ? rename(path.basename(f)) : null); });
}

// 01. Фоны MoonLight BG — по наборам, с названиями из src/core/sets.js.
(function () {
  var bg = path.join(ROOT, "vscode-bg");
  var sec = "01 Фоны VS Code (MoonLight BG)";
  var src = exists(path.join(bg, "src", "core", "sets.js")) ? fs.readFileSync(path.join(bg, "src", "core", "sets.js"), "utf8") : "";
  var zones = { editor: "Редактор", sidebar: "Боковая панель", panel: "Нижняя панель", master: "Целиком" };
  var n = 0;
  (src.match(/\{\s*name:\s*"[^"]+"[^\n]*/g) || []).forEach(function (line) {
    var name = /name:\s*"([^"]+)"/.exec(line)[1];
    var files = [];
    Object.keys(zones).forEach(function (z) {
      var m = new RegExp(z + ':\\s*"([^"]+)"').exec(line);
      if (m) files.push([z, m[1]]);
    });
    if (!files.length) return;   // градиентные и процедурные наборы — без картинок
    var group = pad(n++) + " " + safe(name);
    files.forEach(function (f) { put(path.join(bg, f[1]), sec, group, zones[f[0]] + path.extname(f[1])); });
  });
  ["editor", "sidebar", "panel", "sets"].forEach(function (d) { putAll(list(path.join(bg, "assets", d)), sec, "Без набора"); });
  putAll(list(path.join(bg, "assets")), sec, "Без набора");
})();

// 02. Фоны окна документации C++ и палитры VSCodeLauncher (по одной картинке на тему).
putAll(list(path.join(ROOT, "cpp-docs-panel", "extension"), /^bg-.*\.(webp|png|jpe?g)$/i), "02 Фоны тем", "Документация C++", function (n) { return n.replace(/^bg-/, ""); });
putAll(list(path.join(ROOT, "VSCodeLauncher", "assets", "palettes")), "02 Фоны тем", "VSCodeLauncher (палитры)");

// 03. Наклейки документации C++ — по группам.
(function () {
  var st = path.join(ROOT, "cpp-docs-panel", "extension", "stickers");
  var sec = "03 Наклейки (Документация C++)";
  list(st).forEach(function (f) {
    var n = path.basename(f), m;
    if (/^mascot-/.test(n)) put(f, sec, "Маскот", n.replace(/^mascot-/, ""));
    else if (/^icon-/.test(n)) put(f, sec, "Значки разделов", n.replace(/^icon-/, ""));
    else if (/^badge-/.test(n)) put(f, sec, "Бейджи", n.replace(/^badge-/, ""));
    // ui-cards@dracula.webp -> Интерфейс/cards/dracula.webp (без @ — тема по умолчанию)
    else if ((m = /^ui-([^@.]+)(?:@([^.]+))?(\.\w+)$/.exec(n))) put(f, sec, "Интерфейс/" + m[1], (m[2] || "default") + m[3]);
    else if (/^ui-/.test(n)) put(f, sec, "Интерфейс", n.replace(/^ui-/, ""));
    else put(f, sec, "Прочее");
  });
})();

// 04. Маскоты.
putAll(list(path.join(ROOT, "VSCodeLauncher", "assets", "mascots")), "04 Маскоты", "VSCodeLauncher");
putAll(list(path.join(ROOT, "cpp-docs-panel", "art")), "04 Маскоты", "Документация C++ (исходники)");

// 05. Значки и логотипы — по проектам.
(function () {
  var sec = "05 Значки и логотипы";
  put(path.join(ROOT, "moon-core", "extension", "media", "icon.svg"), sec, "Moon Core");
  put(path.join(ROOT, "vscode-bg", "extension", "icon.png"), sec, "MoonLight BG");
  putAll(list(path.join(ROOT, "vscode-bg", "assets", "ui")), sec, "MoonLight BG/панель");
  put(path.join(ROOT, "cpp-docs-panel", "extension", "icon-marketplace.png"), sec, "Документация C++");
  put(path.join(ROOT, "cpp-docs-panel", "extension", "icon.svg"), sec, "Документация C++");
  putAll(list(path.join(ROOT, "cpp-docs-panel", "scripts", "note-icons")), sec, "Документация C++/заметки");
  put(path.join(ROOT, "VSCodeLauncher", "assets", "logo.png"), sec, "VSCodeLauncher");
  put(path.join(ROOT, "VSCodeLauncher", "assets", "app.ico"), sec, "VSCodeLauncher");
  putAll(list(path.join(ROOT, "VSCodeLauncher", "assets", "icons")), sec, "VSCodeLauncher/кнопки");
  put(path.join(ROOT, "personal-project", "assets", "tm_icon.png"), sec, "personal-project");
  put(path.join(ROOT, "moon-bundle", "engine", "tools", "img", "item.svg"), sec, "Установщик (moon-bundle)");
})();

// 06. Интерфейс personal project.
putAll(list(path.join(ROOT, "personal-project", "assets", "tm_ui")), "06 Интерфейс personal project");

// 07. Скриншоты и обложки README.
putAll(list(path.join(ROOT, "vscode-bg", "docs", "screenshots")), "07 Скриншоты и обложки", "MoonLight BG");
putAll(list(path.join(ROOT, "cpp-docs-panel", "docs", "screenshots")), "07 Скриншоты и обложки", "Документация C++");
putAll(list(path.join(ROOT, "VSCodeLauncher", "docs")), "07 Скриншоты и обложки", "VSCodeLauncher");

// 08. Нарисованное, но не используемое.
putAll(list(path.join(ROOT, "cpp-docs-panel", "art", "unused")), "08 Не используются", "Документация C++");

// 99. Всё остальное, что найдётся в проектах, — чтобы новые картинки не терялись.
walk(ROOT).forEach(function (f) {
  if (taken[f]) return;
  var r = rel(f).split("/");
  put(f, "99 Прочее", safe(r[0]), safe(r.slice(1).join(" - ")));
});

// ---------------- копирование ----------------
var old = {};
try { old = JSON.parse(fs.readFileSync(MANIFEST, "utf8")); } catch (e) {}
var now = {}, copied = 0, same = 0, removed = 0;
plan.forEach(function (p) {
  var dst = path.join(HERE, p.dst);
  now[p.dst.replace(/\\/g, "/")] = rel(p.src);
  var s = fs.statSync(p.src);
  if (exists(dst)) {
    var d = fs.statSync(dst);
    if (d.size === s.size && Math.abs(d.mtimeMs - s.mtimeMs) < 2000) { same++; return; }
  }
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(p.src, dst);
  fs.utimesSync(dst, s.atime, s.mtime);
  copied++;
});
Object.keys(old).forEach(function (d) {
  if (now[d]) return;
  var p = path.join(HERE, d);
  if (exists(p)) { fs.unlinkSync(p); removed++; }
  // пустые папки после удаления
  var dir = path.dirname(p);
  while (dir.length > HERE.length && exists(dir) && !fs.readdirSync(dir).length) { fs.rmdirSync(dir); dir = path.dirname(dir); }
});
fs.writeFileSync(MANIFEST, JSON.stringify(now, null, 1), "utf8");

// ---------------- свои картинки ----------------
// Всё, что положено сюда руками (например, в «10 Свои заготовки»), тоже показывается в галерее.
// Такие файлы не копируются и не удаляются: в _источники.json их нет.
(function own(dir) {
  fs.readdirSync(dir, { withFileTypes: true }).forEach(function (e) {
    var p = path.join(dir, e.name);
    if (/^_/.test(e.name)) return;
    if (e.isDirectory()) return own(p);
    var r = path.relative(HERE, p).replace(/\\/g, "/"), parts = r.split("/");
    if (!IMG.test(e.name) || now[r] || parts.length < 2) return;
    plan.push({ src: p, dst: r, section: parts[0], group: parts.slice(1, -1).join("/") });
  });
})(HERE);

// ---------------- галерея ----------------
function sizeStr(b) { return b < 1024 * 1024 ? Math.round(b / 1024) + " КБ" : (b / 1048576).toFixed(1) + " МБ"; }
var sections = [];
plan.forEach(function (p) {
  var sec = sections.filter(function (s) { return s.name === p.section; })[0];
  if (!sec) { sec = { name: p.section, groups: [] }; sections.push(sec); }
  var g = sec.groups.filter(function (x) { return x.name === p.group; })[0];
  if (!g) { g = { name: p.group, items: [] }; sec.groups.push(g); }
  g.items.push({ file: p.dst.replace(/\\/g, "/"), name: path.basename(p.dst), src: path.resolve(p.src), size: sizeStr(fs.statSync(p.src).size) });
});
sections.sort(function (a, b) { return a.name.localeCompare(b.name, "ru", { numeric: true }); });
sections.forEach(function (s) { s.groups.sort(function (a, b) { return a.name.localeCompare(b.name, "ru", { numeric: true }); }); });
var tpl = fs.readFileSync(path.join(HERE, "_галерея-шаблон.html"), "utf8");
var data = JSON.stringify({ sections: sections, built: new Date().toLocaleString("ru-RU"), total: plan.length })
  .replace(/</g, "\\u003c");
fs.writeFileSync(path.join(HERE, "Галерея.html"), tpl.replace("/*__DATA__*/null", data), "utf8");

console.log("  Картинок: " + plan.length + " (скопировано " + copied + ", без изменений " + same + (removed ? ", убрано " + removed : "") + ")");
sections.forEach(function (s) {
  var n = 0; s.groups.forEach(function (g) { n += g.items.length; });
  console.log("    " + s.name + ": " + n);
});
console.log("  Галерея: " + path.join(HERE, "Галерея.html"));
