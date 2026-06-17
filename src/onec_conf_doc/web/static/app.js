/* global state */
let logsPaused = false;
let logsSinceId = 0;
let logsTimer = null;
let selectedJobId = null;
let activeJobPoll = null;
let configurations = [];

const API = "";

async function api(path, options = {}) {
  const res = await fetch(API + path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function $(sel) {
  return document.querySelector(sel);
}

function showPanel(name) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  $(`#panel-${name}`).classList.add("active");
  const tab = $(`.tab[data-tab="${name}"]`);
  if (tab) tab.classList.add("active");
  if (name === "logs") {
    refreshJobs();
    startLogsPolling();
  } else {
    stopLogsPolling();
  }
}

function objectJsonUrl(objectType, name, configuration) {
  const q = configuration ? `?configuration=${encodeURIComponent(configuration)}` : "";
  return `/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(name)}${q}`;
}

function objectPageUrl(objectType, name, configuration) {
  const q = configuration ? `?configuration=${encodeURIComponent(configuration)}` : "";
  return `/object/${encodeURIComponent(objectType)}/${encodeURIComponent(name)}${q}`;
}

function parseObjectRoute() {
  const match = window.location.pathname.match(/^\/object\/([^/]+)\/(.+)$/);
  if (!match) return null;
  const configuration = new URLSearchParams(window.location.search).get("configuration") || "";
  return {
    objectType: decodeURIComponent(match[1]),
    name: decodeURIComponent(match[2]),
    configuration,
  };
}

async function loadObjectPage(objectType, name, configuration) {
  showPanel("object");
  const header = $("#object-header");
  const chunksEl = $("#object-chunks");
  const jsonLink = $("#object-json-link");
  header.innerHTML = '<p class="muted">Загрузка...</p>';
  chunksEl.innerHTML = "";
  jsonLink.href = objectJsonUrl(objectType, name, configuration);

  const configQ = configuration ? `?configuration=${encodeURIComponent(configuration)}` : "";
  const basePath = `/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(name)}`;

  try {
    const detail = await api(`${basePath}${configQ}`);
    const obj = detail.object;
    const chunks = detail.chunks || [];

    header.innerHTML = `
      <h2>${escapeHtml(obj.name)}${obj.synonym ? ` — ${escapeHtml(obj.synonym)}` : ""}</h2>
      <div class="object-meta">
        <span>${escapeHtml(obj.object_type)}</span>
        <span>${escapeHtml(obj.configuration_name || "")}</span>
        <span>UUID: ${escapeHtml(obj.uuid || "—")}</span>
        <span>Реквизитов: ${detail.attributes_count ?? 0}</span>
        <span>ТЧ: ${detail.tabular_sections_count ?? 0}</span>
        <span>Чанков: ${chunks.length}</span>
      </div>
    `;

    if (!chunks.length) {
      chunksEl.innerHTML = '<p class="muted">Чанков нет</p>';
      return;
    }

    chunksEl.innerHTML = '<p class="muted">Загрузка чанков...</p>';

    const loaded = await Promise.all(
      chunks.map((ch) =>
        api(`${basePath}/chunks/${ch.chunk_index}${configQ}`).then((r) => ({
          meta: ch,
          text: r.text,
        }))
      )
    );
    loaded.sort((a, b) => a.meta.chunk_index - b.meta.chunk_index);

    chunksEl.innerHTML = loaded
      .map(
        ({ meta, text }) => `
      <div class="chunk-block">
        <div class="chunk-meta">Чанк #${meta.chunk_index} · ${meta.token_count} tok · ${meta.text_len} симв.</div>
        <pre>${escapeHtml(text || "")}</pre>
      </div>`
      )
      .join("");
  } catch (err) {
    header.innerHTML = `<p class="muted">Ошибка: ${escapeHtml(err.message)}</p>`;
    chunksEl.innerHTML = "";
  }
}

function goToSearch() {
  if (window.location.pathname.startsWith("/object/")) {
    history.pushState({}, "", "/");
  }
  showPanel("search");
}

function initRouting() {
  const route = parseObjectRoute();
  if (route) {
    loadObjectPage(route.objectType, route.name, route.configuration);
    return;
  }
  loadHealth();
  loadConfigurations();
}

$("#btn-object-back").addEventListener("click", goToSearch);

window.addEventListener("popstate", () => {
  const route = parseObjectRoute();
  if (route) {
    loadObjectPage(route.objectType, route.name, route.configuration);
  } else {
    showPanel("dashboard");
    loadHealth();
    loadConfigurations();
  }
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => showPanel(tab.dataset.tab));
});

document.querySelectorAll(".subtab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".subtab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".subpanel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $(`#subpanel-${tab.dataset.subtab}`).classList.add("active");
  });
});

async function loadHealth() {
  const el = $("#health-content");
  try {
    const data = await api("/health");
    const statusClass = data.status === "ok" ? "ok" : "warn";
    const dbClass = data.database === "ok" ? "ok" : "error";
    el.innerHTML = `
      <div class="health-item"><div class="label">Статус</div><div class="value ${statusClass}">${data.status}</div></div>
      <div class="health-item"><div class="label">Версия</div><div class="value">${data.version}</div></div>
      <div class="health-item"><div class="label">База данных</div><div class="value ${dbClass}">${data.database}</div></div>
      <div class="health-item"><div class="label">Конфигураций</div><div class="value">${data.configurations_count}</div></div>
    `;
  } catch (err) {
    el.innerHTML = `<p class="muted">Ошибка: ${escapeHtml(err.message)}</p>`;
  }
}

$("#btn-refresh-health").addEventListener("click", loadHealth);

async function loadConfigurations() {
  const tbody = $("#configs-body");
  try {
    configurations = await api("/configurations");
    fillConfigSelect();
    if (!configurations.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted">Нет проиндексированных конфигураций</td></tr>';
      return;
    }
    tbody.innerHTML = configurations
      .map(
        (c) => `
      <tr>
        <td>${escapeHtml(c.name)}</td>
        <td>${escapeHtml(c.synonym || "—")}</td>
        <td>${escapeHtml(c.version || "—")}</td>
        <td>${c.objects_count}</td>
        <td>${escapeHtml(c.indexed_at || "—")}</td>
        <td class="path" title="${escapeHtml(c.export_path)}">${escapeHtml(c.export_path)}</td>
        <td><button class="btn secondary btn-reindex" data-path="${escapeHtml(c.export_path)}">Переиндексировать</button></td>
      </tr>`
      )
      .join("");
    tbody.querySelectorAll(".btn-reindex").forEach((btn) => {
      btn.addEventListener("click", () => reindexConfig(btn.dataset.path));
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted">Ошибка: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function fillConfigSelect() {
  const sel = $("#search-configuration");
  const prev = sel.value;
  sel.innerHTML = configurations
    .map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`)
    .join("");
  if (prev && configurations.some((c) => c.name === prev)) {
    sel.value = prev;
  }
}

$("#btn-refresh-configs").addEventListener("click", loadConfigurations);

async function reindexConfig(exportPath) {
  if (!exportPath) return;
  try {
    const data = await api("/reindex", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: exportPath, skip_embeddings: true, async_job: true }),
    });
    showPanel("logs");
    selectedJobId = data.job_id;
    pollJob(data.job_id, null);
    refreshJobs();
  } catch (err) {
    alert(`Ошибка: ${err.message}`);
  }
}

$("#form-path").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = $("#input-source-path").value.trim();
  const body = {
    source,
    skip_embeddings: $("#path-skip-embeddings").checked,
    force: $("#path-force").checked,
  };
  try {
    const data = await api("/configurations/index", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    showJobStatus(data.job_id);
  } catch (err) {
    showAddError(err.message);
  }
});

let zipFile = null;
const dropZone = $("#drop-zone");
const zipInput = $("#input-zip");

$("#btn-pick-zip").addEventListener("click", () => zipInput.click());

zipInput.addEventListener("change", () => {
  if (zipInput.files.length) setZipFile(zipInput.files[0]);
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  const file = e.dataTransfer.files[0];
  if (file) setZipFile(file);
});

function setZipFile(file) {
  if (!file.name.toLowerCase().endsWith(".zip")) {
    alert("Только .zip файлы");
    return;
  }
  zipFile = file;
  $("#zip-filename").textContent = file.name;
  $("#btn-upload").disabled = false;
}

$("#form-zip").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!zipFile) return;
  const form = new FormData();
  form.append("file", zipFile);
  const params = new URLSearchParams({
    skip_embeddings: $("#zip-skip-embeddings").checked,
    force: $("#zip-force").checked,
  });
  try {
    const data = await api(`/configurations/upload?${params}`, { method: "POST", body: form });
    showJobStatus(data.job_id);
    zipFile = null;
    zipInput.value = "";
    $("#zip-filename").textContent = "";
    $("#btn-upload").disabled = true;
  } catch (err) {
    showAddError(err.message);
  }
});

function showAddError(msg) {
  const el = $("#add-job-status");
  el.classList.remove("hidden", "completed", "running");
  el.classList.add("failed");
  el.textContent = `Ошибка: ${msg}`;
}

function showJobStatus(jobId) {
  const el = $("#add-job-status");
  el.classList.remove("hidden", "completed", "failed");
  el.classList.add("running");
  el.textContent = "Индексация запущена...";
  showPanel("logs");
  selectedJobId = jobId;
  pollJob(jobId, (job) => {
    if (job.status === "completed") {
      el.classList.remove("running");
      el.classList.add("completed");
      el.textContent = `Готово: ${job.configuration_name || ""} — объектов ${job.stats?.objects_total ?? "?"}`;
      loadConfigurations();
    } else if (job.status === "failed") {
      el.classList.remove("running");
      el.classList.add("failed");
      el.textContent = `Ошибка: ${job.error || "неизвестная"}`;
    } else {
      el.textContent = `Статус: ${job.status}...`;
    }
  });
}

function pollJob(jobId, onUpdate) {
  if (activeJobPoll) clearInterval(activeJobPoll);
  const tick = async () => {
    try {
      const job = await api(`/configurations/jobs/${jobId}`);
      if (onUpdate) onUpdate(job);
      if (selectedJobId === jobId) renderJobLogs(job);
      if (job.status === "completed" || job.status === "failed") {
        clearInterval(activeJobPoll);
        activeJobPoll = null;
        refreshJobs();
        loadConfigurations();
      }
    } catch (_) { /* ignore */ }
  };
  tick();
  activeJobPoll = setInterval(tick, 2000);
}

$("#form-search").addEventListener("submit", async (e) => {
  e.preventDefault();
  const container = $("#search-results");
  container.innerHTML = '<p class="muted">Поиск...</p>';
  const body = {
    query: $("#search-query").value.trim(),
    top_k: parseInt($("#search-top-k").value, 10),
    full: $("#search-full").checked,
    configuration: $("#search-configuration").value || null,
    include_fields: false,
  };
  try {
    const results = await api("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!results.length) {
      container.innerHTML = '<p class="muted">Результаты не найдены</p>';
      return;
    }
    container.innerHTML = results
      .map((r, i) => {
        const objectUrl = objectPageUrl(r.object_type, r.name, r.configuration_name || "");
        const jsonUrl = objectJsonUrl(r.object_type, r.name, r.configuration_name || "");
        const chunkLabel =
          r.chunk_index !== undefined && r.chunk_index !== null
            ? `чанк #${r.chunk_index}`
            : "";
        return `
      <div class="result-card">
        <div class="meta">
          <span class="score">#${i + 1} score: ${(r.score ?? 0).toFixed(4)}</span>
          <span>${escapeHtml(r.object_type)}</span>
          <span>${escapeHtml(r.configuration_name || "")}</span>
          ${chunkLabel ? `<span>${escapeHtml(chunkLabel)}</span>` : ""}
        </div>
        <div class="title">${escapeHtml(r.name)}${r.synonym ? ` — ${escapeHtml(r.synonym)}` : ""}</div>
        <p class="hint muted">Показан найденный фрагмент документации, не весь объект</p>
        <pre>${escapeHtml(r.text || "")}</pre>
        <div class="actions">
          <a href="${objectUrl}" target="_blank" rel="noopener">Все чанки объекта</a>
          <a href="${jsonUrl}" target="_blank" rel="noopener">JSON</a>
        </div>
      </div>`;
      })
      .join("");
  } catch (err) {
    container.innerHTML = `<p class="muted">Ошибка: ${escapeHtml(err.message)}</p>`;
  }
});

async function refreshJobs() {
  const list = $("#jobs-list");
  try {
    const jobs = await api("/configurations/jobs?limit=50");
    if (!jobs.length) {
      list.innerHTML = '<li class="muted">Нет задач</li>';
      return;
    }
    list.innerHTML = jobs
      .map(
        (j) => `
      <li data-id="${j.id}" class="${j.id === selectedJobId ? "selected" : ""}">
        <div>${escapeHtml(j.configuration_name || j.source || j.id.slice(0, 8))}</div>
        <div class="job-type">${escapeHtml(j.type)} · ${escapeHtml(j.created_at?.slice(0, 19) || "")}</div>
        <span class="job-status-badge ${j.status}">${escapeHtml(j.status)}</span>
      </li>`
      )
      .join("");
    list.querySelectorAll("li[data-id]").forEach((li) => {
      li.addEventListener("click", async () => {
        selectedJobId = li.dataset.id;
        list.querySelectorAll("li").forEach((x) => x.classList.remove("selected"));
        li.classList.add("selected");
        const job = await api(`/configurations/jobs/${selectedJobId}`);
        renderJobLogs(job);
      });
    });
  } catch (err) {
    list.innerHTML = `<li class="muted">Ошибка: ${escapeHtml(err.message)}</li>`;
  }
}

$("#btn-refresh-jobs").addEventListener("click", refreshJobs);

function renderJobLogs(job) {
  $("#logs-title").textContent = `Лог задачи ${job.id.slice(0, 8)}`;
  const out = $("#logs-output");
  out.innerHTML = (job.logs || []).map((line) => `<span class="log-line info">${escapeHtml(line)}</span>`).join("\n");
  out.scrollTop = out.scrollHeight;
}

async function refreshServerLogs() {
  if (logsPaused || selectedJobId) return;
  $("#logs-title").textContent = "Лог сервера";
  try {
    const params = logsSinceId > 0 ? `?since_id=${logsSinceId}` : "?tail=200";
    const data = await api(`/logs${params}`);
    if (!data.records.length) return;
    const out = $("#logs-output");
    const atBottom = out.scrollHeight - out.scrollTop <= out.clientHeight + 40;
    data.records.forEach((r) => {
      const cls = r.level === "ERROR" ? "error" : r.level === "WARNING" ? "warning" : "info";
      out.insertAdjacentHTML("beforeend", `<span class="log-line ${cls}">[${escapeHtml(r.ts)}] ${escapeHtml(r.message)}</span>\n`);
    });
    logsSinceId = data.last_id;
    if (atBottom) out.scrollTop = out.scrollHeight;
  } catch (_) { /* ignore */ }
}

function startLogsPolling() {
  stopLogsPolling();
  if (!logsPaused && !selectedJobId) refreshServerLogs();
  logsTimer = setInterval(() => {
    if (selectedJobId) return;
    refreshServerLogs();
  }, 3000);
}

function stopLogsPolling() {
  if (logsTimer) {
    clearInterval(logsTimer);
    logsTimer = null;
  }
}

$("#btn-logs-pause").addEventListener("click", () => {
  logsPaused = !logsPaused;
  $("#btn-logs-pause").textContent = logsPaused ? "Продолжить" : "Пауза";
});

$("#btn-logs-clear").addEventListener("click", () => {
  $("#logs-output").innerHTML = "";
  logsSinceId = 0;
});

$("#btn-logs-refresh").addEventListener("click", async () => {
  if (selectedJobId) {
    const job = await api(`/configurations/jobs/${selectedJobId}`);
    renderJobLogs(job);
  } else {
    logsSinceId = 0;
    $("#logs-output").innerHTML = "";
    await refreshServerLogs();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && selectedJobId) {
    selectedJobId = null;
    $("#logs-title").textContent = "Лог сервера";
    $("#logs-output").innerHTML = "";
    logsSinceId = 0;
    refreshJobs();
    refreshServerLogs();
  }
});

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

initRouting();
