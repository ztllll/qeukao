// 前端关键边界回归检查（真实服务端 + 无头浏览器）。运行：scripts/ui_regression.sh
// 钉住审查发现的四个问题：①关闭态不再弹「数据未验收」；②一次确认只下发一次且对话框是真模态；
// ③会话过期的 401 回登录页（旧密码错的 401 仍留在表单）；④切换视图后只剩一条轮询链。
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const base = process.env.BASE;
const fails = [];
const check = (cond, msg) => { console.log((cond ? "ok   " : "FAIL ") + msg); if (!cond) fails.push(msg); };
const post = async (path, body, cookie) => {
  const r = await fetch(base + path, { method: "POST", headers: { "Content-Type": "application/json", ...(cookie ? { Cookie: cookie } : {}) }, body: JSON.stringify(body) });
  return { status: r.status, cookie: (r.headers.get("set-cookie") || "").split(";")[0], json: await r.json() };
};
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME });
  // ---- ① closed session while the fill page still shows "open" ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/dispatch", { mode: "now", title: "回归场次" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(800);
    await post("/api/admin/accept", {}, ck);
    await page.click("#confirmRoomButton"); await page.waitForTimeout(600);
    const s = await page.evaluate(() => ({ closed: document.body.classList.contains("is-closed"), dialog: document.querySelector("#appDialog").classList.contains("open") }));
    check(s.closed && !s.dialog, "关闭态：只显示空状态，不再弹「数据未验收」(closed=" + s.closed + ", dialog=" + s.dialog + ")");
  }
  // ---- ⑦ 前台只能填报：没有管理入口、验收、改项目、导图、改数据，也没有密码框；教室名单/机构名来自后台配置 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/site", { orgName: "回归考点", orgAddress: "回归路 1 号", roomCount: 3, roomNames: ["甲教室", "乙教室", "丙教室"] }, ck);
    await post("/api/admin/dispatch", { mode: "now", title: "前台回归场次", examDate: "2026-11-11" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(1200);
    const gone = await page.evaluate(() => ({
      adminLink: !!document.querySelector('a[href="/admin"]'), accept: !!document.querySelector("#acceptButton"),
      editProject: !!document.querySelector("#editProjectButton"), exportBtn: !!document.querySelector("#exportSnapshotButton"),
      password: !!document.querySelector('input[type="password"]'), editRow: !!document.querySelector(".row-edit-button"),
      text: document.body.innerText,
    }));
    check(!gone.adminLink && !gone.accept && !gone.editProject && !gone.exportBtn && !gone.password && !gone.editRow,
      "前台没有管理员入口/验收/改项目/导图/密码框/改数据按钮 (" + JSON.stringify({ ...gone, text: undefined }) + ")");
    check(/回归考点/.test(gone.text) && !/示例考试中心/.test(gone.text), "前台机构名来自后台配置，不再写死");
    check(/前台回归场次/.test(gone.text), "前台只读显示管理员下发时填的标题");
    await page.click("#changeRoomButton"); await page.waitForTimeout(300);
    const rooms = await page.evaluate(() => [...document.querySelectorAll("#classroomGrid .classroom-option")].map((n) => n.textContent));
    check(JSON.stringify(rooms) === JSON.stringify(["甲教室", "乙教室", "丙教室"]), "教室选项来自后台配置: " + JSON.stringify(rooms));
    // submit 乙教室 through the 3 steps; afterwards nothing on the page can change it
    await page.click('#classroomGrid .classroom-option:nth-child(2)');
    await page.click("#confirmRoomButton"); await page.waitForTimeout(300);
    await page.evaluate(() => document.querySelector("#appDialogConfirm").click()); await page.waitForTimeout(400);
    // 人数框只收数字：全角数字转半角，字母/负号/科学计数法都去掉；鼠标滚轮不能偷偷改数
    await page.click("#expectedCount"); await page.keyboard.type("４e0-");
    const typed = await page.inputValue("#expectedCount");
    const eb = await page.locator("#expectedCount").boundingBox();
    await page.mouse.move(eb.x + eb.width / 2, eb.y + eb.height / 2); await page.mouse.wheel(0, 400); await page.waitForTimeout(200);
    check(typed === "40" && (await page.inputValue("#expectedCount")) === "40", "人数框只留数字、滚轮不改数 (typed=" + typed + ")");
    await page.keyboard.press("Enter");
    check((await page.evaluate(() => document.activeElement.id)) === "actualCount", "应到框按回车跳到实到");
    await page.fill("#actualCount", "45"); await page.waitForTimeout(100);
    check((await page.getAttribute("#actualCount", "aria-invalid")) === "true" && /实到不能大于应到/.test(await page.textContent("#countPreview")), "实到大于应到时当场标红");
    await page.fill("#actualCount", "38");
    await page.evaluate(() => document.querySelector("#countForm").requestSubmit()); await page.waitForTimeout(300);
    check((await page.evaluate(() => state.step)) === 3 && !(await page.evaluate(() => document.querySelector("#appDialog").classList.contains("open"))), "第 2 步直接进第 3 步核对（不再弹重复的确认人数框）");
    await page.click("#confirmAddButton"); await page.waitForTimeout(900);
    const done = await page.evaluate(() => ({ step: state.step, title: document.querySelector("#doneTitle").textContent, focus: document.activeElement.id, dialog: document.querySelector("#appDialog").classList.contains("open") }));
    check(done.step === 4 && done.title === "乙教室 已提交" && done.focus === "doneTitle" && !done.dialog, "提交后停在完成页，写明哪间教室已提交，不再跳回第 1 步预选别的教室 (" + JSON.stringify(done) + ")");
    const after = await page.evaluate(() => ({ text: document.body.innerText, editRow: !!document.querySelector(".row-edit-button"), table: !!document.querySelector("#currentRows") }));
    const stored = await (await fetch(base + "/api/current-reports")).json();
    check(stored.data.items.length === 1 && stored.data.items[0].roomName === "乙教室" && stored.data.items[0].title === "前台回归场次" && stored.data.items[0].examDate === "2026-11-11",
      "提交成功：标题/日期来自下发，不是老师填的 (" + JSON.stringify(stored.data.items.map((i) => [i.roomName, i.title, i.examDate])) + ")");
    check(!after.editRow && !after.table, "提交后页面上没有修改按钮，也不展示统计表");
    check(/已提交|提交成功|可以关闭页面/.test(after.text), "提交后有明确的完成提示");
    await page.close();
    await post("/api/admin/accept", {}, ck);
    await post("/api/admin/site", { roomCount: 30 }, ck);
  }
  // ---- ⑧ 验收在后台：二次确认（无密码），取消不动数据，确认后场次关闭、数据已入库 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/dispatch", { mode: "now", title: "验收回归场次", examDate: "2026-12-12" }, ck);
    await post("/api/current-reports", { report: { roomName: "七教室", expectedCount: 45, actualCount: 43 } }, ck);
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 } });
    const page = await ctx.newPage();
    await page.goto(base + "/admin"); await page.waitForTimeout(400);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
    await page.waitForTimeout(1500);
    await page.click("#acceptButton"); await page.waitForTimeout(500);
    const dlg = await page.evaluate(() => ({ body: document.querySelector("#adminDialog").innerText, pw: !!document.querySelector("#adminDialog input[type=password]") }));
    check(/已填报 1 /.test(dlg.body) && !dlg.pw, "验收确认框：写清已填报数量且没有密码框");
    await page.evaluate(() => document.querySelector("#adminDialogCancel").click()); await page.waitForTimeout(300);
    check((await (await fetch(base + "/api/session")).json()).data.open === true, "取消验收：场次仍开着");
    await page.click("#acceptButton"); await page.waitForTimeout(400);
    await page.evaluate(() => document.querySelector("#adminDialogConfirm").click()); await page.waitForTimeout(1600);
    const msg = (await page.textContent("#adminMessage")).trim();
    check((await (await fetch(base + "/api/session")).json()).data.open === false && /验收完成/.test(msg), "确认验收：场次关闭并提示入库 (" + msg + ")");
    check(await page.evaluate(() => document.querySelector("#acceptButton").disabled), "场次关闭后验收按钮置灰");
    await page.close(); await ctx.close();
  }
  // ---- ⑩ 前台的教室名单要跟着后台改：场次开着、还没人提交时管理员改了名单，已打开的前台下一轮刷新就得拿到新名单 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/site", { orgName: "名单回归", roomCount: 3, roomNames: ["甲教室", "乙教室", "丙教室"] }, ck);
    await post("/api/admin/dispatch", { mode: "now", title: "名单回归场次" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(1200);
    await post("/api/admin/site", { roomCount: 2, roomNames: ["东教室", "西教室"] }, ck);
    await page.evaluate(() => refreshLiveReport()); await page.waitForTimeout(1200);
    await page.click("#changeRoomButton"); await page.waitForTimeout(300);
    const rooms = await page.evaluate(() => [...document.querySelectorAll("#classroomGrid .classroom-option")].map((n) => n.textContent));
    check(JSON.stringify(rooms) === JSON.stringify(["东教室", "西教室"]), "管理员改了教室名单后，已打开的前台刷新就用新名单: " + JSON.stringify(rooms));
    await page.close();
    await post("/api/admin/accept", {}, ck);
    await post("/api/admin/site", { roomCount: 30 }, ck);
  }
  // ---- ⑪ 后台左侧栏的机构名来自基本信息，改了立刻跟着变 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/site", { orgName: "侧栏回归考点" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    await page.goto(base + "/admin"); await page.waitForTimeout(400);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
    await page.waitForTimeout(1000);
    check((await page.textContent("#railOrg")) === "侧栏回归考点", "后台侧栏显示基本信息里的机构名: " + (await page.textContent("#railOrg")));
    await page.click('[data-nav="settings"]'); await page.waitForTimeout(600);
    await page.fill("#siteOrgName", "侧栏改名后"); await page.click("#saveSite"); await page.waitForTimeout(900);
    check((await page.textContent("#railOrg")) === "侧栏改名后", "保存基本信息后侧栏立刻跟着变");
    await page.close();
    await post("/api/admin/site", { orgName: "示例考试中心" }, ck);
  }
  // ---- ⑫ 连续筛选：先发后到的旧查询不能盖在新条件上（loadData 只认最后一次） ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    for (const t of ["乱序甲", "乙乱序"]) { await post("/api/admin/dispatch", { mode: "now", title: t, examDate: "2026-05-0" + (t === "乱序甲" ? 1 : 2) }, ck); await post("/api/current-reports", { report: { roomName: "一教室", expectedCount: 30, actualCount: 28 } }, ck); await post("/api/admin/accept", {}, ck); }
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    await page.goto(base + "/admin"); await page.waitForTimeout(400);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
    await page.waitForTimeout(1200);
    let release = null; const gate = new Promise((r) => { release = r; }); let held = false;
    await page.route("**/api/admin/analytics**", async (route) => { if (!held && /title=%E4%B9%B1%E5%BA%8F%E7%94%B2/.test(route.request().url())) { held = true; await gate; } await route.continue(); });
    await page.fill("#filterTitle", "乱序甲"); await page.evaluate(() => document.querySelector("#filterForm").requestSubmit());   // FIRST：被卡住
    await page.waitForTimeout(400);
    await page.fill("#filterTitle", "乙乱序"); await page.evaluate(() => document.querySelector("#filterForm").requestSubmit());   // SECOND：先完成
    await page.waitForTimeout(800);
    release(); await page.waitForTimeout(800);                                                                                       // FIRST 现在才返回
    const note = await page.textContent("#chartsNote");
    const rows = await page.evaluate(() => [...document.querySelectorAll("#reportRows tr")].map((r) => r.children[0]?.textContent));
    check(held && /乙乱序/.test(note) && !/乱序甲/.test(note) && rows.every((t) => /乙乱序/.test(t)), "旧查询晚到不覆盖新条件：说明=" + note.slice(0, 30) + "，明细=" + JSON.stringify(rows));
    await page.close();
  }
  // ---- ⑭ 填到一半时后台改了教室名单：不能带着空教室继续，要回到第 1 步并提示；名单没变的普通刷新不能打断填写 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/site", { roomCount: 3, roomNames: ["甲教室", "乙教室", "丙教室"] }, ck);
    await post("/api/admin/dispatch", { mode: "now", title: "半途改名单", examDate: "2026-07-07" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(1200);
    await page.click("#changeRoomButton"); await page.click('#classroomGrid .classroom-option:nth-child(1)');
    await page.click("#confirmRoomButton"); await page.waitForTimeout(300);
    await page.evaluate(() => document.querySelector("#appDialogConfirm").click()); await page.waitForTimeout(400);
    await page.fill("#expectedCount", "40"); await page.fill("#actualCount", "38");
    await page.evaluate(() => refreshLiveReport()); await page.waitForTimeout(1000);          // 名单没变：普通刷新
    const kept = await page.evaluate(() => ({ step: state.step, room: state.selectedRoom, exp: document.querySelector("#expectedCount").value }));
    check(kept.step === 2 && kept.room === "甲教室" && kept.exp === "40", "名单没变的刷新不打断填写 (" + JSON.stringify(kept) + ")");
    await page.evaluate(() => document.querySelector("#countForm").requestSubmit()); await page.waitForTimeout(300);   // 停在第 3 步核对
    await post("/api/admin/site", { roomCount: 2, roomNames: ["东教室", "西教室"] }, ck);   // 无人提交时管理员可以改名单
    await page.evaluate(() => refreshLiveReport()); await page.waitForTimeout(1200);
    const afterConfirm = await page.evaluate(() => ({ step: state.step, review: !!state.reviewPayload, room: state.selectedRoom }));
    check(afterConfirm.step === 1 && !afterConfirm.review && afterConfirm.room === "东教室", "停在第 3 步时名单变了：退回第 1 步、清掉待提交的数据 (" + JSON.stringify(afterConfirm) + ")");
    const after = await page.evaluate(() => ({ step: state.step, room: state.selectedRoom, msg: document.querySelector("#stepOneMessage").textContent }));
    check(after.step === 1 && /教室名单.*(变|更新)|重新选择/.test(after.msg) && after.room !== "甲教室" && after.room !== "", "名单变了：回到第 1 步并提示重新选择，并换成一个有效教室 (" + JSON.stringify(after) + ")");
    const label = await page.textContent("#selectedRoomLabel");
    check(!/甲教室/.test(label), "第 2 步的“已选择”标签不再显示已失效的教室: " + label);
    await page.close();
    await post("/api/admin/accept", {}, ck);
    await post("/api/admin/site", { roomCount: 30 }, ck);
  }
  // ---- ⑮ 真实 Chromium 里的导图：长名不许被省略号截断（假 canvas 按理想线性宽度量字，测不出真实字体的取整） ----
  {
    const page = await (await browser.newContext({ viewport: { width: 900, height: 1200 } })).newPage();
    await page.setContent("<html><body></body></html>");
    await page.addScriptTag({ path: require("node:path").join(__dirname, "..", "static", "report-image.js") });
    const res = await page.evaluate(() => {
      const spy = []; const orig = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (t, x, y) { spy.push(String(t)); return orig.call(this, t, x, y); };
      const out = [];
      const sets = [["汉字长名500", 500, (i) => "甲乙丙丁戊己庚辛壬癸天地玄黃宇宙洪" + i], ["全角500", 500, (i) => "Ｗ".repeat(17) + i], ["长名5000", 5000, (i) => "甲乙丙丁戊己庚辛壬癸子丑" + i], ["默认式500", 500, (i) => "第" + i + "号考场教室"]];
      for (const [label, n, nameFn] of sets) {
        const rooms = Array.from({ length: n }, (_, i) => ({ roomName: nameFn(i + 1), expectedCount: 40, actualCount: 33, absentCount: 7, attendanceRate: 0.825 }));
        spy.length = 0;
        const c = document.createElement("canvas");
        const L = QkReportImage.draw(c, { title: "t", examDate: "2026-01-01", rooms, totals: { expectedCount: 40 * n, actualCount: 33 * n, absentCount: 7 * n, attendanceRate: 0.825 } }, { orgName: "o" }, 1);
        const drawn = new Set(spy);
        const named = rooms.filter((r) => drawn.has(r.roomName)).length;
        out.push({ label, n, ellipsis: spy.filter((t) => t.endsWith("…")).length, named, textless: !!L.textless, font: L.font });
      }
      CanvasRenderingContext2D.prototype.fillText = orig;
      return out;
    });
    for (const r of res) check(r.ellipsis === 0 && (r.named === r.n || (r.textless && r.named === 0)), "真实 Chromium：" + r.label + " 名字不被省略号截断（要么全画要么整张不画字） " + JSON.stringify(r));
    await page.close();
  }
  // ---- ⑯ 一张 A4 看不清时改导出 HTML（先单间、后全部汇总），30 间仍是 PNG ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, acceptDownloads: true });
    const page = await ctx.newPage();
    await page.goto(base + "/admin"); await page.waitForTimeout(400);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
    await page.waitForTimeout(800);
    const grab = async (n) => {
      const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 10000 }), page.evaluate((n) => {
        const items = Array.from({ length: n }, (_, i) => ({ roomName: "第" + (i + 1) + "号考场教室", expectedCount: 40, actualCount: 35, absentCount: 5, attendanceRate: 0.875 }));
        exportReportSnapshot({ title: "大场次", examDate: "2026-09-09", items, expectedCount: 40 * n, actualCount: 35 * n, absentCount: 5 * n, attendanceRate: 0.875 });
      }, n)]);
      const file = require("node:os").tmpdir() + "/qk-uireg-" + Date.now() + "-" + n;
      await dl.saveAs(file); const buf = require("node:fs").readFileSync(file); require("node:fs").unlinkSync(file);
      return { name: dl.suggestedFilename(), buf, msg: (await page.textContent("#adminMessage")).trim() };
    };
    const small = await grab(30), big = await grab(1200);
    check(small.name.endsWith(".png") && /一张 A4/.test(small.msg), "30 间导出 A4 图片: " + small.name);
    const doc = big.buf.toString("utf8");
    const lastRoom = doc.indexOf("第1200号考场教室"), sum = doc.indexOf("全部汇总（1200 个教室）");
    check(big.name.endsWith(".html") && /HTML/.test(big.msg) && lastRoom > 0 && sum > lastRoom, "1200 间改导出 HTML，先单间后全部汇总: " + big.name + " " + big.msg.slice(0, 30));
    // 打印时“全部汇总”只出现一次、在最后一页（tfoot 默认每页重复）
    const pp = await ctx.newPage(); await pp.setContent(doc);
    const pdf = await pp.pdf({ format: "A4" }); await pp.close();
    const pdfFile = require("node:os").tmpdir() + "/qk-uireg-" + Date.now() + ".pdf"; require("node:fs").writeFileSync(pdfFile, pdf);
    const txt = require("node:child_process").execFileSync("pdftotext", ["-layout", pdfFile, "-"]).toString("utf8"); require("node:fs").unlinkSync(pdfFile);
    const pages = txt.split("\f").filter((x) => x.trim());
    const hits = pages.map((pg, i) => (pg.includes("全部汇总") ? i : -1)).filter((i) => i >= 0);
    check(hits.length === 1 && hits[0] === pages.length - 1, "HTML 打印：全部汇总只在最后一页出现一次 (共 " + pages.length + " 页，出现在 " + JSON.stringify(hits) + ")");
    await page.close(); await ctx.close();
  }
  // ---- ⑰ 完成页跨场次：本场验收后马上下发新场（页面没来得及看到“关闭”），新场本教室没填，完成页必须让位给第 1 步 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/dispatch", { mode: "now", title: "跨场次甲", examDate: "2026-08-08" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(1200);
    await page.click("#confirmRoomButton"); await page.waitForTimeout(300);
    await page.evaluate(() => document.querySelector("#appDialogConfirm").click()); await page.waitForTimeout(300);
    await page.fill("#expectedCount", "30"); await page.fill("#actualCount", "29");
    await page.evaluate(() => document.querySelector("#countForm").requestSubmit()); await page.waitForTimeout(300);
    await page.click("#confirmAddButton"); await page.waitForTimeout(900);
    const room = await page.evaluate(() => state.step === 4 && document.querySelector("#doneTitle").textContent);
    await post("/api/admin/accept", {}, ck);
    await post("/api/admin/dispatch", { mode: "now", title: "跨场次乙", examDate: "2026-08-09" }, ck);   // 两次轮询之间完成：页面只看到 open → open
    await page.evaluate(() => { pollSession(); refreshLiveReport(); }); await page.waitForTimeout(1500);
    const now = await page.evaluate(() => ({ step: state.step, title: document.querySelector("#currentProjectName").textContent, done: !document.querySelector(".done-panel").classList.contains("hidden") }));
    check(!!room && now.step === 1 && !now.done && now.title === "跨场次乙", "新场次本教室没填：完成页让位给第 1 步 (" + JSON.stringify({ room, now }) + ")");
    await page.close();
    await post("/api/admin/accept", {}, ck);
  }
  // ---- ⑱ 中文输入法组合输入：全角“４”“４０”逐步组合，最后应是 40，不是 440；组合中的回车不跳框 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/dispatch", { mode: "now", title: "输入法回归", examDate: "2026-08-10" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(1200);
    await page.click("#confirmRoomButton"); await page.waitForTimeout(300);
    await page.evaluate(() => document.querySelector("#appDialogConfirm").click()); await page.waitForTimeout(300);
    await page.focus("#expectedCount");
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.imeSetComposition", { text: "４", selectionStart: 1, selectionEnd: 1 });
    await cdp.send("Input.imeSetComposition", { text: "４０", selectionStart: 2, selectionEnd: 2 });
    const mid = await page.inputValue("#expectedCount");
    await cdp.send("Input.insertText", { text: "４０" });
    await page.waitForTimeout(150);
    const val = await page.inputValue("#expectedCount");
    check(val === "40" && (await page.evaluate(() => document.activeElement.id)) === "expectedCount", "输入法组合输入“４０”得到 40 (组合中=" + mid + "，结束=" + val + ")");
    // 组合中确认候选的回车（isComposing / keyCode 229）不能跳到实到；普通回车要跳
    const enter = await page.evaluate(() => {
      const el = document.querySelector("#expectedCount"); el.focus();
      const fire = (init) => el.dispatchEvent(new KeyboardEvent("keydown", Object.assign({ key: "Enter", bubbles: true, cancelable: true }, init)));
      fire({ isComposing: true }); const a = document.activeElement.id;
      fire({ keyCode: 229 }); const b = document.activeElement.id;
      fire({}); const c = document.activeElement.id;
      return [a, b, c];
    });
    check(JSON.stringify(enter) === JSON.stringify(["expectedCount", "expectedCount", "actualCount"]), "输入法确认候选的回车不跳框，普通回车跳到实到 " + JSON.stringify(enter));
    await page.close();
    await post("/api/admin/accept", {}, ck);
  }
  // ---- ⑲ 提交前就在路上的旧“已提交列表”晚到（且系统时钟往回调过）：完成页不能被它撤掉 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/dispatch", { mode: "now", title: "旧响应回归", examDate: "2026-08-11" }, ck);
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    await page.goto(base + "/"); await page.waitForTimeout(1200);
    await page.click("#confirmRoomButton"); await page.waitForTimeout(300);
    await page.evaluate(() => document.querySelector("#appDialogConfirm").click()); await page.waitForTimeout(300);
    await page.fill("#expectedCount", "30"); await page.fill("#actualCount", "30");
    await page.evaluate(() => document.querySelector("#countForm").requestSubmit()); await page.waitForTimeout(300);
    // 拖住下一次 GET /api/current-reports（返回空列表），并让时钟往回走
    await page.route("**/api/current-reports", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      await new Promise((r) => setTimeout(r, 1500));
      route.fulfill({ contentType: "application/json", body: JSON.stringify({ success: true, data: { items: [] } }) });
    });
    await page.evaluate(() => { loadCurrentReports(); const real = Date.now; Date.now = () => real() - 600000; });
    await page.click("#confirmAddButton"); await page.waitForTimeout(2500);
    const st = await page.evaluate(() => ({ step: state.step, done: !document.querySelector(".done-panel").classList.contains("hidden") }));
    check(st.step === 4 && st.done, "提交前发出的旧列表晚到（时钟回拨）不撤掉完成页 (" + JSON.stringify(st) + ")");
    await page.close();
    await post("/api/admin/accept", {}, ck);
  }
  // ---- ⑳ 首次使用（真实服务端、没有环境变量密码）：112233 登录 → 设置新密码页（刷新后仍在）→ 拒绝 112233 → 改成新密码进后台 → 单位名称为空时带到「基本信息」 ----
  {
    const fresh = process.env.FIRST_RUN_BASE;
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 } });
    const page = await ctx.newPage();
    await page.goto(fresh + "/admin"); await page.waitForTimeout(500);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForTimeout(600);
    const view = () => page.evaluate(() => ({ form: !document.querySelector("#firstPasswordForm").classList.contains("hidden"), admin: !document.querySelector("#adminView").classList.contains("hidden") }));
    const first = await view();
    await page.reload(); await page.waitForTimeout(800);
    const again = await view();
    check(first.form && !first.admin && again.form && !again.admin, "默认密码登录后先设置新密码，刷新后仍停在这一步 " + JSON.stringify({ first, again }));
    await page.fill("#firstPwNew", "112233"); await page.fill("#firstPwConfirm", "112233");
    await page.evaluate(() => document.querySelector("#firstPasswordForm").requestSubmit()); await page.waitForTimeout(300);
    check(/不能继续使用默认密码/.test(await page.textContent("#firstPwMessage")), "新密码不能还是 112233");
    await page.fill("#firstPwNew", "first-run-pw"); await page.fill("#firstPwConfirm", "first-run-pw");
    await page.evaluate(() => document.querySelector("#firstPasswordForm").requestSubmit()); await page.waitForTimeout(2000);
    const inside = await page.evaluate(() => ({ admin: !document.querySelector("#adminView").classList.contains("hidden"), view: state.view, msg: document.querySelector("#siteMessage").textContent, rail: document.querySelector("#railOrg").textContent }));
    check(inside.admin && inside.view === "settings" && /请先填写单位名称/.test(inside.msg) && inside.rail === "未填写单位名称", "改完密码进后台，单位名称为空时带到「基本信息」并提示 " + JSON.stringify(inside));
    const relog = await fetch(fresh + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: "112233" }) });
    check(relog.status === 401, "改完后 112233 不能再登录 (" + relog.status + ")");
    await page.close(); await ctx.close();
  }
  // ---- ⑬ 删除失败：管理员必须看到服务端的错误提示（不能因为前端异常而静默） ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/dispatch", { mode: "now", title: "删除失败回归", examDate: "2026-06-06" }, ck);
    await post("/api/current-reports", { report: { roomName: "一教室", expectedCount: 30, actualCount: 28 } }, ck);
    await post("/api/admin/accept", {}, ck);
    const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
    const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.goto(base + "/admin"); await page.waitForTimeout(400);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
    await page.waitForTimeout(1200);
    await page.route("**/api/admin/reports/*", async (route) => {
      if (route.request().method() === "DELETE") await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ success: false, error: { code: "BOOM", message: "删除失败测试" } }) });
      else await route.continue();
    });
    await page.click(".row-delete-button"); await page.waitForTimeout(400);
    await page.evaluate(() => document.querySelector("#adminDialogConfirm").click()); await page.waitForTimeout(400);
    await page.evaluate(() => document.querySelector("#adminDialogConfirm").click()); await page.waitForTimeout(900);
    const msg = (await page.textContent("#adminMessage")).trim();
    check(/删除失败测试/.test(msg) && pageErrors.length === 0, "删除失败：显示服务端错误，页面无脚本异常 (msg=" + msg + ", errors=" + JSON.stringify(pageErrors) + ")");
    await page.close();
  }
  // ---- ⑨ 导图：竖版 A4 PNG；机构名/地址来自基本信息；教室数超过一页容量时拆成多张 ----
  {
    const ck = (await post("/api/admin/login", { password: "112233" })).cookie;
    await post("/api/admin/site", { orgName: "导图考点", orgAddress: "导图路 9 号", roomCount: 3, roomNames: ["甲教室", "乙教室", "丙教室"] }, ck);
    await post("/api/admin/dispatch", { mode: "now", title: "导图回归场次", examDate: "2026-12-20" }, ck);
    for (const [n, e, a] of [["甲教室", 30, 28], ["乙教室", 40, 30], ["丙教室", 35, 35]]) await post("/api/current-reports", { report: { roomName: n, expectedCount: e, actualCount: a } }, ck);
    await post("/api/admin/accept", {}, ck);
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, acceptDownloads: true });
    const page = await ctx.newPage();
    await page.goto(base + "/admin"); await page.waitForTimeout(400);
    await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
    await page.waitForTimeout(1500);
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 10000 }), page.click(".row-export-button")]);
    const file = require("node:os").tmpdir() + "/qk-uireg-" + Date.now() + ".png";
    await dl.saveAs(file);
    const buf = require("node:fs").readFileSync(file); require("node:fs").unlinkSync(file);
    const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
    check(buf.slice(1, 4).toString() === "PNG" && Math.abs(h / w - 297 / 210) < 0.01, "导图是 PNG，宽高比是 A4 竖版 (" + w + "x" + h + ", 比值 " + (h / w).toFixed(4) + ")");
    check(/导图回归场次/.test(dl.suggestedFilename()) && /2026-12-20/.test(dl.suggestedFilename()), "文件名含标题和日期: " + dl.suggestedFilename());
    const fit = await page.evaluate(() => { const bad = []; for (let n = 1; n <= QkReportImage.MAX_ROOMS; n++) if (!QkReportImage.layout(n).fits) bad.push(n); return bad; });
    check(fit.length === 0, "1..500 间每一档都在一张 A4 里放得下 (放不下的: " + JSON.stringify(fit.slice(0, 5)) + ")");
    await page.close(); await ctx.close();
    await post("/api/admin/site", { roomCount: 30 }, ck);
  }
  // ---- ②③④ admin ----
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  let posts = 0, liveReqs = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/api/admin/dispatch")) posts++; if (r.url().endsWith("/api/admin/live")) liveReqs++; });
  await page.goto(base + "/admin"); await page.waitForTimeout(500);
  await page.fill("#password", "112233"); await page.click("#loginButton"); await page.waitForSelector("#adminView:not(.hidden)");
  const countDispatches = () => page.evaluate(async () => (await (await fetch("/api/admin/dispatches")).json()).data.items.length);
  const createdBefore = await countDispatches(); // 第 ① 段为了开放场次已经下发过一条，这里按增量算
  await page.click('[data-nav="dispatch"]'); await page.waitForTimeout(400);
  await page.fill("#dispatchTitle", "回归场次"); await page.fill("#dispatchMessage", "回归检查"); await page.check('input[value="now"]');
  await page.focus("#dispatchSubmit"); await page.keyboard.press("Enter"); await page.waitForTimeout(400);
  let escaped = false;
  for (let i = 0; i < 30; i++) { await page.keyboard.press("Tab"); if (!(await page.evaluate(() => !!document.activeElement.closest("#adminDialog")))) { escaped = true; break; } }
  check(!escaped, "对话框是真模态：Tab 30 次焦点没有跑到遮罩后面");
  await page.keyboard.press("Enter"); await page.waitForTimeout(300);
  await page.evaluate(() => document.querySelector("#adminDialogConfirm").click()); await page.waitForTimeout(1200);
  check(posts === 1, "一次确认只发出 1 次下发请求 (实际 " + posts + ")");
  const created = (await countDispatches()) - createdBefore;
  check(created === 1, "服务端只新增 1 条下发 (实际新增 " + created + ")");
  // ⑥ 弹窗文案按「显示行数」限制（每硬行按 30 字折行，最多 9 行）：「186 字 + 7 个短行」恰好 200 字 8 个硬行，
  //    折算成 14 行，放不下，必须在提交前就被拦下、不发请求（只数硬行或只数字数的旧规则会放过它）
  await page.click('[data-nav="dispatch"]'); await page.waitForTimeout(300);
  const before = posts;
  await page.fill("#dispatchMessage", "字".repeat(186) + "\n字".repeat(7));
  await page.evaluate(() => document.querySelector("#dispatchForm").requestSubmit()); await page.waitForTimeout(500);
  const err = await page.evaluate(() => document.querySelector("#dispatchMessageErr").textContent);
  // 如果规则失效，表单会弹出「确认立即下发」对话框，它会挡住后面所有点击——先把它取消掉，让失败是一条可读的 FAIL 而不是脚本超时崩溃
  const dialogOpen = await page.evaluate(() => document.querySelector("#adminDialog").classList.contains("open"));
  if (dialogOpen) await page.evaluate(() => document.querySelector("#adminDialogCancel").click());
  await page.waitForTimeout(200);
  check(!dialogOpen && posts === before && /换行太多/.test(err), "200 字 + 8 个硬行（折算 14 行）：前端拦下，不弹确认框、不发请求 (dialog=" + dialogOpen + ", posts " + before + "→" + posts + ", err=" + err + ")");
  await page.fill("#dispatchMessage", "");
  // ④ 一条轮询链：必须让一个 live 请求在「切走再切回」期间一直挂着，旧循环才有机会复活
  let release = null; const gate = new Promise((r) => { release = r; });
  let hold = false;
  await page.route("**/api/admin/live", async (route) => { if (hold) { hold = false; await gate; } await route.continue(); });
  await page.click('[data-nav="settings"]'); await page.click('[data-nav="data"]');   // 新一代 startLive；setView 自己的那次 refreshLive 先放行
  await page.waitForTimeout(900);
  hold = true;                                                                           // 只拦「轮询循环自己发出的」下一次请求
  await page.waitForTimeout(3600);                                                       // 3 秒回调进入被拦住的 refreshLive，循环挂在 await 上，busy=true
  await page.click('[data-nav="settings"]'); await page.click('[data-nav="data"]');   // stopLive → startLive 发生在请求挂起期间
  await page.waitForTimeout(1500);                                                       // 错开相位：否则两条链的定时器只差几毫秒，busy 会把其中一条的请求吃掉，看起来像单链
  release();                                                                             // 旧请求返回：旧循环若无代际检查，此刻复活成第二条链
  await page.waitForTimeout(600); liveReqs = 0; await page.waitForTimeout(9000);
  check(liveReqs >= 2 && liveReqs <= 4, "请求挂起期间切视图后只剩一条 3 秒轮询链：9 秒内 live 请求 " + liveReqs + " 次 (单链 2..4；0 次=轮询停了，双链会到 6+)");
  await page.unroute("**/api/admin/live");
  // ③ expired session + change password
  await page.click('[data-nav="settings"]'); await page.waitForTimeout(400);
  await page.fill("#pwOld", "wrong-old"); await page.fill("#pwNew", "abcd1234"); await page.fill("#pwConfirm", "abcd1234");
  await page.evaluate(() => document.querySelector("#passwordForm").requestSubmit()); await page.waitForTimeout(400);
  await page.evaluate(() => document.querySelector("#adminDialogConfirm").click()); await page.waitForTimeout(800);
  let st = await page.evaluate(() => ({ login: !document.querySelector("#loginView").classList.contains("hidden"), msg: (document.querySelector("#pwOldErr") || {}).textContent }));
  check(!st.login && /不正确/.test(st.msg || ""), "旧密码错：留在设置页并提示「旧密码不正确」(login=" + st.login + ", msg=" + st.msg + ")");
  await ctx.clearCookies();
  await page.fill("#pwOld", "112233");
  await page.evaluate(() => document.querySelector("#passwordForm").requestSubmit()); await page.waitForTimeout(400);
  await page.evaluate(() => document.querySelector("#adminDialogConfirm").click()); await page.waitForTimeout(900);
  st = await page.evaluate(() => ({ login: !document.querySelector("#loginView").classList.contains("hidden") }));
  check(st.login, "会话过期后改密码：回到登录页，而不是把「请先登录」标在旧密码框上");
  await browser.close();
  if (fails.length) { console.log("\nFAILED: " + fails.length); process.exit(1); }
  console.log("\nPASS");
})();
