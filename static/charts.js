"use strict";
// 数据可视化：纯 SVG，不引第三方库（内网/离线可用）。这里只负责「画」，所有数字都来自 /api/admin/analytics。
window.QkCharts = (function () {
  var NS = "http://www.w3.org/2000/svg";
  var MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  var LOW = 0.8; // 出考率低于 80% 标红
  function esc(v) { return String(v).replace(/[&<>"']/g, function (c) { return MAP[c]; }); }
  function pct(v) { return Math.round(v * 1000) / 10 + "%"; }
  function num(v) { return String(Math.round(v)); }
  function clip(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "\u2026" : s; }
  function empty(msg) { return '<div class="empty small">' + esc(msg) + "</div>"; }
  function note(msg) { return '<p class="hint chart-note">' + esc(msg) + "</p>"; }
  function svg(w, h, label, inner) {
    return '<svg xmlns="' + NS + '" viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" role="img" aria-label="' + esc(label) + '">' + inner + "</svg>";
  }
  function niceMax(v) {
    if (!(v > 0)) return 1;
    var p = Math.pow(10, Math.floor(Math.log(v) / Math.LN10)), f = v / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }
  function maxOf(list) { return Math.max.apply(null, [0].concat(list)); }

  function legendSvg(items, x, y) {
    var out = "";
    items.forEach(function (it, i) {
      var lx = x + i * 70;
      out += '<rect x="' + lx + '" y="' + (y - 9) + '" width="12" height="12" rx="2" class="' + it.cls + '"/><text x="' + (lx + 17) + '" y="' + (y + 2) + '" class="ca">' + esc(it.text) + "</text>";
    });
    return out;
  }
  function grid(left, top, plotH, W, maxV, fmt) {
    var out = "";
    for (var t = 0; t <= 4; t++) {
      var y = top + plotH - (plotH * t) / 4;
      out += '<line x1="' + left + '" x2="' + (W - 8) + '" y1="' + y + '" y2="' + y + '" class="cg"/>';
      out += '<text x="' + (left - 6) + '" y="' + (y + 4) + '" text-anchor="end" class="ca">' + esc(fmt((maxV * t) / 4)) + "</text>";
    }
    return out;
  }

  // 竖向分组柱：groups=[{label,sub,tip,values:[..],cls?:[..]}]，o.series=[{cls}]
  function xlabel(x, y, label, sub, rotate) {
    if (!rotate) return '<text x="' + x + '" y="' + (y + 17) + '" text-anchor="middle" class="ct">' + esc(clip(label, 8)) + '</text><text x="' + x + '" y="' + (y + 33) + '" text-anchor="middle" class="ca">' + esc(sub || "") + "</text>";
    return '<text x="' + x + '" y="' + (y + 15) + '" text-anchor="middle" class="ca">' + esc(sub || "") + '</text><text transform="translate(' + (x + 4) + "," + (y + 30) + ') rotate(-35)" text-anchor="end" class="ct">' + esc(clip(label, 12)) + "</text>";
  }
  function columns(groups, o) {
    var gw = o.gw || 76, left = o.rotate ? 72 : 52, top = o.legend ? 32 : 16, plotH = 190, bottom = o.rotate ? 104 : 54, n = o.series.length;
    // 铺满容器：组数少时把每组拉宽（有上限，免得两三场考试的柱子粗得离谱）；fit 模式（分布图）则必须缩到容器内放得下，不能靠横向滚动藏数据
    if (o.avail) gw = o.fit ? Math.max(40, Math.floor((o.avail - left - 16) / groups.length)) : Math.max(gw, Math.min(o.maxGw || 120, Math.floor((o.avail - left - 16) / groups.length)));
    var maxV = o.yMax || niceMax(maxOf(groups.map(function (g) { return maxOf(g.values); })));
    var W = Math.max(o.fit ? 0 : 440, left + groups.length * gw + 16), H = top + plotH + bottom;
    var out = grid(left, top, plotH, W, maxV, o.fmt);
    if (o.legend) out += legendSvg(o.legend, left, 14);
    groups.forEach(function (g, i) {
      var gx = left + i * gw + 7, bw = (gw - 14) / n;
      g.values.forEach(function (v, k) {
        var h = (plotH * v) / maxV, cls = (g.cls && g.cls[k]) || o.series[k].cls;
        out += '<rect x="' + (gx + k * bw).toFixed(1) + '" y="' + (top + plotH - h).toFixed(1) + '" width="' + (bw - 2).toFixed(1) + '" height="' + h.toFixed(1) + '" class="' + cls + '"/>';
        if (n === 1) out += '<text x="' + (gx + bw / 2 - 1).toFixed(1) + '" y="' + (top + plotH - h - 4).toFixed(1) + '" text-anchor="middle" class="cv">' + esc(o.fmt(v)) + "</text>";
      });
      out += xlabel(left + i * gw + gw / 2, top + plotH, g.label, g.sub, o.rotate);
      out += '<rect x="' + (left + i * gw) + '" y="' + top + '" width="' + gw + '" height="' + plotH + '" class="hit"><title>' + esc(g.tip) + "</title></rect>";
    });
    return svg(W, H, o.label, out);
  }

  // 折线：points=[{label,sub,value,tip}]
  function lines(points, o) {
    var step = o.gw || 60, left = o.rotate ? 72 : 52, top = 16, plotH = 190, bottom = o.rotate ? 104 : 54;
    if (o.avail) step = Math.max(step, Math.min(o.maxGw || 200, Math.floor((o.avail - left - 16) / points.length)));
    var maxV = o.yMax || niceMax(maxOf(points.map(function (p) { return p.value; })));
    var W = Math.max(440, left + points.length * step + 16), H = top + plotH + bottom;
    var out = grid(left, top, plotH, W, maxV, o.fmt), path = [], every = o.rotate ? 1 : Math.ceil(points.length / Math.max(1, Math.floor((W - left) / 70)));
    points.forEach(function (p, i) {
      var x = left + i * step + step / 2, y = top + plotH - (plotH * p.value) / maxV;
      path.push(x.toFixed(1) + "," + y.toFixed(1));
      if (i % every === 0) out += xlabel(x, top + plotH, p.label, p.sub, o.rotate);
    });
    if (path.length > 1) out += '<polyline points="' + path.join(" ") + '" class="cl"/>';
    points.forEach(function (p, i) {
      var x = left + i * step + step / 2, y = top + plotH - (plotH * p.value) / maxV;
      out += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="5" class="' + (o.low && p.value < o.low ? "dot-bad" : "dot") + '"><title>' + esc(p.tip) + "</title></circle>";
      if (points.length <= 14) out += '<text x="' + x.toFixed(1) + '" y="' + (y - 9).toFixed(1) + '" text-anchor="middle" class="cv">' + esc(o.fmt(p.value)) + "</text>";
    });
    return svg(W, H, o.label, out);
  }

  // 横向条形：items=[{label,value,text,cls,tip}]
  function hbars(items, o) {
    var Wd = Math.max(300, o.avail || 560), L = 96, R = 76, RH = 26, H = items.length * RH + 8;
    var top = o.max || maxOf(items.map(function (i) { return i.value; })) || 1, out = "";
    items.forEach(function (it, k) {
      var y = 4 + k * RH, bw = Math.max(it.value > 0 ? 2 : 0, ((Wd - L - R) * it.value) / top);
      out += '<text x="' + (L - 8) + '" y="' + (y + 17) + '" text-anchor="end" class="ct">' + esc(clip(it.label, 9)) + "</text>";
      out += '<rect x="' + L + '" y="' + (y + 3) + '" width="' + bw.toFixed(1) + '" height="' + (RH - 8) + '" class="' + it.cls + '"><title>' + esc(it.tip) + "</title></rect>";
      out += '<text x="' + (L + bw + 6).toFixed(1) + '" y="' + (y + 17) + '" class="cv">' + esc(it.text) + "</text>";
    });
    return svg(Wd, H, o.label, out);
  }

  function examTip(e) {
    return e.title + " " + e.examDate + "\n教室 " + e.rooms + "，应到 " + e.expected + "，实到 " + e.actual + "，缺考 " + e.absent + "，出考率 " + pct(e.rate);
  }
  function roomTip(r) {
    return r.roomName + "（考过 " + r.exams + " 场）\n应到 " + r.expected + "，实到 " + r.actual + "，缺考 " + r.absent + "，出考率 " + pct(r.rate);
  }

  function compare(el, exams, metric) {
    if (!exams.length) { el.innerHTML = empty("没有数据"); return; }
    var groups = exams.map(function (e) {
      return {
        label: e.title, sub: e.examDate, tip: examTip(e),
        values: metric === "people" ? [e.expected, e.actual, e.absent] : metric === "rate" ? [e.rate] : [e.absent],
        cls: metric === "rate" ? [e.rate < LOW ? "c-abs" : "c-act"] : null,
      };
    });
    var people = [{ cls: "c-exp" }, { cls: "c-act" }, { cls: "c-abs" }];
    el.innerHTML = (exams.length > 20 ? note("共 " + exams.length + " 场考试，图可以左右滑动；想看细一点就缩小日期范围或按标题筛选。") : "") +
      columns(groups, {
        label: "多场考试对比", series: metric === "people" ? people : [{ cls: metric === "rate" ? "c-act" : "c-abs" }],
        fmt: metric === "rate" ? pct : num, yMax: metric === "rate" ? 1 : 0,
        legend: metric === "people" ? [{ cls: "c-exp", text: "应到" }, { cls: "c-act", text: "实到" }, { cls: "c-abs", text: "缺考" }] : null,
        rotate: true, gw: metric === "people" ? 84 : 64, avail: el.clientWidth,
      });
  }

  function trend(el, exams, metric) {
    if (!exams.length) { el.innerHTML = empty("没有数据"); return; }
    var pick = { rate: "rate", expected: "expected", actual: "actual", absent: "absent" }[metric];
    var points = exams.map(function (e) { return { label: e.title, sub: e.examDate, value: e[pick], tip: examTip(e) }; });
    el.innerHTML = (exams.length > 20 ? note("共 " + exams.length + " 场考试，图可以左右滑动。") : "") +
      lines(points, { label: "考试趋势", fmt: metric === "rate" ? pct : num, yMax: metric === "rate" ? 1 : 0, low: metric === "rate" ? LOW : 0, rotate: true, gw: 70, avail: el.clientWidth });
  }

  function rooms(el, list, metric, showAll) {
    var rows = list.filter(function (r) { return metric !== "rate" || r.expected > 0; });
    if (!rows.length) { el.innerHTML = empty("没有数据"); return; }
    rows = rows.slice().sort(function (a, b) {
      return metric === "rate" ? a.rate - b.rate || a.roomName.localeCompare(b.roomName) : b[metric] - a[metric] || a.roomName.localeCompare(b.roomName);
    });
    var limit = showAll ? rows.length : 15, cut = rows.length - limit;
    rows = rows.slice(0, limit);
    var items = rows.map(function (r) {
      return {
        label: r.roomName, value: r[metric], tip: roomTip(r),
        text: metric === "rate" ? pct(r.rate) : num(r[metric]) + " 人",
        cls: metric === "rate" ? (r.rate < LOW ? "c-abs" : "c-act") : metric === "absent" ? "c-abs" : "c-exp",
      };
    });
    var more = cut > 0 ? '<p class="hint chart-note">共 ' + (rows.length + cut) + " 间教室，只列" + (metric === 'rate' ? "出考率最低的" : "最多的") + " " + rows.length + ' 间。 <button type="button" class="link-btn" data-showall="1">展开全部</button></p>' : (showAll && rows.length > 15 ? '<p class="hint chart-note"><button type="button" class="link-btn" data-showall="0">只看前 15 间</button></p>' : "");
    el.innerHTML = more + hbars(items, { label: "教室对比", max: metric === "rate" ? 1 : 0, avail: el.clientWidth });
  }

  function top(el, list) {
    if (!list.length) { el.innerHTML = empty("没有缺考记录"); return; }
    el.innerHTML = hbars(list.map(function (r) {
      return { label: r.roomName, value: r.absent, text: r.absent + " 人", cls: "c-abs", tip: roomTip(r) };
    }), { label: "缺考最多的教室", avail: el.clientWidth });
  }

  function dist(el, buckets) {
    var total = buckets.reduce(function (s, b) { return s + b.count; }, 0);
    if (!total) { el.innerHTML = empty("没有数据"); return; }
    el.innerHTML = columns(buckets.map(function (b, i) {
      return { label: b.label, sub: "", tip: b.label + "：" + b.count + " 间教室", values: [b.count], cls: [i < 3 ? "c-abs" : "c-act"] };
    }), { label: "出考率分布", series: [{ cls: "c-act" }], fmt: num, gw: 60, fit: true, avail: el.clientWidth || 420 });
  }

  function roomHistory(el, history, roomName) {
    if (!roomName) { el.innerHTML = empty("在右上角选一间教室，看它历次考试的出考率"); return; }
    if (!history.length) { el.innerHTML = empty(roomName + " 在当前筛选范围内没有记录"); return; }
    el.innerHTML = lines(history.map(function (h) {
      return { label: h.title, sub: h.examDate, value: h.rate, tip: h.title + " " + h.examDate + "\n应到 " + h.expected + "，实到 " + h.actual + "，缺考 " + h.absent + "，出考率 " + pct(h.rate) };
    }), { label: roomName + " 历次出考率", fmt: pct, yMax: 1, low: LOW, rotate: true, gw: 70, avail: el.clientWidth });
  }

  return { compare: compare, trend: trend, rooms: rooms, top: top, dist: dist, roomHistory: roomHistory };
})();
