# Headless tier-1 gateway image (CI / academic + web + searxng + exa only).
#
# This image proves the package assembles and serves in a clean environment.
# It has NO models and NO browser CLIs, so the social/vertical sources and
# re-rank/embed paths are unavailable — exactly the "minimal" tier described in
# docs/deployment.md. Full deployments run the gateway as a host process.
#
#   docker build -t search-gateway .
#   docker run --rm -p 8765:8765 search-gateway
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY search_gateway ./search_gateway
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    SEARCH_GATEWAY_LOG_FMT=text

EXPOSE 8765

ENTRYPOINT ["search-gateway"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8765"]
