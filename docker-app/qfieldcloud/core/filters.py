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
        if "include_public" in self.form.cleaned_data:
            if not self.form.cleaned_data["include_public"]:
                self.form.cleaned_data["include_public"] = "0"

        return super().filter_queryset(queryset)

    class Meta:
        model = Project
        fields = ["name", "owner", "include_public"]
