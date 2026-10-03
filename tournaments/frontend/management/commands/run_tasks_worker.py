import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from frontend.task_runner import runnable
from frontend.tasks import schedule_tasks


class Command(BaseCommand):
    help = "Continuously run tournament background tasks for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=5.0,
            help="Seconds between checks (default: 5).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum tasks per batch (default: 50).",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        limit = options["limit"]

        if interval <= 0:
            raise CommandError("--interval must be positive.")

        if limit < 1:
            raise CommandError("--limit must be positive.")

        created = schedule_tasks()

        self.stdout.write(
            self.style.SUCCESS(
                f"Tournament task worker started: "
                f"interval={interval}s limit={limit} "
                f"created_tasks={created}"
            )
        )

        try:
            while True:
                close_old_connections()

                if runnable().exists():
                    try:
                        call_command(
                            "run_tasks",
                            limit=limit,
                        )
                    except Exception as error:
                        self.stderr.write(
                            self.style.ERROR(
                                f"Tournament task batch failed: {error}"
                            )
                        )

                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING(
                    "Tournament task worker stopped."
                )
            )