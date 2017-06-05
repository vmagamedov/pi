import os.path
import pkgutil
import sqlite3


def create_container():
    def proc(conn):
        conn.execute('')
    return proc


def _db_exists(conn):
    rows = conn.execute('SELECT name FROM sqlite_master '
                        'WHERE type=\'table\' AND name=?;',
                        ['meta']).fetchall()
    if rows == [('meta',)]:
        return True
    elif rows == []:
        return False
    else:
        raise TypeError('Unexpected result: {!r}'.format(rows))


def _db_init(conn):
    conn.executescript(pkgutil.get_data('pi', '_sql/meta.sql')
                       .decode('utf-8'))


def _db_version(conn):
    (version,), = conn.execute('SELECT version from meta;')
    return version


class State:

    def __init__(self, path):
        self._path = path
        self._conn = None
        self._checked = False

    def _connect(self):
        if not self._checked:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)

        conn = sqlite3.connect(self._path)
        if self._checked:
            return conn

        db_exists = _db_exists(conn)
        if not db_exists:
            _db_init(conn)

        db_version = _db_version(conn)
        assert db_version == 1, db_version
        # TODO: run migrations if necessary
        self._checked = True
        return conn

    def execute(self, op):
        assert self._conn is not None, 'Not in transaction'
        return op(self._conn)

    async def __aenter__(self):
        assert self._conn is None, 'Already in transaction'
        self._conn = self._connect()
        self._conn.__enter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._conn.__exit__(exc_type, exc_val, exc_tb)
        self._conn.close()
        self._conn = None
