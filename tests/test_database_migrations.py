import tempfile
import unittest
from pathlib import Path

import aiosqlite


LEGACY_ARTICLES_SQL = """
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    link TEXT UNIQUE NOT NULL,
    description TEXT,
    content TEXT,
    search_text TEXT DEFAULT '',
    translated_title TEXT,
    translated_description TEXT,
    translation_language TEXT,
    translation_status TEXT DEFAULT 'pending',
    translation_updated_at TEXT,
    published TEXT NOT NULL,
    ai_score INTEGER DEFAULT 0,
    decision_type TEXT DEFAULT 'recommend',
    recommend_level TEXT DEFAULT 'low',
    feedback INTEGER DEFAULT 0,
    feedback_updated_at TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""


class ArticleIdentityMigrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_migrates_global_link_uniqueness_to_feed_scoped_uniqueness(self):
        from app.database import _migrate_article_identity

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "legacy.db"
            async with aiosqlite.connect(database_path) as db:
                await db.execute(
                    "CREATE TABLE feeds (id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL)"
                )
                await db.executemany(
                    "INSERT INTO feeds (id, url) VALUES (?, ?)",
                    [(1, "https://first.example/rss"), (2, "https://second.example/rss")],
                )
                await db.execute(LEGACY_ARTICLES_SQL)
                await db.execute(
                    "INSERT INTO articles (feed_id, title, link, published) VALUES (1, 'First', 'https://example.com/story', '2026-07-31T00:00:00Z')"
                )
                await db.commit()

                await _migrate_article_identity(db)
                await _migrate_article_identity(db)

                await db.execute(
                    "INSERT INTO articles (feed_id, title, link, published) VALUES (2, 'Second', 'https://example.com/story', '2026-07-31T00:00:00Z')"
                )
                await db.commit()

                rows = await db.execute(
                    "SELECT feed_id FROM articles WHERE link = 'https://example.com/story' ORDER BY feed_id"
                )
                self.assertEqual([row[0] for row in await rows.fetchall()], [1, 2])

                indexes = await db.execute("PRAGMA index_list('articles')")
                unique_indexes = [row[1] for row in await indexes.fetchall() if row[2]]
                unique_columns = []
                for index_name in unique_indexes:
                    columns = await db.execute(f'PRAGMA index_info("{index_name}")')
                    unique_columns.append([row[2] for row in await columns.fetchall()])

                self.assertIn(["feed_id", "link"], unique_columns)
                self.assertNotIn(["link"], unique_columns)


if __name__ == "__main__":
    unittest.main()
