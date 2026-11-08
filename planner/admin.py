from django.contrib import admin

from planner.models import Town


@admin.register(Town)
class TownAdmin(admin.ModelAdmin):
    list_display = ["name", "state", "lat", "lng"]
    list_filter = ["state"]
    search_fields = ["name"]
