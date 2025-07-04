import django_filters
from django.db import models

from qfieldcloud.core.models import Project, ProjectQueryset


class IncludePublicChoices(models.IntegerChoices):
    EXCLUDE = 0, "Exclude"
    INCLUDE = 1, "Include"


class ProjectFilterSet(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name="name", label="Project name", lookup_expr="iexact"
    )
    owner = django_filters.CharFilter(
        field_name="owner__username",
        label="Project owner username",
        lookup_expr="iexact",
    )
    include_public = django_filters.ChoiceFilter(
        label="Include public projects (can be provided with it's deprecated name `include-public`)",
        choices=IncludePublicChoices.choices,
        method="filter_include_public",
    )

    def filter_include_public(
        self, queryset: models.QuerySet[Project], name: str, value: str
    ) -> models.QuerySet[Project]:
        if value != "1":
            queryset = queryset.exclude(
                user_role_origin=ProjectQueryset.RoleOrigins.PUBLIC
            )

        return queryset

    def filter_queryset(
        self, queryset: models.QuerySet[Project]
    ) -> models.QuerySet[Project]:
        if self.form.cleaned_data.get("include_public") != "":
            return super().filter_queryset(queryset)

        # This is a workaround to make the filter work with the `include-public` parameter,
        # since Django does not have a good support for hyphens in field names and it was previously used in the API.
        if "include-public" in self.form.data:
            self.form.cleaned_data["include_public"] = self.form.data["include-public"]

        return super().filter_queryset(queryset)

    class Meta:
        model = Project
        fields = ["name", "owner", "include_public"]
