from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gamelink.models import GameLink


class Command(BaseCommand):
    help = (
        "Reset non-completed GameLink rows after split tournament rooms have been cancelled on "
        "the game server"
    )

    def add_arguments(self, parser):
        parser.add_argument("--tournament-id", type=int, required=True)
        parser.add_argument(
            "--fixture-id",
            type=int,
            action="append",
            dest="fixture_ids",
            help="Limit reset to this fixture id; repeat for multiple erroneous fixtures",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the reset. Without this flag the command is a dry run.",
        )

    def handle(self, *args, **options):
        links = GameLink.objects.select_related("fixture").filter(
            fixture__mode__tournament_id=options["tournament_id"],
        ).exclude(status="completed").order_by("fixture_id")
        fixture_ids = options.get("fixture_ids") or []
        if fixture_ids:
            links = links.filter(fixture_id__in=fixture_ids)
        links = list(links)
        if not links:
            raise CommandError("No non-completed game links matched the requested scope.")

        for link in links:
            self.stdout.write(
                f"fixture={link.fixture_id} status={link.status} "
                f"room={link.external_room_id or '-'}"
            )

        if not options["execute"]:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {len(links)} game link(s) would be reset. "
                "Re-run with --execute after cancelling the corresponding game-server rooms."
            ))
            return

        with transaction.atomic():
            ids = [link.pk for link in links]
            reset = GameLink.objects.select_for_update().filter(pk__in=ids).exclude(
                status="completed").update(
                    status="pending",
                    external_room_id="",
                    completed_at=None,
                    raw_result=None,
                    live_snapshot=None,
                    live_updated_at=None,
                )

        self.stdout.write(self.style.SUCCESS(f"Reset {reset} game link(s)."))
