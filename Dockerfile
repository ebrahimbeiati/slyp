# Backend only. The Next.js frontend deploys separately to Vercel and is
# deliberately NOT in this image.
#
# Why a Dockerfile rather than letting the platform auto-detect: this repo
# has package.json AND requirements.txt at the root, and nixpacks-style
# detection picks Node from package.json - which would build the frontend
# and never start the API. Being explicit removes the guess.

FROM python:3.12-slim

# Fail fast and log straight through, so a crash-on-boot (see main.py's
# startup credential check) actually shows up in the platform's log view
# instead of sitting in a buffer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not re-resolve the whole tree.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only what the API actually needs. Not app/, lib/, components/,
# node_modules/, tests/ or verify/ - and emphatically not .env, which is
# excluded here, by .dockerignore and by .gitignore. Secrets come from the
# platform's environment config; baking one into an image layer would put
# it somewhere it cannot be rotated out of.
COPY main.py ./
COPY slyp/ ./slyp/

# Documentation only - the platform injects the real $PORT at runtime and
# ignores this.
EXPOSE 8000

# Shell form so ${PORT} expands. Railway, Render and Fly all set PORT;
# the default keeps `docker run -p 8000:8000` working locally.
#
# One worker on purpose: the OpenAI reasoning_effort discovery round trip
# is remembered per process (see slyp/extraction.py), so every extra worker
# pays that ~1s penalty again on its own first request. For a single-user
# demo one worker is also simply enough.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
