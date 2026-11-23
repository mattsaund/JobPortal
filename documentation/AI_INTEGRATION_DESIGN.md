# JobPortal - AI Integration Design

**Course:** CMSC 495 - Computer Science Capstone 
**Project:** JobPortal  
**Contribution:** AI Integration Design  
**Status:** Proposed design for team review

## 1. AI Integration Overview

JobPortal is an AI-powered desktop application designed to help users find relevant employment opportunities and prepare personalized application materials.

The application uses a Python/FastAPI backend, a JavaScript-based dashboard, SQLite for local data storage, and whichever AI provider the user connects for AI-assisted tasks (Section 11).

The proposed AI integration will support job matching, resume tailoring, cover letter generation, and interview preparation while keeping final application decisions under user control.

## 2. AI Integration Architecture

The proposed integration follows this workflow:

1. The user uploads a resume and provides job preferences.
2. FastAPI processes and validates the submitted information.
3. Relevant profile information and job requirements are prepared for AI processing.
4. The AI service analyzes the information and generates recommendations or application materials.
5. FastAPI validates and organizes the generated results.
6. The dashboard displays results for user review.
7. The user decides whether to save, download, or use the generated materials.

The AI service should remain separated from the application interface and database operations to support modularity, maintainability, and future changes to AI providers.

## 3. AI-Powered Job Matching

JobPortal will compare candidate qualifications with job requirements to identify suitable opportunities.

Matching factors may include:

- Technical and professional skills
- Education and certifications
- Relevant work experience
- Preferred job titles and locations
- Required qualifications and employment eligibility

The system should provide an explanation of why a position matches the user's profile.

AI recommendations will assist the job search rather than automatically determine which jobs the user must pursue.

## 4. AI-Generated Application Materials

The AI integration will support the creation of:

- Job-specific resumes
- Personalized cover letters
- Professional outreach messages
- Interview preparation materials
- Company and position summaries

Generated materials must remain consistent with the user's verified information.

The system must not invent qualifications, certifications, employment history, or professional accomplishments.

Users will review generated materials before using them.

## 5. AI Security and Privacy

The proposed integration will apply the following safeguards:

- Limit AI requests to information necessary for the requested task.
- Avoid sending unnecessary sensitive personal information.
- Keep local user records protected from unauthorized access.
- Validate external job descriptions before using them as AI context.
- Treat job postings and other external content as untrusted data.
- Prevent external content from overriding application instructions.
- Avoid logging sensitive resume content or authentication credentials.
- Require user confirmation before submitting applications or sending messages.

These controls will reduce privacy risks and help protect users from misleading or malicious AI-generated content.

## 6. Error Handling and Reliability

The integration should account for possible failures, including:

- AI service unavailability
- Network connection interruptions
- Invalid or incomplete resume data
- Unsuccessful AI responses
- Unexpected response formats
- API request limits

When an AI request fails, JobPortal should display a clear error message without losing the user's saved profile or application progress.

Retry mechanisms should be limited to avoid unnecessary repeated requests.

The application should never represent incomplete AI output as a verified recommendation.

## 7. User Feedback and Continuous Improvement

Users should be able to review and correct information used to generate recommendations.

Feedback may help identify inaccurate job matches, missing qualifications, or poor-quality application materials.

Proposed improvements include:

- Allowing users to update their professional profiles
- Recording user corrections locally
- Recalculating recommendations after profile changes
- Identifying recurring AI response problems
- Testing updated prompts before deployment

Feedback should not automatically modify verified qualifications without user approval.

## 8. Proposed AI Acceptance Tests

The following tests are proposed for future implementation and verification.

| Test Area | Expected Result |
|---|---|
| Resume processing | Extracted qualifications match the supplied documents |
| Job matching | Recommendations are based on relevant user qualifications |
| Resume generation | No fabricated employment history or certifications |
| Privacy | Unnecessary sensitive information is excluded from AI requests |
| Error handling | Failed AI requests return understandable error messages |
| User control | No application or message is sent without user authorization |
| Prompt injection | Instructions embedded in job postings cannot override application rules |
| Profile updates | Corrected information is reflected in subsequent recommendations |

Test outcomes should be recorded during implementation. These are proposed acceptance criteria, not completed test results.

## 9. Integration Responsibilities and Team Coordination

The AI integration design must remain consistent with the team's architecture diagram and FastAPI interface specifications.

Coordination with the Lead Architect and Interface Designers should confirm:

1. How the dashboard requests AI operations through FastAPI.
2. Which backend components prepare and validate AI requests.
3. How AI results are returned to the dashboard.
4. How errors and service interruptions are handled.
5. Which information is stored locally.
6. How user authorization is enforced before external actions.

## 10. Design Rationale

Separating AI processing from the dashboard and database logic supports modularity and separation of concerns. The interface remains responsible for user interaction, FastAPI coordinates application operations, and the AI integration handles requests to the external model provider.

This design reduces coupling between components and allows individual services to be tested or modified without redesigning the entire application.

A key tradeoff is reliance on an external AI service. Although this approach reduces the complexity of maintaining a local language model, it introduces network, availability, privacy, and request-limit considerations.

Input validation, restricted data sharing, clear error handling, and human review help address these limitations.

## 11. AI Providers (updated in v0.5.0)

JobPortal does not depend on a single AI service, and it has no default one. The user connects one in the Connect AI popup,
from 122 providers listed as data in `jobportal/ai/provider_list.py`.

| How the user connects | Providers | Hosted web search |
|---|---|---|
| Browser sign-in (3) | ChatGPT on a Go, Plus or Pro plan, and OpenRouter and Pollinations (OAuth PKCE, no app registration). OpenRouter and Pollinations also take a pasted key | ChatGPT |
| API key (104) | Model makers (Claude, Gemini, OpenAI, Grok, Mistral, DeepSeek and others), clouds (Azure, Bedrock, Cloudflare and others), model hosts and gateways | OpenAI API, Claude and Perplexity |
| A server on the user's computer (14) | Ollama, LM Studio, llama.cpp, vLLM, LocalAI, Jan, KoboldCpp, text-generation-webui, GPT4All, MLX, Docker Model Runner, Lemonade, SGLang and the LiteLLM proxy | No |
| Any address (1) | The Custom entry, for anything with an OpenAI-compatible API | No |

Providers without hosted web search read pages with `fetch_url`, which only opens public internet addresses and checks every
redirect.

- One request loop serves every provider. Three adapters ("wires") turn the conversation into OpenAI's Responses API (3
  providers), the chat completions API most services share (118), or Anthropic's Messages API (1). A provider that speaks
  one of them needs only a data entry.
- Each provider's own output (encrypted reasoning, thinking blocks, search results, thought signatures) goes back
  unchanged in the next request, as the providers require.
- The result comes back through the `submit_result` function. The call is never forced, because several providers reject
  forced tool calls, so a turn that ends without it gets a short reminder.
- Every result is checked against its task's full JSON Schema (with the `jsonschema` library), whichever provider sent it.
  A result with a missing field, a wrong type or a value out of range is not used. The model gets a short correction that
  names the field and tries again.
- API keys are stored owner-only in the data folder and never reach the dashboard, which only sees their last four
  characters.
- A new connection is checked against the provider's model list and kept only if it works. A provider with no model list
  asks for a model name, and is then checked with one small real request.
- Errors are handled per provider. A refused key asks the user for a new one. No credit, a spending limit or a rate limit
  pauses searching for a while, and a short Retry-After wait is honored first.
- Anthropic and Google do not let other apps sign people in with their Claude or Gemini subscriptions, so those come by
  API key.

### Models without tool calling

Many local models and some hosted ones can't call functions. The chat wire handles that without any setting:

1. If a service refuses the `tool_choice` field, the request is sent again without it.
2. If a service says the model has no tool support, the wire stops offering tools for that task. The system prompt then
   holds the task's JSON Schema and asks for one JSON object with no other text.
3. The JSON is read from the model's plain-text answer and checked against the same schema as any other result. An answer
   that doesn't fit gets a short correction, up to two times, and then the task fails with a clear error.

A model without tools can't call `fetch_url` either, so web tasks on it work only from what's in the prompt. Automated tests
cover this path against a mock service.

Design rationale: many providers remove the single-vendor dependency named in Section 10, let people use the app without a
paid plan (free tiers, or a server on their own computer), and keep the user in control of what they pay and where their data
goes.

## References

OpenAI. (n.d.). API documentation. https://platform.openai.com/docs/

OWASP Foundation. (2025). OWASP Top 10 for LLM applications. https://genai.owasp.org/

FastAPI. (n.d.). FastAPI documentation. https://fastapi.tiangolo.com/

## Contribution Summary

This document proposes the AI integration workflow, job-matching responsibilities, application-material generation safeguards, privacy controls, failure handling, feedback process, and acceptance testing approach for JobPortal.

It is intended for team review and incorporation into the Unit 3 System Design Specification.
