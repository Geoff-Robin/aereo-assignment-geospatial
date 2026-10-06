import logging
import time

from django.core.management.base import BaseCommand

from geofiles.services.processor import mark_file_failed, process_geospatial_file
from geofiles.services.queue import claim_next_file


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Continuously claim and process queued geospatial files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one file and exit.",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=2.0,
            help="Seconds to wait when no queued file is available.",
        )

    def handle(self, *args, **options):
        run_once = options["once"]
        poll_interval = max(options["poll_interval"], 0.1)

        while True:
            geospatial_file = claim_next_file()
            if geospatial_file is None:
                if run_once:
                    return
                time.sleep(poll_interval)
                continue

            self.stdout.write(f"Processing {geospatial_file.id}")
            try:
                process_geospatial_file(geospatial_file)
            except Exception as error:
                logger.exception(
                    "Failed to process geospatial file %s", geospatial_file.id
                )
                mark_file_failed(geospatial_file, error)
                self.stderr.write(
                    self.style.ERROR(f"Failed {geospatial_file.id}: {error}")
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"Completed {geospatial_file.id}"))

            if run_once:
                return
