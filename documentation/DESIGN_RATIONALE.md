# Design rationale

JobPortal helps one person find work and apply for it. They add a resume and any other documents, connect an AI, and the
app searches for openings, scores them, and writes a tailored application for the best ones. This page explains the main
design choices behind it.

## Separation of concerns

The code is split into packages that stack in layers: `core`, then `ai`, then `candidate` and `documents`, then `search`
and `insights`, then `web`, then `app`. Each one owns a single kind of work. `core` holds storage, settings and everything
that differs between operating systems. `ai` is the only code that talks to an AI service. `search` finds and ranks jobs.
`web` turns all of that into an HTTP API, and the dashboard only ever talks to that API. A lower layer never imports a
higher one at the top of a file. This follows Parnas (1972), who argued that modules should be divided around the decisions
most likely to change, so that each decision stays hidden in one place.

## Cohesion and coupling

The decisions most likely to change in this project are which AI to use and where jobs come from, so both sit behind narrow
interfaces. Every AI feature calls one function, `ai.client.run()`, with a prompt and the JSON Schema of the answer it
expects. Adding one of the 122 providers takes a data entry in `ai/provider_list.py`, because the request formats are three
small "wire" classes. Job sources work the same way. Each collector turns what it reads into the same `RawJob` shape, so
the filters, scoring and packaging never need to know where a job came from. The dashboard is loosely coupled too: it calls
JSON routes and listens to one stream of live events, so a page can be redesigned without touching the server.

## The major tradeoff: a local app instead of a hosted service

We chose to run JobPortal on each user's own computer, with a local server and a SQLite database, rather than host one
shared service. A resume holds a person's work history and contact details, and keeping it on their machine removes the
biggest privacy risk. It also means no server bill, and each user pays only for their own AI account. The cost is real. We
can't share data between users, we can't scale one service to many people, and we have to build, test and ship the app for
Windows, macOS and Linux. Bass, Clements and Kazman (2021) describe architecture as a series of tradeoffs between quality
attributes. Here we traded scalability for privacy and low operating cost, because a job search is personal and only ever
has one user at a time.

## AI integration

The AI is treated as a capable but untrusted component. Its output is checked against a JSON Schema before anything uses
it, and a result that doesn't fit is sent back with a correction. Prompts forbid inventing experience, dates, numbers or
credentials, because a false claim on a resume can cost someone a job. Text from job postings and web pages is handled as
data, never as instructions, and the AI's only tools are searching and reading public pages and returning its result. The most important
safeguard is that a person stays in control: JobPortal prepares every application, but it never sends or submits anything.

## References

Bass, L., Clements, P., & Kazman, R. (2021). *Software architecture in practice* (4th ed.). Addison-Wesley.

International Organization for Standardization. (2022). *ISO/IEC/IEEE 42010:2022, Software, systems and enterprise:
Architecture description*.

Parnas, D. L. (1972). On the criteria to be used in decomposing systems into modules. *Communications of the ACM, 15*(12),
1053-1058. https://doi.org/10.1145/361598.361623
