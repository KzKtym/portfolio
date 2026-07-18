# app/work_shift/db.py
"""
FastAPI(読み取り専任BFF)からDjangoが管理するPostgreSQLを参照するための接続層。

- 書き込みは一切行わない（書き込みはDjango側 /shift/api/v1/ が担当）
- 接続先は環境変数 WSFT_DATABASE_URL で指定する
  例: postgresql+psycopg2://user:password@localhost:5432/dbname
"""
import os

from sqlalchemy import create_engine

DATABASE_URL = os.environ.get(
    "WSFT_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres",
)

# BFFは読み取り専用のため、コネクションプールは小さめで十分
engine = create_engine(DATABASE_URL, pool_size=5, pool_pre_ping=True)
