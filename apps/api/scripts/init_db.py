import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.infrastructure.persistence.models import Base
from app.infrastructure.persistence.schema import apply_schema_migrations


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.mysql_dsn, pool_pre_ping=True, future=True)
    Base.metadata.create_all(engine)
    apply_schema_migrations(engine)
    print(f"initialized database schema: {settings.mysql_database}")


if __name__ == "__main__":
    main()
