/* live.js: the live connection to the server. The server pushes events over Server-Sent Events (GET /api/events, fed by
   core/bus.py): run progress, live feed lines, new and changed leads, profile changes, the ChatGPT sign-in status and
   toasts. onEvent() stores what changed in S and redraws the parts of the open page that show it. */
"use strict";

// Opens the event stream. When it drops (the server restarted, the computer slept), it reconnects after 2.5 seconds,
// unless you quit JobPortal from Settings.
function connect() {
  const events = new EventSource("/api/events");
  events.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch (err) {
      console.error(err);
    }
  };
  events.onerror = () => {
    events.close();
    if (!S.quit) setTimeout(connect, 2500);
  };
}

// A run sends many events close together. This refreshes the counts (and the lead list, when it's open) once, after
// 2.5 quiet seconds.
const refreshSoon = debounce(() => {
  refreshStats();
  if (S.route[0] === "leads") loadLeads(true);
}, 2500);

// Handles one event. kind says what happened and data carries the details.
function onEvent({ kind, data }) {
  switch (kind) {
    case "state": {  // the run state changed: a run started, moved to a new phase, counted more, or finished
      const wasRunning = S.state.running;
      S.state = data;
      renderAgents();
      renderAI();
      if (S.route[0] === "leads") renderMission();
      if (wasRunning && !data.running) refreshSoon();
      break;
    }
    case "log":  // one line for the live feed
      S.logs.push(data);
      if (S.logs.length > 600) S.logs.splice(0, S.logs.length - 600);
      appendLog(data);
      break;
    case "lead":  // a lead was added or changed. data is its summary, or null when many leads changed at once.
      if (data && S.route[0] === "leads") upsertLead(data);
      if (data && S.route[0] === "lead" && +S.route[1] === data.id) renderLead(data.id, true);
      refreshSoon();
      break;
    case "toast":
      toast(data.title, data.body, data.level || "", data.lead_id);
      break;
    case "ai":  // the ChatGPT sign-in status
      onAIStatus(data);
      break;
    case "tokens":  // the AI tokens used since JobPortal started
      S.state.tokens = data;
      renderAI();
      if (S.route[0] === "leads") renderMission();
      break;
    case "agents":  // the AI agents working right now
      S.state.active_agents = data;
      renderAgents();
      break;
    case "run_done":
      toast(`Run #${data.run_id} ${data.status}`, `${data.stats.qualified || 0} qualified, ${data.stats.packaged || 0} packaged`);
      refreshSoon();
      break;
    case "profile":  // the profile changed. Tabs with answers being typed or unsaved edits are left alone.
      S.profileCache = null;
      if (S.route[0] === "profile" && !S.dirty && !["answers", "questions"].includes(S.profileTab)) renderProfile();
      break;
    case "profile_status":  // setup progress, a profile build starting or ending, answers waiting to be added
      onProfileStatus(data);
      break;
    case "questions":  // the questions JobPortal asks changed
      S.questions = data;
      renderNav();
      if (S.route[0] === "profile" && S.profileTab === "questions" && !questionDraft()) renderProfile("questions");
      break;
    case "analysis":  // an analysis started, finished or failed
      if (S.route[0] === "analysis") renderAnalysis();
      break;
  }
}
