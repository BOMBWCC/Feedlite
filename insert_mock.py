import sqlite3

def insert_mock_data():
    # 连接到数据库
    conn = sqlite3.connect('data/feedlite.db')
    cursor = conn.cursor()

    # 咱们刚才准备的 SQL 语句
    sql = """
    -- 1. 插入订阅源
    INSERT INTO feeds (url, title, category, status, created_at) VALUES 
    ('https://v2ex.com/index.xml', 'V2EX', 2, 'active', '2026-03-20T00:00:00Z'),
    ('https://www.yystv.cn/rss/feed', '游研社', 3, 'active', '2026-03-20T00:00:00Z');

    -- 2. 插入测试文章
    INSERT INTO articles (feed_id, title, link, description, content, published, ai_score, status, created_at) VALUES 
    (1, 'Python 3.13 正式发布，带来 JIT 编译器', 'https://v2ex.com/t/10001', '期待已久的 Python 3.13 终于发布了...', '正文...', '2026-03-20T09:00:00Z', 95, 'active', '2026-03-20T09:05:00Z'),
    (2, '《黑神话：悟空》DLC首支预告片公开', 'https://www.yystv.cn/p/10001', '游戏科学今日发布了首个大型资料片...', '正文...', '2026-03-20T08:30:00Z', 98, 'active', '2026-03-20T08:35:00Z'),
    (1, '大家都在用什么稍后阅读工具？', 'https://v2ex.com/t/10002', '最近感觉信息过载，想找个好用的...', '正文...', '2026-03-20T08:00:00Z', 82, 'active', '2026-03-20T08:05:00Z'),
    (1, '开源一个自己写的极简阅读器', 'https://v2ex.com/t/10003', '周末花两天用 FastAPI 写了个...', '正文...', '2026-03-20T07:15:00Z', 90, 'active', '2026-03-20T07:20:00Z'),
    (2, '任天堂 Switch 2 规格疑似泄露', 'https://www.yystv.cn/p/10002', '外媒曝光了硬件规格文档...', '正文...', '2026-03-20T06:45:00Z', 88, 'active', '2026-03-20T06:50:00Z'),
    (1, 'Docker 部署的最佳实践', 'https://v2ex.com/t/10004', '总结了一些生产环境踩坑经验...', '正文...', '2026-03-20T05:30:00Z', 85, 'active', '2026-03-20T05:35:00Z'),
    (2, 'Steam 春季特卖正式开启', 'https://www.yystv.cn/p/10003', '多款大作迎来历史最低价...', '正文...', '2026-03-20T04:00:00Z', 80, 'active', '2026-03-20T04:05:00Z'),
    (1, 'SQLite 高并发会锁库吗？', 'https://v2ex.com/t/10005', '想用 SQLite，但担心并发性能...', '正文...', '2026-03-20T03:20:00Z', 86, 'active', '2026-03-20T03:25:00Z'),
    (2, '《血源诅咒》PC 移植重大突破', 'https://www.yystv.cn/p/10004', '模拟器在 PC 上稳定运行...', '正文...', '2026-03-20T02:10:00Z', 92, 'active', '2026-03-20T02:15:00Z'),
    (1, '如何优雅地写 Prompt？', 'https://v2ex.com/t/10006', '分享几个常用的模板和技巧...', '正文...', '2026-03-20T01:00:00Z', 89, 'active', '2026-03-20T01:05:00Z');
    """

    try:
        # executescript 可以一次性执行多条以分号隔开的 SQL 语句
        cursor.executescript(sql)
        conn.commit()
        print("🎉 数据插入成功！")
    except Exception as e:
        print(f"插入失败: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    insert_mock_data()