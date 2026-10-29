/* main.js: starts the dashboard. It loads last, after every page file has registered its actions. It holds the one click
   listener and the one change listener for <main>, guards unsaved edits, loads what every page needs, connects the live
   stream and shows the first page. */
"use strict";

// Clicks inside <main>: run the action of the nearest element with data-act (see onAction in core.js). An action that
// fails shows its error in a toast.
main.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  const action = el && ACTIONS[el.dataset.act];
  if (!action) return;
  try {
    await action(el, e);
  } catch (err) {
    toast("Something went wrong", err.message, "error");
  }
});

// Changes to selects and checkboxes inside <main>: offer the change to each onChange handler until one takes it.
main.addEventListener("change", async (e) => {
  for (const handle of CHANGE_HANDLERS) {
    try {
      if (await handle(e.target)) return;
    } catch (err) {
      toast("Something went wrong", err.message, "error");
      return;
    }
  }
});

// Reloading or closing with unsaved edits (in an editor, an answers form, Settings or Sources) asks first.
window.addEventListener("beforeunload", (e) => {
  if (S.dirty || S.cfgDirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

(async function boot() {
  S.meta = await api("/api/meta");
  await refreshStats();
  S.state = S.stats.state;
  renderAI();
  renderAgents();
  try { S.profileStatus = await api("/api/profile/status"); } catch (_) { S.profileStatus = {}; }
  renderProfilePill();
  try { S.questions = await api("/api/questions"); } catch (_) {}
  try {
    const cfg = await api("/api/settings");
    S.searchArea = cfg.locations.allowed;
    S.industries = cfg.industries;
  } catch (_) {}
  try {  // show the most recent run's log in the live feed after a reload
    const last = (await api("/api/runs"))[0];
    if (last) S.logs = (await api(`/api/runs/${last.id}/log`)).slice(-250);
  } catch (_) {}
  if (!/[?&]snapshot/.test(location.search)) connect();  // ?snapshot leaves the live stream off (headless screenshots)
  route();
})();
