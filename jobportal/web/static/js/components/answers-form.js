/* answers-form.js: the standard questions. The full form (Settings, Profile, Standard answers) and the input for one
   question (Home asks them one at a time, and checks what it read from your resume). The questions come from the server
   (GET /api/onboarding returns them as sections of fields with an id, label, type, options, help, placeholder and
   required), so adding a question needs no change here: see QUESTIONS in candidate/onboarding.py. */
"use strict";

// The input for one question, by its type: text, email, tel, url, select (pick one), multi (pick several), list (one
// item per line) or textarea. big = Home's one-question card, where a select's options are buttons that answer at once.
// extra adds attributes to a single input (Home labels it with the question above it).
function answerInput(f, value, big, extra = "") {
  const id = esc(f.id), placeholder = `placeholder="${esc(f.placeholder || "")}" ${extra}`;
  if (f.type === "select") {
    if (!big) return `<select data-qf="${id}" ${extra}>${selectOptions([["", "Choose one"], ...f.options], value)}</select>`;
    return `<div class="choice-row">${f.options.map(([key, label]) => `<button type="button" class="choice${value === key ? " active" : ""}"`
      + ` data-act="home-pick" data-id="${id}" data-value="${esc(key)}">${esc(label)}</button>`).join("")}</div>`;
  }
  if (f.type === "multi") {  // a checkbox per option, drawn as a pill
    const chosen = value || [];
    return `<div class="choice-row">${f.options.map(([key, label]) => `<label class="choice${chosen.includes(key) ? " active" : ""}">`
      + `<input type="checkbox" data-qm="${id}" value="${esc(key)}"${chosen.includes(key) ? " checked" : ""}>${esc(label)}</label>`).join("")}</div>`;
  }
  if (f.type === "list") return `<textarea data-ql="${id}" rows="${big ? 4 : 3}" ${placeholder}>${esc((value || []).join("\n"))}</textarea>`;
  if (f.type === "textarea") return `<textarea data-qf="${id}" rows="${f.id === "writing_sample" ? 8 : 3}" ${placeholder}>${esc(value || "")}</textarea>`;
  const type = ["url", "email", "tel"].includes(f.type) ? f.type : "text";
  return `<input type="${type}" data-qf="${id}" value="${esc(value || "")}" ${placeholder}>`;
}

// The full form: a panel per section and a field per question. values are your saved answers. fromResume lists the
// questions answered from your resume that you haven't checked yet; they get a tag.
function answersForm(sections, values, fromResume = []) {
  const field = (f) => {
    const wide = ["multi", "textarea", "list"].includes(f.type);
    const tag = fromResume.includes(f.id) ? `<span class="tag green" title="Read from your resume. Check it.">FROM RESUME</span>` : "";
    const label = `<span class="field-label">${esc(f.label)}${f.required ? `<b class="req" title="Required">*</b>` : ""}${tag}</span>`;
    const help = f.help ? `<small>${esc(f.help)}</small>` : "";
    // A pill group holds labels of its own, so its field is a <div>; every other field is a <label> around its input.
    const tagName = f.type === "multi" ? "div" : "label";
    return `<${tagName} class="field${wide ? " wide" : ""}">${label}${answerInput(f, values[f.id])}${help}</${tagName}>`;
  };
  return sections.map((section) => `<section class="panel form-section"><h2>${esc(section.title)}</h2>`
    + `${section.help ? `<p>${esc(section.help)}</p>` : ""}<div class="form-grid">${section.fields.map(field).join("")}</div></section>`).join("");
}

// Reads the inputs inside root back into { question id: answer }. List fields become arrays of lines, multi-choice
// fields arrays of the options picked.
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

// True when an answer has content: a non-blank string, or a list with at least one non-blank item.
const filled = (value) => (Array.isArray(value) ? value.some((x) => String(x).trim()) : !!String(value ?? "").trim());

// The labels of the required questions left empty. Reads the question list from S.onboarding (GET /api/onboarding).
function missingRequired(answers) {
  const labels = {};
  (S.onboarding?.questions || []).forEach((section) => section.fields.forEach((f) => (labels[f.id] = f.label)));
  return (S.onboarding?.required || []).filter((id) => !filled(answers[id])).map((id) => labels[id] || id);
}

// A multi-choice pill lights up while its checkbox is checked.
document.addEventListener("change", (e) => {
  if (e.target.dataset?.qm != null) e.target.closest(".choice")?.classList.toggle("active", e.target.checked);
});
