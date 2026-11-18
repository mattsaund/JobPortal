"""The resume builder, for people who don't have a resume yet. They answer a few questions and fill in a few text boxes on
Home, and the AI writes a first resume from exactly what they wrote.

How it fits: web/routes/candidate.py serves the form (form()) and sends the answers to write_resume(). The resume it
writes then works like an imported one (onboarding.import_resume): it's the main resume the profile is built from, and
the route keeps a copy in Settings, Resumes to edit and download. The answers that are standard questions too (contact
details, school, licenses, the jobs they want) are saved as standard answers through onboarding.merge_answers(), the
same way Home saves each answer, so Home never asks them again and there's nothing to check.

Key ideas:
- Nothing is invented. The AI may reword, organize and tighten what the person wrote, but every employer, title, date,
  school, skill, number and award must come from their answers (prompts.BUILDER_SYSTEM). The resume playbook guides the
  wording, as it does for every resume JobPortal writes.
- The form is data, like the standard questions: STANDARD_IDS names the standard questions it reuses, and EXTRA_FIELDS and
  JOB_FIELDS are its own. The dashboard draws it from form(), so a new field needs no change there.
- What they wrote is kept ("onboarding.builder"), so coming back fills the form in again to change something and write
  the resume again."""
from jobportal.ai import client as ai, prompts
from jobportal.candidate import library, onboarding, profile
from jobportal.core import db, settings as settings_mod
from jobportal.documents import extract

FILENAME = onboarding.BUILDER_FILENAME  # the main resume's file name, as Home and Settings show it
LIBRARY_NAME = "Resume made in JobPortal"  # the copy in Settings, Resumes
MAX_JOBS = 10  # entries in "Work and volunteering"
MAX_TEXT = 3000  # characters kept from each text box

# The standard questions the builder asks too, in the order it asks them. Their answers become standard answers.
STANDARD_IDS = ["name", "email", "phone", "city", "state", "linkedin", "github", "target_roles", "education_level", "school",
                "field_of_study", "graduation", "gpa", "enrolled", "licenses"]
REQUIRED_IDS = ["name", "email", "city", "target_roles"]
# The builder's own fields, after the standard ones. Same shape as onboarding.QUESTIONS fields.
EXTRA_FIELDS = [
    {"id": "school_notes", "label": "Honors, activities or classes that fit the jobs you want (optional)", "type": "textarea",
     "placeholder": "Honor roll, Spanish club, Intro to Welding"},
    {"id": "skills", "label": "Your skills, one per line", "type": "list",
     "placeholder": "Customer service\nCash handling\nMicrosoft Excel\nForklift"},
    {"id": "languages", "label": "Languages you speak (optional)", "type": "text", "placeholder": "English, Spanish"},
    {"id": "projects", "label": "Projects, activities and awards (optional)", "type": "textarea",
     "placeholder": "Built a website for my church\nTeam captain, varsity soccer\nEmployee of the Month, June 2025"},
]
# One entry in "Work and volunteering". Paid or not, any length.
JOB_FIELDS = [
    {"id": "role", "label": "Job title or role", "type": "text", "placeholder": "Cashier, Volunteer tutor, Babysitter"},
    {"id": "organization", "label": "Where", "type": "text", "placeholder": "Corner Market"},
    {"id": "place", "label": "City and state (optional)", "type": "text", "placeholder": "Columbus, OH"},
    {"id": "dates", "label": "When", "type": "text", "placeholder": "June 2025 to now"},
    {"id": "details", "label": "What you did, one thing per line", "type": "textarea",
     "placeholder": "Ran the register on busy weekends\nTrained two new hires"},
]
EXTRA_IDS = [f["id"] for f in EXTRA_FIELDS]
JOB_IDS = [f["id"] for f in JOB_FIELDS]


def form() -> dict:
    """The form for the dashboard: the standard questions it asks (with their labels, types and options), its own fields,
    the fields of one job, which ones are required, and the answers to start from: what was written here last time, else
    the standard answers saved so far."""
    saved = db.kv_get("onboarding.builder") or {}
    current = profile.standard_answers()
    start = {key: current[key] for key in STANDARD_IDS if onboarding._filled(current.get(key))}
    return {"questions": [onboarding.FIELDS[key] for key in STANDARD_IDS], "extra": EXTRA_FIELDS, "job": JOB_FIELDS,
            "required": REQUIRED_IDS, "answers": {**start, **(saved.get("answers") or {})}, "jobs": saved.get("jobs") or []}


def _clean(raw: dict) -> tuple[dict, list[dict]]:
    """The answers and jobs from the request, with unknown keys dropped, text trimmed and cut to MAX_TEXT, lists as lists,
    and empty jobs left out."""
    answers: dict = {}
    for key, value in (raw.get("answers") or {}).items():
        if key not in STANDARD_IDS and key not in EXTRA_IDS:
            continue
        if isinstance(value, list):
            answers[key] = [str(x).strip()[:MAX_TEXT] for x in value if str(x).strip()][:40]
        else:
            answers[key] = str(value or "").strip()[:MAX_TEXT]
    jobs = []
    for job in raw.get("jobs") or []:
        if isinstance(job, dict):
            entry = {key: str(job.get(key) or "").strip()[:MAX_TEXT] for key in JOB_IDS}
            if entry["role"] or entry["organization"] or entry["details"]:
                jobs.append(entry)
    return answers, jobs[:MAX_JOBS]


def _section(title: str, lines) -> str:
    """One labeled block of the prompt. "(nothing)" when there's nothing in it."""
    body = "\n".join(line for line in lines if line) or "(nothing)"
    return f"=== {title} ===\n{body}"


def _prompt(answers: dict, jobs: list[dict]) -> str:
    """Everything the AI writes the resume from: the person's answers, the resume playbook and the resume format."""
    label = onboarding.label_of
    joined = lambda key: ", ".join(answers.get(key) or []) if isinstance(answers.get(key), list) else answers.get(key, "")  # noqa: E731
    contact = [f"{onboarding.FIELDS[key]['label']}: {answers[key]}" for key in ("name", "email", "phone", "city", "state",
                                                                                  "linkedin", "github") if answers.get(key)]
    school = [f"{onboarding.FIELDS[key]['label']}: {label(key, answers[key])}" for key in
              ("education_level", "school", "field_of_study", "graduation", "gpa", "enrolled") if answers.get(key)]
    if answers.get("school_notes"):
        school.append(f"Honors, activities or classes: {answers['school_notes']}")
    work = []
    for n, job in enumerate(jobs, 1):
        head = ", ".join(part for part in (job["role"], job["organization"], job["place"], job["dates"]) if part)
        work.append(f"{n}. {head}\n{job['details']}".rstrip())
    return "\n\n".join([
        _section("THE JOBS THEY WANT", answers.get("target_roles") or []),
        _section("CONTACT DETAILS", contact),
        _section("SCHOOL AND TRAINING", school),
        _section("WORK AND VOLUNTEERING, AS THEY WROTE IT", work),
        _section("SKILLS", answers.get("skills") or []),
        _section("LANGUAGES", [joined("languages")]),
        _section("CERTIFICATIONS AND LICENSES", answers.get("licenses") or []),
        _section("PROJECTS, ACTIVITIES AND AWARDS", [answers.get("projects", "")]),
        _section("RESUME PLAYBOOK (how good resumes are written)", [settings_mod.resume_playbook()]),
        prompts.RESUME_FORMAT,
    ])


async def write_resume(raw: dict) -> dict:
    """Write a resume from the builder's answers and make it the main resume.

    Saves what was written (for next time), asks the AI for the resume (one call, stage "profile"), imports it as the main
    resume without a pre-fill (the answers are known already), and saves the standard answers among them. Returns
    {"markdown", "notes" (what the AI suggests adding), "resume" (the main resume's details), "answers" (merge_answers'
    result, with "first_complete")}. Raises ValueError when a required answer is missing, and ai.AIError when the AI
    fails or writes something too short to be a resume."""
    answers, jobs = _clean(raw)
    missing = [onboarding.FIELDS[key]["label"] for key in REQUIRED_IDS if not onboarding._filled(answers.get(key))]
    if missing:
        raise ValueError(f"Fill in {', '.join(missing)} first.")
    db.kv_set("onboarding.builder", {"answers": answers, "jobs": jobs, "saved_at": db.now()})
    out = await ai.run(_prompt(answers, jobs), system=prompts.system("builder", prompts.BUILDER_SYSTEM),
                       schema=prompts.BUILDER_SCHEMA, stage="profile", purpose="resume-builder", label="setup: write resume",
                       timeout=900)
    markdown = str(out.get("resume_md") or "").strip()
    if len(markdown) < extract.MIN_CHARS:
        raise ai.AIError("the AI didn't write a usable resume. Try again.")
    if not markdown.startswith("# "):  # the renderer needs the name as the title
        markdown = f"# {answers['name']}\n{markdown}"
    imported = await onboarding.import_resume(FILENAME, text=markdown, do_prefill=False)
    saved = onboarding.merge_answers({key: answers[key] for key in STANDARD_IDS if onboarding._filled(answers.get(key))})
    notes = [str(note).strip() for note in out.get("notes") or [] if str(note).strip()][:4]
    return {"markdown": markdown, "notes": notes, "resume": imported["resume"], "answers": saved}


def keep_in_library(markdown: str) -> dict:
    """Keep the builder's resume in Settings, Resumes, to edit and download. Writing it again updates the same copy, so
    there's one. Returns the saved item. Like every saved resume, it never feeds the profile."""
    row = db.one("SELECT id FROM resume_library WHERE source='builder' ORDER BY id DESC LIMIT 1")
    if row:
        return library.update(row["id"], {"md": markdown})
    return library.create(LIBRARY_NAME, markdown, source="builder", notes="Written by the resume builder from your answers")
