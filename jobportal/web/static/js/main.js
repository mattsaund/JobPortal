/* Starts the dashboard. Loaded last, after every page file has registered its actions: it dispatches clicks and changes to
   those handlers, guards unsaved edits, then loads the app state and shows the first page. */
"use strict";

main.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  const action = el && ACTIONS[el.dataset.act];
  if (!action) return;
  try { await action(el, e); } catch (err) { toast("Something went wrong", err.message, "error"); }
});
main.addEventListener("change", async (e) => {
  for (const handle of CHANGE_HANDLERS) {
    try { if (await handle(e.target)) return; } catch (err) { toast("Something went wrong", err.message, "error"); return; }
  }
});
// Leaving with unsaved edits in an editor or in Settings asks first.
window.addEventListener("beforeunload", (e) => { if (S.dirty || S.cfgDirty) { e.preventDefault(); e.returnValue = ""; } });

(async function boot() {
  S.meta = await api("/api/meta");
  await refreshStats();
  S.state = S.stats.state;
  if (S.state.running) S.runStart = Date.now();
  renderAI(); renderAgents();
  try { S.pstatus = await api("/api/profile/status"); } catch (_) { S.pstatus = {}; }
  renderProfilePill();
  try { S.questions = await api("/api/questions"); } catch (_) {}
  try { const cfg = await api("/api/settings"); S.locAllowed = cfg.locations.allowed; S.industries = cfg.industries; } catch (_) {}
  try { // show the most recent run's log in the live feed after a reload
    const last = (await api("/api/runs"))[0];
    if (last) S.logs = (await api(`/api/runs/${last.id}/log`)).slice(-250);
  } catch (_) {}
  if (!/[?&]snapshot/.test(location.search)) connect(); // ?snapshot = no live stream (headless screenshots)
  route();
})();
