// 导图版面与渲染的检查（node tests/report_image_layout.cjs）。不依赖浏览器。
// 需求原文：竖版 A4，任意数量的教室放在【一张】里，排版整齐，不裁切不挤压；字号自适应。
// 设计：版面按「实测的最长教室名宽度」算，字号连续自适应，没有「放不下」；名字绝不截断；字号很小时由调用方提示。
const assert = require("node:assert");
const fsx = require("node:fs");
const api = require("../static/report-image.js");
const { layout, draw, MAX_ROOMS } = api;
assert.strictEqual(api.pages, undefined, "不应有分页");

// 真实的默认教室名（一教室…五百教室）：由 python 包装器用 qk_config.default_room_name 生成后经环境变量传入
const defaultNames = process.env.QK_ROOM_NAMES ? JSON.parse(fsx.readFileSync(process.env.QK_ROOM_NAMES, "utf8")) : null;
const nameOf = (i) => (defaultNames && defaultNames[i - 1]) || "第" + i + "教室";

// 会记录 fillText 的假 canvas；measureText 按「当前字号」量宽：汉字 = 1 个字号宽，其它 = 0.6 个字号宽
function fakeCanvas() {
  const calls = [], bad = [];
  const state = { font: "10px sans-serif" };
  const px = () => Number((/(\d+(?:\.\d+)?)px/.exec(state.font) || [0, 10])[1]);
  const finite = (name, args) => { if (args.some((a) => typeof a === "number" && !Number.isFinite(a))) bad.push(name + " " + args.join(",")); };
  const ctx = new Proxy({
    measureText: (t) => ({ width: [...String(t)].reduce((w, ch) => w + (ch.charCodeAt(0) > 255 ? px() : px() * 0.6), 0) }),
    fillText: (t, x, y) => { finite("fillText", [x, y]); calls.push({ t: String(t), x, y, font: state.font }); },
    fillRect: (...a) => finite("fillRect", a), strokeRect: (...a) => finite("strokeRect", a),
  }, {
    get: (o, k) => (k === "font" ? state.font : k in o ? o[k] : () => {}),
    set: (o, k, v) => { if (k === "font") state.font = v; else o[k] = v; return true; },
  });
  return { canvas: { width: 0, height: 0, getContext: () => ctx }, calls, bad };
}
const mkRooms = (n) => Array.from({ length: n }, (_, i) => ({ roomName: nameOf(i + 1), expectedCount: 40, actualCount: 30 + (i % 10), absentCount: 10 - (i % 10), attendanceRate: (30 + (i % 10)) / 40 }));
const totalsOf = (n) => ({ expectedCount: 40 * n, actualCount: 35 * n, absentCount: 5 * n, attendanceRate: 0.875 });

// 1) 任意数量：1..500、再加 600/1000/1500/5000 和超大数量（历史明细、导入数据可能远超配置值）。
//    有字（textless=false）：机构名/标题/日期/地址/合计都在；每间教室的名字【和「实到/应到」】都原样完整画出，没有省略号；
//    并且名字、人数的坐标落在【自己的格子里】。字太小（textless=true）：格子里一个字都不画（不画半截），抬头合计照常。
//    任何情况：坐标有限、格子至少 1px、不画小于 3px 的字（浏览器对更小的字号量宽不可靠）。
const counts = []; for (let n = 1; n <= MAX_ROOMS; n++) counts.push(n); counts.push(600, 1000, 1500, 5000, 10000, 30000, 100000);
const run = (n, nameFn) => {
  const rooms = Array.from({ length: n }, (_, i) => ({ roomName: nameFn(i + 1), expectedCount: 40, actualCount: 30 + (i % 10), absentCount: 10 - (i % 10), attendanceRate: (30 + (i % 10)) / 40 }));
  const { canvas, calls, bad } = fakeCanvas();
  const L = draw(canvas, { title: "标题甲", examDate: "2026-01-02", rooms, totals: totalsOf(n) }, { orgName: "机构乙", orgAddress: "地址丙" }, 2);
  return { rooms, calls, bad, L, canvas };
};
const MARGIN = 40;
function checkGrid(label, n, rooms, calls, L) {
  const byText = new Map(); calls.forEach((c) => { if (!byText.has(c.t)) byText.set(c.t, []); byText.get(c.t).push(c); });
  const y0 = MARGIN + 96; // 格子紧接抬头；全部汇总画在格子下面
  rooms.forEach((r, i) => {
    const gx = MARGIN + (i % L.cols) * (L.cellW + L.gap), gy = y0 + Math.floor(i / L.cols) * (L.cellH + L.gap);
    const inCell = (c) => c.x >= gx - 0.01 && c.x <= gx + L.cellW + 0.01 && c.y >= gy - 0.01 && c.y <= gy + L.cellH + 0.01;
    const name = (byText.get(r.roomName) || []).find(inCell);
    assert.ok(name, label + " " + n + " 间：教室名 " + r.roomName + " 没有画在自己的格子里");
    const cnt = (byText.get(r.actualCount + "/" + r.expectedCount) || []).find(inCell);
    assert.ok(cnt, label + " " + n + " 间：" + r.roomName + " 的「实到/应到」没有画在自己的格子里");
  });
}
for (const n of counts) {
  const { rooms, calls, bad, L, canvas } = run(n, nameOf);
  assert.ok(L.fits, n + " 间：layout 必须有解 " + JSON.stringify(L));
  assert.strictEqual(canvas.width, 794 * 2); assert.strictEqual(canvas.height, 1123 * 2);
  assert.deepStrictEqual(bad, [], n + " 间出现非有限坐标：" + bad.slice(0, 3));
  if (L.mode === "grid") assert.ok(L.cellW >= 1 && L.cellH >= 1, n + " 间格子至少 1px");
  const texts = calls.map((c) => c.t), all = texts.join("\n"), drawn = new Set(texts);
  for (const want of ["机构乙出考率统计表", "标题甲", "2026-01-02", "地址丙", n + "个", "87.50%"]) assert.ok(all.includes(want), n + " 间：缺少 " + want);
  assert.ok(!texts.some((t) => t.endsWith("…")), n + " 间：出现省略号（名字被截断）");
  // 先单间、后汇总：「全部汇总」画在所有教室的下面（y 更大）
  const sumY = (calls.find((c) => c.t.startsWith("全部汇总")) || {}).y;
  assert.ok(sumY !== undefined, n + " 间：缺少「全部汇总」");
  const roomYs = calls.filter((c) => rooms.some((r) => r.roomName === c.t)).map((c) => c.y);
  if (roomYs.length) assert.ok(Math.max(...roomYs) < sumY, n + " 间：全部汇总必须在所有教室下面");
  assert.ok(sumY < 1123 - 40 - 28, n + " 间：全部汇总不能压到页脚");
  const named = rooms.filter((r) => drawn.has(r.roomName)).length;
  if (L.textless) assert.strictEqual(named, 0, n + " 间 textless：不应画出半截名字，实际画了 " + named);
  else {
    assert.strictEqual(named, n, n + " 间：只完整画出 " + named + " 个教室名");
    if (L.mode === "grid" && n <= 600) checkGrid("默认名", n, rooms, calls, L); // 大数量只抽查前面的数量，避免测试太慢
  }
  if (n <= MAX_ROOMS) assert.ok(!L.textless && L.legible, n + " 间（配置上限内）必须有字且看得清：" + JSON.stringify(L));
  for (const c of calls) { const m = /(\d+(?:\.\d+)?)px/.exec(c.font); if (m) assert.ok(Number(m[1]) >= 3 - 1e-9, n + " 间画了 " + m[1] + "px 的字：" + c.t); }
}
// 1b) 长名/宽字符：500 间 17 字汉字前缀 + 序号、全角字母、emoji、半角。名字很长时字号会缩小，但「要么完整要么整张都不画字」，绝不画半截
for (const [label, nameFn] of [["汉字长名", (i) => "甲乙丙丁戊己庚辛壬癸天地玄黃宇宙洪" + i], ["全角", (i) => "Ｗ".repeat(17) + i], ["emoji", (i) => "😀".repeat(12) + i], ["半角", (i) => "A" + String(i).padStart(3, "0")]]) {
  for (const n of [31, 100, 300, 500, 5000]) {
    const { rooms, calls, bad, L } = run(n, nameFn);
    assert.deepStrictEqual(bad, [], label + " " + n);
    const texts = calls.map((c) => c.t), drawn = new Set(texts);
    assert.ok(!texts.some((t) => t.endsWith("…")), label + " " + n + " 间：出现省略号");
    const named = rooms.filter((r) => drawn.has(r.roomName)).length;
    assert.ok(named === 0 || named === n, label + " " + n + " 间：只画出一部分名字 " + named + "/" + n);
    if (L.textless) assert.strictEqual(named, 0, label + " " + n);
    if (!L.textless && L.mode === "grid") checkGrid(label, n, rooms, calls, L);
  }
}
// 1c) 超过物理上限（约 50 万间）：draw 直接拒绝，不画任何东西
{
  const huge = 600000;
  const rooms = Array.from({ length: huge }, (_, i) => ({ roomName: "R" + i, expectedCount: 1, actualCount: 1, absentCount: 0, attendanceRate: 1 }));
  const drawCalls = [];
  const ctx = new Proxy({}, { get: (_, k) => (k === "measureText" ? () => ({ width: 100 }) : (...a) => drawCalls.push(k)), set: () => true });
  const L = draw({ width: 0, height: 0, getContext: () => ctx }, { title: "t", rooms, totals: {} }, {}, 2);
  assert.strictEqual(L.fits, false, "超过物理上限必须报 fits=false");
  assert.ok(!drawCalls.some((k) => k === "fillText" || k === "fillRect"), "放不下时不应该画任何东西");
}
// 1d) 一张 A4 看不清时的 HTML：每间教室都在（转义后）、顺序不变、全部汇总在所有教室后面，用户输入被转义
{
  const n = 1200;
  const rooms = Array.from({ length: n }, (_, i) => ({ roomName: i === 0 ? "<script>x</script>&教室" : "教室" + (i + 1), expectedCount: 40, actualCount: 35, absentCount: 5, attendanceRate: 0.875 }));
  const page = api.html({ title: "标<题>", examDate: "2026-01-02", rooms, totals: totalsOf(n) }, { orgName: "机构乙", orgAddress: "地址丙" });
  assert.ok(!page.includes("<script>x"), "教室名必须转义");
  assert.ok(page.includes("&lt;script&gt;x&lt;/script&gt;&amp;教室") && page.includes("标&lt;题&gt;"), "转义后的名字/标题要在");
  let at = -1;
  for (let i = 2; i <= n; i++) { const k = page.indexOf("<td>教室" + i + "</td>", at + 1); assert.ok(k > at, "HTML 缺少或乱序：教室" + i); at = k; }
  const sumAt = page.indexOf("全部汇总（" + n + " 个教室）");
  assert.ok(sumAt > at, "全部汇总必须在所有教室后面");
  for (const want of ["机构乙出考率统计表", "2026-01-02", "地址丙", "87.50%", (40 * n) + "人"]) assert.ok(page.includes(want), "HTML 缺少 " + want);
  // 何时改用 HTML：配置上限内（500 间，真实默认名）一张 A4 看得清 → 图片；5000 间看不清 → HTML
  assert.ok(layout(5000, 3.5).legible === false, "5000 间应判为看不清（改用 HTML）");
}
// 2) 字号：≤30 间不小于 14；100 间不小于 9；500 间（真实默认名）不小于 5；越多越小但不为 0
assert.ok(layout(30).font >= 14 && layout(100).font >= 9, "少量教室时字号要足够大：" + layout(30).font + "/" + layout(100).font);
if (defaultNames) {
  const { canvas } = fakeCanvas();
  const L = draw(canvas, { title: "t", examDate: "d", rooms: mkRooms(500), totals: totalsOf(500) }, {}, 2);
  assert.ok(L.font >= 5, "500 间真实默认名字号 " + L.font);
}
// 3) 同一版式内，教室越多字号不会变大
let prev = null;
for (let n = 101; n <= 600; n++) { const L = layout(n); if (prev) assert.ok(L.font <= prev + 1e-9, "格子模式字号不应随数量变大：" + n); prev = L.font; }
// 4) 版式选择：≤30 单列表格；31..100 多列表格；>100 格子
assert.strictEqual(layout(30).cols, 1); assert.strictEqual(layout(30).mode, "table");
assert.ok(layout(31).cols >= 2 && layout(31).mode === "table");
assert.strictEqual(layout(101).mode, "grid");
console.log("report-image: PASS (1.." + MAX_ROOMS + " and up to 100000 rooms on ONE sheet" + (defaultNames ? "; real default names" : "; synthetic names") + ")");
