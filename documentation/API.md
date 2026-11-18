# JobPortal API reference (v0.4.0)

Every endpoint of JobPortal's local server, which only answers on this computer (http://127.0.0.1:8788 by default). The
dashboard uses all of them. While JobPortal runs, FastAPI serves the same API as interactive docs at
http://127.0.0.1:8788/docs. This file is made from the server's routes and their docstrings, so it matches the code.

Every request must be addressed to 127.0.0.1 or localhost, and a change (anything but GET) from another site's page is
refused. Errors come back as JSON with a `detail` message. An AI failure is 401 when the AI needs connecting (a
sign-in or a key), 429 for a cap, no credit or a rate limit, and 502 for anything else from the AI service.

## App and live updates

From `jobportal/web/routes/system.py`.

### `GET /api/events`

Server-Sent Events. The dashboard keeps this connection open and gets every live update as it happens: run progress, new leads, profile changes and toasts. A comment line every 15 seconds keeps the connection from timing out.

### `GET /api/meta`

Facts the dashboard needs once at startup: version, system, data folder, choices for menus, and whether PDF export works.

### `GET /api/stats`

The numbers behind the sidebar's badges and Home's stats, plus the live run state.

### `POST /api/open-data-folder`

Show the folder that holds the database, generated files and the imported resume.

### `POST /api/open-external`

Open a web or mail link in the default browser or mail app. The app window (a browser in app mode) sends links here so they open outside it.

### `POST /api/quit`

Stop JobPortal. The dashboard offers this in a browser tab, where closing the tab leaves the server running. app/desktop.py hands the app its server object when it starts it.

## The AI: providers, sign-ins, keys and models

From `jobportal/web/routes/ai.py`.

### `GET /api/ai/status`

The AI in use and whether it's ready, who is signed in with ChatGPT, which providers have a key (never the keys or tokens themselves), tokens used since startup, and whether web search works.

### `GET /api/ai/providers`

Every AI JobPortal can run on, for the picker in Settings, AI and on the welcome screen.

### `POST /api/ai/provider`

Run the AI on another provider, {"provider": id}, with {"custom_url": "..."} for another service. The model choices go back to that provider's default.

### `PUT /api/ai/key`

Save a provider's API key, {"provider": id, "key": "..."}, and switch to that provider. The key is checked first by asking the provider for its model list, so a wrong key is caught now rather than in the middle of a search. A key the provider refuses is not saved (401 with the reason). Returns the status and the models.

### `DELETE /api/ai/key`

Forget one provider's saved key. It stays valid at the provider: the user can delete it there.

Parameters: `provider`.

### `POST /api/ai/openrouter/signin`

Start Sign in with OpenRouter. The dashboard opens the returned address in the system browser.

### `GET /auth/openrouter`

OpenRouter sends the browser back here after the user approves JobPortal. Finishing turns the one-time code into the user's key and switches to OpenRouter, so the dashboard updates by itself.

### `POST /api/ai/signin`

Start Sign in with ChatGPT. The dashboard opens the returned OpenAI address in the system browser.

### `GET /auth/callback`

OpenAI sends the browser back here after the user signs in. Finishing the sign-in publishes the new status, so the dashboard updates by itself.

### `POST /api/ai/signout`

Sign out of ChatGPT: revoke the sign-in at OpenAI when it can be reached, and forget the tokens either way.

### `GET /api/ai/models`

The models the account can use with the provider in use, best default first, for the model menus in Settings.

Parameters: `refresh`.

## Search runs and sources

From `jobportal/web/routes/search.py`.

### `POST /api/run`

Start a search run. Refused (409) while one is running or before setup is finished, and (400) for an unknown mode or overrides that aren't whole numbers.

### `POST /api/run/stop`

Stop the search in progress, if any. It saves what it has and ends as "stopped" (see pipeline.stop).

### `GET /api/runs`

The last 60 runs, newest first, for Settings, History.

### `GET /api/runs/{run_id}/log`

A run's log lines. `after` lets the dashboard fetch only lines it hasn't shown yet.

Parameters: `after`, `run_id` (path).

### `GET /api/ai_calls`

The last 200 AI requests with their purpose, model, tokens and outcome. The dashboard doesn't show this. It's for checking AI usage while developing: open http://127.0.0.1:8788/api/ai_calls in a browser.

### `POST /api/sources/detect`

Find the company job board behind a pasted careers link ({"url", "name"}) and read it once (sources.detect_board).

### `POST /api/sources/test/{key}`

Run one job source by itself and report how many of its jobs would pass the rule filters (sources.test_collector).

Parameters: `key` (path).

## Leads and the Tracker

From `jobportal/web/routes/leads.py`.

### `GET /api/leads`

One tab of the Leads page, filtered and sorted, plus the counts for every tab and industry chip.

Parameters: `tab`, `q`, `sort`, `kind`, `industry`, `dream`, `limit`.

### `GET /api/leads/{lead_id}`

Everything about one lead: the lead itself, its history, which documents are rendered, and its questions.

Parameters: `lead_id` (path).

### `PATCH /api/leads/{lead_id}`

Save edits from the lead page and the Tracker: any field in EDITABLE (status, notes, follow-up date, the resume and cover letter text, title, company, location, deadline, apply link, industry, the dream star), and "package", which is merged into the saved package. Returns the lead as the Leads list shows it. An app_status outside config.APP_STATUSES is refused with a 400.
Side effects: a status change goes into the lead's history. Moving a lead to Application sent or later (config.APPLIED_STATUSES) records the date it was applied for, and Application sent also schedules a follow-up in 7 days. Setting the dream star by hand is remembered (dream_manual), so re-checking the Dream list leaves it alone. Editing the resume recomputes its keyword coverage. Editing a document deletes its rendered files so downloads stay current, and a "lead" event tells open dashboards.

Parameters: `lead_id` (path).

### `POST /api/leads/{lead_id}/events`

Add a note (or another event) to a lead's history.

Parameters: `lead_id` (path).

### `POST /api/leads/{lead_id}/questions/generate`

Ask the user 1 to 3 questions whose answers could truthfully strengthen this lead's resume.

Parameters: `lead_id` (path).

### `POST /api/leads/{lead_id}/apply-answers`

Rework this lead's resume with the answers just given (in the background).

Parameters: `lead_id` (path).

### `POST /api/leads/{lead_id}/package`

Build (or rebuild) the full application package for one lead, in the background.

Parameters: `lead_id` (path).

### `POST /api/leads/manual`

Add a job the user found, from the Leads page or straight onto a Tracker column.
Body: url and/or text (the posting), or just title and company for a quick add, plus optional location, kind and app_status (where it goes on the Tracker; "new" leaves it on the Leads page only). With a link or posting text, the application package starts building right away. A quick add with neither has nothing to tailor a resume to, so it's only tracked until the user pastes the posting on its page. The same job added again isn't added twice: the saved lead comes back with "existing": true, and its package is left alone.

### `POST /api/leads/paste`

Find the jobs in posts the user pasted from a community ({"text": "...", "where": "Nursing jobs Discord"}) and add each new one as a lead, scored in the background (search/posts.py). Returns how many were found, added and already saved. 400 for a paste too short to hold a post.

### `DELETE /api/leads/{lead_id}`

Delete a lead for good: its row, its history and its generated files. Deleting from the Tracker or the Leads list only trashes a lead (PATCH app_status "trashed"), which also keeps later searches from adding the same job again. This is the Trash view's "Delete forever", after which a later search may find the job again.

Parameters: `lead_id` (path).

### `POST /api/leads/retriage`

Re-score waiting and filtered leads against the current profile (in the background; it toasts its own results).

### `POST /api/leads/retag-industries`

Re-tag every lead's industry with AI, in the background, then refresh the Leads page.

### `GET /api/tracker`

The Tracker board: leads in each column (config.TRACKER_STATUSES, newest change first), follow-ups due by tomorrow, the response rate and applications per week.

### `GET /api/contacts`

Every contact found for every lead that isn't trashed (recruiters, hiring managers, alumni), for the Tracker's Contacts view.

### `POST /api/leads/{lead_id}/contacts/{idx}`

Change one of a lead's contacts. idx -1 adds a contact; {"delete": true} removes one; anything else updates it.

Parameters: `lead_id` (path), `idx` (path).

## Downloads and document editing

From `jobportal/web/routes/documents.py`.

### `GET /api/leads/{lead_id}/export/{name}`

Download one document ("resume.pdf", "emails.md", "email-0.eml") or everything ("package.zip").

Parameters: `lead_id` (path), `name` (path).

### `POST /api/preview`

The editor's live preview: a resume or cover letter rendered exactly as its PDF will look, or any other Markdown.

### `POST /api/leads/{lead_id}/revise`

Ask the AI to edit a lead's document by instruction. Returns the new text for the editor to show; nothing is saved.

Parameters: `lead_id` (path).

### `POST /api/leads/{lead_id}/resume-check`

Run the resume checks again on the lead's current resume (format, length, keywords, truthful skills) and save the result.

Parameters: `lead_id` (path).

## Setup, the profile and the resume builder

From `jobportal/web/routes/candidate.py`.

### `GET /api/onboarding`

Everything setup needs (Home, and Settings, Profile): the questions, the saved answers and resume, and what's still missing.

### `PUT /api/onboarding/resume`

Import the resume file (sent as the raw request body), read its text, and pre-fill the standard questions from it.

Parameters: `filename`, `save_to_library`, `prefill`.

### `POST /api/onboarding/resume-text`

The same as a file import, for a resume pasted as text.

### `GET /api/onboarding/builder`

The resume builder, for someone without a resume: its questions and text boxes, and the answers to start from (what they wrote last time, else the standard answers saved so far).

### `POST /api/onboarding/builder`

Write a resume from the builder's answers ({"answers": {...}, "jobs": [{...}]}) and make it the main resume (one AI call). A copy goes to Settings, Resumes. When the answers complete setup, the first profile build starts. Returns the resume, the AI's notes on what to add, the saved answers and the profile status.

### `PUT /api/onboarding/answers`

Save the standard answers. With a resume imported, this also starts building the profile in the background.

### `PATCH /api/onboarding/answers`

Save one or a few standard answers ({"answers": {question id: answer}}), as the Home page asks them one at a time. Nothing is required. When this fills the last required question, the answers count as saved and, with a resume imported, the first profile build starts. Returns the answers, the required ids still missing, and the status.

### `GET /api/profile`

Every profile section, keyed by name (empty sections come back with their empty value).

### `GET /api/profile/documents`

The extra documents: other resumes, certificates, licenses, cover letters, awards and transcripts, without their text. Each has its details read from it ("parsed": kind, title, issuer, issued, expires, skills, summary), who read them ("parsed_by": "rules" or "ai") and whether an AI reading runs now ("parsing").

### `PUT /api/profile/documents`

Add one document, sent as the raw request body. Its details are read by patterns right away and, when the AI in use is connected, by AI in the background (a "documents" event says when). The profile rebuilds about a minute after the user stops adding.

Parameters: `filename`.

### `POST /api/profile/documents/{doc_id}/parse`

Read one document's details again with AI, now. Returns its listing entry with the new details.

Parameters: `doc_id` (path).

### `POST /api/profile/documents/{doc_id}/main`

Swap: this document becomes the main resume, and the old main resume becomes a document.

Parameters: `doc_id` (path).

### `POST /api/profile/documents/auto-main`

After a drop of several files on Home: when there's no main resume yet, make the best resume among the documents the main one (documents.best_resume). Returns {"resume": the main resume's details or null, "picked": the file name picked, or null when a main resume was already there or no document looks like a resume}.

### `DELETE /api/profile/documents/{doc_id}`

Forget one extra document and delete its stored copy. The profile rebuilds once the user pauses.

Parameters: `doc_id` (path).

### `PUT /api/profile/{key}`

The user corrects a profile section by hand in Settings, Profile.

Parameters: `key` (path).

### `GET /api/profile/status`

What the profile is doing now (a build, an update, the last error) and how far setup has come.

### `GET /api/profile/overview`

The overview in Settings, Profile: who the user is, what the profile knows and what it has made so far.

### `POST /api/profile/build`

Rebuild every AI-written profile section from the resume and all answers.

### `POST /api/profile/sync-answers`

Fold new answers into the profile now instead of waiting for the background watcher.

### `POST /api/profile/voice`

Learn how the user writes from the writing sample in the standard answers.

### `GET /api/profile/{key}/history`

Earlier versions of one profile section, newest first.

Parameters: `key` (path).

### `GET /api/questions`

Every question asked along the way, oldest first, with its status and answer.

### `POST /api/questions/answer`

Save the user's answer to a question ({"question", "answer"}; a new question is added as answered). Returns the updated list and the profile status. The answer joins the profile on the next update.

### `POST /api/questions/dismiss`

Mark a question as not relevant ({"question"}). Returns the updated list.

## Saved resumes

From `jobportal/web/routes/library.py`.

### `GET /api/library`

Every saved resume, most recently changed first, each with a short preview instead of its full text.

### `POST /api/library`

Save a resume: pass md (and optionally a style), or just lead_id to save that lead's current resume.

### `PUT /api/library/import`

Add a resume file (sent as the raw request body) to the collection, wording kept exactly.

Parameters: `filename`, `name`.

### `GET /api/library/{item_id}`

One saved resume with its full Markdown, style, tags and notes.

Parameters: `item_id` (path).

### `PUT /api/library/{item_id}`

Change a saved resume's name, Markdown, style, tags or notes (other keys are ignored). Returns the item.

Parameters: `item_id` (path).

### `DELETE /api/library/{item_id}`

Delete a saved resume and its rendered downloads.

Parameters: `item_id` (path).

### `GET /api/library/{item_id}/html`

The saved resume rendered exactly as its PDF will look.

Parameters: `item_id` (path).

### `POST /api/library/{item_id}/revise`

Ask the AI to edit a saved resume by instruction. Returns the new text; nothing is saved.

Parameters: `item_id` (path).

### `GET /api/library/{item_id}/export/{fmt}`

Download a saved resume as PDF, DOCX or Markdown.

Parameters: `item_id` (path), `fmt` (path).

### `POST /api/library/{item_id}/apply/{lead_id}`

Use a saved resume for a lead, as it is or tailored to that job by the AI. {"backup": true} first saves the lead's current resume to the collection.

Parameters: `item_id` (path), `lead_id` (path).

## Analysis, Next moves and the Dream list

From `jobportal/web/routes/insights.py`.

### `GET /api/analysis`

The Analysis page: the radar's roles with their numbers and scores, the market numbers, the latest AI assessment and its history (see insights/analysis.get).

### `GET /api/moves`

Home's Next moves: a few things worth doing next, found by plain rules (see insights/moves.py).

### `POST /api/moves/hide`

Keep one move off the card for 30 days, {"key": "..."}.

### `POST /api/analysis/run`

Ask the AI for a fresh fit-and-demand assessment, in the background (it toasts its own result or error).

### `POST /api/analysis/roles/add`

Add a job title of the user's own to the radar, {"title": "..."}. It stays until they remove it. A 400 explains a title that can't be added (empty, too long, only a level, or too many added already).

### `POST /api/analysis/roles/remove`

Take a role off the radar for good, {"id": "<role id>"}.

### `POST /api/analysis/roles/restore`

Bring back a role the user removed, {"id": "<role id>"}.

### `GET /api/dreams`

The Dream list (in Settings, Search). Companies come from two places: the ones the user added, and the ones the profile's search plan suggested (minus any the user removed).

### `PUT /api/dreams`

Save the Dream list: companies, job titles, removed suggestions, and whether dream jobs may skip the location filter.

### `POST /api/dreams/recheck`

Re-flag every lead against the current Dream list. Leads the user starred or unstarred by hand are left alone.

## Settings, the schedule and alerts

From `jobportal/web/routes/settings.py`.

### `GET /api/settings`

Every setting: what the user saved, merged over the defaults (core/settings.get).

### `PUT /api/settings`

Store the whole settings document the dashboard sends, replacing what was saved, and return the result. The schedule and the desktop alerts follow the new settings at once (search/schedule.settings_saved).

### `GET /api/schedule`

The schedule as Settings and Home show it: on or off, the next scheduled search, the last one, and whether JobPortal starts in the background at login.

### `POST /api/alerts/test`

Send a desktop alert right away, the same way JobPortal sends one when its window is closed, so the user can check that alerts show on this computer. ok is False when the system has no way to show one.

### `POST /api/settings/reset`

Put one section back to its default, for example {"path": "sources.ats_boards"}. Returns the settings.

### `GET /api/resume-playbook`

The playbook in use, the built-in one, whether the user customized it, and the resume layouts to choose from.

### `GET /api/prompts/defaults`

The built-in system prompts by name, which Settings, AI shows as placeholders until the user overrides one.
