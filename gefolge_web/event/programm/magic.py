import lazyjson
import pathlib
import wtforms

import gefolge_web.event.programm
import gefolge_web.forms
import gefolge_web.login

FENHL = gefolge_web.login.Mensch(86841168427495424)
LORE_SEEKER_REPO = pathlib.Path('/opt/git/github.com/fenhl/lore-seeker/stage')
MAGIC_CONFIG = lazyjson.File('/usr/local/share/fidera/games/magic.json')

class CustomMagicDraft(gefolge_web.event.programm.Programmpunkt):
    def __new__(cls, event=None, name=None, *, event_id=None):
        return object.__new__(cls)

    def __init__(self, event=None, name=None, *, event_id=None):
        self.name = 'custom-magic-draft'
        super().__init__(event=event, name=self.name, event_id=event_id)

    def __repr__(self):
        return 'gefolge_web.event.programm.CustomMagicDraft({!r})'.format(self.event)

    def __str__(self):
        return 'Custom Magic Draft'

    def add_form_details(self, Form, editor):
        #TODO remove format poll when set has been determined
        Form.section_sets_intro = gefolge_web.forms.FormText('Welche(s) set(s) würdest du am liebsten draften? Du kannst auch ohne abzustimmen einen Platz reservieren.')
        for set_code, (set_info, set_config) in self.draftable_sets():
            setattr(Form, 'set_checkbox_{}'.format(set_code), wtforms.BooleanField(flask.render_template('event/custom-magic-draft-set-blurb.html', programmpunkt=self, set_code=set_code, set_info=set_info, set_config=set_config)))

    @property
    def description(self):
        return 'Wir [draften](https://mtg.gamepedia.com/Booster_draft) ein Custom Magic Set. Um zu bestimmen, welches, kannst du unten abstimmen.\n\nWir spielen mit [Proxies](https://mtg.gamepedia.com/Proxy), der Draft ist also kostenlos. Ihr müsst nichts mitbringen. Es gibt 8 Plätze. Es können gerne alle, die Interesse haben, Plätze reservieren, das ist *keine* verbindliche Anmeldung. Ich selbst spiele nur mit, wenn es ohne mich weniger als 8 Spieler wären. Falls wir am Ende weniger als 5 Menschen sind, spielen wir [Sealed](https://mtg.gamepedia.com/Sealed_deck) statt Draft.'

    @description.setter
    def description(self, value):
        if value != self.description:
            raise NotImplementedError()

    def draftable_sets(self):
        result = {}
        for set_path in (LORE_SEEKER_REPO / 'data' / 'sets').iterdir():
            set_info = lazyjson.File(set_path)
            set_code = set_info['code'].value()
            if set_info.get('custom', False):
                set_config = MAGIC_CONFIG['customSets'].get(set_code, {})
                if set_config.get('boosters', True) and set_config.get('drafted') is None:
                    result[set_code] = set_info, set_config
        return sorted(result.items(), key=lambda kv: (kv[1][0]['releaseDate'], kv[0]))

    @property
    def orga(self):
        return FENHL

    @orga.setter
    def orga(self, value):
        if value != self.orga:
            raise NotImplementedError()

    def process_form_details(self, form, editor):
        #TODO disallow voting on the format poll when set has been determined
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
                    self.data['votes'][set_code] = list(filter(lambda snowflake: snowflake != editor.snowflake, self.data['votes'][set_code]))

    @property
    def signup_limit(self):
        return self.data.get('limit', 9)

    @property
    def signups(self):
        return [
            self.event.person(snowflake)
            for snowflake in self.data.get('signups', [FENHL.snowflake])
        ]
