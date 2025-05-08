import django_filters

from qfieldcloud.core.models import Project


class ProjectFilterSet(django_filters.FilterSet):
    owner = django_filters.CharFilter(field_name="owner__username", lookup_expr="exact")

    class Meta:
        model = Project
        fields = ["owner", "name"]
