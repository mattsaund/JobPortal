/* The live connection to the server (Server-Sent Events from /api/events): run progress, new leads, profile changes,
   sign-in status and toasts arrive here and update whatever page is open. */
"use strict";

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  es.onerror = () => { es.close(); if (!S.quit) setTimeout(connect, 2500); };
}
const refreshSoon = debounce(() => { refreshStats(); if (S.route[0] === "leads") loadLeads(true); }, 2500);
function onEvent({ kind, data }) {
  if (kind === "state") {
    const wasRunning = S.state.running;
    S.state = data;
    if (data.running && !wasRunning) S.runStart = Date.now();
    renderAgents(); renderAI();
    if (S.route[0] === "leads") renderMission();
    if (wasRunning && !data.running) refreshSoon();
  } else if (kind === "log") {
    S.logs.push(data); if (S.logs.length > 600) S.logs.splice(0, S.logs.length - 600);
    appendLog(data);
  } else if (kind === "lead") {
    if (data && S.route[0] === "leads") upsertLead(data);
    if (data && S.route[0] === "lead" && +S.route[1] === data.id) renderLead(data.id, true);
    refreshSoon();
  } else if (kind === "toast") {
    toast(data.title, data.body, data.level || "", data.lead_id);
  } else if (kind === "ai") { onAIStatus(data); }
  else if (kind === "tokens") { S.state.tokens = data; renderAI(); if (S.route[0] === "leads") renderMission(); }
  else if (kind === "agents") { S.state.active_agents = data; renderAgents(); }
  else if (kind === "run_done") { toast(`Run #${data.run_id} ${data.status}`, `${data.stats.qualified || 0} qualified, ${data.stats.packaged || 0} packaged`); refreshSoon(); }
  else if (kind === "profile") { S.profileCache = null; if (S.route[0] === "profile" && !S.dirty && !["answers", "questions"].includes(S.ptab)) renderProfile(); }
  else if (kind === "profile_status") { onProfileStatus(data); }
  else if (kind === "questions") { S.questions = data; renderNav(); if (S.route[0] === "profile" && S.ptab === "questions" && !questionDraft()) renderProfile("questions"); }
  else if (kind === "analysis") { if (S.route[0] === "analysis") renderAnalysis(); }
}
