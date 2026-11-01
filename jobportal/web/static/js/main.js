/* main.js: starts the dashboard. It loads last, after every file has registered its actions. It holds the one click
   listener and the one change listener for the whole window (the page in <main>, the dialogs, the sidebar and the top
   bar), guards unsaved edits, loads what every page needs, connects the live stream and shows the first page.
   APIs, all at startup: GET /api/meta, GET /api/stats, GET /api/profile/status, GET /api/questions, GET /api/onboarding,
   GET /api/settings, GET /api/runs and GET /api/runs/{id}/log. */
"use strict";

// Clicks: run the action of the nearest element with data-act (see onAction in core.js). An action that fails shows its
// error in a toast. While an element's action is still running (most wait on the server), more clicks on that element
// are ignored, so a double click never saves, sends, adds or deletes twice.
const busy = new WeakSet();
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  const action = el && ACTIONS[el.dataset.act];
  if (!action || el.disabled || busy.has(el)) return;
  busy.add(el);
  try {
    await action(el, e);
  } catch (err) {
    toast("Something went wrong", err.message, "error");
  } finally {
    busy.delete(el);
  }
});

// Changes to selects, checkboxes and file pickers: offer the change to each onChange handler until one takes it.
document.addEventListener("change", async (e) => {
  for (const handle of CHANGE_HANDLERS) {
    try {
      if (await handle(e.target)) return;
    } catch (err) {
      toast("Something went wrong", err.message, "error");
      return;
    }
  }
});

// Reloading or closing with unsaved edits (an editor, a form, an answer on Home, Settings or Sources) asks first.
window.addEventListener("beforeunload", (e) => {
  if (S.dirty || S.cfgDirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

// Loads what the frame and every page need, all at once. Anything that fails to load starts empty; the live events
// fill it in later. Only the facts from GET /api/meta are a must (the statuses, the menus): without them the page says
// what went wrong, with a button to try again, instead of staying blank.
(async function boot() {
  const quiet = (promise, fallback) => promise.catch(() => fallback);
  let meta, profileStatus, questions, onboarding, cfg, runs;
  try {
    [meta, , profileStatus, questions, onboarding, cfg, runs] = await Promise.all([
      api("/api/meta"), refreshStats(), quiet(api("/api/profile/status"), {}), quiet(api("/api/questions"), []),
      quiet(api("/api/onboarding"), null), quiet(api("/api/settings"), null), quiet(api("/api/runs"), []),
    ]);
  } catch (err) {
    main.innerHTML = `<div class="empty-state quit"><h3>JobPortal couldn't start</h3><p>${esc(err.message)}</p>`
      + `<button class="button primary" type="button" data-act="reload-app">${icon("refresh")}Try again</button></div>`;
    return;
  }
  S.meta = meta;
  S.state = S.stats?.state || S.state;
  S.profileStatus = profileStatus;
  S.questions = questions;
  S.onboarding = onboarding;
  S.documents = onboarding?.documents || [];
  if (cfg) {
    S.searchArea = cfg.locations.allowed;
    S.industries = cfg.industries;
  }
  if (runs[0]) S.logs = (await quiet(api(`/api/runs/${runs[0].id}/log`), [])).slice(-250);  // the last search's feed
  renderFrame();
  if (!/[?&]snapshot/.test(location.search)) connect();  // ?snapshot leaves the live stream off (headless screenshots)
  route();
})();

onAction("reload-app", () => location.reload());  // Try again when startup failed: load the whole dashboard again
