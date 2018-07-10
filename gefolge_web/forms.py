import decimal
import wtforms

import gefolge_web.util

class AnnotatedStringField(wtforms.StringField):
    def __init__(self, *args, prefix=None, suffix=None, **kwargs):
        self.type = 'AnnotatedStringField'
        super().__init__(*args, **kwargs)
        self.prefix = prefix
        self.suffix = suffix

class EuroField(wtforms.StringField):
    """A form field that validates to the Euro class. Some code derived from wtforms.DecimalField."""
    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        elif self.data is not None:
            return str(self.data.value)
        else:
            return ''

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = gefolge_web.util.Euro(valuelist[0].replace(' ', '').replace(',', '.').strip('€'))
            except (decimal.InvalidOperation, ValueError) as e:
                self.data = None
                raise ValueError('Ungültiger Eurobetrag') from e

class EventPersonField(wtforms.SelectField):
    """A form field that validates to a Mensch or Guest. Displayed as a combobox."""

    #TODO actually display as a combobox (text field with dropdown menu)

    def __init__(self, event, label, validators=[], *, allow_guests=True, **kwargs):
        self.event = event
        self.allow_guests = allow_guests
        super().__init__(label, validators, choices=[(person.snowflake, str(person)) for person in self.people], **kwargs)

    @property
    def people(self):
        if self.allow_guests:
            return self.event.signups
        else:
            return self.event.menschen

    def iter_choices(self):
        for person in self.people:
            yield person.snowflake, str(person), person == self.data

    def process_data(self, value):
        try:
            self.data = None if value is None else self.event.person(value)
        except (TypeError, ValueError):
            self.data = None

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = self.event.person(valuelist[0])
            except (TypeError, ValueError):
                raise ValueError('Invalid choice: could not coerce')

    def pre_validate(self, form):
        for person in self.people:
            if self.data == person:
                break
        else:
            raise ValueError('Not a valid choice')

class FormSection(wtforms.Field):
    def __init__(self, title, level=2):
        self.level = level
        self.title = title

class FormText(wtforms.Field):
    def __init__(self, text):
        self.text = text

class HorizontalButtonGroupField(wtforms.RadioField):
    def __init__(self, label, choices, default=None, **kwargs):
        self.type = 'HorizontalButtonGroupField'
        super_choices = []
        self.choice_colors = []
        for name, label, color in choices:
            super_choices.append((name, label))
            self.choice_colors.append((name, color))
        super().__init__(label, choices=super_choices, default=default, **kwargs)

class YesMaybeNoField(HorizontalButtonGroupField):
    """A form field that validates to yes, maybe, or no. Displayed as a horizontal button group."""

    def __init__(self, label, default='maybe', **kwargs):
        super().__init__(label, choices=[('yes', 'Ja', '#449d44'), ('maybe', 'Vielleicht', '#d58512'), ('no', 'Nein', '#ac2925')], default=default, **kwargs)
