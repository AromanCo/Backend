# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN python -c 'import tomllib; data=tomllib.load(open("pyproject.toml", "rb")); print("\n".join(data["project"]["dependencies"]))' > /tmp/aroman-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/aroman-requirements.txt 'setuptools>=75'
COPY README.md ./
COPY aroman ./aroman
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-deps --no-build-isolation . && useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "aroman.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
