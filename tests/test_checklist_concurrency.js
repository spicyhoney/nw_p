"use strict";

const assert = require("node:assert/strict");
const {
  SessionResponseCoordinator,
} = require("../src/home_repair_agent/web/static/app.js");

function deferred() {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

function session(sessionId, serviceChecked, locationChecked) {
  return {
    session_id: sessionId,
    checklist: [
      { key: "service", checked: serviceChecked },
      { key: "location", checked: locationChecked },
    ],
  };
}

function olderResponseIsRejectedAfterANewerRequestStarts() {
  const coordinator = new SessionResponseCoordinator();
  const targetStore = { session: session("session-1", false, false) };
  const firstRequest = coordinator.begin("session-1");
  const secondRequest = coordinator.begin("session-1");

  assert.equal(
    coordinator.apply(
      targetStore,
      firstRequest,
      session("session-1", true, false),
    ),
    false,
  );
  assert.deepEqual(targetStore.session, session("session-1", false, false));
  assert.equal(
    coordinator.apply(
      targetStore,
      secondRequest,
      session("session-1", true, true),
    ),
    true,
  );
}

async function reversedChecklistResponsesKeepServerTruth() {
  const coordinator = new SessionResponseCoordinator();
  const targetStore = { session: session("session-1", false, false) };
  const first = deferred();
  const second = deferred();
  const firstRequest = coordinator.begin("session-1");
  const secondRequest = coordinator.begin("session-1");

  const firstTask = first.promise.then((response) =>
    coordinator.apply(targetStore, firstRequest, response),
  );
  const secondTask = second.promise.then((response) =>
    coordinator.apply(targetStore, secondRequest, response),
  );

  second.resolve(session("session-1", true, true));
  assert.equal(await secondTask, true);
  first.resolve(session("session-1", true, false));
  assert.equal(await firstTask, false);

  const serverState = session("session-1", true, true);
  const syncRequest = coordinator.begin("session-1");
  assert.equal(coordinator.apply(targetStore, syncRequest, serverState), true);
  assert.deepEqual(targetStore.session, serverState);
  assert.equal(
    targetStore.session.checklist.every((item) => item.checked),
    true,
  );
}

async function staleChecklistCannotOverwriteResetOrNewSession() {
  const coordinator = new SessionResponseCoordinator();
  const targetStore = { session: session("session-1", false, false) };

  const staleBeforeReset = coordinator.begin("session-1");
  const resetRequest = coordinator.begin("session-1");
  const resetState = session("session-1", false, false);
  assert.equal(coordinator.apply(targetStore, resetRequest, resetState), true);
  assert.equal(
    coordinator.apply(
      targetStore,
      staleBeforeReset,
      session("session-1", true, false),
    ),
    false,
  );
  assert.deepEqual(targetStore.session, resetState);

  const staleBeforeReplacement = coordinator.begin("session-1");
  const replacementRequest = coordinator.beginReplacement();
  const newSession = session("session-2", false, false);
  assert.equal(
    coordinator.apply(targetStore, replacementRequest, newSession),
    true,
  );
  assert.equal(
    coordinator.apply(
      targetStore,
      staleBeforeReplacement,
      session("session-1", true, true),
    ),
    false,
  );
  assert.deepEqual(targetStore.session, newSession);
}

Promise.resolve()
  .then(olderResponseIsRejectedAfterANewerRequestStarts)
  .then(reversedChecklistResponsesKeepServerTruth)
  .then(staleChecklistCannotOverwriteResetOrNewSession)
  .then(() => {
    console.log("checklist concurrency regression: passed");
  })
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
