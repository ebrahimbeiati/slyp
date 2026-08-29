# Slyp — deployment handoff

Two services, deployed separately from this one repo:

| | What | Where | Reads |
|---|---|---|---|
| **API** | `main.py` + `slyp/` (FastAPI) | Railway, from `Dockerfile` | `SLYP_*`, one provider API key |
| **Frontend** | Next.js (`app/`, `lib/`, `components/`) | Vercel | `NEXT_PUBLIC_API_BASE_URL` |

They only meet over HTTP. The frontend calls `POST {NEXT_PUBLIC_API_BASE_URL}/analyse`
(`lib/Api.ts`) and the API allows its origin via `SLYP_CORS_ORIGINS` (`main.py`).

---

## Environment variables

Every variable, where it is read, and what happens if you get it wrong. **The two marked
build-time vs runtime are the ones that fail in confusing ways.**

| Variable | Service | Required | Read at | If missing |
|---|---|---|---|---|
| `OPENAI_API_KEY` | API | **Yes** (when provider is `openai`) | Runtime, by the OpenAI SDK | **The process refuses to start**, with a message naming the variable |
| `ANTHROPIC_API_KEY` | API | **Yes** (when provider is `anthropic`) | Runtime, by the Anthropic SDK | Same |
| `SLYP_MODEL_PROVIDER` | API | Recommended — **set it explicitly** | Import time, `slyp/extraction.py` | Silently defaults to `anthropic`. If your key is an OpenAI one, startup then fails on the *Anthropic* key, which is confusing. Set it. |
| `SLYP_EXTRACTION_MODEL` | API | **Yes** when provider is `openai` | Import time | Import fails loudly: *"SLYP_EXTRACTION_MODEL must be set when SLYP_MODEL_PROVIDER=openai."* Optional for `anthropic` (defaults to `claude-sonnet-5`) |
| `SLYP_CORS_ORIGINS` | API | **Yes** once deployed | Import time, `main.py` | Defaults to `http://localhost:3000`, so **every browser request from the deployed frontend is blocked**. The UI shows "Couldn't reach the server", which looks exactly like a dead backend. A warning is logged at startup |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend | **Yes** | **BUILD time** — see below | The build **fails** on Vercel/CI with an explanatory error (`next.config.ts`) |
| `PORT` | API | No | Runtime | Injected by Railway. The Dockerfile falls back to 8000 locally |

### The build-time trap, stated plainly

`NEXT_PUBLIC_*` variables are **inlined into the JavaScript bundle when it is built**, not
read when the page loads. Consequences:

- Setting it in Vercel *after* a deploy does nothing until you **redeploy**. A restart is
  not enough.
- Before this was guarded, the built bundle shipped with `http://localhost:8000` baked in,
  so every visitor's browser called their own machine. On an HTTPS page that is also blocked
  as mixed content.
- `next.config.ts` now **throws** if the variable is missing on a hosted build
  (`process.env.VERCEL` or `CI` set). Locally it stays optional, because the
  `http://localhost:8000` fallback is correct there.
- It must **not** end with a slash — `lib/Api.ts` appends `/analyse`, and `//analyse` 404s.
  Also guarded.

---

## Deploying the API (Railway)

1. **New Project → Deploy from GitHub repo** → `ebrahimbeiati/slyp`, branch `demo-ready`.
2. Railway reads `railway.json` and builds the **`Dockerfile`**. Do not let it auto-detect:
   this repo has `package.json` and `requirements.txt` side by side at the root, and
   auto-detection picks Node from `package.json`, builds the frontend, and never starts the
   API.
3. **Variables** → set:
   ```
   SLYP_MODEL_PROVIDER=openai
   SLYP_EXTRACTION_MODEL=gpt-5.6-sol
   OPENAI_API_KEY=<the key>
   SLYP_CORS_ORIGINS=https://<your-vercel-domain>
   ```
   `SLYP_CORS_ORIGINS` is a comma-separated list with **no trailing slash** and including
   the scheme. Add the Vercel preview domain too if you will demo from a preview URL.
4. **Settings → Networking → Generate Domain.** That URL is what the frontend needs.
5. Check the deploy log says `Uvicorn running on http://0.0.0.0:<port>`. If it says
   `RuntimeError: OPENAI_API_KEY is not set`, the guard did its job — go back to step 3.

Health check is `/health`, configured in `railway.json` with a 300s timeout. The timeout is
deliberately generous: the API does blocking work on the event loop during a model call
(see *Known issues*), so `/health` can be slow to answer while an upload is in flight.

## Deploying the frontend (Vercel)

1. **Add New → Project** → same GitHub repo, branch `demo-ready`. Framework: Next.js
   (auto-detected). Root directory: repo root.
2. **Environment Variables** → add, for Production *and* Preview:
   ```
   NEXT_PUBLIC_API_BASE_URL=https://<your-railway-domain>
   ```
   No trailing slash.
3. Deploy. If you forget step 2 the build fails with a message telling you exactly this —
   that is intentional, and far better than a site that silently calls localhost.
4. Copy the resulting Vercel domain back into Railway's `SLYP_CORS_ORIGINS`, then
   **redeploy the API** so it picks the value up (it is read at import time).

The two services reference each other, so the order is: deploy API → get its domain →
deploy frontend with that domain → put the frontend's domain into the API's CORS → redeploy
API.

---

## Verifying a deployment — do this before the demo, not on the day

```bash
API=https://<railway-domain>
WEB=https://<vercel-domain>

# 1. API is alive
curl -s $API/health                                  # {"status":"ok"}

# 2. CORS allows the real frontend origin
curl -s -D - -o /dev/null -X OPTIONS $API/analyse \
  -H "Origin: $WEB" -H "Access-Control-Request-Method: POST" \
  | grep -i access-control-allow-origin                # must echo $WEB

# 3. A real analysis end to end
curl -s -F "file=@verify/fixtures/emergency_m1_midyear_start.pdf" \
        -F "only_job=true" $API/analyse | head -c 400
#    expect "status":"ok" and an estimate of 419.00

# 4. Size limit enforced
curl -s -o /dev/null -w '%{http_code}\n' \
  -F "file=@<any file over 10MB>" $API/analyse         # 413

# 5. The frontend is not calling localhost
curl -s $WEB/upload | grep -c 'localhost:8000'         # 0
```

Then do it in a browser: open `$WEB`, upload
`verify/fixtures/emergency_m1_midyear_start.pdf`, answer "No" to the other-job question, and
confirm £419.00 appears with no console errors.

**Warm it up before presenting.** Push one fixture through `/analyse` a few minutes
beforehand. The first upload of a process pays a one-off ~1s penalty (the OpenAI
`reasoning_effort` discovery round trip, remembered per process — `slyp/extraction.py`), on
top of container start.

---

## Known issues that affect deployment

- **Blocking I/O on the event loop** (report FR-06). `analyse` is `async def` but calls
  synchronous pdfplumber and OpenAI code, so the whole server stalls for the duration of
  each model call — measured: `/health` takes 18 ms idle and **2,309 ms** during an upload.
  Concurrent uploads serialise. Mitigated here with a 300s health-check timeout; the real
  fix is `run_in_threadpool`, not yet applied.
- **`SLYP_MODEL_PROVIDER` defaults to `anthropic`.** The startup guard now catches the
  resulting misconfiguration, but set the variable explicitly anyway rather than relying on
  a default that does not match how this is actually run.
- **Single worker, on purpose.** The `reasoning_effort` discovery result is cached per
  process, so each extra worker repeats that round trip on its own first request.
- **The Dockerfile has not been built locally** — there is no Docker on the development
  machine. It is deliberately minimal (deps, `main.py`, `slyp/`, uvicorn) and every
  dependency ships manylinux wheels for CPython 3.12, but the first Railway build is the
  first real test of it. Do that early enough to fix it calmly.
- **Only tax year 2026/27 is supported.** A payslip from any other year is refused by
  design, with a clear message. Worth knowing before someone offers you their own payslip.

## Repo facts worth knowing

- `.env` is gitignored and has never been committed; no key appears anywhere in git history
  or in any built asset. `.dockerignore` excludes it from the image too — secrets come from
  platform config, never from a layer.
- The API keeps nothing: no disk write, no database, no temp file (Starlette's multipart
  spool is patched so a large upload cannot spill to disk), and logs carry only timings and
  exception **type** names.
- Full detail on all of the above, including what was verified and how, is in
  `verify/FINAL_REPORT.md`.
