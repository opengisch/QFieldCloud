from django.urls.converters import StringConverter


class IStringConverter(StringConverter):
    def to_python(self, value):
        return value.lower()
