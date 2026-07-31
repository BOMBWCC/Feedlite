import tempfile
import unittest
from pathlib import Path

import aiosqlite


CURRENT_INDEX_SCHEMA = """
CREATE TABLE articles (
    id INTEGER PRIMARY KEY,
    title TEXT,
    description TEXT,
    content TEXT,
    search_text TEXT DEFAULT ''
);
CREATE VIRTUAL TABLE articles_fts USING fts5(
    search_text,
    content='articles',
    content_rowid='id',
    tokenize='unicode61'
);
CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;
CREATE TRIGGER articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
  INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;
CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
END;

CREATE TABLE article_chunks (
    id INTEGER PRIMARY KEY,
    search_text TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE article_chunks_fts USING fts5(
    search_text,
    content='article_chunks',
    content_rowid='id',
    tokenize='unicode61'
);
CREATE TRIGGER article_chunks_ai AFTER INSERT ON article_chunks BEGIN
  INSERT INTO article_chunks_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;
CREATE TRIGGER article_chunks_au AFTER UPDATE ON article_chunks BEGIN
  INSERT INTO article_chunks_fts(article_chunks_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
  INSERT INTO article_chunks_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;
CREATE TRIGGER article_chunks_ad AFTER DELETE ON article_chunks BEGIN
  INSERT INTO article_chunks_fts(article_chunks_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
END;
"""


class DatabaseIndexInitializationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_current_indexes_are_not_recreated_on_startup_check(self):
        from app.database import _ensure_search_indexes

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "current.db"
            async with aiosqlite.connect(database_path) as db:
                await db.executescript(CURRENT_INDEX_SCHEMA)
                await db.execute(
                    "INSERT INTO articles (id, title, description, content, search_text) VALUES (1, 'Sentinel', '', '', 'sentinel')"
                )
                await db.execute(
                    "INSERT INTO article_chunks (id, search_text) VALUES (1, 'sentinel')"
                )
                await db.commit()

                before = await db.execute("PRAGMA schema_version")
                before_version = (await before.fetchone())[0]

                await _ensure_search_indexes(db, batch_size=2)

                after = await db.execute("PRAGMA schema_version")
                after_version = (await after.fetchone())[0]
                self.assertEqual(after_version, before_version)

                article_match = await db.execute(
                    "SELECT rowid FROM articles_fts WHERE articles_fts MATCH 'sentinel'"
                )
                chunk_match = await db.execute(
                    "SELECT rowid FROM article_chunks_fts WHERE article_chunks_fts MATCH 'sentinel'"
                )
                self.assertEqual(await article_match.fetchall(), [(1,)])
                self.assertEqual(await chunk_match.fetchall(), [(1,)])

    async def test_empty_legacy_search_text_is_backfilled_in_bounded_batches(self):
        from app.database import _ensure_search_indexes

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "legacy.db"
            async with aiosqlite.connect(database_path) as db:
                await db.executescript(CURRENT_INDEX_SCHEMA)
                await db.executemany(
                    "INSERT INTO articles (id, title, description, content, search_text) VALUES (?, ?, '', '', '')",
                    [(index, f"Article {index}") for index in range(1, 6)],
                )
                await db.commit()

                await _ensure_search_indexes(db, batch_size=2)

                rows = await db.execute("SELECT search_text FROM articles ORDER BY id")
                values = [row[0] for row in await rows.fetchall()]
                self.assertEqual(len(values), 5)
                self.assertTrue(all(value for value in values))


if __name__ == "__main__":
    unittest.main()
