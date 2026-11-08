from django.contrib import admin

from planner.models import FuelStation, Town


@admin.register(Town)
class TownAdmin(admin.ModelAdmin):
    list_display = ["name", "state", "lat", "lng"]
    list_filter = ["state"]
    search_fields = ["name"]


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "state", "price_per_gallon"]
    list_filter = ["state"]
    search_fields = ["name", "city"]
    ordering = ["price_per_gallon"]
