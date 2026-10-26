let classroomNames = []; // 来自后台「基本信息」（/api/site），页面启动时加载

const classroomGrid = document.querySelector("#classroomGrid");
const detectedRoomName = document.querySelector("#detectedRoomName");
const changeRoomButton = document.querySelector("#changeRoomButton");
const appDialog = document.querySelector("#appDialog");
const appDialogTitle = document.querySelector("#appDialogTitle");
const appDialogBody = document.querySelector("#appDialogBody");
const appDialogCancel = document.querySelector("#appDialogCancel");
const appDialogConfirm = document.querySelector("#appDialogConfirm");
const stepPanels = document.querySelectorAll("[data-step]");
const stepPills = document.querySelectorAll("[data-step-pill]");
const confirmRoomButton = document.querySelector("#confirmRoomButton");
const backToRoomButton = document.querySelector("#backToRoomButton");
const editCountsButton = document.querySelector("#editCountsButton");
const countForm = document.querySelector("#countForm");
const expectedInput = document.querySelector("#expectedCount");
const actualInput = document.querySelector("#actualCount");
const absentOutput = document.querySelector("#absentCount");
const countPreview = document.querySelector("#countPreview");
const selectedRoomLabel = document.querySelector("#selectedRoomLabel");
const reviewBox = document.querySelector("#reviewBox");
const confirmAddButton = document.querySelector("#confirmAddButton");
const currentProjectBanner = document.querySelector("#currentProjectBanner");
const currentProjectName = document.querySelector("#currentProjectName");
const currentProjectDate = document.querySelector("#currentProjectDate");
const orgName = document.querySelector("#orgName");
const footOrg = document.querySelector("#footOrg");
const roomNotice = document.querySelector("#roomNotice");
const stepOneMessage = document.querySelector("#stepOneMessage");
const stepTwoMessage = document.querySelector("#stepTwoMessage");
const stepThreeMessage = document.querySelector("#stepThreeMessage");
const reviewTitle = document.querySelector("#reviewTitle");
const doneTitle = document.querySelector("#doneTitle");
const doneBox = document.querySelector("#doneBox");
const doneJoke = document.querySelector("#doneJoke");

const state = {
  step: 1,
  selectedRoom: "",
  detectedRoom: "",
  roomPickerOpen: false,
  reviewPayload: null,
  doneRoom: "",
  roomNotice: "",
  doneSeq: 0,
  reports: [],
  reportTitle: "",
  reportDate: "",
};
const pendingAcceptanceMessage = "数据未验收，不支持重新填报！请联系考务老师确认！";

const funnyCloseMessages = [
  "任务完成，今天的键盘表现很懂事。",
  "数据已收编，表格正在暗自鼓掌。",
  "报告已归队，鼠标可以下班喝水了。",
  "提交成功，数字们排队站好了。",
  "搞定，缺考数没有偷偷溜走。",
  "已确认，页面说它也想早点休息。",
  "数据到账，表格露出了职业微笑。",
  "提交完毕，今天你比计算器还靠谱。",
  "搞定啦，系统刚刚点了个头。",
  "信息已收好，数字们没有打架。",
  "提交成功，考勤小本本记上了。",
  "完成，页面已经把小红花别上了。",
  "收到，数据正在乖乖坐好。",
  "确认完毕，系统心里有数了。",
  "搞定，今天的表格没有白等。",
  "已提交，数字们集体表示服气。",
  "完成，缺考数被自动抓住了。",
  "提交成功，页面准备原地收工。",
  "信息已保存，鼠标终于可以松口气。",
  "搞定，考勤宇宙暂时和平。",
  "数据已入队，表格队长表示满意。",
  "确认成功，系统刚刚偷偷比了个耶。",
  "已完成，今天没有数字离家出走。",
  "提交成功，计算器看了都说专业。",
  "数据已锁定，页面不再眨眼。",
  "搞定，表格里的小格子都站直了。",
  "确认完毕，系统已经把门关好。",
  "已提交，数字们正在排队领盒饭。",
  "完成，页面说辛苦你点这么准。",
  "提交成功，缺考数已经自动报到。",
  "搞定，系统把这份认真收藏了。",
  "信息已收下，表格今天很有安全感。",
  "确认成功，数字们没有继续开小会。",
  "已完成，页面已经进入乖巧模式。",
  "提交成功，今日份考勤拼图拼上了。",
  "搞定，系统刚刚把小算盘收起来。",
  "数据已确认，页面满意地点点头。",
  "完成，鼠标左键获得优秀员工奖。",
  "提交成功，表格终于不空虚了。",
  "已收好，数字们已经各回各家。",
  "搞定，系统没有让你白认真。",
  "确认完毕，考勤小火车准点发车。",
  "数据已保存，页面正在假装很淡定。",
  "提交成功，缺考数已被安排明白。",
  "完成，今天的统计味儿很正。",
  "搞定，系统表示这波很稳。",
  "已确认，表格里的格子开始鼓掌。",
  "提交成功，数字们都签了到。",
  "完成，页面已经把结果抱紧了。",
  "数据已收齐，系统没有皱眉头。",
  "搞定，今天的点击很有水平。",
  "确认成功，考勤江湖风平浪静。",
  "已提交，缺考数没有机会装傻。",
  "完成，系统把这条数据盖了章。",
  "提交成功，页面快乐地转了个身。",
  "搞定，表格今天吃饱了数据。",
  "已确认，数字们没有迟到。",
  "完成，鼠标功成身退。",
  "提交成功，考勤小剧场落幕。",
  "数据已就位，页面站得笔直。",
  "搞定，系统刚刚把答案揣兜里。",
  "确认完毕，表格没意见。",
  "已提交，今天的数字很听话。",
  "完成，页面说这事办得敞亮。",
  "提交成功，系统给你递了杯虚拟热水。",
  "搞定，缺考数已被温柔拿捏。",
  "数据已确认，表格心情不错。",
  "完成，考勤小算盘啪嗒一声合上了。",
  "提交成功，页面已经收拾书包。",
  "已收好，数字们终于不用排练了。",
  "搞定，系统把这份数据放进保险柜。",
  "确认成功，页面表示可以安心躺平。",
  "完成，今天的统计没有绕弯子。",
  "提交成功，数字们都找到了座位。",
  "数据已归档，表格正在优雅退场。",
  "搞定，系统的眉头舒展开了。",
  "已确认，考勤小本本没有漏页。",
  "完成，页面把你这一票记住了。",
  "提交成功，缺考数表示它是自动来的。",
  "搞定，数字们已经停止窃窃私语。",
  "数据已收妥，系统刚刚深呼吸。",
  "确认完毕，页面像刚考完一样轻松。",
  "已提交，表格说这就对味了。",
  "完成，统计小船顺利靠岸。",
  "提交成功，系统把这条数据安排得明明白白。",
  "搞定，今天的表单没有难为你。",
  "已确认，数字们排成了整齐队形。",
  "完成，页面把小板凳收起来了。",
  "提交成功，考勤小雷达已扫描完毕。",
  "数据已稳稳落袋，系统不再碎碎念。",
  "搞定，表格已经从紧张变成淡定。",
  "确认成功，今日份人数谜题解开了。",
  "已提交，页面正在快乐收尾。",
  "完成，系统表示这题会做。",
  "提交成功，数字们下课铃响了。",
  "搞定，表格里的空气都清爽了。",
  "已确认，系统给这次操作打了勾。",
  "完成，页面说终于等到你。",
  "提交成功，缺考数自动上岗成功。",
  "数据已收好，表格准备关灯。",
];

function todayString() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatRate(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function parseCount(input) {
  if (!/^[0-9]+$/.test(input.value)) return null;
  return Number(input.value);
}

// 只留数字：全角数字（中文输入法）转半角，其它字符直接去掉
function sanitizeCountInput(input) {
  const clean = input.value
    .replace(/[０-９]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0))
    .replace(/[^0-9]/g, "")
    .slice(0, 6);
  if (clean !== input.value) input.value = clean;
}

function setAbsentOutput(value) {
  const text = value === null ? "-" : String(value);
  absentOutput.value = text;
  absentOutput.textContent = text;
}

function randomCloseMessage() {
  const index = Math.floor(Math.random() * funnyCloseMessages.length);
  return funnyCloseMessages[index];
}

function setMessage(element, text, type = "") {
  element.textContent = text;
  element.className = `message ${type}`.trim();
}

function clearMessages() {
  setMessage(stepOneMessage, "");
  setMessage(stepTwoMessage, "");
  setMessage(stepThreeMessage, "");
}

function showDialog(options = {}) {
  return new Promise((resolve) => {
    const {
      title = "确认",
      message = "",
      confirmText = "确认",
      cancelText = "取消",
      showCancel = true,
      highlight = "",
      lead = "",
    } = options;

    appDialogTitle.textContent = title;
    appDialogBody.innerHTML = "";
    if (lead) {
      const leadElement = document.createElement("div");
      leadElement.className = "dialog-lead";
      leadElement.textContent = lead;
      appDialogBody.appendChild(leadElement);
    }
    if (highlight) {
      const highlightElement = document.createElement("div");
      highlightElement.className = "dialog-highlight";
      highlightElement.textContent = highlight;
      appDialogBody.appendChild(highlightElement);
    }
    if (message) {
      const messageElement = document.createElement("div");
      messageElement.className = "dialog-message";
      messageElement.textContent = message;
      appDialogBody.appendChild(messageElement);
    }
    appDialogConfirm.textContent = confirmText;
    appDialogCancel.textContent = cancelText;
    appDialogCancel.classList.toggle("hidden", !showCancel);
    appDialog.classList.add("open");
    appDialog.setAttribute("aria-hidden", "false");

    const cleanup = (value) => {
      appDialog.classList.remove("open");
      appDialog.setAttribute("aria-hidden", "true");
      appDialogConfirm.removeEventListener("click", onConfirm);
      appDialogCancel.removeEventListener("click", onCancel);
      appDialog.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKeydown);
      resolve(value);
    };

    const onConfirm = () => {
      cleanup(true);
    };
    const onCancel = () => cleanup(false);
    const onBackdrop = (event) => {
      if (event.target === appDialog && showCancel) cleanup(false);
    };
    const onKeydown = (event) => {
      if (event.key === "Escape" && showCancel) cleanup(false);
      if (event.key === "Tab") {
        // 焦点只在对话框的按钮之间循环，不能跑到遮罩后面的页面上
        const items = [appDialogCancel, appDialogConfirm].filter((el) => !el.classList.contains("hidden"));
        const i = items.indexOf(document.activeElement);
        event.preventDefault();
        items[(i + (event.shiftKey ? items.length - 1 : 1)) % items.length].focus();
      }
    };

    appDialogConfirm.addEventListener("click", onConfirm);
    appDialogCancel.addEventListener("click", onCancel);
    appDialog.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKeydown);

    window.setTimeout(() => {
      appDialogConfirm.focus();
    }, 0);
  });
}

function showHighlightedConfirm(
  title,
  message,
  highlight,
  confirmText = "确认",
  lead = "",
) {
  return showDialog({
    title,
    message,
    highlight,
    lead,
    confirmText,
    showCancel: true,
  });
}

function showAlert(title, message, confirmText = "知道了") {
  return showDialog({ title, message, confirmText, showCancel: false });
}

function roomNumber(roomName) {
  return classroomNames.indexOf(roomName) + 1;
}

function normalizeReports(reports) {
  if (!Array.isArray(reports)) return [];
  return reports
    .filter((item) => classroomNames.includes(item.roomName))
    .map((item) => {
      const expectedCount = Number(item.expectedCount || 0);
      const actualCount = Number(item.actualCount || 0);
      const absentCount = expectedCount - actualCount;
      return {
        reportId: item.reportId || null,
        batchToken: item.batchToken || "",
        roomName: item.roomName,
        expectedCount,
        actualCount,
        absentCount,
        attendanceRate:
          expectedCount > 0 ? actualCount / expectedCount : Number(item.attendanceRate || 0),
        examDate: item.examDate || todayString(),
        createdAt: item.createdAt || "",
        title: item.title || "",
      };
    })
    .sort((a, b) => roomNumber(a.roomName) - roomNumber(b.roomName));
}

// 已有请求在途时共用同一个 promise：调用方 await 它就一定拿到「完成后的最新数据」，而不是立刻返回旧的 state.reports
let currentReportsRequest = null;
function loadCurrentReports() {
  if (currentReportsRequest) return currentReportsRequest;
  const doneSeqAtStart = state.doneSeq;
  currentReportsRequest = (async () => {
    try {
      const result = await requestJson("/api/current-reports");
      state.reports = normalizeReports(result.items);
      // 完成页跟着数据走：本场已提交的教室里没有它了（验收后下发了新场次），就回到第 1 步重新填
      // 只认完成页出现之后才发出的请求：之前就在路上的旧列表里当然没有本教室。用计数而不是时钟，系统改时间也不影响
      if (state.step === 4 && doneSeqAtStart === state.doneSeq && !state.reports.some((item) => item.roomName === state.doneRoom)) {
        state.doneRoom = "";
        clearMessages();
        setSelectedRoom(state.detectedRoom || chooseFallbackRoom());
        setStep(1);
      }
      renderClassrooms();
    } finally {
      currentReportsRequest = null;
    }
  })();
  return currentReportsRequest;
}

async function saveCurrentReport(report) {
  const result = await requestJson("/api/current-reports", {
    method: "POST",
    body: JSON.stringify({ report }),
  });
  state.reports = normalizeReports(result.items);
  renderClassrooms();
}

async function checkCurrentReportRoom(roomName) {
  return requestJson("/api/current-reports/check-room", {
    method: "POST",
    body: JSON.stringify({ roomName }),
  });
}

function renderReportTitle() {
  currentProjectName.textContent = state.reportTitle || "未设置";
  currentProjectBanner.classList.toggle("empty", !state.reportTitle);
  currentProjectDate.textContent = state.reportDate ? "考试日期　" + state.reportDate : "";
}

async function loadSite() {
  try {
    const site = await requestJson("/api/site");
    classroomNames = site.roomNames || [];
    // 名单变了，选中的教室可能已经不存在：必须明确回到第 1 步重新选，不能带着空教室往下填
    const lost = state.selectedRoom && !classroomNames.includes(state.selectedRoom);
    if (state.detectedRoom && !classroomNames.includes(state.detectedRoom)) state.detectedRoom = "";
    if (lost) {
      state.selectedRoom = "";
      state.reviewPayload = null;
      if (appDialog.classList.contains("open")) appDialogCancel.click(); // 正开着“确认人数”弹窗：关掉，免得老师点了旧弹窗继续往下走
      setSelectedRoom(state.detectedRoom || chooseFallbackRoom());
      if (state.step !== 1) setStep(1);
      updateSelectedRoomLabel();
      setMessage(stepOneMessage, "教室名单已更新，请重新选择教室。", "error");
    }
    orgName.textContent = site.orgName || "";
    footOrg.textContent = site.orgName ? site.orgName + " · 考务系统" : "考务系统";
    state.roomNotice = site.roomNotice || "";
    roomNotice.textContent = state.roomNotice;
    roomNotice.closest(".notice").classList.toggle("hidden", !state.roomNotice);
    document.title = "出考率信息填报" + (site.orgName ? " - " + site.orgName : "");
    renderClassrooms();
  } catch (error) {
    // 取不到名单就保持空名单：按钮不会显示，后面会提示刷新；不要退回写死的旧名单
    setMessage(stepOneMessage, "暂时取不到教室名单，请刷新页面重试。", "error");
  }
}

function setStep(step) {
  state.step = step;
  stepPanels.forEach((panel) => {
    panel.classList.toggle("hidden", Number(panel.dataset.step) !== step);
  });
  stepPills.forEach((pill) => {
    const pillStep = Number(pill.dataset.stepPill);
    pill.classList.toggle("active", pillStep === step);
    pill.classList.toggle("done", pillStep < step);
    if (pillStep === step) pill.setAttribute("aria-current", "step");
    else pill.removeAttribute("aria-current");
  });
}

function chooseFallbackRoom() {
  const filledRooms = new Set(state.reports.map((item) => item.roomName));
  return classroomNames.find((name) => !filledRooms.has(name)) || classroomNames[0];
}

function setSelectedRoom(roomName, options = {}) {
  state.selectedRoom = roomName;
  if (options.manual) {
    state.roomPickerOpen = false;
  }
  updateDetectedRoom();
}

function updateDetectedRoom() {
  detectedRoomName.textContent = state.selectedRoom || "未匹配";
  changeRoomButton.textContent = state.roomPickerOpen ? "收起选择" : "修改教室";
  classroomGrid.classList.toggle("hidden", !state.roomPickerOpen);
}

async function loadClientContext() {
  try {
    const context = await requestJson("/api/client-context");
    state.detectedRoom = context.matchedRoomName || "";
    if (!state.selectedRoom) {
      setSelectedRoom(state.detectedRoom || chooseFallbackRoom());
    } else {
      updateDetectedRoom();
    }
    if (!context.matchedRoomName) {
      setMessage(
        stepOneMessage,
        "未能按访问 IP 自动匹配教室，请确认当前教室后继续。",
        "error",
      );
    }
  } catch (error) {
    if (!state.selectedRoom) {
      setSelectedRoom(chooseFallbackRoom());
    } else {
      updateDetectedRoom();
    }
    setMessage(stepOneMessage, "未能获取访问 IP，已默认选择可填教室。", "error");
  }
}

function renderClassrooms() {
  classroomGrid.innerHTML = "";
  const filledRooms = new Set(
    state.reports.map((item) => item.roomName),
  );
  classroomNames.forEach((name) => {
    const button = document.createElement("button");
    button.className = "classroom-option";
    button.type = "button";
    button.textContent = name;
    button.disabled = filledRooms.has(name);
    if (state.selectedRoom === name) button.classList.add("selected");
    if (filledRooms.has(name)) button.title = "本次已填写";
    button.addEventListener("click", () => {
      setSelectedRoom(name, { manual: true });
      clearMessages();
      renderClassrooms();
    });
    classroomGrid.appendChild(button);
  });
  updateDetectedRoom();
}

function resetCountInputs() {
  countForm.reset();
  updateCountPreview();
}

function updateSelectedRoomLabel() {
  selectedRoomLabel.textContent = `已选择：${state.selectedRoom || "-"}`;
}

function updateCountPreview() {
  const expected = parseCount(expectedInput);
  const actual = parseCount(actualInput);
  countPreview.classList.remove("bad");
  actualInput.removeAttribute("aria-invalid");
  if (expected === null || actual === null) {
    setAbsentOutput(null);
    countPreview.textContent = "请填写应到、实到。";
    return;
  }
  if (actual > expected) {
    setAbsentOutput(null);
    countPreview.textContent = "实到不能大于应到，请检查。";
    countPreview.classList.add("bad");
    actualInput.setAttribute("aria-invalid", "true");
    return;
  }
  const absent = expected - actual;
  setAbsentOutput(absent);
  const rate = expected > 0 ? actual / expected : 0;
  countPreview.textContent = `当前：缺考 ${absent} 人 · 出考率 ${formatRate(rate)}`;
}

function validateCounts() {
  const expected = parseCount(expectedInput);
  const actual = parseCount(actualInput);
  if (expected === null || actual === null) {
    return "应到、实到都必须填写非负整数";
  }
  if (actual > expected) {
    return "实到不能大于应到";
  }
  return "";
}

function getCountPayload() {
  const expectedCount = parseCount(expectedInput);
  const actualCount = parseCount(actualInput);
  const absentCount = expectedCount - actualCount;
  const attendanceRate = expectedCount > 0 ? actualCount / expectedCount : 0;
  return {
    roomName: state.selectedRoom,
    expectedCount,
    actualCount,
    absentCount,
    attendanceRate,
  };
}

function renderSummary(box, payload, withTitle) {
  box.innerHTML = "";
  const rows = [
    ["教室", payload.roomName],
    ["应到", payload.expectedCount + " 人"],
    ["实到", payload.actualCount + " 人"],
    ["缺考", payload.absentCount + " 人"],
    ["出考率", formatRate(payload.attendanceRate)],
  ];
  if (withTitle) rows.unshift(["考试", state.reportTitle || "-"]);
  rows.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "review-item";
    const labelElement = document.createElement("span");
    labelElement.textContent = label;
    const valueElement = document.createElement("strong");
    valueElement.textContent = value;
    item.append(labelElement, valueElement);
    box.appendChild(item);
  });
}

// 提交完成（或本机对应的教室早已提交）：停在完成页，不再预选别的教室，免得老师以为还要再确认一次
function showDone(report, joke) {
  state.doneRoom = report.roomName;
  state.doneSeq += 1;
  doneTitle.textContent = report.roomName + " 已提交";
  renderSummary(doneBox, report, false);
  doneJoke.textContent = joke || "";
  doneJoke.classList.toggle("hidden", !joke);
  setStep(4);
  doneTitle.focus();
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    const messageText = payload.error?.message || "请求失败";
    const failure = new Error(messageText);
    failure.code = payload.error?.code || "";
    if (failure.code === "NO_OPEN_SESSION") applySession({ open: false, closedMessage: messageText });
    throw failure;
  }
  return payload.data;
}

confirmRoomButton.addEventListener("click", async () => {
  clearMessages();
  if (!state.selectedRoom) {
    setMessage(stepOneMessage, "请先确认教室", "error");
    return;
  }
  try {
    await checkCurrentReportRoom(state.selectedRoom);
  } catch (error) {
    // 场次已关闭：requestJson 已切到「当前暂无可填报场次」空状态，这里不能再弹「数据未验收」
    if (error.code === "NO_OPEN_SESSION") return;
    const message = error.message || pendingAcceptanceMessage;
    setMessage(stepOneMessage, message, "error");
    await showAlert("数据未验收", message);
    return;
  }
  const projectLine = state.reportTitle
    ? `你当前正在上报的缺考是 ${state.reportTitle} 考试项目。\n如果不正确，请联系考务老师修改！`
    : "当前考试项目未设置，请联系考务老师进行设置！";
  const accepted = await showHighlightedConfirm(
    "确认教室",
    `你选择的是：${state.selectedRoom}` + (state.roomNotice ? "\n\n" + state.roomNotice : ""),
    projectLine,
    "确认无误",
  );
  if (!accepted) return;
  updateSelectedRoomLabel();
  resetCountInputs();
  setStep(2);
  expectedInput.focus();
});

changeRoomButton.addEventListener("click", () => {
  state.roomPickerOpen = !state.roomPickerOpen;
  clearMessages();
  renderClassrooms();
});

backToRoomButton.addEventListener("click", () => {
  clearMessages();
  setStep(1);
});

editCountsButton.addEventListener("click", () => {
  clearMessages();
  setStep(2);
});

[expectedInput, actualInput].forEach((input) => {
  // 中文输入法组合期间改 value 会打断组合（"４"→"４０" 会变成 "440"）：组合结束后再统一清洗
  input.addEventListener("input", (event) => {
    if (event.isComposing) return;
    sanitizeCountInput(input);
    updateCountPreview();
  });
  input.addEventListener("compositionend", () => {
    sanitizeCountInput(input);
    updateCountPreview();
  });
});
expectedInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    actualInput.focus();
  }
});

countForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearMessages();
  const error = validateCounts();
  if (error) {
    setMessage(stepTwoMessage, error, "error");
    (parseCount(expectedInput) === null ? expectedInput : actualInput).focus();
    return;
  }
  state.reviewPayload = getCountPayload();
  renderSummary(reviewBox, state.reviewPayload, true);
  setStep(3);
  reviewTitle.focus();
});

confirmAddButton.addEventListener("click", async () => {
  clearMessages();
  if (!state.reviewPayload) {
    setMessage(stepThreeMessage, "请先填写人数", "error");
    return;
  }
  if (state.reports.some((item) => item.roomName === state.reviewPayload.roomName)) {
    setMessage(stepThreeMessage, pendingAcceptanceMessage, "error");
    return;
  }
  const submitted = state.reviewPayload;
  confirmAddButton.disabled = true;
  editCountsButton.disabled = true;
  confirmAddButton.textContent = "提交中…";
  try {
    await saveCurrentReport(submitted);
    state.reviewPayload = null;
    resetCountInputs();
    showDone(submitted, randomCloseMessage());
  } catch (error) {
    setMessage(stepThreeMessage, error.message, "error");
  } finally {
    confirmAddButton.disabled = false;
    editCountsButton.disabled = false;
    confirmAddButton.textContent = "确认提交";
  }
});

// ---- 场次开关：GET /api/session，每 5 秒 + 页面重新可见时轮询 ----
const defaultClosedMessage = "当前暂无可填报场次，请联系考务管理员";
const closedMessageElement = document.querySelector("#closedMessage");
const sessionState = { open: null };

function applySession(session) {
  const open = Boolean(session.open);
  // 标题和考试日期由管理员下发时决定，前台只读显示
  state.reportTitle = open ? String(session.title || "") : "";
  state.reportDate = open ? String(session.examDate || "") : "";
  renderReportTitle();
  document.body.classList.remove("booting");
  document.body.classList.toggle("is-closed", !open);
  closedMessageElement.textContent = session.closedMessage || defaultClosedMessage;
  const wasOpen = sessionState.open;
  sessionState.open = open;
  if (!open) {
    // 关闭时收起所有流程状态，避免恢复后残留半途数据
    state.reviewPayload = null;
    appDialogCancel.click();
    return;
  }
  const examKey = state.reportTitle + "|" + state.reportDate;
  const newExam = sessionState.examKey !== undefined && sessionState.examKey !== examKey;
  sessionState.examKey = examKey;
  if (wasOpen === false || newExam) {
    // 新场次（包括两次轮询之间“验收→再下发”、页面没看到关闭的情况）：从第 1 步重新开始
    state.reviewPayload = null;
    appDialogCancel.click();
    if (state.step !== 4) setStep(1);
    loadSite().then(() => loadCurrentReports()).catch(() => {});
  }
}

async function pollSession() {
  try {
    const response = await fetch("/api/session", { cache: "no-store" });
    const payload = await response.json();
    if (payload.success) applySession(payload.data);
  } catch (error) {
    // 网络抖动：保持当前显示，下一轮重试；首次失败时不要卡在空白
    document.body.classList.remove("booting");
  }
}

renderClassrooms();
setStep(1);
updateCountPreview();
renderReportTitle();
pollSession();
// 教室名单来自后台配置：必须先拿到名单，再取已提交的教室和本机 IP 对应的教室（它们都要用名单做过滤/默认选择）
loadSite()
  .then(() => loadCurrentReports().catch(() => {})) // 先知道哪些教室已提交，默认选择才不会落在已填的教室上
  .then(() => loadClientContext())
  .then(() => {
    renderClassrooms();
    const mine = state.reports.find((item) => item.roomName === state.detectedRoom);
    if (mine && state.step === 1) showDone(mine, "");
  });
// 其他教室提交后本页的「已提交」状态要跟着变。刷新只重画教室按钮，不动当前步骤和已填的人数；
// 只有本页选中的教室被管理员从名单里删掉时，loadSite 才会把页面带回第 1 步（第 3 步也一样，否则提交必被拒）
function refreshLiveReport() {
  if (document.hidden) return;
  // 名单也要跟着刷：管理员在没有未验收数据时可以改教室名单，旧名单提交会被服务端拒绝
  loadSite().then(() => loadCurrentReports()).catch(() => {});
}
setInterval(pollSession, 5000);
setInterval(refreshLiveReport, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    pollSession();
    refreshLiveReport();
  }
});
