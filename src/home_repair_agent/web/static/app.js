const store = {
  session: null,
  busy: false,
  alertTimer: null,
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
  elements.traceList = document.querySelector("#trace-list");
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
  elements.candidateEmpty = document.querySelector("#candidate-empty");
  elements.candidateCount = document.querySelector("#candidate-count");
  elements.mobileCandidateCount = document.querySelector(
    "#mobile-candidate-count",
  );
  elements.appAlert = document.querySelector("#app-alert");
  elements.mobileTabs = [...document.querySelectorAll("[data-mobile-target]")];
}

function bindEvents() {
  elements.messageForm.addEventListener("submit", handleMessageSubmit);
  elements.consultationForm.addEventListener("submit", handleFormSubmit);
  elements.resetButton.addEventListener("click", resetSession);
  elements.messageInput.addEventListener("input", resizeMessageInput);
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.messageForm.requestSubmit();
    }
  });
  elements.mobileTabs.forEach((button) => {
    button.addEventListener("click", () => {
      setMobileView(button.dataset.mobileTarget);
    });
  });
}

async function createSession() {
  setBusy(true);
  try {
    store.session = await api("/api/sessions", { method: "POST" });
    renderSession();
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

  setBusy(true);
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

  setBusy(true);
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}/form`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
    renderSession();
    setMobileView("candidates");
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
  setBusy(true);
  try {
    store.session = await api(
      `/api/sessions/${store.session.session_id}/reset`,
      { method: "POST" },
    );
    renderSession();
    setMobileView("conversation");
    elements.messageInput.focus();
  } catch (error) {
    showAlert(error.message);
  } finally {
    setBusy(false);
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
  renderMessages();
  renderForm();
  renderCandidates();
  updateControls();
}

function renderHeader() {
  const session = store.session;
  elements.providerChip.textContent = session.provider.label;
  elements.providerChip.title = session.provider.is_external
    ? "外部 hosted model"
    : "本機規則式 Mock Model";
  const labels = {
    collecting_need: "確認需求",
    clarifying: "補充資料",
    awaiting_form: "填寫諮詢單",
    matched: "媒合完成",
    no_candidates: "暫無候選",
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

      const label = document.createElement("span");
      label.textContent = step.label;
      item.append(marker, label);
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
    input.required = Boolean(topic.is_required && index === 0);

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
  }

  if (!preferredStart || !preferredEnd) {
    showFormError(new Error("請選擇希望服務的開始與結束時間。"));
    return null;
  }
  return {
    answers,
    preferred_start: toTaipeiIso(preferredStart),
    preferred_end: toTaipeiIso(preferredEnd),
  };
}

function renderCandidates() {
  const candidates = store.session.candidates || [];
  elements.candidateCount.textContent = String(candidates.length);
  elements.mobileCandidateCount.textContent = String(candidates.length);
  elements.candidateEmpty.hidden = candidates.length > 0;
  elements.candidateList.replaceChildren(
    ...candidates.map((candidate, index) =>
      renderCandidate(candidate, index),
    ),
  );
}

function renderCandidate(candidate, index) {
  const card = document.createElement("article");
  card.className = "candidate-card";

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

  card.append(header, score, metrics, time, reasons);
  return card;
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

  const submitButton =
    elements.consultationForm.querySelector('button[type="submit"]');
  if (submitButton) {
    submitButton.disabled = store.busy;
    submitButton.textContent = store.busy ? "媒合中…" : "查看媒合結果 →";
  }
}

function setBusy(value) {
  store.busy = value;
  document.body.setAttribute("aria-busy", String(value));
  if (store.session) {
    updateControls();
  }
}

function setMobileView(view) {
  document.body.dataset.mobileView = view;
  elements.mobileTabs.forEach((button) => {
    if (button.dataset.mobileTarget === view) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
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
    }
  });
  elements.formError.scrollIntoView({ block: "nearest" });
}

function clearFormErrors() {
  elements.formError.hidden = true;
  elements.formError.textContent = "";
  elements.formFields
    .querySelectorAll(".field-group--error")
    .forEach((group) => group.classList.remove("field-group--error"));
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
