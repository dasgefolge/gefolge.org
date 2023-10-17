import flask # PyPI: Flask

class Person:
    def __init__(self):
        raise TypeError('gefolge_web.person.Person cannot be instantiated directly')

    @staticmethod
    def by_api_key(key, *, exclude):
        import gefolge_web.login

        for person in gefolge_web.login.DiscordPerson:
            if person in exclude:
                continue
            if key == person.api_key_inner(create=False, exclude=exclude):
                return person

    @property
    def api_key(self):
        return self.api_key_inner(create=True)

    def api_key_inner(self, *, create, exclude=None):
        return None

    @property
    def is_active(self):
        return False # wer weder als Mensch noch als Gast verifiziert wurde, wird wie anonym behandelt

    @property
    def is_authenticated(self):
        return False

    @property
    def is_admin(self):
        import gefolge_web.login

        return self == gefolge_web.login.Mensch.admin()

    @property
    def is_guest(self):
        return isinstance(self, Guest)

    @property
    def is_mensch(self):
        import gefolge_web.login

        return isinstance(self, gefolge_web.login.Mensch)

    @property
    def is_treasurer(self):
        import gefolge_web.login

        return self == gefolge_web.login.Mensch.treasurer()

    @property
    def long_name(self):
        return str(self)

class Guest(Person):
    pass
