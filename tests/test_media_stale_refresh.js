"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appPath = path.resolve(
  __dirname,
  "../src/home_repair_agent/web/static/app.js",
);
const source = fs.readFileSync(appPath, "utf8");

const documentStub = {
  activeElement: null,
  addEventListener() {},
  querySelectorAll() {
    return [];
  },
};

class FakeElement {
  constructor(name) {
    this.name = name;
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.textContent = "";
    this.src = "";
    this.scrollTop = 0;
    this.attributes = new Map();
    this.classList = {
      add() {},
      remove() {},
      toggle() {},
    };
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "src") {
      this.src = "";
    }
  }

  focus() {
    documentStub.activeElement = this;
  }

  getBoundingClientRect() {
    return { top: 20, bottom: 80 };
  }

  scrollTo({ top }) {
    this.scrollTop = top;
  }
}

function analysis(revision, serviceQuery, problemSummary, confirmed = false) {
  return {
    analysis_revision: revision,
    service_query: serviceQuery,
    problem_summary: problemSummary,
    safety_warnings: ["synthetic safety reminder"],
    confidence: 0.8,
    uncertain: true,
    confirmed,
  };
}

function session(mediaId, mediaAnalysis) {
  return {
    session_id: "session-stale-media",
    state: "awaiting_form",
    answers: {},
    active_task: { branch: "faucet_leak" },
    service: { name: "水電修繕" },
    location: null,
    consultation_form: null,
    media: {
      media_id: mediaId,
      analysis: mediaAnalysis,
    },
  };
}

const oldRevision = "revision-old-0001";
const latestRevision = "revision-new-0002";
const oldSession = session(
  "media-old",
  analysis(oldRevision, "舊服務建議", "舊問題摘要"),
);
const latestSession = session(
  "media-new",
  analysis(latestRevision, "最新服務建議", "最新問題摘要"),
);
const confirmedSession = session(
  "media-new",
  analysis(latestRevision, "最新服務建議", "最新問題摘要", true),
);

const requests = [];
let confirmationCount = 0;

async function fetchStub(requestPath, options = {}) {
  const method = options.method || "GET";
  requests.push({ path: requestPath, method, body: options.body || null });
  if (requestPath.endsWith("/image/confirm") && method === "POST") {
    confirmationCount += 1;
    if (confirmationCount === 1) {
      return {
        ok: false,
        async json() {
          return {
            error: {
              code: "IMAGE_CONFIRMATION_STALE",
              message: "圖片分析版本已更新。",
            },
          };
        },
      };
    }
    return {
      ok: true,
      async json() {
        return confirmedSession;
      },
    };
  }
  if (
    requestPath === "/api/sessions/session-stale-media" &&
    method === "GET"
  ) {
    return {
      ok: true,
      async json() {
        return latestSession;
      },
    };
  }
  throw new Error(`unexpected request: ${method} ${requestPath}`);
}

const context = vm.createContext({
  console,
  document: documentStub,
  fetch: fetchStub,
  FormData: class FakeFormData {},
  requestAnimationFrame(callback) {
    callback();
  },
  setTimeout,
  clearTimeout,
  URL: {
    createObjectURL() {
      return "blob:synthetic";
    },
    revokeObjectURL() {},
  },
  window: {
    addEventListener() {},
    matchMedia() {
      return { matches: true };
    },
  },
});
vm.runInContext(source, context, { filename: appPath });

const fakeElements = {};
for (const name of [
  "appStatus",
  "conversationScrollRegion",
  "mediaAnalysisForm",
  "mediaConfidence",
  "mediaConfirmButton",
  "mediaConfirmedCard",
  "mediaConfirmedNextStep",
  "mediaConfirmedPreview",
  "mediaConfirmedRemove",
  "mediaConfirmedService",
  "mediaConfirmedSummary",
  "mediaConfirmedTitle",
  "mediaConsent",
  "mediaEditToggle",
  "mediaFile",
  "mediaMode",
  "mediaPreview",
  "mediaPreviewPanel",
  "mediaProblemSummary",
  "mediaRemoveButton",
  "mediaSafetyWarnings",
  "mediaSection",
  "mediaServiceQuery",
  "mediaStatus",
  "mediaUploadButton",
  "mediaUploadForm",
]) {
  fakeElements[name] = new FakeElement(name);
}
fakeElements.conversationScrollRegion.getBoundingClientRect = () => ({
  top: 0,
  bottom: 500,
});

context.testElements = fakeElements;
context.testSession = oldSession;
vm.runInContext(
  `
    Object.assign(elements, testElements);
    store.session = testSession;
    store.mediaProvider = "huggingface";
    renderSession = () => renderMedia();
    updateControls = () => renderMedia();
    renderMedia();
  `,
  context,
);

async function run() {
  await vm.runInContext(
    "confirmMediaAnalysis({ preventDefault() {} })",
    context,
  );

  assert.equal(requests[0].method, "POST");
  assert.equal(
    requests[0].path,
    "/api/sessions/session-stale-media/image/confirm",
  );
  assert.deepEqual(JSON.parse(requests[0].body), {
    media_id: "media-old",
    analysis_revision: oldRevision,
    service_query: "舊服務建議",
    problem_summary: "舊問題摘要",
    safety_warnings: ["synthetic safety reminder"],
  });
  assert.equal(requests[1].method, "GET");
  assert.equal(requests[1].path, "/api/sessions/session-stale-media");
  assert.equal(
    vm.runInContext("store.session.media.media_id", context),
    "media-new",
  );
  assert.equal(
    vm.runInContext(
      "store.session.media.analysis.analysis_revision",
      context,
    ),
    latestRevision,
  );
  assert.equal(fakeElements.mediaServiceQuery.value, "最新服務建議");
  assert.equal(fakeElements.mediaProblemSummary.value, "最新問題摘要");
  assert.equal(documentStub.activeElement, fakeElements.mediaServiceQuery);

  await vm.runInContext(
    "confirmMediaAnalysis({ preventDefault() {} })",
    context,
  );

  const confirmations = requests.filter(
    (request) => request.path.endsWith("/image/confirm"),
  );
  assert.equal(confirmations.length, 2);
  const retriedPayload = JSON.parse(confirmations[1].body);
  assert.equal(retriedPayload.media_id, "media-new");
  assert.equal(retriedPayload.analysis_revision, latestRevision);
  assert.notEqual(retriedPayload.analysis_revision, oldRevision);
  assert.equal(retriedPayload.service_query, "最新服務建議");
  assert.equal(documentStub.activeElement, fakeElements.mediaConfirmedTitle);
  console.log("media stale refresh DOM regression: passed");

  const requestCountBeforeLockChecks = requests.length;
  vm.runInContext(
    `
      store.session.answers = { issue_description: "synthetic saved answer" };
      store.session.state = "awaiting_summary_confirmation";
      store.mediaEditorExpanded = true;
      renderMedia();
    `,
    context,
  );

  assert.equal(vm.runInContext("store.mediaEditorExpanded", context), false);
  assert.equal(fakeElements.mediaEditToggle.disabled, true);
  assert.equal(fakeElements.mediaEditToggle.textContent, "圖片分析已鎖定");
  assert.equal(fakeElements.mediaEditToggle.attributes.get("aria-expanded"), "false");
  assert.equal(fakeElements.mediaAnalysisForm.hidden, true);
  assert.equal(fakeElements.mediaServiceQuery.disabled, true);
  assert.equal(fakeElements.mediaProblemSummary.disabled, true);
  assert.equal(fakeElements.mediaSafetyWarnings.disabled, true);
  assert.equal(fakeElements.mediaConfirmButton.disabled, true);
  assert.match(fakeElements.mediaConfirmedNextStep.textContent, /已鎖定/);
  assert.match(fakeElements.mediaConfirmedNextStep.textContent, /重新開始/);
  assert.doesNotMatch(
    fakeElements.mediaConfirmedNextStep.textContent,
    /移除圖片再重新上傳/,
  );

  vm.runInContext("toggleMediaEditor()", context);
  await vm.runInContext(
    "confirmMediaAnalysis({ preventDefault() {} })",
    context,
  );

  assert.equal(requests.length, requestCountBeforeLockChecks);
  assert.equal(vm.runInContext("store.mediaEditorExpanded", context), false);
  assert.match(fakeElements.mediaStatus.textContent, /已鎖定/);
  assert.equal(documentStub.activeElement, fakeElements.mediaConfirmedTitle);
  console.log("media flow lock DOM regression: passed");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
