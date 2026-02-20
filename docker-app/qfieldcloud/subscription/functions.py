from django.contrib.postgres.fields import DateTimeRangeField
from django.db.models import Func


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()
