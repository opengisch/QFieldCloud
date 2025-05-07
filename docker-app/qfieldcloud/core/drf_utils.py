from typing import Iterable

from django.db.models import QuerySet
from rest_framework import filters, views
from rest_framework.request import Request


class QfcOrderingFilter(filters.OrderingFilter):
    """Custom QFC OrderingFilter class that allows usage of custom attributes expression.

    Use it in a ModelViewSet by setting the `filter_backends` and `ordering_fields` fields.
    It is possible to use an `ordering_fields` expression value with attributes.
    Custom attributes expression has form : "my_field::alias=my_field_alias,key=value"
    """

    SEPARATOR = "::"
    TOKENS_LIST_SEPARATOR = ","
    TOKENS_VALUE_SEPARATOR = "="

    def _get_query_field(self, fields: Iterable[str], term: str) -> str | None:
        """Searches a term in a query field list.

        The field list elements may start with "-".
        This method should be used to search a term from a query's ordering fields.

        Args:
            fields: list of fields to search
            term: term to search in the list
        Returns:
            the matching field, if present in the list
        """
        for field in fields:
            compare_value = field

            # the "-" is used when the fields are sorted descending
            if field.startswith("-"):
                compare_value = field[1:]

            if compare_value != term:
                continue

            return field

        return None

    def _parse_tokenized_attributes(self, raw: str) -> dict[str, str]:
        """Parses an ordering field attributes expression.

        Args:
            raw: raw expression to parse, e.g.: "alias=my_field_alias,key=value"
        Returns:
            dict containing the expression's attributes
        """
        definition_attrs = raw.split(self.TOKENS_LIST_SEPARATOR)

        attr_dict = {}
        for attr in definition_attrs:
            token, value = attr.split(self.TOKENS_VALUE_SEPARATOR, 1)
            attr_dict[token] = value

        return attr_dict

    def _parse_definition(self, definition: str) -> tuple[str, dict[str, str]]:
        """Parses a custom ordering field with attributes expression.

        Args:
            definition: raw definition of the ordering field to parse,
                e.g.: "my_field::alias=my_field_alias,key=value"

        Returns:
            tuple containing the field name (1st) and its attributes dict (2nd)
        """
        name, attr_str = definition.split(self.SEPARATOR, 1)
        attrs = self._parse_tokenized_attributes(attr_str)

        return name, attrs

    def remove_invalid_fields(
        self,
        queryset: QuerySet,
        fields: Iterable[str],
        view: views.APIView,
        request: Request,
    ) -> list[str]:
        """Process ordering fields by parsing custom field expression.

        Custom attributes expression has form : "my_field::alias=my_field_alias,key=value".
        In the above example, `alias` is the URL GET param value,
        but `my_field` is the real model field.

        Args:
            queryset: Django's ORM queryset of the same model as the one used in view of the `ModelViewSet`
            fields: ordering fields passed to the HTTP querystring
            view: DRF view instance
            request: DRF request instance
        Returns :
            parsed ordering fields where aliases have been replaced
        """
        base_fields = super().remove_invalid_fields(queryset, fields, view, request)
        valid_fields = []

        for field_name, _verbose_name in self.get_valid_fields(
            queryset, view, context={"request": request}
        ):
            # standard handling of fields from the base class
            query_field_name = self._get_query_field(base_fields, field_name)

            if query_field_name:
                valid_fields.append(query_field_name)
                continue

            # skip fields without custom attributes expression
            if self.SEPARATOR not in field_name:
                continue

            definition_name, attrs = self._parse_definition(field_name)
            alias = attrs.get("alias", definition_name)
            query_field_name = self._get_query_field(fields, alias)

            # field is not in the HTTP GET request querystring
            if not query_field_name:
                continue

            if query_field_name.startswith("-"):
                definition_name = f"-{definition_name}"

            valid_fields.append(definition_name)

        return valid_fields
