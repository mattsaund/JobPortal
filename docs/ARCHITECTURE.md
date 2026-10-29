# How JobPortal works

JobPortal is a local web app: a FastAPI server on 127.0.0.1 with a vanilla JavaScript dashboard, shown in a native window
(pywebview) or the browser. Data lives in SQLite in the user's app-data folder. All AI work runs through the Claude Code CLI
(`claude -p`) on the user's own account.

```
             resume + standard answers + answers along the way
                                 |
                                 v
  setup (onboarding.py) --> profile (profile.py) --> search plan, skills, record, stories
                                 |
                                 v
  search run (pipeline.py):  collectors --> rule filters --> AI triage --> AI packages --> Leads
                                 ^                                  |
                                 |                                  v
                     questions (profile.ask) <-------- gaps found while packaging
```

## The profile

`profile.py` holds what JobPortal knows about the user, stored as sections in the `kv` table (`profile.<section>`):

| Section | What it is |
|---|---|
| `facts` | contact details, school, degree, graduation, GPA, work authorization, clearance, skills |
| `project_bank` | the experience, education and project record every resume is written from |
| `story_bank` | interview stories (STAR) |
| `targeting` | what the user wants, plus eligibility facts and dealbreakers |
| `qa` | the standard application answers, built directly from the standard questions (no AI) |
| `search_plan` | role families, search queries and target companies |
| `provenance` | where each key fact came from |
| `skills_inventory` | every skill with a level (strong, working, listed) and evidence |
| `voice` | a style guide learned from the user's writing sample |

Inputs live next to it: `profile.resume` (the imported resume's text), `profile.answers` (the standard answers) and
`profile.questions` (questions asked along the way, with answers). A **build** reads all inputs and writes every AI section;
an **update** folds in new answers and returns only the sections that change. Standard answers always win over what the AI
read from the resume. Every save keeps the previous version in the `profile_history` table.

A background task (`answers_watcher`) adds new answers to the profile about a minute after the user stops answering, and a
search run adds any waiting answers before it starts.

## Setup

`onboarding.py` defines the standard questions (`QUESTIONS`) as data, so the dashboard renders the form from the API and one
place controls the wording. Importing a resume extracts its text (`extract.py`) and pre-fills the questions with a cheap AI
call plus regular expressions. Saving the answers writes `facts` and `qa` directly and maps the answers onto settings:
experience levels, title filters (`levels.py`), allowed locations, dream companies and clearance keywords.

## A search run

`pipeline.py` runs collectors in parallel (`collectors/`), then:

1. **Rule filters** drop titles that don't match the user's levels, locations outside the search area, old postings and
   excluded companies or keywords, and dedupe against everything seen before.
2. **AI triage** scores candidates in batches against `profile.digest()` (stage `triage`). Candidates the per-run cap doesn't
   reach are saved to a backlog and triaged first next time.
3. **Packages** are built for qualified leads, best first, with deadlines jumping the line (stage `package`). Each resume then
   goes through deterministic checks (`resumecheck.py`) and a recruiter-critic AI pass.

The AI hunt (`collectors/hunt.py`) runs web-search agents from `prompts.DEFAULT_MISSIONS`; each one reads the profile, so the
same missions work for anyone.

## AI calls

`claude.py` is the only place that starts Claude Code. Each call picks a model and effort by stage (prefill, triage, hunt,
package, revise, profile, analysis; see Settings), passes the system prompt through a temporary file and the prompt through
stdin, asks for structured output with a JSON schema, and allows only WebSearch and WebFetch. Every call is logged in the
`ai_calls` table with its cost.

## Cross-platform pieces

- `config.py` picks the data and cache folders with `platformdirs` (overridable with `JOBPORTAL_HOME`).
- `osutil.py` opens files and links, sends notifications, and finds Chrome or Edge, LibreOffice and Claude Code on each system.
- `extract.py` reads PDF, DOCX, ODT and RTF in pure Python (pypdf, python-docx).
- `render.py` prints PDFs with whichever Chromium browser is installed.
- `desktop.py` picks the window toolkit and falls back to the browser; `cli.py` handles the server modes with a PID file
  instead of system tools.

## The dashboard

`static/app.js` is one file organized by page (look for the `// ====` section headers). It talks to `/api/*` and listens to
`/api/events` (Server-Sent Events from `bus.py`) for live updates: run progress, new leads, profile status and toasts.

## Common changes

| To | Edit |
|---|---|
| change or add a standard question | `QUESTIONS` in `onboarding.py` (and `facts_from_answers` / `qa_from_answers` if it should feed them) |
| change what the AI writes | the prompt in `prompts.py` |
| add a job source | a collector in `collectors/`, registered in `collectors/__init__.py`, with defaults in `config.py` |
| add a company board | Sources page, or `ATS_BOARDS` in `config.py` |
| change resume layouts | `RESUME_THEMES` in `render.py` and the playbook in `resources/resume_playbook.md` |
| add an operating-system feature | `osutil.py` |
