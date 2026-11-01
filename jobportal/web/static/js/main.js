/* main.js: starts the dashboard. It loads last, after every file has registered its actions. It holds the one click
   listener and the one change listener for the whole window (the page in <main>, the dialogs, the sidebar and the top
   bar), guards unsaved edits, loads what every page needs, connects the live stream and shows the first page. */
"use strict";

// Clicks: run the action of the nearest element with data-act (see onAction in core.js). An action that fails shows its
// error in a toast.
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  const action = el && ACTIONS[el.dataset.act];
  if (!action || el.disabled) return;
  try {
    await action(el, e);
  } catch (err) {
    toast("Something went wrong", err.message, "error");
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

// Reloading or closing with unsaved edits (an editor, a form, Settings or Sources) asks first.
window.addEventListener("beforeunload", (e) => {
  if (S.dirty || S.cfgDirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

// Loads what the frame and every page need, all at once. Anything that fails to load starts empty; the live events
// fill it in later.
(async function boot() {
  const quiet = (promise, fallback) => promise.catch(() => fallback);
  const [meta, , profileStatus, questions, onboarding, cfg, runs] = await Promise.all([
    api("/api/meta"), refreshStats(), quiet(api("/api/profile/status"), {}), quiet(api("/api/questions"), []),
    quiet(api("/api/onboarding"), null), quiet(api("/api/settings"), null), quiet(api("/api/runs"), []),
  ]);
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
