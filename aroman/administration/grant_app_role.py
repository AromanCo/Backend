"""Apply the local Compose application's table permissions after migrations.

Production deployments should provision roles and grants through their own database controls.
"""

from sqlalchemy import text

from aroman.core.db import get_engine


def main() -> None:
    statements = [
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM aroman_app",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM aroman_app",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO aroman_app",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO aroman_app",
        "GRANT INSERT ON users TO aroman_app",
        "GRANT INSERT, UPDATE ON auth_challenges TO aroman_app",
        "GRANT INSERT ON auth_verify_attempts TO aroman_app",
        "GRANT INSERT, UPDATE ON auth_sessions TO aroman_app",
        "GRANT INSERT, UPDATE, DELETE ON fragrance_concepts TO aroman_app",
        "GRANT INSERT, DELETE ON concept_notes TO aroman_app",
    ]
    with get_engine().begin() as connection:
        if connection.dialect.name != "postgresql":
            raise RuntimeError("Local role grants require PostgreSQL")
        for statement in statements:
            connection.execute(text(statement))


if __name__ == "__main__":
    main()
