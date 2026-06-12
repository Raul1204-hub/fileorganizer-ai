"""Tests for the structural read-only enforcement in chat._execute_query.

These tests verify that the security boundary (get_readonly_connection +
authorizer) holds independently of safety_check(), by calling _execute_query
directly with hostile SQL.
"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import chat
import database


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Create a minimal SQLite database for testing."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE archivos (id INTEGER PRIMARY KEY, nombre TEXT, tamaño_bytes INTEGER)")
    conn.execute("INSERT INTO archivos VALUES (1, 'report.pdf', 1024)")
    conn.execute("INSERT INTO archivos VALUES (2, 'photo.jpg', 204800)")
    conn.commit()
    conn.close()
    return db_file


# ── SELECT (must succeed) ─────────────────────────────────────────────────────

def test_select_returns_rows(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        results = chat._execute_query("SELECT * FROM archivos")
    assert len(results) == 2
    assert results[0]["nombre"] == "report.pdf"


def test_select_with_where(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        results = chat._execute_query("SELECT nombre FROM archivos WHERE id = 1")
    assert results == [{"nombre": "report.pdf"}]


def test_select_aggregate(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        results = chat._execute_query("SELECT COUNT(*) AS total FROM archivos")
    assert results[0]["total"] == 2


# ── LIMIT enforcement ─────────────────────────────────────────────────────────

def test_limit_added_when_absent(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        results = chat._execute_query("SELECT * FROM archivos")
    # Just verifying it executes; real cap test needs > _QUERY_LIMIT rows
    assert isinstance(results, list)


def test_existing_limit_is_preserved(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        results = chat._execute_query("SELECT * FROM archivos LIMIT 1")
    assert len(results) == 1


def test_wrap_limit_adds_outer_limit():
    sql = "SELECT * FROM archivos"
    wrapped = chat._wrap_limit(sql)
    assert "LIMIT" in wrapped.upper()
    assert str(chat._QUERY_LIMIT) in wrapped


def test_wrap_limit_skips_when_present():
    sql = "SELECT * FROM archivos LIMIT 10"
    assert chat._wrap_limit(sql) == sql


# ── Denied operations — authorizer layer ─────────────────────────────────────

def test_update_denied(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        with pytest.raises(ValueError, match="SQL error"):
            chat._execute_query("UPDATE archivos SET nombre='x' WHERE id=1")


def test_delete_denied(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        with pytest.raises(ValueError, match="SQL error"):
            chat._execute_query("DELETE FROM archivos WHERE id=1")


def test_pragma_denied(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        with pytest.raises(ValueError, match="SQL error"):
            chat._execute_query("PRAGMA table_info(archivos)")


def test_attach_denied(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        with pytest.raises(ValueError, match="SQL error"):
            chat._execute_query("ATTACH ':memory:' AS mem")


def test_insert_denied(tmp_db):
    with patch("database.DB_PATH", tmp_db):
        with pytest.raises(ValueError, match="SQL error"):
            chat._execute_query("INSERT INTO archivos VALUES (3, 'evil.exe', 0)")


def test_data_not_mutated_after_denied_update(tmp_db):
    """Verify the authorizer truly prevents mutation (not just raises)."""
    with patch("database.DB_PATH", tmp_db):
        with pytest.raises(ValueError):
            chat._execute_query("UPDATE archivos SET nombre='mutated' WHERE id=1")
        results = chat._execute_query("SELECT nombre FROM archivos WHERE id=1")
    assert results[0]["nombre"] == "report.pdf"


# ── safety_check pre-filter ───────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "PRAGMA table_info(archivos)",
    "ATTACH ':memory:' AS mem",
    "DROP TABLE archivos",
    "DELETE FROM archivos",
    "UPDATE archivos SET nombre='x'",
    "INSERT INTO archivos VALUES (3,'x',0)",
    "VACUUM",
    "ALTER TABLE archivos ADD COLUMN bad TEXT",
    "CREATE TABLE evil (id INTEGER)",
    "TRUNCATE TABLE archivos",
])
def test_safety_check_blocks_dangerous_sql(sql):
    assert chat.safety_check(sql) is False


def test_safety_check_passes_valid_select():
    assert chat.safety_check("SELECT * FROM archivos WHERE id = 1") is True


def test_safety_check_rejects_no_select():
    assert chat.safety_check("VALUES (1, 2, 3)") is False
