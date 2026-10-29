/* answers-form.js: the standard questions form, used by setup (step 3) and Profile > Standard answers. The questions come
   from the server (GET /api/onboarding returns them as sections of fields), so adding a question needs no change here:
   see QUESTIONS in candidate/onboarding.py. */
"use strict";

// The form for the given sections. values are your saved answers. prefill holds answers the AI read from your resume: a
// field whose value is still the prefilled one gets a "from resume" chip, so you know to check it.
function answersForm(sections, values, prefill) {
  const answers = values || {}, fromAI = prefill || {};
  const fromResume = (id) => (fromAI[id] != null && JSON.stringify(fromAI[id]) === JSON.stringify(answers[id])
    ? `<span class="chip violet pf" title="Filled in from your resume. Check it.">from resume</span>` : "");
  const field = (f) => {
    const value = answers[f.id];
    const required = f.required ? `<b class="req" title="required">*</b>` : "";
    const help = f.help ? `<div class="small muted">${esc(f.help)}</div>` : "";
    const head = `<span>${esc(f.label)}${required}${fromResume(f.id)}</span>`;
    const placeholder = `placeholder="${esc(f.placeholder || "")}"`;
    if (f.type === "select") {
      return `<label class="f">${head}<select data-qf="${f.id}">${selectOptions([["", "Choose one"], ...f.options], value)}</select>${help}</label>`;
    }
    if (f.type === "multi") {  // pick any number: a checkbox per option, styled as pills
      const chosen = value || [];
      const pills = f.options.map(([key, label]) => `<label class="chk ${chosen.includes(key) ? "on" : ""}">`
        + `<input type="checkbox" data-qm="${f.id}" value="${esc(key)}" ${chosen.includes(key) ? "checked" : ""}>${esc(label)}</label>`).join("");
      return `<div class="f qmulti" style="grid-column:1/-1"><label class="f">${head}</label><div class="row" style="gap:6px;margin-top:4px">${pills}</div>${help}</div>`;
    }
    if (f.type === "list") {  // one item per line
      return `<label class="f">${head}<textarea data-ql="${f.id}" rows="4" ${placeholder}>${esc((value || []).join("\n"))}</textarea>${help}</label>`;
    }
    if (f.type === "textarea") {
      const rows = f.id === "writing_sample" ? 8 : 3;
      return `<label class="f" style="grid-column:1/-1">${head}<textarea data-qf="${f.id}" rows="${rows}" ${placeholder}>${esc(value || "")}</textarea>${help}</label>`;
    }
    const type = ["url", "email", "tel"].includes(f.type) ? f.type : "text";
    return `<label class="f">${head}<input type="${type}" data-qf="${f.id}" value="${esc(value || "")}" ${placeholder}>${help}</label>`;
  };
  return sections.map((section) => `<div class="card qsec" style="margin-bottom:14px"><h3>${esc(section.title)}</h3>
    ${section.help ? `<p class="muted small" style="margin-top:-4px">${esc(section.help)}</p>` : ""}
    <div class="grid3">${section.fields.map(field).join("")}</div></div>`).join("");
}

// Reads the form back into { field id: answer }. List fields become arrays of lines, multi-choice fields arrays of values.
function readAnswersForm(root) {
  const out = {};
  $$("[data-qf]", root).forEach((el) => (out[el.dataset.qf] = el.value.trim()));
  $$("[data-ql]", root).forEach((el) => (out[el.dataset.ql] = el.value.split("\n").map((x) => x.trim()).filter(Boolean)));
  $$("[data-qm]", root).forEach((el) => {
    out[el.dataset.qm] = out[el.dataset.qm] || [];
    if (el.checked) out[el.dataset.qm].push(el.value);
  });
  return out;
}

// The labels of the required questions left empty. Reads the question list from S.onboarding (GET /api/onboarding).
function missingRequired(answers) {
  const required = (S.onboarding && S.onboarding.required) || [];
  const labels = {};
  ((S.onboarding && S.onboarding.questions) || []).forEach((section) => section.fields.forEach((f) => (labels[f.id] = f.label)));
  const isEmpty = (value) => (Array.isArray(value) ? !value.length : !String(value ?? "").trim());
  return required.filter((id) => isEmpty(answers[id])).map((id) => labels[id] || id);
}

// A multi-choice pill lights up while its checkbox is checked.
document.addEventListener("change", (e) => {
  if (e.target.dataset && e.target.dataset.qm != null) e.target.closest(".chk")?.classList.toggle("on", e.target.checked);
});
