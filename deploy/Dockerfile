# syntax=docker/dockerfile:1.7
# The planning poker, one process (its page, its WebSocket RPC and topics), served behind a reverse proxy under
# PUBLIC_PATH (default /planningpoker, the proxy removing it). Its MongoDB is its own (docker-compose.yml).
#   docker build -f deploy/Dockerfile --secret id=gh_token,env=GH_TOKEN -t planningpoker .
# The framework's wheels come from its private GitHub releases (deploy/releases.lock, a read-only GH_TOKEN); when
# deploy/wheels/*.whl exist (git-ignored: wheels built locally) they are used instead.
FROM python:3.14.7-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

WORKDIR /src
COPY . .
RUN --mount=type=secret,id=gh_token \
    if ls deploy/wheels/*.whl >/dev/null 2>&1; then mkdir -p /opt/wheels && cp deploy/wheels/*.whl /opt/wheels/; \
    else GH_TOKEN="$(cat /run/secrets/gh_token)" python3 deploy/fetch_wheels.py deploy/releases.lock /opt/wheels; fi \
 && uv build --wheel --quiet --out-dir /opt/wheels

# every framework wheel given by its file (never looked up on a package index), their third-party requirements from PyPI
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python --no-cache /opt/wheels/*.whl

# the process' root: its configuration; a first assembly checks the composition (--strict) at build time
RUN mkdir -p /srv/app/data && cp -r deploy/conf /srv/app/conf \
 && cd /srv/app && /opt/venv/bin/python -m ycappuccino.build assemble --source wheels --wheels /opt/wheels --strict \
      --host conf/application.yml --cache /opt/cache \
 && rm -rf /src /srv/app/build && chown -R app:app /srv/app

USER app
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /srv/app
EXPOSE 8080
CMD ["python", "-m", "ycappuccino.build", "run", "--source", "wheels", "--wheels", "/opt/wheels", \
     "--host", "conf/application.yml", "--cache", "/opt/cache"]
