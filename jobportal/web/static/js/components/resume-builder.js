/* resume-builder.js: the resume builder, for anyone who doesn't have a resume yet. Home's resume card ("No resume?") and
   the main resume's "Change your answers" open it in a dialog. Its questions and text boxes come from the server
   (GET /api/onboarding/builder: contact details, the work you want, school, work and volunteering, skills, certifications,
   projects), filled in with what you wrote last time. "Write my resume" sends them (POST /api/onboarding/builder). The AI
   writes the resume from exactly what you wrote, it becomes your main resume, and a copy goes to Settings, Resumes. The
   standard questions among them are saved as your answers, so Home doesn't ask them again. */
"use strict";

let builderForm = null;  // GET /api/onboarding/builder, while the dialog is open

// The questions in each part of the dialog, by id (the server's standard questions and the builder's own fields).
const BUILDER_PARTS = [
  ["Contact", ["name", "email", "phone", "city", "state", "linkedin", "github"]],
  ["Target jobs", ["target_roles"]],
  ["Education", ["education_level", "school", "field_of_study", "graduation", "gpa", "enrolled", "school_notes"]],
  ["Skills", ["skills", "languages"]],
  ["Licenses", ["licenses"]],
  ["Projects and awards", ["projects"]],
];

// One question of the builder, with its label and a star when it's required.
function builderField(id) {
  const f = [...builderForm.questions, ...builderForm.extra].find((field) => field.id === id);
  if (!f) return "";
  const wide = ["multi", "textarea", "list"].includes(f.type);
  const star = builderForm.required.includes(id) ? `<b class="req" title="Required">*</b>` : "";
  const tagName = f.type === "multi" ? "div" : "label";
  return `<${tagName} class="field${wide ? " wide" : ""}"><span class="field-label">${esc(f.label)}${star}</span>`
    + `${answerInput(f, builderForm.answers[id])}</${tagName}>`;
}

// One job, paid or not, with a button that removes it.
function builderJob(job = {}) {
  const input = (f) => f.type === "textarea"
    ? `<textarea data-jf="${esc(f.id)}" rows="3" placeholder="${esc(f.placeholder || "")}">${esc(job[f.id] || "")}</textarea>`
    : `<input type="text" data-jf="${esc(f.id)}" value="${esc(job[f.id] || "")}" placeholder="${esc(f.placeholder || "")}">`;
  return `<div class="builder-job"><div class="form-grid">${builderForm.job.map((f) =>
    `<label class="field${f.type === "textarea" ? " wide" : ""}"><span class="field-label">${esc(f.label)}</span>${input(f)}</label>`).join("")}</div>
    <div class="block-actions end"><button class="button text" type="button" data-act="builder-remove-job">${icon("trash")}Remove</button></div></div>`;
}

// Opens the builder. With a main resume that the builder didn't write, it says that the new one takes its place.
async function openResumeBuilder() {
  builderForm = await api("/api/onboarding/builder");
  const jobs = builderForm.jobs.length ? builderForm.jobs : [{}, {}];
  const replaces = S.onboarding?.resume && !S.onboarding.resume_from_builder
    ? `<div class="banner warn">${icon("warning")}<div>Replaces ${esc(S.onboarding.resume.filename)}</div></div>` : "";
  const dialog = openDialog(`<h2>Resume builder</h2>
    ${replaces}
    <div class="builder" data-builder>
      ${BUILDER_PARTS.slice(0, 3).map(builderPart).join("")}
      <section class="form-section"><h3>Work and volunteering</h3>
        <div data-builder-jobs>${jobs.map(builderJob).join("")}</div>
        <button class="button light small" type="button" data-act="builder-add-job">${icon("plus")}Add</button></section>
      ${BUILDER_PARTS.slice(3).map(builderPart).join("")}
    </div>
    <div class="dialog-actions"><span class="spacer"></span>
      <button class="button primary" type="button" data-act="builder-write">${icon("sparkle")}Write resume</button></div>`,
    { wide: true, guard: true, onClose: () => (builderForm = null) });
  dialog.addEventListener("input", () => (S.dirty = true));  // typed answers count as unsaved until the resume is written
}

const builderPart = ([title, ids]) => `<section class="form-section"><h3>${esc(title)}</h3>
  <div class="form-grid">${ids.map(builderField).join("")}</div></section>`;

// ---------------------------------------------------------------- actions
onAction("open-builder", () => openResumeBuilder());
onAction("builder-add-job", (el) => {
  $("[data-builder-jobs]", el.closest("dialog")).insertAdjacentHTML("beforeend", builderJob());
});
onAction("builder-remove-job", (el) => {
  el.closest(".builder-job").remove();
  S.dirty = true;
});
onAction("builder-write", async (el) => {
  const dialog = el.closest("dialog"), root = $("[data-builder]", dialog);
  const answers = readAnswersForm(root);
  const jobs = $$(".builder-job", root).map((job) => Object.fromEntries($$("[data-jf]", job).map((input) => [input.dataset.jf, input.value.trim()])));
  const labels = Object.fromEntries([...builderForm.questions, ...builderForm.extra].map((f) => [f.id, f.label]));
  const missing = builderForm.required.filter((id) => !filled(answers[id])).map((id) => labels[id] || id);
  if (missing.length) {
    toast("Required", missing.join(", "), "error");
    return;
  }
  const label = el.innerHTML;
  el.disabled = true;
  el.innerHTML = `${spinner()}Writing`;
  try {
    const r = await api("/api/onboarding/builder", { method: "POST", body: { answers, jobs } });
    S.dirty = false;
    closeDialog(dialog);
    toast("Resume ready", r.notes.join(" "));
    if (r.status) onProfileStatus(r.status);
    await reloadOnboarding();  // Home moves on to the next question
  } finally {
    el.disabled = false;
    el.innerHTML = label;
  }
});
