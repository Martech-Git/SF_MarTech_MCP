# Build stage: install pinned, hash-checked dependencies into a virtualenv.
FROM python:3.12-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --require-hashes -r requirements.lock

# Runtime stage: same base, no build tools, non-root user, app source and policy only.
FROM python:3.12-slim-bookworm
RUN groupadd --gid 10001 sfmcp \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sfmcp
COPY --from=build /opt/venv /opt/venv
COPY src/sf_mcp /app/sf_mcp
COPY policy /app/policy
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SFMCP_POLICY_DIR=/app/policy
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "sf_mcp"]
