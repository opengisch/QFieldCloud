from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Upper

PROJECT_NAME_MAX_LENGTH = 255


def get_next_available_name(name: str, taken_names: set[str]) -> str:
    """Returns `<name>_<N>` with the lowest `N >= 2` not in `taken_names` (compared uppercase)."""
    suffix_number = 2

    while True:
        suffix = f"_{suffix_number}"
        candidate = name[: PROJECT_NAME_MAX_LENGTH - len(suffix)] + suffix

        if candidate.upper() not in taken_names:
            return candidate

        suffix_number += 1


def rename_case_insensitive_duplicate_names(apps, schema_editor):
    """Rename projects of the same owner whose names differ only by case.

    The oldest project keeps its name, the others get a `_2`, `_3`, ... suffix in creation order,
    skipping suffixed names already used by the owner.
    """
    Project = apps.get_model("project", "Project")

    duplicate_groups = (
        Project.objects.annotate(upper_name=Upper("name"))
        .values("owner_id", "upper_name")
        .annotate(projects_count=Count("upper_name"))
        .filter(projects_count__gt=1)
        .order_by("owner_id", "upper_name")
    )

    taken_names_by_owner: dict[int, set[str]] = {}
    projects_to_update = []

    for group in duplicate_groups:
        owner_id = group["owner_id"]

        if owner_id not in taken_names_by_owner:
            taken_names_by_owner[owner_id] = set(
                Project.objects.filter(owner_id=owner_id)
                .annotate(upper_name=Upper("name"))
                .values_list("upper_name", flat=True)
            )

        taken_names = taken_names_by_owner[owner_id]

        projects = Project.objects.filter(
            owner_id=owner_id,
            name__iexact=group["upper_name"],
        ).order_by("created_at", "id")

        for project in projects[1:]:
            new_name = get_next_available_name(project.name, taken_names)

            print(f'Renaming project {project.id}: "{project.name}" -> "{new_name}"')

            taken_names.add(new_name.upper())
            project.name = new_name
            projects_to_update.append(project)

    Project.objects.bulk_update(projects_to_update, ["name"], batch_size=500)

    print(f"Renamed {len(projects_to_update)} project(s).")


class Migration(migrations.Migration):
    dependencies = [
        ("project", "0017_qgislayerfield"),
    ]

    operations = [
        migrations.RunPython(
            rename_case_insensitive_duplicate_names,
            # Reversing keeps the renamed projects, there is no reason to restore the confusing duplicates.
            migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="project",
            name="project_owner_name_uniq",
        ),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(
                models.F("owner"),
                Upper("name"),
                name="project_owner_name_uniq",
                violation_error_message="Project with the same name already exists.",
            ),
        ),
    ]
