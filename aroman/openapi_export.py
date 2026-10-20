"""Print the live FastAPI OpenAPI document without contacting the database."""

import json

from aroman.main import app


def main() -> None:
    print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
