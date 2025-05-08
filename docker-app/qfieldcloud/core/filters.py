import django_filters
from django.db import models

from qfieldcloud.core.models import Project, ProjectQueryset


class IncludePublicChoices(models.IntegerChoices):
    EXCLUDE = 0, "Exclude"
    INCLUDE = 1, "Include"


class ProjectFilterSet(django_filters.FilterSet):
    owner = django_filters.CharFilter(field_name="owner__username", lookup_expr="exact")
    include_public = django_filters.ChoiceFilter(
        label="Include public projects",
        choices=IncludePublicChoices.choices,
        method="filter_include_public",
    )

    def filter_include_public(self, queryset, name, value):
        if value != "1":
            queryset = queryset.exclude(
                user_role_origin=ProjectQueryset.RoleOrigins.PUBLIC
            )

        return queryset

    def filter_queryset(self, queryset):
        include_public = "0"
        if (
            "include-public" in self.form.data
            and self.form.data["include-public"] != ""
        ):
            include_public = self.form.data["include-public"]

        if "include_public" in self.form.cleaned_data:
            if self.form.cleaned_data["include_public"] == "":
                self.form.cleaned_data["include_public"] = include_public

        return super().filter_queryset(queryset)

    class Meta:
        model = Project
        fields = ["name", "owner", "include_public"]
