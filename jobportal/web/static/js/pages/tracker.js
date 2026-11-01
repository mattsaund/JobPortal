/* tracker.js: the Tracker (#/tracker): your applications on a board with five columns, from Ready to apply to Rejected.
   Drag a card to another column (or pick one from its menu) to change its status, click it to see the lead's full
   details in a large dialog (lead.js), add a job straight onto a column, and delete one (with Undo). Above the board:
   the numbers and the follow-ups that are due. The Contacts view (#/tracker/contacts) lists every person JobPortal found
   across your leads.
   Live updates (refreshTracker, from live.js and the lead dialog) redraw the board only when something on it changed,
   wait while you drag a card, and never wipe what you typed in the Contacts view.
   APIs: GET /api/tracker, PATCH /api/leads/{id}, POST /api/leads/manual, GET /api/contacts and
   POST /api/leads/{id}/contacts/{i}. */
"use strict";

// Draws the page frame once, then the board or the contacts.
async function renderTracker(view) {
  const contacts = view === "contacts";
  if (main.dataset.page !== "tracker") {
    main.dataset.page = "tracker";
    main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">YOUR APPLICATIONS</p><h1>Tracker</h1>
        <p>Where each application stands. Drag a card when it moves along.</p></div>
        <div class="heading-actions"><button class="button primary" type="button" data-act="track-add">${icon("plus")} Add a job</button></div></div>
      <div class="filters" role="group" aria-label="View">
        <a class="chip" href="#/tracker" data-view="board">${icon("columns")}Board</a>
        <a class="chip" href="#/tracker/contacts" data-view="contacts">${icon("people")}Contacts</a></div>
      <div id="tracker-body"></div>`;
  }
  $$("[data-view]").forEach((chip) => {
    const on = chip.dataset.view === (contacts ? "contacts" : "board");
    chip.classList.toggle("active", on);
    if (on) chip.setAttribute("aria-current", "page");
    else chip.removeAttribute("aria-current");
  });
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

// The columns a card can be in: every status but "new" (not tracked yet) and "trashed", as [status, label].
const trackerColumns = () => S.meta.statuses.filter((s) => !["new", "trashed"].includes(s)).map((s) => [s, statusLabel(s)]);

// What the body shows when its first load failed (the error, with Try again). The board draws with setHtml, which only
// compares with the last board it drew, so anything else written into the body clears that memory.
function showInTrackerBody(box, html) {
  box.shownHtml = undefined;
  box.innerHTML = html;
}

// ---------------------------------------------------------------- the board
// The numbers, the follow-ups due, then the five columns (the server sends them in order).
// - It's redrawn only when its HTML changed (setHtml), so a refresh after an unrelated live event (a new lead that isn't
//   tracked yet) leaves the board as it is: an open menu stays open and the focus stays put.
// - While you drag a card, a redraw would pull the card out from under the pointer and the drop would do nothing, so it
//   waits for the drag to end (boardStale, see the drag listeners below).
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
  if ($(".track-card.dragging")) {
    boardStale = true;
    return;
  }
  const s = d.stats;
  const busiest = Math.max(1, ...d.weekly.map((w) => w.n));
  const weekly = d.weekly.slice().reverse().map((w) => `<i style="height:${Math.max(8, (w.n / busiest) * 100)}%" title="Week ${esc(w.wk)}: ${w.n}"></i>`).join("");
  const stat = (value, label, note, name, tint, extra = "") => `<div class="stat"><span class="stat-icon ${tint}">${icon(name)}</span>`
    + `<span><strong>${value}</strong><b>${label}</b><small>${note}</small></span>${extra}</div>`;
  const due = d.due.length ? `<section class="panel due-panel"><div class="panel-heading"><h2>${icon("bell")}Follow-ups due</h2><span class="small-tag">${d.due.length}</span></div>
      <ul class="due-list">${d.due.map((l) => `<li><span class="tag warn">${esc(fmtDate(l.follow_up_at))}</span><span class="due-name"><b>${esc(l.company)}</b> ${esc(l.title)}</span>
        <button class="button light small" type="button" data-act="track-open" data-id="${l.id}" data-tab="emails">Send a follow-up</button></li>`).join("")}</ul></section>` : "";
  const columns = trackerColumns();
  setHtml(box, `<div class="stats four">
      ${stat(s.applied, "Applications sent", weekly ? "Per week, newest last" : "None yet", "file", "blue", weekly ? `<span class="weekly" aria-hidden="true">${weekly}</span>` : "")}
      ${stat(`${Math.round(s.response_rate * 100)}%`, "Response rate", `${s.responded} heard back`, "mail", "")}
      ${stat(s.interviewing, "Interviews", "In interview now", "people", "purple")}
      ${stat(s.accepted, "Accepted", "Offers you took", "check", "")}</div>
    ${due}
    <div class="board" id="board">${Object.entries(d.columns).map(([status, leads]) => boardColumn(status, leads, columns)).join("")}</div>`);
}

// One column: its name, count and Add button, then its cards.
function boardColumn(status, leads, columns) {
  const name = esc(statusLabel(status));
  return `<section class="column" data-status="${esc(status)}" aria-label="${name}">
    <header class="column-head"><h2>${name}</h2><span class="count">${leads.length}</span>
      <button class="icon-button" type="button" data-act="track-add" data-status="${esc(status)}" aria-label="Add a job to ${name}">${icon("plus")}</button></header>
    <div class="column-cards">${leads.map((l) => trackCard(l, status, columns)).join("") || `<p class="column-empty">Drop a card here</p>`}</div></section>`;
}

// One card: the title, the company, the follow-up date while you wait on them (highlighted once it's due), a menu to
// move it (the way to move it without dragging), and Delete.
function trackCard(l, status, columns) {
  const days = daysUntil(l.follow_up_at);
  const followUp = l.follow_up_at && ["applied", "interviewing"].includes(status)
    ? `<span class="tag${days <= 0 ? " warn" : ""}">${icon("calendar")}Follow up ${days === 0 ? "today" : esc(fmtDate(l.follow_up_at))}</span>` : "";
  return `<article class="track-card" draggable="true" data-id="${l.id}" data-status="${esc(status)}">
    <button class="track-open" type="button" data-act="track-open" data-id="${l.id}"><strong>${esc(l.title)}</strong><span>${esc(l.company || "Company not given")}</span></button>
    ${followUp ? `<div class="track-meta">${followUp}</div>` : ""}
    <div class="track-foot"><select class="move" data-move="${l.id}" aria-label="Move ${esc(l.title)} to">${selectOptions(columns, status)}</select>
      <button class="icon-button" type="button" data-act="track-delete" data-id="${l.id}" data-title="${esc(l.title)}" aria-label="Delete ${esc(l.title)}">${icon("trash")}</button></div></article>`;
}

// Moves a lead to another column (PATCH) and redraws the board, with Undo to put it back. When the save fails, the
// card's menu goes back to the column the card is still in. Moved with its menu, the card keeps the focus on its menu in
// its new column (setHtml finds it again by data-move).
async function moveCard(id, status) {
  const card = $(`.track-card[data-id="${id}"]`);
  const before = card?.dataset.status;
  if (!before || before === status) return;
  try {
    await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } });
  } catch (err) {
    const menu = $("[data-move]", card);
    if (menu) menu.value = before;
    throw err;
  }
  refreshStats();
  await drawBoard();
  toast(`Moved to ${statusLabel(status)}`, "", "", null, { label: "Undo", run: () => moveCardBack(id, before) });
}
async function moveCardBack(id, status) {
  await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } });
  refreshStats();
  refreshTracker();
}

// Opens a lead's full details in a large dialog, on the given tab.
function openLeadDialog(id, tab) {
  const dialog = openDialog(`<div class="lead-dialog"></div>`, { eyebrow: "LEAD DETAILS", wide: true, guard: true, onClose: () => {
    if (S.leadView?.box === box) closeLeadDetails();  // unless another page has opened a lead meanwhile
    refreshTracker();
  } });
  const box = $(".lead-dialog", dialog);
  showLeadDetails(box, id, { tab, header: true });
}

// The "Add a job" dialog: a title and company are enough; a link or the posting lets JobPortal tailor it.
function trackAddDialog(status) {
  openDialog(`<h2>Add a job</h2><p>Add one you found yourself. A title and company are enough. Paste the link or the posting too, and
      JobPortal tailors a resume and cover letter for it.</p>
    <div class="form-grid">
      <label class="field"><span class="field-label">Job title</span><input type="text" id="ta-title"></label>
      <label class="field"><span class="field-label">Company</span><input type="text" id="ta-company"></label>
      <label class="field"><span class="field-label">Location (optional)</span><input type="text" id="ta-location"></label>
      <label class="field"><span class="field-label">Column</span><select id="ta-status">${selectOptions(trackerColumns(), status || "ready")}</select></label>
      <label class="field wide"><span class="field-label">Link (optional)</span><input type="url" id="ta-url" placeholder="https://"></label>
      <label class="field wide"><span class="field-label">Or paste the posting (optional)</span><textarea id="ta-text" rows="5"></textarea></label></div>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="track-add-go">Add it ${icon("arrow")}</button></div>`, { eyebrow: "ADD TO YOUR TRACKER" });
}

// Dragging a card onto a column moves it there. Files dragged in from the computer are file-drops.js's business: these
// only act while a card of the board is being dragged (it has the class "dragging").
document.addEventListener("dragstart", (e) => {
  const card = e.target.closest?.(".track-card");
  if (!card) return;
  e.dataTransfer.setData("text/plain", card.dataset.id);
  e.dataTransfer.effectAllowed = "move";
  card.classList.add("dragging");
});
document.addEventListener("dragend", (e) => {
  e.target.closest?.(".track-card")?.classList.remove("dragging");
  $$(".column.over").forEach((column) => column.classList.remove("over"));  // dropped outside, or Esc
  if (boardStale) {  // a live update came in during the drag
    boardStale = false;
    refreshTracker();
  }
});
document.addEventListener("dragover", (e) => {
  const column = e.target.closest?.(".column");
  if (!column || !$(".track-card.dragging")) return;
  e.preventDefault();  // allows the drop
  $$(".column.over").forEach((c) => c !== column && c.classList.remove("over"));
  column.classList.add("over");
});
document.addEventListener("dragleave", (e) => {
  const column = e.target.closest?.(".column");
  if (column && !column.contains(e.relatedTarget)) column.classList.remove("over");
});
document.addEventListener("drop", (e) => {
  const column = e.target.closest?.(".column");
  if (!column || !$(".track-card.dragging")) return;
  e.preventDefault();
  column.classList.remove("over");
  moveCard(e.dataTransfer.getData("text/plain"), column.dataset.status).catch((err) => toast("Couldn't move it", err.message, "error"));
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

// Every contact from GET /api/contacts, filtered as you type in Find or pick a status. The panel (with Find and the
// Status menu) is drawn once; a live refresh only redraws the rows with the new list, so what you typed in Find stays,
// and it leaves the rows alone while you're typing notes for someone (they save when you leave the box).
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
    showInTrackerBody(box, `<section class="panel">
      <div class="panel-heading"><div><h2>Contacts</h2><p class="panel-note" id="contact-count"></p></div>
        <div class="list-controls"><label class="control"><span>Find</span><input type="search" id="contact-q" placeholder="Name, company, anything"></label>
          <label class="control"><span>Status</span><select id="contact-status">${selectOptions(contactStatusChoices("Any status"))}</select></label></div></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Person</th><th>For</th><th>Email</th><th>Links</th><th>Status</th><th>Notes</th></tr></thead>
        <tbody id="contact-rows"></tbody></table></div></section>`);
    $("#contact-q").addEventListener("input", drawContactRows);
    $("#contact-status").addEventListener("change", drawContactRows);
  }
  trackerContacts = contacts;
  $("#contact-count").textContent = `${contacts.length === 1 ? "1 person" : `${contacts.length} people`} across your leads: recruiters, hiring managers, people on the team.`;
  if (!typingIn($("#contact-rows"))) drawContactRows();
}

// The contact in the Contacts view's list that a status menu or notes box (data-lead and data-i) belongs to.
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
      ? `<span class="nowrap">${esc(c.email)}</span><div class="cell-row"><span class="tag ${c.email_confidence === "found" ? "green" : "warn"}">${esc(humanize(c.email_confidence || "unknown"))}</span>`
        + `<button class="text-button" type="button" data-act="copytext" data-text="${esc(c.email)}">${icon("copy")}Copy</button></div>`
      : `<span class="muted-note">None</span>`;
    return `<tr><td><b>${esc(c.name)}</b><small class="cell-note">${esc(c.title)}${c.org ? `, ${esc(c.org)}` : ""}</small></td>
      <td><button class="text-button" type="button" data-act="track-open" data-id="${c.lead_id}" data-tab="contacts">${esc(c.lead_company)}</button>
        <small class="cell-note">${esc(c.lead_title)}</small></td>
      <td>${email}</td><td><div class="cell-row">${link(c.linkedin, "LinkedIn")}${link(c.source_url, "Source")}</div></td>
      <td>${contactStatusSelect(c.lead_id, c.idx, c.status, c.name)}</td>
      <td><input type="text" data-contact-notes data-lead="${c.lead_id}" data-i="${c.idx}" value="${esc(c.notes || "")}" placeholder="Notes" aria-label="Notes about ${esc(c.name)}"></td></tr>`;
  };
  const focus = focusKey(rows);
  rows.innerHTML = shown.map(row).join("")
    || `<tr><td colspan="6" class="muted-note">No contacts yet. JobPortal finds them while it tailors your applications.</td></tr>`;
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
    toast("Add a title and company", "Or paste the link or the posting.", "error");
    return;
  }
  el.disabled = true;
  try {
    const lead = await api("/api/leads/manual", { method: "POST", body });
    closeDialog(dialog);
    toast(lead.existing ? "Already in your leads" : "Added", lead.existing ? "That job is saved already." : `${body.title || "The job"} is on your tracker.`);
    refreshStats();
    refreshTracker();
  } finally {
    el.disabled = false;
  }
});
onAction("track-delete", async (el) => {
  const id = el.dataset.id, before = el.closest(".track-card").dataset.status;
  await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: "trashed" } });
  refreshStats();
  await drawBoard();
  // The card is gone, and its Delete button with it: a keyboard user goes on from its column's Add button.
  if (document.activeElement === document.body) $(`.column[data-status="${before}"] [data-act="track-add"]`)?.focus();
  toast("Deleted", el.dataset.title, "", null, { label: "Undo", run: () => moveCardBack(id, before) });
});
onChange(async (el) => {
  if (el.matches("[data-move]")) {  // a card's menu
    await moveCard(el.dataset.move, el.value);
  } else if (el.matches("[data-contact-status]")) {  // a contact's status, here or on a lead's Contacts tab
    await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } }).catch((err) => {
      el.value = savedChoice(el);
      throw err;
    });
    markSaved(el);
    // The list behind the Contacts view and the lead on screen (a lead's Contacts tab) get it too, so the rows and the
    // tab show it when they're drawn again (a new search in Find, another tab and back).
    const row = listedContact(el), contact = S.lead?.id === +el.dataset.lead && S.lead.package?.contacts?.[+el.dataset.i];
    if (row) row.status = el.value;
    if (contact) contact.status = el.value;
    toast("Saved", "Contact status changed.");
  } else if (el.matches("[data-contact-notes]")) {
    await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { notes: el.value } });
    const row = listedContact(el);
    if (row) row.notes = el.value;
    toast("Saved", "Notes saved.");
  } else {
    return false;
  }
  return true;
});
