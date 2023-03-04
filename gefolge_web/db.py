import subprocess

import simplejson # PyPI: simplejson

import lazyjson # https://github.com/fenhl/lazyjson

NO_INIT = object()

class PgFile(lazyjson.BaseFile):
    def __init__(self, table, id, *, init=NO_INIT):
        self.table = table
        self.id = id
        if init is not NO_INIT:
            #TODO debug “expecting ParseComplete but received ReadyForQuery” error when using sqlx from flask
            #rs.db.set_json_if_not_exists(self.table, self.id, simplejson.dumps(init, use_decimal=True))
            subprocess.run(['/home/fenhl/bin/gefolge-web-back', self.table, 'set-if-not-exists', str(self.id), simplejson.dumps(init, use_decimal=True)], check=True)

    def __eq__(self, other):
        return self.table == other.table and self.id == other.id

    def __hash__(self):
        return hash((self.table, self.id))

    def __repr__(self):
        return f'gefolge_web.db.PgFile({self.table!r}, {self.id!r})'

    def set(self, new_value):
        #TODO debug “expecting ParseComplete but received ReadyForQuery” error when using sqlx from flask
        #rs.db.set_json(self.table, self.id, simplejson.dumps(new_value, use_decimal=True))
        subprocess.run(['/home/fenhl/bin/gefolge-web-back', self.table, 'set', str(self.id), simplejson.dumps(new_value, use_decimal=True)], check=True)

    def value(self):
        #TODO debug “expecting ParseComplete but received ReadyForQuery” error when using sqlx from flask
        #return rs.db.get_json(self.table, self.id)
        return simplejson.loads(subprocess.run(['/home/fenhl/bin/gefolge-web-back', self.table, 'get', str(self.id)], stdout=subprocess.PIPE, encoding='utf-8', check=True).stdout, use_decimal=True)
