// 图表必须画出【全部】数据：不允许静默截断（需求：数据可视化针对全部数据）。node tests/charts_all_data.cjs
const assert = require("node:assert");
global.window = {};
require("../static/charts.js");
const C = window.QkCharts;
const el = () => ({ innerHTML: "", clientWidth: 520 });

// 1) 考试对比、趋势：250 场考试，第一场和最后一场的日期都必须出现在图里
const exams = [];
for (let i = 0; i < 250; i++) {
  const d = new Date(Date.UTC(2020, 0, 1 + i)).toISOString().slice(0, 10);
  exams.push({ title: "考试" + i, examDate: d, rooms: 3, batches: 1, records: 3, expected: 90, actual: 80, absent: 10, rate: 80 / 90 });
}
for (const [name, fn] of [["compare", (e, m) => C.compare(e, exams, m)], ["trend", (e, m) => C.trend(e, exams, m)]]) {
  const e = el();
  fn(e, name === "compare" ? "people" : "rate");
  assert.ok(e.innerHTML.includes(exams[0].examDate), name + " 少了最早一场");
  assert.ok(e.innerHTML.includes(exams[249].examDate), name + " 少了最近一场");
  assert.ok(!/只画最近/.test(e.innerHTML), name + " 不能再提示“只画最近”");
  assert.strictEqual((e.innerHTML.match(/<title>/g) || []).length >= 250, true, name + " 每场考试都要有一个可悬停的数据点/柱");
}
// 2) 教室对比：250 间，展开全部后每一间都在，且不再提供“展开全部”
const rooms = [];
for (let i = 1; i <= 250; i++) rooms.push({ roomName: "第" + i + "教室", exams: 2, expected: 60, actual: 50 + (i % 9), absent: 10 - (i % 9), rate: (50 + (i % 9)) / 60 });
const folded = el(); C.rooms(folded, rooms, "rate", false);
assert.ok(folded.innerHTML.includes("展开全部"), "折叠状态要有“展开全部”");
const all = el(); C.rooms(all, rooms, "rate", true);
for (let i = 1; i <= 250; i++) assert.ok(all.innerHTML.includes("第" + i + "教室"), "展开全部后缺少 第" + i + "教室");
assert.ok(!all.innerHTML.includes("展开全部"), "已展开时不能再显示“展开全部”");
assert.ok(all.innerHTML.includes("只看前 15 间"), "已展开时提供收起");
console.log("charts show all data: PASS");
