import os
import sys
from pathlib import Path

# Tests talk to a local Postgres loaded with deploy/postgres/*.sql (see CONTRIBUTING.md).
os.environ.setdefault("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@localhost:55432/gold")
sys.path.insert(0, str(Path(__file__).parent))
