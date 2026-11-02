# JobPortal - AI Integration Design

**Course:** CMSC 495 - Computer Science Capstone 
**Project:** JobPortal  
**Contribution:** AI Integration Design  
**Status:** Proposed design for team review

## 1. AI Integration Overview

JobPortal is an AI-powered desktop application designed to help users find relevant employment opportunities and prepare personalized application materials.

The application uses a Python/FastAPI backend, a JavaScript-based dashboard, SQLite for local data storage, and OpenAI's Responses API for AI-assisted tasks.

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

## References

OpenAI. (n.d.). API documentation. https://platform.openai.com/docs/

OWASP Foundation. (2025). OWASP Top 10 for LLM applications. https://genai.owasp.org/

FastAPI. (n.d.). FastAPI documentation. https://fastapi.tiangolo.com/

## Contribution Summary

This document proposes the AI integration workflow, job-matching responsibilities, application-material generation safeguards, privacy controls, failure handling, feedback process, and acceptance testing approach for JobPortal.

It is intended for team review and incorporation into the Unit 3 System Design Specification.
