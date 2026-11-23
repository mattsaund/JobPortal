/* tracker.js: the Tracker page (#/tracker). The Board tab shows your applications in five lanes, from Ready to apply to
   Rejected, with the numbers and the follow-ups due above them. Each application is a plain row in its lane: drag it to
   another lane (or use its Move menu) to change its status, click it for the lead's full details in a large dialog
   (lead.js), and delete it with Undo. A lane's + button adds a job straight into it. The Contacts tab (#/tracker/contacts)
   lists every person JobPortal found across your leads.
   Live updates (refreshTracker, from live.js and the lead dialog) redraw the board only when something on it changed,
   wait while you drag a row, and never wipe what you typed in the Contacts tab.
   APIs: GET /api/tracker, PATCH /api/leads/{id}, POST /api/leads/manual, GET /api/contacts and
   POST /api/leads/{id}/contacts/{i}. */
"use strict";

// Puts the tabs in the top bar, draws the page's frame once, then the board or the contacts.
async function renderTracker(view) {
  const contacts = view === "contacts";
  pageHead("Tracker", pageTab('href="#/tracker"', "Board", !contacts) + pageTab('href="#/tracker/contacts"', "Contacts", contacts));
  if (main.dataset.page !== "tracker") {
    main.dataset.page = "tracker";
    main.innerHTML = `<div id="tracker-body"></div>`;
  }
  if (contacts) await drawContacts();
  else await drawBoard();
}

// Redraws whatever the Tracker shows, after a change elsewhere (a live update, the lead dialog). A failed refresh keeps
// what's on screen.
function refreshTracker() {
  if (S.route[0] !== "tracker") return;
  if (S.route[1] === "contacts") drawContacts(true);
  else drawBoard(true);
}

// The lanes a job can be in: every status but "new" (not tracked yet) and "trashed", as [status, label].
const trackerColumns = () => S.meta.statuses.filter((s) => !["new", "trashed"].includes(s)).map((s) => [s, statusLabel(s)]);

// What the body shows when its first load failed (the error, with Try again). The board draws with setHtml, which only
// compares with the last board it drew, so anything else written into the body clears that memory.
function showInTrackerBody(box, html) {
  box.shownHtml = undefined;
  box.innerHTML = html;
}

// The Add job button, at the end of the numbers and of the Contacts toolbar.
const addJobButton = () => `<button class="button primary" type="button" data-act="track-add">${icon("plus")}Add job</button>`;

// ---------------------------------------------------------------- the board
// The numbers, the follow-ups due, then the five lanes (the server sends them in order).
// - It's redrawn only when its HTML changed (setHtml), so a refresh after an unrelated live event (a new lead that isn't
//   tracked yet) leaves the board as it is: the focus stays put. A redraw puts each lane back where it was scrolled.
// - While you drag a row, a redraw would pull it out from under the pointer and the drop would do nothing, so it waits
//   for the drag to end (boardStale, see the drag listeners below).
// - Only the newest load draws: a live refresh and a move can overlap, and the older answer must not win.
let boardLoad = 0, boardStale = false;
async function drawBoard(live = false) {
  const ticket = ++boardLoad;
  let d;
  try {
    d = await api("/api/tracker");
  } catch (err) {
    const box = $("#tracker-body");
    if (box && !live && ticket === boardLoad && S.route[1] !== "contacts") showInTrackerBody(box, loadError(err));
    return;
  }
  const box = $("#tracker-body");
  if (!box || S.route[1] === "contacts" || ticket !== boardLoad) return;
  if ($(".lane-row.dragging")) {
    boardStale = true;
    return;
  }
  const columns = trackerColumns();
  const scrolled = new Map($$("[data-scroll]", box).map((el) => [el.dataset.scroll, el.scrollTop]));
  setHtml(box, `<div class="board-view">
    <div class="tracker-top">${trackerStats(d)}<div class="tracker-add">${addJobButton()}</div></div>
    ${trackerDue(d.due)}
    <div class="lanes">${Object.entries(d.columns).map(([status, leads]) => boardLane(status, leads, columns)).join("")}</div></div>`);
  $$("[data-scroll]", box).forEach((el) => (el.scrollTop = scrolled.get(el.dataset.scroll) || 0));
}

// The numbers across the top. Applied has a small bar per week, newest last.
function trackerStats({ stats: s, weekly }) {
  const busiest = Math.max(1, ...weekly.map((w) => w.n));
  const weeks = weekly.slice().reverse().map((w) => `<i style="height:${Math.max(12, (w.n / busiest) * 100)}%" title="Week ${esc(w.wk)}: ${w.n}"></i>`).join("");
  const stat = (value, label, extra = "") => `<div><strong>${value}</strong><span>${label}</span>${extra}</div>`;
  return `<div class="stat-strip">
    ${stat(s.applied, "Applied", weeks ? `<span class="weekly" aria-hidden="true">${weeks}</span>` : "")}
    ${stat(`${Math.round(s.response_rate * 100)}%${s.applied ? `<small>${s.responded} of ${s.applied}</small>` : ""}`, "Response rate")}
    ${stat(s.interviewing, "Interviews")}
    ${stat(s.accepted, "Accepted")}</div>`;
}

// The follow-ups due, soonest first, each with a button to its emails. Nothing when none are due.
function trackerDue(due) {
  if (!due.length) return "";
  const row = (l) => `<li><span class="due-date${daysUntil(l.follow_up_at) <= 0 ? " late" : ""}">${esc(fmtDate(l.follow_up_at))}</span>
    <span class="due-name"><b>${esc(l.company)}</b> <span>${esc(l.title)}</span></span>
    <button class="button outline small" type="button" data-act="track-open" data-id="${l.id}" data-tab="emails">Follow up</button></li>`;
  return `<section class="tracker-due" aria-label="Follow-ups due"><h2>${icon("bell")}Follow-ups due <span>${due.length}</span></h2>
    <ul class="due-rows" data-scroll="due">${due.map(row).join("")}</ul></section>`;
}

// One lane: its name, count and Add button, then its rows, which scroll on their own.
function boardLane(status, leads, columns) {
  const name = esc(statusLabel(status));
  return `<section class="lane" data-status="${esc(status)}" aria-label="${name}">
    <header class="lane-head"><h2>${name}</h2><span class="lane-count">${leads.length}</span>
      <button class="icon-button" type="button" data-act="track-add" data-status="${esc(status)}" aria-label="Add job to ${name}" title="Add job">${icon("plus")}</button></header>
    <div class="lane-rows" data-scroll="lane:${esc(status)}">${leads.map((l) => laneRow(l, status, columns)).join("") || `<p class="lane-empty">No jobs</p>`}</div></section>`;
}

// One application: the title, the company, the follow-up date while you wait on them (highlighted once it's due), a Move
// menu (the way to move it without dragging) and Delete. The main part is a div with the role of a button, because some
// browsers won't start a drag on a real button.
function laneRow(l, status, columns) {
  const days = daysUntil(l.follow_up_at);
  const followUp = l.follow_up_at && ["applied", "interviewing"].includes(status)
    ? `<small class="lane-follow${days <= 0 ? " late" : ""}">${icon("calendar")}Follow up ${days === 0 ? "today" : esc(fmtDate(l.follow_up_at))}</small>` : "";
  return `<article class="lane-row" draggable="true" data-id="${l.id}" data-status="${esc(status)}">
    <div class="lane-open" role="button" tabindex="0" data-act="track-open" data-id="${l.id}"><strong>${esc(l.title)}</strong>
      <span>${esc(l.company || "No company")}</span>${followUp}</div>
    <div class="lane-tools"><label class="lane-move">Move${icon("chevron")}<select data-move="${l.id}" aria-label="Move ${esc(l.title)} to">${selectOptions(columns, status)}</select></label>
      <button class="icon-button" type="button" data-act="track-delete" data-id="${l.id}" data-title="${esc(l.title)}" aria-label="Delete ${esc(l.title)}" title="Delete">${icon("trash")}</button></div></article>`;
}

// Moves a lead to another lane (PATCH) and redraws the board, with Undo to put it back. When the save fails, the row's
// menu goes back to the lane the row is still in. Moved with its menu, the row keeps the focus on its menu in its new
// lane (setHtml finds it again by data-move).
async function moveLaneRow(id, status) {
  const row = $(`.lane-row[data-id="${id}"]`);
  const before = row?.dataset.status;
  if (!before || before === status) return;
  try {
    await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } });
  } catch (err) {
    const menu = $("[data-move]", row);
    if (menu) menu.value = before;
    throw err;
  }
  refreshStats();
  await drawBoard();
  toast(`Moved to ${statusLabel(status)}`, "", "", null, { label: "Undo", run: () => moveLaneRowBack(id, before) });
}
async function moveLaneRowBack(id, status) {
  await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } });
  refreshStats();
  refreshTracker();
}

// Opens a lead's full details in a large dialog, on the given tab.
function openLeadDialog(id, tab) {
  const dialog = openDialog(`<div class="lead-dialog"></div>`, { title: "Lead", wide: true, guard: true, onClose: () => {
    if (S.leadView?.box === box) closeLeadDetails();  // unless another page has opened a lead meanwhile
    refreshTracker();
  } });
  const box = $(".lead-dialog", dialog);
  showLeadDetails(box, id, { tab, header: true });
}

// The Add job dialog: a title and company are enough, or a link or the posting, which lets JobPortal tailor it.
function trackAddDialog(status) {
  openDialog(`<h2>Add job</h2>
    <div class="form-grid">
      <label class="field"><span class="field-label">Job title</span><input type="text" id="ta-title"></label>
      <label class="field"><span class="field-label">Company</span><input type="text" id="ta-company"></label>
      <label class="field"><span class="field-label">Location (optional)</span><input type="text" id="ta-location"></label>
      <label class="field"><span class="field-label">Status</span><select id="ta-status">${selectOptions(trackerColumns(), status || "ready")}</select></label>
      <label class="field wide"><span class="field-label">Link (optional)</span><input type="url" id="ta-url" placeholder="https://"></label>
      <label class="field wide"><span class="field-label">Posting text (optional)</span><textarea id="ta-text" rows="5"></textarea></label></div>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="track-add-go">Add job</button></div>`);
}

// Dragging a row onto a lane moves it there. Files dragged in from the computer are file-drops.js's business: these only
// act while a row of the board is being dragged (it has the class "dragging").
document.addEventListener("dragstart", (e) => {
  const row = e.target.closest?.(".lane-row");
  if (!row) return;
  e.dataTransfer.setData("text/plain", row.dataset.id);
  e.dataTransfer.effectAllowed = "move";
  row.classList.add("dragging");
});
document.addEventListener("dragend", (e) => {
  e.target.closest?.(".lane-row")?.classList.remove("dragging");
  $$(".lane.over").forEach((lane) => lane.classList.remove("over"));  // dropped outside, or Esc
  if (boardStale) {  // a live update came in during the drag
    boardStale = false;
    refreshTracker();
  }
});
document.addEventListener("dragover", (e) => {
  const lane = e.target.closest?.(".lane");
  if (!lane || !$(".lane-row.dragging")) return;
  e.preventDefault();  // allows the drop
  $$(".lane.over").forEach((other) => other !== lane && other.classList.remove("over"));
  lane.classList.add("over");
});
document.addEventListener("dragleave", (e) => {
  const lane = e.target.closest?.(".lane");
  if (lane && !lane.contains(e.relatedTarget)) lane.classList.remove("over");
});
document.addEventListener("drop", (e) => {
  const lane = e.target.closest?.(".lane");
  if (!lane || !$(".lane-row.dragging")) return;
  e.preventDefault();
  lane.classList.remove("over");
  moveLaneRow(e.dataTransfer.getData("text/plain"), lane.dataset.status).catch((err) => toast("Couldn't move it", err.message, "error"));
});
// Enter or Space on a row's main part opens it, as on a real button.
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches?.(".lane-open")) {
    e.preventDefault();
    e.target.click();
  }
});

// ---------------------------------------------------------------- contacts
// Where you stand with a contact. "" means not set.
const CONTACT_STATUSES = ["to contact", "contacted", "replied", "no response", "referred me"];
const contactStatusChoices = (emptyLabel) => [["", emptyLabel], ...CONTACT_STATUSES.map((s) => [s, humanize(s)])];

// The status menu for one contact (lead id, its place in the lead's list, and the person's name for screen readers). A
// change saves at once (see onChange below). Used here and on a lead's Contacts tab.
const contactStatusSelect = (leadId, i, status, name) => `<select data-contact-status data-lead="${leadId}" data-i="${i}" aria-label="Status for ${esc(name || "this contact")}">`
  + `${selectOptions(contactStatusChoices("Not set"), status)}</select>`;

// A menu that saves on change goes back to its last saved choice when the save fails. Its options' "selected" attributes
// (defaultSelected) remember that choice: drawn with the menu, and moved along after each save.
const savedChoice = (select) => [...select.options].find((option) => option.defaultSelected)?.value ?? "";
const markSaved = (select) => [...select.options].forEach((option) => (option.defaultSelected = option.selected));

// Every contact from GET /api/contacts, filtered as you type in Find or pick a status. The toolbar and table are drawn
// once; a live refresh only redraws the rows with the new list, so what you typed in Find stays, and it leaves the rows
// alone while you're typing notes for someone (they save when you leave the box).
let trackerContacts = [], contactsLoad = 0;
async function drawContacts(live = false) {
  const ticket = ++contactsLoad;
  let contacts;
  try {
    contacts = await api("/api/contacts");
  } catch (err) {
    const box = $("#tracker-body");
    if (box && !live && ticket === contactsLoad && S.route[1] === "contacts") showInTrackerBody(box, loadError(err));
    return;
  }
  const box = $("#tracker-body");
  if (!box || S.route[1] !== "contacts" || ticket !== contactsLoad) return;
  if (!$("#contact-rows", box)) {
    showInTrackerBody(box, `<div class="contacts-view">
      <div class="toolbar"><input type="search" id="contact-q" placeholder="Find" aria-label="Find contacts">
        <select id="contact-status" aria-label="Status">${selectOptions(contactStatusChoices("Any status"))}</select>
        <span class="muted" id="contact-count"></span><span class="spacer"></span>${addJobButton()}</div>
      <div class="table-wrap contacts-scroll"><table class="table contacts-table"><thead><tr><th>Person</th><th>For</th><th>Email</th><th>Links</th><th>Status</th><th>Notes</th></tr></thead>
        <tbody id="contact-rows"></tbody></table></div></div>`);
    $("#contact-q").addEventListener("input", drawContactRows);
    $("#contact-status").addEventListener("change", drawContactRows);
  }
  trackerContacts = contacts;
  $("#contact-count").textContent = contacts.length === 1 ? "1 person" : `${contacts.length} people`;
  if (!typingIn($("#contact-rows"))) drawContactRows();
}

// The contact in the Contacts tab's list that a status menu or notes box (data-lead and data-i) belongs to.
const listedContact = (el) => trackerContacts.find((c) => c.lead_id === +el.dataset.lead && c.idx === +el.dataset.i);

// The rows of the contacts that match Find and the Status menu.
function drawContactRows() {
  const rows = $("#contact-rows");
  if (!rows) return;
  const text = $("#contact-q").value.toLowerCase(), status = $("#contact-status").value;
  const shown = trackerContacts.filter((c) => (!text || JSON.stringify(c).toLowerCase().includes(text)) && (!status || c.status === status));
  const link = (url, label) => (safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${label}</a>` : "");
  const row = (c) => {
    const email = c.email
      ? `<span class="contact-email">${esc(c.email)}</span><div class="cell-row"><span class="tag ${c.email_confidence === "found" ? "green" : "warn"}">${esc(humanize(c.email_confidence || "unknown"))}</span>`
        + `<button class="text-button" type="button" data-act="copytext" data-text="${esc(c.email)}">${icon("copy")}Copy</button></div>`
      : `<span class="muted">None</span>`;
    return `<tr><td><b>${esc(c.name)}</b><small class="cell-note">${esc(c.title)}${c.org ? `, ${esc(c.org)}` : ""}</small></td>
      <td><button class="text-button" type="button" data-act="track-open" data-id="${c.lead_id}" data-tab="contacts">${esc(c.lead_company)}</button>
        <small class="cell-note">${esc(c.lead_title)}</small></td>
      <td>${email}</td><td><div class="cell-row">${link(c.linkedin, "LinkedIn")}${link(c.source_url, "Source")}</div></td>
      <td>${contactStatusSelect(c.lead_id, c.idx, c.status, c.name)}</td>
      <td><input type="text" data-contact-notes data-lead="${c.lead_id}" data-i="${c.idx}" value="${esc(c.notes || "")}" placeholder="Notes" aria-label="Notes about ${esc(c.name)}"></td></tr>`;
  };
  const focus = focusKey(rows);
  rows.innerHTML = shown.map(row).join("")
    || `<tr class="contacts-none"><td colspan="6"><div class="empty"><p>${trackerContacts.length ? "No matches" : "No contacts yet"}</p></div></td></tr>`;
  refocus(rows, focus);
}

// ---------------------------------------------------------------- actions
onAction("track-open", (el) => openLeadDialog(+el.dataset.id, el.dataset.tab));
onAction("track-add", (el) => trackAddDialog(el.dataset.status));
onAction("track-add-go", async (el) => {
  const dialog = el.closest("dialog");
  const value = (id) => $(id, dialog).value.trim();
  const body = { title: value("#ta-title"), company: value("#ta-company"), location: value("#ta-location"), app_status: value("#ta-status"),
    url: value("#ta-url"), text: value("#ta-text") };
  if (!(body.title && body.company) && !body.url && !body.text) {
    toast("Title and company needed", "Or a link or posting.", "error");
    return;
  }
  el.disabled = true;
  try {
    const lead = await api("/api/leads/manual", { method: "POST", body });
    closeDialog(dialog);
    toast(lead.existing ? "Already saved" : "Job added");
    refreshStats();
    refreshTracker();
  } finally {
    el.disabled = false;
  }
});
onAction("track-delete", async (el) => {
  const id = el.dataset.id, before = el.closest(".lane-row").dataset.status;
  await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: "trashed" } });
  refreshStats();
  await drawBoard();
  // The row is gone, and its Delete button with it: a keyboard user goes on from its lane's Add button.
  if (document.activeElement === document.body) $(`.lane[data-status="${before}"] [data-act="track-add"]`)?.focus();
  toast("Deleted", el.dataset.title, "", null, { label: "Undo", run: () => moveLaneRowBack(id, before) });
});
onChange(async (el) => {
  if (el.matches("[data-move]")) {  // a row's Move menu
    await moveLaneRow(el.dataset.move, el.value);
  } else if (el.matches("[data-contact-status]")) {  // a contact's status, here or on a lead's Contacts tab
    await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } }).catch((err) => {
      el.value = savedChoice(el);
      throw err;
    });
    markSaved(el);
    // The list behind the Contacts tab and the lead on screen (a lead's Contacts tab) get it too, so the rows and the tab
    // show it when they're drawn again (a new search in Find, another tab and back).
    const row = listedContact(el), contact = S.lead?.id === +el.dataset.lead && S.lead.package?.contacts?.[+el.dataset.i];
    if (row) row.status = el.value;
    if (contact) contact.status = el.value;
    toast("Saved");
  } else if (el.matches("[data-contact-notes]")) {
    await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { notes: el.value } });
    const row = listedContact(el);
    if (row) row.notes = el.value;
    toast("Saved");
  } else {
    return false;
  }
  return true;
});
