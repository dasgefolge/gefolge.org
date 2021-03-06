import datetime
import decimal

import flask_pagedown.fields # PyPI: Flask-PageDown
import pytz # PyPI: pytz
import wtforms # PyPI: WTForms
import wtforms.ext.dateutil.fields # PyPI: WTForms
import wtforms.validators # PyPI: WTForms

import gefolge_web.util

class AnnotatedStringField(wtforms.StringField):
    def __init__(self, *args, prefix=None, suffix=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = 'AnnotatedStringField'
        self.prefix = prefix
        self.suffix = suffix

class DateTimeField(wtforms.ext.dateutil.fields.DateTimeField):
    def __init__(self, *args, formats=('%d.%m.%Y %H:%M', 'DD.MM.YYYY HH:mm'), parse_kwargs={}, tz=pytz.timezone('Europe/Berlin'), **kwargs):
        super().__init__(*args, **kwargs, display_format=formats[0], parse_kwargs={'dayfirst': True, **parse_kwargs})
        self.moment_format = formats[1]
        self.timezone = tz

class EuroField(AnnotatedStringField):
    """A form field that validates to the Euro class. Some code derived from wtforms.DecimalField."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, suffix='€', **kwargs)

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        elif self.data is not None:
            return str(self.data).strip('€')
        else:
            return ''

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = gefolge_web.util.Euro(valuelist[0].replace(' ', '').replace(',', '.').strip('€'))
            except (decimal.InvalidOperation, ValueError) as e:
                self.data = None
                raise ValueError('Ungültiger Eurobetrag') from e

class FormSection(wtforms.Field):
    def __init__(self, title, level=2, **kwargs):
        self.level = level
        self.title = title
        super().__init__(**kwargs)

class FormText(wtforms.Field):
    def __init__(self, text, *, display_label='', **kwargs):
        self.display_label = display_label
        self.text = text
        super().__init__(**kwargs)

class HorizontalButtonGroupField(wtforms.RadioField):
    def __init__(self, label, validators=None, choices=None, **kwargs):
        super_choices = []
        self.choice_colors = []
        for choice in choices:
            if len(choice) == 3:
                name, choice_label, color_light = choice
                color_dark = color_light
            elif len(choice) == 4:
                name, choice_label, color_light, color_dark = choice
            else:
                raise ValueError('Choice must have 3 or 4 elements, found {!r} ({} elements)'.format(choice, len(choice)))
            super_choices.append((name, choice_label))
            self.choice_colors.append((name, color_light, color_dark))
        super().__init__(label, validators, choices=super_choices, **kwargs)
        self.type = 'HorizontalButtonGroupField'

class MenschField(wtforms.SelectField):
    """A form field that validates to a Mensch. Displayed as a combobox."""

    #TODO actually display as a combobox (text field with dropdown menu)

    def __init__(self, label, validators=[], *, optional_label=None, person_filter=lambda person: True, **kwargs):
        self.optional_label = optional_label
        self.person_filter = person_filter
        super().__init__(label, validators, choices=([] if self.optional_label is None else [(0, optional_label)]) + [(person.snowflake, person.long_name) for person in self.people], **kwargs)

    @property
    def people(self):
        import gefolge_web.login

        return list(filter(self.person_filter, gefolge_web.login.Mensch))

    def iter_choices(self):
        if self.optional_label is not None:
            yield 0, self.optional_label, self.data is None
        for person in self.people:
            yield person.snowflake, person.long_name, person == self.data

    def process_data(self, value):
        try:
            self.data = None if value is None or value == 0 or value == '0' else self.value_constructor(value)
        except (TypeError, ValueError):
            self.data = None

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                if self.optional_label is not None and (valuelist[0] is None or valuelist[0] == 0 or valuelist[0] == '0'):
                    self.data = None
                else:
                    self.data = self.value_constructor(valuelist[0])
            except (TypeError, ValueError):
                raise ValueError('Invalid choice: could not coerce')

    def pre_validate(self, form):
        if self.optional_label is not None:
            if self.data is None:
                return
        for person in self.people:
            if self.data == person:
                break
        else:
            raise ValueError('Not a valid choice')

    def value_constructor(self, snowflake):
        import gefolge_web.login

        return gefolge_web.login.Mensch(snowflake)

class OtherInputRequired:
    def __init__(self, fieldname, message=None):
        self.fieldname = fieldname
        self.message = message

    def __call__(self, form, field):
        try:
            other = form[self.fieldname]
        except KeyError:
            raise wtforms.validators.ValidationError(
                field.gettext(f"Invalid field name '{self.fieldname}'.")
            )
        if not other.raw_data or not other.raw_data[0]:
            if self.message is None:
                message = field.gettext(f'Another field {self.fieldname} is required.')
            else:
                message = self.message

            raise wtforms.validators.ValidationError(message)

class RadioFieldWithSubfields(wtforms.RadioField): # subfield in the sense that there can be additional fields grouped with each option, not in the sense used by WTForms
    def __init__(self, label, validators=None, choices=None, *, _form=None, **kwargs):
        super_choices = []
        self.subforms = []
        for choice in choices:
            if len(choice) == 2:
                name, choice_label = choice
                #TODO make empty subform
            elif len(choice) == 3:
                name, choice_label, subform = choice
            else:
                raise ValueError('Choice must have 2 or 3 elements, found {!r} ({} elements)'.format(choice, len(choice)))
            super_choices.append((name, choice_label))
            subform = subform.bind(form=_form, name=name)
            self.subforms.append(subform)
        super().__init__(label, validators, choices=super_choices, _form=_form, **kwargs)
        self.type = 'RadioFieldWithSubfields'

class TimezoneField(wtforms.SelectField):
    def __init__(self, label='Zeitzone', validators=[], *, featured=[], include_auto=True, **kwargs):
        self.include_auto = include_auto
        timezones = featured + [timezone for timezone in pytz.all_timezones if timezone not in featured]
        self.timezones = [pytz.timezone(tz) for tz in timezones]
        super().__init__(label, validators, choices=([('auto', 'automatisch')] if self.include_auto else []) + [(str(tz), str(tz)) for tz in self.timezones], **kwargs)

    def iter_choices(self):
        if self.include_auto:
            yield 'auto', 'automatisch', self.data is None
        for tz in self.timezones:
            yield str(tz), str(tz), tz == self.data

    def process_data(self, value):
        try:
            self.data = None if value is None or value == 'auto' else self.value_constructor(value)
        except (TypeError, ValueError):
            self.data = None

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                if self.include_auto and (valuelist[0] is None or valuelist[0] == 'auto'):
                    self.data = None
                else:
                    self.data = self.value_constructor(valuelist[0])
            except (TypeError, ValueError):
                raise ValueError('Invalid choice: could not coerce')

    def pre_validate(self, form):
        if self.include_auto:
            if self.data is None:
                return
        for tz in self.timezones:
            if self.data == tz:
                break
        else:
            raise ValueError('Not a valid choice')

    def value_constructor(self, tz_name):
        if isinstance(tz_name, datetime.tzinfo):
            return tz_name
        else:
            return pytz.timezone(tz_name)
