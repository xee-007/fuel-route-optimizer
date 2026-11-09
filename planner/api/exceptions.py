"""
Turn every known error into one consistent shape:

    {"error": {"code": "invalid_location", "message": "Could not find ..."}}
"""

from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from planner.services.fuel_planner import FuelPlanError
from planner.services.locations import LocationError
from planner.services.routing import RoutingError

# Errors caused by the request or the trip itself, with messages safe to show users.
USER_FACING_ERRORS = (ValidationError, LocationError, RoutingError, FuelPlanError)


def describe_error(exc: Exception) -> tuple[int, str, str] | None:
    """(HTTP status, error code, message) for errors we can explain; None otherwise."""
    if isinstance(exc, ValidationError):
        return 400, "invalid_request", _validation_message(exc.detail)
    if isinstance(exc, LocationError):
        return 400, "invalid_location", str(exc)
    if isinstance(exc, RoutingError):
        return exc.status_code, exc.code, str(exc)
    if isinstance(exc, FuelPlanError):
        return 422, "no_fuel_plan", str(exc)
    if isinstance(exc, APIException):  # e.g. 405 Method Not Allowed
        return exc.status_code, exc.default_code, str(exc.detail)
    return None


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF exception handler (see REST_FRAMEWORK in settings)."""
    described = describe_error(exc)
    if described is None:
        # A bug, not a bad request: let Django log it and return a 500.
        return drf_exception_handler(exc, context)

    status, code, message = described
    # Start from DRF's response when there is one, to keep headers such as "Allow".
    response = drf_exception_handler(exc, context) or Response()
    response.status_code = status
    response.data = {"error": {"code": code, "message": message}}
    return response


def _validation_message(detail) -> str:
    """{"finish": ["This field is required."]} -> "finish: This field is required." """
    if isinstance(detail, dict):
        return " ".join(
            f"{field}: {_validation_message(errors)}" for field, errors in detail.items()
        )
    if isinstance(detail, list):
        return " ".join(str(error) for error in detail)
    return str(detail)
