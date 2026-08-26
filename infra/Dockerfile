# Headless tier-1 gateway image (CI / academic + web + searxng + exa only).
#
# This image proves the package assembles and serves in a clean environment.
# It has NO models and NO browser CLIs, so the social/vertical sources and
# re-rank/embed paths are unavailable — exactly the "minimal" tier described in
# docs/deployment.md. Full deployments run the gateway as a host process.
#
#   docker build -t kortex-search .
#   docker run --rm -p 127.0.0.1:8765:8765 -e KORTEX_SEARCH_HTTP_TOKEN=<token> kortex-search
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY kortex_search ./kortex_search
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    KORTEX_SEARCH_LOG_FMT=text

EXPOSE 8765

ENTRYPOINT ["kortex-search"]
# Loopback-only + token-gated: the HTTP transport refuses to serve without
# KORTEX_SEARCH_HTTP_TOKEN (see server.main).
CMD ["serve", "--transport", "http", "--host", "127.0.0.1", "--port", "8765"]
