/* live.js: the live connection to the server. The server pushes events over Server-Sent Events (GET /api/events, fed by
   core/bus.py): run progress, live feed lines, new and changed leads, profile changes, documents, the ChatGPT sign-in and
   toasts. onEvent() stores what changed in S and redraws the parts of the frame and of the open page that show it.
   Every redraw it starts leaves your unsaved edits alone, and a text box you're typing in (see typingIn in core.js).
   APIs: GET /api/events, plus what the redraws load (GET /api/stats, the open page's list, GET /api/onboarding). */
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

// A run sends many events close together. This refreshes the counts and the open page's lists once, after 2.5 quiet
// seconds.
const refreshSoon = debounce(() => {
  refreshStats();
  if (S.route[0] === "leads") loadLeads(true);
  if (S.route[0] === "home") loadTopLeads();
  if (S.route[0] === "tracker") refreshTracker();
}, 2500);

// Handles one event. kind says what happened and data carries the details.
function onEvent({ kind, data }) {
  switch (kind) {
    case "state": {  // the run state changed: a run started, moved to a new phase, counted more, or finished
      const wasRunning = S.state.running;
      S.state = data;
      renderFrame();
      if (S.route[0] === "leads") renderFeedHead();
      if (S.route[0] === "home") homeRunChanged();
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
      if (data && S.lead && S.lead.id === data.id) refreshLeadDetails(data);
      refreshSoon();
      break;
    case "toast":
      toast(data.title, data.body, data.level || "", data.lead_id);
      break;
    case "ai":  // the ChatGPT sign-in
      onAIStatus(data);
      break;
    case "tokens":  // the AI tokens used since JobPortal started
      S.state.tokens = data;
      renderSidebarFoot();
      if (S.route[0] === "leads") renderFeedHead();
      break;
    case "agents":  // the AI agents working right now
      S.state.active_agents = data;
      renderNextStep();
      break;
    case "run_done":
      toast(`Search #${data.run_id} ${data.status}`, `${data.stats.qualified || 0} good fits, ${data.stats.packaged || 0} ready to apply`);
      refreshSoon();
      break;
    case "profile":  // the profile or your answers changed. Forms with unsaved edits are left alone.
      S.profileCache = null;
      reloadOnboarding();
      if (S.route[0] === "settings" && S.route[1] === "profile" && !S.dirty) renderSettings("profile", S.route[2]);
      break;
    case "profile_status":  // a profile build starting, moving on, failing or finishing
      onProfileStatus(data);
      break;
    case "questions":  // the questions JobPortal asks changed
      S.questions = data;
      renderNextStep();
      if (S.route[0] === "home") renderFeed();
      break;
    case "documents":  // your extra documents changed: the new list
      S.documents = data;
      renderNextStep();
      if (S.route[0] === "home") homeDocumentsChanged();
      break;
    case "analysis":  // an analysis started, finished or failed
      if (S.route[0] === "analysis") renderAnalysis();
      break;
  }
}
