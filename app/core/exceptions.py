"""Domain-level exceptions raised by the services layer.

Routers translate these into explicit HTTP responses via the exception
handlers registered in app/main.py, keeping HTTP-status decisions out of the
services layer while still producing precise, explanatory error messages.
"""


class AppError(Exception):
    """Base class for all explicit domain errors."""

    status_code: int = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404


class ForbiddenError(AppError):
    status_code = 403


class ValidationAppError(AppError):
    status_code = 422
