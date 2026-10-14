from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from break_instantiation_backend.questionnaires import services
from break_instantiation_backend.questionnaires.models import ConsentTemplate


class Command(BaseCommand):
    help = (
        "Idempotently create a ConsentTemplate version from a plain-text "
        "file. ConsentTemplate is immutable once created -- re-running "
        "under the same version with different file content is an error, "
        "not an update; publish a new version instead."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("version")
        parser.add_argument("text_file", type=Path)
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Deactivate any other active version and activate this one.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        text_file: Path = options["text_file"]
        if not text_file.exists():
            msg = f"No such file: {text_file}"
            raise CommandError(msg)
        text = text_file.read_text(encoding="utf-8").strip()
        version = options["version"]

        template, created = ConsentTemplate.objects.get_or_create(
            version=version,
            defaults={"text": text},
        )
        if not created and template.text != text:
            msg = (
                f"ConsentTemplate {version!r} already exists with different "
                "text -- ConsentTemplate is immutable, use a new version "
                "string for changed wording."
            )
            raise CommandError(msg)

        if options["activate"]:
            services.activate_consent_template(template)

        self.stdout.write(
            self.style.SUCCESS(
                f"ConsentTemplate '{version}' "
                f"{'created' if created else 'already exists (unchanged)'}"
                f"{' (active)' if options['activate'] else ''}.",
            ),
        )
