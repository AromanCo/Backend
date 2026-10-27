"""Refuse local Compose migrations when an old volume has unsafe role ownership."""

from sqlalchemy import text

from aroman.core.db import get_engine


def main() -> None:
    with get_engine().connect() as connection:
        if connection.dialect.name != "postgresql":
            raise RuntimeError("Migration role preflight requires PostgreSQL")
        row = connection.execute(
            text(
                "SELECT current_user AS actor, current_database() AS database, "
                "pg_get_userbyid(d.datdba) AS owner, "
                "r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls "
                "FROM pg_database d JOIN pg_roles r ON r.rolname = current_user "
                "WHERE d.datname = current_database()"
            )
        ).one()
        if (
            row.actor != "aroman_migrator"
            or row.database != "aroman"
            or row.owner != "aroman_migrator"
            or any(
                (
                    row.rolsuper,
                    row.rolcreatedb,
                    row.rolcreaterole,
                    row.rolreplication,
                    row.rolbypassrls,
                )
            )
        ):
            raise RuntimeError(
                "Unsafe migrator role or database ownership; stop before Alembic and review "
                "the existing PostgreSQL volume"
            )


if __name__ == "__main__":
    main()
