# One instance per visitor.
#
# Not a way to host Tilt for several people — the app has no user model, so a
# shared instance means a shared journal. This builds an image where each
# container is one person's journal for as long as they have it open, and
# nothing survives the container. See SECURITY.md, particularly the part about
# what the token does and does not protect once the page is served from here.

FROM node:22-slim AS ui
WORKDIR /ui
# pnpm, because `pnpm-lock.yaml` is what this repo commits — `npm ci` would
# want a package-lock.json that does not exist, and `npm install` would ignore
# the lockfile and build against whatever resolved today.
RUN corepack enable
COPY apps/desktop/package.json apps/desktop/pnpm-lock.yaml ./
# --ignore-scripts, and not only for speed: pnpm 10 refuses to run a
# dependency's install script without explicit approval and *exits non-zero*
# when it skips one, so a plain `pnpm install --frozen-lockfile` fails this
# build outright. Asking for the skip is the honest version of what pnpm was
# going to do anyway, and running no third-party install scripts in an image is
# the posture this repo wants regardless.
#
# Verified rather than assumed: the interface builds from this tree, because
# esbuild's platform binary arrives as an optional dependency rather than from
# the postinstall that is being skipped.
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY apps/desktop/ ./
# The Tauri shell is not involved: this is the same React app served as a plain
# page, talking to the sidecar over HTTP exactly as it always does.
RUN pnpm run build


FROM python:3.11-slim
WORKDIR /app

COPY core/pyproject.toml ./
COPY core/tilt ./tilt
RUN pip install --no-cache-dir .

COPY --from=ui /ui/dist ./static
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Not root. The journal is written by this process and nothing else needs to
# read it. `static` is owned by the runtime user because the entrypoint stamps
# the session token into index.html before uvicorn starts.
RUN useradd --create-home --uid 10001 tilt \
    && mkdir -p /journal /support \
    && chown -R tilt /journal /support /app/static
USER tilt

ENV TILT_DATA_DIR=/journal
# Derived state, deliberately not under /journal: the journal folder is the
# one a visitor might export, and it should carry no database and no key.
ENV TILT_SUPPORT_DIR=/support
ENV TILT_STATIC_DIR=/app/static
ENV TILT_HOST=0.0.0.0
ENV TILT_PORT=8765
ENV TILT_PROVIDER=auto
# The visitor brings their own key, so it is never written to disk.
ENV TILT_EPHEMERAL_SETTINGS=true

EXPOSE 8765
ENTRYPOINT ["docker-entrypoint.sh"]
