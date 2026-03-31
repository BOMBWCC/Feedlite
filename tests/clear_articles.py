"""
清空 FeedLite 数据库中的 articles 表数据。

用法:
    /Users/mac/Documents/Feedlite/.venv/bin/python tests/clear_articles.py
"""

from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "feedlite.db"


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"数据库文件不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        before_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

        conn.execute("BEGIN")
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'articles'")
        conn.commit()

        after_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        print(f"数据库: {DB_PATH}")
        print(f"清理前 articles 数量: {before_count}")
        print(f"清理后 articles 数量: {after_count}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
