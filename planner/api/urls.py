from django.urls import path

from planner.api.views import RoutePlanMapView, RoutePlanView

urlpatterns = [
    path("route-plan/", RoutePlanView.as_view(), name="route-plan"),
    path("route-plan/map/", RoutePlanMapView.as_view(), name="route-plan-map"),
]
