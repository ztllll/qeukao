"use strict";
// 统计表导图：竖版 A4（210×297mm，按 96dpi 的 794×1123 逻辑像素，2 倍清晰度），任意数量的教室都在同一张里。
// 版面规则：≤30 间单列表格；31–100 间自动 2–3 列表格；更多用紧凑格子（每间一格：教室名 + 实到/应到）。始终一张；字号按最长教室名的实际宽度连续自适应，名字不截断。
(function (root) {
  var PAGE = { w: 794, h: 1123 };
  var MARGIN = 40;
  var SINGLE_COLUMN_MAX = 30;
  var MAX_ROW = 40;
  var HEADER_H = 150; // 机构名 + 标题 + 日期
  var METRICS_H = 78;
  var TABLE_HEAD_H = 34;
  var FOOT_H = 56;

  var TABLE_MAX = 100;     // 超过这个数，表格行在一张 A4 上无法保持可读，切到紧凑格子
  var MIN_ROW_H = 20;      // 表格模式：行高下限
  var MIN_FONT = 9;        // 表格模式：字号下限
  var MIN_DRAW_FONT = 3;   // 小于 3px 的字看不清，浏览器对这种字号的字宽还会按整数像素取整、量出来不可靠；低于它格子里就只画色块不画字
  var LEGIBLE_FONT = 5;    // 格子模式字号低于它（约 3.75pt）就不算「看得清」：仍然画在一张里，但导出时要提示管理员
  var MAX_ROOMS = 500;     // 基本信息允许的教室数上限；历史明细可能更多（Excel 导入），layout 对任意数量都给出一张的版面
  var DENSE_HEADER_H = 96, DENSE_METRICS_H = 56; // 格子模式用紧凑抬头，把高度让给教室
  var WEIGHTS = [1.5, 1, 1, 1, 1.3];
  var WSUM = 5.8;

  function bodyHeight(dense) { return PAGE.h - MARGIN * 2 - (dense ? DENSE_HEADER_H : HEADER_H) - (dense ? DENSE_METRICS_H : METRICS_H) - FOOT_H - 24; }

  // 纯函数：给定教室数和「最长教室名的宽度」（单位 em = 字号的倍数，由 measureNameEm 用真实 canvas 量出），算出版面。tests/report_image_layout.cjs 直接调用。
  // 版面按实测的名字宽度算，字号连续自适应：名字绝不截断，教室再多也在这一张里，只是字越来越小（legible=false 时调用方要提示）。
  //   table：≤30 单列；31..100 自动 2-3 列（名字放不下时改走格子）；行高 20..40、字号 9..16
  //   grid ：每间一个小格（教室名 + 实到/应到），列数 3..60 里挑能让字号最大的那个
  function layout(roomCount, nameEm) {
    var chars = Math.max(1, nameEm || 5), inner = PAGE.w - MARGIN * 2, gap = 12;
    if (roomCount <= TABLE_MAX) {
      var avail = bodyHeight() - TABLE_HEAD_H;
      for (var cols = roomCount <= SINGLE_COLUMN_MAX ? 1 : 2; cols <= 3; cols++) {
        var perCol = Math.ceil(roomCount / cols);
        var row = Math.min(MAX_ROW, Math.floor(avail / Math.max(1, perCol)));
        var colW = (inner - (cols - 1) * gap) / cols;
        var nameW = colW * WEIGHTS[0] / WSUM - 8;
        var font = Math.min(16, Math.floor(row / 1.6), Math.floor((colW * 1.3 / WSUM - 8) / 4.4), Math.floor(nameW / (chars + 0.1)));
        if (row >= MIN_ROW_H && font >= MIN_FONT) {
          return { mode: "table", cols: cols, perCol: perCol, rowH: row, colW: colW, gap: gap, font: font, dense: false, fits: perCol * row <= avail, legible: true };
        }
      }
    }
    // 格子模式：列数不设上限，间隙随数量收紧（4→1→0），所以对任意数量都有解（物理上限是每格至少 1×1 px，约 50 万间）。
    var availH = bodyHeight(true), best = null;
    [4, 1, 0].forEach(function (gapG) {
      if (best && best.legible) return; // 已经有看得清的版面就不再收紧间隙
      for (var c = 3; c <= Math.min(Math.max(3, roomCount), 800); c++) {
        var cellW = (inner - (c - 1) * gapG) / c, rows = Math.ceil(roomCount / c), cellH = Math.floor((availH - (rows - 1) * gapG) / rows);
        if (cellW < 1 || cellH < 1) continue;
        var f = Math.floor(Math.min(13, cellH / 2.7, (cellW - 4) / (Math.max(chars, 3.2) + 0.3)) * 10) / 10;
        if (f < 0) f = 0;
        var cand = { mode: "grid", cols: c, rows: rows, cellW: cellW, cellH: cellH, gap: gapG, font: f, dense: true, fits: rows * cellH + (rows - 1) * gapG <= availH, legible: f >= LEGIBLE_FONT, textless: f < MIN_DRAW_FONT };
        if (cand.fits && (!best || f > best.font || (f === best.font && cellW * cellH > best.cellW * best.cellH))) best = cand;
      }
    });
    return best || { mode: "grid", cols: 0, rows: 0, cellW: 0, cellH: 0, gap: 0, font: 0, dense: true, fits: false, legible: false, textless: true };
  }

  // 用真实 canvas 以 100px 粗体量每个教室名，取最宽的，换算成 em。全角、emoji、半角都按浏览器实际字体算。
  function measureNameEm(rooms, ctx) {
    ctx.font = "700 100px sans-serif";
    var m = 1;
    rooms.forEach(function (r) {
      var w = ctx.measureText(String(r.roomName || "")).width / 100;
      if (w > m) m = w;
    });
    return m;
  }

  // 格子模式的最后一道关：按最终字号用真实字体再量一遍所有名字和「实到/应到」，放不下就继续缩；缩到画不出来（<MIN_DRAW_FONT）就只画色块。
  // layout 里的 em 是在 100px 下量的，小字号下浏览器的字宽取整后会偏大，所以这里必须按最终字号复核。
  function fitGridFont(ctx, rooms, L) {
    var f = L.font, limit = L.cellW - 4;
    while (f >= MIN_DRAW_FONT) {
      var widest = 0;
      ctx.font = "700 " + f + "px sans-serif";
      rooms.forEach(function (r) { var w = ctx.measureText(String(r.roomName || "")).width; if (w > widest) widest = w; });
      ctx.font = f + "px sans-serif";
      rooms.forEach(function (r) { var w = ctx.measureText(r.actualCount + "/" + r.expectedCount).width; if (w > widest) widest = w; });
      if (widest <= limit) break;
      f = Math.round((f - 0.5) * 10) / 10;
    }
    var out = {};
    Object.keys(L).forEach(function (k) { out[k] = L[k]; });
    out.textless = f < MIN_DRAW_FONT;
    out.font = out.textless ? 0 : f;
    out.legible = f >= LEGIBLE_FONT;
    return out;
  }

  function rate(v) { return (Number(v || 0) * 100).toFixed(2) + "%"; }
  function people(v) { return Number(v || 0) + "人"; }
  function today() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function nowMinute() {
    var d = new Date();
    return today() + " " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function safeName(v) { return String(v || "出考率统计表").replace(/[\\/:*?"<>|]/g, "-"); }

  // 文字超宽时截断并加省略号，保证不会画出格子
  function fit(ctx, text, width) {
    var s = String(text);
    if (ctx.measureText(s).width <= width) return s;
    while (s.length > 1 && ctx.measureText(s + "…").width > width) s = s.slice(0, -1);
    return s + "…";
  }
  function text(ctx, str, x, y, o) {
    o = o || {};
    var font = o.font || "16px sans-serif";
    ctx.fillStyle = o.color || "#1d2833";
    ctx.font = font;
    if (o.width && o.minPx) { // 先缩字号再考虑省略号：长标题/长机构名尽量完整
      var px = Number((/(\d+(?:\.\d+)?)px/.exec(font) || [0, 16])[1]);
      while (px > o.minPx && ctx.measureText(String(str)).width > o.width) { px -= 1; font = font.replace(/\d+(?:\.\d+)?px/, px + "px"); ctx.font = font; }
    }
    ctx.textAlign = o.align || "left";
    ctx.textBaseline = o.baseline || "middle";
    ctx.fillText(o.width ? fit(ctx, str, o.width) : str, x, y);
  }
  function cell(ctx, str, x, y, w, h, o) {
    o = o || {};
    if (o.bg) { ctx.fillStyle = o.bg; ctx.fillRect(x, y, w, h); }
    ctx.strokeStyle = "#c9d3de"; ctx.lineWidth = 1; ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    text(ctx, str, x + w / 2, y + h / 2, { align: "center", font: o.font, color: o.color, width: w - 8 });
  }

  // site: {orgName, orgAddress}；rooms 已按教室顺序排好
  function draw(canvas, data, site, scale) {
    var rooms = data.rooms, totals = data.totals || {}, ctx = canvas.getContext("2d"), L = layout(rooms.length, measureNameEm(rooms, ctx));
    if (!L.fits) return L; // 超过约 50 万间才会到这里；不画，免得 NaN 坐标画出乱图
    canvas.width = PAGE.w * scale; canvas.height = PAGE.h * scale;
    ctx.scale(scale, scale);
    if (L.mode === "grid" && !L.textless) L = fitGridFont(ctx, rooms, L);
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, PAGE.w, PAGE.h);
    ctx.strokeStyle = "#1d2833"; ctx.lineWidth = 1.5; ctx.strokeRect(MARGIN / 2, MARGIN / 2, PAGE.w - MARGIN, PAGE.h - MARGIN);

    var inner = PAGE.w - MARGIN * 2, cx = PAGE.w / 2, y = MARGIN + 8, dn = L.dense, headerH = dn ? DENSE_HEADER_H : HEADER_H, metricsH = dn ? DENSE_METRICS_H : METRICS_H;
    text(ctx, (site.orgName || "") + "出考率统计表", cx, y + (dn ? 14 : 22), { align: "center", font: "700 " + (dn ? 24 : 30) + "px sans-serif", width: inner, minPx: 14 });
    text(ctx, data.title || "未设置标题", cx, y + (dn ? 42 : 66), { align: "center", font: "800 " + (dn ? 18 : 24) + "px sans-serif", color: "#b42318", width: inner, minPx: 12 });
    text(ctx, "考试日期：" + (data.examDate || today()), cx, y + (dn ? 66 : 102), { align: "center", font: (dn ? 13 : 16) + "px sans-serif", color: "#475569" });

    y = MARGIN + headerH;
    // 先列每间教室，最后是「全部汇总」（紧跟在最后一间教室下面；版面高度已为它预留 metricsH）
    function summary(yTop) {
      var mg = 10, mw = (inner - mg * 4) / 5, sy = yTop + 12;
      [["全部汇总 · 教室", rooms.length + "个"], ["应到合计", people(totals.expectedCount)], ["实到合计", people(totals.actualCount)],
       ["缺考合计", people(totals.absentCount)], ["总出考率", rate(totals.attendanceRate)]].forEach(function (m, i) {
        var x = MARGIN + i * (mw + mg);
        ctx.fillStyle = "#eef3f8"; ctx.fillRect(x, sy, mw, metricsH - 10);
        ctx.strokeStyle = "#1d3a5f"; ctx.lineWidth = 1.2; ctx.strokeRect(x + 0.5, sy + 0.5, mw - 1, metricsH - 11); ctx.lineWidth = 1;
        text(ctx, m[0], x + mw / 2, sy + (dn ? 13 : 17), { align: "center", font: (dn ? 11 : 13) + "px sans-serif", color: "#475569", width: mw - 6 });
        text(ctx, m[1], x + mw / 2, sy + (dn ? 33 : 43), { align: "center", font: "800 " + (dn ? 16 : 20) + "px sans-serif", color: i === 3 ? "#b42318" : "#1d2833", width: mw - 6 });
      });
    }
    // 列：教室 / 应到 / 实到 / 缺考 / 出考率（单页导图里不再放「日期时间」，日期已在标题区）
    var weights = WEIGHTS, sum = WSUM;
    if (L.mode === "grid") {
      rooms.forEach(function (r, i) {
        var gc = i % L.cols, gr = Math.floor(i / L.cols);
        var gx = MARGIN + gc * (L.cellW + L.gap), gy = y + gr * (L.cellH + L.gap);
        var low = Number(r.expectedCount) > 0 && Number(r.actualCount) / Number(r.expectedCount) < 0.8;
        ctx.fillStyle = low ? "#fdecea" : "#f7f9fb"; ctx.fillRect(gx, gy, L.cellW, L.cellH);
        if (L.cellW >= 4 && L.cellH >= 4) { ctx.strokeStyle = "#c9d3de"; ctx.strokeRect(gx + 0.5, gy + 0.5, L.cellW - 1, L.cellH - 1); }
        if (L.textless) return; // 格子比 1px 字还小：只剩色块（红色 = 出考率低于 80%），名字和人数看明细表
        text(ctx, r.roomName, gx + L.cellW / 2, gy + L.cellH * 0.28, { align: "center", font: "700 " + L.font + "px sans-serif", width: L.cellW - 4 });
        text(ctx, r.actualCount + "/" + r.expectedCount, gx + L.cellW / 2, gy + L.cellH * 0.74, { align: "center", font: L.font + "px sans-serif", color: low ? "#b42318" : "#475569", width: L.cellW - 4 });
      });
      summary(y + L.rows * (L.cellH + L.gap) - L.gap);
      return finish(ctx, site, cx, inner, L);
    }
    for (var c = 0; c < L.cols; c++) {
      var x0 = MARGIN + c * (L.colW + L.gap), x = x0;
      ["教室", "应到", "实到", "缺考", "出考率"].forEach(function (h, i) {
        var w = (L.colW * weights[i]) / sum;
        cell(ctx, h, x, y, w, TABLE_HEAD_H, { bg: "#e9eff5", color: "#334155", font: "700 " + Math.min(15, L.font + 1) + "px sans-serif" });
        x += w;
      });
    }
    rooms.forEach(function (r, i) {
      var c = Math.floor(i / L.perCol), k = i % L.perCol;
      var x = MARGIN + c * (L.colW + L.gap), ry = y + TABLE_HEAD_H + k * L.rowH;
      [r.roomName, people(r.expectedCount), people(r.actualCount), people(r.absentCount), rate(r.attendanceRate)].forEach(function (v, j) {
        var w = (L.colW * weights[j]) / sum;
        cell(ctx, v, x, ry, w, L.rowH, { bg: i % 2 ? "#fafbfc" : "#ffffff", font: L.font + "px sans-serif", color: j === 3 && r.absentCount > 0 ? "#b42318" : "#1d2833" });
        x += w;
      });
    });
    summary(y + TABLE_HEAD_H + L.perCol * L.rowH);

    return finish(ctx, site, cx, inner, L);
  }

  function finish(ctx, site, cx, inner, L) {
    var fy = PAGE.h - MARGIN - 8;
    if (site.orgAddress) text(ctx, (site.orgName || "") + " · " + site.orgAddress, cx, fy - 20, { align: "center", font: "13px sans-serif", color: "#475569", width: inner, minPx: 9 });
    else if (site.orgName) text(ctx, site.orgName, cx, fy - 20, { align: "center", font: "13px sans-serif", color: "#475569", width: inner });
    text(ctx, "导出时间：" + nowMinute(), cx, fy, { align: "center", font: "13px sans-serif", color: "#667382" });
    return L;
  }

  // 一张 A4 放不下（字号会小于 LEGIBLE_FONT）时改用 HTML：先列每间教室，最后是全部汇总；浏览器里可直接看，打印时自动分页。
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function html(data, site) {
    var rooms = data.rooms || [], t = data.totals || {}, org = esc(site.orgName || "");
    var rows = rooms.map(function (r, i) {
      return "<tr><td>" + (i + 1) + "</td><td>" + esc(r.roomName) + "</td><td>" + esc(people(r.expectedCount)) + "</td><td>" + esc(people(r.actualCount)) +
        "</td><td" + (Number(r.absentCount) > 0 ? " class=\"abs\"" : "") + ">" + esc(people(r.absentCount)) + "</td><td>" + esc(rate(r.attendanceRate)) + "</td></tr>";
    }).join("\n");
    return "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>" + esc(data.title || "出考率统计表") + "</title><style>" +
      "@page{size:A4 portrait;margin:14mm}body{font-family:'Microsoft YaHei UI','Microsoft YaHei','PingFang SC',sans-serif;color:#1d2833;max-width:900px;margin:24px auto;padding:0 16px}" +
      "h1{text-align:center;font-size:26px;margin:0}h2{text-align:center;color:#b42318;font-size:20px;margin:8px 0}.date{text-align:center;color:#475569}" +
      "table{width:100%;border-collapse:collapse;margin-top:16px}th,td{border:1px solid #c9d3de;padding:5px 8px;text-align:center}thead th{background:#e9eff5}thead{display:table-header-group}" +
      "tbody tr:nth-child(even){background:#fafbfc}.abs{color:#b42318}tfoot{display:table-row-group}tfoot td{background:#eef3f8;font-weight:800;border-top:2px solid #1d3a5f}" +
      ".foot{text-align:center;color:#667382;font-size:13px;margin-top:18px}</style></head><body>" +
      "<h1>" + org + "出考率统计表</h1><h2>" + esc(data.title || "未设置标题") + "</h2><div class=\"date\">考试日期：" + esc(data.examDate || today()) + "</div>" +
      "<table><thead><tr><th>序号</th><th>教室</th><th>应到</th><th>实到</th><th>缺考</th><th>出考率</th></tr></thead><tbody>\n" + rows + "\n</tbody>" +
      "<tfoot><tr><td colspan=\"2\">全部汇总（" + rooms.length + " 个教室）</td><td>" + esc(people(t.expectedCount)) + "</td><td>" + esc(people(t.actualCount)) +
      "</td><td class=\"abs\">" + esc(people(t.absentCount)) + "</td><td>" + esc(rate(t.attendanceRate)) + "</td></tr></tfoot></table>" +
      "<div class=\"foot\">" + org + (site.orgAddress ? " · " + esc(site.orgAddress) : "") + "<br>导出时间：" + esc(nowMinute()) + "</div></body></html>";
  }

  var api = { layout: layout, MAX_ROOMS: MAX_ROOMS, draw: draw, html: html, PAGE: PAGE, safeName: safeName, today: today, TABLE_MAX: TABLE_MAX };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.QkReportImage = api;

  // 页面入口：downloadReportSnapshotImage({title, examDate, rooms, totals}, site)。返回 1=一张 A4 图片；2=教室太多一张 A4 看不清，改为下载 HTML 网页（先单间、后全部汇总）；0=没有教室。
  root.downloadReportSnapshotImage = function (data, site) {
    var rooms = Array.isArray(data.rooms) ? data.rooms : [];
    if (rooms.length === 0) return 0;
    var payload = { title: data.title, examDate: data.examDate, rooms: rooms, totals: data.totals };
    var canvas = document.createElement("canvas");
    var L0 = draw(canvas, payload, site || {}, 2);
    var link = document.createElement("a"), base = safeName(data.title) + "-" + (data.examDate || today());
    if (L0.fits && L0.legible && !L0.textless) {
      link.download = base + ".png";
      link.href = canvas.toDataURL("image/png");
    } else {
      link.download = base + ".html";
      link.href = URL.createObjectURL(new Blob([html(payload, site || {})], { type: "text/html;charset=utf-8" }));
      setTimeout(function () { URL.revokeObjectURL(link.href); }, 60000);
    }
    document.body.appendChild(link); link.click(); link.remove();
    return link.download.endsWith(".png") ? 1 : 2; // 1 = A4 图片；2 = 一张 A4 看不清，改为 HTML
  };
})(typeof window !== "undefined" ? window : globalThis);
