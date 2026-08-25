const state = {
  tasks: [],
  summary: null,
  currentTaskId: null,
  currentTask: null,
  scene: null,
  rules: [],
  modelStatus: null,
  acceptance: null,
  photoAcceptance: null,
  selectedImageId: null,
  selectedResultId: null,
  mediaMode: "original",
  fusionMode: "profile",
  fusionInspectorTab: "issues",
  selectedFusionId: null
};

const titles = {
  "task-center": "任务中心",
  assets: "数据资料",
  fusion: "融合总览",
  pointcloud: "点云处理",
  compare: "模型点云对比",
  vision: "影像验收",
  issues: "问题台账",
  rules: "规则库",
  reports: "报告归档"
};

const checkLabels = {
  foundation_span: "基础根开偏差",
  tower_inclination: "杆塔倾斜度",
  conductor_sag: "导线弧垂",
  crossing_clearance: "交叉跨越净空",
  channel_distance: "通道物距"
};

const parameterLabels = {
  threshold: "允许偏差",
  review_ratio: "复核倍率",
  serious_ratio: "严重倍率",
  default_design: "示例设计值",
  default_measured: "示例实测值",
  box_threshold: "目标框阈值",
  text_threshold: "文本匹配阈值",
  candidate_threshold: "缺陷候选阈值",
  min_clarity: "最低清晰度",
  min_brightness: "最低亮度",
  max_brightness: "最高亮度",
  min_target_detections: "最少构件数",
  min_rust_ratio: "锈蚀占比阈值",
  high_rust_ratio: "严重锈蚀占比",
  min_edge_density: "最低边缘密度",
  max_edge_density: "最高边缘密度",
  candidate_score: "规则候选分数",
  max_conductor_distance_ratio: "最大相对距离",
  required_count: "预期数量",
  min_bolt_score: "螺栓检测阈值"
};

const byId = id => document.getElementById(id);

function icons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
}

async function api(path, options = {}) {
  const init = { ...options };
  if (options.body !== undefined) {
    init.headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : data.error || JSON.stringify(data.detail || data);
    throw new Error(message);
  }
  return data;
}

async function uploadApi(path, formData) {
  const response = await fetch(path, { method: "POST", body: formData });
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : data.error || JSON.stringify(data.detail || data);
    throw new Error(message);
  }
  return data;
}

function showToast(message) {
  const el = byId("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => el.classList.remove("show"), 3200);
}

async function busy(action, label = "正在处理") {
  const overlay = byId("loading");
  overlay.querySelector("span").textContent = label;
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  try {
    return await action();
  } finally {
    overlay.classList.remove("show");
    overlay.setAttribute("aria-hidden", "true");
  }
}

function setView(name) {
  document.querySelectorAll(".view").forEach(view => view.classList.toggle("active", view.id === name));
  document.querySelectorAll(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  byId("page-title").textContent = titles[name];
  byId("page-context").textContent = titles[name];
  if (name === "fusion") {
    requestAnimationFrame(drawScene);
    requestAnimationFrame(syncThreeScene);
  }
  icons();
}

async function refresh({ keepPhotoAcceptance = false } = {}) {
  const [summary, tasks, model, rules] = await Promise.all([
    api("/api/summary"),
    api("/api/tasks"),
    api("/api/ai/model/status"),
    api("/api/rules")
  ]);
  state.summary = summary;
  state.tasks = tasks.items;
  state.modelStatus = model;
  state.rules = rules.items;
  if (!keepPhotoAcceptance) state.photoAcceptance = null;

  if (!state.currentTaskId || !state.tasks.some(item => item.id === state.currentTaskId)) {
    state.currentTaskId = state.tasks[0]?.id || null;
  }
  renderTaskSelect();
  renderModelStatus();
  renderSummary();
  renderTaskTable();
  renderRules();

  if (state.currentTaskId) {
    const [task, scene, acceptance] = await Promise.all([
      api(`/api/tasks/${state.currentTaskId}`),
      api(`/api/tasks/${state.currentTaskId}/fusion-scene`),
      api(`/api/tasks/${state.currentTaskId}/acceptance-summary`)
    ]);
    state.currentTask = task;
    state.scene = scene;
    state.acceptance = acceptance;
    if (!task.images.some(item => item.id === state.selectedImageId)) state.selectedImageId = task.images[0]?.id || null;
    renderCurrentTask();
  } else {
    state.currentTask = null;
    state.scene = null;
    state.acceptance = null;
    clearTaskViews();
  }
  icons();
}

function renderTaskSelect() {
  const select = byId("task-select");
  select.innerHTML = state.tasks.length
    ? state.tasks.map(task => `<option value="${escapeHtml(task.id)}" ${task.id === state.currentTaskId ? "selected" : ""}>${escapeHtml(task.task_no)} / ${escapeHtml(task.project_name)}</option>`).join("")
    : `<option value="">暂无验收任务</option>`;
  select.disabled = !state.tasks.length;
}

function renderSummary() {
  const summary = state.summary || {};
  setText("task-count", summary.task_count || 0);
  setText("measurement-count", summary.measurement_count || 0);
  setText("geometry-count", summary.geometry_count || 0);
  setText("vision-count", summary.vision_count || 0);
  setText("report-count", summary.report_count || 0);
  byId("task-summary-text").textContent = summary.task_count
    ? `共 ${summary.task_count} 个任务，形成 ${summary.geometry_count || 0} 条模型点云校核结果`
    : "尚未创建验收任务，请先新建任务后上传现场照片";
  byId("load-demo").hidden = state.tasks.length > 0;
  setTaskControlsEnabled(Boolean(state.currentTaskId));
}

function renderTaskTable() {
  const rows = state.tasks.map(task => [
    `<strong>${escapeHtml(task.task_no)}</strong><br><span class="muted">${escapeHtml(task.project_name)}</span>`,
    escapeHtml(task.line_name),
    escapeHtml(task.section_name),
    escapeHtml(task.batch_no),
    tag(task.status),
    task.measurement_count,
    task.issue_count,
    `<button class="text-button secondary-button" data-open-task="${escapeHtml(task.id)}">进入任务</button>`
  ]);
  renderTable("task-table", ["任务", "线路", "标段", "批次", "状态", "量测", "问题", "操作"], rows);
}

function renderCurrentTask() {
  const task = state.currentTask;
  byId("task-status").outerHTML = `<span id="task-status" class="tag ${tagColor(task.status)}">${escapeHtml(task.status)}</span>`;
  const pending = task.issues.filter(item => item.review_status === "待复核").length;
  byId("pending-badge").textContent = pending;
  byId("pending-badge").classList.toggle("alert", pending > 0);
  renderAssets(task);
  renderFusion(task);
  renderPointcloud(task);
  renderCompare(task);
  renderVision(task);
  renderIssues(task);
  renderReports(task);
}

function clearTaskViews() {
  byId("task-status").textContent = "未选择任务";
  byId("pending-badge").textContent = "0";
  byId("pending-badge").classList.remove("alert");
  ["model-asset-count", "pointcloud-asset-count", "image-asset-count", "fusion-model-count", "fusion-slice-count", "fusion-check-count", "fusion-issue-count"].forEach(id => setText(id, 0));
  ["model-asset-table", "pointcloud-asset-table", "image-asset-table", "object-table", "measurement-table", "slice-table", "check-table", "heatmap-table", "vision-table", "issue-table", "report-table"].forEach(id => {
    byId(id).innerHTML = `<div class="empty-state"><span>暂无任务数据</span></div>`;
  });
  byId("task-detail").innerHTML = `<div class="empty-state"><span>请先创建验收任务</span></div>`;
  byId("fusion-issue-list").innerHTML = `<div class="fusion-panel-empty">暂无验收问题</div>`;
  byId("fusion-selection-detail").innerHTML = fusionDetailEmpty();
  byId("unlocated-evidence").innerHTML = "";
  byId("scene-warning-bar").hidden = true;
  byId("fusion-scene-empty").hidden = false;
  byId("image-strip").innerHTML = `<div class="empty-state"><span>暂无现场影像</span></div>`;
  const image = byId("vision-image");
  image.classList.remove("visible");
  image.removeAttribute("src");
  byId("image-empty").style.display = "grid";
  byId("media-title").textContent = "尚未上传现场照片";
  byId("media-meta").textContent = "创建任务后即可上传并执行AI验收";
  renderAcceptance(null);
  renderRunDetail(null);
  renderQuality({});
  renderCandidates([]);
}

function setTaskControlsEnabled(enabled) {
  [
    "export-report", "export-report-secondary", "upload-model", "upload-pointcloud",
    "process-pointcloud", "run-registration", "run-compare", "upload-photo", "run-vision",
    "model-file", "pointcloud-file", "photo-file", "shoot-position"
  ].forEach(id => {
    const element = byId(id);
    if (element) element.disabled = !enabled;
  });
}

function renderAssets(task) {
  setText("model-asset-count", task.models.length);
  setText("pointcloud-asset-count", task.pointclouds.length);
  setText("image-asset-count", task.images.length);
  renderTable("model-asset-table", ["类型", "版本", "构件", "解析状态"], task.models.map(item => [
    escapeHtml(item.model_type), escapeHtml(item.model_version), item.component_count, tag(item.parse_status)
  ]));
  renderTable("pointcloud-asset-table", ["文件", "点数", "密度", "质量"], task.pointclouds.map(item => [
    escapeHtml(item.file_name), item.point_count, item.density, tag(item.quality_status)
  ]));
  renderTable("image-asset-table", ["影像", "拍摄位置", "清晰度", "处理状态"], task.images.map(item => [
    escapeHtml(item.file_name), escapeHtml(item.shoot_position), number(item.clarity_score), tag(item.process_status)
  ]));
}

function renderFusion(task) {
  setText("fusion-model-count", task.components.length);
  setText("fusion-slice-count", task.pointcloud_slices.length);
  setText("fusion-check-count", task.geometry_results.length);
  setText("fusion-issue-count", task.issues.length);
  byId("task-detail").innerHTML = [
    detail("任务编号", task.task_no),
    detail("工程名称", task.project_name),
    detail("线路名称", task.line_name),
    detail("验收标段", task.section_name),
    detail("验收批次", task.batch_no),
    detail("负责人", task.owner)
  ].join("");
  const legend = state.scene?.legend || [];
  byId("scene-legend").innerHTML = legend.map(item => `<div class="legend-row"><span class="legend-swatch" style="background:${escapeHtml(item.color)}"></span><span>${escapeHtml(item.label)}</span></div>`).join("");
  const scene = state.scene || {};
  const statistics = scene.statistics || {};
  const coordinate = scene.coordinate_info || {};
  byId("fusion-data-note").textContent = statistics.source_point_count
    ? `${statistics.component_count || 0} 个构件 · ${statistics.source_point_count} 个原始点 · ${statistics.issue_count || 0} 个问题`
    : `${statistics.component_count || 0} 个构件 · 等待点云数据`;
  byId("scene-coordinate").textContent = `坐标系：${coordinate.coordinate_system || "未提供"}`;
  byId("scene-point-summary").textContent = `场景点：${statistics.scene_point_count || 0} / ${statistics.source_point_count || 0}`;
  byId("inspector-issue-count").textContent = statistics.issue_count || 0;
  renderSceneWarnings(scene.warnings || []);
  renderFusionIssueList(task.issues || []);
  renderUnlocatedEvidence(scene.profile?.unlocated_images || []);
  if (!scene.selection_index?.[state.selectedFusionId]) {
    const orderedIssues = [...(task.issues || [])].sort((a, b) => fusionLevelRank(b.level) - fusionLevelRank(a.level));
    state.selectedFusionId = orderedIssues[0]?.id || null;
  }
  renderFusionSelection();
  const hasSceneData = Boolean(statistics.component_count || statistics.source_point_count);
  byId("fusion-scene-empty").hidden = hasSceneData;
  requestAnimationFrame(drawScene);
  requestAnimationFrame(syncThreeScene);
}

function renderPointcloud(task) {
  renderTable("object-table", ["对象", "编号", "点数", "空间包络", "结果"], task.pointcloud_objects.map(item => [
    escapeHtml(item.object_type), escapeHtml(item.object_code), item.point_count, bboxText(item.bbox_json), item.defect_type ? tag(item.defect_type) : tag("正常")
  ]));
  renderTable("measurement-table", ["校核项", "实测值", "单位", "量测方法", "置信度"], task.measurements.map(item => [
    escapeHtml(checkLabels[item.check_item] || item.check_item), number(item.measured_value), escapeHtml(item.unit), escapeHtml(item.method), number(item.confidence)
  ]));
  renderTable("slice-table", ["格网", "点数", "密度", "主类别", "高程范围", "空间范围"], task.pointcloud_slices.map(item => [
    `${item.grid_x}, ${item.grid_y}`, item.point_count, number(item.density), escapeHtml(item.dominant_class), `${number(item.min_z)} - ${number(item.max_z)}`, bboxText(item.bounds_json)
  ]));
}

function renderCompare(task) {
  renderTable("check-table", ["校核项", "设计值", "实测值", "偏差", "阈值", "状态", "等级", "量测依据"], task.geometry_results.map(item => [
    escapeHtml(checkLabels[item.check_item] || item.check_item), number(item.design_value), number(item.measured_value), number(item.deviation), number(item.threshold), tag(item.status), tag(item.level), escapeHtml(item.evidence_json?.measurement_method || "")
  ]));
  renderTable("heatmap-table", ["标记", "偏差倍率", "等级", "平面位置"], task.heatmap_markers.map(item => [
    escapeHtml(item.label), number(item.value), tag(item.level), `${number(item.x)}, ${number(item.y)}`
  ]));
}

function renderVision(task) {
  renderAcceptance(state.photoAcceptance || state.acceptance);
  renderImageStrip(task);
  renderSelectedImage(task);
  renderTable("vision-table", ["影像", "目标", "缺陷候选", "模型分数", "规则分数", "综合置信度", "状态", "证据"], task.vision_results.map(item => {
    const image = task.images.find(value => value.id === item.image_id);
    return [
      escapeHtml(image?.file_name || item.image_id), escapeHtml(item.target_type), escapeHtml(item.defect_type), number(item.model_score), number(item.rule_score), number(item.confidence), tag(item.status), item.snapshot_path ? `<button class="text-button secondary-button" data-result-id="${escapeHtml(item.id)}">查看</button>` : ""
    ];
  }));
}

function renderImageStrip(task) {
  byId("image-strip").innerHTML = task.images.length
    ? task.images.map(image => `<button class="image-thumb ${image.id === state.selectedImageId ? "active" : ""}" data-image-id="${escapeHtml(image.id)}"><img src="${escapeHtml(assetUrl(image.file_path))}" alt=""><span>${escapeHtml(image.file_name)}<br>${escapeHtml(image.process_status)}</span></button>`).join("")
    : `<div class="empty-state"><span>暂无现场影像</span></div>`;
}

function renderSelectedImage(task) {
  const image = task.images.find(item => item.id === state.selectedImageId);
  const imageResults = image ? task.vision_results.filter(item => item.image_id === image.id) : [];
  if (!state.selectedResultId || !imageResults.some(item => item.id === state.selectedResultId)) state.selectedResultId = imageResults[0]?.id || null;
  const result = imageResults.find(item => item.id === state.selectedResultId);
  const run = image ? task.vision_inference_runs.find(item => item.image_id === image.id) : null;
  const img = byId("vision-image");
  const empty = byId("image-empty");
  if (!image) {
    img.classList.remove("visible");
    img.removeAttribute("src");
    empty.style.display = "grid";
    byId("media-title").textContent = "尚未选择影像";
    byId("media-meta").textContent = "";
    renderRunDetail(null);
    renderQuality({});
    renderCandidates([]);
    return;
  }
  const source = state.mediaMode === "evidence" && result?.snapshot_path ? result.snapshot_path : assetUrl(image.file_path);
  img.src = source;
  img.classList.add("visible");
  empty.style.display = "none";
  byId("media-title").textContent = image.file_name;
  byId("media-meta").textContent = `${image.shoot_position || "未填写位置"} · ${image.process_status}`;
  byId("open-media").href = source;
  byId("open-media").classList.remove("disabled");
  byId("show-original").classList.toggle("active", state.mediaMode === "original");
  byId("show-evidence").classList.toggle("active", state.mediaMode === "evidence");
  byId("show-evidence").disabled = !result?.snapshot_path;
  byId("diagnosis-run-status").outerHTML = `<span id="diagnosis-run-status" class="tag ${tagColor(run?.status || "未运行")}">${escapeHtml(run?.status || "未运行")}</span>`;
  renderRunDetail(run);
  renderQuality(image.quality_json || {});
  renderCandidates(imageResults);
}

function renderAcceptance(acceptance) {
  const panel = byId("acceptance-panel");
  if (!acceptance) {
    panel.className = "acceptance-panel neutral";
    panel.innerHTML = `<div class="acceptance-title">未验收</div><div class="acceptance-basis">上传现场照片后生成AI初判。</div>`;
    return;
  }
  const color = acceptance.level === "严重" || acceptance.conclusion.includes("不符合") ? "red" : acceptance.level === "关注" || acceptance.requires_review ? "amber" : "green";
  panel.className = `acceptance-panel ${color}`;
  panel.innerHTML = `<div class="acceptance-title">${escapeHtml(acceptance.conclusion)}</div><div class="acceptance-status">${escapeHtml(acceptance.standard_status)}</div><div class="acceptance-basis">${escapeHtml(acceptance.basis)}</div>`;
}

function renderRunDetail(run) {
  byId("run-detail").innerHTML = run ? [
    detail("模型", run.model_id), detail("版本", run.model_revision || "-"), detail("设备", run.device || "-"), detail("耗时", `${run.duration_ms || 0} ms`), detail("状态", run.status), run.error_message ? detail("说明", run.error_message) : ""
  ].join("") : detail("运行状态", "尚未执行");
}

function renderQuality(features) {
  const items = [
    ["清晰度", features.clarity], ["亮度", features.brightness], ["对比度", features.contrast], ["边缘密度", features.edge_density]
  ];
  byId("quality-detail").innerHTML = items.map(([label, value]) => `<div class="quality-item"><span>${label}</span><strong>${value === undefined ? "-" : number(value)}</strong></div>`).join("");
}

function renderCandidates(results) {
  byId("candidate-list").innerHTML = results.length ? results.map(item => `<div class="candidate-item ${item.id === state.selectedResultId ? "active" : ""}" data-result-id="${escapeHtml(item.id)}"><strong>${escapeHtml(item.defect_type)} ${tag(item.level)}</strong><span>${escapeHtml(item.target_type)} · 置信度 ${number(item.confidence)}</span><span>${escapeHtml(item.diagnosis_json?.feature_reason || "")}</span></div>`).join("") : `<div class="muted">当前影像暂无缺陷候选</div>`;
}

function renderIssues(task) {
  renderTable("issue-table", ["来源", "问题类型", "等级", "复核状态", "整改状态", "问题说明", "操作"], task.issues.map(item => [
    escapeHtml(item.source_type), escapeHtml(item.issue_type), tag(item.level), tag(item.review_status), tag(item.rectify_status), escapeHtml(item.description), item.review_status === "待复核" ? `<button class="text-button" data-review-id="${escapeHtml(item.id)}">人工复核</button>` : escapeHtml(item.reviewer || "-")
  ]));
}

function renderRules() {
  renderTable("rule-table", ["模块", "规则", "对象", "关键阈值", "等级", "状态", "版本", "操作"], state.rules.map(rule => [
    rule.module === "vision" ? "影像验收" : "几何校核", escapeHtml(rule.name), escapeHtml(rule.target_type), escapeHtml(ruleParameterSummary(rule.parameters_json)), tag(rule.severity), tag(rule.enabled ? "启用" : "停用"), `V${rule.version}`, `<button class="text-button secondary-button" data-rule-id="${escapeHtml(rule.id)}">编辑</button>`
  ]));
}

function renderReports(task) {
  renderTable("report-table", ["格式", "归档文件", "导出时间", "操作人"], task.reports.map(item => {
    const name = String(item.file_path).split(/[\\/]/).pop();
    const href = reportHref(item.file_path);
    return [escapeHtml(item.format.toUpperCase()), href ? `<a href="${escapeHtml(href)}" target="_blank">${escapeHtml(name)}</a>` : escapeHtml(name), escapeHtml(item.export_time), escapeHtml(item.operator)];
  }));
}

function renderModelStatus() {
  const status = state.modelStatus;
  const className = status?.runtime_ready ? "ready" : "warning";
  const title = status?.runtime_ready ? (status.loaded ? "AI模型已加载" : "AI模型已就绪") : "AI模型未就绪";
  const subtitle = status?.runtime_ready ? `${status.display_name} · ${status.device}` : (status?.message || "检查失败");
  [byId("sidebar-model"), byId("model-status-panel")].forEach(panel => {
    panel.className = panel.id === "sidebar-model" ? `sidebar-status ${className}` : `model-status ${className}`;
    panel.innerHTML = `<span class="status-dot"></span><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(subtitle)}</small></div>`;
  });
}

function openRuleDialog(ruleId) {
  const rule = state.rules.find(item => item.id === ruleId);
  if (!rule) return;
  byId("rule-id").value = rule.id;
  byId("rule-dialog-title").textContent = `编辑：${rule.name}`;
  const fields = [];
  Object.entries(rule.parameters_json || {}).forEach(([key, value]) => {
    if (typeof value !== "number" && typeof value !== "string") return;
    fields.push(`<label><span>${escapeHtml(parameterLabels[key] || key)}</span><input data-parameter="${escapeHtml(key)}" type="${typeof value === "number" ? "number" : "text"}" step="any" value="${escapeHtml(value)}"></label>`);
  });
  fields.push(`<label><span>问题等级</span><select id="rule-severity">${["一般", "关注", "严重"].map(value => `<option ${value === rule.severity ? "selected" : ""}>${value}</option>`).join("")}</select></label>`);
  fields.push(`<label><span>启用状态</span><select id="rule-enabled"><option value="true" ${rule.enabled ? "selected" : ""}>启用</option><option value="false" ${!rule.enabled ? "selected" : ""}>停用</option></select></label>`);
  fields.push(`<label class="span-two"><span>验收依据</span><textarea id="rule-basis" rows="3">${escapeHtml(rule.standard_basis)}</textarea></label>`);
  byId("rule-fields").innerHTML = fields.join("");
  byId("rule-dialog").showModal();
}

function openReviewDialog(issueId) {
  const issue = state.currentTask?.issues.find(item => item.id === issueId);
  if (!issue) return;
  byId("review-issue-id").value = issue.id;
  byId("review-opinion").value = `${issue.issue_type}证据已核对，请记录现场复核结论。`;
  byId("review-dialog").showModal();
}

async function withTask(action, label) {
  if (!state.currentTaskId) throw new Error("请先创建或选择验收任务");
  return busy(async () => {
    const result = await action(state.currentTaskId);
    await refresh({ keepPhotoAcceptance: true });
    return result;
  }, label);
}

async function exportReport() {
  await withTask(async id => {
    const report = await api(`/api/tasks/${id}/report/export`, { method: "POST", body: { format: "docx" } });
    showToast(`报告已生成：${String(report.file_path).split(/[\\/]/).pop()}`);
  }, "正在生成验收报告");
}

function bindEvents() {
  document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
  document.querySelectorAll("[data-layer]").forEach(item => item.addEventListener("change", updateFusionLayers));
  document.querySelectorAll("[data-scene-mode]").forEach(button => button.addEventListener("click", () => setFusionMode(button.dataset.sceneMode)));
  document.querySelectorAll("[data-inspector-tab]").forEach(button => button.addEventListener("click", () => setFusionInspectorTab(button.dataset.inspectorTab)));
  document.querySelectorAll("[data-scene-camera]").forEach(button => button.addEventListener("click", () => controlFusionCamera(button.dataset.sceneCamera)));
  window.addEventListener("resize", () => {
    requestAnimationFrame(drawScene);
    window.LineFusion3D?.resize();
  });
  window.addEventListener("fusion3dready", syncThreeScene);

  byId("task-select").addEventListener("change", async event => {
    state.currentTaskId = event.target.value || null;
    state.selectedImageId = null;
    await busy(refresh, "正在切换任务");
  });
  byId("new-task").addEventListener("click", () => byId("task-dialog").showModal());
  byId("task-create-primary").addEventListener("click", () => byId("task-dialog").showModal());
  document.querySelectorAll(".close-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));

  byId("task-form").addEventListener("submit", async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    await busy(async () => {
      const task = await api("/api/tasks", { method: "POST", body: payload });
      state.currentTaskId = task.id;
      state.selectedImageId = null;
      byId("task-dialog").close();
      await refresh();
      setView("vision");
      showToast("验收任务已创建，请上传现场照片");
    }, "正在创建任务");
  });

  byId("upload-model").addEventListener("click", () => withTask(async id => {
    const file = byId("model-file").files[0];
    if (!file) throw new Error("请选择 JSON 设计模型文件");
    const form = new FormData();
    form.append("file", file);
    form.append("model_version", byId("model-version").value || "V1.0");
    form.append("operator", "资料管理员");
    await uploadApi(`/api/tasks/${id}/model/upload`, form);
    showToast("设计模型已导入并解析");
  }, "正在解析设计模型").catch(error => showToast(error.message)));

  byId("upload-pointcloud").addEventListener("click", () => withTask(async id => {
    const file = byId("pointcloud-file").files[0];
    if (!file) throw new Error("请选择 CSV 点云文件");
    const form = new FormData();
    form.append("file", file);
    form.append("coordinate_system", byId("coordinate-system").value || "CGCS2000");
    form.append("operator", "资料管理员");
    await uploadApi(`/api/tasks/${id}/pointcloud/upload`, form);
    showToast("点云资料已导入");
  }, "正在导入点云").catch(error => showToast(error.message)));

  byId("process-pointcloud").addEventListener("click", () => withTask(async id => {
    await api(`/api/tasks/${id}/pointcloud/process`, { method: "POST", body: { grid_size: 40 } });
    showToast("点云分片、分类和量测已完成");
  }, "正在处理点云").catch(error => showToast(error.message)));

  byId("run-registration").addEventListener("click", () => withTask(async id => {
    await api(`/api/tasks/${id}/registration/run`, { method: "POST", body: { control_point_count: 5 } });
    showToast("模型与点云配准已完成");
  }, "正在执行坐标配准").catch(error => showToast(error.message)));

  byId("run-compare").addEventListener("click", () => withTask(async id => {
    await api(`/api/tasks/${id}/compare/run`, { method: "POST", body: {} });
    showToast("模型点云偏差校核已完成");
  }, "正在执行模型点云校核").catch(error => showToast(error.message)));

  byId("upload-photo").addEventListener("click", () => withTask(async id => {
    const files = [...byId("photo-file").files];
    if (!files.length) throw new Error("请选择现场照片");
    let lastResult = null;
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("shoot_position", byId("shoot-position").value || "现场照片");
      form.append("source_type", "照片");
      form.append("operator", "验收工程师");
      lastResult = await uploadApi(`/api/tasks/${id}/images/upload`, form);
      state.selectedImageId = lastResult.image.id;
    }
    state.photoAcceptance = lastResult?.acceptance || null;
    showToast(`已完成 ${files.length} 张照片的AI验收`);
    setView("vision");
  }, "正在执行本地AI影像验收").catch(error => showToast(error.message)));

  byId("run-vision").addEventListener("click", () => withTask(async id => {
    await api(`/api/tasks/${id}/vision/run`, { method: "POST", body: {} });
    state.photoAcceptance = null;
    showToast("任务影像已重新诊断");
  }, "正在重新诊断全部影像").catch(error => showToast(error.message)));

  byId("export-report").addEventListener("click", () => exportReport().catch(error => showToast(error.message)));
  byId("export-report-secondary").addEventListener("click", () => exportReport().catch(error => showToast(error.message)));
  byId("load-demo").addEventListener("click", async () => {
    await busy(async () => {
      const task = await api("/api/demo/load", { method: "POST" });
      state.currentTaskId = task.id;
      state.selectedImageId = null;
      await refresh();
      showToast("示例数据已加载");
    }, "正在加载示例数据");
  });
  byId("show-original").addEventListener("click", () => { state.mediaMode = "original"; renderSelectedImage(state.currentTask); });
  byId("show-evidence").addEventListener("click", () => { state.mediaMode = "evidence"; renderSelectedImage(state.currentTask); });

  byId("rule-form").addEventListener("submit", async event => {
    event.preventDefault();
    const ruleId = byId("rule-id").value;
    const rule = state.rules.find(item => item.id === ruleId);
    const parameters = {};
    byId("rule-fields").querySelectorAll("[data-parameter]").forEach(input => {
      const original = rule.parameters_json[input.dataset.parameter];
      parameters[input.dataset.parameter] = typeof original === "number" ? Number(input.value) : input.value;
    });
    await busy(async () => {
      await api(`/api/rules/${encodeURIComponent(ruleId)}`, { method: "PUT", body: { parameters, severity: byId("rule-severity").value, enabled: byId("rule-enabled").value === "true", standard_basis: byId("rule-basis").value } });
      byId("rule-dialog").close();
      await refresh({ keepPhotoAcceptance: true });
      showToast("验收规则已更新");
    }, "正在保存验收规则");
  });

  byId("reset-rules").addEventListener("click", async () => {
    await busy(async () => {
      await api("/api/rules/reset", { method: "POST", body: {} });
      await refresh({ keepPhotoAcceptance: true });
      showToast("已恢复项目示例规则");
    }, "正在恢复规则");
  });

  byId("review-form").addEventListener("submit", async event => {
    event.preventDefault();
    await busy(async () => {
      await api(`/api/issues/${byId("review-issue-id").value}/review`, { method: "POST", body: { action: byId("review-action").value, reviewer: byId("reviewer").value, opinion: byId("review-opinion").value } });
      byId("review-dialog").close();
      state.photoAcceptance = null;
      await refresh();
      showToast("人工复核结论已记录");
    }, "正在提交复核结论");
  });

  document.addEventListener("click", event => {
    const taskButton = event.target.closest("[data-open-task]");
    if (taskButton) {
      state.currentTaskId = taskButton.dataset.openTask;
      state.selectedImageId = null;
      busy(refresh, "正在打开任务").then(() => setView("fusion")).catch(error => showToast(error.message));
    }
    const imageButton = event.target.closest("[data-image-id]");
    if (imageButton) {
      state.selectedImageId = imageButton.dataset.imageId;
      state.selectedResultId = null;
      state.mediaMode = "original";
      renderVision(state.currentTask);
    }
    const resultButton = event.target.closest("[data-result-id]");
    if (resultButton) {
      const result = state.currentTask?.vision_results.find(item => item.id === resultButton.dataset.resultId);
      if (result) {
        state.selectedImageId = result.image_id;
        state.selectedResultId = result.id;
        state.mediaMode = "evidence";
        renderVision(state.currentTask);
        setView("vision");
      }
    }
    const ruleButton = event.target.closest("[data-rule-id]");
    if (ruleButton) openRuleDialog(ruleButton.dataset.ruleId);
    const reviewButton = event.target.closest("[data-review-id]");
    if (reviewButton) openReviewDialog(reviewButton.dataset.reviewId);
    const fusionButton = event.target.closest("[data-fusion-id]");
    if (fusionButton) selectFusionItem(fusionButton.dataset.fusionId, true);
  });
}

function renderTable(target, headers, rows) {
  const head = headers.map(item => `<th>${escapeHtml(item)}</th>`).join("");
  const body = rows.length ? rows.map(row => `<tr>${row.map(cell => `<td>${cell ?? ""}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}"><span class="muted">暂无数据</span></td></tr>`;
  byId(target).innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function tag(text) {
  return `<span class="tag ${tagColor(text)}">${escapeHtml(text)}</span>`;
}

function tagColor(text) {
  const value = String(text || "");
  if (["严重", "失败", "不符合", "超限", "缺失", "破损"].some(word => value.includes(word))) return "red";
  if (["复核", "整改", "关注", "不足", "未就绪", "异常", "待"].some(word => value.includes(word))) return "amber";
  if (["成功", "通过", "正常", "符合", "完成", "已确认", "启用", "就绪"].some(word => value.includes(word))) return "green";
  if (["运行", "导入", "校核"].some(word => value.includes(word))) return "blue";
  return "neutral";
}

function detail(label, value) {
  return `<div class="detail-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "-")}</strong></div>`;
}

function ruleParameterSummary(parameters) {
  const parts = Object.entries(parameters || {}).filter(([, value]) => typeof value === "number").slice(0, 3).map(([key, value]) => `${parameterLabels[key] || key}=${value}`);
  if (Array.isArray(parameters?.prompts)) parts.push(`目标类别=${parameters.prompts.length}`);
  return parts.join("；") || "配置项";
}

function bboxText(value) {
  return Array.isArray(value) ? value.map(item => number(item)).join(", ") : "";
}

function number(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value ?? "-");
  return Math.abs(parsed) >= 100 ? parsed.toFixed(1) : parsed.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function setText(id, value) {
  byId(id).textContent = value;
}

function assetUrl(filePath) {
  const normalized = String(filePath || "").replaceAll("\\", "/");
  if (normalized.startsWith("storage/projects/")) return "/uploads/" + normalized.slice("storage/projects/".length);
  if (normalized.startsWith("sample_data/")) return "/sample_data/" + normalized.slice("sample_data/".length);
  return normalized.startsWith("/") ? normalized : "/" + normalized;
}

function reportHref(filePath) {
  const normalized = String(filePath || "").replaceAll("\\", "/");
  const marker = "storage/reports/";
  const index = normalized.indexOf(marker);
  return index >= 0 ? "/reports/" + normalized.slice(index + marker.length) : "";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function renderSceneWarnings(warnings) {
  const bar = byId("scene-warning-bar");
  if (!warnings.length) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  bar.hidden = false;
  bar.innerHTML = warnings.slice(0, 3).map(item => `<span class="${escapeHtml(item.level)}"><i data-lucide="${item.level === "error" ? "circle-alert" : "info"}"></i>${escapeHtml(item.message)}</span>`).join("");
  icons();
}

function renderFusionIssueList(issues) {
  const ordered = [...issues].sort((a, b) => fusionLevelRank(b.level) - fusionLevelRank(a.level));
  byId("fusion-issue-list").innerHTML = ordered.length ? ordered.map(item => `
    <button class="fusion-issue-row ${item.id === state.selectedFusionId ? "active" : ""}" data-fusion-id="${escapeHtml(item.id)}">
      <span class="risk-bar ${fusionLevelClass(item.level)}"></span>
      <span class="issue-row-main"><strong>${escapeHtml(item.issue_type)}</strong><small>${escapeHtml(item.description)}</small></span>
      <span class="issue-row-meta"><b>${escapeHtml(item.level)}</b><small>${escapeHtml(item.review_status)}</small></span>
    </button>`).join("") : `<div class="fusion-panel-empty"><i data-lucide="badge-check"></i><strong>暂无验收问题</strong><span>执行模型对比或影像诊断后在此汇总。</span></div>`;
}

function renderUnlocatedEvidence(images) {
  const panel = byId("unlocated-evidence");
  panel.innerHTML = images.length ? `
    <div class="inspector-section-title second"><span>待定位证据</span><small>${images.length} 张</small></div>
    ${images.map(image => `<button class="evidence-row" data-fusion-id="${escapeHtml(image.id)}"><i data-lucide="map-pin-off"></i><span><strong>${escapeHtml(image.label)}</strong><small>${escapeHtml(image.file_name)}</small></span></button>`).join("")}` : "";
  icons();
}

function renderFusionSelection() {
  const selected = state.scene?.selection_index?.[state.selectedFusionId];
  const panel = byId("fusion-selection-detail");
  if (!selected) {
    panel.innerHTML = fusionDetailEmpty();
    byId("scene-selection-summary").textContent = "未选择验收对象";
    return;
  }
  const evidence = selected.evidence || [];
  panel.innerHTML = `
    <div class="selection-head">
      <span class="selection-kind">${fusionKindLabel(selected.kind)}</span>
      <span class="selection-level ${fusionLevelClass(selected.level)}">${escapeHtml(selected.level || selected.status || "资料")}</span>
      <h3>${escapeHtml(selected.title)}</h3>
      <p>${escapeHtml(selected.subtitle || "")}</p>
    </div>
    <div class="selection-data">${(selected.details || []).map(item => `<div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></div>`).join("")}</div>
    ${evidence.length ? `<div class="selection-evidence"><h4>关联证据</h4>${evidence.map(item => `<button data-image-id="${escapeHtml(item.image_id)}"><img src="${escapeHtml(sceneEvidenceUrl(item.url))}" alt=""><span>${escapeHtml(item.title)}</span></button>`).join("")}</div>` : ""}`;
  byId("scene-selection-summary").textContent = `${selected.title} · ${selected.status || selected.level || "已选中"}`;
}

function fusionDetailEmpty() {
  return `<div class="fusion-panel-empty detail-empty"><i data-lucide="mouse-pointer-2"></i><strong>未选择对象</strong><span>从问题列表或场景中选择验收对象。</span></div>`;
}

function sceneEvidenceUrl(url) {
  const value = String(url || "");
  return value.startsWith("/evidence/") ? value : assetUrl(value);
}

function fusionKindLabel(kind) {
  return { component: "设计构件", check: "几何校核", issue: "验收问题", image: "影像证据" }[kind] || "融合对象";
}

function fusionLevelRank(level) {
  return level === "严重" ? 4 : level === "关注" ? 3 : level === "一般" ? 2 : level === "待定位" ? 1 : 0;
}

function fusionLevelClass(level) {
  return level === "严重" ? "serious" : level === "关注" ? "attention" : level === "待定位" ? "unlocated" : "qualified";
}

function setFusionMode(mode) {
  state.fusionMode = mode === "three" ? "three" : "profile";
  document.querySelectorAll("[data-scene-mode]").forEach(button => {
    const active = button.dataset.sceneMode === state.fusionMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  byId("profile-scene").classList.toggle("active", state.fusionMode === "profile");
  byId("three-scene").classList.toggle("active", state.fusionMode === "three");
  document.querySelector(".fusion-console")?.classList.toggle("three-mode", state.fusionMode === "three");
  if (state.fusionMode === "profile") requestAnimationFrame(drawScene);
  else requestAnimationFrame(syncThreeScene);
}

function setFusionInspectorTab(tab) {
  state.fusionInspectorTab = tab;
  document.querySelectorAll("[data-inspector-tab]").forEach(button => {
    const active = button.dataset.inspectorTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-inspector-panel]").forEach(panel => panel.classList.toggle("active", panel.dataset.inspectorPanel === tab));
}

function selectFusionItem(id, revealDetail = false) {
  if (!id || !state.scene?.selection_index?.[id]) return;
  state.selectedFusionId = id;
  renderFusionIssueList(state.currentTask?.issues || []);
  renderFusionSelection();
  if (revealDetail) setFusionInspectorTab("detail");
  requestAnimationFrame(drawScene);
  window.LineFusion3D?.select(id, true);
}

window.selectFusionItem = selectFusionItem;

function fusionLayerState() {
  return Object.fromEntries([...document.querySelectorAll("[data-layer]")].map(item => [item.dataset.layer, item.checked]));
}

function updateFusionLayers() {
  requestAnimationFrame(drawScene);
  window.LineFusion3D?.setLayers(fusionLayerState());
}

function syncThreeScene() {
  if (!state.scene || !window.LineFusion3D) return;
  window.LineFusion3D.setData(state.scene, fusionLayerState());
  if (state.selectedFusionId) window.LineFusion3D.select(state.selectedFusionId, false);
  if (state.fusionMode === "three") window.LineFusion3D.resize();
}

function controlFusionCamera(view) {
  if (state.fusionMode === "profile") {
    requestAnimationFrame(drawScene);
    return;
  }
  window.LineFusion3D?.setView(view);
}

function drawScene() {
  const canvas = byId("fusion-pointcloud-canvas");
  const svg = byId("fusion-profile-svg");
  const profile = state.scene?.profile;
  if (!canvas || !svg || !profile || !canvas.closest(".view.active") || state.fusionMode !== "profile") return;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.round(rect.width || 900));
  const height = Math.max(480, Math.round(rect.height || 620));
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#07111f";
  ctx.fillRect(0, 0, width, height);
  const mapper = createProfileMapper(profile.bounds, width, height);
  drawProfileGrid(ctx, mapper, profile.bounds, width, height);
  if (layerEnabled("pointcloud")) drawProfilePointcloud(ctx, mapper, profile.pointcloud || []);
  svg.innerHTML = buildProfileSvg(profile, mapper, width, height);
}

function createProfileMapper(bounds, width, height) {
  const [minX, minZ, maxX, maxZ] = bounds;
  const margin = { left: width < 600 ? 48 : 66, right: 24, top: width < 600 ? 112 : 124, bottom: 52 };
  const drawingWidth = Math.max(width - margin.left - margin.right, 1);
  const drawingHeight = Math.max(height - margin.top - margin.bottom, 1);
  return {
    margin,
    width,
    height,
    x(value) { return margin.left + (Number(value) - minX) / Math.max(maxX - minX, 1) * drawingWidth; },
    y(value) { return margin.top + (maxZ - Number(value)) / Math.max(maxZ - minZ, 1) * drawingHeight; },
    rect(bbox) {
      const x1 = this.x(bbox[0]);
      const x2 = this.x(bbox[3]);
      const y1 = this.y(bbox[2]);
      const y2 = this.y(bbox[5]);
      return [Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)];
    }
  };
}

function drawProfileGrid(ctx, mapper, bounds, width, height) {
  const [minX, minZ, maxX, maxZ] = bounds;
  const xTicks = niceTicks(minX, maxX, width < 600 ? 4 : 8);
  const zTicks = niceTicks(minZ, maxZ, 6);
  ctx.font = "11px Microsoft YaHei, Arial";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  xTicks.forEach(value => {
    const x = mapper.x(value);
    ctx.strokeStyle = "rgba(123, 161, 188, 0.14)";
    ctx.beginPath(); ctx.moveTo(x, mapper.margin.top); ctx.lineTo(x, height - mapper.margin.bottom); ctx.stroke();
    ctx.fillStyle = "#7f96aa";
    ctx.fillText(`K${Math.max(0, value / 1000).toFixed(2)}`, x, height - mapper.margin.bottom + 12);
  });
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  zTicks.forEach(value => {
    const y = mapper.y(value);
    ctx.strokeStyle = "rgba(123, 161, 188, 0.14)";
    ctx.beginPath(); ctx.moveTo(mapper.margin.left, y); ctx.lineTo(width - mapper.margin.right, y); ctx.stroke();
    ctx.fillStyle = "#7f96aa";
    ctx.fillText(`${number(value)} m`, mapper.margin.left - 10, y);
  });
  ctx.strokeStyle = "rgba(151, 186, 209, 0.42)";
  ctx.strokeRect(mapper.margin.left, mapper.margin.top, width - mapper.margin.left - mapper.margin.right, height - mapper.margin.top - mapper.margin.bottom);
  ctx.textAlign = "left";
  ctx.fillStyle = "#8ca3b5";
  ctx.fillText("高程", 12, mapper.margin.top - 18);
  ctx.textAlign = "right";
  ctx.fillText("线路里程", width - mapper.margin.right, height - 16);
}

function niceTicks(min, max, count) {
  const span = Math.max(max - min, 1);
  const rough = span / Math.max(count, 1);
  const power = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / power;
  const step = (normalized < 2 ? 2 : normalized < 5 ? 5 : 10) * power;
  const start = Math.ceil(min / step) * step;
  const values = [];
  for (let value = start; value <= max + step * 0.1; value += step) values.push(Number(value.toFixed(6)));
  return values;
}

const profileClassColors = {
  ground: "rgba(112, 151, 137, 0.48)",
  foundation: "rgba(155, 174, 190, 0.78)",
  tower: "rgba(99, 199, 255, 0.66)",
  conductor: "rgba(141, 227, 207, 0.88)",
  crossing: "rgba(189, 151, 104, 0.74)",
  vegetation: "rgba(87, 179, 122, 0.72)",
  unknown: "rgba(159, 174, 188, 0.52)"
};

function drawProfilePointcloud(ctx, mapper, points) {
  points.forEach(point => {
    const [x, z, cls, intensity] = point;
    ctx.fillStyle = profileClassColors[cls] || profileClassColors.unknown;
    const size = cls === "conductor" || cls === "tower" ? 2.4 : 1.8;
    ctx.globalAlpha = Math.max(0.42, Math.min(1, Number(intensity || 0.65)));
    ctx.fillRect(mapper.x(x) - size / 2, mapper.y(z) - size / 2, size, size);
  });
  ctx.globalAlpha = 1;
}

function buildProfileSvg(profile, mapper, width, height) {
  const parts = [`<defs>
    <marker id="dimension-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#b9ccda"/></marker>
    <filter id="selected-glow" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="0" stdDeviation="4" flood-color="#63c7ff" flood-opacity="0.7"/></filter>
  </defs>`];
  if ((profile.terrain || []).length) parts.push(terrainSvg(profile.terrain, mapper, height));
  if (layerEnabled("objects")) (profile.objects || []).forEach(item => parts.push(profileObjectSvg(item, mapper)));
  if (layerEnabled("model")) {
    (profile.towers || []).forEach(item => parts.push(towerSvg(item, mapper)));
    (profile.conductors || []).forEach(item => parts.push(designConductorSvg(item, mapper)));
  }
  if (layerEnabled("measured") && (profile.measured_conductor || []).length) parts.push(measuredConductorSvg(profile.measured_conductor, mapper));
  if (layerEnabled("issues")) {
    const visibleDimensions = prioritizedDimensions(profile.dimensions || [], width);
    parts.push(dimensionAnnotationsSvg(visibleDimensions, mapper, width));
    (profile.issues || []).forEach(item => parts.push(issueMarkerSvg(item, mapper)));
  }
  if (layerEnabled("images")) {
    (state.scene?.layers?.images || []).forEach(item => parts.push(imageMarkerSvg(item, mapper)));
  }
  parts.push(`<text x="${mapper.margin.left + 8}" y="${height - mapper.margin.bottom - 12}" class="profile-caption">实测点云剖面</text>`);
  return parts.join("");
}

function terrainSvg(points, mapper, height) {
  const line = points.map((item, index) => `${index ? "L" : "M"}${mapper.x(item.x).toFixed(1)},${mapper.y(item.z).toFixed(1)}`).join(" ");
  const firstX = mapper.x(points[0].x).toFixed(1);
  const lastX = mapper.x(points[points.length - 1].x).toFixed(1);
  const bottom = (height - mapper.margin.bottom).toFixed(1);
  return `<path d="${line} L${lastX},${bottom} L${firstX},${bottom} Z" class="terrain-fill"/><path d="${line}" class="terrain-line"/>`;
}

function profileObjectSvg(item, mapper) {
  const [x, y, w, h] = mapper.rect(item.bbox);
  const className = item.class === "vegetation" ? "vegetation-object" : item.class === "crossing" ? "crossing-object" : "semantic-object";
  const label = escapeHtml(`${item.label} · ${item.point_count} 点`);
  return `<g class="profile-selectable" data-fusion-id="${escapeHtml(item.id)}"><title>${label}</title><rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(w, 5).toFixed(1)}" height="${Math.max(h, 5).toFixed(1)}" class="${className}"/><text x="${(x + 6).toFixed(1)}" y="${Math.max(y - 7, 142).toFixed(1)}" class="object-label">${escapeHtml(item.label)}</text></g>`;
}

function towerSvg(item, mapper) {
  const baseX = mapper.x(item.x);
  const baseY = mapper.y(item.base_z);
  const topY = mapper.y(item.base_z + item.height);
  const towerWidth = Math.max(18, Math.min(34, Math.abs(baseY - topY) * 0.32));
  const left = baseX - towerWidth / 2;
  const right = baseX + towerWidth / 2;
  const midY = topY + (baseY - topY) * 0.48;
  const inferred = item.inferred ? " inferred" : "";
  const selected = item.id === state.selectedFusionId ? " selected" : "";
  return `<g class="tower-assembly profile-selectable${inferred}${selected}" data-fusion-id="${escapeHtml(item.id)}">
    <title>${escapeHtml(item.label)} · 高度 ${number(item.height)} m</title>
    <path d="M${left},${baseY} L${baseX - towerWidth * 0.18},${topY} L${baseX + towerWidth * 0.18},${topY} L${right},${baseY} M${left},${baseY} L${right},${baseY} M${left + 2},${midY} L${right - 2},${midY} M${left + 3},${baseY} L${right - 3},${midY} M${right - 3},${baseY} L${left + 3},${midY}"/>
    <path d="M${baseX - towerWidth * 0.72},${topY + 8} L${baseX + towerWidth * 0.72},${topY + 8} M${baseX - towerWidth * 0.55},${topY + 17} L${baseX + towerWidth * 0.55},${topY + 17}" class="tower-crossarm"/>
    <rect x="${left - 4}" y="${baseY}" width="${towerWidth + 8}" height="5" class="tower-foundation"/>
    <text x="${baseX}" y="${Math.max(topY - 10, 138)}" class="tower-label">${escapeHtml(item.label)}</text>
  </g>`;
}

function designConductorSvg(item, mapper) {
  const selected = item.id === state.selectedFusionId ? " selected" : "";
  return item.curves.map((curve, index) => {
    if (index > 0) return "";
    const d = curve.points.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${mapper.x(point[0]).toFixed(1)},${mapper.y(point[2]).toFixed(1)}`).join(" ");
    return `<path d="${d}" class="design-conductor profile-selectable${selected}" data-fusion-id="${escapeHtml(item.id)}"><title>${escapeHtml(item.label)} · 设计弧垂 ${number(item.design_sag)} ${escapeHtml(item.unit)}</title></path>`;
  }).join("");
}

function measuredConductorSvg(points, mapper) {
  const d = points.map((item, index) => `${index ? "L" : "M"}${mapper.x(item.x).toFixed(1)},${mapper.y(item.z).toFixed(1)}`).join(" ");
  return `<path d="${d}" class="measured-conductor"><title>点云拟合实测导线</title></path>`;
}

function prioritizedDimensions(dimensions, width) {
  const selected = state.scene?.selection_index?.[state.selectedFusionId];
  const sourceId = selected?.kind === "issue" ? state.currentTask?.issues.find(item => item.id === selected.id)?.source_id : selected?.id;
  return [...dimensions]
    .sort((a, b) => (b.id === sourceId) - (a.id === sourceId) || fusionLevelRank(b.level) - fusionLevelRank(a.level))
    .slice(0, width < 620 ? 2 : width < 920 ? 3 : 4);
}

function dimensionAnnotationsSvg(items, mapper, width) {
  if (!items.length) return "";
  const available = width - mapper.margin.left - mapper.margin.right;
  const gap = 8;
  const cardWidth = Math.min(166, Math.max(126, (available - gap * (items.length - 1)) / items.length));
  return items.map((item, index) => {
    const cardX = mapper.margin.left + index * (available / items.length) + (available / items.length - cardWidth) / 2;
    const cardY = 18 + (index % 2) * 48;
    const anchorX = mapper.x(item.x);
    const anchorY = mapper.y(item.z);
    const colorClass = fusionLevelClass(item.level);
    const selected = state.scene?.selection_index?.[state.selectedFusionId];
    const sourceId = selected?.kind === "issue" ? state.currentTask?.issues.find(issue => issue.id === selected.id)?.source_id : selected?.id;
    const selectedClass = item.id === sourceId ? " selected" : "";
    const measured = item.measured_value === null || item.measured_value === undefined ? "待校核" : `${number(item.measured_value)} ${escapeHtml(item.unit || "")}`;
    return `<g class="dimension-annotation ${colorClass}${selectedClass} profile-selectable" data-fusion-id="${escapeHtml(item.id)}">
      <path d="M${(cardX + cardWidth / 2).toFixed(1)},${(cardY + 38).toFixed(1)} L${anchorX.toFixed(1)},${anchorY.toFixed(1)}" class="annotation-leader"/>
      <circle cx="${anchorX.toFixed(1)}" cy="${anchorY.toFixed(1)}" r="5" class="annotation-anchor"/>
      <rect x="${cardX.toFixed(1)}" y="${cardY}" width="${cardWidth.toFixed(1)}" height="38" rx="3"/>
      <text x="${(cardX + 10).toFixed(1)}" y="${cardY + 15}" class="annotation-title">${escapeHtml(item.label)}</text>
      <text x="${(cardX + 10).toFixed(1)}" y="${cardY + 30}" class="annotation-value">实测 ${measured} · ${escapeHtml(item.status)}</text>
    </g>`;
  }).join("");
}

function issueMarkerSvg(item, mapper) {
  const x = mapper.x(item.x);
  const y = mapper.y(item.z);
  const selected = item.id === state.selectedFusionId ? " selected" : "";
  return `<g class="issue-marker ${fusionLevelClass(item.level)}${selected} profile-selectable" data-fusion-id="${escapeHtml(item.id)}"><title>${escapeHtml(item.label)} · ${escapeHtml(item.review_status)}</title><path d="M${x},${y - 11} L${x + 10},${y + 8} L${x - 10},${y + 8} Z"/><text x="${x}" y="${y + 5}">!</text></g>`;
}

function imageMarkerSvg(item, mapper) {
  const selected = item.id === state.selectedFusionId ? " selected" : "";
  const x = mapper.x(item.x);
  const y = mapper.y(item.z);
  return `<g class="image-marker${selected} profile-selectable" data-fusion-id="${escapeHtml(item.id)}"><title>${escapeHtml(item.file_name)} · ${escapeHtml(item.shoot_position)}</title><circle cx="${x}" cy="${y}" r="8"/><path d="M${x - 4},${y - 2} h8 v5 h-8 z M${x - 2},${y - 4} h4 l1 2 h-6 z"/><text x="${x + 13}" y="${y + 4}">${escapeHtml(item.label)}</text></g>`;
}

function layerEnabled(name) {
  const checkbox = document.querySelector(`[data-layer="${name}"]`);
  return !checkbox || checkbox.checked;
}

icons();
bindEvents();
busy(refresh, "正在加载验收工作台").catch(error => showToast(error.message));
