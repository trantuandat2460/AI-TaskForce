#!/usr/bin/env python3
"""Điểm chạy. Lần đầu: tự seed (users + documents + ingest). Sau đó: start server.
    python run.py            # chạy server (seed nếu DB rỗng)
    python run.py --seed     # seed lại rồi chạy
    python run.py --reset    # xoá data/kms.db rồi seed lại rồi chạy
"""
import sys
from config import settings
from kms_app import db, seed, server

def main():
    args = set(sys.argv[1:])
    if "--reset" in args and settings.DB_PATH.exists():
        settings.DB_PATH.unlink()
        print("  Đã xoá data/kms.db.")
    db.init_db()
    if "--seed" in args or "--reset" in args or db.is_empty():
        seed.run_seed()
    server.serve()

if __name__ == "__main__":
    main()
