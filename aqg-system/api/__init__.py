"""HTTP API layer for the AQG educational assessment platform.

Routes are grouped by domain and only handle transport concerns: parsing and
validating request data, delegating to a service, and translating typed domain
errors into safe JSON responses. All business logic lives under ``services/``.
"""
