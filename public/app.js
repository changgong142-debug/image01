const FILE_SIZE_LIMIT = 25 * 1024 * 1024; // 25 MB
const ACCEPTED_MIME_PREFIX = "image/";
const ACCEPTED_EXTENSIONS = [
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
  ".bmp",
  ".tiff",
  ".tif",
  ".svg",
  ".heic",
  ".heif",
];

const endpoints = {
  upload: "/api/uploads",
  status: "/api/uploads/status",
  process: "/api/process",
  processSingle: (id) => `/api/process/${encodeURIComponent(id)}`,
  downloadOriginal: (id) => `/api/uploads/${encodeURIComponent(id)}/original`,
  downloadProcessed: (id) => `/api/uploads/${encodeURIComponent(id)}/processed`,
  downloadZip: (ids) => `/api/downloads/batch?ids=${ids.map((id) => encodeURIComponent(id)).join(",")}`,
};

const STATUS_LABELS = {
  queued: "Waiting to upload",
  uploading: "Uploading",
  uploaded: "Ready for processing",
  processing: "Processing",
  processed: "Processed",
  failed: "Action required",
};

const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const processAllBtn = document.getElementById("processAllBtn");
const downloadZipBtn = document.getElementById("downloadZipBtn");
const fileListEl = document.getElementById("fileList");
const emptyMessageEl = document.querySelector("[data-empty-message]");
const template = document.getElementById("fileItemTemplate");
const liveRegion = document.getElementById("liveRegion");
const toastRegion = document.getElementById("toastRegion");
const alertRegion = document.getElementById("alertRegion");

const state = {
  items: [],
  pollTimer: null,
  batchDownloadUrl: null,
};

let pollErrorNotified = false;

function init() {
  setupEventListeners();
  setAlert();
  renderQueue();
}

function setupEventListeners() {
  if (dropZone) {
    ["dragenter", "dragover"].forEach((type) => {
      dropZone.addEventListener(type, (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropZone.classList.add("is-dragover");
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "copy";
        }
      });
    });

    ["dragleave", "dragend"].forEach((type) => {
      dropZone.addEventListener(type, (event) => {
        if (event.relatedTarget && dropZone.contains(event.relatedTarget)) {
          return;
        }
        dropZone.classList.remove("is-dragover");
      });
    });

    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragover");
      const files = event.dataTransfer?.files;
      if (files?.length) {
        handleFileSelection(files);
      }
    });

    dropZone.addEventListener("click", (event) => {
      if (event.target && event.target.closest("[data-action=\"browse\"]")) {
        fileInput?.click();
        return;
      }
      if (event.currentTarget === dropZone) {
        fileInput?.click();
      }
    });

    dropZone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInput?.click();
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      const files = fileInput.files;
      if (files?.length) {
        handleFileSelection(files);
      }
      fileInput.value = "";
    });
  }

  if (processAllBtn) {
    processAllBtn.addEventListener("click", () => {
      const readyItems = state.items.filter(canRequestProcessing);
      if (!readyItems.length) {
        const warningMessage = "There are no files ready to process yet.";
        showToast(warningMessage, "warning");
        setAlert(warningMessage, "warning");
        return;
      }
      const ids = readyItems.map((item) => item.serverId);
      requestProcessing(ids);
    });
  }

  if (downloadZipBtn) {
    downloadZipBtn.addEventListener("click", (event) => {
      event.preventDefault();
      if (downloadZipBtn.disabled) {
        const warningMessage = "Batch download will be available after processing completes.";
        showToast(warningMessage, "warning");
        setAlert(warningMessage, "warning");
        return;
      }
      const processedItems = state.items.filter((item) => item.status === "processed" && item.serverId);
      if (!processedItems.length && !state.batchDownloadUrl) {
        const warningMessage = "Processed files are not available for download yet.";
        showToast(warningMessage, "warning");
        setAlert(warningMessage, "warning");
        return;
      }
      const url = state.batchDownloadUrl || endpoints.downloadZip(processedItems.map((item) => item.serverId));
      window.location.assign(url);
      announce("Batch download started");
    });
  }

  if (fileListEl) {
    fileListEl.addEventListener("click", (event) => {
      const processButton = event.target.closest("[data-action=\"process-one\"]");
      if (processButton) {
        const clientId = processButton.dataset.clientId;
        const item = state.items.find((entry) => entry.clientId === clientId);
        if (!item) {
          return;
        }
        if (!canRequestProcessing(item)) {
          const warningMessage = "This file is still uploading or has already been processed.";
          showToast(warningMessage, "warning");
          setAlert(warningMessage, "warning");
          return;
        }
        requestProcessing([item.serverId], { itemName: item.name });
      }
    });
  }

  window.addEventListener("beforeunload", () => {
    state.items.forEach((item) => {
      if (item.originalPreviewUrl && item.originalPreviewUrl.startsWith("blob:")) {
        URL.revokeObjectURL(item.originalPreviewUrl);
      }
      if (item.processedPreviewUrl && item.processedPreviewUrl.startsWith("blob:")) {
        URL.revokeObjectURL(item.processedPreviewUrl);
      }
    });
  });
}

function handleFileSelection(fileList) {
  const files = Array.from(fileList);
  const acceptedFiles = files.filter((file) => {
    const validation = validateFile(file);
    if (!validation.valid) {
      showToast(validation.message, "warning");
      return false;
    }

    if (isDuplicateFile(file)) {
      showToast(`${file.name} is already in the queue.`, "warning");
      return false;
    }

    return true;
  });

  if (!acceptedFiles.length) {
    return;
  }

  acceptedFiles.forEach(queueFile);
  setAlert(`${acceptedFiles.length} ${acceptedFiles.length === 1 ? "file" : "files"} added to the queue.`, "info");
}

function queueFile(file) {
  const clientId = generateClientId();
  const previewUrl = window.URL?.createObjectURL ? URL.createObjectURL(file) : null;
  const item = {
    clientId,
    name: file.name,
    size: file.size,
    lastModified: file.lastModified,
    status: "queued",
    progress: 0,
    file,
    originalPreviewUrl: previewUrl,
    originalUrl: null,
    processedPreviewUrl: null,
    createdAt: Date.now(),
    message: "",
    serverId: null,
    processedUrl: null,
    downloadOriginalUrl: null,
    downloadProcessedUrl: null,
  };

  state.items.push(item);
  state.batchDownloadUrl = null;
  renderQueue();
  uploadFile(item);
}

async function uploadFile(item) {
  if (!item?.file) {
    return;
  }

  item.status = "uploading";
  item.progress = 0;
  item.message = "";
  renderQueue();

  const formData = new FormData();
  formData.append("file", item.file, item.name);

  try {
    const response = await fetch(endpoints.upload, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorText = (await response.text()) || "Upload failed";
      throw new Error(errorText);
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    const identifier =
      payload?.id || payload?.uploadId || payload?.uuid || payload?.fileId || payload?.identifier || item.serverId || item.clientId;
    item.serverId = identifier;
    item.status = normaliseStatus(payload?.status || payload?.state) || "uploaded";
    item.progress = payload?.progress !== undefined ? normaliseProgress(payload.progress) : 100;
    item.originalUrl = payload?.originalUrl || payload?.sourceUrl || item.originalUrl;
    item.downloadOriginalUrl = payload?.downloadOriginalUrl || payload?.originalDownloadUrl || item.downloadOriginalUrl;
    item.processedUrl = payload?.processedUrl || payload?.resultUrl || item.processedUrl;
    item.downloadProcessedUrl = payload?.processedDownloadUrl || payload?.downloadUrl || item.downloadProcessedUrl;
    item.message = payload?.message || "";
    item.file = null;

    if (item.status === "processed") {
      item.progress = 100;
    }

    ensurePolling();
    renderQueue();
    const successMessage = `${item.name} uploaded successfully.`;
    showToast(successMessage, "success");
    setAlert(successMessage, "success");
  } catch (error) {
    item.status = "failed";
    item.progress = 0;
    item.message = error?.message || "Upload failed";
    renderQueue();
    const errorMessage = `Unable to upload ${item.name}: ${item.message}`;
    showToast(errorMessage, "error");
    setAlert(errorMessage, "error");
  }
}

async function requestProcessing(ids, { itemName } = {}) {
  if (!ids?.length) {
    return;
  }

  const snapshots = ids
    .map((id) => {
      const entry = state.items.find((item) => item.serverId === id);
      return entry
        ? {
            item: entry,
            status: entry.status,
            message: entry.message,
          }
        : null;
    })
    .filter(Boolean);

  snapshots.forEach(({ item }) => {
    item.status = "processing";
    item.message = "";
    if (item.progress < 5) {
      item.progress = 5;
    }
  });

  renderQueue();
  ensurePolling();

  try {
    const response = await fetch(endpoints.process, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ ids }),
    });

    if (!response.ok) {
      const errorText = (await response.text()) || "Unable to start processing";
      throw new Error(errorText);
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (payload?.zipUrl) {
      state.batchDownloadUrl = payload.zipUrl;
    }

    let messageText;
    if (payload?.message) {
      messageText = payload.message;
    } else if (ids.length === 1) {
      messageText = `Processing started for ${itemName || "selected file"}.`;
    } else {
      messageText = `Processing started for ${ids.length} files.`;
    }

    showToast(messageText, "success");
    setAlert(messageText, "success");
  } catch (error) {
    snapshots.forEach(({ item, status, message }) => {
      item.status = status;
      item.message = message;
    });
    renderQueue();
    const errorMessage = error?.message || "Unable to start processing.";
    showToast(errorMessage, "error");
    setAlert(errorMessage, "error");
  }
}

function renderQueue() {
  if (!fileListEl || !template) {
    return;
  }

  const fragment = document.createDocumentFragment();
  state.items
    .slice()
    .sort((a, b) => a.createdAt - b.createdAt)
    .forEach((item) => {
      const element = renderQueueItem(item);
      if (element) {
        fragment.appendChild(element);
      }
    });

  fileListEl.innerHTML = "";
  fileListEl.appendChild(fragment);

  if (emptyMessageEl) {
    emptyMessageEl.hidden = state.items.length > 0;
  }

  updateControlStates();
}

function renderQueueItem(item) {
  const fragment = template.content.cloneNode(true);
  const li = fragment.querySelector(".file-item");
  if (!li) {
    return null;
  }

  li.dataset.clientId = item.clientId;
  li.dataset.status = item.status;

  const nameEl = fragment.querySelector(".file-name");
  if (nameEl) {
    nameEl.textContent = item.name;
  }

  const sizeEl = fragment.querySelector(".file-size");
  if (sizeEl) {
    sizeEl.textContent = formatFileSize(item.size);
  }

  const originalMedia = fragment.querySelector('[data-role="original-thumb"]');
  const originalImg = originalMedia?.querySelector("img");
  const originalUrl = item.originalUrl || item.originalPreviewUrl;
  if (originalMedia && originalImg) {
    if (originalUrl) {
      originalImg.src = originalUrl;
      originalImg.alt = `Original preview for ${item.name}`;
      originalMedia.classList.add("has-image");
    } else {
      originalImg.removeAttribute("src");
      originalImg.alt = `Original preview not available for ${item.name}`;
      originalMedia.classList.remove("has-image");
    }
  }

  const processedMedia = fragment.querySelector('[data-role="processed-thumb"]');
  const processedImg = processedMedia?.querySelector("img");
  const processedUrl = item.processedUrl || item.processedPreviewUrl || "";
  if (processedMedia && processedImg) {
    if (processedUrl) {
      processedImg.src = processedUrl;
      processedImg.alt = `Processed preview for ${item.name}`;
      processedMedia.classList.add("has-image");
    } else {
      processedImg.removeAttribute("src");
      processedImg.alt = `Processed preview not yet available for ${item.name}`;
      processedMedia.classList.remove("has-image");
    }
  }

  const progressEl = fragment.querySelector(".file-progress");
  if (progressEl) {
    const value = Math.min(100, Math.max(0, Math.round(item.progress ?? 0)));
    progressEl.value = value;
    progressEl.setAttribute("aria-valuemin", "0");
    progressEl.setAttribute("aria-valuemax", "100");
    progressEl.setAttribute("aria-valuenow", String(value));
    progressEl.setAttribute("aria-valuetext", `${value}%`);
    progressEl.setAttribute("aria-label", `Progress for ${item.name}`);
  }

  const statusEl = fragment.querySelector(".file-status");
  if (statusEl) {
    const label = STATUS_LABELS[item.status] || item.status || "Status unknown";
    statusEl.textContent = item.message ? `${label}. ${item.message}` : label;
  }

  const processButton = fragment.querySelector('[data-action="process-one"]');
  if (processButton) {
    processButton.dataset.clientId = item.clientId;
    const canProcess = canRequestProcessing(item);
    processButton.disabled = !canProcess;
    processButton.setAttribute("aria-disabled", String(!canProcess));
    processButton.textContent = item.status === "processing" ? "Processing…" : "Process";
  }

  const originalLink = fragment.querySelector('[data-role="download-original"]');
  if (originalLink) {
    const downloadUrl = item.downloadOriginalUrl || (item.serverId ? endpoints.downloadOriginal(item.serverId) : originalUrl);
    if (downloadUrl) {
      originalLink.href = downloadUrl;
      originalLink.download = item.name;
      originalLink.hidden = false;
    } else {
      originalLink.hidden = true;
    }
  }

  const processedLink = fragment.querySelector('[data-role="download-processed"]');
  if (processedLink) {
    const processedDownloadUrl = item.downloadProcessedUrl || item.processedUrl;
    if (item.status === "processed" && processedDownloadUrl) {
      processedLink.href = processedDownloadUrl;
      processedLink.download = buildProcessedFilename(item.name);
      processedLink.hidden = false;
    } else {
      processedLink.hidden = true;
    }
  }

  return li;
}

function updateControlStates() {
  if (processAllBtn) {
    const canProcess = state.items.some(canRequestProcessing);
    processAllBtn.disabled = !canProcess;
    processAllBtn.setAttribute("aria-disabled", String(!canProcess));
  }

  if (downloadZipBtn) {
    const allProcessed = state.items.length > 0 && state.items.every((item) => item.status === "processed");
    const hasZipUrl = Boolean(state.batchDownloadUrl);
    const isReady = allProcessed || hasZipUrl;
    downloadZipBtn.disabled = !isReady;
    downloadZipBtn.setAttribute("aria-disabled", String(!isReady));
  }
}

function ensurePolling() {
  if (state.pollTimer) {
    return;
  }
  if (!state.items.some(shouldPoll)) {
    return;
  }
  pollStatuses();
  state.pollTimer = window.setInterval(pollStatuses, 2500);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  pollErrorNotified = false;
}

async function pollStatuses() {
  const ids = state.items.filter(shouldPoll).map((item) => item.serverId);
  if (!ids.length) {
    stopPolling();
    return;
  }

  const url = `${endpoints.status}?ids=${ids.map((id) => encodeURIComponent(id)).join(",")}`;

  try {
    const response = await fetch(url, {
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`Status request failed (${response.status})`);
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    pollErrorNotified = false;

    const updates = normaliseStatusPayload(payload);
    let latestZipUrl = null;

    updates.forEach((entry) => {
      const identifier =
        entry?.id || entry?.uploadId || entry?.uuid || entry?.fileId || entry?.identifier;

      if (!identifier) {
        return;
      }

      const item = state.items.find((candidate) => candidate.serverId === identifier || candidate.clientId === identifier);
      if (!item) {
        return;
      }

      if (!item.serverId) {
        item.serverId = identifier;
      }

      updateItemFromServer(item, entry);

      if (entry?.zipUrl) {
        latestZipUrl = entry.zipUrl;
      }
    });

    if (payload?.zipUrl) {
      latestZipUrl = payload.zipUrl;
    }

    if (latestZipUrl) {
      state.batchDownloadUrl = latestZipUrl;
    }

    if (!state.items.some(shouldPoll)) {
      stopPolling();
    }

    renderQueue();
    if (alertRegion?.dataset.variant === "warning") {
      setAlert();
    }
  } catch (error) {
    if (!pollErrorNotified) {
      const warningMessage = `Unable to refresh file status: ${error.message}`;
      showToast(warningMessage, "warning");
      setAlert(warningMessage, "warning");
      pollErrorNotified = true;
    }
  }
}

function normaliseStatusPayload(payload) {
  if (!payload) {
    return [];
  }
  if (Array.isArray(payload)) {
    return payload;
  }
  if (Array.isArray(payload.items)) {
    return payload.items;
  }
  if (Array.isArray(payload.data)) {
    return payload.data;
  }
  if (payload.result && Array.isArray(payload.result)) {
    return payload.result;
  }
  return [payload];
}

function updateItemFromServer(item, payload) {
  if (!payload || !item) {
    return;
  }

  const nextStatus = normaliseStatus(payload.status || payload.state || payload.stage);
  if (nextStatus) {
    item.status = nextStatus;
  }

  if (typeof payload.progress === "number") {
    item.progress = normaliseProgress(payload.progress);
  } else if (typeof payload.percentage === "number") {
    item.progress = normaliseProgress(payload.percentage);
  }

  if (payload.originalUrl || payload.sourceUrl || payload.thumbnailUrl) {
    item.originalUrl = payload.originalUrl || payload.sourceUrl || payload.thumbnailUrl;
  }

  if (payload.processedUrl || payload.resultUrl || payload.previewUrl) {
    item.processedUrl = payload.processedUrl || payload.resultUrl || payload.previewUrl;
  }

  if (payload.processedPreviewUrl) {
    item.processedPreviewUrl = payload.processedPreviewUrl;
    if (!item.processedUrl) {
      item.processedUrl = payload.processedPreviewUrl;
    }
  }

  if (payload.downloadOriginalUrl || payload.originalDownloadUrl) {
    item.downloadOriginalUrl = payload.downloadOriginalUrl || payload.originalDownloadUrl;
  }

  if (payload.downloadProcessedUrl || payload.downloadUrl || payload.resultDownloadUrl) {
    item.downloadProcessedUrl = payload.downloadProcessedUrl || payload.downloadUrl || payload.resultDownloadUrl;
  }

  if (Array.isArray(payload.errors) && payload.errors.length) {
    item.status = "failed";
    item.message = payload.errors.join(" ");
  } else if (payload.error) {
    item.status = "failed";
    item.message = payload.error;
  } else if (payload.message) {
    item.message = payload.message;
  }

  if (item.status === "processed") {
    item.progress = 100;
    if (item.originalPreviewUrl && item.originalPreviewUrl.startsWith("blob:") && item.originalUrl && item.originalUrl !== item.originalPreviewUrl) {
      URL.revokeObjectURL(item.originalPreviewUrl);
      item.originalPreviewUrl = null;
    }
  }
}

function canRequestProcessing(item) {
  return Boolean(item?.serverId) && (item.status === "uploaded" || item.status === "failed");
}

function shouldPoll(item) {
  return Boolean(item?.serverId) && ["uploading", "uploaded", "processing"].includes(item.status);
}

function validateFile(file) {
  if (!file) {
    return { valid: false, message: "Invalid file." };
  }

  if (file.size > FILE_SIZE_LIMIT) {
    return {
      valid: false,
      message: `${file.name} exceeds the 25 MB size limit.`,
    };
  }

  const mimeValid = !file.type || file.type.startsWith(ACCEPTED_MIME_PREFIX);
  const extensionValid = ACCEPTED_EXTENSIONS.some((extension) => file.name.toLowerCase().endsWith(extension));

  if (!mimeValid && !extensionValid) {
    return {
      valid: false,
      message: `${file.name} is not a supported image format.`,
    };
  }

  return { valid: true };
}

function isDuplicateFile(file) {
  return state.items.some(
    (item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified
  );
}

function formatFileSize(size) {
  if (!Number.isFinite(size)) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unit = units.shift();
  while (value >= 1024 && units.length) {
    value /= 1024;
    unit = units.shift();
  }
  return `${value.toFixed(value >= 10 || unit === "B" ? 0 : 1)} ${unit}`;
}

function generateClientId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `client-${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
}

function normaliseStatus(value) {
  if (!value) {
    return null;
  }
  const normalised = value.toString().toLowerCase();
  switch (normalised) {
    case "queued":
    case "waiting":
    case "pending":
      return "uploaded";
    case "uploading":
      return "uploading";
    case "uploaded":
    case "ready":
      return "uploaded";
    case "processing":
    case "in_progress":
      return "processing";
    case "processed":
    case "completed":
    case "complete":
    case "success":
    case "done":
      return "processed";
    case "failed":
    case "error":
    case "errored":
      return "failed";
    default:
      return normalised;
  }
}

function normaliseProgress(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }
  if (value <= 1) {
    return Math.round(value * 100);
  }
  return Math.round(value);
}

function buildProcessedFilename(name) {
  if (!name) {
    return "processed";
  }
  const dotIndex = name.lastIndexOf(".");
  if (dotIndex === -1) {
    return `${name}-processed`;
  }
  const base = name.slice(0, dotIndex);
  const extension = name.slice(dotIndex);
  return `${base}-processed${extension}`;
}

function showToast(message, variant = "info") {
  if (!toastRegion || !message) {
    return;
  }

  const toast = document.createElement("div");
  toast.className = `toast toast--${variant}`;
  toast.setAttribute("role", "alert");

  const text = document.createElement("p");
  text.className = "toast__message";
  text.textContent = message;
  toast.appendChild(text);

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "toast__close";
  closeButton.setAttribute("aria-label", "Dismiss notification");
  closeButton.innerHTML = "&times;";
  toast.appendChild(closeButton);

  toastRegion.appendChild(toast);

  requestAnimationFrame(() => {
    toast.classList.add("is-active");
  });

  const removeToast = () => {
    toast.classList.add("is-leaving");
    setTimeout(() => {
      toast.remove();
    }, 200);
  };

  const timeoutId = window.setTimeout(removeToast, 6000);
  closeButton.addEventListener("click", () => {
    window.clearTimeout(timeoutId);
    removeToast();
  });

  announce(message);
}

function setAlert(message = "", variant = "info") {
  if (!alertRegion) {
    return;
  }
  if (!message) {
    alertRegion.textContent = "";
    alertRegion.removeAttribute("data-variant");
    alertRegion.setAttribute("hidden", "");
    return;
  }
  alertRegion.textContent = message;
  alertRegion.dataset.variant = variant;
  alertRegion.removeAttribute("hidden");
}

function announce(message) {
  if (!liveRegion) {
    return;
  }
  liveRegion.textContent = "";
  requestAnimationFrame(() => {
    liveRegion.textContent = message;
  });
}

init();
