"""The HTTP API, one module per area. Each module's name matches the package it mostly talks to, so the routes for the
profile live in candidate.py next to jobportal/candidate/, and so on. web/server.py includes every router listed here.

Adding an endpoint: put it in the module for its area, or add a module and list its router in ROUTERS."""
from jobportal.web.routes import candidate, chatgpt, documents, insights, leads, library, search, settings, system

ROUTERS = [system.router, chatgpt.router, search.router, leads.router, documents.router, candidate.router, library.router,
           insights.router, settings.router]
