"""Create tables and load sample data in one step.

    python scripts/init_db.py            # create + seed (skips seed if products exist)
    python scripts/init_db.py --reset    # drop everything first
    python scripts/init_db.py --no-history
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.seed import seed_all  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--reset", action="store_true", help="drop all tables before creating them")
parser.add_argument("--no-history", action="store_true", help="skip generating historical orders")
parser.add_argument("--days", type=int, default=420, help="days of order history to generate")
args = parser.parse_args()

app = create_app(os.environ.get("FLASK_CONFIG", "development"))
with app.app_context():
    if args.reset:
        db.drop_all()
    db.create_all()
    print("Tables ready:", ", ".join(sorted(db.metadata.tables)))
    seed_all(history_days=0 if args.no_history else args.days)
