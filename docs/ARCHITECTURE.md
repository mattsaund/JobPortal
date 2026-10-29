# How JobPortal works

JobPortal is a local web app that looks like a desktop app. A FastAPI server runs on 127.0.0.1, and a plain JavaScript
dashboard talks to it. The dashboard shows in a native window (pywebview), in Chrome, Edge, Chromium or Brave in app mode,
or in a browser tab. Data lives in SQLite in the user's app-data folder. All AI work runs through OpenAI's Responses API on
the user's own ChatGPT plan, authorized with Sign in with ChatGPT.

```
             resume + standard answers + questions along the way
                                 |
                                 v
  setup (candidate/onboarding.py) --> profile (candidate/profile.py) --> search plan, skills, record, stories
                                 |
                                 v
  search run (search/pipeline.py): collectors --> rule filters --> AI triage --> AI packages --> leads
                                 ^                                         |
                                 |                                         v
                     questions (profile.ask) <------------- gaps found while packaging
```

## The packages

| Package | What it holds | Uses |
|---|---|---|
| `core/` | config and settings, the database, live updates (`bus.py`), background tasks, OS differences, text helpers, levels and genres | nothing else in JobPortal |
| `ai/` | the Responses API client, Sign in with ChatGPT, every prompt | `core` |
| `documents/` | reading imported files, rendering resumes, resume checks, downloads, AI edits | `core`, `ai`, `candidate` |
| `candidate/` | setup, the profile, questions along the way, saved resumes | `core`, `ai`, `documents` |
| `search/` | the search run, what to search for, the collectors, the Sources page checks | everything above |
| `insights/` | the Analysis and Equity mining pages | `core`, `ai`, `candidate` |
| `web/` | the FastAPI app, the routes, the dashboard files | everything above |
| `app/` | the command line, the app window, `--doctor` | `web`, `core` |

Lower packages never import higher ones at module level. When a lower module needs a higher one (for example, the profile
asking the search run to re-score leads), it imports inside the function. That keeps import cycles out.

## A request, start to finish

1. A page in `web/static/js/pages/` calls `api("/api/...")` (defined in `js/core.js`).
2. `web/server.py` checks every request twice. The Host must be this computer, which blocks DNS rebinding. A change (not a
   GET) must come from the dashboard's own origin, so another website can't send one.
3. The route in `web/routes/<area>.py` checks the input and calls the package that does the work.
4. Long jobs (building a package, rebuilding the profile, an AI analysis) start with `core/background.py` and return right
   away. Their progress and results go out as live events: `core/bus.py` publishes, `/api/events` streams them
   (Server-Sent Events), and `js/live.js` updates the open page.

## The profile

`candidate/profile.py` holds what JobPortal knows about the user, stored as sections in the `kv` table (`profile.<section>`):

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

The inputs sit next to it: `profile.resume` (the imported resume's text), `profile.answers` (the standard answers) and
`profile.questions` (questions asked along the way, with answers). These three are the only inputs. Saved resumes, leads
and web results never feed the profile, and `tests/test_profile.py` checks that.

A **build** reads all inputs and writes every AI section. An **update** folds in new answers and returns only the sections
that change. Standard answers always win over what the AI read from the resume. Every save keeps the previous version in
the `profile_history` table. A background task (`answers_watcher`) adds new answers about a minute after the user stops
answering, and a search run adds any waiting answers before it starts.

## Setup

`candidate/onboarding.py` defines the standard questions (`QUESTIONS`) as data, so the dashboard renders the form from the
API and one place controls the wording. Importing a resume extracts its text (`documents/extract.py`) and pre-fills the
questions with a cheap AI call plus regular expressions. Saving the answers writes `facts` and `qa` directly and turns the
answers into settings: experience levels, title filters (`core/levels.py`), allowed locations, dream companies and
clearance keywords.

## A search run

`search/pipeline.py` runs the collectors in `search/collectors/` side by side. What they search for comes from
`search/plan.py`: the user's levels, target roles, queries and dream companies, combined from settings and the profile's
search plan. Then:

1. **Rule filters** (`RuleFilters`) drop titles that don't match the user's levels, too-senior titles, jobs outside the
   search area, old postings and excluded companies or keywords. Location matching lives in `core/textutil.py`
   (`LocationMatcher`). Dream companies can skip the location filter if the user allows it.
2. **Dedupe** merges jobs seen before, by fingerprint and by URL.
3. **AI triage** scores candidates in batches against `profile.digest()` (stage `triage`). Candidates the per-run cap
   doesn't reach are saved to a backlog and triaged first next time.
4. **Packages** are built for qualified leads, best first, with deadlines jumping the line (stage `package`). Each resume then
   goes through deterministic checks (`documents/resumecheck.py`) and a recruiter-critic AI pass.

The AI hunt (`search/collectors/hunt.py`) runs web-search agents from the missions in `ai/prompts.py`. Each mission reads the
profile, so the same missions work for anyone.

## Sign in with ChatGPT

`ai/signin.py` registers JobPortal as an open-source local client (`dynamic_agent_client` with a stable host id). The
dashboard opens OpenAI's authorize page in the system browser. OpenAI redirects back to
`http://127.0.0.1:<port>/auth/callback` on JobPortal's own server, which exchanges the code (PKCE), checks the ID token claims
and stores the tokens in the data folder. Access tokens last an hour and refresh near expiry. Refresh tokens rotate, so
refreshes run one at a time.

## AI calls

`ai/client.py` is the only place that talks to OpenAI. Each call picks a model and reasoning effort by stage (prefill,
triage, hunt, package, revise, profile, analysis; see Settings) and streams one stateless Responses request
(`store: false`). The model returns its result by calling `submit_result`, whose parameters are the task's JSON schema. Web
tasks also get `fetch_url` (run by JobPortal, public addresses only) and OpenAI's hosted web search when the account allows
it. Tool calls loop until `submit_result` arrives or the step budget runs out. Every call is logged in the `ai_calls` table
with its token count. A usage-cap error pauses the current run.

## The dashboard

`web/static/index.html` loads plain scripts in order: `js/core.js` (helpers, the state `S`, toasts, the action registry),
`js/live.js` (live events), `js/layout.js` (sidebar and the hash router), `js/components/`, one file per page in
`js/pages/`, and `js/main.js` last. There's no build step and no framework.

- **Routing.** The URL hash picks the page: `#/leads`, `#/lead/12`, `#/profile/questions`. `ROUTES` in `layout.js` maps each
  name to its page's render function.
- **Clicks.** Any element with `data-act="name"` runs the handler a page registered with `onAction("name", fn)`. `main.js`
  holds the one listener that dispatches them, so each page keeps its buttons and their handlers in the same file.
- **Load order.** Top-level code may only use things from files loaded earlier. Wrap anything else in a function.

## The app window

`app/desktop.py` starts the server in a background thread, then picks the best window it can:

1. A native window through pywebview: Edge WebView2 on Windows, WebKit on macOS, GTK or Qt on Linux.
2. Without a toolkit (the Linux AppImage), Chrome, Edge, Chromium or Brave in app mode, with a separate profile. JobPortal
   quits when that window closes.
3. A normal browser tab. Closing the tab leaves JobPortal running, so Settings has a Quit button.

Run as an AppImage, JobPortal also adds itself to the Linux app menu.

## Packaging and releases

- `packaging/jobportal.spec` builds the app with PyInstaller. `packaging/entry.py` is the frozen app's entry point. It sends
  output to a log file when there's no console, and on Linux it restores the library path for programs JobPortal starts.
- `.github/workflows/release.yml` runs on a version tag. It builds on Windows, macOS and Linux, bundles Chrome Headless
  Shell as the PDF engine on macOS and Linux (`packaging/fetch_pdf_engine.py`), smoke-tests each app (server, dashboard and
  a real PDF export), then wraps them: an Inno Setup installer on Windows (`packaging/windows/jobportal.iss`), a disk image
  on macOS and an AppImage on Linux.

## Cross-platform pieces

- `core/config.py` picks the data and cache folders with `platformdirs` (overridable with `JOBPORTAL_HOME`).
- `core/osutil.py` opens files and links, sends notifications, and finds the PDF engine and LibreOffice on each system.
- `documents/extract.py` reads PDF, DOCX, ODT and RTF in pure Python (pypdf, python-docx).
- `documents/render.py` prints PDFs with the bundled engine or an installed Chromium browser.
- `app/cli.py` handles the server modes with a PID file instead of system tools.
