import flask # PyPI: Flask
import psycopg # PyPI: psycopg[binary]
import simplejson # PyPI: simplejson

import lazyjson # https://github.com/fenhl/lazyjson

import rs.db

NO_INIT = object()

def setup(app):
    conn = psycopg.connect(f'postgresql:///gefolge')

    @app.before_request
    def db_conn():
        flask.g.db = conn

class PgFile(lazyjson.BaseFile):
    def __init__(self, table, id, *, init=NO_INIT):
        self.table = table
        self.id = id
        if init is not NO_INIT:
            #TODO debug “expecting ParseComplete but received ReadyForQuery” error when using sqlx from flask
            #rs.db.set_json_if_not_exists(self.table, self.id, simplejson.dumps(init, use_decimal=True))
            with flask.g.db.cursor() as cur:
                #TODO wrap u64 to i64
                if table == rs.db.Table.Events:
                    cur.execute("INSERT INTO json_events (id, value) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (self.id, init))
                if table == rs.db.Table.Locations:
                    cur.execute("INSERT INTO json_locations (id, value) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (self.id, init))
                if table == rs.db.Table.Profiles:
                    cur.execute("INSERT INTO json_profiles (id, value) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (self.id, init))
                if table == rs.db.Table.UserData:
                    cur.execute("INSERT INTO json_user_data (id, value) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (self.id, init))
                flask.g.db.commit()

    def __eq__(self, other):
        return self.table == other.table and self.id == other.id

    def __hash__(self):
        return hash((self.table, self.id))

    def __repr__(self):
        return f'gefolge_web.db.PgFile({self.table!r}, {self.id!r})'

    def set(self, new_value):
        #TODO debug “expecting ParseComplete but received ReadyForQuery” error when using sqlx from flask
        #rs.db.set_json(self.table, self.id, simplejson.dumps(new_value, use_decimal=True))
        with flask.g.db.cursor() as cur:
            #TODO wrap u64 to i64
            if self.table == rs.db.Table.Events:
                cur.execute("INSERT INTO json_events (id, value) VALUES (%s, %s)", (self.id, new_value))
            if self.table == rs.db.Table.Locations:
                cur.execute("INSERT INTO json_locations (id, value) VALUES (%s, %s)", (self.id, new_value))
            if self.table == rs.db.Table.Profiles:
                cur.execute("INSERT INTO json_profiles (id, value) VALUES (%s, %s)", (self.id, new_value))
            if self.table == rs.db.Table.UserData:
                cur.execute("INSERT INTO json_user_data (id, value) VALUES (%s, %s)", (self.id, new_value))
            flask.g.db.commit()

    def value(self):
        #TODO debug “expecting ParseComplete but received ReadyForQuery” error when using sqlx from flask
        #return rs.db.get_json(self.table, self.id)
        with flask.g.db.cursor() as cur:
            #TODO wrap u64 to i64
            if self.table == rs.db.Table.Events:
                cur.execute("SELECT value FROM json_events WHERE id = %s", (self.id,))
            if self.table == rs.db.Table.Locations:
                cur.execute("SELECT value FROM json_locations WHERE id = %s", (self.id,))
            if self.table == rs.db.Table.Profiles:
                cur.execute("SELECT value FROM json_profiles WHERE id = %s", (self.id,))
            if self.table == rs.db.Table.UserData:
                cur.execute("SELECT value FROM json_user_data WHERE id = %s", (self.id,))
            value, = cur.fetchone()
            flask.g.db.commit()
        return value
