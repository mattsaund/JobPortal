/* tracker.js: the Tracker board and the Contacts page.
   Tracker: your applications as cards in columns from Saved to Withdrawn. Drag a card to change its status. Above the
   board: the headline numbers, applications per week and the follow-ups that are due. APIs: GET /api/tracker,
   PATCH /api/leads/{id}.
   Contacts: every person the AI found across your leads, with a filter and a status menu per person. APIs:
   GET /api/contacts, POST /api/leads/{id}/contacts/{i} (the status menu, here and on a lead's Contacts tab). */
"use strict";

// The board's columns, in order.
const TRACK = ["saved", "applied", "assessment", "interviewing", "offer", "rejected", "ghosted", "withdrawn"];

// Draws the board from GET /api/tracker and makes the cards draggable between columns.
async function renderTracker() {
  const d = await api("/api/tracker"), s = d.stats;
  const busiestWeek = Math.max(1, ...d.weekly.map((w) => w.n));
  const weekly = d.weekly.slice().reverse().map((w) => `<i style="height:${(w.n / busiestWeek) * 100}%" title="week ${esc(w.wk)}: ${w.n}"></i>`).join("")
    || `<span class="muted small">no applications yet</span>`;
  const due = d.due.length ? `<div class="card" style="margin-bottom:16px"><h3>Follow-ups due</h3>${d.due.map((l) => `<div class="row" style="padding:5px 0">`
    + `<span class="chip warn">${esc(l.follow_up_at)}</span><b>${esc(l.company)}</b><span class="muted">${esc(l.title)}</span><span class="spacer"></span>`
    + `<a class="btn sm" href="#/lead/${l.id}/emails">Send follow-up</a></div>`).join("")}</div>` : "";
  const card = (l, status) => {
    const applied = l.applied_at ? `<span class="chip">applied ${esc(l.applied_at)}</span>` : "";
    // While you wait on the company, the follow-up date shows (orange once it's due).
    const followUp = l.follow_up_at && ["applied", "assessment", "interviewing"].includes(status)
      ? `<span class="chip ${daysUntil(l.follow_up_at) <= 0 ? "warn" : ""}">f/u ${esc(l.follow_up_at)}</span>` : "";
    return `<div class="kcard" draggable="true" data-id="${l.id}"><div class="t">${esc(l.title)}</div><div class="c">${esc(l.company)}${l.location ? `, ${esc(l.location)}` : ""}</div>
        <div class="row" style="gap:5px;margin-top:6px">${applied}${followUp}</div></div>`;
  };
  const column = (status) => `<div class="kcol" data-st="${status}"><h4><span>${STATUS_LABEL[status]}</span><span>${d.columns[status].length}</span></h4>
      ${d.columns[status].map((l) => card(l, status)).join("")}</div>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Application tracker</h1><span class="sub">Drag cards between columns. Applying sets a 7-day follow-up automatically.</span></div>
    <div class="tiles"><div class="tile"><div class="n">${s.applied}</div><div class="l">Applied</div></div>
      <div class="tile"><div class="n">${Math.round(s.response_rate * 100)}%</div><div class="l">Response rate</div></div>
      <div class="tile"><div class="n">${s.interviewing}</div><div class="l">OA / interviewing</div></div>
      <div class="tile ${s.offers ? "hot" : ""}"><div class="n">${s.offers}</div><div class="l">Offers</div></div>
      <div class="tile"><div class="weekly" title="Applications per week">${weekly}</div><div class="l">Per week</div></div></div>
    ${due}
    <div class="kanban">${TRACK.map(column).join("")}</div>
    <p class="muted small">Leads you haven't acted on live in <a href="#/leads">Leads</a>. Set a lead to “Saved” there to put it on this board.</p></div>`;
  $$(".kcard").forEach((c) => {
    c.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", c.dataset.id);
      c.classList.add("dragging");
    });
    c.addEventListener("dragend", () => c.classList.remove("dragging"));
    c.addEventListener("click", () => (location.hash = `#/lead/${c.dataset.id}`));
  });
  $$(".kcol").forEach((col) => {
    col.addEventListener("dragover", (e) => {
      e.preventDefault();  // allows the drop
      col.classList.add("over");
    });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", async (e) => {  // dropping a card in a column sets that status
      e.preventDefault();
      col.classList.remove("over");
      const id = e.dataTransfer.getData("text/plain");
      await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: col.dataset.st } });
      refreshStats();
      renderTracker();
    });
  });
}

// ---------------------------------------------------------------- contacts
// Where you stand with a contact. "" means not set.
const CONTACT_STATUSES = ["to contact", "contacted", "replied", "no response", "referred me"];

// The status menu for one contact (lead id + index in its contact list). A change saves it at once (see onChange below).
const contactStatusSelect = (leadId, i, status) => `<select data-contact-status data-lead="${leadId}" data-i="${i}">`
  + `${selectOptions([["", "not set"], ...CONTACT_STATUSES], status)}</select>`;

// The Contacts page: every contact from GET /api/contacts, filtered as you type or pick a status.
async function renderContacts() {
  const contacts = await api("/api/contacts");
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Contacts</h1>
    <span class="sub">${contacts.length} people across your leads: recruiters, hiring managers, people on the team, alumni.</span><span class="spacer"></span>
    <input type="text" id="cq" placeholder="Filter" style="max-width:260px"><select id="cst" style="width:auto">${selectOptions([["", "Any status"], ...CONTACT_STATUSES])}</select></div>
    <div class="card"><table class="t"><thead><tr><th>Person</th><th>Lead</th><th>Email</th><th>Links</th><th>Status</th></tr></thead><tbody id="ctb"></tbody></table></div></div>`;
  const row = (c) => {
    const email = c.email
      ? `<span class="mono small">${esc(c.email)}</span> <span class="chip ${c.email_confidence === "found" ? "good" : "warn"}">${esc(c.email_confidence)}</span>`
      : `<span class="muted">none</span>`;
    const links = (safeUrl(c.linkedin) ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">LinkedIn</a> ` : "")
      + (safeUrl(c.source_url) ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">source</a>` : "");
    return `<tr>
      <td><b>${esc(c.name)}</b><div class="muted small">${esc(c.title)}${c.org ? `, ${esc(c.org)}` : ""}</div></td>
      <td><a href="#/lead/${c.lead_id}">${esc(c.lead_company)}</a><div class="muted small">${esc(c.lead_title)}</div></td>
      <td>${email}</td>
      <td class="small">${links}</td>
      <td>${contactStatusSelect(c.lead_id, c.idx, c.status)}</td></tr>`;
  };
  const draw = () => {
    const text = $("#cq").value.toLowerCase(), status = $("#cst").value;
    const shown = contacts.filter((c) => (!text || JSON.stringify(c).toLowerCase().includes(text)) && (!status || c.status === status));
    $("#ctb").innerHTML = shown.map(row).join("")
      || `<tr><td colspan="5" class="muted">No contacts yet. They're found while application packages are built.</td></tr>`;
  };
  $("#cq").oninput = draw;
  $("#cst").onchange = draw;
  draw();
}

// ---------------------------------------------------------------- actions
onChange(async (el) => {  // a contact's status menu, here or on a lead's Contacts tab
  if (!el.matches("[data-contact-status]")) return false;
  await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } });
  toast("Updated", "Contact status saved");
  return true;
});
