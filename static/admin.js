const loginView = document.querySelector("#loginView");
const adminView = document.querySelector("#adminView");
const loginForm = document.querySelector("#loginForm");
const loginButton = document.querySelector("#loginButton");
const loginMessage = document.querySelector("#loginMessage");
const logoutButton = document.querySelector("#logoutButton");
const filterForm = document.querySelector("#filterForm");
const resetButton = document.querySelector("#resetButton");
const exportButton = document.querySelector("#exportButton");
const previewExcelButton = document.querySelector("#previewExcelButton");
const importExcelButton = document.querySelector("#importExcelButton");
const excelPreviewSummary = document.querySelector("#excelPreviewSummary");
const excelPreviewContent = document.querySelector("#excelPreviewContent");
const excelPreviewEmpty = document.querySelector("#excelPreviewEmpty");
const refreshLogsButton = document.querySelector("#refreshLogsButton");
const logFilterForm = document.querySelector("#logFilterForm");
const resetLogsButton = document.querySelector("#resetLogsButton");
const reportRows = document.querySelector("#reportRows");
const emptyState = document.querySelector("#emptyState");
const logSummary = document.querySelector("#logSummary");
const logRows = document.querySelector("#logRows");
const logEmptyState = document.querySelector("#logEmptyState");
const pagerInfo = document.querySelector("#pagerInfo");
const prevButton = document.querySelector("#prevButton");
const nextButton = document.querySelector("#nextButton");
const adminMessage = document.querySelector("#adminMessage");
const detailModal = document.querySelector("#detailModal");
const closeModalButton = document.querySelector("#closeModalButton");
const editDetailButton = document.querySelector("#editDetailButton");
const exportDetailImageButton = document.querySelector("#exportDetailImageButton");
const detailContent = document.querySelector("#detailContent");
const editModal = document.querySelector("#editModal");
const editReportForm = document.querySelector("#editReportForm");
const editReportTitle = document.querySelector("#editReportTitle");
const editExamDate = document.querySelector("#editExamDate");
const editSessionName = document.querySelector("#editSessionName");
const editRows = document.querySelector("#editRows");
const editSummary = document.querySelector("#editSummary");
const saveEditButton = document.querySelector("#saveEditButton");
const cancelEditButton = document.querySelector("#cancelEditButton");
const editMessage = document.querySelector("#editMessage");
const adminDialog = document.querySelector("#adminDialog");
const adminDialogTitle = document.querySelector("#adminDialogTitle");
const adminDialogBody = document.querySelector("#adminDialogBody");
const adminDialogInputWrap = document.querySelector("#adminDialogInputWrap");
const adminDialogInputLabel = document.querySelector("#adminDialogInputLabel");
const adminDialogInput = document.querySelector("#adminDialogInput");
const adminDialogCancel = document.querySelector("#adminDialogCancel");
const adminDialogConfirm = document.querySelector("#adminDialogConfirm");

const state = {
  page: 1,
  pageSize: 10,
  total: 0,
  title: "",
  from: "",
  to: "",
  room: "",
  metrics: { compare: "people", trend: "rate", rooms: "rate" },
  showAllRooms: false,
  analytics: null,
  logDate: "",
  logKeyword: "",
  currentDetail: null,
  editingReport: null,
  excelPreview: null,
  view: "",
};

function formatRate(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function formatRooms(value) {
  return `${Number(value || 0)}个`;
}

function formatPeople(value) {
  return `${Number(value || 0)}人`;
}

function formatTime(value) {
  if (!value) return "";
  return value.replace("T", " ").replace("+08:00", "");
}

function eventTypeText(value) {
  const labels = {
    admin_login: "后台登录",
    admin_logout: "退出登录",
    admin_login_failed: "登录失败",
    project_updated: "项目修改",
    project_update_blocked: "项目锁定",
    project_update_failed: "项目失败",
    report_submitted: "数据提交",
    report_updated: "数据修改",
    report_group_updated: "后台修改",
    report_edit_failed: "修改失败",
    excel_previewed: "Excel预览",
    excel_imported: "Excel导入",
    excel_import_failed: "导入失败",
    duplicate_report_blocked: "重复拦截",
    reports_accepted: "数据验收",
    reports_exported: "表格导出",
    accept_failed: "验收失败",
    reports_deleted: "后台删除",
    report_delete_failed: "删除失败",
    logs_cleaned: "日志清理",
    client_enrolled: "客户端登记",
    dispatch_created: "创建下发",
    dispatch_cancelled: "取消下发",
    dispatch_fired: "下发触发",
    dispatch_missed: "下发错过",
    session_opened: "场次开启",
    session_closed: "场次关闭",
    client_blocked: "客户端拉黑",
    client_unblocked: "解除拉黑",
    client_deleted: "客户端删除",
    password_changed: "修改密码",
    room_rule_changed: "教室规则修改",
    site_changed: "基本信息修改",
    db_backup: "数据库备份",
    db_exported: "数据库导出",
    db_imported: "数据库导入",
  };
  return labels[value] || value || "日志";
}

function setMessage(element, text, type = "") {
  element.textContent = text;
  element.className = `message ${type}`.trim();
}

let adminDialogOpen = false;

function showAdminDialog(options = {}) {
  // 共用同一个对话框：已有对话框打开时直接拒绝，避免监听器叠加后一次确认触发多次回调
  if (adminDialogOpen) return Promise.resolve(options.input ? null : false);
  adminDialogOpen = true;
  const opener = document.activeElement;
  return new Promise((resolve) => {
    const {
      title = "确认",
      message = "",
      confirmText = "确认",
      cancelText = "取消",
      showCancel = true,
      input = false,
      inputLabel = "请输入",
      inputType = "text",
      danger = false,
    } = options;

    adminDialogTitle.textContent = title;
    adminDialogBody.textContent = message;
    adminDialogConfirm.textContent = confirmText;
    adminDialogConfirm.className = `button ${danger ? "danger" : ""}`.trim();
    adminDialogCancel.textContent = cancelText;
    adminDialogCancel.classList.toggle("hidden", !showCancel);
    adminDialogInputWrap.classList.toggle("hidden", !input);
    adminDialogInputLabel.textContent = inputLabel;
    adminDialogInput.type = inputType;
    adminDialogInput.value = "";
    adminDialog.classList.add("open");
    adminDialog.setAttribute("aria-hidden", "false");

    const cleanup = (value) => {
      adminDialogOpen = false;
      adminDialog.classList.remove("open");
      adminDialog.setAttribute("aria-hidden", "true");
      adminDialog.removeEventListener("keydown", trapTab);
      if (opener && typeof opener.focus === "function" && document.contains(opener)) opener.focus();
      adminDialogConfirm.removeEventListener("click", onConfirm);
      adminDialogCancel.removeEventListener("click", onCancel);
      adminDialog.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKeydown);
      resolve(value);
    };

    const onConfirm = () => {
      cleanup(input ? adminDialogInput.value : true);
    };
    const onCancel = () => cleanup(input ? null : false);
    const onBackdrop = (event) => {
      if (event.target === adminDialog && showCancel) {
        cleanup(input ? null : false);
      }
    };
    const onKeydown = (event) => {
      if (event.key === "Escape" && showCancel) {
        cleanup(input ? null : false);
      }
      if (event.key === "Enter" && input) {
        onConfirm();
      }
    };

    // 焦点陷阱：Tab/Shift+Tab 只在对话框内循环，不能跑到遮罩后面的页面上
    const trapTab = (event) => {
      if (event.key !== "Tab") return;
      const items = [adminDialogInput, adminDialogCancel, adminDialogConfirm].filter((el) => el.offsetParent !== null && !el.disabled);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      else if (!adminDialog.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
    };

    adminDialogConfirm.addEventListener("click", onConfirm);
    adminDialogCancel.addEventListener("click", onCancel);
    adminDialog.addEventListener("click", onBackdrop);
    adminDialog.addEventListener("keydown", trapTab);
    document.addEventListener("keydown", onKeydown);

    window.setTimeout(() => {
      (input ? adminDialogInput : adminDialogConfirm).focus();
    }, 0);
  });
}

function showAdminConfirm(title, message, confirmText = "确认", danger = false) {
  return showAdminDialog({
    title,
    message,
    confirmText,
    showCancel: true,
    danger,
  });
}

function showLogin() {
  loginView.classList.remove("hidden");
  adminView.classList.add("hidden");
  stopLive();
  document.querySelector("#password").focus();
}

function showAdmin() {
  const wasHidden = adminView.classList.contains("hidden");
  loginView.classList.add("hidden");
  adminView.classList.remove("hidden");
  if (wasHidden) {
    setView(viewFromHash(), { force: true });
    loadSiteInfo();
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
    keepSession: undefined,
  });
  const payload = await response.json();
  // keepSession：修改密码接口用 401 表示旧密码错误，不应踢回登录页
  // 服务端对「未登录」返回 code=UNAUTHORIZED + 「请先登录」；改密码的「旧密码不正确」也是 401，两者靠 message 区分
  if (response.status === 401 && (!options.keepSession || payload.error?.message === "请先登录")) {
    showLogin();
  }
  if (!response.ok || !payload.success) {
    const messageText = payload.error?.message || "请求失败";
    const failure = new Error(messageText);
    failure.code = payload.error?.code || "";
    failure.status = response.status;
    throw failure;
  }
  return payload.data;
}

function buildQuery(includePage = false, f = state) {
  const params = new URLSearchParams();
  if (f.title) params.set("title", f.title);
  if (f.from) params.set("from", f.from);
  if (f.to) params.set("to", f.to);
  if (includePage) {
    params.set("page", String(f.page ?? state.page));
    params.set("pageSize", String(state.pageSize));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function buildLogQuery() {
  const params = new URLSearchParams();
  if (state.logDate) params.set("date", state.logDate);
  if (state.logKeyword) params.set("keyword", state.logKeyword);
  params.set("page", "1");
  params.set("pageSize", "10");
  return `?${params.toString()}`;
}

function renderSummary(summary) {
  document.querySelector("#summaryCount").textContent = summary.reportCount;
  document.querySelector("#summaryExpected").textContent =
    summary.totalExpectedCount;
  document.querySelector("#summaryActual").textContent = summary.totalActualCount;
  document.querySelector("#summaryAbsent").textContent = summary.totalAbsentCount;
  document.querySelector("#summaryRate").textContent = formatRate(
    summary.overallAttendanceRate,
  );
}

function renderRows(items) {
  reportRows.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("tr");
    row.className = item.roomCount > 1 ? "grouped-row" : "";
    row.innerHTML = `
      <td class="title-cell"></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>
        <div class="row-actions">
          <button class="button ghost detail-button" type="button">详情</button>
          <button class="button ghost row-edit-report-button" type="button">修改</button>
          <button class="button ghost row-export-button" type="button" title="导出图片">导图</button>
          <button class="button ghost danger-text row-delete-button" type="button">删除</button>
        </div>
      </td>
    `;
    const cells = row.querySelectorAll("td");
    cells[0].textContent = item.title;
    cells[1].textContent = item.examDate;
    cells[2].textContent = item.sessionName || "-";
    cells[3].textContent = item.roomSummary || item.roomName;
    cells[3].title =
      item.roomCount > 1 ? `点击详情查看 ${item.roomCount} 间教室` : "";
    cells[4].textContent = item.expectedCount;
    cells[5].textContent = item.actualCount;
    cells[6].textContent = item.absentCount;
    cells[7].textContent = formatRate(item.attendanceRate);
    cells[8].textContent = item.totalCount;
    cells[9].textContent = formatRate(item.totalAttendanceRate);
    cells[10].textContent = formatTime(item.createdAt);
    row.querySelector(".detail-button").addEventListener("click", () =>
      openDetail(item.id),
    );
    row.querySelector(".row-edit-report-button").addEventListener("click", () =>
      openEditReport(item.id),
    );
    row.querySelector(".row-export-button").addEventListener("click", () =>
      exportReportImageById(item.id),
    );
    row.querySelector(".row-delete-button").addEventListener("click", () =>
      deleteReport(item),
    );
    reportRows.appendChild(row);
  }
  emptyState.classList.toggle("hidden", items.length > 0);
}

// 机构名和地址来自「基本信息」，导图时现取，改了立刻生效
let siteInfo = { orgName: "", orgAddress: "" };
async function loadSiteInfo() {
  try {
    siteInfo = await requestJson("/api/site");
  } catch (error) {
    // 取不到就用上一次的；导图不会因此失败
  }
  document.querySelector("#railOrg").textContent = siteInfo.orgName || "未填写单位名称";
  // 首次使用还没填单位名称：直接带到「设置 → 基本信息」
  if (!siteInfo.orgName && !siteInfoPrompted) {
    siteInfoPrompted = true;
    setView("settings");
    setMessage(document.querySelector("#siteMessage"), "欢迎使用！请先填写单位名称并保存，它会显示在填报页和统计表上。", "error");
    document.querySelector("#siteOrgName").focus();
  }
}
let siteInfoPrompted = false;

async function exportReportSnapshotNow(report) {
  await loadSiteInfo();
  exportReportSnapshot(report);
}

function exportReportSnapshot(report) {
  const rooms = Array.isArray(report.items) ? report.items : [report];
  if (rooms.length === 0) {
    setMessage(adminMessage, "当前没有可导出的统计表", "error");
    return;
  }

  const sheets = downloadReportSnapshotImage(
    {
      title: report.title,
      examDate: report.examDate,
      rooms,
      totals: {
        expectedCount: report.expectedCount,
        actualCount: report.actualCount,
        absentCount: report.absentCount,
        attendanceRate: report.attendanceRate,
      },
    },
    siteInfo,
  );
  if (sheets === 1) {
    setMessage(adminMessage, "统计表已导出：一张 A4 竖版图片（先列每间教室，最后是全部汇总）。", "success");
  } else if (sheets === 2) {
    setMessage(adminMessage, "教室太多，一张 A4 图片看不清，已改为导出 HTML 网页（先列每间教室，最后是全部汇总），用浏览器打开即可，也能直接打印。", "success");
  }
}

async function exportReportImageById(id) {
  setMessage(adminMessage, "");
  try {
    const report = await requestJson(`/api/admin/reports/${id}`);
    await exportReportSnapshotNow(report);
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}

function renderPager() {
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  pagerInfo.textContent = `第 ${state.page} 页，共 ${state.total} 条`;
  prevButton.disabled = state.page <= 1;
  nextButton.disabled = state.page >= totalPages;
}

function renderLogSummary(summary) {
  const items = Array.isArray(summary.items) ? summary.items : [];
  logSummary.innerHTML = "";
  if (items.length === 0) {
    return;
  }
  items.slice(0, 8).forEach((item) => {
    const badge = document.createElement("div");
    badge.className = `log-badge ${item.severity === "warning" ? "warning" : ""}`.trim();
    badge.innerHTML = `
      <span></span>
      <strong></strong>
    `;
    badge.querySelector("span").textContent = eventTypeText(item.eventType);
    badge.querySelector("strong").textContent = item.count;
    logSummary.appendChild(badge);
  });
}

function renderLogs(logs) {
  logRows.innerHTML = "";
  const items = Array.isArray(logs.items) ? logs.items : [];
  items.forEach((item) => {
    const row = document.createElement("article");
    row.className = `log-row ${item.severity === "warning" ? "warning" : ""}`.trim();
    row.innerHTML = `
      <div class="log-row-main">
        <span class="log-type"></span>
        <strong></strong>
        <p></p>
      </div>
      <div class="log-meta"></div>
    `;
    row.querySelector(".log-type").textContent = eventTypeText(item.eventType);
    row.querySelector("strong").textContent = item.title;
    row.querySelector("p").textContent = item.message;
    const meta = [
      formatTime(item.createdAt),
      item.actorIp ? `IP ${item.actorIp}` : "",
      item.roomName ? `教室 ${item.roomName}` : "",
      item.batchToken ? `批次 ${item.batchToken}` : "",
      item.reportId ? `记录 #${item.reportId}` : "",
    ].filter(Boolean);
    row.querySelector(".log-meta").textContent = meta.join(" · ");
    logRows.appendChild(row);
  });
  logEmptyState.classList.toggle("hidden", items.length > 0);
}

function renderExcelPreview(result) {
  excelPreviewSummary.classList.remove("hidden");
  excelPreviewEmpty.classList.add("hidden");
  excelPreviewSummary.innerHTML = `
    <div class="metric">
      <span>文件</span>
      <strong></strong>
    </div>
    <div class="metric">
      <span>识别表格</span>
      <strong>${formatRooms(result.tableCount)}</strong>
    </div>
    <div class="metric">
      <span>教室数据</span>
      <strong>${Number(result.validRowCount || 0)}条</strong>
    </div>
    <div class="metric">
      <span>可直接导入</span>
      <strong>${formatRooms(result.readyTableCount)}</strong>
    </div>
    <div class="metric ${result.problemCount ? "warning" : ""}">
      <span>放弃导入</span>
      <strong>${Number(result.discardedRowCount || 0)}行</strong>
    </div>
  `;
  excelPreviewSummary.querySelector("strong").textContent = result.fileName || "-";

  const tables = Array.isArray(result.tables) ? result.tables : [];
  const problems = Array.isArray(result.problems) ? result.problems : [];
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const discarded = Array.isArray(result.discardedItems)
    ? result.discardedItems
    : [];
  excelPreviewContent.innerHTML = "";

  const problemBox = document.createElement("section");
  problemBox.className = "excel-problem-box";
  problemBox.innerHTML = `
    <div class="excel-section-title">
      <h3>清洗提示</h3>
      <span></span>
    </div>
    <div class="excel-problem-list"></div>
  `;
  problemBox.querySelector("span").textContent = warnings.length
    ? `显示前 ${Math.min(warnings.length, 200)} 项`
    : "没有清洗提示";
  const problemList = problemBox.querySelector(".excel-problem-list");
  if (warnings.length === 0) {
    problemList.innerHTML = `<div class="empty small">当前 Excel 没有需要特别提示的清洗项。</div>`;
  } else {
    warnings.slice(0, 200).forEach((warning) => {
      const item = document.createElement("div");
      item.className = "excel-problem-item warning";
      item.innerHTML = `
        <strong></strong>
        <span></span>
      `;
      item.querySelector("strong").textContent = "需要复核";
      item.querySelector("span").textContent = [
        warning.sheetName,
        `第${warning.tableIndex}张表`,
        warning.rowNumber ? `第${warning.rowNumber}行` : "",
        warning.message,
      ]
        .filter(Boolean)
        .join(" · ");
      problemList.appendChild(item);
    });
  }
  excelPreviewContent.appendChild(problemBox);

  const discardedBox = document.createElement("section");
  discardedBox.className = "excel-problem-box";
  discardedBox.innerHTML = `
    <div class="excel-section-title">
      <h3>放弃导入的数据</h3>
      <span></span>
    </div>
    <div class="excel-problem-list"></div>
  `;
  discardedBox.querySelector("span").textContent = discarded.length
    ? `显示前 ${Math.min(discarded.length, 200)} 行`
    : "没有放弃导入的数据";
  const discardedList = discardedBox.querySelector(".excel-problem-list");
  if (discarded.length === 0) {
    discardedList.innerHTML = `<div class="empty small">没有因为缺少人数等原因被放弃的数据。</div>`;
  } else {
    discarded.slice(0, 200).forEach((row) => {
      const item = document.createElement("div");
      item.className = "excel-problem-item";
      item.innerHTML = `
        <strong></strong>
        <span></span>
      `;
      item.querySelector("strong").textContent = row.reason;
      item.querySelector("span").textContent = [
        row.sheetName,
        `第${row.tableIndex}张表`,
        `第${row.rowNumber}行`,
        row.room ? `教室：${row.room}` : "",
        row.expected !== null && row.expected !== undefined
          ? `应到：${row.expected}`
          : "",
        row.actual !== null && row.actual !== undefined
          ? `实到：${row.actual}`
          : "",
      ]
        .filter(Boolean)
        .join(" · ");
      discardedList.appendChild(item);
    });
  }
  excelPreviewContent.appendChild(discardedBox);

  const tableBox = document.createElement("section");
  tableBox.className = "excel-table-box";
  tableBox.innerHTML = `
    <div class="excel-section-title">
      <h3>识别到的表格</h3>
      <span></span>
    </div>
    <div class="excel-table-list"></div>
  `;
  tableBox.querySelector("span").textContent = `显示前 ${Math.min(
    tables.length,
    20,
  )} 张，共 ${tables.length} 张`;
  const tableList = tableBox.querySelector(".excel-table-list");
  tables.slice(0, 20).forEach((table) => {
    const totalExpected = table.items.reduce(
      (sum, item) => sum + Number(item.expectedCount || 0),
      0,
    );
    const totalActual = table.items.reduce(
      (sum, item) => sum + Number(item.actualCount || 0),
      0,
    );
    const totalRate = totalExpected > 0 ? totalActual / totalExpected : 0;
    const card = document.createElement("article");
    card.className = `excel-table-card ${
      table.problems?.length ? "has-problem" : ""
    }`.trim();
    card.innerHTML = `
      <div class="excel-table-card-head">
        <strong></strong>
        <span></span>
      </div>
      <div class="excel-table-meta"></div>
      <div class="excel-table-preview"></div>
    `;
    card.querySelector("strong").textContent = table.title || "-";
    card.querySelector("span").textContent = table.problems?.length
      ? `${table.problems.length} 个问题`
      : table.discardedItems?.length
        ? `放弃 ${table.discardedItems.length} 行`
        : table.warnings?.length
          ? `${table.warnings.length} 个提示`
          : "可导入";
    card.querySelector(".excel-table-meta").textContent = [
      table.sheetName,
      table.examDate || "日期待确认",
      table.needsDateReview ? "占位日期待修改" : "",
      table.sessionName || "场次自动识别",
      table.dateSource,
      `${table.items.length} 个教室`,
      table.discardedItems?.length ? `放弃 ${table.discardedItems.length} 行` : "",
      `应到 ${totalExpected} 人`,
      `实到 ${totalActual} 人`,
      `出考率 ${formatRate(totalRate)}`,
    ]
      .filter(Boolean)
      .join(" · ");
    const preview = card.querySelector(".excel-table-preview");
    table.items.slice(0, 6).forEach((item) => {
      const pill = document.createElement("span");
      pill.textContent = `${item.roomName} ${item.expectedCount}/${item.actualCount}`;
      preview.appendChild(pill);
    });
    if (table.items.length > 6) {
      const more = document.createElement("span");
      more.textContent = `另 ${table.items.length - 6} 个`;
      preview.appendChild(more);
    }
    tableList.appendChild(card);
  });
  excelPreviewContent.appendChild(tableBox);
}

async function previewExcelImport() {
  setMessage(adminMessage, "");
  state.excelPreview = null;
  importExcelButton.disabled = true;
  previewExcelButton.disabled = true;
  previewExcelButton.textContent = "解析中...";
  try {
    const result = await requestJson("/api/admin/import/excel-preview");
    state.excelPreview = result;
    renderExcelPreview(result);
    importExcelButton.disabled = false;
    await loadLogs();
    setMessage(
      adminMessage,
      "Excel 预览已生成，目前只是读取分析，没有写入数据库。",
      "success",
    );
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  } finally {
    previewExcelButton.disabled = false;
    previewExcelButton.textContent = "预览桌面 Excel";
  }
}

async function importCleanedExcel() {
  setMessage(adminMessage, "");
  if (!state.excelPreview) {
    setMessage(adminMessage, "请先预览 Excel，再执行导入。", "error");
    return;
  }
  const confirmed = await showAdminConfirm(
    "确认导入 Excel",
    [
      `将导入“${state.excelPreview.fileName}”中清洗后的有效数据。`,
      `可识别教室数据 ${state.excelPreview.validRowCount} 条。`,
      `缺少应到或实到等无效数据 ${state.excelPreview.discardedRowCount} 行会放弃导入。`,
      `缺少日期的表会使用 1900-01-01 占位，导入后需要在后台手动修改。`,
      "系统会在导入前自动备份数据库。",
    ].join("\n"),
    "继续导入",
    true,
  );
  if (!confirmed) return;
  importExcelButton.disabled = true;
  importExcelButton.textContent = "导入中...";
  try {
    const result = await requestJson("/api/admin/import/excel", { method: "POST", body: "{}" });
    await loadData();
    await loadLogs();
    setMessage(
      adminMessage,
      `Excel 导入完成：导入 ${result.importedTables} 张表、${result.importedRows} 条教室数据；放弃 ${result.discardedRows} 行无效数据。`,
      "success",
    );
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
    importExcelButton.disabled = false;
  } finally {
    importExcelButton.textContent = "导入清洗后数据";
  }
}

async function loadLogs() {
  const [summary, logs] = await Promise.all([
    requestJson("/api/admin/logs/summary"),
    requestJson(`/api/admin/logs${buildLogQuery()}`),
  ]);
  renderLogSummary(summary);
  renderLogs(logs);
}

async function deleteReport(item) {
  setMessage(adminMessage, "");
  const firstConfirmed = await showAdminConfirm(
    "确认删除",
    `将从数据库永久删除这条后台记录：\n\n${item.title}\n${item.examDate} ${item.sessionName || ""}\n${item.roomSummary || item.roomName}\n\n删除后不可恢复。`,
    "继续删除",
    true,
  );
  if (!firstConfirmed) return;

  const secondConfirmed = await showAdminConfirm(
    "二次确认",
    "这是不可恢复操作，会从数据库彻底删除该场次下的全部教室数据。确认继续？",
    "确认永久删除",
    true,
  );
  if (!secondConfirmed) return;

  try {
    const result = await requestJson(`/api/admin/reports/${item.id}`, { method: "DELETE" });
    if (reportRows.children.length <= 1 && state.page > 1) {
      state.page -= 1;
    }
    await loadData();
    setMessage(
      adminMessage,
      `已永久删除 ${result.deletedCount} 条数据库记录。`,
      "success",
    );
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}

function readFilter(data) {
  state.title = String(data.get("title") || "").trim();
  state.from = String(data.get("from") || "");
  state.to = String(data.get("to") || "");
}

// ---- 当前场次条：进行中默认展开教室格子，没有场次时折起；管理员手动点过就不再自动改 ----
const boardToggle = document.querySelector("#boardToggle");
const boardBody = document.querySelector("#boardBody");
const board = { manual: false, open: false };
function setBoard(open) {
  board.open = open;
  boardBody.hidden = !open;
  boardToggle.setAttribute("aria-expanded", String(open));
  boardToggle.textContent = open ? "收起教室" : "展开教室";
}
function autoBoard(sessionOpen) {
  if (!board.manual) setBoard(sessionOpen);
}
boardToggle.addEventListener("click", () => {
  board.manual = true;
  setBoard(!board.open);
});

const acceptButton = document.querySelector("#acceptButton");
acceptButton.addEventListener("click", async () => {
  setMessage(adminMessage, "");
  let data;
  try {
    data = await requestJson("/api/admin/live");
  } catch (error) {
    setMessage(adminMessage, "暂时无法获取最新填报情况：" + error.message, "error");
    return;
  }
  const filled = data.rooms.filter((room) => room.submitted);
  const missing = data.rooms.filter((room) => !room.submitted).map((room) => room.roomName);
  const lines = filled.length
    ? [`已填报 ${filled.length} / ${data.rooms.length} 间，验收后数据入库、场次关闭，教室不能再填。`,
       missing.length ? `未填报：${missing.slice(0, 12).join("、")}${missing.length > 12 ? ` 等 ${missing.length} 间` : ""}` : "全部教室都已填报。"]
    : ["当前场次还没有任何教室提交数据，继续将直接关闭本场次，教室不能再填报。"];
  const ok = await showAdminConfirm(filled.length ? "验收并结束本场" : "结束本场", lines.join("\n\n"), filled.length ? "确认验收" : "结束本场", true);
  if (!ok) return;
  acceptButton.disabled = true;
  try {
    const result = await requestJson("/api/admin/accept", { method: "POST", body: "{}" });
    await loadData(); // 会先清掉旧提示，所以成功提示要放在它后面
    live.busy = false;
    await refreshLive();
    setMessage(adminMessage, result.message || `验收完成，入库 ${result.savedCount} 间教室。`, "success");
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
    acceptButton.disabled = false;
  }
});

// ---- 图表：数据来自 /api/admin/analytics，画图交给 static/charts.js ----
function renderCharts() {
  const data = state.analytics;
  if (!data) return;
  const none = data.totals.exams === 0;
  document.querySelector("#chartsEmpty").classList.toggle("hidden", !none);
  document.querySelector("#chartsGrid").classList.toggle("hidden", none);
  const f = state.analyticsFilter || state;
  const parts = [];
  if (f.title) parts.push(`标题包含“${f.title}”`);
  if (f.from || f.to) parts.push(`日期 ${f.from || "最早"} 至 ${f.to || "最新"}`);
  document.querySelector("#chartsNote").textContent = (parts.length ? parts.join("，") : "全部数据") + `：共 ${data.totals.exams} 场考试、${data.rooms.length} 间教室`;
  if (none) return;
  QkCharts.compare(document.querySelector("#chartCompare"), data.exams, state.metrics.compare);
  QkCharts.trend(document.querySelector("#chartTrend"), data.exams, state.metrics.trend);
  QkCharts.rooms(document.querySelector("#chartRooms"), data.rooms, state.metrics.rooms, state.showAllRooms);
  QkCharts.top(document.querySelector("#chartTop"), data.topAbsent);
  QkCharts.dist(document.querySelector("#chartDist"), data.distribution);
  const pick = document.querySelector("#roomPick");
  const keep = f.room;
  pick.innerHTML = '<option value="">选择教室…</option>';
  data.rooms.forEach((room) => {
    const option = document.createElement("option");
    option.value = option.textContent = room.roomName;
    pick.appendChild(option);
  });
  pick.value = data.rooms.some((room) => room.roomName === keep) ? keep : "";
  QkCharts.roomHistory(document.querySelector("#chartRoom"), data.roomHistory, pick.value);
}

document.querySelector("#chartsGrid").addEventListener("click", (event) => {
  const more = event.target.closest("[data-showall]");
  if (more) {
    state.showAllRooms = more.dataset.showall === "1";
    renderCharts();
    return;
  }
  const button = event.target.closest("[data-metric]");
  if (!button) return;
  const figure = button.closest("figure");
  const key = figure.querySelector(".chart-body").id === "chartCompare" ? "compare" : figure.querySelector(".chart-body").id === "chartTrend" ? "trend" : "rooms";
  state.metrics[key] = button.dataset.metric;
  figure.querySelectorAll("[data-metric]").forEach((node) => node.setAttribute("aria-pressed", String(node === button)));
  renderCharts();
});
let resizeTimer = 0;
window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => { if (state.view === "data") renderCharts(); }, 200);
});
document.querySelector("#roomPick").addEventListener("change", async (event) => {
  state.room = event.target.value;
  try {
    await loadData();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
});

let dataSeq = 0;
async function loadData() {
  setMessage(adminMessage, "");
  // 只认最后一次发出的查询：连续筛选时，先发后到的旧响应必须丢掉，否则旧结果会盖在新条件上
  const seq = ++dataSeq;
  const f = { title: state.title, from: state.from, to: state.to, room: state.room, page: state.page };
  try {
    const [summary, reports, analytics] = await Promise.all([
      requestJson(`/api/admin/reports/summary${buildQuery(false, f)}`),
      requestJson(`/api/admin/reports${buildQuery(true, f)}`),
      requestJson(`/api/admin/analytics${buildQuery(false, f)}${f.room ? (buildQuery(false, f) ? "&" : "?") + "room=" + encodeURIComponent(f.room) : ""}`),
    ]);
    if (seq !== dataSeq) return;
    state.total = reports.total;
    state.analytics = analytics;
    state.analyticsFilter = f;
    renderSummary(summary);
    renderRows(reports.items);
    renderPager();
    showAdmin();
    renderCharts(); // 必须在页面可见之后画：隐藏时容器宽度是 0，图会按最小宽度画成一小条
    loadLogs().catch(() => {});
  } catch (error) {
    if (seq === dataSeq) setMessage(adminMessage, error.message, "error");
  }
}

function detailItem(label, value, full = false) {
  const item = document.createElement("div");
  item.className = `detail-item ${full ? "full" : ""}`.trim();
  const labelElement = document.createElement("span");
  labelElement.textContent = label;
  const valueElement = document.createElement("div");
  valueElement.textContent = value || "-";
  item.append(labelElement, valueElement);
  return item;
}

function renderRoomDetails(items) {
  const section = document.createElement("section");
  section.className = "detail-item full room-detail-section";

  const heading = document.createElement("span");
  heading.textContent = "教室数据详情";

  const tableWrap = document.createElement("div");
  tableWrap.className = "detail-table-wrap";
  tableWrap.innerHTML = `
    <table class="detail-table">
      <thead>
        <tr>
          <th>教室</th>
          <th>应到</th>
          <th>实到</th>
          <th>缺考</th>
          <th>出考率</th>
          <th>提交时间</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  `;
  const tbody = tableWrap.querySelector("tbody");
  for (const item of items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    `;
    const cells = row.querySelectorAll("td");
    cells[0].textContent = item.roomName;
    cells[1].textContent = item.expectedCount;
    cells[2].textContent = item.actualCount;
    cells[3].textContent = item.absentCount;
    cells[4].textContent = formatRate(item.attendanceRate);
    cells[5].textContent = formatTime(item.createdAt);
    tbody.appendChild(row);
  }

  section.append(heading, tableWrap);
  return section;
}

function closeEditModal() {
  editModal.classList.remove("open");
  state.editingReport = null;
  editReportForm.reset();
  editRows.innerHTML = "";
  editSummary.textContent = "";
  setMessage(editMessage, "");
}

function parseEditCount(input) {
  if (input.value === "") return null;
  const value = Number(input.value);
  if (!Number.isInteger(value) || value < 0) return null;
  return value;
}

function updateEditPreview() {
  let totalExpected = 0;
  let totalActual = 0;
  let hasError = false;
  editRows.querySelectorAll("tr").forEach((row) => {
    const expectedInput = row.querySelector("[data-field='expected']");
    const actualInput = row.querySelector("[data-field='actual']");
    const absentCell = row.querySelector("[data-field='absent']");
    const rateCell = row.querySelector("[data-field='rate']");
    const expected = parseEditCount(expectedInput);
    const actual = parseEditCount(actualInput);
    if (expected === null || actual === null || actual > expected) {
      absentCell.textContent = "-";
      rateCell.textContent = "-";
      hasError = true;
      return;
    }
    totalExpected += expected;
    totalActual += actual;
    absentCell.textContent = `${expected - actual}人`;
    rateCell.textContent = formatRate(expected > 0 ? actual / expected : 0);
  });
  const totalAbsent = totalExpected - totalActual;
  const totalRate = totalExpected > 0 ? totalActual / totalExpected : 0;
  editSummary.textContent = hasError
    ? "请检查人数：应到、实到必须是非负整数，且实到不能大于应到。"
    : `合计：应到 ${formatPeople(totalExpected)}，实到 ${formatPeople(totalActual)}，缺考 ${formatPeople(totalAbsent)}，总出考率 ${formatRate(totalRate)}`;
  editSummary.classList.toggle("error", hasError);
}

function renderEditRows(report) {
  const rooms = Array.isArray(report.items) ? report.items : [report];
  editRows.innerHTML = "";
  rooms.forEach((item) => {
    const row = document.createElement("tr");
    row.dataset.id = item.id;
    row.innerHTML = `
      <td></td>
      <td><input data-field="expected" type="number" min="0" step="1" inputmode="numeric" required /></td>
      <td><input data-field="actual" type="number" min="0" step="1" inputmode="numeric" required /></td>
      <td data-field="absent"></td>
      <td data-field="rate"></td>
    `;
    row.children[0].textContent = item.roomName;
    row.querySelector("[data-field='expected']").value = item.expectedCount;
    row.querySelector("[data-field='actual']").value = item.actualCount;
    row.querySelectorAll("input").forEach((input) => {
      input.addEventListener("input", updateEditPreview);
    });
    editRows.appendChild(row);
  });
  updateEditPreview();
}

async function openEditReport(id) {
  setMessage(adminMessage, "");
  setMessage(editMessage, "");
  try {
    const report = await requestJson(`/api/admin/reports/${id}`);
    state.editingReport = report;
    editReportTitle.value = report.title || "";
    editExamDate.value = report.examDate || "";
    editSessionName.value = report.manualSessionName || "";
    editSessionName.placeholder = report.sessionName
      ? `留空则显示 ${report.sessionName}`
      : "留空则自动显示第几场";
    renderEditRows(report);
    detailModal.classList.remove("open");
    editModal.classList.add("open");
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}

function buildEditPayload() {
  const items = [];
  editRows.querySelectorAll("tr").forEach((row) => {
    const expected = parseEditCount(row.querySelector("[data-field='expected']"));
    const actual = parseEditCount(row.querySelector("[data-field='actual']"));
    items.push({
      id: Number(row.dataset.id),
      expectedCount: expected,
      actualCount: actual,
    });
  });
  return {
    title: editReportTitle.value.trim(),
    examDate: editExamDate.value,
    sessionName: editSessionName.value.trim(),
    items,
  };
}

async function saveEditedReport(event) {
  event.preventDefault();
  if (!state.editingReport) return;
  setMessage(editMessage, "");
  const payload = buildEditPayload();
  if (!payload.title) {
    setMessage(editMessage, "请填写考试项目名称", "error");
    return;
  }
  if (!payload.examDate) {
    setMessage(editMessage, "请选择考试日期", "error");
    return;
  }
  const invalid = payload.items.some(
    (item) =>
      item.expectedCount === null ||
      item.actualCount === null ||
      item.actualCount > item.expectedCount,
  );
  if (invalid) {
    setMessage(editMessage, "请检查人数，实到不能大于应到。", "error");
    return;
  }
  const confirmed = await showAdminConfirm(
    "确认修改",
    `将修改“${state.editingReport.title}”这场已入库数据。保存后系统会重新计算缺考、出考率和总数。确认继续？`,
    "确认保存",
    true,
  );
  if (!confirmed) return;

  saveEditButton.disabled = true;
  saveEditButton.textContent = "保存中...";
  try {
    await requestJson(`/api/admin/reports/${state.editingReport.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    closeEditModal();
    await loadData();
    await loadLogs();
    setMessage(adminMessage, "已保存修改，统计数据已重新计算。", "success");
  } catch (error) {
    setMessage(editMessage, error.message, "error");
  } finally {
    saveEditButton.disabled = false;
    saveEditButton.textContent = "保存修改";
  }
}

async function openDetail(id) {
  try {
    const report = await requestJson(`/api/admin/reports/${id}`);
    const rooms = Array.isArray(report.items) ? report.items : [report];
    state.currentDetail = report;
    detailContent.innerHTML = "";
    detailContent.append(
      detailItem("上报标题", report.title, true),
      detailItem("日期", report.examDate),
      detailItem("场次", report.sessionName || "-"),
      detailItem("教室数量", report.roomCount || rooms.length),
      detailItem("教室", report.roomSummary || report.roomName),
      detailItem("应到人数", report.expectedCount),
      detailItem("实到人数", report.actualCount),
      detailItem("缺考人数", report.absentCount),
      detailItem("出考率", formatRate(report.attendanceRate)),
      detailItem("总数", report.totalCount),
      detailItem("总出考率", formatRate(report.totalAttendanceRate)),
      detailItem("验收批次", report.batchToken || "-", true),
      detailItem("提交 IP", report.clientIp),
      detailItem("提交时间", formatTime(report.createdAt)),
      renderRoomDetails(rooms),
    );
    detailModal.classList.add("open");
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(loginMessage, "");
  loginButton.disabled = true;
  loginButton.textContent = "登录中...";
  try {
    const password = new FormData(loginForm).get("password");
    const login = await requestJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    loginForm.reset();
    if (login.mustChangePassword) {
      showFirstPassword(password);
      return;
    }
    state.page = 1;
    await loadData();
  } catch (error) {
    setMessage(loginMessage, error.message, "error");
  } finally {
    loginButton.disabled = false;
    loginButton.textContent = "登录";
  }
});

logoutButton.addEventListener("click", async () => {
  try {
    await requestJson("/api/admin/logout", { method: "POST" });
  } finally {
    showLogin();
  }
});

filterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(filterForm);
  readFilter(data);
  state.page = 1;
  await loadData();
});

resetButton.addEventListener("click", async () => {
  filterForm.reset();
  state.title = state.from = state.to = state.room = "";
  state.page = 1;
  await loadData();
});

exportButton.addEventListener("click", () => {
  readFilter(new FormData(filterForm));
  window.location.href = `/api/admin/reports/export${buildQuery(false)}`;
});

previewExcelButton.addEventListener("click", previewExcelImport);
importExcelButton.addEventListener("click", importCleanedExcel);

refreshLogsButton.addEventListener("click", async () => {
  setMessage(adminMessage, "");
  try {
    await loadLogs();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
});

logFilterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(logFilterForm);
  state.logDate = String(data.get("date") || "");
  state.logKeyword = String(data.get("keyword") || "").trim();
  try {
    await loadLogs();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
});

resetLogsButton.addEventListener("click", async () => {
  logFilterForm.reset();
  state.logDate = "";
  state.logKeyword = "";
  try {
    await loadLogs();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
});

prevButton.addEventListener("click", async () => {
  if (state.page > 1) {
    state.page -= 1;
    await loadData();
  }
});

nextButton.addEventListener("click", async () => {
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (state.page < totalPages) {
    state.page += 1;
    await loadData();
  }
});

closeModalButton.addEventListener("click", () => {
  detailModal.classList.remove("open");
});

editDetailButton.addEventListener("click", () => {
  if (!state.currentDetail) {
    setMessage(adminMessage, "没有可修改的详情数据", "error");
    return;
  }
  openEditReport(state.currentDetail.id);
});

exportDetailImageButton.addEventListener("click", () => {
  if (!state.currentDetail) {
    setMessage(adminMessage, "没有可导出的详情数据", "error");
    return;
  }
  exportReportSnapshotNow(state.currentDetail);
});

detailModal.addEventListener("click", (event) => {
  if (event.target === detailModal) {
    detailModal.classList.remove("open");
  }
});

editModal.addEventListener("click", (event) => {
  if (event.target === editModal) {
    closeEditModal();
  }
});

cancelEditButton.addEventListener("click", closeEditModal);
editReportForm.addEventListener("submit", saveEditedReport);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    detailModal.classList.remove("open");
    closeEditModal();
  }
});

// ================= 多视图 / 实时看板 / 下发 / 客户端 / 设置 =================
const VIEWS = {
  data: ["数据", "当前场次的填报进度；按标题和日期筛选后做统计、可视化对比，查看和修改已入库数据。"],
  dispatch: ["下发", "向教室电脑推送“请填写缺考信息”弹窗，并开启填报场次；盯着谁已弹窗、谁已确认。"],
  clients: ["客户端", "教室电脑上的绑定客户端：在线状态、拉黑与删除。"],
  logs: ["日志", "记录提交、验收、下发、客户端与设置等关键动作。"],
  settings: ["设置", "访问地址、教室识别规则与管理密码。"],
};
const navItems = document.querySelectorAll("[data-nav]");
const viewTitle = document.querySelector("#viewTitle");
const viewDesc = document.querySelector("#viewDesc");
const connState = document.querySelector("#connState");
const live = { data: null, timer: null, generation: 0, busy: false, offsetMs: 0, baseMs: 0, baseAt: 0, failures: 0 };
const noticeText = { none: "未弹", shown: "已弹", confirmed: "已确认", opened: "已打开", failed: "失败" };
const noticeTone = { none: "", shown: "info", confirmed: "ok", opened: "ok", failed: "bad" };
const dispatchStatusText = { pending: "待触发", fired: "已触发", cancelled: "已取消", missed: "已错过" };
const dispatchStatusTone = { pending: "warn", fired: "ok", cancelled: "", missed: "bad" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function chip(text, tone = "") {
  return el("span", `chip ${tone}`.trim(), text);
}

function viewFromHash() {
  const name = window.location.hash.replace("#", "");
  return VIEWS[name] ? name : "data";
}

function setView(name, options = {}) {
  if (!VIEWS[name]) name = "data";
  if (state.view === name && !options.force) return;
  state.view = name;
  if (window.location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  document.querySelectorAll("[data-view]").forEach((node) => {
    node.hidden = node.dataset.view !== name;
  });
  navItems.forEach((item) => {
    if (item.dataset.nav === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  viewTitle.textContent = VIEWS[name][0];
  viewDesc.textContent = VIEWS[name][1];
  document.title = `${VIEWS[name][0]} - 考务管理后台`;
  setMessage(adminMessage, "");
  if (name === "data" || name === "dispatch" || name === "clients") {
    refreshLive();
    startLive();
  } else {
    stopLive();
  }
  if (name === "dispatch") loadDispatches().catch(() => {});
  if (name === "settings") loadSettings().catch((e) => setMessage(adminMessage, e.message, "error"));
  if (name === "logs") loadLogs().catch(() => {});
  if (name === "data" && !options.force) loadData();
}

navItems.forEach((item) => item.addEventListener("click", () => setView(item.dataset.nav)));
window.addEventListener("hashchange", () => {
  if (!adminView.classList.contains("hidden")) setView(viewFromHash());
});

// ---- 轮询：3 秒，页面不可见时暂停 ----
function liveWanted() {
  return (
    !document.hidden &&
    !adminView.classList.contains("hidden") &&
    ["data", "dispatch", "clients"].includes(state.view)
  );
}

function startLive() {
  if (live.timer) return;
  const generation = ++live.generation;
  const loop = async () => {
    if (liveWanted()) await refreshLive();
    // 请求挂起期间 stopLive→startLive 会开新一代循环；旧一代醒来后必须自己退出，否则会出现两条并行定时链
    if (generation !== live.generation || live.timer === null) return;
    live.timer = window.setTimeout(loop, 3000);
  };
  live.timer = window.setTimeout(loop, 3000);
}

function stopLive() {
  window.clearTimeout(live.timer);
  live.timer = null;
  live.generation += 1;
}

async function refreshLive() {
  if (live.busy || !liveWanted()) return;
  live.busy = true;
  try {
    const data = await requestJson("/api/admin/live");
    live.data = data;
    live.failures = 0;
    calibrateClock(data.serverTime);
    renderLive(data);
    connState.textContent = `已更新 ${clockText()}`;
    connState.className = "conn";
  } catch (error) {
    live.failures += 1;
    if (!adminView.classList.contains("hidden")) {
      connState.textContent = "连接异常，正在重试…";
    }
  } finally {
    live.busy = false;
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshLive();
});

// ---- 服务器时钟：每次 live 校准，本地计时器按秒走 ----
function parseServerTime(iso) {
  const text = String(iso || "");
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}+08:00`);
}

function calibrateClock(iso) {
  const ms = parseServerTime(iso);
  if (Number.isNaN(ms)) return;
  live.baseMs = ms;
  live.baseAt = Date.now();
  tickClock();
}

function serverNow() {
  // 取服务器 UTC+8 墙钟：把毫秒平移 8 小时后用 UTC 方法读取
  const ms = live.baseMs + (Date.now() - live.baseAt) + 8 * 3600 * 1000;
  return new Date(ms).toISOString().slice(0, 19);
}

function clockText() {
  return live.baseMs ? serverNow().replace("T", " ") : "--";
}

function tickClock() {
  const clock = document.querySelector("#serverClock");
  clock.textContent = clockText();
}
window.setInterval(tickClock, 1000);

// ---- 实时看板渲染 ----
function renderLive(data) {
  const summary = data.summary || {};
  document.querySelector("#kpiClients").innerHTML = `${Number(summary.clientsOnline || 0)}<small> / ${Number(summary.clientsTotal || 0)}</small>`;
  const offline = Number(summary.clientsTotal || 0) - Number(summary.clientsOnline || 0);
  document.querySelector("#kpiClientsNote").textContent = Number(summary.clientsTotal || 0) === 0 ? "暂无客户端登记" : offline > 0 ? `${offline} 台离线` : "全部在线";
  document.querySelector("#boardNote").textContent = data.session && data.session.open ? (data.session.title || "未设置标题") + " · " + (data.session.examDate || "") : "尚未下发或已验收";
  document.querySelector("#kpiRooms").innerHTML = `${Number(summary.roomsSubmitted || 0)}<small> / ${Number(summary.roomsTotal)}</small>`;
  document.querySelector("#kpiRoomsNote").textContent = `未填报 ${Number(summary.roomsTotal) - Number(summary.roomsSubmitted || 0)} 间`;
  const open = Boolean(data.session && data.session.open);
  document.querySelector("#kpiSession").textContent = open ? "填报中" : "未开启";
  document.querySelector("#kpiSessionNote").textContent = open ? data.session.title || "未设置考试项目" : "验收后或尚未下发";
  document.querySelector("#kpiSessionBox").className = `kpi ${open ? "open" : "closed"}`;
  renderRoomGrid(data);
  if (state.view === "dispatch") renderLiveSide(data);
  autoBoard(Boolean(data.session && data.session.open));
  acceptButton.disabled = !(data.session && data.session.open) && Number(summary.roomsSubmitted || 0) === 0;
  acceptButton.textContent = Number(summary.roomsSubmitted || 0) === 0 ? "结束本场（无数据）" : "验收并结束本场";
  if (state.view === "dispatch") renderDispatchRows(data.dispatches || []);
  if (state.view === "clients") renderClientRows(data.clients || []);
}

function roomOfflineClients(room, clients) {
  const ids = new Set(room.clientIds || []);
  return clients.filter((client) => ids.has(client.clientId) && !client.online);
}

function renderRoomGrid(data) {
  const grid = document.querySelector("#roomGrid");
  const clients = data.clients || [];
  grid.innerHTML = "";
  (data.rooms || []).forEach((room) => {
    const report = room.report;
    const button = el("button", `room-cell ${room.submitted ? "filled" : "unfilled"}`);
    button.type = "button";
    const offlineClients = roomOfflineClients(room, clients);
    if (offlineClients.length) button.classList.add("offline");
    const head = el("div", "rn");
    head.append(el("span", "", room.roomName));
    if (offlineClients.length) {
      const tag = el("span", "tag-off");
      tag.innerHTML = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 8.8a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M3 3l18 18"/></svg>';
      tag.append("离线");
      head.append(tag);
    }
    button.append(head);
    if (room.submitted && report) {
      const line = (label, value, cls = "") => {
        const row = el("div", `line ${cls}`.trim());
        row.append(el("span", "", label), el("b", "", String(value)));
        return row;
      };
      button.append(
        line("应到", report.expectedCount),
        line("实到", report.actualCount),
        line("缺考", report.absentCount, "abs"),
        el("div", "rate", formatRate(report.attendanceRate)),
      );
    } else {
      button.append(el("div", "none", offlineClients.length ? "未填报 · 客户端离线" : "未填报"));
    }
    button.setAttribute(
      "aria-label",
      room.submitted && report
        ? `${room.roomName} 已填报，应到 ${report.expectedCount}，实到 ${report.actualCount}，缺考 ${report.absentCount}${offlineClients.length ? "，客户端离线" : ""}`
        : `${room.roomName} 未填报${offlineClients.length ? "，客户端离线" : ""}`,
    );
    button.addEventListener("click", () => showRoomDetail(room, clients));
    grid.appendChild(button);
  });
}

function showRoomDetail(room, clients) {
  const report = room.report;
  const ids = new Set(room.clientIds || []);
  const own = clients.filter((client) => ids.has(client.clientId));
  const lines = [];
  if (room.submitted && report) {
    lines.push(
      `应到 ${report.expectedCount} 人`,
      `实到 ${report.actualCount} 人`,
      `缺考 ${report.absentCount} 人`,
      `出考率 ${formatRate(report.attendanceRate)}`,
      `更新时间 ${formatTime(report.updatedAt)}`,
    );
  } else {
    lines.push("本场尚未填报。");
  }
  lines.push("");
  if (own.length === 0) lines.push("该教室暂无已登记客户端。");
  own.forEach((client) => {
    lines.push(
      `客户端 ${client.name || client.clientId}（${client.ip}）· ${client.online ? "在线" : "离线"}${client.blocked ? " · 已拉黑" : ""}`,
      `  最后心跳 ${formatTime(client.lastSeenAt) || "-"} · 下发状态 ${noticeText[client.notice?.state || "none"]}`,
    );
  });
  return showAdminDialog({ title: room.roomName, message: lines.join("\n"), confirmText: "关闭", showCancel: false });
}

function renderLiveSide(data) {
  const box = document.querySelector("#liveDispatch");
  const list = document.querySelector("#liveClients");
  const current = (data.dispatches || []).find((item) => item.id === data.session?.dispatchId) || (data.dispatches || [])[0];
  box.innerHTML = "";
  if (current) {
    const brief = el("div", "dispatch-brief");
    const top = el("div", "");
    top.append(chip(dispatchStatusText[current.status] || current.status, dispatchStatusTone[current.status] || ""), " ", el("span", "", `#${current.id} · ${formatTime(current.firedAt || current.scheduledAt || current.createdAt)}`));
    const counts = el("div", "counts");
    const c = current.counts || {};
    [["在线", c.online], ["已弹", c.shown], ["已确认", c.confirmed], ["已打开", c.opened], ["失败", c.failed]].forEach(([label, value]) => {
      const span = el("span", "", label);
      span.append(el("b", "", String(value ?? 0)));
      counts.appendChild(span);
    });
    brief.append(top, el("div", "msg", current.message), counts);
    box.appendChild(brief);
  } else {
    box.appendChild(el("div", "empty small", "还没有下发记录"));
  }
  list.innerHTML = "";
  const clients = [...(data.clients || [])].sort((a, b) => (a.roomNumber || 99) - (b.roomNumber || 99));
  if (clients.length === 0) {
    list.appendChild(el("div", "empty small", "暂无客户端登记"));
    return;
  }
  clients.forEach((client) => {
    const row = el("div", `cs-row ${client.online ? "" : "off"}`.trim());
    const left = el("div", "");
    left.append(el("strong", "", `${client.roomName || "未匹配"} · ${client.name || client.clientId.slice(0, 8)}`), el("br"), el("small", "", `${client.ip}${client.online ? "" : " · 离线"}`));
    const state = client.notice?.state || "none";
    row.append(left, chip(noticeText[state] || state, noticeTone[state] || ""));
    list.appendChild(row);
  });
}

// ---- 下发 ----
const dispatchForm = document.querySelector("#dispatchForm");
const dispatchMessage = document.querySelector("#dispatchMessage");
const dispatchTitle = document.querySelector("#dispatchTitle");
const dispatchTitleErr = document.querySelector("#dispatchTitleErr");
const dispatchExamDate = document.querySelector("#dispatchExamDate");
const dispatchAt = document.querySelector("#dispatchAt");
const dispatchSubmit = document.querySelector("#dispatchSubmit");
const dispatchResult = document.querySelector("#dispatchResult");
const dispatchMessageErr = document.querySelector("#dispatchMessageErr");
const dispatchAtErr = document.querySelector("#dispatchAtErr");
const defaultDispatchText = "请点击确定填写缺考信息";
dispatchMessage.value = defaultDispatchText;

function dispatchMode() {
  return dispatchForm.querySelector("input[name='dispatchMode']:checked").value;
}

// 与服务端 qk_agents.py 的 MESSAGE_LINE_CHARS/MESSAGE_MAX_LINES 和客户端 client/fit.go 保持一致：
// 每个硬行按 30 字折行累加，最多 9 行（一个换行至少占一整行，所以只数字数或只数换行都不够）。
const MESSAGE_LINE_CHARS = 30;
const MESSAGE_MAX_LINES = 9;
// 宽字符约 2em，按 2 计；ASCII/拉丁/常用标点/CJK 按 1（与服务端 _weight、客户端 runeWeight 一致，CJK_RANGES 逐项一致）
const CJK_RANGES = [[0x1100, 0x11ff], [0x2e80, 0x2fdf], [0x3000, 0x30ff], [0x3100, 0x312f], [0x3400, 0x4dbf], [0x4e00, 0x9fff],
  [0xac00, 0xd7af], [0xf900, 0xfaff], [0xfe30, 0xfe4f], [0xff00, 0xffef]]; // 补充平面汉字故意不在表里：按「未知一律 2」处理
function messageWeight(line) {
  return Array.from(line).reduce((sum, ch) => {
    const o = ch.codePointAt(0);
    const narrow = o < 0x250 || (o >= 0x2000 && o <= 0x206f) || CJK_RANGES.some(([lo, hi]) => o >= lo && o <= hi);
    return sum + (narrow ? 1 : 2);
  }, 0);
}
function messageDisplayLines(value) {
  return value
    .replace(/\r\n|[\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/g, "\n")
    .split("\n")
    .reduce((sum, line) => sum + Math.max(1, Math.ceil(messageWeight(line) / MESSAGE_LINE_CHARS)), 0);
}

function updateDispatchForm() {
  const scheduled = dispatchMode() === "scheduled";
  document.querySelector("#scheduleField").classList.toggle("hidden", !scheduled);
  dispatchSubmit.textContent = scheduled ? "创建定时下发" : "立即下发";
  document.querySelector("#dispatchMessageCount").textContent = `${dispatchMessage.value.length} / 200 字，约 ${messageDisplayLines(dispatchMessage.value)} / ${MESSAGE_MAX_LINES} 行`;
}
dispatchForm.addEventListener("change", updateDispatchForm);
dispatchMessage.addEventListener("input", () => {
  dispatchMessageErr.textContent = "";
  dispatchMessage.removeAttribute("aria-invalid");
  updateDispatchForm();
});
dispatchAt.addEventListener("input", () => {
  dispatchAtErr.textContent = "";
  dispatchAt.removeAttribute("aria-invalid");
});

let dispatchInFlight = false;
dispatchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (dispatchInFlight) return; // 确认框打开期间/请求进行中，再次提交一律忽略
  dispatchInFlight = true;
  try {
    await submitDispatch();
  } finally {
    dispatchInFlight = false;
  }
});

async function submitDispatch() {
  setMessage(dispatchResult, "");
  const message = dispatchMessage.value.trim();
  const mode = dispatchMode();
  let invalid = false;
  dispatchTitleErr.textContent = "";
  if (!dispatchTitle.value.trim()) {
    dispatchTitleErr.textContent = "请填写标题（每次下发都要填，它是统计表的表头）";
    dispatchTitle.setAttribute("aria-invalid", "true");
    invalid = true;
  }
  if (!message) {
    dispatchMessageErr.textContent = "请填写弹窗内容";
    dispatchMessage.setAttribute("aria-invalid", "true");
    invalid = true;
  }
  if (messageDisplayLines(message) > MESSAGE_MAX_LINES) {
    dispatchMessageErr.textContent = `弹窗内容太长或换行太多（每行约 ${MESSAGE_LINE_CHARS} 字，最多 ${MESSAGE_MAX_LINES} 行；表情、符号、箭头、生僻字等每个按 2 字计）`;
    dispatchMessage.setAttribute("aria-invalid", "true");
    invalid = true;
  }
  if (mode === "scheduled") {
    if (!dispatchAt.value) {
      dispatchAtErr.textContent = "请选择下发时间";
      dispatchAt.setAttribute("aria-invalid", "true");
      invalid = true;
    } else if (live.baseMs && dispatchAt.value <= serverNow().slice(0, 16)) {
      dispatchAtErr.textContent = "下发时间必须晚于服务器当前时间";
      dispatchAt.setAttribute("aria-invalid", "true");
      invalid = true;
    }
  }
  if (invalid) {
    (dispatchTitleErr.textContent ? dispatchTitle : dispatchMessageErr.textContent ? dispatchMessage : dispatchAt).focus();
    return;
  }
  if (mode === "now") {
    const confirmed = await showAdminConfirm(
      "确认立即下发",
      `将立即向所有在线教室电脑弹出通知，并开启填报场次：\n\n“${message}”\n\n确认下发？`,
      "立即下发",
      true,
    );
    if (!confirmed) return;
  }
  const body = { message, mode, title: dispatchTitle.value.trim() };
  if (dispatchExamDate.value) body.examDate = dispatchExamDate.value;
  if (mode === "scheduled") body.scheduledAt = dispatchAt.value;
  dispatchSubmit.disabled = true;
  try {
    const result = await requestJson("/api/admin/dispatch", { method: "POST", body: JSON.stringify(body) });
    setMessage(dispatchResult, mode === "now" ? (`已下发（#${result.id}）。` + (result.titleKept ? `当前已有未验收数据，统计表表头沿用「${result.sessionTitle}」（${result.sessionExamDate}），本次填写的标题和日期未生效；验收后再下发即可使用新标题。` : "")) : `已创建定时下发（#${result.id}），按服务器时间 ${dispatchAt.value.replace("T", " ")} 触发。`, "success");
    await loadDispatches();
    refreshLive();
  } catch (error) {
    if (/时间|scheduled/i.test(error.message) && mode === "scheduled") {
      dispatchAtErr.textContent = error.message;
      dispatchAt.setAttribute("aria-invalid", "true");
    } else {
      setMessage(dispatchResult, error.message, "error");
    }
  } finally {
    dispatchSubmit.disabled = false;
  }
}

async function loadDispatches() {
  const result = await requestJson("/api/admin/dispatches");
  renderDispatchRows(result.items || []);
}

function renderDispatchRows(items) {
  const body = document.querySelector("#dispatchRows");
  body.innerHTML = "";
  items.forEach((item) => {
    const row = document.createElement("tr");
    const counts = item.counts || {};
    const cells = [
      `#${item.id}`,
      item.title ? `${item.title}：${item.message}` : item.message,
      item.mode === "scheduled" ? `定时 ${formatTime(item.scheduledAt)}` : "立即",
    ];
    cells.forEach((text, index) => {
      const td = el("td", index === 1 ? "wrap" : "", text);
      row.appendChild(td);
    });
    const statusCell = document.createElement("td");
    statusCell.appendChild(chip(dispatchStatusText[item.status] || item.status, dispatchStatusTone[item.status] || ""));
    row.appendChild(statusCell);
    [counts.online, counts.shown, counts.confirmed, counts.opened, counts.failed].forEach((value) => row.appendChild(el("td", "num", String(value ?? 0))));
    row.appendChild(el("td", "", formatTime(item.firedAt || item.createdAt)));
    const actions = document.createElement("td");
    if (item.status === "pending") {
      const cancel = el("button", "button ghost danger-text", "取消");
      cancel.type = "button";
      cancel.addEventListener("click", () => cancelDispatch(item));
      actions.appendChild(cancel);
    }
    row.appendChild(actions);
    body.appendChild(row);
  });
  document.querySelector("#dispatchEmpty").classList.toggle("hidden", items.length > 0);
}

async function cancelDispatch(item) {
  const confirmed = await showAdminConfirm("取消定时下发", `取消 #${item.id}“${item.message}”？取消后不会再触发。`, "取消下发", true);
  if (!confirmed) return;
  try {
    await requestJson(`/api/admin/dispatches/${item.id}/cancel`, { method: "POST", body: "{}" });
    setMessage(adminMessage, `已取消下发 #${item.id}。`, "success");
    await loadDispatches();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}
document.querySelector("#refreshDispatches").addEventListener("click", () => loadDispatches().catch((e) => setMessage(adminMessage, e.message, "error")));

// ---- 客户端 ----
function renderClientRows(clients) {
  const body = document.querySelector("#clientRows");
  body.innerHTML = "";
  clients.forEach((client) => {
    const row = document.createElement("tr");
    row.appendChild(el("td", "", client.name || "-"));
    row.appendChild(el("td", "num", client.ip || "-"));
    row.appendChild(el("td", "", client.roomName || "未匹配"));
    const online = document.createElement("td");
    online.appendChild(client.blocked ? chip("已拉黑", "bad") : client.online ? chip("在线", "ok") : chip("离线", "warn"));
    row.appendChild(online);
    row.appendChild(el("td", "num", formatTime(client.lastSeenAt) || "-"));
    row.appendChild(el("td", "num", client.version || "-"));
    const noticeCell = document.createElement("td");
    const st = client.notice?.state || "none";
    noticeCell.appendChild(chip(noticeText[st] || st, noticeTone[st] || ""));
    row.appendChild(noticeCell);
    const actions = el("td", "");
    const group = el("div", "row-actions");
    const block = el("button", "button ghost", client.blocked ? "解除拉黑" : "拉黑");
    block.type = "button";
    block.addEventListener("click", () => toggleBlock(client));
    const remove = el("button", "button ghost danger-text", "删除");
    remove.type = "button";
    remove.addEventListener("click", () => deleteClient(client));
    group.append(block, remove);
    actions.appendChild(group);
    row.appendChild(actions);
    body.appendChild(row);
  });
  document.querySelector("#clientEmpty").classList.toggle("hidden", clients.length > 0);
}

async function toggleBlock(client) {
  const target = !client.blocked;
  if (target) {
    const confirmed = await showAdminConfirm("拉黑客户端", `拉黑后“${client.name || client.ip}”将不再收到下发。确认拉黑？`, "确认拉黑", true);
    if (!confirmed) return;
  }
  try {
    await requestJson(`/api/admin/clients/${encodeURIComponent(client.clientId)}/block`, { method: "POST", body: JSON.stringify({ blocked: target }) });
    setMessage(adminMessage, target ? "已拉黑。" : "已解除拉黑。", "success");
    refreshLive();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}

async function deleteClient(client) {
  const confirmed = await showAdminConfirm("删除客户端", `将删除客户端“${client.name || client.ip}”（${client.ip}）的登记记录。客户端再次联网时会重新登记。确认删除？`, "确认删除", true);
  if (!confirmed) return;
  try {
    await requestJson(`/api/admin/clients/${encodeURIComponent(client.clientId)}`, { method: "DELETE" });
    setMessage(adminMessage, "客户端已删除。", "success");
    refreshLive();
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
}

document.querySelector("#refreshClients").addEventListener("click", refreshLive);
document.querySelector("#downloadClient").addEventListener("click", async () => {
  setMessage(adminMessage, "");
  try {
    const response = await fetch("/api/admin/client/download");
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok) {
      let code = "";
      let text = "下载失败";
      try {
        const payload = await response.json();
        code = payload.error?.code || "";
        text = payload.error?.message || text;
      } catch (ignored) {}
      setMessage(adminMessage, code === "CLIENT_TEMPLATE_MISSING" ? "尚未构建客户端模板，请先在开发机运行 scripts/build_client.sh。" : text, "error");
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "qeukao-client.exe";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    setMessage(adminMessage, "已下载 qeukao-client.exe，已绑定本服务端。", "success");
  } catch (error) {
    setMessage(adminMessage, error.message, "error");
  }
});

// ---- 设置 ----
const ruleOctet = document.querySelector("#ruleOctet");
const rulePrefix = document.querySelector("#rulePrefix");
const ruleIp = document.querySelector("#ruleIp");
const ruleResult = document.querySelector("#ruleResult");
const rulePrefixErr = document.querySelector("#rulePrefixErr");
const ruleMessage = document.querySelector("#ruleMessage");
const prefixPattern = /^(\d{1,3}\.){0,3}$/;
let previewSeq = 0;

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (ignored) {}
  // 局域网 http 页面没有 clipboard API，退回 execCommand
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;left:-9999px;top:0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (ignored) {}
  area.remove();
  return ok;
}

function renderAccessUrls(urls) {
  const box = document.querySelector("#accessUrls");
  box.innerHTML = "";
  urls.forEach((item) => {
    [["填报地址（教室电脑）", item.fillUrl], ["管理地址", item.adminUrl]].forEach(([kind, url], index) => {
      const row = el("div", "url-row");
      const left = el("div", "");
      left.append(el("span", "url-kind", kind), el("span", "ip", item.ip));
      const code = el("code", "", url);
      const button = el("button", "button secondary small", "复制");
      button.type = "button";
      button.setAttribute("aria-label", `复制${kind} ${url}`);
      button.addEventListener("click", async () => {
        const ok = await copyText(url);
        button.textContent = ok ? "已复制" : "复制失败";
        window.setTimeout(() => (button.textContent = "复制"), 1800);
      });
      row.append(left, code, button);
      box.appendChild(row);
    });
  });
  document.querySelector("#accessEmpty").classList.toggle("hidden", urls.length > 0);
}

// ---- 基本信息 ----
const siteForm = document.querySelector("#siteForm");
const siteOrgName = document.querySelector("#siteOrgName");
const siteOrgAddress = document.querySelector("#siteOrgAddress");
const siteRoomCount = document.querySelector("#siteRoomCount");
const siteRoomNames = document.querySelector("#siteRoomNames");
const siteMessage = document.querySelector("#siteMessage");
const siteNaming = () => siteForm.querySelector("input[name='siteNaming']:checked").value;

function updateSiteForm() {
  const custom = siteNaming() === "custom";
  siteRoomNames.classList.toggle("hidden", !custom);
  document.querySelector("#siteRoomsHint").textContent = custom
    ? "名称个数必须等于教室数量。IP 的第几段就是第几行。"
    : "IP 第几段就是第几间教室；名称按「一教室、二教室……」自动生成。";
}
siteForm.addEventListener("change", updateSiteForm);
siteRoomCount.addEventListener("input", updateSiteForm);

function renderSite(settings) {
  const site = settings.site;
  siteOrgName.value = site.orgName;
  siteOrgAddress.value = site.orgAddress;
  document.querySelector("#siteRoomNotice").value = site.roomNotice || "";
  siteRoomCount.value = site.roomCount;
  siteForm.querySelector("input[name='siteNaming'][value='" + (site.roomNames.length ? "custom" : "auto") + "']").checked = true;
  siteRoomNames.value = settings.roomNames.join("\n");
  const locked = Boolean(settings.hasUnacceptedData);
  siteRoomCount.disabled = locked;
  siteRoomNames.disabled = locked;
  siteForm.querySelectorAll("input[name='siteNaming']").forEach((node) => { node.disabled = locked; });
  document.querySelector("#siteLocked").classList.toggle("hidden", !locked);
  document.querySelector("#siteOrgNameErr").textContent = "";
  document.querySelector("#siteRoomNamesErr").textContent = "";
  updateSiteForm();
}

siteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(siteMessage, "");
  const orgErr = document.querySelector("#siteOrgNameErr");
  const namesErr = document.querySelector("#siteRoomNamesErr");
  orgErr.textContent = namesErr.textContent = "";
  const body = { orgName: siteOrgName.value.trim(), orgAddress: siteOrgAddress.value.trim(), roomNotice: document.querySelector("#siteRoomNotice").value.trim() };
  if (!body.orgName) {
    orgErr.textContent = "请填写单位名称";
    siteOrgName.focus();
    return;
  }
  if (!siteRoomCount.disabled) {
    const count = Number(siteRoomCount.value);
    if (!Number.isInteger(count) || count < 1 || count > 500) {
      setMessage(siteMessage, "教室数量需要是 1–500 的整数", "error");
      siteRoomCount.focus();
      return;
    }
    body.roomCount = count;
    if (siteNaming() === "custom") {
      const names = siteRoomNames.value.split("\n").map((line) => line.trim()).filter(Boolean);
      if (names.length !== count) {
        namesErr.textContent = `名称有 ${names.length} 行，教室数量是 ${count}，两者必须一致`;
        siteRoomNames.focus();
        return;
      }
      body.roomNames = names;
    } else {
      body.roomNames = [];
    }
  }
  document.querySelector("#saveSite").disabled = true;
  try {
    await requestJson("/api/admin/site", { method: "POST", body: JSON.stringify(body) });
    setMessage(siteMessage, "已保存。", "success");
    loadSiteInfo();
    await loadSettings();
  } catch (error) {
    setMessage(siteMessage, error.message, "error");
  } finally {
    document.querySelector("#saveSite").disabled = false;
  }
});

async function loadSettings() {
  const settings = await requestJson("/api/admin/settings");
  renderSite(settings);
  document.querySelector("#serverNameText").textContent = settings.serverName || "考务服务端";
  renderAccessUrls(settings.accessUrls || []);
  ruleOctet.value = String(settings.roomRule?.octet || 3);
  rulePrefix.value = settings.roomRule?.prefix || "";
  rulePrefixErr.textContent = "";
  previewRule();
}

async function previewRule() {
  const ip = ruleIp.value.trim();
  if (!ip) {
    ruleResult.className = "rule-result";
    ruleResult.textContent = "输入 IP 查看对应教室";
    return;
  }
  if (!prefixPattern.test(rulePrefix.value.trim())) return;
  const seq = ++previewSeq;
  try {
    const result = await requestJson("/api/admin/settings/room-rule/preview", {
      method: "POST",
      body: JSON.stringify({ octet: Number(ruleOctet.value), prefix: rulePrefix.value.trim(), ip }),
    });
    if (seq !== previewSeq) return;
    ruleResult.className = `rule-result ${result.matched ? "ok" : "bad"}`;
    ruleResult.textContent = result.matched ? `${ip} → ${result.roomName}` : `${ip} 无法对应任何教室（超出教室数量范围或前缀不符）`;
  } catch (error) {
    if (seq !== previewSeq) return;
    ruleResult.className = "rule-result bad";
    ruleResult.textContent = error.message;
  }
}

let previewTimer = null;
[ruleOctet, rulePrefix, ruleIp].forEach((input) => {
  input.addEventListener("input", () => {
    rulePrefixErr.textContent = "";
    rulePrefix.removeAttribute("aria-invalid");
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(previewRule, 250);
  });
});

document.querySelector("#suggestRule").addEventListener("click", async () => {
  setMessage(ruleMessage, "");
  try {
    const result = await requestJson("/api/admin/settings/room-rule/suggest");
    const suggestion = result.suggestion;
    if (!suggestion) {
      document.querySelector("#suggestText").textContent = "已登记客户端不足，或 IP 中没有落在教室数量范围内的段，暂无推荐。";
      return;
    }
    ruleOctet.value = String(suggestion.octet);
    rulePrefix.value = suggestion.prefix || "";
    document.querySelector("#suggestText").textContent = `推荐：第 ${suggestion.octet} 段，前缀 ${suggestion.prefix || "（空）"}，匹配 ${suggestion.matched}/${suggestion.total} 台。已套用，确认无误后点“保存规则”。`;
    previewRule();
  } catch (error) {
    setMessage(ruleMessage, error.message, "error");
  }
});

document.querySelector("#ruleForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(ruleMessage, "");
  const prefix = rulePrefix.value.trim();
  if (!prefixPattern.test(prefix)) {
    rulePrefixErr.textContent = "前缀应为空或形如 10.10.（以点结尾）";
    rulePrefix.setAttribute("aria-invalid", "true");
    rulePrefix.focus();
    return;
  }
  try {
    await requestJson("/api/admin/settings/room-rule", { method: "POST", body: JSON.stringify({ octet: Number(ruleOctet.value), prefix }) });
    setMessage(ruleMessage, "教室识别规则已保存。", "success");
  } catch (error) {
    rulePrefixErr.textContent = error.message;
    rulePrefix.setAttribute("aria-invalid", "true");
  }
});
document.querySelector("#refreshSettings").addEventListener("click", () => loadSettings().catch((e) => setMessage(adminMessage, e.message, "error")));

const pwFields = { old: document.querySelector("#pwOld"), next: document.querySelector("#pwNew"), confirm: document.querySelector("#pwConfirm") };
const pwErrors = { old: document.querySelector("#pwOldErr"), next: document.querySelector("#pwNewErr"), confirm: document.querySelector("#pwConfirmErr") };
const pwMessage = document.querySelector("#pwMessage");

function pwFail(key, text) {
  pwErrors[key].textContent = text;
  pwFields[key].setAttribute("aria-invalid", "true");
  pwFields[key].focus();
}

Object.keys(pwFields).forEach((key) => pwFields[key].addEventListener("input", () => {
  pwErrors[key].textContent = "";
  pwFields[key].removeAttribute("aria-invalid");
}));

document.querySelector("#passwordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(pwMessage, "");
  Object.keys(pwErrors).forEach((key) => {
    pwErrors[key].textContent = "";
    pwFields[key].removeAttribute("aria-invalid");
  });
  const oldPassword = pwFields.old.value;
  const newPassword = pwFields.next.value;
  if (!oldPassword) return pwFail("old", "请输入旧密码");
  if (newPassword.length < 4 || newPassword.length > 64) return pwFail("next", "新密码需为 4–64 个字符");
  if (newPassword !== pwFields.confirm.value) return pwFail("confirm", "两次输入的新密码不一致");
  const confirmed = await showAdminConfirm("修改管理密码", "修改后，填报页验收、改删数据等所有需要管理密码的操作都使用新密码。确认修改？", "确认修改", true);
  if (!confirmed) return;
  try {
    await requestJson("/api/admin/password", { method: "POST", keepSession: true, body: JSON.stringify({ oldPassword, newPassword }) });
    document.querySelector("#passwordForm").reset();
    setMessage(pwMessage, "管理密码已修改。", "success");
  } catch (error) {
    pwFail(error.status === 401 ? "old" : "next", error.message);
  }
});

// 首次使用：默认密码登录后先改密码，改完才进后台（服务端同样拒绝其它接口）
const firstPasswordForm = document.querySelector("#firstPasswordForm");
let firstOldPassword = "";
function showFirstPassword(oldPassword) {
  firstOldPassword = oldPassword;
  loginForm.classList.add("hidden");
  firstPasswordForm.classList.remove("hidden");
  document.querySelector("#firstPwNew").focus();
}
firstPasswordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const msg = document.querySelector("#firstPwMessage");
  const newPassword = document.querySelector("#firstPwNew").value;
  setMessage(msg, "");
  if (newPassword.length < 4 || newPassword.length > 64) return setMessage(msg, "新密码需为 4–64 个字符", "error");
  if (newPassword !== document.querySelector("#firstPwConfirm").value) return setMessage(msg, "两次输入的新密码不一致", "error");
  if (newPassword === "112233") return setMessage(msg, "不能继续使用默认密码", "error");
  try {
    await requestJson("/api/admin/password", { method: "POST", keepSession: true, body: JSON.stringify({ oldPassword: firstOldPassword || "112233", newPassword }) });
    firstPasswordForm.reset();
    firstPasswordForm.classList.add("hidden");
    loginForm.classList.remove("hidden");
    state.page = 1;
    await loadData();
  } catch (error) {
    setMessage(msg, error.message, "error");
  }
});

async function boot() {
  try {
    const me = await requestJson("/api/admin/me");
    if (me.mustChangePassword) {
      showLogin();
      showFirstPassword("112233");
      return;
    }
    await loadData();
  } catch {
    showLogin();
  }
}

boot();
