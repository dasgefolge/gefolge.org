import datetime
import pathlib

import pytz # PyPI: pytz
import wtforms # PyPI: WTForms

import lazyjson # https://github.com/fenhl/lazyjson

import gefolge_web.event.programm
import gefolge_web.forms
import gefolge_web.login
import gefolge_web.util

FENHL = gefolge_web.login.Mensch(86841168427495424)
LORE_SEEKER_REPO = pathlib.Path('/opt/git/github.com/fenhl/lore-seeker/main')

class CustomMagicDraft(gefolge_web.event.programm.Programmpunkt):
    def __new__(cls, event, programmpunkt='custom-magic-draft'):
        return object.__new__(cls)

    def __init__(self, event, programmpunkt='custom-magic-draft'):
        super().__init__(event, 'custom-magic-draft')

    def __repr__(self):
        return 'gefolge_web.event.programm.magic.CustomMagicDraft({!r})'.format(self.event)

    def add_form_details(self, Form, editor):
        if self.card_set is None:
            Form.section_sets_intro = gefolge_web.forms.FormText('Welche(s) set(s) würdest du am liebsten draften? Du kannst auch ohne abzustimmen einen Platz reservieren.')
            for set_code, (set_info, set_config) in self.draftable_sets():
                votes = list(map(self.event.person, self.data.get('votes', {}).get(set_code, [])))
                setattr(Form, 'set_checkbox_{}'.format(set_code), wtforms.BooleanField(gefolge_web.util.render_template('event.custom-magic-draft-set-blurb', programmpunkt=self, set_code=set_code, set_info=set_info, set_config=set_config, votes=votes), default=editor.snowflake in self.data.get('votes', {}).get(set_code, [])))
            return True
        else:
            return False

    def assert_exists(self):
        if self.start is None or self.start >= pytz.utc.localize(datetime.datetime(2021, 1, 1)) or self.event.event_id in config().get('skippedEvents', []):
            raise ValueError('Es gibt auf {} (noch) keinen Custom Magic Draft.'.format(self.event))

    @property
    def card_set(self):
        for set_code, iter_set in config()['customSets'].value().items():
            if iter_set.get('drafted') == self.event.event_id:
                return set_code

    @property
    def default_strings(self):
        return gefolge_web.event.programm.Strings(
            signups_header='Spieler',
            signup_form_header='Anmeldung',
            signup_button='Platz reservieren',
            signup_other_button='Platz für {} reservieren',
            edit_signup_button='Änderungen speichern'
        )

    @property
    def description(self):
        set_code = self.card_set
        if set_code is None:
            result = 'Wir [draften](https://mtg.wiki/page/Booster_Draft) ein Custom Magic Set. Um zu bestimmen, welches, kannst du unten abstimmen.'
        else:
            set_info_path = LORE_SEEKER_REPO / 'data' / 'sets' / f'{set_code}.json'
            if set_info_path.exists():
                set_info = gefolge_web.util.cached_json(lazyjson.File(set_info_path))
            else:
                set_info = lazyjson.PythonFile({})
            set_config = config()['customSets'].get(set_code, {})
            set_name = set_info.get('name', set_config.get('name', set_code))
            result = 'Wir [draften](https://mtg.wiki/page/Booster_Draft) [*{}*](https://loreseeker.fenhl.net/set/{}), ein Custom Magic Set.'.format(set_name, set_code.lower())
            result += '\r\n\r\n*{}* {}'.format(set_name, set_config.get('blurb', 'hat noch keine Beschreibung :('))
        return result + '\r\n\r\nWir spielen mit [Proxies](https://mtg.wiki/page/Proxy_card), der Draft ist also kostenlos. Ihr müsst nichts mitbringen. Es gibt 8 Plätze. Es können gerne alle, die Interesse haben, Plätze reservieren, das ist *keine* verbindliche Anmeldung. Ich selbst spiele nur mit, wenn es ohne mich weniger als 8 Spieler wären. Falls wir am Ende weniger als 5 Menschen sind, spielen wir [Sealed](https://mtg.wiki/page/Sealed_Deck) statt Draft.'

    @description.setter
    def description(self, value):
        if value != self.description:
            raise NotImplementedError()

    @property
    def description_editable(self):
        return False

    def draftable_sets(self):
        result = {}
        for set_path in (LORE_SEEKER_REPO / 'data' / 'sets').iterdir():
            set_info = gefolge_web.util.cached_json(lazyjson.File(set_path))
            set_code = set_info['code'].value()
            if set_info.get('custom', False):
                set_config = config()['customSets'].get(set_code, {})
                if set_config.get('boosters', True) and set_config.get('drafted') is None:
                    result[set_code] = set_info, set_config
        return sorted(result.items(), key=lambda kv: (kv[1][0]['releaseDate'].value(), kv[0]))

    @property
    def name(self):
        return 'Custom Magic Draft'

    @property
    def name_editable(self):
        return False

    @property
    def orga(self):
        return FENHL

    @orga.setter
    def orga(self, value):
        if value != self.orga:
            raise NotImplementedError()

    def process_form_details(self, form, editor):
        if self.card_set is None:
            for set_code, (set_info, set_config) in self.draftable_sets():
                if getattr(form, 'set_checkbox_{}'.format(set_code)).data:
                    # voted
                    if editor.snowflake not in self.data.get('votes', {}).get(set_code, []):
                        if 'votes' not in self.data:
                            self.data['votes'] = {}
                        if set_code not in self.data['votes']:
                            self.data['votes'][set_code] = []
                        self.data['votes'][set_code].append(editor.snowflake)
                else:
                    # not voted
                    if editor.snowflake in self.data.get('votes', {}).get(set_code, []):
                        self.data['votes'][set_code] = list(filter(lambda snowflake: snowflake != editor.snowflake, self.data['votes'][set_code].value()))

    @property
    def signups(self):
        return super().signups + [FENHL]

    @property
    def subtitle(self):
        if self.data.get('ibSubtitle'):
            return self.data['ibSubtitle'].value()
        set_code = self.card_set
        if set_code is not None:
            set_info_path = LORE_SEEKER_REPO / 'data' / 'sets' / f'{set_code}.json'
            if set_info_path.exists():
                set_info = gefolge_web.util.cached_json(lazyjson.File(set_info_path))
            else:
                set_info = lazyjson.PythonFile({})
            set_config = config()['customSets'].get(set_code, {})
            return set_info.get('name', set_config.get('name', set_code))

    @subtitle.setter
    def subtitle(self, value):
        self.data['ibSubtitle'] = value #TODO allow resetting to default

def config():
    return gefolge_web.util.cached_json(lazyjson.File(gefolge_web.util.BASE_PATH / 'games' / 'magic.json'))
