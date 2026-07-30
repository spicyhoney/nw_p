const store = {
  session: null,
  busy: false,
  selectedProviderId: "",
  alertTimer: null,
  pollTimer: null,
  checklistBusy: new Set(),
  lastDispatchSignature: "",
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  bindElements();
  bindEvents();
  createSession();
});

function bindElements() {
  elements.providerChip = document.querySelector("#provider-chip");
  elements.resetButton = document.querySelector("#reset-button");
  elements.progressList = document.querySelector("#progress-list");
  elements.serviceSummary = document.querySelector("#service-summary");
  elements.locationSummary = document.querySelector("#location-summary");
  elements.checklistList = document.querySelector("#checklist-list");
  elements.checklistSummary = document.querySelector("#checklist-summary");
  elements.checklistFeedback = document.querySelector("#checklist-feedback");
  elements.traceList = document.querySelector("#trace-list");
  elements.workflowNote = document.querySelector("#workflow-note");
  elements.sessionState = document.querySelector("#session-state");
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
}

function bindEvents() {
  elements.messageForm.addEventListener("submit", handleMessageSubmit);
  elements.consultationForm.addEventListener("submit", handleFormSubmit);
  elements.resetButton.addEventListener("click", resetSession);
  elements.cancelDispatch.addEventListener("click", cancelDispatch);
  elements.confirmDispatch.addEventListener("click", confirmDispatch);
  elements.messageInput.addEventListener("input", resizeMessageInput);
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
  setBusy(true, "正在建立新諮詢。");
  try {
    stopSessionPolling();
    store.selectedProviderId = "";
    store.checklistBusy.clear();
    store.lastDispatchSignature = "";
    store.session = await api("/api/sessions", { method: "POST" });
    renderSession();
    announce("新諮詢已建立，可以開始描述修繕需求。");
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
  }
}

async function handleMessageSubmit(event) {
  event.preventDefault();
  if (!store.session || store.busy) {
    return;
  }
  const text = elements.messageInput.value.trim();
  if (!text) {
    return;
  }

  setBusy(true, "正在整理你的修繕需求。");
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ text }),
      },
    );
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

async function handleFormSubmit(event) {
  event.preventDefault();
  if (!store.session || store.busy || !store.session.consultation_form) {
    return;
  }

  clearFormErrors();
  const payload = collectFormPayload(store.session.consultation_form);
  if (!payload) {
    return;
  }

  setBusy(true, "正在核對表單並媒合師傅。");
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}/form`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
    renderSession();
    announce(`媒合完成，共有 ${store.session.candidates.length} 位候選。`);
    setMobileView("candidates", { focusHeading: true });
  } catch (error) {
    showFormError(error);
  } finally {
    setBusy(false);
  }
}

async function resetSession() {
  if (!store.session || store.busy) {
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
    store.session = await api(
      `/api/sessions/${store.session.session_id}/reset`,
      { method: "POST" },
    );
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
  if (!store.session || store.checklistBusy.has(itemKey)) {
    return;
  }

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
  announce(`正在儲存「${item?.label || "核對項目"}」。`);
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}/checklist/${encodeURIComponent(
        itemKey,
      )}`,
      {
        method: "PUT",
        body: JSON.stringify({ checked }),
      },
    );
    renderSession();
    const resultText = checked ? "已由你勾選" : "已由你取消勾選";
    elements.checklistFeedback.textContent =
      `${item?.label || "核對項目"}：${resultText}。`;
  } catch (error) {
    showAlert(error.message);
  } finally {
    store.checklistBusy.delete(itemKey);
    renderChecklist();
    window.requestAnimationFrame(() => {
      document.querySelector(`#${inputId}`)?.focus({ preventScroll: true });
    });
  }
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
    store.busy
  ) {
    return;
  }

  setBusy(true, "正在建立案件並通知所選廠商。");
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}/dispatch`,
      {
        method: "POST",
        body: JSON.stringify({
          provider_id: store.selectedProviderId,
          confirmed: true,
          idempotency_key:
            `dispatch:${store.session.session_id}:${store.selectedProviderId}`,
        }),
      },
    );
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
    store.busy ||
    store.session.dispatch?.status !== "pending_provider"
  ) {
    return;
  }
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}`,
    );
    renderSession();
    if (store.session.dispatch?.status !== "pending_provider") {
      stopSessionPolling();
    }
  } catch (error) {
    stopSessionPolling();
    showAlert(error.message);
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
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
  renderForm();
  renderDispatch();
  renderCandidates();
  updateControls();
}

function renderHeader() {
  const session = store.session;
  elements.providerChip.textContent = {
    mock: "Mock 模式",
    huggingface: "HF 模式",
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
    clarifying: "補充資料",
    awaiting_form: "填寫諮詢單",
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
    input.disabled = store.checklistBusy.has(item.key);
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
  const nodes = store.session.messages.map((message) => {
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
  requestAnimationFrame(() => {
    elements.messageList.scrollTop = elements.messageList.scrollHeight;
  });
}

function renderForm() {
  const form = store.session.consultation_form;
  const formCompleted = Object.keys(store.session.answers || {}).length > 0;
  if (!form || formCompleted) {
    elements.formSection.hidden = true;
    elements.formFields.replaceChildren();
    return;
  }

  elements.formSection.hidden = false;
  elements.formTitle.textContent = form.name;
  elements.formDescription.textContent = form.description || "";
  const topics = [...form.topics].sort(
    (left, right) => left.sort_order - right.sort_order,
  );
  elements.formFields.replaceChildren(...topics.map(renderTopic));
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
    topic.config?.suggested_start,
  );
  const separator = document.createElement("span");
  separator.textContent = "至";
  const end = createDateTimePart(
    "結束",
    "preferred_end",
    topic.config?.suggested_end,
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

function updateControls() {
  const canSend = Boolean(store.session?.can_send_message);
  elements.messageForm.hidden = !canSend;
  elements.messageInput.disabled = store.busy || !canSend;
  elements.sendButton.disabled = store.busy || !canSend;
  elements.resetButton.disabled = store.busy;
  elements.resetButton.title = store.session?.dispatch
    ? "建立新諮詢"
    : "重新開始";
  elements.resetButton.setAttribute(
    "aria-label",
    elements.resetButton.title,
  );
  elements.confirmDispatch.disabled =
    store.busy ||
    !Boolean(store.selectedProviderId) ||
    !Boolean(store.session?.can_dispatch);
  elements.cancelDispatch.disabled = store.busy;
  document.querySelectorAll("[data-provider-select]").forEach((button) => {
    button.disabled = store.busy;
  });

  const submitButton =
    elements.consultationForm.querySelector('button[type="submit"]');
  if (submitButton) {
    submitButton.disabled =
      store.busy || !Boolean(store.session?.can_submit_form);
    submitButton.textContent = store.busy ? "媒合中…" : "查看媒合結果 →";
  }
}

function setBusy(value, message = "") {
  store.busy = value;
  document.body.setAttribute("aria-busy", String(value));
  if (value && message) {
    announce(message);
  }
  if (store.session) {
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
