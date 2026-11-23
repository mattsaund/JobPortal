# Interface contracts

What each part of JobPortal promises the others: the HTTP API, the live events, the main internal functions, the shared data
shapes, and how errors work. [API.md](API.md) lists every endpoint. FastAPI also serves them at http://127.0.0.1:8788/docs
while the app runs.

## 1. HTTP conventions

| Rule | Contract |
|---|---|
| Address | `http://127.0.0.1:8788` by default (`--port` or `JOBPORTAL_PORT` changes it) |
| Host check | A request not addressed to `127.0.0.1` or `localhost` gets 403 |
| Origin check | A change (anything but GET) from another site's page gets 403 |
| Bodies | JSON, except file uploads, which send the raw file as the body |
| Upload limit | 25 MB, else 413 |
| Errors | JSON with a `detail` message written for the user. The host and origin checks answer in plain text |

| Status | Meaning |
|---|---|
| 200 | It worked |
| 400 | The request is invalid: `detail` says why |
| 401 | The AI needs connecting: no sign-in, no key, or a key the provider refused |
| 403 | Failed the host or origin check |
| 404 | No such lead, document or file |
| 409 | Not possible right now: a search is running or setup isn't finished, this server can't be stopped from the dashboard, or a provider with no model list needs a model name |
| 413 | The upload is too large |
| 429 | The AI account hit a cap, ran out of credit, or is rate limited |
| 502 | Anything else that went wrong talking to the AI |
| 503 | PDF export has no browser engine, or it timed out |

## 2. Main endpoints

### Connect an AI

`GET /api/ai/providers` returns every provider and the current status.

```json
{
  "providers": [
    {"id": "gemini", "name": "Gemini", "group": "key", "connect": "key", "fields": [], "needs_key": true,
     "key_url": "https://aistudio.google.com/apikey", "key_prefix": "AIza", "free": true, "search": false,
     "note": "Free tier: Google may review what you send."},
    {"id": "ollama", "name": "Ollama", "group": "local", "connect": "key", "needs_key": false,
     "fields": [{"id": "url", "label": "Address", "default": "http://localhost:11434/v1"}]}
  ],
  "status": {"provider": "gemini", "provider_name": "Gemini", "auth": "key", "ready": true, "keys": {"gemini": "ending in 1234"}}
}
```

`group` is `signin`, `key`, `local` or `custom`. A key is never returned, only its last four characters.

`PUT /api/ai/key` connects a provider by key or address.

```json
{"provider": "azure", "key": "example-key", "endpoint": {"resource": "my-resource"}, "model": "my-deployment"}
```

The connection is checked against the provider's model list and kept only if it works. Returns the status plus `models`.
Errors: 400 (invalid field), 401 (refused key), 409 (no model list and no `model` sent), 429, 502.

`POST /api/ai/signin` with `{"provider": "chatgpt"}`, `"openrouter"` or `"pollinations"` returns `{"url": "..."}` for the
browser. The provider sends the browser back to `/auth/...`, and an `ai` event reports the result.

`DELETE /api/ai/connection?provider=<id>` signs out or forgets the key.

### Resume and answers

| Endpoint | Request | Response |
|---|---|---|
| `GET /api/onboarding` | | `questions`, `answers`, `required`, `missing`, `from_resume`, `resume`, `documents`, `status`, `accept` |
| `PUT /api/profile/documents?filename=x.pdf` | the file | the document's listing entry, with `duplicate: true` when it's already there |
| `PATCH /api/onboarding/answers` | `{"answers": {"city": "Columbus"}}` | `answers`, `missing`, `complete`, `status`, `building` |
| `POST /api/onboarding/builder` | `{"answers": {...}, "jobs": [{"role": "...", "organization": "..."}]}` | `markdown`, `notes`, `resume`, `answers` |
| `POST /api/profile/build` | | starts a build; `profile_status` events report it |

### Search and leads

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/run` | `{"mode": "full"}` (`full`, `boards`, `hunt` or `backlog`) | the run starts; `state`, `log` and `lead` events follow |
| `POST /api/run/stop` | | stops the run |
| `GET /api/leads` | `tab`, `q`, `sort`, `kind`, `industry`, `dream`, `limit` | `leads`, `counts`, `industries`, `dream_count` |
| `GET /api/leads/{id}` | | the full lead (section 5), with `events`, `files` and `questions` |
| `PATCH /api/leads/{id}` | editable fields, such as `{"app_status": "applied"}` | the updated lead; 400 for a bad status |
| `POST /api/leads/paste` | `{"text": "...", "where": "Discord"}` | `found`, `added`, `existing`, `lead_ids` |
| `GET /api/leads/{id}/export/{name}` | `resume.pdf`, `cover_letter.docx`, `email-0.eml`, `package.zip` and so on | the file |
| `GET /api/export/leads.zip` | the same filters as `GET /api/leads` | a spreadsheet of the leads and a folder of documents for each |

### Settings

`GET /api/settings` returns the whole settings document, and `PUT /api/settings` replaces it. `POST /api/settings/reset`
puts one section back to its default.

## 3. Live events

`GET /api/events` is a stream of Server-Sent Events. Each message is JSON: `{"kind": "...", "data": ...}`.

| Kind | Data |
|---|---|
| `state` | the run state: `running`, `phase`, `counts`, `run_id` |
| `log` | one log line: `source`, `level`, `msg`, and usually `run_id` and `ts` |
| `lead` | a lead's summary, or null when many changed |
| `run_done` | `run_id`, `status`, `stats` |
| `ai` | the AI's status (`providers.status()`) |
| `usage` | the model, tasks running, session tokens and requests |
| `agents` | the AI tasks running now |
| `tokens` | tokens used since startup |
| `profile`, `profile_status` | the profile changed, or a build moved on |
| `questions`, `documents` | the new list |
| `schedule` | the schedule's status |
| `analysis` | an analysis started, finished or failed |
| `toast` | `title`, `body`, `level`, `lead_id` |

## 4. Internal interfaces

```python
# ai/client.py: the only way any package talks to an AI
async def run(prompt: str, *, system: str, schema: dict, stage: str, purpose: str, web: bool = False,
              max_steps: int = 12, run_id: int | None = None, lead_id: int | None = None,
              timeout: int = 1200, label: str | None = None) -> dict
# Returns the fields of `schema` plus "_tokens" and "_tools".
# Raises NotSignedIn, UsageLimitError or AIError. The result always passes `schema`.

async def models(force: bool = False) -> list[str]   # the account's models, best default first
def setup_problem() -> str                           # why the AI can't run, or ""

# ai/providers.py
def current(cfg: dict | None = None) -> str          # the provider in use, or ""
def info(provider: str | None = None, cfg: dict | None = None) -> dict
def status(cfg: dict | None = None) -> dict          # safe for the dashboard: never holds a key
async def credential(provider: str | None = None) -> str

# search/collectors: every source
async def collect(ctx: Ctx) -> list[RawJob]          # one failing source never stops the others

# search/pipeline.py
class RuleFilters:
    def check(self, j: RawJob) -> tuple[bool, str, float]     # passed, why it was dropped, pre-score

# documents/exports.py
async def lead_file(lead: dict, name: str) -> tuple[Path, str]
async def package_zip(lead: dict) -> tuple[Path, str]
async def leads_zip(leads: list[dict]) -> tuple[Path, str]
```

## 5. Data contracts

**RawJob** (`search/collectors/base.py`): one job as a source found it.

| Field | Type | Notes |
|---|---|---|
| `source` | str | the collector's id |
| `title`, `url` | str | required for a job to go on |
| `company` | str | can be empty |
| `location`, `locations` | str, list | a display string, and each place on its own |
| `description` | str | |
| `posted_at`, `deadline` | str or None | ISO dates |
| `apply_url` | str or None | |
| `kind` | str | `posting`, `program`, `event` or `intel` |
| `strict_titles` | bool | the title must name the user's level |
| `found_url`, `source_detail` | str | where it was found |

**Lead** (the `leads` table): a RawJob after filtering and scoring.

| Field | Values |
|---|---|
| `stage` | `filtered`, `qualified`, `packaging`, `ready`, `closed`, `error` |
| `app_status` | `new`, `ready`, `applied`, `interviewing`, `accepted`, `rejected`, `trashed` |
| `score`, `verdict` | 0 to 100, and `strong`, `possible`, `stretch` or `no` |
| `triage` | `summary`, `reasons`, `red_flags`, `genres`, `industry`, `eligibility` |
| `package` | `fit`, `keywords`, `emails`, `contacts`, `application_answers`, `interview_prep_md`, `company_brief_md`, `action_plan` |
| `resume_md`, `cover_md` | the tailored resume and cover letter, as Markdown |

## 6. Validation

- **AI results** are checked against the task's JSON Schema. A failing result goes back to the model with a correction.
- **API keys** have no spaces and are at most 500 characters. They're stored in an owner-only file and never returned.
- **Provider addresses:** a URL must be http or https. Other address parts may only hold letters, digits, dots, dashes and
  underscores, so they can't change which host a key is sent to.
- **Fetched pages:** the AI's page reader only opens public internet addresses, and each redirect is checked again.
- **Spreadsheets:** exported cells that start like a formula are escaped.
- **Dashboard:** every value from the server is escaped before it reaches the page, and only web and mail links are linked.
