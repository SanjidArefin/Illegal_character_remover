import { confirm, open } from "@tauri-apps/plugin-dialog";
import { Command } from "@tauri-apps/plugin-shell";
import { collisionKey, validateManualCandidate } from "./manual-validation.js";

const MODE_FILES_NON_RECURSIVE = "files_non_recursive";
const MODE_FILES_RECURSIVE = "files_recursive";
const MODE_FOLDERS_RECURSIVE = "folders_recursive";
const MODE_FILES_AND_FOLDERS_NON_RECURSIVE = "files_and_folders_non_recursive";
const MODE_FILES_AND_FOLDERS_RECURSIVE = "files_and_folders_recursive";
const SIDECAR_NAME = "binaries/illegal-char-remover";
const REQUEST_TIMEOUT_MS = 120_000;
const elements = {};
function createSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `app-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const state = {
  sessionId: createSessionId(),
  selection: null,
  sidecarCommand: null,
  sidecarChild: null,
  waitingResponses: [],
  renamed: [],
  recoveredRenames: [],
  recoveryDismissed: false,
  errors: [],
  manualNeeded: [],
  scannedItems: [],
  completedManualTargets: new Set(),
  renameConfirmationAccepted: false,
  busy: false,
};

function isTauri() {
  return Boolean(window.__TAURI__?.core?.invoke);
}

function setStatus(message, kind = "") {
  if (!elements.connectionStatus) return;
  elements.connectionStatus.textContent = message;
  elements.connectionStatus.dataset.state = kind;
}

function showMessage(message) {
  elements.appMessage.textContent = message;
  elements.appMessage.hidden = !message;
}

function errorMessage(error) {
  if (typeof error === "string") return error;
  if (typeof error?.message === "string" && error.message) return error.message;
  try {
    return JSON.stringify(error) || String(error);
  } catch {
    return String(error);
  }
}

function addErrors(errors) {
  const keyFor = (error) => `${error.path || ""}\n${error.message || ""}`;
  const seen = new Set(state.errors.map(keyFor));
  for (const error of errors || []) {
    const key = keyFor(error);
    if (!seen.has(key)) {
      state.errors.push(error);
      seen.add(key);
    }
  }
}

function resolvePendingWithError(message) {
  const waiting = state.waitingResponses.splice(0);
  for (const item of waiting) {
    clearTimeout(item.timeout);
    item.reject(new Error(message));
  }
}

function parseSidecarResponse(line) {
  const trimmed = String(line).trim();
  if (!trimmed) return;
  let response;
  try {
    response = JSON.parse(trimmed);
  } catch (error) {
    resolvePendingWithError(`Python returned invalid JSON: ${error.message}`);
    return;
  }
  const pending = state.waitingResponses.shift();
  if (!pending) return;
  clearTimeout(pending.timeout);
  pending.resolve(response);
}

function handleSidecarFailure(message, exitCode = null) {
  state.sidecarChild = null;
  state.sidecarCommand = null;
  resolvePendingWithError(message);
  const suffix = exitCode === null ? "" : ` (exit code ${exitCode})`;
  setStatus(`Python sidecar stopped${suffix}`, "error");
  elements.restartSidecar.hidden = false;
  showMessage(`${message}. Restart the sidecar to continue.`);
}

async function startSidecar() {
  if (!isTauri()) {
    setStatus("Open this app in its Tauri window", "error");
    elements.restartSidecar.hidden = false;
    showMessage("The Python sidecar is available inside the desktop app. The binary is added after the PyInstaller build.");
    return false;
  }
  if (state.sidecarChild) return true;

  const wasBusy = state.busy;
  if (!wasBusy) setBusy(true);
  setStatus("Starting Python…");
  elements.restartSidecar.hidden = true;
  try {
    const command = Command.sidecar(SIDECAR_NAME);
    command.stdout.on("data", parseSidecarResponse);
    command.stderr.on("data", (line) => console.error("Python sidecar:", line));
    command.on("error", (error) => handleSidecarFailure(String(error)));
    command.on("close", (event) => handleSidecarFailure("Python sidecar exited", event.code));
    state.sidecarCommand = command;
    state.sidecarChild = await command.spawn();
    setStatus("Python sidecar ready", "ready");
    showMessage("");
    const recovered = await requestSidecar({
      action: "start_session",
      session_id: state.sessionId,
    });
    const recoveredByPair = new Map();
    for (const item of [...state.renamed, ...(recovered.renamed || [])]) {
      recoveredByPair.set(`${collisionKey(item.old_path)}\n${collisionKey(item.new_path)}`, item);
    }
    state.renamed = [...recoveredByPair.values()];
    state.recoveredRenames = recovered.recovered || [];
    if (recovered.manual_needed?.length) state.manualNeeded = recovered.manual_needed;
    addErrors(recovered.errors);
    renderResults();
    if (recovered.errors?.length) showMessage("Some saved undo entries could not be loaded. See the error list.");
    if (state.recoveredRenames.length && !state.recoveryDismissed) showRecoveredDialog();
    return true;
  } catch (error) {
    handleSidecarFailure(`Could not start the Python sidecar: ${errorMessage(error)}`);
    return false;
  } finally {
    if (!wasBusy) setBusy(false);
  }
}

async function requestSidecar(payload) {
  if (!state.sidecarChild && !(await startSidecar())) {
    throw new Error("Python sidecar is not running. Check the binary placeholder and restart it.");
  }

  return new Promise((resolve, reject) => {
    const pending = { resolve, reject, timeout: null };
    pending.timeout = setTimeout(() => {
      const index = state.waitingResponses.indexOf(pending);
      if (index >= 0) state.waitingResponses.splice(index, 1);
      const child = state.sidecarChild;
      handleSidecarFailure("Python sidecar timed out waiting for a response");
      void child?.kill().catch((error) => console.error("Could not stop timed-out sidecar:", error));
      reject(new Error("Python sidecar did not respond in time."));
    }, REQUEST_TIMEOUT_MS);
    state.waitingResponses.push(pending);
    state.sidecarChild.write(`${JSON.stringify(payload)}\n`).catch((error) => {
      const index = state.waitingResponses.indexOf(pending);
      if (index >= 0) state.waitingResponses.splice(index, 1);
      clearTimeout(pending.timeout);
      const child = state.sidecarChild;
      const detail = errorMessage(error);
      handleSidecarFailure(`Could not write to the Python sidecar: ${detail}`);
      void child?.kill().catch((killError) => console.error("Could not stop failed sidecar:", killError));
      reject(new Error(`Could not write to the Python sidecar: ${detail}`));
    });
  });
}

function currentRequest(action) {
  if (!state.selection) throw new Error("Choose a folder first.");
  return { action, path: state.selection.path, mode: selectedFolderMode() };
}

function selectedFolderMode() {
  const target = elements.targetSelect.value;
  const includeSubfolders = elements.scopeCheckbox.checked;
  if (target === "folders") return MODE_FOLDERS_RECURSIVE;
  if (target === "files_and_folders") {
    return includeSubfolders
      ? MODE_FILES_AND_FOLDERS_RECURSIVE
      : MODE_FILES_AND_FOLDERS_NON_RECURSIVE;
  }
  return includeSubfolders ? MODE_FILES_RECURSIVE : MODE_FILES_NON_RECURSIVE;
}

function updateTargetScopeControls() {
  const isFoldersTarget = elements.targetSelect.value === "folders";
  if (isFoldersTarget) elements.scopeCheckbox.checked = true;
  elements.targetSelect.disabled = state.busy;
  elements.scopeCheckbox.disabled = state.busy || isFoldersTarget;
  elements.scopeHint.textContent = isFoldersTarget
    ? "Folders are always processed recursively."
    : "";
}

function setBusy(busy) {
  state.busy = busy;
  elements.startButton.disabled = busy || !state.selection;
  elements.selectFolder.disabled = busy;
  if (elements.clearSelection) elements.clearSelection.disabled = busy || !state.selection;
  updateTargetScopeControls();
  elements.undoButton.disabled = busy || state.renamed.length === 0;
  elements.reviewRecovered.disabled = busy;
}

function renderSelection() {
  const selected = state.selection;
  if (elements.clearSelection) {
    elements.clearSelection.hidden = !selected;
    elements.clearSelection.disabled = state.busy || !selected;
  }
  if (!selected) {
    elements.selectionTitle.textContent = "Nothing selected";
    elements.selectionPath.textContent = "Select a folder to begin.";
  } else {
    elements.selectionTitle.textContent = "Folder selected";
    elements.selectionPath.textContent = selected.path;
  }
  elements.modeHelp.textContent = "The selected folder itself is never renamed.";
  setBusy(state.busy);
}

function clearSelection() {
  if (state.busy) return;
  state.selection = null;
  state.scannedItems = [];
  renderSelection();
  showMessage("");
}

function createItemRow(title, detail = "", className = "") {
  const li = document.createElement("li");
  li.className = `item-row ${className}`.trim();
  const strong = document.createElement("strong");
  strong.textContent = title;
  li.append(strong);
  if (detail) {
    const span = document.createElement("span");
    span.textContent = detail;
    li.append(span);
  }
  return li;
}

function showRecoveredDialog() {
  if (!state.recoveredRenames.length) return;
  elements.recoveredDialogMessage.textContent =
    `Found ${state.recoveredRenames.length} recovered renames from a previous session. Undo these?`;
  if (!elements.recoveredDialog.open) elements.recoveredDialog.showModal();
}

function dismissRecoveredDialog() {
  state.recoveryDismissed = true;
  if (elements.recoveredDialog.open) elements.recoveredDialog.close();
  renderResults();
}

async function confirmRecoveredUndo() {
  state.recoveryDismissed = true;
  if (elements.recoveredDialog.open) elements.recoveredDialog.close();
  await undoRenames({ confirmPrevious: true });
}

function renderResults() {
  const hasSession = state.renamed.length > 0 || state.errors.length > 0 || state.manualNeeded.length > 0
    || (elements.undoResult && !elements.undoResult.hidden)
    || (state.recoveryDismissed && state.recoveredRenames.length > 0);
  elements.resultsPanel.hidden = !hasSession;
  elements.renamedCount.textContent = String(state.renamed.length);
  elements.manualCount.textContent = String(state.manualNeeded.length);
  elements.errorCount.textContent = String(state.errors.length);
  elements.renamedList.replaceChildren(...state.renamed.map((item) =>
    createItemRow(item.new_path.split(/[\\/]/).pop(), `${item.old_path}  →  ${item.new_path}`)
  ));
  elements.manualList.replaceChildren(...state.manualNeeded.map((item) =>
    createItemRow(item.name, `${item.kind} · ${item.path}`)
  ));
  elements.errorList.replaceChildren(...state.errors.map((error) =>
    createItemRow(error.message || "Unknown error", error.path || "", "error-row")
  ));
  elements.renamedEmpty.hidden = state.renamed.length > 0;
  elements.manualEmpty.hidden = state.manualNeeded.length > 0;
  elements.errorsEmpty.hidden = state.errors.length > 0;
  elements.reviewManual.hidden = state.manualNeeded.length === 0;
  elements.reviewRecovered.hidden = state.recoveredRenames.length === 0 || !state.recoveryDismissed;
  elements.undoButton.disabled = state.busy || state.renamed.length === 0;
}

function applyResponse(response) {
  state.renamed.push(...(response.renamed || []));
  state.recoveredRenames = response.recovered || [];
  addErrors(response.errors);
  state.manualNeeded = response.manual_needed || [];
  renderResults();
}

async function selectFolder() {
  try {
    const path = await open({ directory: true, multiple: false, title: "Select a folder" });
    if (typeof path !== "string") return;
    state.selection = { path };
    renderSelection();
    showMessage("");
  } catch (error) {
    showMessage(`Could not open the folder picker: ${error.message}`);
  }
}

async function startRename() {
  if (state.busy) return;
  if (state.renamed.length > 0 || state.manualNeeded.length > 0) {
    showMessage("Finish manual names or undo the current batch before starting another so every change stays reversible.");
    return;
  }
  showMessage("");
  elements.undoResult.hidden = true;
  elements.undoResult.textContent = "";
  try {
    setBusy(true);
    state.errors = [];
    state.manualNeeded = [];
    state.scannedItems = [];
    state.completedManualTargets.clear();
    renderResults();

    const scan = await requestSidecar(currentRequest("scan"));
    state.scannedItems = scan.items || [];
    addErrors(scan.errors);
    if (scan.status === "error") {
      renderResults();
      showMessage("Nothing was renamed because the selected path could not be scanned.");
      return;
    }

    if (!state.renameConfirmationAccepted) {
      const itemCount = scan.items?.length ?? 0;
      const accepted = await confirm(`Rename ${itemCount} items? This can be undone.`, {
        title: "Confirm rename",
        kind: "warning",
      });
      if (!accepted) {
        renderResults();
        showMessage("Rename cancelled.");
        return;
      }
      state.renameConfirmationAccepted = true;
    }

    const response = await requestSidecar(currentRequest("rename"));
    applyResponse(response);
    if (state.manualNeeded.length) {
      const refreshed = await requestSidecar(currentRequest("scan"));
      if (refreshed.items) state.scannedItems = refreshed.items;
    }
    renderResults();
    if (response.errors?.length) showMessage("The run finished with errors. They are listed below.");
  } catch (error) {
    showMessage(error.message);
  } finally {
    setBusy(false);
    renderResults();
  }
}

function baseName(path) {
  return path.slice(Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\")) + 1);
}

function getExtension(record) {
  if (record.kind === "folder") return "";
  const name = record.name || baseName(record.path);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot) : "";
}

function showManualDialog() {
  if (!state.manualNeeded.length) return;
  elements.manualDialog.showModal();
  renderManualDialog();
}

function renderManualDialog() {
  const record = state.manualNeeded[0];
  if (!record) {
    elements.manualDialog.close();
    renderResults();
    return;
  }
  elements.manualProgress.textContent = `${state.manualNeeded.length} item${state.manualNeeded.length === 1 ? "" : "s"} left to name`;
  elements.manualItemPath.textContent = `${record.kind}: ${record.path}`;
  elements.manualExtension.textContent = getExtension(record) || "";
  elements.manualName.value = "";
  elements.manualError.hidden = true;
  elements.manualError.textContent = "";
  elements.manualName.focus();
}

function relocateKnownItems(oldPath, newPath) {
  const oldKey = collisionKey(oldPath);
  const separator = oldPath.includes("\\") ? "\\" : "/";
  const oldPrefix = `${oldKey.replace(/[\\/]+$/, "")}${separator}`;
  state.scannedItems = state.scannedItems.map((item) => {
    const itemKey = collisionKey(item.path);
    if (itemKey === oldKey) return { ...item, path: newPath, name: baseName(newPath) };
    if (itemKey.startsWith(oldPrefix)) {
      return { ...item, path: `${newPath}${item.path.slice(oldPath.length)}` };
    }
    return item;
  });
}

async function saveManualName(event) {
  event.preventDefault();
  const record = state.manualNeeded[0];
  if (!record || state.busy) return;

  const validation = validateManualCandidate(
    elements.manualName.value,
    record,
    state.scannedItems,
    state.completedManualTargets,
  );
  if (validation.error) {
    elements.manualError.textContent = validation.error;
    elements.manualError.hidden = false;
    return;
  }

  try {
    setBusy(true);
    const response = await requestSidecar({
      action: "manual_rename",
      path: record.path,
      new_name: validation.name,
    });
    const renamed = response.renamed || [];
    if (renamed.length) {
      state.renamed.push(...renamed);
      relocateKnownItems(renamed[0].old_path, renamed[0].new_path);
    }
    addErrors(response.errors);
    if (response.errors?.length && !renamed.length) {
      renderResults();
      elements.manualError.textContent = response.errors[0].message;
      elements.manualError.hidden = false;
      return;
    }
    state.completedManualTargets.add(validation.targetKey);
    state.manualNeeded = response.manual_needed || [];
    renderResults();
    renderManualDialog();
    if (response.errors?.length) showMessage("The name was saved, but the undo log reported an error. See the error list.");
  } catch (error) {
    elements.manualError.textContent = error.message;
    elements.manualError.hidden = false;
  } finally {
    setBusy(false);
  }
}

async function undoRenames({ confirmPrevious = false } = {}) {
  const hasCurrent = state.renamed.length > 0;
  const hasConfirmedRecovery = confirmPrevious && state.recoveredRenames.length > 0;
  if (state.busy || (!hasCurrent && !hasConfirmedRecovery)) return;
  showMessage("");
  try {
    setBusy(true);
    const response = await requestSidecar({
      action: "undo",
      confirm_previous: confirmPrevious,
    });
    const undone = response.undone || [];
    const undonePairs = new Set((response.undone || []).map((item) =>
      `${collisionKey(item.new_path)}\n${collisionKey(item.old_path)}`
    ));
    state.renamed = state.renamed.filter((item) =>
      !undonePairs.has(`${collisionKey(item.old_path)}\n${collisionKey(item.new_path)}`)
    );
    state.recoveredRenames = response.recovered || [];
    addErrors(response.errors);
    state.manualNeeded = response.manual_needed || [];
    state.completedManualTargets.clear();
    if (state.manualNeeded.length && state.selection) {
      const refreshed = await requestSidecar(currentRequest("scan"));
      state.scannedItems = refreshed.items || [];
    }
    const filesRestored = undone.filter((item) => item.kind === "file").length;
    const foldersRestored = undone.filter((item) => item.kind === "folder").length;
    const errorCount = response.errors?.length || 0;
    elements.undoResult.textContent = `Restored ${filesRestored} file${filesRestored === 1 ? "" : "s"} and ${foldersRestored} folder${foldersRestored === 1 ? "" : "s"}. Errors: ${errorCount}.`;
    elements.undoResult.hidden = false;
    if (confirmPrevious && state.recoveredRenames.length) {
      state.recoveryDismissed = false;
    }
    renderResults();
    if (state.manualNeeded.length && elements.manualDialog.open) renderManualDialog();
    if (confirmPrevious && state.recoveredRenames.length) showRecoveredDialog();
    if (response.errors?.length) showMessage("Some changes could not be undone. Retry after resolving the listed errors.");
    else showMessage(confirmPrevious ? "Recovered changes were undone." : "All successful renames from this batch were undone.");
  } catch (error) {
    elements.undoResult.textContent = `Undo could not complete. Errors: 1 (${error.message})`;
    elements.undoResult.hidden = false;
    addErrors([{ message: error.message }]);
    renderResults();
    showMessage(error.message);
  } finally {
    setBusy(false);
  }
}

function setTheme(preference) {
  localStorage.setItem("theme", preference);
  for (const button of elements.themeButtons || []) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === preference));
  }
  if (preference === "system") {
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  } else {
    document.documentElement.dataset.theme = preference;
  }
}

function cacheElements() {
  const ids = [
    "connection-status", "selection-title", "selection-path", "clear-selection", "select-folder",
    "target-select", "scope-checkbox", "scope-hint", "mode-help", "start-button",
    "app-message", "restart-sidecar",
    "results-panel", "review-manual", "review-recovered", "undo-button", "undo-result", "renamed-count", "manual-count", "error-count",
    "renamed-list", "manual-list", "error-list", "renamed-empty", "manual-empty", "errors-empty",
    "recovered-dialog", "recovered-dialog-message", "recovered-dismiss", "recovered-confirm",
    "manual-dialog", "manual-form", "manual-progress", "manual-item-path", "manual-extension",
    "manual-name", "manual-error", "manual-later",
  ];
  for (const id of ids) {
    const key = id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    elements[key] = document.getElementById(id);
  }
  elements.themeButtons = [...document.querySelectorAll("[data-theme-choice]")];
}

function initializeTheme() {
  const savedPreference = localStorage.getItem("theme");
  const preference = ["system", "light", "dark"].includes(savedPreference) ? savedPreference : "system";
  setTheme(preference);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (localStorage.getItem("theme") === "system") setTheme("system");
  });
}

function initialize() {
  cacheElements();
  initializeTheme();
  for (const button of elements.themeButtons) {
    button.addEventListener("click", () => setTheme(button.dataset.themeChoice));
  }
  elements.selectFolder.addEventListener("click", selectFolder);
  elements.clearSelection.addEventListener("click", clearSelection);
  elements.startButton.addEventListener("click", startRename);
  elements.restartSidecar.addEventListener("click", startSidecar);
  elements.reviewRecovered.addEventListener("click", () => {
    state.recoveryDismissed = false;
    showRecoveredDialog();
    renderResults();
  });
  elements.recoveredDismiss.addEventListener("click", dismissRecoveredDialog);
  elements.recoveredConfirm.addEventListener("click", confirmRecoveredUndo);
  elements.recoveredDialog.addEventListener("cancel", () => {
    state.recoveryDismissed = true;
    queueMicrotask(renderResults);
  });
  elements.reviewManual.addEventListener("click", showManualDialog);
  elements.manualForm.addEventListener("submit", saveManualName);
  elements.manualLater.addEventListener("click", () => elements.manualDialog.close());
  elements.undoButton.addEventListener("click", undoRenames);
  elements.targetSelect.addEventListener("change", () => {
    updateTargetScopeControls();
    showMessage("");
  });
  elements.scopeCheckbox.addEventListener("change", () => showMessage(""));
  renderSelection();
  renderResults();
  void startSidecar();
}

document.addEventListener("DOMContentLoaded", initialize, { once: true });
