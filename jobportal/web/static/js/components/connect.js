/* connect.js: the Connect popup, the one place to connect an AI. It opens from the sidebar, Home and Settings, AI.
   A searchable dropdown lists every provider (GET /api/ai/providers). Choosing one does what that provider needs:
   - a sign-in opens the provider's page in the browser and waits for it to finish (POST /api/ai/signin);
   - a key shows a key field with a link to get one (PUT /api/ai/key);
   - an address (a local server, or a service with its own URL) shows its fields and tests them (PUT /api/ai/key).
   The server checks every connection against the provider's model list before keeping it. A provider with no list answers
   409, and the popup then asks for a model name. An "ai" event says when a sign-in is done (connectStatusChanged). */
"use strict";

let connectList = null;   // the providers, while the popup is open
let connectChosen = null; // the provider picked in the dropdown
let connectWaiting = "";  // the id of a provider whose sign-in is open in the browser
let connectNeedsModel = "";  // the id of a provider that has no model list, so the popup asks for a model name

const CONNECT_GROUPS = [["signin", "Sign in"], ["key", "API key"], ["local", "On this computer"], ["custom", "Other"]];

// Opens the popup, on the AI in use when there is one.
async function openConnect() {
  const r = await api("/api/ai/providers");
  connectList = r.providers;
  connectWaiting = "";
  connectChosen = connectList.find((p) => p.id === r.status.provider && r.status.ready) || null;
  openDialog(`<div class="connect" id="connect">
      <label class="field"><span class="field-label">Provider</span>
        <span class="combo" id="connect-combo"><input id="connect-search" type="text" role="combobox" aria-expanded="false" aria-controls="connect-options"
          aria-autocomplete="list" autocomplete="off" spellcheck="false" placeholder="Choose a provider">${icon("chevron")}
          <span class="combo-list" id="connect-options" role="listbox" aria-label="Providers" hidden></span></span></label>
      <div id="connect-body"></div></div>`, { title: "Connect AI", onClose: () => {
        connectList = connectChosen = null;
        connectWaiting = connectNeedsModel = "";
      } });
  $("#connect-search").value = connectChosen?.name || "";
  renderConnectBody();
  if (!connectChosen) {
    $("#connect-search").focus();
    showConnectOptions("");
  }
}

// ---------------------------------------------------------------- the dropdown
// Fills the list with the providers matching what's typed, grouped by how they connect.
function showConnectOptions(query) {
  const list = $("#connect-options");
  if (!list) return;
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const hits = connectList.filter((p) => words.every((w) => `${p.name} ${p.id} ${p.aliases || ""}`.toLowerCase().includes(w)));
  list.innerHTML = CONNECT_GROUPS.map(([group, label]) => {
    const inGroup = hits.filter((p) => p.group === group);
    if (!inGroup.length) return "";
    return `<span class="combo-group">${label}</span>${inGroup.map((p) => `<button type="button" role="option" class="combo-option" tabindex="-1" data-act="connect-pick" data-id="${esc(p.id)}"`
      + ` aria-selected="${p.id === connectChosen?.id}"><span>${esc(p.name)}</span>${p.free ? `<small>Free tier</small>` : ""}${S.state.ai?.keys?.[p.id] ? `<small>Saved</small>` : ""}</button>`).join("")}`;
  }).join("") || `<span class="combo-empty">No match</span>`;
  list.hidden = false;
  $("#connect-search").setAttribute("aria-expanded", "true");
  $("#connect-combo").classList.add("open");
}

function hideConnectOptions() {
  const list = $("#connect-options");
  if (!list) return;
  list.hidden = true;
  $("#connect-search").setAttribute("aria-expanded", "false");
  $("#connect-combo").classList.remove("open");
}

// Moves the highlight with the arrow keys.
function moveConnectOption(step) {
  const options = $$(".combo-option", $("#connect-options"));
  if (!options.length) return;
  const at = options.findIndex((el) => el.classList.contains("active"));
  options[at]?.classList.remove("active");
  const next = options[at < 0 && step < 0 ? options.length - 1 : (at + step + options.length) % options.length];
  next.classList.add("active");
  next.scrollIntoView({ block: "nearest" });
  $("#connect-search").setAttribute("aria-activedescendant", "");
}

// A provider was picked: show what it needs, and start right away when that's a sign-in.
function pickProvider(id) {
  connectChosen = connectList.find((p) => p.id === id);
  connectWaiting = connectNeedsModel = "";
  $("#connect-search").value = connectChosen.name;
  hideConnectOptions();
  renderConnectBody();
  if (connectChosen.connect === "signin" && !isConnected(connectChosen)) startProviderSignIn(connectChosen);
  else $("#connect-body input")?.focus();
}

// ---------------------------------------------------------------- each provider's connection
const isConnected = (p) => S.state.ai?.ready && S.state.ai.provider === p.id;

// What the chosen provider needs, under the dropdown.
function renderConnectBody() {
  const box = $("#connect-body");
  if (!box) return;
  const p = connectChosen;
  if (!p) {
    box.innerHTML = "";
    return;
  }
  const note = p.note ? `<p class="connect-note">${esc(p.note)}</p>` : "";
  if (isConnected(p)) {
    const who = S.state.ai.email || S.state.ai.keys?.[p.id] || "";
    box.innerHTML = `<div class="connect-done">${icon("check")}<span><b>Connected</b>${who ? `<small>${esc(who)}</small>` : ""}</span>
      <span class="spacer"></span><button class="button outline small" type="button" data-act="connect-remove">Disconnect</button></div>${note}`;
    return;
  }
  if (p.connect === "signin") {
    box.innerHTML = connectWaiting === p.id
      ? `<div class="connect-wait">${spinner()}<span>Waiting for ${esc(p.name)}</span><span class="spacer"></span>
          <button class="button outline small" type="button" data-act="connect-signin">Open again</button></div>${p.key_url ? keyFields(p, true) : ""}${note}`
      : `<button class="button primary full" type="button" data-act="connect-signin">Sign in with ${esc(p.name)}</button>${p.key_url ? keyFields(p, true) : ""}${note}`;
    return;
  }
  box.innerHTML = keyFields(p) + note;
}

// The fields a provider needs: its address parts, and its key unless it has none.
function keyFields(p, optional = false) {
  const saved = S.state.ai?.endpoints?.[p.id] || {};
  const fields = (p.fields || []).map((f) => `<label class="field"><span class="field-label">${esc(f.label)}</span>
      <input type="${f.id === "url" ? "url" : "text"}" data-endpoint="${esc(f.id)}" value="${esc(saved[f.id] ?? f.default ?? "")}" placeholder="${esc(f.placeholder || "")}" spellcheck="false" autocomplete="off"></label>`).join("");
  const held = S.state.ai?.keys?.[p.id];
  const key = p.needs_key === false ? `<label class="field"><span class="field-label">API key <small>(optional)</small></span>
      <input type="password" id="connect-key" autocomplete="off" spellcheck="false"></label>`
    : `<label class="field"><span class="field-label">${optional ? "Or paste a key" : "API key"}${p.key_url ? ` <a class="text-button" href="${esc(p.key_url)}" target="_blank" rel="noopener">Get key ${icon("external")}</a>` : ""}</span>
      <input type="password" id="connect-key" autocomplete="off" spellcheck="false" placeholder="${esc(held || (p.key_prefix ? `${p.key_prefix}...` : ""))}"></label>`;
  const model = connectNeedsModel === p.id ? `<label class="field"><span class="field-label">Model</span>
      <input type="text" id="connect-model" spellcheck="false" autocomplete="off"></label>` : "";
  return `<div class="connect-fields">${fields}${key}${model}<button class="button ${optional ? "outline" : "primary"} full" type="button" data-act="connect-key">Connect</button></div>`;
}

// Opens the provider's sign-in page in the browser. In a normal tab, the new tab opens during the click so popup blockers
// allow it, and gets its address once the server answers.
async function startProviderSignIn(p) {
  const tab = ownWindow() ? null : window.open("", "_blank");
  try {
    const r = await api("/api/ai/signin", { method: "POST", body: { provider: p.id } });
    if (ownWindow()) await openUrl(r.url);
    else if (tab) tab.location = r.url;
    else location.href = r.url;
    connectWaiting = p.id;
    renderConnectBody();
  } catch (e) {
    if (tab) tab.close();
    toast("Sign-in failed", e.message, "error");
  }
}

// An "ai" event: when the provider being connected is ready, say so and close the popup.
function connectStatusChanged(data) {
  if (!connectList) return;
  if (data.ready && connectChosen && data.provider === connectChosen.id && (connectWaiting === data.provider)) {
    connectWaiting = "";
    closeDialog($("#connect")?.closest("dialog"));
    return;
  }
  renderConnectBody();
}

// ---------------------------------------------------------------- actions
onAction("connect-pick", (el) => pickProvider(el.dataset.id));
onAction("connect-signin", () => startProviderSignIn(connectChosen));
onAction("connect-key", async (el) => {
  const p = connectChosen, key = $("#connect-key")?.value.trim() || "";
  const endpoint = Object.fromEntries($$("[data-endpoint]", $("#connect-body")).map((input) => [input.dataset.endpoint, input.value.trim()]));
  const needed = (p.fields || []).filter((f) => f.required !== false && !endpoint[f.id]).map((f) => f.label);
  if (needed.length) {
    toast("Required", needed.join(", "), "error");
    return;
  }
  if (!key && p.needs_key !== false && !S.state.ai?.keys?.[p.id]) {
    toast("Key required", "", "error");
    return;
  }
  const model = $("#connect-model")?.value.trim() || "";
  if (connectNeedsModel === p.id && !model) {
    toast("Model required", "", "error");
    return;
  }
  const label = el.innerHTML;
  el.disabled = true;
  el.innerHTML = `${spinner()}Checking`;
  try {
    const r = await api("/api/ai/key", { method: "PUT", body: { provider: p.id, key, endpoint, model } });
    S.state.ai = r;
    renderFrame();
    if (S.route[0] === "home") renderHome();
    if (S.route[0] === "settings" && S.route[1] === "ai" && !S.cfgDirty) renderSettings("ai");
    closeDialog(el.closest("dialog"));
    toast(`${p.name} connected`);
  } catch (e) {
    el.disabled = false;
    el.innerHTML = label;
    if (e.status === 409) {  // no model list here: keep what's typed and ask for the model name
      connectNeedsModel = p.id;
      el.insertAdjacentHTML("beforebegin", `<label class="field"><span class="field-label">Model</span>
        <input type="text" id="connect-model" spellcheck="false" autocomplete="off"></label>`);
      $("#connect-model").focus();
      return;
    }
    toast("Couldn't connect", e.message, "error");
  }
});
onAction("connect-remove", async () => {
  const p = connectChosen;
  const r = await api(`/api/ai/connection?provider=${encodeURIComponent(p.id)}`, { method: "DELETE" });
  S.state.ai = r;
  renderFrame();
  renderConnectBody();
  if (S.route[0] === "home") renderHome();
  if (S.route[0] === "settings" && S.route[1] === "ai" && !S.cfgDirty) renderSettings("ai");
  toast(`${p.name} disconnected`);
});

// The dropdown's own keys and focus. These listeners are on the document because the popup is drawn when it opens.
document.addEventListener("input", (e) => {
  if (e.target.id === "connect-search") showConnectOptions(e.target.value);
});
document.addEventListener("focusin", (e) => {
  if (e.target.id === "connect-search") {
    e.target.select();
    showConnectOptions("");
  } else if (connectList && !e.target.closest?.("#connect-combo")) hideConnectOptions();
});
document.addEventListener("mousedown", (e) => {
  if (connectList && !e.target.closest?.("#connect-combo")) hideConnectOptions();
});
document.addEventListener("keydown", (e) => {
  if (e.target.id !== "connect-search") return;
  const open = !$("#connect-options").hidden;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!open) showConnectOptions("");
    moveConnectOption(e.key === "ArrowDown" ? 1 : -1);
  } else if (e.key === "Enter") {
    e.preventDefault();
    const typed = e.target.value.trim().toLowerCase();  // the exact name wins over the first match
    const exact = connectList.find((p) => p.name.toLowerCase() === typed);
    const option = $(".combo-option.active") || $(".combo-option");
    if (open && (exact || option)) pickProvider(option?.classList.contains("active") ? option.dataset.id : exact?.id || option.dataset.id);
  } else if (e.key === "Escape" && open) {
    e.preventDefault();
    e.stopPropagation();
    hideConnectOptions();
    e.target.value = connectChosen?.name || "";
  }
});
