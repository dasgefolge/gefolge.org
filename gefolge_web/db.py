import simplejson # PyPI: simplejson

import lazyjson # https://github.com/fenhl/lazyjson

import rs.db

NO_INIT = object()

class PgFile(lazyjson.BaseFile):
    def __init__(self, table, id, *, init=NO_INIT):
        self.table = table
        self.id = id
        if init is not NO_INIT:
            rs.db.set_json_if_not_exists(self.table, self.id, simplejson.dumps(init, use_decimal=True))

    def __eq__(self, other):
        return self.table == other.table and self.id == other.id

    def __hash__(self):
        return hash((self.table, self.id))

    def __repr__(self):
        return f'gefolge_web.db.PgFile({self.table!r}, {self.id!r})'

    def set(self, new_value):
        rs.db.set_json(self.table, self.id, simplejson.dumps(new_value, use_decimal=True))

    def value(self):
        return rs.db.get_json(self.table, self.id)
