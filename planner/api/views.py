"""
Thin HTTP layer: validate the query, plan the trip, return JSON or a map page.
All the logic lives in planner/services.
"""

from django.shortcuts import render
from django.views import View
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from planner.api.exceptions import USER_FACING_ERRORS, describe_error
from planner.api.serializers import RoutePlanQuerySerializer, TripPlanSerializer
from planner.services.trip_planner import plan_trip


def build_plan(request, params) -> dict:
    """Validate the query, plan the trip and return the response data."""
    query = RoutePlanQuerySerializer(data=params)
    query.is_valid(raise_exception=True)
    plan = plan_trip(query.validated_data["start"], query.validated_data["finish"])
    context = {"request": request, "query": query.validated_data}
    return TripPlanSerializer(plan, context=context).data


class RoutePlanView(APIView):
    """GET /api/v1/route-plan/?start=Chicago, IL&finish=Denver, CO"""

    def get(self, request: Request) -> Response:
        return Response(build_plan(request, request.query_params))


class RoutePlanMapView(View):
    """GET /api/v1/route-plan/map/?start=...&finish=... : the same plan, drawn on a map.

    The route comes from the cache filled by the API call, so this page
    doesn't call the routing API again.
    """

    def get(self, request):
        try:
            plan = build_plan(request, request.GET)
        except USER_FACING_ERRORS as exc:
            status, _, message = describe_error(exc)
            return render(request, "planner/map.html", {"error": message}, status=status)

        response = render(request, "planner/map.html", {"plan": plan})
        # OpenStreetMap refuses map tiles requested without a Referer. Let the
        # browser send our origin (never the full URL, which contains the trip).
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
