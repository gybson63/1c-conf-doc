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

function on(selector, event, handler) {
  const el = $(selector);
  if (el) el.addEventListener(event, handler);
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
      } else if (["index", "reindex", "path", "zip"].includes(job.type)) {
        const name = job.configuration_name;
        if (name) pendingConfigOps.updates.set(name, job.id);
      }
    }
  } catch (_) {
    /* keep previous pending state on transient errors */
  }
}

async function startConfigurationUpdate(name) {
  try {
    const data = await api(`/configurations/${encodeURIComponent(name)}/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skip_embeddings: true, force: false }),
    });
    showConfigJobStatus(data.job_id, name, "update");
    loadConfigurations();
  } catch (err) {
    showConfigActionError(err.message);
  }
}

async function startConfigurationReindex(name) {
  try {
    const data = await api(`/configurations/${encodeURIComponent(name)}/embed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: false }),
    });
    showConfigJobStatus(data.job_id, name, "embed");
    loadConfigurations();
  } catch (err) {
    showConfigActionError(err.message);
  }
}

function showConfigActionError(message) {
  const el = $("#configs-action-status");
  el.classList.remove("hidden", "completed", "running");
  el.classList.add("failed");
  el.textContent = message;
}

function configActionStates(config) {
  const deleting = pendingConfigOps.deletes.has(config.name);
  const updating = pendingConfigOps.updates.has(config.name);
  const embedding = pendingConfigOps.embeds.has(config.name);
  const busy = deleting || updating || embedding;
  const canUpdate = config.has_export;
  const canReindex = config.in_database && config.has_export;
  const busyHint = embedding
    ? "Идёт переиндексация — дождитесь завершения"
    : updating
      ? "Идёт обновление — дождитесь завершения"
      : deleting
        ? "Идёт удаление — дождитесь завершения"
        : "";
  return {
    busy,
    busyHint,
    deleteDisabled: busy,
    deleteLabel: deleting ? "Удаление…" : config.in_database ? "Удалить" : "Удалить слот",
    updateDisabled: busy || !canUpdate,
    updateLabel: updating ? "Обновление…" : "Обновить",
    updateHint: !canUpdate ? "Нет выгрузки в слоте" : busyHint,
    reindexDisabled: busy || !canReindex,
    reindexLabel: embedding ? "Переиндексация…" : "Переиндексировать",
    reindexHint: !canReindex ? "Сначала обновите метаданные" : busyHint,
  };
}

function exportStatusLabel(config) {
  if (config.slot_status === "invalid") {
    return '<span class="warn-text">битая выгрузка</span>';
  }
  if (config.has_export && config.export_linked) {
    return '<span class="ok-text" title="Читает из staging без копирования">staging</span>';
  }
  if (config.has_export) return '<span class="ok-text">в слоте</span>';
  if (config.in_database) return '<span class="warn-text">нет в слоте</span>';
  return '<span class="warn-text">нет выгрузки</span>';
}

function indexStatusLabel(config) {
  if (!config.in_database) return "не индексировалась";
  if (!config.has_export && config.slot_status !== "ready") {
    return "индекс без слота";
  }
  if (!config.in_database || !config.indexed_at) return "готов к индексации";
  return escapeHtml(config.indexed_at);
}

function embeddingStatusLabel(config) {
  const model = config.embedding_model;
  const provider = config.embeddings_provider || "";
  const custom = config.embeddings_custom ? "" : " (дефолт)";
  if (config.embedding_status === "ready") {
    return '<span class="muted">настроить при индексации</span>';
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
        const updateDisabled = actions.updateDisabled ? " disabled" : "";
        const reindexDisabled = actions.reindexDisabled ? " disabled" : "";
        const deleteDisabled = actions.deleteDisabled ? " disabled" : "";
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
          <div class="btn-group">
            <button type="button" class="btn secondary btn-config-update" data-name="${escapeHtml(c.name)}"${updateDisabled} title="${escapeHtml(actions.updateHint || "Парсинг XML и чанки без эмбеддингов")}">${actions.updateLabel}</button>
            <button type="button" class="btn secondary btn-config-reindex" data-name="${escapeHtml(c.name)}"${reindexDisabled} title="${escapeHtml(actions.reindexHint || "Эмбеддинги и FAISS по чанкам в базе")}">${actions.reindexLabel}</button>
            <button type="button" class="btn danger btn-delete" data-name="${escapeHtml(c.name)}"${deleteDisabled} title="${escapeHtml(actions.busyHint || "")}">${actions.deleteLabel}</button>
          </div>
        </td>
      </tr>`;
      })
      .join("");
    tbody.querySelectorAll(".btn-config-update").forEach((btn) => {
      btn.addEventListener("click", () => startConfigurationUpdate(btn.dataset.name));
    });
    tbody.querySelectorAll(".btn-config-reindex").forEach((btn) => {
      btn.addEventListener("click", () => startConfigurationReindex(btn.dataset.name));
    });
    tbody.querySelectorAll(".btn-delete").forEach((btn) => {
      btn.addEventListener("click", () => deleteConfig(btn.dataset.name, btn));
    });
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

async function openWizard(name) {
  clearWizardStatuses();
  wizardZipFile = null;
  $("#wizard-input-zip").value = "";
  $("#wizard-zip-filename").textContent = "";
  const overlay = $("#wizard-overlay");
  overlay?.classList.remove("hidden");
  overlay?.setAttribute("aria-hidden", "false");

  if (name) {
    $("#wizard-config-name").value = name;
    $("#wizard-config-name").readOnly = true;
    $("#wizard-title").textContent = `Обновить: ${name}`;
    try {
      const card = await api(`/configurations/${encodeURIComponent(name)}`);
      $("#wizard-slot-path").textContent = card.export_slot_path || "";
      $("#wizard-slot-hint").textContent = card.has_export
        ? card.export_linked
          ? "Слот привязан к staging-пути. Можно заменить ZIP/путём или сразу проверить и индексировать."
          : "Выгрузка в слоте. Можно заменить ZIP/путём или сразу проверить и индексировать."
        : "Слот пуст — импортируйте выгрузку.";
      await loadWizardEmbeddings(name);
    } catch (err) {
      setWizardStatus("#wizard-import-status", err.message, "error");
    }
  } else {
    $("#wizard-config-name").value = "";
    $("#wizard-config-name").readOnly = false;
    $("#wizard-title").textContent = "Новая конфигурация";
    $("#wizard-slot-path").textContent = "output/exports/…";
    $("#wizard-slot-hint").textContent =
      "Укажите путь к выгрузке или ZIP — имя подставится из Configuration.xml.";
  }
  $("#wizard-source-path").value = "";
}

function closeWizard() {
  const overlay = $("#wizard-overlay");
  overlay?.classList.add("hidden");
  overlay?.setAttribute("aria-hidden", "true");
}

function setupWizard() {
  on("#btn-new-configuration", "click", () => openWizard(null));
  on("#btn-wizard-close", "click", closeWizard);
  on("#wizard-overlay", "click", (e) => {
    if (e.target?.id === "wizard-overlay") closeWizard();
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
  });

  on("#btn-wizard-import-zip", "click", wizardImportZip);
  on("#btn-wizard-import-path", "click", wizardImportPath);
  on("#btn-wizard-detect", "click", wizardDetect);
  on("#btn-wizard-test-embeddings", "click", wizardTestEmbeddings);
  on("#btn-wizard-index", "click", wizardStartIndex);
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
  try {
    const name = await wizardConfigName();
    const form = new FormData();
    form.append("file", wizardZipFile);
    const data = await api(`/configurations/${encodeURIComponent(name)}/import`, {
      method: "POST",
      body: form,
    });
    $("#wizard-config-name").value = data.detected_name || name;
    if (data.detected_name && data.detected_name !== name) {
      setWizardStatus(
        "#wizard-import-status",
        `Импорт OK, но имя в XML «${data.detected_name}» ≠ слот «${name}»`,
        "error"
      );
      return;
    }
    setWizardStatus("#wizard-import-status", `Импортировано в слот «${name}»`, "ok");
    await loadWizardEmbeddings(name);
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
  const prevLabel = btn?.textContent || "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = mirror ? "Копирование…" : "Привязка…";
  }
  try {
    if (!$("#wizard-config-name").value.trim()) {
      await wizardDetectFromSourcePath(source, { quiet: true });
    }
    const name = await wizardConfigName();
    const data = await api(`/configurations/${encodeURIComponent(name)}/import-path`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, mirror }),
    });
    if (data.detected_name && data.detected_name !== name) {
      setWizardStatus(
        "#wizard-import-status",
        `${mirror ? "Скопировано" : "Привязано"}, но XML «${data.detected_name}» ≠ слот «${name}»`,
        "error"
      );
      return;
    }
    setWizardStatus(
      "#wizard-import-status",
      mirror ? `Скопировано в слот «${name}»` : `Путь привязан к слоту «${name}»`,
      "ok"
    );
    await loadWizardEmbeddings(name);
  } catch (err) {
    setWizardStatus("#wizard-import-status", err.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prevLabel || "Привязать путь к слоту";
    }
  }
}

async function wizardDetect() {
  try {
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
  } catch (err) {
    setWizardStatus("#wizard-detect-status", err.message, "error");
  }
}

async function wizardTestEmbeddings() {
  try {
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
  } catch (err) {
    setWizardStatus("#wizard-embeddings-status", err.message, "error");
  }
}

async function wizardStartIndex() {
  try {
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
    closeWizard();
    showWizardJobStatus(data.job_id, name);
  } catch (err) {
    setWizardStatus("#wizard-index-status", err.message, "error");
  }
}

function jobRunningLabel(configName, kind) {
  const labels = {
    update: `Обновление «${configName}»…`,
    embed: `Переиндексация «${configName}»…`,
    delete: `Удаление «${configName}»…`,
    full: `Индексация «${configName}»…`,
  };
  return labels[kind] || labels.update;
}

function formatJobLogLine(line) {
  return String(line || "").replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, "");
}

function createJobStatusHandler(el, configName, kind) {
  return (job) => {
    const lastLog = job.logs?.length ? job.logs[job.logs.length - 1] : "";
    if (job.status === "completed") {
      el.classList.remove("running");
      el.classList.add("completed");
      if (kind === "delete") {
        const count = job.stats?.objects_count ?? "?";
        el.textContent = `Удалено: ${job.configuration_name || configName} (${count} объектов)`;
      } else {
        el.textContent = `Готово: ${job.configuration_name || configName}`;
      }
    } else if (job.status === "failed") {
      el.classList.remove("running");
      el.classList.add("failed");
      el.textContent = `Ошибка: ${job.error || "неизвестная"}`;
    } else if (lastLog) {
      el.textContent = formatJobLogLine(lastLog);
    } else {
      el.textContent = jobRunningLabel(configName, kind);
    }
  };
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
  const el = $("#configs-action-status");
  el.classList.remove("hidden", "completed", "failed");
  el.classList.add("running");
  el.textContent = jobRunningLabel(configName, kind);
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

  const el = $("#configs-action-status");
  el.classList.remove("hidden", "completed", "failed");
  el.classList.add("running");
  el.textContent = jobRunningLabel(configName, kind);
  selectedJobId = jobId;
  pollJob(jobId, createJobStatusHandler(el, configName, kind));
  applyConfigRowStates();
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
    : `Удалить конфигурацию «${name}» из базы?\nMarkdown и FAISS-индекс на диске также будут удалены.\n\nДля больших конфигураций удаление может занять несколько минут — прогресс будет во вкладке «Логи».`;
  if (!confirm(confirmText)) {
    return;
  }
  const btn = triggerBtn || null;
  const prevLabel = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Запуск…";
  }
  try {
    const data = await api(
      `/configurations/${encodeURIComponent(name)}?async_job=true`,
      { method: "DELETE" }
    );
    pendingConfigOps.deletes.set(name, data.job_id);
    showDeleteJobStatus(data.job_id, name);
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prevLabel || "Удалить";
    }
    showDeleteError(err.message);
    alert(`Ошибка: ${err.message}`);
  }
}

function showDeleteJobStatus(jobId, name) {
  showConfigJobStatus(jobId, name, "delete");
}

function showDeleteError(message) {
  const el = $("#configs-action-status");
  el.classList.remove("hidden", "completed", "running");
  el.classList.add("failed");
  el.textContent = `Ошибка: ${message}`;
  selectedJobId = null;
  $("#logs-title").textContent = "Лог сервера";
  $("#logs-output").innerHTML = "";
  logsSinceId = 0;
  showPanel("logs");
  refreshServerLogs();
}

function pollJob(jobId, onUpdate) {
  if (activeJobPoll) clearInterval(activeJobPoll);
  const tick = async () => {
    try {
      const job = await api(`/configurations/jobs/${jobId}`);
      if (onUpdate) onUpdate(job);
      if (selectedJobId === jobId) renderJobLogs(job);
      if ($("#panel-configurations").classList.contains("active")) {
        await refreshPendingConfigOps();
        applyConfigRowStates();
      }
      if (job.status === "completed" || job.status === "failed") {
        clearInterval(activeJobPoll);
        activeJobPoll = null;
        await refreshPendingConfigOps();
        refreshJobs();
        loadConfigurations();
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
    const updateBtn = row.querySelector(".btn-config-update");
    const reindexBtn = row.querySelector(".btn-config-reindex");
    const deleteBtn = row.querySelector(".btn-delete");
    if (updateBtn) {
      updateBtn.disabled = actions.updateDisabled;
      updateBtn.textContent = actions.updateLabel;
      updateBtn.title = actions.updateHint || "Парсинг XML и чанки без эмбеддингов";
    }
    if (reindexBtn) {
      reindexBtn.disabled = actions.reindexDisabled;
      reindexBtn.textContent = actions.reindexLabel;
      reindexBtn.title = actions.reindexHint || "Эмбеддинги и FAISS по чанкам в базе";
    }
    if (deleteBtn) {
      deleteBtn.disabled = actions.deleteDisabled;
      deleteBtn.textContent = actions.deleteLabel;
      deleteBtn.title = actions.busyHint || "";
    }
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

function boot() {
  setupWizard();
  initRouting();
}

boot();
