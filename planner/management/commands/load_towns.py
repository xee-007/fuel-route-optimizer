import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import Town
from planner.services.place_names import normalize_place_name

DEFAULT_PATH = settings.BASE_DIR / "data" / "us_towns.csv"


class Command(BaseCommand):
    help = "Load US town coordinates into the database, replacing any existing towns."

    def add_arguments(self, parser):
        parser.add_argument("--path", type=Path, default=DEFAULT_PATH)

    def handle(self, *args, path: Path, **options):
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        towns: dict[tuple[str, str], Town] = {}
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                normalized_name = normalize_place_name(row["name"])
                towns.setdefault(
                    (normalized_name, row["state"]),
                    Town(
                        name=row["name"],
                        normalized_name=normalized_name,
                        state=row["state"],
                        lat=float(row["lat"]),
                        lng=float(row["lng"]),
                    ),
                )

        with transaction.atomic():
            Town.objects.all().delete()
            Town.objects.bulk_create(towns.values(), batch_size=2000)

        self.stdout.write(self.style.SUCCESS(f"Loaded {len(towns)} towns."))
