"""SQLite: предупреждения, счётчик банов, время последнего мата."""
import sqlite3
import time

import config

_db = sqlite3.connect(config.DB_PATH)
_db.execute("""CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INT, user_id INT, ts INT, reason TEXT, moderator_id INT)""")
_db.execute("CREATE TABLE IF NOT EXISTS bans (chat_id INT, user_id INT, count INT, PRIMARY KEY(chat_id,user_id))")
_db.execute("CREATE TABLE IF NOT EXISTS mat_log (chat_id INT, user_id INT, ts INT, PRIMARY KEY(chat_id,user_id))")
_db.execute("CREATE TABLE IF NOT EXISTS settings (chat_id INT, key TEXT, value TEXT, PRIMARY KEY(chat_id,key))")
# перенос предупреждений из старой версии бота (если была таблица warn_log)
try:
    _db.execute("INSERT INTO warnings (chat_id,user_id,ts,reason,moderator_id) "
                "SELECT chat_id,user_id,ts,'',0 FROM warn_log")
    _db.execute("DROP TABLE warn_log")
except sqlite3.OperationalError:
    pass
_db.commit()

TTL = config.WARN_TTL_DAYS * 86400


def _purge():
    _db.execute("DELETE FROM warnings WHERE ts < ?", (int(time.time()) - TTL,))
    _db.commit()


def active_warns(chat_id: int, user_id: int) -> int:
    _purge()
    return _db.execute("SELECT COUNT(*) FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()[0]


def list_warns(chat_id: int, user_id: int) -> list[tuple[int, str]]:
    _purge()
    return _db.execute("SELECT ts, reason FROM warnings WHERE chat_id=? AND user_id=? ORDER BY ts",
                       (chat_id, user_id)).fetchall()


def add_warn(chat_id: int, user_id: int, reason: str = "", moderator_id: int = 0) -> tuple[int, int]:
    """Добавляет предупреждение. Возвращает (действующих предупреждений, число банов).
    Набралось 3 -> предупреждения обнуляются, счётчик банов растёт (первый бан 3 дня, дальше навсегда)."""
    _db.execute("INSERT INTO warnings (chat_id,user_id,ts,reason,moderator_id) VALUES (?,?,?,?,?)",
                (chat_id, user_id, int(time.time()), reason, moderator_id))
    _db.commit()
    count = active_warns(chat_id, user_id)
    row = _db.execute("SELECT count FROM bans WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    bans = row[0] if row else 0
    if count >= 3:
        bans += 1
        _db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        _db.execute("INSERT OR REPLACE INTO bans VALUES (?,?,?)", (chat_id, user_id, bans))
        _db.commit()
        return 0, bans
    return count, bans


def remove_last_warn(chat_id: int, user_id: int) -> int:
    """Снимает последнее предупреждение. Возвращает, сколько осталось."""
    _purge()
    _db.execute("DELETE FROM warnings WHERE id = (SELECT id FROM warnings WHERE chat_id=? AND user_id=? "
                "ORDER BY ts DESC, id DESC LIMIT 1)", (chat_id, user_id))
    _db.commit()
    return active_warns(chat_id, user_id)


def get_last_mat(chat_id: int, user_id: int) -> int:
    row = _db.execute("SELECT ts FROM mat_log WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    return row[0] if row else 0


def set_last_mat(chat_id: int, user_id: int):
    _db.execute("INSERT OR REPLACE INTO mat_log VALUES (?,?,?)", (chat_id, user_id, int(time.time())))
    _db.commit()


# ---------- Настройки чата (правила, включённые фильтры) ----------
_cache: dict[tuple[int, str], str | None] = {}


def get_setting(chat_id: int, key: str) -> str | None:
    k = (chat_id, key)
    if k not in _cache:
        row = _db.execute("SELECT value FROM settings WHERE chat_id=? AND key=?", k).fetchone()
        _cache[k] = row[0] if row else None
    return _cache[k]


def set_setting(chat_id: int, key: str, value: str | None):
    if value is None:
        _db.execute("DELETE FROM settings WHERE chat_id=? AND key=?", (chat_id, key))
    else:
        _db.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?)", (chat_id, key, value))
    _db.commit()
    _cache[(chat_id, key)] = value


def filter_on(chat_id: int, kind: str) -> bool:
    v = get_setting(chat_id, "f_" + kind)
    return config.FILTER_DEFAULTS[kind] if v is None else v == "1"
