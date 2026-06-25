/* global state */
let logsPaused = false;
let logsSinceId = 0;
let logsTimer = null;
let selectedJobId = null;
let activeJobPoll = null;
let configurations = [];
const ACTIVE_JOB_STATUSES = new Set(["pending", "extracting", "indexing", "deleting"]);
const pendingConfigOps = {
  deletes: new Map(),
  updates: new Map(),
  embeds: new Map(),
};

let wizardZipFile = null;
let wizardPathDetectTimer = null;
let configFilterText = "";
let currentConfigurationCard = null;
const jobLogOffsets = new Map();
const MAX_LOG_DOM_LINES = 500;

const API = "";

const JOB_STATUS_LABELS = {
  pending: "ожидание",
  extracting: "импорт",
  indexing: "индексация",
  deleting: "удаление",
  completed: "готово",
  failed: "ошибка",
};

const JOB_TYPE_LABELS = {
  path: "путь",
  zip: "ZIP + индекс",
  reindex: "переиндексация",
  index: "метаданные",
  embed: "эмбеддинги",
  delete: "удаление",
  import_zip: "обновление из файлов",
  import_path: "обновление из файлов",
};

const JOB_KIND_LABELS = {
  update: "обновление метаданных",
  embed: "переиндексация",
  delete: "удаление",
  full: "полная индексация",
  import: "обновление из файлов",
};

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

function on(selector, event, handler) {
  const el = $(selector);
  if (el) el.addEventListener(event, handler);
}

function setButtonLoading(btn, loading, { label } = {}) {
  if (!btn) return;
  btn.classList.toggle("is-loading", Boolean(loading));
  btn.setAttribute("aria-busy", loading ? "true" : "false");
  if (label != null) btn.textContent = label;
  if (loading) btn.disabled = true;
}

function clearButtonLoading(btn, label) {
  if (!btn) return;
  btn.classList.remove("is-loading");
  btn.setAttribute("aria-busy", "false");
  btn.disabled = false;
  if (label != null) btn.textContent = label;
}

async function withButtonLoading(btn, fn, options = {}) {
  const { loadingLabel = "Запуск…", sustainOnSuccess = false } = options;
  if (!btn) return fn();
  const prevLabel = btn.textContent;
  setButtonLoading(btn, true, { label: loadingLabel });
  try {
    const result = await fn();
    if (!sustainOnSuccess) {
      clearButtonLoading(btn, prevLabel);
    } else {
      const card = currentConfigurationCard || {
        name: $("#wizard-config-name")?.value.trim() || "",
        in_database: false,
        has_export: false,
        objects_count: 0,
      };
      if (card.name) updateConfigurationPageActions(card);
    }
    return result;
  } catch (err) {
    clearButtonLoading(btn, prevLabel);
    throw err;
  }
}

function syncConfigButton(btn, { disabled, loading, label, title } = {}) {
  if (!btn) return;
  if (label != null) btn.textContent = label;
  if (title != null) btn.title = title;
  btn.disabled = Boolean(disabled);
  btn.classList.toggle("is-loading", Boolean(loading));
  btn.setAttribute("aria-busy", loading ? "true" : "false");
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
    if (name === "configurations") {
      loadConfigurations();
    } else if (name === "dashboard") {
      loadHealth();
    } else if (name === "configuration") {
      /* loaded by loadConfigurationPage */
    }
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

function configurationPageUrl(name) {
  if (!name || name === "new") return "/configuration/new";
  return `/configuration/${encodeURIComponent(name)}`;
}

function parseConfigurationRoute() {
  const match = window.location.pathname.match(/^\/configuration\/(.+)$/);
  if (!match) return null;
  const raw = decodeURIComponent(match[1]);
  if (raw === "new") return { name: null, isNew: true };
  return { name: raw, isNew: false };
}

function navigateToConfiguration(name) {
  const url = configurationPageUrl(name);
  history.pushState({}, "", url);
  loadConfigurationPage(name);
}

function goToConfigurations() {
  if (window.location.pathname.startsWith("/configuration/")) {
    history.pushState({}, "", "/");
  }
  currentConfigurationCard = null;
  showPanel("configurations");
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
  const objectRoute = parseObjectRoute();
  if (objectRoute) {
    loadObjectPage(objectRoute.objectType, objectRoute.name, objectRoute.configuration);
    return;
  }
  const configRoute = parseConfigurationRoute();
  if (configRoute) {
    loadConfigurationPage(configRoute.isNew ? null : configRoute.name);
    return;
  }
  loadHealth();
  loadConfigurations();
}

$("#btn-object-back").addEventListener("click", goToSearch);
$("#btn-configuration-back")?.addEventListener("click", goToConfigurations);

window.addEventListener("popstate", () => {
  const objectRoute = parseObjectRoute();
  if (objectRoute) {
    loadObjectPage(objectRoute.objectType, objectRoute.name, objectRoute.configuration);
    return;
  }
  const configRoute = parseConfigurationRoute();
  if (configRoute) {
    loadConfigurationPage(configRoute.isNew ? null : configRoute.name);
    return;
  }
  showPanel("dashboard");
  loadHealth();
  loadConfigurations();
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.dataset.tab === "configurations" && window.location.pathname.startsWith("/configuration/")) {
      history.pushState({}, "", "/");
      currentConfigurationCard = null;
    }
    showPanel(tab.dataset.tab);
  });
});

async function loadHealth() {
  const el = $("#health-content");
  if (!el) return;
  try {
    const data = await api("/health");
    const statusClass = data.status === "ok" ? "ok" : "warn";
    const dbClass = data.database === "ok" ? "ok" : "error";
    const emb = data.embeddings || {};
    const providerLabel = {
      sentence_transformers: "локально",
      ollama: "Ollama",
      openai: "OpenAI API",
    }[emb.provider] || emb.provider || "—";
    el.innerHTML = `
      <div class="health-item"><div class="label">Статус</div><div class="value ${statusClass}">${data.status}</div></div>
      <div class="health-item"><div class="label">Версия</div><div class="value">${data.version}</div></div>
      <div class="health-item"><div class="label">База данных</div><div class="value ${dbClass}">${data.database}</div></div>
      <div class="health-item"><div class="label">Конфигураций</div><div class="value">${data.configurations_count}</div></div>
      <div class="health-item health-item-wide"><div class="label">Эмбеддинги</div><div class="value health-embeddings">${escapeHtml(providerLabel)} · ${escapeHtml(emb.model || "—")}</div></div>
    `;
  } catch (err) {
    el.innerHTML = `<p class="muted">Ошибка: ${escapeHtml(err.message)}</p>`;
  }
}

$("#btn-refresh-health").addEventListener("click", loadHealth);

async function refreshPendingConfigOps() {
  pendingConfigOps.deletes.clear();
  pendingConfigOps.updates.clear();
  pendingConfigOps.embeds.clear();
  try {
    const jobs = await api("/configurations/jobs?limit=50");
    for (const job of jobs) {
      if (!ACTIVE_JOB_STATUSES.has(job.status)) continue;
      if (job.type === "delete") {
        const name = job.configuration_name || job.source;
        if (name) pendingConfigOps.deletes.set(name, job.id);
      } else if (job.type === "embed") {
        const name = job.configuration_name;
        if (name) pendingConfigOps.embeds.set(name, job.id);
      } else if (["index", "reindex", "path", "zip", "import_zip", "import_path"].includes(job.type)) {
        const name = job.configuration_name;
        if (name) pendingConfigOps.updates.set(name, job.id);
      }
    }
  } catch (_) {
    /* keep previous pending state on transient errors */
  }
}

async function startConfigurationUpdate(name) {
  const btn = $("#btn-config-page-update");
  try {
    await withButtonLoading(
      btn,
      async () => {
        const data = await api(`/configurations/${encodeURIComponent(name)}/index`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skip_embeddings: true, force: false }),
        });
        showConfigJobStatus(data.job_id, name, "update");
        loadConfigurations();
      },
      { sustainOnSuccess: true }
    );
  } catch (err) {
    showConfigActionError(err.message);
  }
}

async function startConfigurationReindex(name) {
  const btn = $("#btn-config-page-reindex");
  try {
    await withButtonLoading(
      btn,
      async () => {
        const data = await api(`/configurations/${encodeURIComponent(name)}/embed`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ force: false }),
        });
        showConfigJobStatus(data.job_id, name, "embed");
        loadConfigurations();
      },
      { sustainOnSuccess: true }
    );
  } catch (err) {
    showConfigActionError(err.message);
  }
}

function showConfigActionError(message) {
  const el = activeJobStatusContainer();
  const textEl = el?.querySelector(".job-status-text") || el?.querySelector("[id$='-action-text']");
  el?.classList.remove("hidden", "completed", "running");
  el?.classList.add("failed");
  hideProgressBar();
  if (textEl) textEl.textContent = message;
  else if (el) el.textContent = message;
}

function hideProgressBar() {
  ["#configs-progress-bar", "#configuration-progress-bar"].forEach((sel) => {
    $(sel)?.classList.add("hidden");
  });
  ["#configs-progress-fill", "#configuration-progress-fill"].forEach((sel) => {
    const fill = $(sel);
    if (fill) fill.style.width = "0%";
  });
}

function updateProgressBar(job) {
  const onConfigPage = $("#panel-configuration")?.classList.contains("active");
  const bar = $(onConfigPage ? "#configuration-progress-bar" : "#configs-progress-bar");
  const fill = $(onConfigPage ? "#configuration-progress-fill" : "#configs-progress-fill");
  if (!bar || !fill) return;
  const progress = job?.progress;
  if (!progress || job.status === "completed" || job.status === "failed") {
    bar.classList.add("hidden");
    fill.style.width = "0%";
    return;
  }
  bar.classList.remove("hidden");
  if (progress.percent != null && progress.total) {
    bar.classList.remove("indeterminate");
    fill.style.width = `${Math.min(100, progress.percent)}%`;
  } else {
    bar.classList.add("indeterminate");
    fill.style.width = "40%";
  }
}

function configMatchesFilter(config) {
  const q = configFilterText.trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    config.name,
    config.synonym,
    config.version,
    config.has_export ? "выгрузка" : "нет выгрузки",
    config.in_database ? "база" : "",
    config.embedding_status,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

function applyConfigFilter() {
  document.querySelectorAll("#configs-body tr[data-config-name]").forEach((row) => {
    const name = row.dataset.configName;
    const config = configurations.find((c) => c.name === name);
    row.classList.toggle("config-row-filtered-out", config ? !configMatchesFilter(config) : false);
  });
}

function configActionStates(config) {
  const deleting = pendingConfigOps.deletes.has(config.name);
  const updating = pendingConfigOps.updates.has(config.name);
  const embedding = pendingConfigOps.embeds.has(config.name);
  const busy = deleting || updating || embedding;
  const canUpdate = config.has_export;
  const canReindex = config.in_database && (config.has_export || config.objects_count > 0);
  const busyHint = embedding
    ? "Идёт переиндексация — дождитесь завершения"
    : updating
      ? "Идёт операция — дождитесь завершения"
      : deleting
        ? "Идёт удаление — дождитесь завершения"
        : "";
  return {
    busy,
    busyHint,
    deleteDisabled: busy,
    deleteLabel: deleting ? "Удаление…" : config.in_database ? "Удалить" : "Удалить слот",
    updateDisabled: busy || !canUpdate,
    updateLabel: updating ? "Обновление…" : "Обновить метаданные",
    updateHint: !canUpdate
      ? "Подключите источник файлов в «Обновить из файлов»"
      : busyHint || "Парсинг XML и чанки в базу, без эмбеддингов",
    reindexDisabled: busy || !canReindex,
    reindexLabel: embedding ? "Переиндексация…" : "Переиндексировать",
    reindexHint: !canReindex
      ? "Нет чанков в базе — сначала обновите метаданные"
      : !config.has_export
        ? "Эмбеддинги по чанкам в базе (источник XML не подключён)"
        : busyHint || "Только эмбеддинги и FAISS по чанкам в базе",
    fullIndexLabel: updating ? "Индексация…" : "Полная индексация",
    importZipLabel: updating ? "Обновление…" : "Подключить ZIP",
    importPathLabel: updating ? "Обновление…" : "Подключить путь",
    updating,
    deleting,
    embedding,
  };
}

function exportStatusLabel(config) {
  if (config.slot_status === "invalid") {
    return '<span class="warn-text" title="Configuration.xml не найден или повреждён">битая выгрузка</span>';
  }
  if (config.has_export && config.export_linked) {
    return '<span class="ok-text" title="Путь привязан без копирования">привязка</span>';
  }
  if (config.has_export) return '<span class="ok-text" title="Файлы в хранилище">подключён</span>';
  if (config.in_database) return '<span class="warn-text" title="Укажите источник на странице управления">нет источника</span>';
  return '<span class="warn-text">нет источника</span>';
}

function indexStatusLabel(config) {
  if (!config.in_database) return "не индексировалась";
  if (!config.has_export && config.slot_status !== "ready") {
    return '<span class="warn-text" title="Индекс в базе, источник XML не подключён">индекс без источника</span>';
  }
  if (!config.indexed_at) return "готова к обновлению";
  return escapeHtml(config.indexed_at);
}

function embeddingStatusLabel(config) {
  const model = config.embedding_model;
  const provider = config.embeddings_provider || "";
  const custom = config.embeddings_custom ? "" : " (по умолчанию)";
  if (config.embedding_status === "ready") {
    return '<span class="warn-text" title="Выгрузка есть, FAISS ещё не построен">нет индекса</span>';
  }
  if (config.embedding_status === "ok") {
    return escapeHtml(`${provider || ""} · ${model || "ok"}${custom}`);
  }
  if (config.embedding_status === "stale") {
    return `<span class="warn-text" title="Модель в индексе не совпадает с настройками">устарел: ${escapeHtml(model || "?")}</span>`;
  }
  return '<span class="warn-text">нет индекса</span>';
}

async function loadConfigurations() {
  const tbody = $("#configs-body");
  try {
    await refreshPendingConfigOps();
    configurations = await api("/configurations");
    fillConfigSelect();
    if (!configurations.length) {
      tbody.innerHTML =
        '<tr><td colspan="8" class="muted">Нет конфигураций. Нажмите «+ Новая».</td></tr>';
      return;
    }
    tbody.innerHTML = configurations
      .map((c) => {
        const actions = configActionStates(c);
        const manageUrl = configurationPageUrl(c.name);
        return `
      <tr data-config-name="${escapeHtml(c.name)}" class="${actions.busy ? "config-row-busy" : ""}">
        <td>${escapeHtml(c.name)}</td>
        <td>${escapeHtml(c.synonym || "—")}</td>
        <td>${escapeHtml(c.version || "—")}</td>
        <td>${c.in_database ? c.objects_count : "—"}</td>
        <td>${exportStatusLabel(c)}</td>
        <td>${indexStatusLabel(c)}</td>
        <td>${embeddingStatusLabel(c)}</td>
        <td>
          <a href="${manageUrl}" class="btn secondary btn-config-manage" data-name="${escapeHtml(c.name)}">Управление</a>
        </td>
      </tr>`;
      })
      .join("");
    tbody.querySelectorAll(".btn-config-manage").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        navigateToConfiguration(btn.dataset.name);
      });
    });
    applyConfigFilter();
    resumeActiveJobs();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">Ошибка: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function fillConfigSelect() {
  const sel = $("#search-configuration");
  if (!sel) return;
  const prev = sel.value;
  const indexed = configurations.filter((c) => c.in_database && c.indexed_at);
  sel.innerHTML = indexed
    .map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`)
    .join("");
  if (prev && indexed.some((c) => c.name === prev)) {
    sel.value = prev;
  }
}

const EMBEDDINGS_MODEL_HINTS = {
  sentence_transformers: "Локальная модель без API. Пример: paraphrase-multilingual-MiniLM-L12-v2",
  ollama: "Embedding-модель в Ollama. Пример: nomic-embed-text, mxbai-embed-large",
  openai: "Embedding-модель API. Пример: text-embedding-3-small",
};

const EMBEDDINGS_MODEL_DEFAULTS = {
  sentence_transformers: "paraphrase-multilingual-MiniLM-L12-v2",
  ollama: "nomic-embed-text",
  openai: "text-embedding-3-small",
};

function wizardEmbeddingsTestUrl(name) {
  return `/settings/embeddings/test?configuration=${encodeURIComponent(name)}`;
}

function updateWizardEmbeddingsFields() {
  const provider = $("#wizard-embeddings-provider")?.value;
  $("#wizard-embeddings-openai-fields")?.classList.toggle("hidden", provider !== "openai");
  $("#wizard-embeddings-ollama-fields")?.classList.toggle("hidden", provider !== "ollama");
  const hint = $("#wizard-embeddings-model-hint");
  if (hint) hint.textContent = EMBEDDINGS_MODEL_HINTS[provider] || "";
}

function wizardEmbeddingsPayload() {
  const payload = {
    provider: $("#wizard-embeddings-provider").value,
    model: $("#wizard-embeddings-model").value.trim(),
    base_url: $("#wizard-embeddings-base-url").value.trim() || null,
    ollama_base_url: $("#wizard-embeddings-ollama-url").value.trim() || "http://localhost:11434",
  };
  const apiKey = $("#wizard-embeddings-api-key").value.trim();
  if (apiKey) payload.openai_api_key = apiKey;
  return payload;
}

function applyWizardEmbeddings(data) {
  const label = $("#wizard-embeddings-label");
  if (label && data.configuration) {
    const suffix = data.uses_default ? " (по умолчанию)" : " (сохранённые)";
    label.textContent = `Для «${data.configuration}»${suffix}`;
  }
  $("#wizard-embeddings-provider").value = data.provider;
  $("#wizard-embeddings-model").value = data.model;
  $("#wizard-embeddings-base-url").value = data.base_url || "";
  $("#wizard-embeddings-ollama-url").value = data.ollama_base_url || "http://localhost:11434";
  $("#wizard-embeddings-api-key").value = "";
  $("#wizard-embeddings-api-key").placeholder = data.has_openai_api_key
    ? "ключ сохранён — оставьте пустым"
    : "API-ключ";
  updateWizardEmbeddingsFields();
}

async function loadWizardEmbeddings(name) {
  if (!name) return;
  try {
    const data = await api(`/settings/embeddings?configuration=${encodeURIComponent(name)}`);
    applyWizardEmbeddings(data);
  } catch (err) {
    setWizardStatus("#wizard-embeddings-status", err.message, "error");
  }
}

function setWizardStatus(selector, message, kind) {
  const el = $(selector);
  if (!el) return;
  el.textContent = message;
  el.className = `job-status ${kind}`;
  el.classList.remove("hidden");
}

function clearWizardStatuses() {
  ["#wizard-import-status", "#wizard-detect-status", "#wizard-embeddings-status", "#wizard-index-status"].forEach(
    (sel) => $(sel)?.classList.add("hidden")
  );
}

async function ensureWizardSlot(name) {
  await api("/configurations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

function renderConfigurationStatus(card) {
  const el = $("#configuration-status");
  if (!el || !card) return;
  const sourceText = card.has_export
    ? card.export_linked
      ? "привязка к пути"
      : "файлы в хранилище"
    : card.in_database
      ? "нет источника"
      : "не подключён";
  el.innerHTML = `
    <div class="configuration-status-grid">
      <div><span class="label">В базе</span><span class="value">${card.in_database ? "да" : "нет"}</span></div>
      <div><span class="label">Источник XML</span><span class="value">${escapeHtml(sourceText)}</span></div>
      <div><span class="label">Объектов</span><span class="value">${card.in_database ? card.objects_count : "—"}</span></div>
      <div><span class="label">Метаданные</span><span class="value">${card.indexed_at ? escapeHtml(card.indexed_at) : "—"}</span></div>
      <div><span class="label">Эмбеддинги</span><span class="value">${embeddingStatusLabel(card)}</span></div>
    </div>
  `;
  $("#configuration-no-source-banner")?.classList.toggle("hidden", Boolean(card.has_export));
}

function updateConfigurationPageActions(card) {
  if (!card) return;
  const actions = configActionStates(card);
  syncConfigButton($("#btn-config-page-update"), {
    disabled: actions.updateDisabled,
    loading: actions.updating,
    label: actions.updateLabel,
    title: actions.updateHint,
  });
  syncConfigButton($("#btn-config-page-reindex"), {
    disabled: actions.reindexDisabled,
    loading: actions.embedding,
    label: actions.reindexLabel,
    title: actions.reindexHint,
  });
  syncConfigButton($("#btn-config-page-delete"), {
    disabled: actions.deleteDisabled,
    loading: actions.deleting,
    label: actions.deleteLabel,
    title: actions.busyHint || "",
  });
  syncConfigButton($("#btn-wizard-index"), {
    disabled: actions.busy || !card.has_export,
    loading: actions.updating,
    label: actions.fullIndexLabel,
    title: card.has_export
      ? "Метаданные и эмбеддинги с параметрами ниже"
      : "Сначала подключите источник файлов",
  });
  syncConfigButton($("#btn-wizard-import-zip"), {
    disabled: actions.busy,
    loading: actions.updating,
    label: actions.importZipLabel,
  });
  syncConfigButton($("#btn-wizard-import-path"), {
    disabled: actions.busy,
    loading: actions.updating,
    label: actions.importPathLabel,
  });
}

async function loadConfigurationPage(name) {
  showPanel("configuration");
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  $(".tab[data-tab='configurations']")?.classList.add("active");

  clearWizardStatuses();
  wizardZipFile = null;
  $("#wizard-input-zip").value = "";
  $("#wizard-zip-filename").textContent = "";
  $("#wizard-source-path").value = "";
  $("#configuration-action-status")?.classList.add("hidden");

  const isNew = !name || name === "new";
  if (isNew) {
    currentConfigurationCard = null;
    $("#configuration-title").textContent = "Новая конфигурация";
    $("#configuration-status").innerHTML =
      '<p class="hint">Укажите имя или источник файлов — имя подставится из Configuration.xml.</p>';
    $("#configuration-no-source-banner")?.classList.remove("hidden");
    $("#wizard-config-name").value = "";
    $("#wizard-config-name").readOnly = false;
    $("#wizard-slot-path").textContent = "output/exports/…";
    $("#wizard-slot-hint").textContent =
      "Укажите путь к выгрузке или ZIP — имя заполнится автоматически.";
    updateConfigurationPageActions({
      name: "",
      in_database: false,
      has_export: false,
      objects_count: 0,
    });
    return;
  }

  $("#configuration-title").textContent = name;
  $("#configuration-status").innerHTML = '<p class="muted">Загрузка…</p>';
  $("#wizard-config-name").value = name;
  $("#wizard-config-name").readOnly = true;

  try {
    const card = await api(`/configurations/${encodeURIComponent(name)}`);
    currentConfigurationCard = card;
    $("#wizard-slot-path").textContent = card.export_slot_path || `output/exports/${name}`;
    $("#wizard-slot-hint").textContent = card.has_export
      ? card.export_linked
        ? "Источник привязан к пути на сервере. Можно заменить файлы или сразу обновить метаданные."
        : "Источник подключён. Можно заменить файлы или сразу обновить метаданные."
      : "Источник не подключён — укажите ZIP или путь в блоке «Обновить из файлов».";
    renderConfigurationStatus(card);
    await loadWizardEmbeddings(name);
    await refreshPendingConfigOps();
    updateConfigurationPageActions(card);
  } catch (err) {
    $("#configuration-status").innerHTML = `<p class="muted">Ошибка: ${escapeHtml(err.message)}</p>`;
  }
}

async function openWizard(name) {
  navigateToConfiguration(name);
}

function closeWizard() {
  goToConfigurations();
}

function updateSkipEmbeddingsHint() {
  const hint = $("#wizard-skip-embeddings-hint");
  const skip = Boolean($("#wizard-skip-embeddings")?.checked);
  if (!hint) return;
  hint.textContent = skip
    ? "Будет обновлена только текстовая информация, без возможности семантического поиска."
    : "Обновится текстовая информация и семантический поиск по изменённым файлам.";
}

function setupWizard() {
  on("#btn-new-configuration", "click", () => navigateToConfiguration(null));
  on("#btn-config-page-update", "click", () => {
    const name = $("#wizard-config-name")?.value.trim();
    if (name) startConfigurationUpdate(name);
  });
  on("#btn-config-page-reindex", "click", () => {
    const name = $("#wizard-config-name")?.value.trim();
    if (name) startConfigurationReindex(name);
  });
  on("#btn-config-page-delete", "click", () => {
    const name = $("#wizard-config-name")?.value.trim();
    if (name) deleteConfig(name, $("#btn-config-page-delete"));
  });

  document.querySelectorAll(".wizard-import-tabs .subtab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".wizard-import-tabs .subtab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const mode = tab.dataset.wizardImport;
      $("#wizard-import-zip")?.classList.toggle("hidden", mode !== "zip");
      $("#wizard-import-path")?.classList.toggle("hidden", mode !== "path");
    });
  });

  on("#btn-wizard-pick-zip", "click", () => $("#wizard-input-zip")?.click());
  on("#wizard-input-zip", "change", () => {
    const file = $("#wizard-input-zip")?.files?.[0];
    if (file) setWizardZipFile(file);
  });
  on("#wizard-source-path", "blur", () => {
    const source = $("#wizard-source-path")?.value.trim();
    if (source) wizardDetectFromSourcePath(source).catch(() => {});
  });
  on("#wizard-source-path", "input", () => {
    if (wizardPathDetectTimer) clearTimeout(wizardPathDetectTimer);
    const source = $("#wizard-source-path")?.value.trim();
    if (!source) return;
    wizardPathDetectTimer = setTimeout(() => {
      wizardDetectFromSourcePath(source, { quiet: true }).catch(() => {});
    }, 500);
  });
  const drop = $("#wizard-drop-zone");
  drop?.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("dragover");
  });
  drop?.addEventListener("dragleave", () => drop.classList.remove("dragover"));
  drop?.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("dragover");
    if (e.dataTransfer?.files?.[0]) setWizardZipFile(e.dataTransfer.files[0]);
  });

  on("#wizard-embeddings-provider", "change", () => {
    const provider = $("#wizard-embeddings-provider").value;
    const modelInput = $("#wizard-embeddings-model");
    if (modelInput && !modelInput.dataset.userEdited) {
      modelInput.value = EMBEDDINGS_MODEL_DEFAULTS[provider] || "";
    }
    updateWizardEmbeddingsFields();
  });

  on("#wizard-embeddings-model", "input", () => {
    const modelInput = $("#wizard-embeddings-model");
    if (modelInput) modelInput.dataset.userEdited = "1";
  });

  on("#wizard-skip-embeddings", "change", () => {
    $("#wizard-embeddings-section")?.classList.toggle(
      "hidden",
      $("#wizard-skip-embeddings").checked
    );
    updateSkipEmbeddingsHint();
  });

  on("#wizard-mirror-path", "change", () => {
    $("#wizard-mirror-warning")?.classList.toggle(
      "hidden",
      !$("#wizard-mirror-path")?.checked
    );
  });

  on("#configs-filter", "input", (e) => {
    configFilterText = e.target.value;
    applyConfigFilter();
  });

  on("#btn-wizard-import-zip", "click", wizardImportZip);
  on("#btn-wizard-import-path", "click", wizardImportPath);
  on("#btn-wizard-detect", "click", wizardDetect);
  on("#btn-wizard-test-embeddings", "click", wizardTestEmbeddings);
  on("#btn-wizard-index", "click", wizardStartIndex);
  updateSkipEmbeddingsHint();
}

function setWizardZipFile(file) {
  if (!file.name.toLowerCase().endsWith(".zip")) {
    alert("Только .zip файлы");
    return;
  }
  wizardZipFile = file;
  $("#wizard-zip-filename").textContent = file.name;
}

async function wizardDetectFromSourcePath(source, options = {}) {
  const { quiet = false, fillName = true } = options;
  const nameInput = $("#wizard-config-name");
  const readonly = Boolean(nameInput?.readOnly);
  const expected = nameInput?.value.trim() || null;
  const body = { source };
  if (expected) body.expected_configuration = expected;

  const data = await api("/configurations/detect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (fillName && !readonly && data.name) {
    nameInput.value = data.name;
    $("#wizard-slot-path").textContent = `output/exports/${data.name}`;
    await ensureWizardSlot(data.name);
    if ($("#panel-configuration")?.classList.contains("active")) {
      history.replaceState({}, "", configurationPageUrl(data.name));
      $("#configuration-title").textContent = data.name;
      nameInput.readOnly = true;
    }
  }

  const label = `${data.name}${data.synonym ? ` (${data.synonym})` : ""}`;
  if (!quiet) {
    if (data.matches_expected === false) {
      setWizardStatus("#wizard-import-status", data.message || `В папке: ${label}`, "error");
    } else {
      setWizardStatus("#wizard-import-status", `В папке: ${label}`, "ok");
    }
  }

  if (data.embeddings) {
    data.embeddings.configuration = data.name;
    applyWizardEmbeddings(data.embeddings);
  } else if (data.name) {
    await loadWizardEmbeddings(data.name);
  }

  return data;
}

async function wizardConfigName() {
  const name = $("#wizard-config-name").value.trim();
  if (!name) throw new Error("Укажите имя конфигурации");
  await ensureWizardSlot(name);
  $("#wizard-slot-path").textContent = `output/exports/${name}`;
  return name;
}

async function wizardImportZip() {
  if (!wizardZipFile) {
    setWizardStatus("#wizard-import-status", "Выберите ZIP-файл", "error");
    return;
  }
  const btn = $("#btn-wizard-import-zip");
  try {
    await withButtonLoading(
      btn,
      async () => {
        const name = await wizardConfigName();
        const form = new FormData();
        form.append("file", wizardZipFile);
        const data = await api(
          `/configurations/${encodeURIComponent(name)}/import?async_job=true`,
          { method: "POST", body: form }
        );
        history.replaceState({}, "", configurationPageUrl(name));
        currentConfigurationCard = { name, in_database: false, has_export: false };
        showConfigJobStatus(data.job_id, name, "import");
        loadConfigurations();
      },
      { sustainOnSuccess: true }
    );
  } catch (err) {
    setWizardStatus("#wizard-import-status", err.message, "error");
  }
}

async function wizardImportPath() {
  const source = $("#wizard-source-path").value.trim();
  if (!source) {
    setWizardStatus("#wizard-import-status", "Укажите путь", "error");
    return;
  }
  const mirror = Boolean($("#wizard-mirror-path")?.checked);
  const btn = $("#btn-wizard-import-path");
  try {
    await withButtonLoading(
      btn,
      async () => {
        if (!$("#wizard-config-name").value.trim()) {
          await wizardDetectFromSourcePath(source, { quiet: true });
        }
        const name = await wizardConfigName();
        const data = await api(
          `/configurations/${encodeURIComponent(name)}/import-path?async_job=true`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source, mirror }),
          }
        );
        history.replaceState({}, "", configurationPageUrl(name));
        currentConfigurationCard = { name, in_database: false, has_export: false };
        showConfigJobStatus(data.job_id, name, "import");
        loadConfigurations();
      },
      { sustainOnSuccess: true }
    );
  } catch (err) {
    setWizardStatus("#wizard-import-status", err.message, "error");
  }
}

async function wizardDetect() {
  const btn = $("#btn-wizard-detect");
  try {
    await withButtonLoading(
      btn,
      async () => {
        const name = await wizardConfigName();
        const data = await api(`/configurations/${encodeURIComponent(name)}/detect`, { method: "POST" });
        const label = `${data.name}${data.synonym ? ` (${data.synonym})` : ""}`;
        if (!data.matches_expected) {
          setWizardStatus("#wizard-detect-status", data.message || `Несовпадение: ${label}`, "error");
          return;
        }
        setWizardStatus("#wizard-detect-status", `OK: ${label}`, "ok");
        if (data.embeddings) {
          data.embeddings.configuration = name;
          applyWizardEmbeddings(data.embeddings);
        } else {
          await loadWizardEmbeddings(name);
        }
      },
      { loadingLabel: "Проверка…" }
    );
  } catch (err) {
    setWizardStatus("#wizard-detect-status", err.message, "error");
  }
}

async function wizardTestEmbeddings() {
  const btn = $("#btn-wizard-test-embeddings");
  try {
    await withButtonLoading(
      btn,
      async () => {
        const name = await wizardConfigName();
        const data = await api(wizardEmbeddingsTestUrl(name), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(wizardEmbeddingsPayload()),
        });
        setWizardStatus(
          "#wizard-embeddings-status",
          `OK: ${data.provider}, ${data.model}, dim=${data.dimension}`,
          "ok"
        );
      },
      { loadingLabel: "Проверка…" }
    );
  } catch (err) {
    setWizardStatus("#wizard-embeddings-status", err.message, "error");
  }
}

async function wizardStartIndex() {
  const btn = $("#btn-wizard-index");
  try {
    await withButtonLoading(
      btn,
      async () => {
        const name = await wizardConfigName();
        const skipEmbeddings = $("#wizard-skip-embeddings").checked;
        const body = {
          skip_embeddings: skipEmbeddings,
          force: $("#wizard-force").checked,
        };
        if (!skipEmbeddings) body.embeddings = wizardEmbeddingsPayload();
        const data = await api(`/configurations/${encodeURIComponent(name)}/index`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        showWizardJobStatus(data.job_id, name);
      },
      { sustainOnSuccess: true }
    );
  } catch (err) {
    setWizardStatus("#wizard-index-status", err.message, "error");
  }
}

function jobRunningLabel(configName, kind) {
  const prefix = JOB_KIND_LABELS[kind] || JOB_KIND_LABELS.update;
  return `${prefix}: «${configName}»…`;
}

function setJobStatusText(_el, text) {
  const onConfigPage = $("#panel-configuration")?.classList.contains("active");
  const textEl = $(onConfigPage ? "#configuration-action-text" : "#configs-action-text");
  if (textEl) textEl.textContent = text;
}

function activeJobStatusContainer() {
  if ($("#panel-configuration")?.classList.contains("active")) {
    return $("#configuration-action-status");
  }
  return $("#configs-action-status");
}

function formatJobLogLine(line) {
  return String(line || "").replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, "");
}

function jobStatusMessage(job, configName, kind) {
  const lastLog = job.logs?.length ? job.logs[job.logs.length - 1] : "";
  if (job.status === "completed") {
    if (kind === "delete") {
      const count = job.stats?.objects_count ?? "?";
      return `Удалено: ${job.configuration_name || configName} (${count} объектов)`;
    }
    if (kind === "import") {
      return `Обновление из файлов завершено: ${job.configuration_name || configName}`;
    }
    return `Готово: ${job.configuration_name || configName}`;
  }
  if (job.status === "failed") {
    return `Ошибка: ${job.error || "неизвестная"}`;
  }
  if (job.progress?.message) {
    return formatJobLogLine(job.progress.message);
  }
  if (lastLog) {
    return formatJobLogLine(lastLog);
  }
  return jobRunningLabel(configName, kind);
}

function createJobStatusHandler(el, configName, kind) {
  return (job) => {
    if (job.status === "completed") {
      el.classList.remove("running");
      el.classList.add("completed");
      hideProgressBar();
    } else if (job.status === "failed") {
      el.classList.remove("running");
      el.classList.add("failed");
      hideProgressBar();
    } else {
      updateProgressBar(job);
    }
    setJobStatusText(el, jobStatusMessage(job, configName, kind));
  };
}

function resetJobLogView(jobId) {
  jobLogOffsets.set(jobId, 0);
  const out = $("#logs-output");
  if (out) {
    out.innerHTML = "";
    out.dataset.jobId = jobId;
  }
  $("#logs-truncated-hint")?.classList.add("hidden");
}

function showConfigJobStatus(jobId, configName, kind = "update", options = {}) {
  const { switchToLogs = true } = options;
  if (kind === "embed") {
    pendingConfigOps.embeds.set(configName, jobId);
  } else if (kind === "delete") {
    pendingConfigOps.deletes.set(configName, jobId);
  } else {
    pendingConfigOps.updates.set(configName, jobId);
  }
  const el = activeJobStatusContainer();
  el?.classList.remove("hidden", "completed", "failed");
  el?.classList.add("running");
  setJobStatusText(el, jobRunningLabel(configName, kind));
  resetJobLogView(jobId);
  if (switchToLogs) {
    showPanel("logs");
  }
  selectedJobId = jobId;
  pollJob(jobId, createJobStatusHandler(el, configName, kind));
  refreshJobs();
  applyConfigRowStates();
}

function resumeActiveJobs() {
  if (activeJobPoll) return;

  let jobId = null;
  let configName = null;
  let kind = null;

  if (pendingConfigOps.embeds.size) {
    [configName, jobId] = pendingConfigOps.embeds.entries().next().value;
    kind = "embed";
  } else if (pendingConfigOps.updates.size) {
    [configName, jobId] = pendingConfigOps.updates.entries().next().value;
    kind = "update";
  } else if (pendingConfigOps.deletes.size) {
    [configName, jobId] = pendingConfigOps.deletes.entries().next().value;
    kind = "delete";
  }

  if (!jobId || !configName || !kind) return;

  api(`/configurations/jobs/${jobId}`)
    .then((job) => {
      if (["import_zip", "import_path"].includes(job.type)) {
        kind = "import";
      } else if (job.type === "embed") {
        kind = "embed";
      } else if (job.type === "delete") {
        kind = "delete";
      } else if (job.type === "index" || job.type === "zip" || job.type === "path") {
        kind = job.type === "index" ? "update" : "full";
      }
      const el = activeJobStatusContainer();
      el?.classList.remove("hidden", "completed", "failed");
      el?.classList.add("running");
      setJobStatusText(el, jobRunningLabel(configName, kind));
      selectedJobId = jobId;
      resetJobLogView(jobId);
      pollJob(jobId, createJobStatusHandler(el, configName, kind));
      applyConfigRowStates();
    })
    .catch(() => {});
}

function showWizardJobStatus(jobId, configName) {
  showConfigJobStatus(jobId, configName, "full");
}

$("#btn-refresh-configs").addEventListener("click", loadConfigurations);

async function deleteConfig(name, triggerBtn) {
  if (!name) return;
  if (pendingConfigOps.deletes.has(name)) return;
  const config = configurations.find((c) => c.name === name);
  const slotOnly = config && !config.in_database;
  const confirmText = slotOnly
    ? `Удалить слот «${name}»?\nПапка выгрузки на диске будет удалена. Записи в базе нет.`
    : `Удалить конфигурацию «${name}» из базы?\nMarkdown и FAISS-индекс на диске также будут удалены.\n\nДля больших конфигураций удаление может занять несколько минут — прогресс будет на вкладке «Задачи».`;
  if (!confirm(confirmText)) {
    return;
  }
  const btn = triggerBtn || null;
  try {
    await withButtonLoading(
      btn,
      async () => {
        const data = await api(
          `/configurations/${encodeURIComponent(name)}?async_job=true`,
          { method: "DELETE" }
        );
        pendingConfigOps.deletes.set(name, data.job_id);
        showDeleteJobStatus(data.job_id, name);
      },
      { sustainOnSuccess: true }
    );
  } catch (err) {
    showDeleteError(err.message);
    alert(`Ошибка: ${err.message}`);
  }
}

function showDeleteJobStatus(jobId, name) {
  showConfigJobStatus(jobId, name, "delete");
}

function showDeleteError(message) {
  const el = activeJobStatusContainer();
  el?.classList.remove("hidden", "completed", "running");
  el?.classList.add("failed");
  hideProgressBar();
  setJobStatusText(el, `Ошибка: ${message}`);
  selectedJobId = null;
  $("#logs-title").textContent = "Лог сервера";
  $("#logs-output").innerHTML = "";
  delete $("#logs-output")?.dataset.jobId;
  logsSinceId = 0;
  showPanel("logs");
  refreshServerLogs();
}

function trimLogOutput(out) {
  const lines = out.querySelectorAll(".log-line");
  if (lines.length > MAX_LOG_DOM_LINES) {
    const removeCount = lines.length - MAX_LOG_DOM_LINES;
    for (let i = 0; i < removeCount; i++) {
      lines[i].remove();
    }
    $("#logs-truncated-hint")?.classList.remove("hidden");
  }
}

function appendJobLogs(job, reset = false) {
  const out = $("#logs-output");
  if (!out) return;
  const jobKey = job.id || selectedJobId;
  if (reset || out.dataset.jobId !== jobKey) {
    out.innerHTML = "";
    out.dataset.jobId = jobKey;
    jobLogOffsets.set(jobKey, 0);
    $("#logs-truncated-hint")?.classList.add("hidden");
  }
  const titleName = job.configuration_name || job.source || (jobKey || "").slice(0, 8);
  $("#logs-title").textContent = `Задача: ${titleName}`;
  const newLines = job.logs || [];
  const atBottom = out.scrollHeight - out.scrollTop <= out.clientHeight + 40;
  newLines.forEach((line) => {
    out.insertAdjacentHTML(
      "beforeend",
      `<span class="log-line info">${escapeHtml(line)}</span>\n`
    );
  });
  trimLogOutput(out);
  if (atBottom || reset) {
    out.scrollTop = out.scrollHeight;
  }
}

function pollJob(jobId, onUpdate) {
  if (activeJobPoll) clearInterval(activeJobPoll);
  if (!jobLogOffsets.has(jobId)) jobLogOffsets.set(jobId, 0);
  const tick = async () => {
    try {
      const offset = jobLogOffsets.get(jobId) || 0;
      const job = await api(`/configurations/jobs/${jobId}?since_log=${offset}`);
      jobLogOffsets.set(jobId, job.logs_total ?? offset + (job.logs?.length || 0));
      if (onUpdate) onUpdate(job);
      if (selectedJobId === jobId) {
        appendJobLogs(job, offset === 0 && !$("#logs-output")?.dataset.jobId);
      }
      if ($("#panel-configurations")?.classList.contains("active")) {
        await refreshPendingConfigOps();
        applyConfigRowStates();
      }
      if ($("#panel-configuration")?.classList.contains("active") && currentConfigurationCard?.name) {
        await refreshPendingConfigOps();
        updateConfigurationPageActions(currentConfigurationCard);
      }
      if (job.status === "completed" || job.status === "failed") {
        clearInterval(activeJobPoll);
        activeJobPoll = null;
        await refreshPendingConfigOps();
        refreshJobs();
        loadConfigurations();
        if ($("#panel-configuration")?.classList.contains("active") && currentConfigurationCard?.name) {
          await loadConfigurationPage(currentConfigurationCard.name);
        }
      }
    } catch (_) { /* ignore */ }
  };
  tick();
  activeJobPoll = setInterval(tick, 2000);
}

function applyConfigRowStates() {
  document.querySelectorAll("#configs-body tr[data-config-name]").forEach((row) => {
    const name = row.dataset.configName;
    const config = configurations.find((c) => c.name === name);
    if (!config) return;
    const actions = configActionStates(config);
    row.classList.toggle("config-row-busy", actions.busy);
  });
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
        (j) => {
          const statusLabel = JOB_STATUS_LABELS[j.status] || j.status;
          const typeLabel = JOB_TYPE_LABELS[j.type] || j.type;
          return `
      <li data-id="${j.id}" class="${j.id === selectedJobId ? "selected" : ""}">
        <div>${escapeHtml(j.configuration_name || j.source || j.id.slice(0, 8))}</div>
        <div class="job-type">${escapeHtml(typeLabel)} · ${escapeHtml(j.created_at?.slice(0, 19) || "")}</div>
        <span class="job-status-badge ${j.status}">${escapeHtml(statusLabel)}</span>
      </li>`;
        }
      )
      .join("");
    list.querySelectorAll("li[data-id]").forEach((li) => {
      li.addEventListener("click", async () => {
        selectedJobId = li.dataset.id;
        list.querySelectorAll("li").forEach((x) => x.classList.remove("selected"));
        li.classList.add("selected");
        resetJobLogView(selectedJobId);
        const job = await api(`/configurations/jobs/${selectedJobId}`);
        jobLogOffsets.set(selectedJobId, job.logs_total ?? job.logs?.length ?? 0);
        renderJobLogs(job);
      });
    });
  } catch (err) {
    list.innerHTML = `<li class="muted">Ошибка: ${escapeHtml(err.message)}</li>`;
  }
}

$("#btn-refresh-jobs").addEventListener("click", refreshJobs);

function renderJobLogs(job) {
  appendJobLogs(job, true);
  if (job.id) {
    jobLogOffsets.set(job.id, job.logs_total ?? job.logs?.length ?? 0);
  }
  updateProgressBar(job);
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
    resetJobLogView(selectedJobId);
    const job = await api(`/configurations/jobs/${selectedJobId}`);
    jobLogOffsets.set(selectedJobId, job.logs_total ?? job.logs?.length ?? 0);
    renderJobLogs(job);
  } else {
    logsSinceId = 0;
    $("#logs-output").innerHTML = "";
    delete $("#logs-output")?.dataset.jobId;
    await refreshServerLogs();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && selectedJobId) {
    selectedJobId = null;
    $("#logs-title").textContent = "Лог сервера";
    $("#logs-output").innerHTML = "";
    delete $("#logs-output")?.dataset.jobId;
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

function boot() {
  setupWizard();
  initRouting();
}

boot();
