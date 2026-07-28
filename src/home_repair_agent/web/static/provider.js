const providerStore = {
  identities: [],
  providerId: "",
  cases: [],
  selectedCaseId: "",
  detail: null,
  filter: "",
  busy: false,
  decision: "",
  alertTimer: null,
  pollTimer: null,
};

const providerElements = {};

document.addEventListener("DOMContentLoaded", () => {
  bindProviderElements();
  bindProviderEvents();
  initializeProviderWorkspace();
});

function bindProviderElements() {
  providerElements.identity = document.querySelector("#provider-identity");
  providerElements.refresh = document.querySelector("#refresh-button");
  providerElements.statusTabs = [
    ...document.querySelectorAll("[data-status]"),
  ];
  providerElements.countAll = document.querySelector("#count-all");
  providerElements.countPending = document.querySelector("#count-pending");
  providerElements.countAccepted = document.querySelector("#count-accepted");
  providerElements.countRejected = document.querySelector("#count-rejected");
  providerElements.lastUpdated = document.querySelector("#last-updated");
  providerElements.caseList = document.querySelector("#case-list");
  providerElements.caseEmpty = document.querySelector("#case-empty");
  providerElements.detailEmpty = document.querySelector("#detail-empty");
  providerElements.detailContent = document.querySelector("#detail-content");
  providerElements.detailCaseId = document.querySelector("#detail-case-id");
  providerElements.detailOrder = document.querySelector("#detail-order");
  providerElements.detailStatus = document.querySelector("#detail-status");
  providerElements.detailService = document.querySelector("#detail-service");
  providerElements.detailLocation = document.querySelector("#detail-location");
  providerElements.detailWindow = document.querySelector("#detail-window");
  providerElements.detailSummary = document.querySelector("#detail-summary");
  providerElements.answerList = document.querySelector("#answer-list");
  providerElements.contactSection = document.querySelector("#contact-section");
  providerElements.contactAccess = document.querySelector("#contact-access");
  providerElements.contactList = document.querySelector("#contact-list");
  providerElements.auditList = document.querySelector("#audit-list");
  providerElements.decisionActions = document.querySelector(
    "#decision-actions",
  );
  providerElements.decisionButtons = [
    ...document.querySelectorAll("[data-decision]"),
  ];
  providerElements.dialog = document.querySelector("#decision-dialog");
  providerElements.decisionTitle = document.querySelector("#decision-title");
  providerElements.decisionMessage =
    document.querySelector("#decision-message");
  providerElements.confirmDecision =
    document.querySelector("#confirm-decision");
  providerElements.appAlert = document.querySelector("#app-alert");
}

function bindProviderEvents() {
  providerElements.identity.addEventListener("change", async () => {
    providerStore.providerId = providerElements.identity.value;
    providerStore.selectedCaseId = "";
    providerStore.detail = null;
    window.localStorage.setItem(
      "home-repair-demo-provider",
      providerStore.providerId,
    );
    await loadProviderCases();
  });
  providerElements.refresh.addEventListener("click", loadProviderCases);
  providerElements.statusTabs.forEach((button) => {
    button.addEventListener("click", async () => {
      await updateProviderFilter(button);
    });
  });
  providerElements.decisionButtons.forEach((button) => {
    button.addEventListener("click", () => {
      openDecisionDialog(button.dataset.decision);
    });
  });
  providerElements.confirmDecision.addEventListener(
    "click",
    confirmProviderDecision,
  );
  window.addEventListener("beforeunload", () => {
    window.clearInterval(providerStore.pollTimer);
  });
}

async function initializeProviderWorkspace() {
  setProviderBusy(true);
  try {
    const response = await providerApi("/api/provider/identities");
    providerStore.identities = response.identities || [];
    if (!providerStore.identities.length) {
      throw new Error("目前沒有可用的 synthetic 廠商身分。");
    }
    const saved = window.localStorage.getItem("home-repair-demo-provider");
    providerStore.providerId = providerStore.identities.some(
      (identity) => identity.provider_id === saved,
    )
      ? saved
      : providerStore.identities[0].provider_id;
    renderProviderIdentities();
    setProviderBusy(false);
    await loadProviderCases();
    providerStore.pollTimer = window.setInterval(loadProviderCases, 3000);
  } catch (error) {
    showProviderAlert(error.message);
  } finally {
    setProviderBusy(false);
  }
}

function renderProviderIdentities() {
  providerElements.identity.replaceChildren(
    ...providerStore.identities.map((identity) => {
      const option = document.createElement("option");
      option.value = identity.provider_id;
      option.textContent = identity.display_name;
      option.selected = identity.provider_id === providerStore.providerId;
      return option;
    }),
  );
}

async function loadProviderCases() {
  if (!providerStore.providerId || providerStore.busy) {
    return;
  }
  setProviderBusy(true);
  try {
    const response = await providerApi("/api/provider/cases", {
      provider: true,
    });
    providerStore.cases = response.cases || [];
    reconcileProviderSelection();
    renderProviderCounts();
    renderProviderCaseList();
    providerElements.lastUpdated.textContent =
      `更新 ${new Intl.DateTimeFormat("zh-TW", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date())}`;
    if (providerStore.selectedCaseId) {
      await loadProviderDetail(providerStore.selectedCaseId);
    } else {
      renderProviderDetail();
    }
  } catch (error) {
    showProviderAlert(error.message);
  } finally {
    setProviderBusy(false);
  }
}

async function updateProviderFilter(button) {
  if (providerStore.busy) {
    return;
  }
  providerStore.filter = button.dataset.status;
  providerElements.statusTabs.forEach((item) => {
    item.setAttribute(
      "aria-pressed",
      String(item === button),
    );
  });
  const selectionChanged = reconcileProviderSelection();
  renderProviderCaseList();
  if (!selectionChanged) {
    return;
  }

  renderProviderDetail();
  if (!providerStore.selectedCaseId) {
    return;
  }
  setProviderBusy(true);
  try {
    await loadProviderDetail(providerStore.selectedCaseId);
  } catch (error) {
    showProviderAlert(error.message);
  } finally {
    setProviderBusy(false);
  }
}

function visibleProviderCases() {
  return providerStore.filter
    ? providerStore.cases.filter(
        (item) => item.status === providerStore.filter,
      )
    : providerStore.cases;
}

function reconcileProviderSelection() {
  const visible = visibleProviderCases();
  const selectedIsVisible = visible.some(
    (item) => item.case_id === providerStore.selectedCaseId,
  );
  if (selectedIsVisible) {
    return false;
  }
  providerStore.selectedCaseId = visible[0]?.case_id || "";
  providerStore.detail = null;
  return true;
}

async function selectProviderCase(caseId) {
  if (providerStore.busy) {
    return;
  }
  providerStore.selectedCaseId = caseId;
  renderProviderCaseList();
  setProviderBusy(true);
  try {
    await loadProviderDetail(caseId);
    document.querySelector("#case-detail").scrollIntoView({
      block: "start",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  } catch (error) {
    showProviderAlert(error.message);
  } finally {
    setProviderBusy(false);
  }
}

async function loadProviderDetail(caseId) {
  providerStore.detail = await providerApi(
    `/api/provider/cases/${encodeURIComponent(caseId)}`,
    { provider: true },
  );
  renderProviderDetail();
}

function renderProviderCounts() {
  const counts = {
    pending_provider: 0,
    accepted: 0,
    rejected: 0,
  };
  providerStore.cases.forEach((item) => {
    counts[item.status] += 1;
  });
  providerElements.countAll.textContent = String(providerStore.cases.length);
  providerElements.countPending.textContent = String(
    counts.pending_provider,
  );
  providerElements.countAccepted.textContent = String(counts.accepted);
  providerElements.countRejected.textContent = String(counts.rejected);
}

function renderProviderCaseList() {
  const visible = visibleProviderCases();
  providerElements.caseEmpty.hidden = visible.length > 0;
  providerElements.caseList.replaceChildren(
    ...visible.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `case-item case-item--${item.status}`;
      button.setAttribute(
        "aria-current",
        String(item.case_id === providerStore.selectedCaseId),
      );
      button.addEventListener("click", () => {
        selectProviderCase(item.case_id);
      });

      const top = document.createElement("span");
      top.className = "case-item__top";
      const id = document.createElement("strong");
      id.textContent = item.case_id;
      const status = document.createElement("span");
      status.className = `status-label status-label--${item.status}`;
      status.textContent = statusLabel(item.status);
      top.append(id, status);

      const summary = document.createElement("span");
      summary.className = "case-item__summary";
      summary.textContent = item.problem_summary;

      const meta = document.createElement("span");
      meta.className = "case-item__meta";
      const location = document.createElement("span");
      location.textContent = item.location_name;
      const time = document.createElement("time");
      time.dateTime = item.preferred_start;
      time.textContent = formatProviderDate(item.preferred_start);
      meta.append(location, time);
      button.append(top, summary, meta);
      return button;
    }),
  );
}

function renderProviderDetail() {
  const detail = providerStore.detail;
  providerElements.detailEmpty.hidden = Boolean(detail);
  providerElements.detailContent.hidden = !detail;
  if (!detail) {
    return;
  }

  providerElements.detailCaseId.textContent = detail.case_id;
  providerElements.detailOrder.hidden = !detail.order_no;
  providerElements.detailOrder.textContent = detail.order_no
    ? `Demo 訂單 ${detail.order_no}`
    : "";
  providerElements.detailStatus.className =
    `status-label status-label--${detail.status}`;
  providerElements.detailStatus.textContent = statusLabel(detail.status);
  providerElements.detailService.textContent = detail.service_name;
  providerElements.detailLocation.textContent = detail.location_name;
  providerElements.detailWindow.textContent = formatProviderWindow(
    detail.preferred_start,
    detail.preferred_end,
  );
  providerElements.detailSummary.textContent = detail.problem_summary;
  providerElements.answerList.replaceChildren(
    ...Object.entries(detail.answers || {}).map(([key, value]) =>
      definition(answerLabel(key), answerValue(value)),
    ),
  );

  providerElements.contactSection.dataset.access = detail.contact.access;
  providerElements.contactAccess.className =
    `access-badge access-badge--${detail.contact.access}`;
  providerElements.contactAccess.textContent = contactAccessLabel(
    detail.contact.access,
  );
  const contactItems = [];
  if (detail.contact.access !== "unavailable") {
    contactItems.push(
      definition("聯絡人", detail.contact.name),
      definition("手機", detail.contact.mobile),
      definition("地址", detail.contact.address),
    );
  } else {
    contactItems.push(
      definition("狀態", "案件已拒絕，聯絡資料未揭露"),
    );
  }
  providerElements.contactList.replaceChildren(...contactItems);

  providerElements.auditList.replaceChildren(
    ...(detail.audit_events || []).map((event) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = event.label;
      const time = document.createElement("time");
      time.dateTime = event.created_at;
      time.textContent = formatProviderDateTime(event.created_at);
      item.append(label, time);
      return item;
    }),
  );
  providerElements.decisionActions.hidden =
    detail.status !== "pending_provider";
}

function definition(labelText, valueText) {
  const wrapper = document.createElement("div");
  const term = document.createElement("dt");
  term.textContent = labelText;
  const value = document.createElement("dd");
  value.textContent = valueText || "未提供";
  wrapper.append(term, value);
  return wrapper;
}

function openDecisionDialog(decision) {
  if (!providerStore.detail || providerStore.detail.status !== "pending_provider") {
    return;
  }
  providerStore.decision = decision;
  const accepting = decision === "accept";
  providerElements.decisionTitle.textContent = accepting
    ? "確認接受案件"
    : "確認拒絕案件";
  providerElements.decisionMessage.textContent = accepting
    ? "接單後會建立 synthetic Demo 訂單，並依規則揭露完整 synthetic 聯絡資料。"
    : "拒絕後不會揭露完整聯絡資料，消費者可改派其他候選廠商。";
  providerElements.confirmDecision.textContent = accepting
    ? "確認接單"
    : "確認拒絕";
  providerElements.confirmDecision.className = accepting
    ? "primary-button"
    : "secondary-button secondary-button--danger";
  providerElements.dialog.showModal();
}

async function confirmProviderDecision() {
  const detail = providerStore.detail;
  const decision = providerStore.decision;
  if (!detail || !decision || providerStore.busy) {
    return;
  }
  setProviderBusy(true);
  try {
    providerStore.detail = await providerApi(
      `/api/provider/cases/${encodeURIComponent(detail.case_id)}/decision`,
      {
        method: "POST",
        provider: true,
        body: JSON.stringify({
          decision,
          confirmed: true,
          idempotency_key: `${decision}:${detail.case_id}`,
        }),
      },
    );
    providerElements.dialog.close();
    providerStore.decision = "";
    setProviderBusy(false);
    await loadProviderCases();
  } catch (error) {
    showProviderAlert(error.message);
  } finally {
    setProviderBusy(false);
  }
}

async function providerApi(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (options.provider) {
    headers["X-Demo-Provider-Id"] = providerStore.providerId;
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
    const message =
      payload?.error?.message ||
      validationMessage(payload?.detail) ||
      "目前無法完成操作，請稍後再試。";
    throw new Error(message);
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

function setProviderBusy(value) {
  providerStore.busy = value;
  document.body.setAttribute("aria-busy", String(value));
  providerElements.identity.disabled = value;
  providerElements.refresh.disabled = value;
  providerElements.confirmDecision.disabled = value;
  providerElements.statusTabs.forEach((button) => {
    button.disabled = value;
  });
  providerElements.decisionButtons.forEach((button) => {
    button.disabled = value;
  });
}

function showProviderAlert(message) {
  window.clearTimeout(providerStore.alertTimer);
  providerElements.appAlert.textContent = message;
  providerElements.appAlert.hidden = false;
  providerStore.alertTimer = window.setTimeout(() => {
    providerElements.appAlert.hidden = true;
  }, 6000);
}

function statusLabel(status) {
  return {
    pending_provider: "待回覆",
    accepted: "已接單",
    rejected: "已拒絕",
  }[status] || "未知狀態";
}

function contactAccessLabel(access) {
  return {
    masked: "已遮罩",
    full: "已授權",
    unavailable: "未揭露",
  }[access] || "未知權限";
}

function answerLabel(key) {
  return {
    issue_category: "問題類型",
    notes: "其他備註",
  }[key] || key;
}

function answerValue(value) {
  return Array.isArray(value) ? value.join("、") : String(value);
}

function formatProviderDate(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "numeric",
    day: "numeric",
  }).format(new Date(value));
}

function formatProviderDateTime(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatProviderWindow(startValue, endValue) {
  const day = new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "short",
  });
  const time = new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const start = new Date(startValue);
  const end = new Date(endValue);
  return `${day.format(start)} ${time.format(start)}–${time.format(end)}`;
}
