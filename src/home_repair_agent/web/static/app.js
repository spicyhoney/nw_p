class SessionResponseCoordinator {
  constructor() {
    this.nextSequence = 0;
    this.latestStartedSequence = 0;
    this.latestAppliedSequence = 0;
    this.generation = 0;
  }

  begin(sessionId) {
    this.nextSequence += 1;
    this.latestStartedSequence = this.nextSequence;
    return {
      sequence: this.nextSequence,
      generation: this.generation,
      sessionId,
    };
  }

  beginReplacement() {
    this.generation += 1;
    return this.begin(null);
  }

  apply(targetStore, request, response) {
    const currentSessionId = targetStore.session?.session_id || null;
    const responseSessionId = response?.session_id || null;
    if (
      request.generation !== this.generation ||
      request.sequence < this.latestStartedSequence ||
      request.sequence <= this.latestAppliedSequence ||
      (request.sessionId && request.sessionId !== currentSessionId) ||
      (request.sessionId && request.sessionId !== responseSessionId)
    ) {
      return false;
    }
    this.latestAppliedSequence = request.sequence;
    targetStore.session = response;
    return true;
  }
}

const sessionResponses = new SessionResponseCoordinator();

const store = {
  session: null,
  busy: false,
  selectedProviderId: "",
  alertTimer: null,
  pollTimer: null,
  checklistBusy: new Set(),
  checklistSyncing: false,
  checklistNeedsRecovery: false,
  lastDispatchSignature: "",
  mediaProvider: "unknown",
  mediaBusy: false,
  previewObjectUrl: "",
  lastMessageSignature: "",
  mediaEditorExpanded: false,
  formSignature: "",
  visibleFormSignature: "",
};

const elements = {};

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    bindEvents();
    createSession();
  });
}

function bindElements() {
  elements.providerChip = document.querySelector("#provider-chip");
  elements.resetButton = document.querySelector("#reset-button");
  elements.progressList = document.querySelector("#progress-list");
  elements.serviceSummary = document.querySelector("#service-summary");
  elements.locationSummary = document.querySelector("#location-summary");
  elements.branchSummary = document.querySelector("#branch-summary");
  elements.taskStatusSummary = document.querySelector("#task-status-summary");
  elements.collectedFieldsList = document.querySelector("#collected-fields-list");
  elements.missingFieldsList = document.querySelector("#missing-fields-list");
  elements.sharedSlotsWarning = document.querySelector("#shared-slots-warning");
  elements.routingSection = document.querySelector("#routing-section");
  elements.routingGuidance = document.querySelector("#routing-guidance");
  elements.routingOptions = document.querySelector("#routing-options");
  elements.routingReject = document.querySelector("#routing-reject");
  elements.checklistList = document.querySelector("#checklist-list");
  elements.checklistSummary = document.querySelector("#checklist-summary");
  elements.checklistFeedback = document.querySelector("#checklist-feedback");
  elements.traceList = document.querySelector("#trace-list");
  elements.workflowNote = document.querySelector("#workflow-note");
  elements.sessionState = document.querySelector("#session-state");
  elements.conversationScrollRegion = document.querySelector(
    "#conversation-scroll-region",
  );
  elements.messageList = document.querySelector("#message-list");
  elements.messageForm = document.querySelector("#message-form");
  elements.messageInput = document.querySelector("#message-input");
  elements.sendButton = document.querySelector("#send-button");
  elements.formSection = document.querySelector("#form-section");
  elements.formTitle = document.querySelector("#form-title");
  elements.formDescription = document.querySelector("#form-description");
  elements.consultationForm = document.querySelector("#consultation-form");
  elements.formFields = document.querySelector("#form-fields");
  elements.formError = document.querySelector("#form-error");
  elements.summarySection = document.querySelector("#summary-section");
  elements.summaryVersion = document.querySelector("#summary-version");
  elements.summaryGuidance = document.querySelector("#summary-guidance");
  elements.summaryDetails = document.querySelector("#summary-details");
  elements.summaryAnswers = document.querySelector("#summary-answers");
  elements.summaryConfirm = document.querySelector("#summary-confirm");
  elements.candidateList = document.querySelector("#candidate-list");
  elements.dispatchStatus = document.querySelector("#dispatch-status");
  elements.dispatchStatusTitle = document.querySelector(
    "#dispatch-status-title",
  );
  elements.dispatchStatusCopy = document.querySelector(
    "#dispatch-status-copy",
  );
  elements.dispatchStatusDetails = document.querySelector(
    "#dispatch-status-details",
  );
  elements.dispatchConfirmation = document.querySelector(
    "#dispatch-confirmation",
  );
  elements.dispatchConfirmationTitle = document.querySelector(
    "#dispatch-confirmation-title",
  );
  elements.dispatchConfirmationCopy = document.querySelector(
    "#dispatch-confirmation-copy",
  );
  elements.cancelDispatch = document.querySelector("#cancel-dispatch");
  elements.confirmDispatch = document.querySelector("#confirm-dispatch");
  elements.candidateEmpty = document.querySelector("#candidate-empty");
  elements.candidateCount = document.querySelector("#candidate-count");
  elements.mobileCandidateCount = document.querySelector(
    "#mobile-candidate-count",
  );
  elements.appAlert = document.querySelector("#app-alert");
  elements.appStatus = document.querySelector("#app-status");
  elements.mobileTabs = [...document.querySelectorAll("[data-mobile-target]")];
  elements.mediaSection = document.querySelector("#media-section");
  elements.mediaMode = document.querySelector("#media-mode");
  elements.mediaUploadForm = document.querySelector("#media-upload-form");
  elements.mediaFile = document.querySelector("#media-file");
  elements.mediaConsent = document.querySelector("#media-external-consent");
  elements.mediaUploadButton = document.querySelector("#media-upload-button");
  elements.mediaStatus = document.querySelector("#media-status");
  elements.mediaPreviewPanel = document.querySelector("#media-preview-panel");
  elements.mediaPreview = document.querySelector("#media-preview");
  elements.mediaRemoveButton = document.querySelector("#media-remove-button");
  elements.mediaAnalysisForm = document.querySelector("#media-analysis-form");
  elements.mediaServiceQuery = document.querySelector("#media-service-query");
  elements.mediaProblemSummary = document.querySelector("#media-problem-summary");
  elements.mediaSafetyWarnings = document.querySelector("#media-safety-warnings");
  elements.mediaConfidence = document.querySelector("#media-confidence");
  elements.mediaConfirmButton = document.querySelector("#media-confirm-button");
  elements.mediaConfirmedCard = document.querySelector("#media-confirmed-card");
  elements.mediaConfirmedPreview = document.querySelector(
    "#media-confirmed-preview",
  );
  elements.mediaConfirmedTitle = document.querySelector(
    "#media-confirmed-title",
  );
  elements.mediaConfirmedService = document.querySelector(
    "#media-confirmed-service",
  );
  elements.mediaConfirmedSummary = document.querySelector(
    "#media-confirmed-summary",
  );
  elements.mediaConfirmedNextStep = document.querySelector(
    "#media-confirmed-next-step",
  );
  elements.mediaEditToggle = document.querySelector("#media-edit-toggle");
  elements.mediaConfirmedRemove = document.querySelector(
    "#media-confirmed-remove",
  );
}

function bindEvents() {
  elements.messageForm.addEventListener("submit", handleMessageSubmit);
  elements.consultationForm.addEventListener("submit", handleFormSubmit);
  elements.routingReject.addEventListener("click", rejectRoutingProposal);
  elements.summaryConfirm.addEventListener("click", confirmSummary);
  elements.resetButton.addEventListener("click", resetSession);
  elements.cancelDispatch.addEventListener("click", cancelDispatch);
  elements.confirmDispatch.addEventListener("click", confirmDispatch);
  elements.messageInput.addEventListener("input", resizeMessageInput);
  elements.mediaUploadForm.addEventListener("submit", handleMediaUpload);
  elements.mediaFile.addEventListener("change", handleMediaFileChange);
  elements.mediaRemoveButton.addEventListener("click", removeMedia);
  elements.mediaConfirmedRemove.addEventListener("click", removeMedia);
  elements.mediaAnalysisForm.addEventListener("submit", confirmMediaAnalysis);
  elements.mediaEditToggle.addEventListener("click", toggleMediaEditor);
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.messageForm.requestSubmit();
    }
  });
  elements.mobileTabs.forEach((button) => {
    button.addEventListener("click", () => {
      setMobileView(button.dataset.mobileTarget, { focusHeading: true });
    });
  });
  window.addEventListener("beforeunload", stopSessionPolling);
}

async function createSession() {
  if (hasChecklistMutation()) {
    return;
  }
  const request = sessionResponses.beginReplacement();
  setBusy(true, "正在建立新諮詢。");
  try {
    stopSessionPolling();
    store.selectedProviderId = "";
    store.checklistBusy.clear();
    store.checklistSyncing = false;
    store.checklistNeedsRecovery = false;
    store.lastDispatchSignature = "";
    resetTransientConversationUi();
    const response = await api("/api/sessions", { method: "POST" });
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    renderSession();
    loadMediaProvider();
    announce("新諮詢已建立，可以開始描述修繕需求。");
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleMessageSubmit(event) {
  event.preventDefault();
  if (!store.session || isSessionMutationBlocked()) {
    return;
  }
  const text = elements.messageInput.value.trim();
  if (!text) {
    return;
  }

  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  setBusy(true, "正在整理你的修繕需求。");
  try {
    const response = await api(
      `/api/sessions/${sessionId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ text }),
      },
    );
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    elements.messageInput.value = "";
    resizeMessageInput();
    renderSession();
    announce("需求已更新，請核對系統整理的內容。");
    if (store.session.consultation_form) {
      setMobileView("conversation");
    }
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

async function confirmBranch(branch, confirm = true) {
  if (!store.session || isSessionMutationBlocked()) {
    return;
  }
  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  setBusy(true, confirm ? "正在確認修繕分支。" : "正在保留原修繕分支。");
  try {
    const response = await api(
      `/api/sessions/${sessionId}/branch/confirm`,
      {
        method: "POST",
        body: JSON.stringify({ branch, confirm }),
      },
    );
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    renderSession();
    announce(
      confirm
        ? `已確認${branchLabel(branch)}，請繼續核對地點與表單。`
        : "未套用候選分支。",
    );
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

function rejectRoutingProposal() {
  const candidate = routingCandidates()[0];
  if (candidate) {
    confirmBranch(candidate, false);
  }
}

async function confirmSummary() {
  const task = store.session?.active_task;
  const summary = task?.summary;
  if (!store.session || !task || !summary || !store.session.can_confirm_summary) {
    return;
  }
  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  setBusy(true, "正在確認最新摘要並執行媒合。");
  try {
    const response = await api(
      `/api/sessions/${sessionId}/summary/confirm`,
      {
        method: "POST",
        body: JSON.stringify({
          active_task_id: task.active_task_id,
          summary_id: summary.summary_id,
          summary_version: summary.version,
          confirm: true,
        }),
      },
    );
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    renderSession();
    announce(`摘要已確認，共有 ${store.session.candidates.length} 位候選。`);
    setMobileView("candidates", { focusHeading: true });
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleFormSubmit(event) {
  event.preventDefault();
  if (
    !store.session ||
    isSessionMutationBlocked() ||
    !store.session.consultation_form
  ) {
    return;
  }

  clearFormErrors();
  const payload = collectFormPayload(store.session.consultation_form);
  if (!payload) {
    return;
  }

  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  setBusy(true, "正在驗證表單並產生最新摘要。");
  try {
    const response = await api(
      `/api/sessions/${sessionId}/form`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    renderSession();
    announce("表單已保存，請核對最新摘要後再確認媒合。");
  } catch (error) {
    showFormError(error);
  } finally {
    setBusy(false);
  }
}

async function resetSession() {
  if (!store.session || isSessionMutationBlocked()) {
    return;
  }
  setBusy(true, "正在重新開始這次諮詢。");
  try {
    if (store.session.dispatch) {
      await createSession();
      setMobileView("conversation", { focusHeading: true });
      elements.messageInput.focus();
      return;
    }
    const sessionId = store.session.session_id;
    const request = sessionResponses.begin(sessionId);
    const response = await api(
      `/api/sessions/${sessionId}/reset`,
      { method: "POST" },
    );
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    resetTransientConversationUi();
    renderSession();
    announce("諮詢已重設，人工核對清單也已清除。");
    setMobileView("conversation", { focusHeading: true });
    elements.messageInput.focus();
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

async function updateChecklistItem(itemKey, checked) {
  if (
    !store.session ||
    store.busy ||
    store.checklistSyncing ||
    store.checklistBusy.has(itemKey)
  ) {
    return;
  }

  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  const item = store.session.checklist.find(
    (candidate) => candidate.key === itemKey,
  );
  const inputId = `checklist-${itemKey}`;
  store.checklistBusy.add(itemKey);
  const activeControl = document.querySelector(`#${inputId}`);
  if (activeControl) {
    activeControl.disabled = true;
    activeControl.closest(".checklist-item")?.setAttribute("aria-busy", "true");
  }
  updateControls();
  announce(`正在儲存「${item?.label || "核對項目"}」。`);
  try {
    const response = await api(
      `/api/sessions/${sessionId}/checklist/${encodeURIComponent(
        itemKey,
      )}`,
      {
        method: "PUT",
        body: JSON.stringify({ checked }),
      },
    );
    if (sessionResponses.apply(store, request, response)) {
      renderSession();
    }
    if (store.session?.session_id === sessionId) {
      const resultText = checked ? "已由你勾選" : "已由你取消勾選";
      elements.checklistFeedback.textContent =
        `${item?.label || "核對項目"}：${resultText}。`;
    }
  } catch (error) {
    store.checklistNeedsRecovery = true;
    showAlert(error.message);
    announce(`「${item?.label || "核對項目"}」儲存失敗，正在重新同步。`);
  } finally {
    store.checklistBusy.delete(itemKey);
    let synchronized = false;
    if (
      store.session?.session_id === sessionId &&
      store.checklistBusy.size === 0
    ) {
      synchronized = await synchronizeChecklistSession(sessionId);
    } else {
      renderChecklist();
      updateControls();
    }
    if (synchronized && store.checklistNeedsRecovery) {
      store.checklistNeedsRecovery = false;
      announce("核對清單已恢復伺服器狀態。");
    }
    if (store.session?.session_id === sessionId) {
      window.requestAnimationFrame(() => {
        document.querySelector(`#${inputId}`)?.focus({ preventScroll: true });
      });
    }
  }
}

async function synchronizeChecklistSession(sessionId) {
  if (
    !store.session ||
    store.session.session_id !== sessionId ||
    store.checklistBusy.size > 0
  ) {
    return false;
  }

  store.checklistSyncing = true;
  renderChecklist();
  updateControls();
  const request = sessionResponses.begin(sessionId);
  let synchronized = false;
  try {
    const response = await api(`/api/sessions/${sessionId}`);
    synchronized = sessionResponses.apply(store, request, response);
    if (synchronized) {
      renderSession();
    }
  } catch (error) {
    showAlert(`核對清單同步失敗：${error.message}`);
  } finally {
    store.checklistSyncing = false;
    if (store.session?.session_id === sessionId) {
      renderChecklist();
      updateControls();
    }
  }
  return synchronized;
}

function selectCandidate(providerId) {
  if (!store.session?.can_dispatch || store.busy) {
    return;
  }
  const rejected = new Set(
    store.session.dispatch?.rejected_provider_ids || [],
  );
  if (rejected.has(providerId)) {
    return;
  }
  store.selectedProviderId = providerId;
  renderCandidates();
  updateControls();
  elements.dispatchConfirmation.scrollIntoView({ block: "nearest" });
}

function cancelDispatch() {
  store.selectedProviderId = "";
  renderCandidates();
  updateControls();
}

async function confirmDispatch() {
  if (
    !store.session ||
    !store.selectedProviderId ||
    !store.session.can_dispatch ||
    isSessionMutationBlocked()
  ) {
    return;
  }

  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  setBusy(true, "正在建立案件並通知所選廠商。");
  try {
    const response = await api(
      `/api/sessions/${sessionId}/dispatch`,
      {
        method: "POST",
        body: JSON.stringify({
          provider_id: store.selectedProviderId,
          confirmed: true,
          idempotency_key:
            `dispatch:${sessionId}:${store.selectedProviderId}`,
        }),
      },
    );
    if (!sessionResponses.apply(store, request, response)) {
      return;
    }
    store.selectedProviderId = "";
    renderSession();
    startSessionPolling();
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

function startSessionPolling() {
  stopSessionPolling();
  if (store.session?.dispatch?.status !== "pending_provider") {
    return;
  }
  store.pollTimer = window.setInterval(refreshSession, 3000);
}

function stopSessionPolling() {
  if (store.pollTimer) {
    window.clearInterval(store.pollTimer);
    store.pollTimer = null;
  }
}

async function refreshSession() {
  if (
    !store.session ||
    isSessionMutationBlocked() ||
    store.session.dispatch?.status !== "pending_provider"
  ) {
    return;
  }
  const sessionId = store.session.session_id;
  const request = sessionResponses.begin(sessionId);
  try {
    const response = await api(`/api/sessions/${sessionId}`);
    const applied = sessionResponses.apply(store, request, response);
    if (applied) {
      renderSession();
    }
    if (applied && store.session.dispatch?.status !== "pending_provider") {
      stopSessionPolling();
    }
  } catch (error) {
    stopSessionPolling();
    showAlert(error.message);
  }
}

const MEDIA_ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);
const MEDIA_MAX_BYTES = 8 * 1024 * 1024;

async function loadMediaProvider() {
  if (store.session?.provider?.key) {
    store.mediaProvider = store.session.provider.key;
  }
  try {
    const health = await api("/api/health");
    store.mediaProvider = health.model_provider || store.mediaProvider || "unknown";
  } catch {
    // Treat an unavailable health contract as unavailable image processing; never fall back to mock.
    store.mediaProvider = "unknown";
  }
  renderMedia();
}

function isHuggingFaceMediaAvailable() {
  return store.mediaProvider === "huggingface";
}

function currentMedia() {
  return store.session?.media || null;
}

function mediaImagePath(sessionId = store.session?.session_id) {
  return `/api/sessions/${encodeURIComponent(sessionId)}/image`;
}

function setMediaStatus(message) {
  elements.mediaStatus.textContent = message;
}

function clearPreviewObjectUrl() {
  if (store.previewObjectUrl) {
    URL.revokeObjectURL(store.previewObjectUrl);
    store.previewObjectUrl = "";
  }
}

function handleMediaFileChange() {
  const file = elements.mediaFile.files?.[0];
  clearPreviewObjectUrl();
  store.mediaEditorExpanded = false;
  if (!file) {
    renderMedia();
    return;
  }
  const error = validateMediaFile(file);
  if (error) {
    elements.mediaFile.value = "";
    setMediaStatus(error);
    renderMedia();
    return;
  }
  store.previewObjectUrl = URL.createObjectURL(file);
  elements.mediaPreview.src = store.previewObjectUrl;
  elements.mediaPreviewPanel.hidden = false;
  setMediaStatus(`已選取 ${file.name}，尚未上傳。`);
}

function validateMediaFile(file) {
  if (!MEDIA_ALLOWED_TYPES.has(file.type)) {
    return "請選擇 JPEG、PNG 或 WebP 圖片。";
  }
  if (file.size > MEDIA_MAX_BYTES) {
    return "圖片大小不可超過 8 MB。";
  }
  return "";
}

async function handleMediaUpload(event) {
  event.preventDefault();
  if (!store.session || store.mediaBusy || !isHuggingFaceMediaAvailable()) {
    return;
  }
  if (!store.session.active_task?.branch) {
    setMediaStatus("請先確認水電修繕分支，再上傳圖片。");
    return;
  }
  const file = elements.mediaFile.files?.[0];
  const error = file ? validateMediaFile(file) : "請先選擇一張圖片。";
  if (error) {
    setMediaStatus(error);
    elements.mediaFile.focus();
    return;
  }
  if (!elements.mediaConsent.checked) {
    setMediaStatus("請先明確勾選同意將圖片送至外部 Hugging Face 處理。");
    elements.mediaConsent.focus();
    return;
  }

  const body = new FormData();
  body.append("file", file);
  body.append("external_processing_confirmed", "true");
  setMediaBusy(true, "正在上傳圖片並等待 Hugging Face 分析結果…");
  try {
    const response = await api(mediaImagePath(), { method: "POST", body });
    store.mediaEditorExpanded = true;
    await applyMediaResponse(response);
    elements.mediaFile.value = "";
    elements.mediaConsent.checked = false;
    clearPreviewObjectUrl();
    setMediaStatus("圖片分析完成。請先核對或更正建議，再確認套用。");
    announce("圖片分析完成，請核對或更正結果。");
    revealConversationSection(
      elements.mediaAnalysisForm,
      elements.mediaServiceQuery,
    );
  } catch (uploadError) {
    setMediaStatus(uploadError.message);
  } finally {
    setMediaBusy(false);
  }
}

async function removeMedia() {
  if (!store.session || store.mediaBusy || !currentMedia()) {
    return;
  }
  const wasConfirmed = currentMedia().analysis?.confirmed === true;
  setMediaBusy(true, "正在移除圖片…");
  try {
    const response = await api(mediaImagePath(), { method: "DELETE" });
    store.mediaEditorExpanded = false;
    await applyMediaResponse(response);
    elements.mediaFile.value = "";
    elements.mediaConsent.checked = false;
    clearPreviewObjectUrl();
    setMediaStatus(
      wasConfirmed
        ? "圖片已移除；先前已確認的服務仍保留，如需更正請重新開始。"
        : "圖片已移除，辨識建議未套用。",
    );
    announce("圖片已移除。");
    revealConversationSection(elements.mediaSection, elements.mediaFile);
  } catch (removeError) {
    setMediaStatus(removeError.message);
  } finally {
    setMediaBusy(false);
  }
}

async function confirmMediaAnalysis(event) {
  event.preventDefault();
  const media = currentMedia();
  if (!store.session || !media || store.mediaBusy) {
    return;
  }
  if (!store.session.active_task?.branch) {
    setMediaStatus("請先確認水電修繕分支，再確認圖片分析。");
    return;
  }
  const payload = {
    media_id: media.media_id,
    analysis_revision: media.analysis.analysis_revision,
    service_query: elements.mediaServiceQuery.value.trim(),
    problem_summary: elements.mediaProblemSummary.value.trim(),
    safety_warnings: elements.mediaSafetyWarnings.value
      .split("\n")
      .map((warning) => warning.trim())
      .filter(Boolean),
  };
  if (!payload.service_query || !payload.problem_summary) {
    setMediaStatus("請填寫建議服務類別與問題摘要後再確認。");
    return;
  }
  setMediaBusy(true, "正在確認圖片辨識結果…");
  try {
    const response = await api(`${mediaImagePath()}/confirm`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    store.mediaEditorExpanded = false;
    await applyMediaResponse(response);
    setMediaStatus("辨識結果已確認並套用到後續流程。");
    announce("圖片辨識結果已確認並套用。");
    revealConversationSection(
      elements.mediaConfirmedCard,
      elements.mediaConfirmedTitle,
    );
  } catch (confirmError) {
    if (confirmError.code === "IMAGE_CONFIRMATION_STALE") {
      try {
        const latest = await api(
          `/api/sessions/${encodeURIComponent(store.session.session_id)}`,
        );
        store.session = latest;
        const latestAnalysis = currentMedia()?.analysis;
        store.mediaEditorExpanded = Boolean(latestAnalysis && !latestAnalysis.confirmed);
        renderSession();
        setMediaStatus(`${confirmError.message} 已載入最新圖片分析。`);
        announce("圖片分析已更新，畫面已同步到最新版本。");
        if (latestAnalysis?.confirmed) {
          revealConversationSection(
            elements.mediaConfirmedCard,
            elements.mediaConfirmedTitle,
          );
        } else if (latestAnalysis) {
          revealConversationSection(
            elements.mediaAnalysisForm,
            elements.mediaServiceQuery,
          );
        } else {
          revealConversationSection(elements.mediaSection, elements.mediaFile);
        }
        return;
      } catch (refreshError) {
        setMediaStatus(`${confirmError.message} ${refreshError.message}`);
        return;
      }
    }
    setMediaStatus(confirmError.message);
  } finally {
    setMediaBusy(false);
  }
}

async function applyMediaResponse(response) {
  // Keep the provisional endpoint response shape isolated while the backend contract lands.
  const session = response?.session || response?.session_view || response;
  if (session?.session_id) {
    store.session = session;
    renderSession();
    return;
  }
  const latest = await api(`/api/sessions/${encodeURIComponent(store.session.session_id)}`);
  store.session = latest;
  renderSession();
}

function renderMedia() {
  if (!elements.mediaSection || !store.session) {
    return;
  }
  const media = currentMedia();
  const analysis = media?.analysis || null;
  const available = isHuggingFaceMediaAvailable();
  const branchReady = Boolean(store.session.active_task?.branch);
  const blocked = store.mediaBusy || isSessionMutationBlocked() || !branchReady;
  const confirmed = analysis?.confirmed === true;

  elements.mediaSection.hidden = !branchReady && !media;
  elements.mediaMode.textContent = available
    ? "Hugging Face 外部分析"
    : "圖片分析目前不可用（Mock／Bedrock／未設定）";
  elements.mediaMode.classList.toggle("media-mode--unavailable", !available);
  elements.mediaUploadForm.hidden = Boolean(media) || !branchReady;
  elements.mediaFile.disabled = blocked || !available;
  elements.mediaConsent.disabled = blocked || !available;
  elements.mediaUploadButton.disabled = blocked || !available;
  elements.mediaUploadButton.textContent = store.mediaBusy ? "處理中…" : "上傳並分析";
  if (!available && !media && !store.mediaBusy) {
    setMediaStatus("此 session 使用 Mock、Bedrock 或未設定模型；圖片不會上傳，也不會改用其他模式處理。");
  } else if (!branchReady && !media && !store.mediaBusy) {
    setMediaStatus("請先確認水電修繕分支，圖片控制才會開放。");
  }

  const previewSource = media ? mediaImagePath() : store.previewObjectUrl;
  elements.mediaPreviewPanel.hidden =
    !previewSource || (confirmed && !store.mediaEditorExpanded);
  if (previewSource) {
    elements.mediaPreview.src = previewSource;
  } else {
    elements.mediaPreview.removeAttribute("src");
  }
  elements.mediaRemoveButton.disabled = blocked || !media;

  elements.mediaConfirmedCard.hidden = !confirmed;
  if (confirmed) {
    elements.mediaConfirmedPreview.src = mediaImagePath();
    elements.mediaConfirmedService.textContent =
      store.session.service?.name || analysis.service_query || "已驗證服務";
    elements.mediaConfirmedSummary.textContent = analysis.problem_summary || "—";
    elements.mediaConfirmedNextStep.textContent = mediaNextStepText();
    elements.mediaEditToggle.disabled = blocked;
    elements.mediaEditToggle.setAttribute(
      "aria-expanded",
      String(store.mediaEditorExpanded),
    );
    elements.mediaEditToggle.textContent = store.mediaEditorExpanded
      ? "收合編輯區"
      : "展開編輯並重新確認";
    elements.mediaConfirmedRemove.disabled = blocked || !media;
  } else {
    elements.mediaConfirmedPreview.removeAttribute("src");
    store.mediaEditorExpanded = false;
  }

  elements.mediaAnalysisForm.hidden =
    !analysis || (confirmed && !store.mediaEditorExpanded);
  if (!analysis) {
    return;
  }
  const active = document.activeElement;
  if (active !== elements.mediaServiceQuery) {
    elements.mediaServiceQuery.value = analysis.service_query || "";
  }
  if (active !== elements.mediaProblemSummary) {
    elements.mediaProblemSummary.value = analysis.problem_summary || "";
  }
  if (active !== elements.mediaSafetyWarnings) {
    elements.mediaSafetyWarnings.value = Array.isArray(analysis.safety_warnings)
      ? analysis.safety_warnings.join("\n")
      : analysis.safety_warnings || "";
  }
  const confidence = Number(analysis.confidence);
  elements.mediaConfidence.textContent = Number.isFinite(confidence)
    ? `信心 ${Math.round(confidence * 100)}%${analysis.uncertain ? " · 需要確認" : ""}`
    : analysis.uncertain
      ? "需要確認"
      : "待確認";
  elements.mediaConfirmButton.disabled = blocked;
  elements.mediaConfirmButton.textContent = confirmed
    ? store.mediaBusy
      ? "重新確認中…"
      : "重新確認並套用辨識結果"
    : store.mediaBusy
      ? "確認中…"
      : "確認並套用辨識結果";
}

function mediaNextStepText() {
  if (store.session?.consultation_form) {
    return "下一步：填寫下方諮詢單；圖片建議不會自行媒合或派單。";
  }
  if (store.session?.location) {
    return "圖片結果已保存；請繼續在對話中補充需求。";
  }
  return "下一步：請在對話中提供完整縣市與行政區，系統不會自行猜測地點。";
}

function setMediaBusy(value, message = "") {
  store.mediaBusy = value;
  if (message) {
    setMediaStatus(message);
  }
  updateControls();
}

async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = { ...(options.headers || {}) };
  if (!isFormData && options.body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    throw new Error("伺服器回傳了無法辨識的內容。");
  }
  if (!response.ok) {
    const apiError = payload?.error;
    const message =
      apiError?.message ||
      validationMessage(payload?.detail) ||
      "目前無法完成操作，請稍後再試。";
    const error = new Error(message);
    error.code = apiError?.code || "";
    error.fields = apiError?.fields || {};
    throw error;
  }
  return payload;
}

function validationMessage(detail) {
  if (!Array.isArray(detail) || !detail.length) {
    return "";
  }
  return detail
    .map((item) => item?.msg)
    .filter(Boolean)
    .join(" ");
}

function renderSession() {
  if (!store.session) {
    return;
  }
  renderHeader();
  renderProgress();
  renderChecklist();
  renderMessages();
  renderRouting();
  renderMedia();
  renderForm();
  renderSummary();
  renderDispatch();
  renderCandidates();
  updateControls();
}

function renderHeader() {
  const session = store.session;
  elements.providerChip.textContent = {
    mock: "Mock 模式",
    huggingface: "HF 模式",
    bedrock: "Bedrock 模式",
  }[session.provider.key];
  elements.providerChip.title = session.provider.is_external
    ? `${session.provider.label}，外部 hosted model`
    : `${session.provider.label}，本機規則式 Mock Model`;
  elements.providerChip.setAttribute(
    "aria-label",
    elements.providerChip.title,
  );
  const labels = {
    collecting_need: "確認需求",
    routing_pending: "確認分支",
    replacement_pending: "確認切換",
    clarifying: "補充資料",
    awaiting_form: "填寫諮詢單",
    awaiting_summary_confirmation: "核對摘要",
    matched: "媒合完成",
    no_candidates: "暫無候選",
    dispatch_pending: "等待廠商",
    provider_accepted: "廠商已接單",
    provider_rejected: "請改選廠商",
    error: "需要重試",
  };
  elements.sessionState.textContent = labels[session.state] || "處理中";
}

function renderProgress() {
  const session = store.session;
  elements.progressList.replaceChildren(
    ...session.progress.map((step, index) => {
      const item = document.createElement("li");
      item.className = `progress-step progress-step--${step.state}`;

      const marker = document.createElement("span");
      marker.className = "progress-step__marker";
      marker.textContent = step.state === "complete" ? "✓" : String(index + 1);
      marker.setAttribute("aria-hidden", "true");

      const content = document.createElement("span");
      content.className = "progress-step__content";
      const label = document.createElement("span");
      label.textContent = step.label;
      const state = document.createElement("small");
      state.className = "progress-step__state";
      state.textContent = {
        complete: "完成",
        active: "目前步驟",
        pending: "尚未開始",
      }[step.state];
      content.append(label, state);
      item.append(marker, content);
      return item;
    }),
  );
  elements.serviceSummary.textContent =
    session.service?.name || "尚未確認";
  elements.locationSummary.textContent =
    session.location?.full_name || "尚未確認";
  const task = session.active_task;
  elements.branchSummary.textContent = task?.branch
    ? branchLabel(task.branch)
    : "尚未確認";
  elements.taskStatusSummary.textContent = task
    ? taskStatusLabel(task.status)
    : "等待描述";
  elements.collectedFieldsList.replaceChildren(
    ...fieldListNodes(task?.collected_fields, "尚無"),
  );
  elements.missingFieldsList.replaceChildren(
    ...missingFieldNodes(task?.missing_fields),
  );
  elements.sharedSlotsWarning.hidden =
    !Boolean(task?.shared_slots_need_confirmation);

  const traceItems = session.tool_trace.map((trace) => {
    const item = document.createElement("li");
    item.className = `trace-item${trace.ok ? " trace-item--ok" : ""}`;
    item.textContent = `${trace.label} · ${trace.ok ? "完成" : "未完成"}`;
    return item;
  });
  if (!traceItems.length) {
    const empty = document.createElement("li");
    empty.className = "trace-item";
    empty.textContent = "尚無查詢";
    traceItems.push(empty);
  }
  elements.traceList.replaceChildren(...traceItems);
}

function renderChecklist() {
  const checklist = store.session?.checklist || [];
  const activeId = document.activeElement?.id || "";
  const nodes = checklist.map((item) => {
    const row = document.createElement("li");
    row.className = "checklist-item";
    if (item.checked) {
      row.classList.add("checklist-item--checked");
    }

    const input = document.createElement("input");
    input.id = `checklist-${item.key}`;
    input.type = "checkbox";
    input.checked = item.checked;
    input.disabled =
      store.busy ||
      store.checklistSyncing ||
      store.checklistBusy.has(item.key);
    input.setAttribute("aria-describedby", `checklist-${item.key}-hint`);
    input.addEventListener("change", () => {
      updateChecklistItem(item.key, input.checked);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        updateChecklistItem(item.key, !input.checked);
      }
    });

    const label = document.createElement("label");
    label.htmlFor = input.id;
    const text = document.createElement("strong");
    text.textContent = item.label;
    const hint = document.createElement("small");
    hint.id = `checklist-${item.key}-hint`;
    hint.textContent = item.suggested
      ? "系統已有資料，請自行核對"
      : "等待更多資料，也可由你自行勾選";
    label.append(text, hint);
    row.append(input, label);
    return row;
  });
  elements.checklistList.replaceChildren(...nodes);

  const checkedCount = checklist.filter((item) => item.checked).length;
  elements.checklistSummary.textContent =
    `${checkedCount} / ${checklist.length}`;

  if (activeId.startsWith("checklist-")) {
    window.requestAnimationFrame(() => {
      document.querySelector(`#${activeId}`)?.focus({ preventScroll: true });
    });
  }
}

function renderMessages() {
  const messages = store.session.messages || [];
  const lastMessage = messages.at(-1);
  const signature = [
    store.session.session_id,
    messages.length,
    lastMessage?.role || "",
    lastMessage?.text || "",
  ].join(":");
  const shouldRevealLatest = signature !== store.lastMessageSignature;
  store.lastMessageSignature = signature;
  const nodes = messages.map((message) => {
    const article = document.createElement("article");
    article.className = `message message--${message.role}`;

    const avatar = document.createElement("span");
    avatar.className = "message__avatar";
    avatar.textContent = message.role === "assistant" ? "AI" : "你";
    avatar.setAttribute("aria-hidden", "true");

    const bubble = document.createElement("div");
    bubble.className = "message__bubble";
    bubble.textContent = message.text;

    article.append(avatar, bubble);
    return article;
  });
  elements.messageList.replaceChildren(...nodes);
  if (shouldRevealLatest) {
    requestAnimationFrame(() => {
      const latestMessage = elements.messageList.lastElementChild;
      const scrollRegion = elements.conversationScrollRegion;
      if (!latestMessage || !scrollRegion) {
        return;
      }
      const messageBounds = latestMessage.getBoundingClientRect();
      const regionBounds = scrollRegion.getBoundingClientRect();
      let delta = 0;
      if (messageBounds.bottom > regionBounds.bottom) {
        delta = messageBounds.bottom - regionBounds.bottom + 16;
      } else if (messageBounds.top < regionBounds.top) {
        delta = messageBounds.top - regionBounds.top - 16;
      }
      if (delta) {
        scrollRegion.scrollTo({
          top: scrollRegion.scrollTop + delta,
        });
      }
    });
  }
}

function toggleMediaEditor() {
  const analysis = currentMedia()?.analysis;
  if (!analysis?.confirmed || store.mediaBusy) {
    return;
  }
  store.mediaEditorExpanded = !store.mediaEditorExpanded;
  renderMedia();
  if (store.mediaEditorExpanded) {
    requestAnimationFrame(() => {
      revealConversationSection(
        elements.mediaAnalysisForm,
        elements.mediaServiceQuery,
      );
    });
  }
}

function renderRouting() {
  const routing = store.session?.repair_routing;
  const candidates = routingCandidates();
  const needsConfirmation = Boolean(
    routing &&
      candidates.length &&
      (!routing.confirmed_branch || routing.replacement_pending),
  );
  elements.routingSection.hidden = !needsConfirmation;
  if (!needsConfirmation) {
    elements.routingOptions.replaceChildren();
    return;
  }
  elements.routingGuidance.textContent = routing.replacement_pending
    ? "切換後會清除舊分支答案與圖片分析；地點與時段會保留並要求重新核對。"
    : candidates.length > 1
      ? "偵測到多個項目，本 session 只處理一項，請先選擇。"
      : `系統信心為 ${routing.confidence}；任何信心等級都必須由你確認。`;
  elements.routingOptions.replaceChildren(
    ...candidates.map((branch) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "primary-button";
      button.textContent = `確認處理：${branchLabel(branch)}`;
      button.disabled = isSessionMutationBlocked();
      button.addEventListener("click", () => confirmBranch(branch, true));
      return button;
    }),
  );
  elements.routingReject.textContent = routing.replacement_pending
    ? "保留目前分支"
    : "這些都不是";
}

function routingCandidates() {
  const routing = store.session?.repair_routing;
  if (!routing) {
    return [];
  }
  return [...new Set([
    routing.repair_branch,
    ...(routing.alternatives || []),
  ].filter(Boolean))];
}

function renderForm() {
  const form = store.session.consultation_form;
  const formLocked =
    (store.session.candidates || []).length > 0 ||
    store.session.state === "no_candidates" ||
    Boolean(store.session.dispatch);
  if (!form || formLocked) {
    elements.formSection.hidden = true;
    if (store.formSignature) {
      elements.formFields.replaceChildren();
    }
    store.formSignature = "";
    store.visibleFormSignature = "";
    return;
  }

  const signature = consultationFormSignature(form);
  const shouldReveal = signature !== store.visibleFormSignature;
  elements.formSection.hidden = false;
  elements.formTitle.textContent = form.name;
  elements.formDescription.textContent = form.description || "";
  if (signature !== store.formSignature) {
    const topics = [...form.topics].sort(
      (left, right) => left.sort_order - right.sort_order,
    );
    elements.formFields.replaceChildren(...topics.map(renderTopic));
    store.formSignature = signature;
  }
  store.visibleFormSignature = signature;
  if (shouldReveal) {
    announce("諮詢單已準備完成，請填寫必填欄位。");
    revealConversationSection(elements.formSection, elements.formTitle);
  }
}

function consultationFormSignature(form) {
  return JSON.stringify({
    sessionId: store.session?.session_id || "",
    formKey: form.form_key,
    formVersion: form.version,
    branch: store.session?.active_task?.branch || "",
    topics: [...form.topics]
      .sort((left, right) => left.sort_order - right.sort_order)
      .map((topic) => ({
        key: topic.topic_key,
        type: topic.input_type,
        required: topic.is_required,
        options: (topic.options || []).map((option) => option.value),
      })),
  });
}

function renderTopic(topic) {
  const group =
    topic.input_type === "single_select" ||
    topic.input_type === "multi_select"
      ? document.createElement("fieldset")
      : document.createElement("div");
  group.className = "field-group";
  group.dataset.topicKey = topic.topic_key;

  if (isDateTimeTopic(topic) || topic.topic_key === "notes") {
    group.classList.add("field-group--wide");
  }

  if (isDateTimeTopic(topic)) {
    renderDateTimeTopic(group, topic);
  } else if (
    topic.input_type === "single_select" ||
    topic.input_type === "multi_select"
  ) {
    renderChoiceTopic(group, topic);
  } else {
    renderTextTopic(group, topic);
  }

  const error = document.createElement("p");
  error.className = "field-error";
  error.dataset.fieldError = topic.topic_key;
  error.hidden = true;
  group.append(error);
  return group;
}

function labelContent(topic) {
  const fragment = document.createDocumentFragment();
  fragment.append(document.createTextNode(topic.title));
  if (topic.is_required) {
    const required = document.createElement("em");
    required.textContent = "＊";
    fragment.append(required);
  }
  return fragment;
}

function renderChoiceTopic(group, topic) {
  const legend = document.createElement("legend");
  legend.append(labelContent(topic));
  group.append(legend);

  const grid = document.createElement("div");
  grid.className = "option-grid";
  topic.options.forEach((option, index) => {
    const label = document.createElement("label");
    label.className = "option-control";

    const input = document.createElement("input");
    input.type = topic.input_type === "single_select" ? "radio" : "checkbox";
    input.name = `answer:${topic.topic_key}`;
    input.value = option.value;
    const savedValue = store.session.answers?.[topic.topic_key];
    input.checked = Array.isArray(savedValue)
      ? savedValue.includes(option.value)
      : savedValue === option.value ||
        (topic.topic_key === "issue_category" &&
          store.session.active_task?.branch === option.value);
    input.required = Boolean(
      topic.is_required && topic.input_type === "single_select" && index === 0,
    );

    const text = document.createElement("span");
    text.textContent = option.label;
    label.append(input, text);
    grid.append(label);
  });
  group.append(grid);
}

function renderTextTopic(group, topic) {
  const label = document.createElement("label");
  label.className = "field-label";
  label.htmlFor = `field-${topic.topic_key}`;
  label.append(labelContent(topic));

  const input =
    topic.topic_key === "notes"
      ? document.createElement("textarea")
      : document.createElement("input");
  input.id = `field-${topic.topic_key}`;
  input.name = `answer:${topic.topic_key}`;
  input.required = topic.is_required;
  input.maxLength = 1000;
  input.className =
    topic.topic_key === "notes" ? "text-area" : "text-input";
  if (input.tagName === "INPUT") {
    input.type = "text";
  } else {
    input.rows = 3;
  }
  const savedValue = store.session.answers?.[topic.topic_key];
  if (typeof savedValue === "string") {
    input.value = savedValue;
  }

  group.append(label, input);
}

function renderDateTimeTopic(group, topic) {
  const label = document.createElement("span");
  label.className = "field-label";
  label.append(labelContent(topic));

  const grid = document.createElement("div");
  grid.className = "datetime-grid";
  const start = createDateTimePart(
    "開始",
    "preferred_start",
    store.session.preferred_start || topic.config?.suggested_start,
  );
  const separator = document.createElement("span");
  separator.textContent = "至";
  const end = createDateTimePart(
    "結束",
    "preferred_end",
    store.session.preferred_end || topic.config?.suggested_end,
  );
  grid.append(start, separator, end);

  const timezone = document.createElement("small");
  timezone.className = "timezone-note";
  timezone.textContent = "時區：Asia/Taipei（UTC+8）";
  group.append(label, grid, timezone);
}

function createDateTimePart(labelText, name, suggestedValue) {
  const wrapper = document.createElement("div");
  wrapper.className = "datetime-part";

  const label = document.createElement("label");
  label.htmlFor = name;
  label.textContent = labelText;

  const input = document.createElement("input");
  input.id = name;
  input.name = name;
  input.type = "datetime-local";
  input.className = "datetime-input";
  input.required = true;
  input.step = "900";
  if (suggestedValue) {
    input.value = isoToLocalInput(suggestedValue);
  }
  wrapper.append(label, input);
  return wrapper;
}

function collectFormPayload(form) {
  const answers = {};
  const fieldErrors = {};
  let preferredStart = "";
  let preferredEnd = "";

  for (const topic of form.topics) {
    if (isDateTimeTopic(topic)) {
      preferredStart = elements.consultationForm.elements.preferred_start.value;
      preferredEnd = elements.consultationForm.elements.preferred_end.value;
      continue;
    }
    const controls = [
      ...elements.consultationForm.querySelectorAll(
        `[name="answer:${cssEscape(topic.topic_key)}"]`,
      ),
    ];
    if (topic.input_type === "single_select") {
      answers[topic.topic_key] =
        controls.find((control) => control.checked)?.value || "";
    } else if (topic.input_type === "multi_select") {
      answers[topic.topic_key] = controls
        .filter((control) => control.checked)
        .map((control) => control.value);
    } else {
      answers[topic.topic_key] = controls[0]?.value?.trim() || "";
    }
    if (
      topic.is_required &&
      (answers[topic.topic_key] === "" ||
        (Array.isArray(answers[topic.topic_key]) &&
          answers[topic.topic_key].length === 0))
    ) {
      fieldErrors[topic.topic_key] = "此欄位為必填。";
    }
  }

  if (!preferredStart || !preferredEnd) {
    fieldErrors.preferred_time = "請選擇開始與結束時間。";
  }
  if (Object.keys(fieldErrors).length > 0) {
    const error = new Error("請完成必填欄位後再送出。");
    error.fields = fieldErrors;
    showFormError(error);
    return null;
  }
  return {
    answers,
    preferred_start: toTaipeiIso(preferredStart),
    preferred_end: toTaipeiIso(preferredEnd),
  };
}

function renderSummary() {
  const summary = store.session?.active_task?.summary;
  elements.summarySection.hidden = !summary;
  if (!summary) {
    elements.summaryDetails.replaceChildren();
    elements.summaryAnswers.replaceChildren();
    return;
  }
  elements.summaryVersion.textContent = `版本 ${summary.version}${summary.confirmed ? " · 已確認" : " · 待確認"}`;
  elements.summaryGuidance.textContent = summary.confirmed
    ? "此版本已確認並完成媒合；派單仍需另外明確確認。"
    : "如需修改，請直接更改上方表單並重新儲存；只有最新版本可確認媒合。";
  elements.summaryDetails.replaceChildren(
    definitionItem("服務", `${summary.service_name}（ID ${summary.canonical_service_id}）`),
    definitionItem("分支", branchLabel(summary.branch)),
    definitionItem("地點", summary.location_name),
    definitionItem("希望時段", formatWindow(summary.preferred_start, summary.preferred_end)),
    definitionItem("表單版本", `${summary.form_key} v${summary.form_version}`),
    definitionItem("Demo 聯絡", summary.synthetic_contact),
  );
  const answerEntries = Object.entries(summary.answers || {});
  elements.summaryAnswers.replaceChildren(
    ...(answerEntries.length
      ? answerEntries.map(([key, value]) => {
          const item = document.createElement("li");
          item.textContent = `${fieldLabel(key)}：${Array.isArray(value) ? value.join("、") : answerStateLabel(value)}`;
          return item;
        })
      : [textListItem("尚無表單答案")]),
  );
  elements.summaryConfirm.hidden = summary.confirmed;
  elements.summaryConfirm.disabled =
    isSessionMutationBlocked() || !store.session.can_confirm_summary;
}

function renderDispatch() {
  const dispatch = store.session.dispatch;
  elements.dispatchStatus.hidden = !dispatch;
  if (!dispatch) {
    store.lastDispatchSignature = "";
    elements.workflowNote.textContent =
      "尚未建立案件；確認候選後才會送出派單。";
    return;
  }

  elements.dispatchStatus.dataset.status = dispatch.status;
  const copy = {
    pending_provider: {
      title: "等待廠商回覆",
      text: `案件已指定給 ${dispatch.provider_name}，廠商接單前只會看到遮罩聯絡資料。`,
      note: "案件已建立；重新開始會建立另一個新諮詢。",
    },
    accepted: {
      title: "廠商已接單",
      text: `${dispatch.provider_name} 已接受案件，synthetic Demo 訂單已建立。`,
      note: "接單完成；原案件與稽核紀錄會保留。",
    },
    rejected: {
      title: "廠商未接案",
      text: `${dispatch.provider_name} 已拒絕，本次沒有揭露完整聯絡資料。`,
      note: "可改選尚未拒絕的其他候選廠商。",
    },
  }[dispatch.status];
  elements.dispatchStatusTitle.textContent = copy.title;
  elements.dispatchStatusCopy.textContent = copy.text;
  elements.workflowNote.textContent = copy.note;
  elements.dispatchStatusDetails.replaceChildren(
    definitionItem("案件編號", dispatch.case_id),
    definitionItem("廠商", dispatch.provider_name),
    definitionItem("訂單編號", dispatch.order_no || "尚未建立"),
  );
  const signature = `${dispatch.case_id}:${dispatch.status}`;
  if (signature !== store.lastDispatchSignature) {
    store.lastDispatchSignature = signature;
    announce(`${copy.title}。${copy.text}`);
  }
}

function renderCandidates() {
  const candidates = store.session.candidates || [];
  const dispatch = store.session.dispatch;
  const rejected = new Set(dispatch?.rejected_provider_ids || []);
  elements.candidateCount.textContent = String(candidates.length);
  elements.mobileCandidateCount.textContent = String(candidates.length);
  elements.candidateEmpty.hidden = candidates.length > 0;
  elements.candidateList.replaceChildren(
    ...candidates.map((candidate, index) =>
      renderCandidate(candidate, index, rejected),
    ),
  );

  const selected = candidates.find(
    (candidate) => candidate.provider_id === store.selectedProviderId,
  );
  elements.dispatchConfirmation.hidden = !selected;
  if (selected) {
    elements.dispatchConfirmationTitle.textContent =
      `派給 ${selected.display_name}`;
    elements.dispatchConfirmationCopy.textContent =
      "送出後會建立 synthetic 案件並等待此廠商回覆；接單前只提供遮罩聯絡資料。";
  }
}

function renderCandidate(candidate, index, rejected) {
  const card = document.createElement("article");
  card.className = "candidate-card";
  const hasRejected = rejected.has(candidate.provider_id);
  if (hasRejected) {
    card.classList.add("candidate-card--unavailable");
  }

  const header = document.createElement("header");
  header.className = "candidate-card__header";
  const title = document.createElement("h3");
  title.textContent = candidate.display_name;
  const source = document.createElement("span");
  source.className = "source-label";
  source.textContent = candidate.source_type;
  header.append(title, source);

  const score = document.createElement("div");
  score.className = "score-row";
  const scoreLabel = document.createElement("span");
  scoreLabel.textContent = index === 0 ? "首選" : "媒合";
  const track = document.createElement("span");
  track.className = "score-track";
  const fill = document.createElement("span");
  fill.className = "score-fill";
  fill.style.width = `${Math.round(candidate.match_score * 100)}%`;
  track.append(fill);
  const scoreValue = document.createElement("strong");
  scoreValue.textContent = `${Math.round(candidate.match_score * 100)}%`;
  score.append(scoreLabel, track, scoreValue);

  const metrics = document.createElement("div");
  metrics.className = "candidate-metrics";
  metrics.append(
    metric("評分", candidate.rating.toFixed(1)),
    metric("完工", `${candidate.completed_jobs} 件`),
    metric("勘查費", formatCurrency(candidate.base_inspection_fee)),
  );

  const time = document.createElement("div");
  time.className = "candidate-time";
  const timeLabel = document.createElement("small");
  timeLabel.textContent = `${candidate.location_name} · 可服務時段`;
  const timeValue = document.createElement("time");
  timeValue.dateTime = candidate.starts_at;
  timeValue.textContent = formatWindow(
    candidate.starts_at,
    candidate.ends_at,
  );
  time.append(timeLabel, timeValue);

  const reasons = document.createElement("ul");
  reasons.className = "candidate-reasons";
  (candidate.reasons || []).slice(0, 3).forEach((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    reasons.append(item);
  });

  const action = document.createElement("footer");
  action.className = "candidate-card__action";
  const actionStatus = document.createElement("small");
  const dispatch = store.session.dispatch;
  const isCurrent = dispatch?.provider_id === candidate.provider_id;
  if (hasRejected) {
    actionStatus.textContent = "此廠商已拒絕本案件";
  } else if (isCurrent && dispatch.status === "pending_provider") {
    actionStatus.textContent = "等待此廠商回覆";
  } else if (isCurrent && dispatch.status === "accepted") {
    actionStatus.textContent = "此廠商已接單";
  } else if (!store.session.can_dispatch) {
    actionStatus.textContent = "目前不可再次派單";
  } else {
    actionStatus.textContent = "確認後才會建立案件";
  }
  action.append(actionStatus);

  if (store.session.can_dispatch && !hasRejected) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary-button";
    button.dataset.providerSelect = candidate.provider_id;
    button.textContent =
      store.selectedProviderId === candidate.provider_id
        ? "已選擇"
        : "選擇此廠商";
    button.disabled = store.busy;
    button.addEventListener("click", () => {
      selectCandidate(candidate.provider_id);
    });
    action.append(button);
  }

  card.append(header, score, metrics, time, reasons, action);
  return card;
}

function branchLabel(branch) {
  return {
    faucet_leak: "水龍頭漏水",
    toilet_issue: "馬桶問題",
    pipe_issue: "水管問題",
    electrical_issue: "插座、燈具或電路問題",
    other: "其他水電問題",
  }[branch] || branch || "尚未確認";
}

function taskStatusLabel(status) {
  return {
    routing: "等待分支確認",
    collecting: "收集共用資料",
    replacement_pending: "等待切換確認",
    awaiting_form: "填寫表單",
    awaiting_summary_confirmation: "等待摘要確認",
    summary_confirmed: "摘要已確認",
    matched: "媒合完成",
    dispatched: "案件流程中",
    error: "需要重試",
  }[status] || status;
}

function fieldLabel(key) {
  return {
    canonical_service_id: "服務 ID",
    issue_category: "修繕分支",
    issue_description: "問題描述",
    water_shutoff: "可否關閉水源",
    county_name: "縣市",
    district_name: "行政區",
    preferred_start: "開始時間",
    preferred_end: "結束時間",
    preferred_time: "希望時段",
    budget: "預算",
    urgency: "緊急程度",
    repair_branch: "修繕分支",
    service: "服務",
    consultation_form: "諮詢表單",
    shared_slots_confirmation: "重新核對共用資料",
    summary_confirmation: "確認最新摘要",
  }[key] || key;
}

function answerStateLabel(value) {
  return {
    skipped: "略過／不知道",
    declined_to_answer: "不願回答",
  }[value] || value;
}

function textListItem(text) {
  const item = document.createElement("li");
  item.textContent = text;
  return item;
}

function fieldListNodes(fields, emptyText) {
  const entries = Object.entries(fields || {});
  if (!entries.length) {
    return [textListItem(emptyText)];
  }
  return entries.map(([key, value]) =>
    textListItem(
      `${fieldLabel(key)}：${Array.isArray(value) ? value.join("、") : answerStateLabel(value)}`,
    ),
  );
}

function missingFieldNodes(fields) {
  if (!Array.isArray(fields) || !fields.length) {
    return [textListItem("無")];
  }
  return fields.map((key) => textListItem(fieldLabel(key)));
}

function definitionItem(labelText, valueText) {
  const wrapper = document.createElement("div");
  const label = document.createElement("dt");
  label.textContent = labelText;
  const value = document.createElement("dd");
  value.textContent = valueText;
  wrapper.append(label, value);
  return wrapper;
}

function metric(labelText, valueText) {
  const wrapper = document.createElement("div");
  const label = document.createElement("small");
  label.textContent = labelText;
  const value = document.createElement("strong");
  value.textContent = valueText;
  wrapper.append(label, value);
  return wrapper;
}

function hasChecklistMutation() {
  return store.checklistBusy.size > 0 || store.checklistSyncing;
}

function isSessionMutationBlocked() {
  return store.busy || store.mediaBusy || hasChecklistMutation();
}

function updateControls() {
  const sessionMutationBlocked = isSessionMutationBlocked();
  const canSend = Boolean(store.session?.can_send_message);
  elements.messageForm.hidden = !canSend;
  elements.messageInput.disabled = sessionMutationBlocked || !canSend;
  elements.sendButton.disabled = sessionMutationBlocked || !canSend;
  elements.resetButton.disabled = sessionMutationBlocked;
  elements.resetButton.title = store.session?.dispatch
    ? "建立新諮詢"
    : "重新開始";
  elements.resetButton.setAttribute(
    "aria-label",
    elements.resetButton.title,
  );
  elements.confirmDispatch.disabled =
    sessionMutationBlocked ||
    !Boolean(store.selectedProviderId) ||
    !Boolean(store.session?.can_dispatch);
  elements.cancelDispatch.disabled = sessionMutationBlocked;
  document.querySelectorAll("[data-provider-select]").forEach((button) => {
    button.disabled = sessionMutationBlocked;
  });

  const submitButton =
    elements.consultationForm.querySelector('button[type="submit"]');
  if (submitButton) {
    submitButton.disabled =
      sessionMutationBlocked || !Boolean(store.session?.can_submit_form);
    submitButton.textContent = sessionMutationBlocked
      ? "處理中…"
      : "儲存並產生摘要 →";
  }
  if (elements.summaryConfirm) {
    elements.summaryConfirm.disabled =
      sessionMutationBlocked || !Boolean(store.session?.can_confirm_summary);
  }
  elements.routingReject.disabled = sessionMutationBlocked;
  elements.routingOptions
    .querySelectorAll("button")
    .forEach((button) => {
      button.disabled = sessionMutationBlocked;
    });
  renderMedia();
}

function setBusy(value, message = "") {
  store.busy = value;
  document.body.setAttribute("aria-busy", String(value));
  if (value && message) {
    announce(message);
  }
  if (store.session) {
    renderChecklist();
    updateControls();
  }
}

function setMobileView(view, { focusHeading = false } = {}) {
  document.body.dataset.mobileView = view;
  elements.mobileTabs.forEach((button) => {
    if (button.dataset.mobileTarget === view) {
      button.setAttribute("aria-current", "page");
      button.setAttribute("aria-pressed", "true");
    } else {
      button.removeAttribute("aria-current");
      button.setAttribute("aria-pressed", "false");
    }
  });
  if (focusHeading) {
    const heading = {
      progress: document.querySelector("#progress-title"),
      conversation: document.querySelector("#conversation-title"),
      candidates: document.querySelector("#candidates-title"),
    }[view];
    heading?.focus({ preventScroll: true });
  }
}

function showFormError(error) {
  clearFormErrors();
  elements.formError.textContent = error.message;
  elements.formError.hidden = false;
  Object.entries(error.fields || {}).forEach(([key, message]) => {
    const group = elements.formFields.querySelector(
      `[data-topic-key="${cssEscape(key)}"]`,
    );
    const errorNode = elements.formFields.querySelector(
      `[data-field-error="${cssEscape(key)}"]`,
    );
    if (group && errorNode) {
      group.classList.add("field-group--error");
      errorNode.textContent = message;
      errorNode.hidden = false;
      errorNode.id = `error-${key}`;
      group.querySelectorAll("input, textarea").forEach((control) => {
        control.setAttribute("aria-invalid", "true");
        control.setAttribute("aria-describedby", errorNode.id);
      });
    }
  });
  elements.formError.scrollIntoView({ block: "nearest" });
  const firstInvalid = elements.formFields.querySelector(
    '[aria-invalid="true"]',
  );
  (firstInvalid || elements.formError).focus?.();
}

function clearFormErrors() {
  elements.formError.hidden = true;
  elements.formError.textContent = "";
  elements.formFields
    .querySelectorAll(".field-group--error")
    .forEach((group) => group.classList.remove("field-group--error"));
  elements.formFields
    .querySelectorAll('[aria-invalid="true"]')
    .forEach((control) => {
      control.removeAttribute("aria-invalid");
      control.removeAttribute("aria-describedby");
    });
  elements.formFields.querySelectorAll(".field-error").forEach((node) => {
    node.hidden = true;
    node.textContent = "";
  });
}

function showAlert(message) {
  window.clearTimeout(store.alertTimer);
  elements.appAlert.textContent = message;
  elements.appAlert.hidden = false;
  store.alertTimer = window.setTimeout(() => {
    elements.appAlert.hidden = true;
  }, 6000);
}

function announce(message) {
  if (!elements.appStatus || !message) {
    return;
  }
  elements.appStatus.textContent = message;
}

function revealConversationSection(section, focusTarget) {
  requestAnimationFrame(() => {
    const scrollRegion = elements.conversationScrollRegion;
    if (!section || section.hidden || !scrollRegion) {
      return;
    }
    const sectionBounds = section.getBoundingClientRect();
    const regionBounds = scrollRegion.getBoundingClientRect();
    let delta = 0;
    if (sectionBounds.top < regionBounds.top) {
      delta = sectionBounds.top - regionBounds.top - 12;
    } else if (sectionBounds.bottom > regionBounds.bottom) {
      delta = Math.min(
        sectionBounds.top - regionBounds.top - 12,
        sectionBounds.bottom - regionBounds.bottom + 12,
      );
    }
    if (delta) {
      const reducedMotion = window.matchMedia?.(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      scrollRegion.scrollTo({
        top: Math.max(0, scrollRegion.scrollTop + delta),
        behavior: reducedMotion ? "auto" : "smooth",
      });
    }
    focusTarget?.focus({ preventScroll: true });
  });
}

function resetTransientConversationUi() {
  clearPreviewObjectUrl();
  store.mediaEditorExpanded = false;
  store.formSignature = "";
  store.visibleFormSignature = "";
  store.lastMessageSignature = "";
  if (elements.mediaFile) {
    elements.mediaFile.value = "";
  }
  if (elements.mediaConsent) {
    elements.mediaConsent.checked = false;
  }
  elements.mediaPreview?.removeAttribute("src");
  elements.mediaConfirmedPreview?.removeAttribute("src");
  if (elements.mediaStatus) {
    elements.mediaStatus.textContent = "";
  }
}

function resizeMessageInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(
    elements.messageInput.scrollHeight,
    128,
  )}px`;
}

function isDateTimeTopic(topic) {
  return topic.config?.control === "datetime_range";
}

function isoToLocalInput(value) {
  return String(value).slice(0, 16);
}

function toTaipeiIso(value) {
  return `${value}:00+08:00`;
}

function formatCurrency(value) {
  return new Intl.NumberFormat("zh-TW", {
    style: "currency",
    currency: "TWD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatWindow(startValue, endValue) {
  const dateFormatter = new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  });
  const timeFormatter = new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const start = new Date(startValue);
  const end = new Date(endValue);
  return `${dateFormatter.format(start)} ${timeFormatter.format(
    start,
  )}–${timeFormatter.format(end)}`;
}

function cssEscape(value) {
  if (window.CSS?.escape) {
    return window.CSS.escape(value);
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { SessionResponseCoordinator };
}
