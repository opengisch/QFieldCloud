from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError


def reserved_words_validator(value):
    reserved_words = ['user', 'users', 'project', 'projects', 'owner', 'push',
                      'file', 'files', 'collaborator', 'collaborators',
                      'member', 'members', 'organization', 'qfield', 'qfieldcloud',
                      'history', 'version', 'delta', 'deltas', 'deltafile',
                      'auth', 'qfield-files', 'esri']
    if value.lower() in reserved_words:
        raise ValidationError('"{}" is a reserved word!'.format(value))


allowed_symbols_validator = RegexValidator(
    r'^[-a-zA-Z0-9_]+$',
    'Only letters, numbers, underscores or hyphens are allowed.')

min_lenght_validator = RegexValidator(
    r'^.{3,}$',
    'The name must be at least 3 characters long.')

first_symbol_validator = RegexValidator(
    r'^[a-zA-Z].*$',
    'The name must begin with a letter.')
