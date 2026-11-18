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
  ["About you", "", ["name", "email", "phone", "city", "state", "linkedin", "github"]],
  ["The work you want", "", ["target_roles"]],
  ["School and training", "Finished or still going. Leave out what doesn't apply.", ["education_level", "school", "field_of_study", "graduation", "gpa", "enrolled", "school_notes"]],
  ["Skills and languages", "", ["skills", "languages"]],
  ["Certifications and licenses", "", ["licenses"]],
  ["Projects, activities and awards", "", ["projects"]],
];

// One question of the builder, with its label, a star when it's required, and its help.
function builderField(id) {
  const f = [...builderForm.questions, ...builderForm.extra].find((field) => field.id === id);
  if (!f) return "";
  const wide = ["multi", "textarea", "list"].includes(f.type);
  const star = builderForm.required.includes(id) ? `<b class="req" title="Required">*</b>` : "";
  const tagName = f.type === "multi" ? "div" : "label";
  return `<${tagName} class="field${wide ? " wide" : ""}"><span class="field-label">${esc(f.label)}${star}</span>`
    + `${answerInput(f, builderForm.answers[id])}${f.help ? `<small>${esc(f.help)}</small>` : ""}</${tagName}>`;
}

// One job, paid or not, with a button that removes it.
function builderJob(job = {}) {
  const input = (f) => f.type === "textarea"
    ? `<textarea data-jf="${esc(f.id)}" rows="3" placeholder="${esc(f.placeholder || "")}">${esc(job[f.id] || "")}</textarea>`
    : `<input type="text" data-jf="${esc(f.id)}" value="${esc(job[f.id] || "")}" placeholder="${esc(f.placeholder || "")}">`;
  return `<div class="builder-job"><div class="form-grid">${builderForm.job.map((f) =>
    `<label class="field${f.type === "textarea" ? " wide" : ""}"><span class="field-label">${esc(f.label)}</span>${input(f)}</label>`).join("")}</div>
    <div class="block-actions end"><button class="button text" type="button" data-act="builder-remove-job">${icon("trash")}Remove this one</button></div></div>`;
}

// Opens the builder. With a main resume that the builder didn't write, it says that the new one takes its place.
async function openResumeBuilder() {
  builderForm = await api("/api/onboarding/builder");
  const jobs = builderForm.jobs.length ? builderForm.jobs : [{}, {}];
  const replaces = S.onboarding?.resume && !S.onboarding.resume_from_builder
    ? `<div class="banner warn">${icon("warning")}<div>Your new resume takes the place of ${esc(S.onboarding.resume.filename)} as your main resume.</div></div>` : "";
  const dialog = openDialog(`<h2>Let's write your resume</h2>
    <p>Answer what you can. JobPortal writes your resume from exactly what you put here and never adds anything you didn't.</p>
    ${replaces}
    <div class="builder" data-builder>
      ${BUILDER_PARTS.slice(0, 3).map(builderPart).join("")}
      <section class="form-section"><h3>Work and volunteering</h3>
        <p class="panel-note">Paid or not, it all counts: part-time jobs, internships, volunteering, babysitting, a family business, the military.</p>
        <div data-builder-jobs>${jobs.map(builderJob).join("")}</div>
        <button class="button light small" type="button" data-act="builder-add-job">${icon("plus")}Add another</button></section>
      ${BUILDER_PARTS.slice(3).map(builderPart).join("")}
    </div>
    <div class="dialog-actions"><span class="spacer"></span>
      <button class="button primary" type="button" data-act="builder-write">${icon("sparkle")}Write my resume</button></div>`,
    { eyebrow: "RESUME BUILDER", wide: true, guard: true, onClose: () => (builderForm = null) });
  dialog.addEventListener("input", () => (S.dirty = true));  // typed answers count as unsaved until the resume is written
}

const builderPart = ([title, note, ids]) => `<section class="form-section"><h3>${esc(title)}</h3>${note ? `<p class="panel-note">${esc(note)}</p>` : ""}
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
    toast("A few answers are needed", `Fill in ${missing.join(", ")}.`, "error");
    return;
  }
  const label = el.innerHTML;
  el.disabled = true;
  el.innerHTML = `${spinner()}Writing your resume`;
  try {
    const r = await api("/api/onboarding/builder", { method: "POST", body: { answers, jobs } });
    S.dirty = false;
    closeDialog(dialog);
    toast("Your resume is ready", r.notes.length ? r.notes.join(" ") : "It's your main resume now, with a copy in Settings, Resumes.");
    if (r.status) onProfileStatus(r.status);
    await reloadOnboarding();  // Home moves on to the next question
  } finally {
    el.disabled = false;
    el.innerHTML = label;
  }
});
