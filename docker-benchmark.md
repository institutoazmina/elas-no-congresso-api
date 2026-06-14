# Docker Benchmark

Date: 2026-06-14
Host: macOS (Darwin 24.6.0, arm64), Docker 29.4.0 (OrbStack)

## Final image — `distroless/cc` + standalone CPython 3.12 + bytecode, no wagtail

| Metric | Value |
|---|---|
| Image size | **306 MB** (306,097,534 bytes) |
| Dive efficiency | **99.9999 %** (613 B wasted) |
| Cold build (`--no-cache`) | 22.40 s ± 1.29 s |
| Warm build | 1.09 s ± 0.05 s |
| Cold start (import) | 544 ms |
| Pure import | ~262 ms |
| Runtime base | `gcr.io/distroless/cc-debian12` (no shell / no apt) |
| Runs as | nonroot (uid 65532) |

Biggest layers: `/app/.venv` **188 MB**, `/opt/python` **83 MB** (standalone CPython), distroless base ~24 MB, app code 1 MB.

## Comparison — full progression

| Metric | Single-stage | Multi-stage (slim) | Distroless + bytecode | **Final (no wagtail)** |
|---|---|---|---|---|
| Image size | 437 MB | 400 MB | 431 MB | **306 MB** |
| Dive efficiency | 98.44 % | 98.67 % | ~100 % | **99.9999 %** |
| Wasted space | 9.6 MB | 7.1 MB | 613 B | **613 B** |
| Cold build (`--no-cache`) | 18.48 s | 19.83 s | 25.69 s | 22.40 s |
| Warm build | 629 ms | 854 ms | 1.21 s | 1.09 s |
| Runtime base | `python:3.12-slim` | `python:3.12-slim` | `distroless/cc` | `distroless/cc` |
| Shell / package mgr | yes | yes | **none** | **none** |
| Runs as | uid 1000 | uid 1000 | uid 65532 | uid 65532 |

## Pushing size to the limit

Layer-of-truth on the distroless+bytecode image: `/app/.venv` (~345 MB) and `/opt/python` (~97 MB) dominate. Levers applied:

| Step | What | Size | Δ |
|---|---|---|---|
| start | distroless + bytecode | 431 MB | — |
| safe cuts | prune `botocore/data` to `sesv2` only (app uses SES, not S3); drop stdlib `test/idlelib/tkinter/ensurepip/lib2to3`; drop bundled `tests/` | 384 MB | −47 MB |
| **drop wagtail** | remove `wagtail` dep + dormant `apps/cms` → drops wagtail, willow, pillow, pillow-heif, openpyxl, telepath, modelsearch, soupsieve | **306 MB** | −78 MB |

**Total: 437 MB baseline → 306 MB (−131 MB, −30 %)**, keeping precompiled bytecode (fast startup). After removing wagtail the venv dropped from ~345 MB to 188 MB.

### Rejected / blocked levers
- **`strip` shared objects** — tried `strip --strip-unneeded` on all `.so`; it corrupted numpy's vendored openblas (`ELF load command address/offset not page-aligned`). manylinux wheels ship pre-stripped, so the win is small and the risk is high. **Not done.**
- **numpy (48 MB: `numpy` + `numpy.libs`)** — hard dependency of `pgvector`, which backs a real `VectorField` model. **Locked, kept.**

### Wagtail removal (code change, not just Docker)
Wagtail was dormant: a single `HomePage(Page)` in `apps/cms`, isolated, used by no API/business logic. Removal touched:
- `pyproject.toml` — dropped `wagtail>=7.3,<8`; `uv lock` regenerated.
- `config/settings/base.py` — removed `WAGTAIL_APPS`, the redirect middleware, `WAGTAIL_*` settings, and `apps.cms` from `LOCAL_APPS`.
- `config/urls.py` — removed wagtail admin/docs/pages routes.
- deleted `apps/cms/`.
- `manage.py check` → clean. (CMS to be rebuilt in plain Django later.)

Remaining top packages: `numpy(.libs)` 48 MB (pgvector), `django` 28 MB, `psycopg_binary(.libs)` 21 MB, `uvloop` 15 MB (uvicorn[standard]), `ninja` 8 MB (django-ninja).

## Startup time — `UV_COMPILE_BYTECODE`

Precompiling bytecode at build time (`UV_COMPILE_BYTECODE=1`) bakes `.pyc` into the venv so the interpreter skips compile-on-first-import. Ref: <https://www.joshkasuboski.com/posts/distroless-python-uv/>

Measured at the distroless stage (still with wagtail), to isolate the bytecode effect:

| Distroless variant | Image size | `.pyc` files | Pure import¹ | Cold start² |
|---|---|---|---|---|
| No bytecode | 374 MB | 0 | ~436 ms | 607 ms |
| **Bytecode** | 431 MB | 4892 | **~256 ms (−41 %)** | **494 ms (−18 %)** |
| Final (bytecode, no wagtail) | 306 MB | — | ~262 ms | 544 ms |

¹ `time.perf_counter()` around `import django, uvicorn, psycopg, celery, numpy` (wagtail dropped in the final row) in a fresh container — isolates the compile savings.
² Full `docker run … python -c "import …"`, hyperfine 8 runs — includes container start overhead (constant across rows).

**Trade-off: +57 MB image for −41 % import time on every cold start.** Worth it here — the real `uvicorn`/`django.setup()` boot imports far more modules than the microbenchmark, so the absolute saving is larger, and it compounds across restarts, rolling deploys, and autoscaling. `PYTHONDONTWRITEBYTECODE=1` stays set in the runtime (the baked `.pyc` are used; nothing is written at runtime by the nonroot user).

### Multi-stage changes
- **`uv sync --frozen` venv (252 MB)** replaces `uv pip install --system` (285 MB) — lockfile-pinned, leaner, reproducible.
- **Dropped `libpq5`** — `psycopg[binary]` bundles libpq → apt layer 5.37 MB → 1.91 MB.
- **`COPY --chown=app:app`** folds ownership into the copy layer → removed the 1.09 MB `chown -R` layer.

### Distroless changes
- Runtime = `gcr.io/distroless/cc-debian12`: **no shell, no apt, no OS python** → tiny attack surface, dive ≈ 100 %.
- Python 3.11 in `distroless/python3` is too old (`requires-python >=3.12`), so a **relocatable standalone CPython 3.12** (`uv python install`, `UV_PYTHON_PREFERENCE=only-managed`) is built and copied to `/opt/python`; the venv symlinks resolve to that same absolute path.
- **`tini` copied as a binary** (no package manager in distroless); `HEALTHCHECK` rewritten to **exec-form** (no shell to run shell-form).
- **`libz.so.1` copied** from the builder — `psycopg[binary]`'s bundled libpq links it and `distroless/cc` doesn't ship it.

### Trade-offs
- **Security win**: no shell / no apt → most CVE-bearing OS utilities are simply absent; dive ≈ 100 % (613 B wasted).
- **Size win after slimming**: 306 MB vs 437 MB baseline (−30 %). The +57 MB bytecode cost is more than paid back by the size cuts and the wagtail removal.
- **Build slower**: cold ~22 s vs 18.5 s baseline (downloads standalone CPython); warm ~1.1 s (more `COPY --from` layers). One-time/CI cost, not runtime.
- **Debugging harder**: no shell in the image — use `docker debug`, an ephemeral sidecar, or a `:debug` distroless variant when you need to poke inside.

---

# Baseline — single-stage `python:3.12-slim`

Image tag: `elas-bench:latest`

## Summary

| Metric | Value |
|---|---|
| Total image size | **437 MB** (436,941,932 bytes) |
| Dive efficiency | **98.44 %** |
| Wasted space | 9.6 MB (2.86 % user-wasted) |
| Build time — cold (`--no-cache`) | **18.48 s** ± 0.34 s |
| Build time — warm (cached) | **628.5 ms** ± 3.2 ms |

## Image size — `docker image inspect`

```
436941932 bytes = 437 MB
```

## Layer breakdown — `docker history`

Biggest layers (own contribution):

| Size | Layer |
|---|---|
| 285 MB | `RUN /uv pip install --system -r pyproject.toml` (python deps) |
| 40 MB | python base build layer |
| 5.37 MB | `apt-get install libpq5 tini` |
| 3.86 MB | python base apt layer |
| 1.09 MB | `useradd + chown -R app:app /app` |
| 1.08 MB | `COPY . .` (app code) |
| 391 kB | `COPY pyproject.toml uv.lock` |

Dependency install (285 MB) dominates. App code is tiny (~1 MB).

## Dive efficiency — `dive` (CI mode)

```
efficiency:        98.4388 %
wastedBytes:       9,636,306 bytes (9.6 MB)
userWastedPercent: 2.8643 %
Result: PASS  [Total:3] [Passed:2] [Failed:0] [Warn:0] [Skipped:1]
```

Wasted space mostly from apt cache churn / package metadata across base layers. No major duplicate-file waste — single-stage build already lean.

## Build time — `hyperfine`

Cold build (`--no-cache`, 3 runs):

| Mean | σ | Min | Max |
|---|---|---|---|
| 18.478 s | 0.339 s | 18.115 s | 18.786 s |

Warm build (full cache, warmup 1, 3 runs):

| Mean | σ | Min | Max |
|---|---|---|---|
| 628.5 ms | 3.2 ms | 624.8 ms | 630.5 ms |

`COPY . .` invalidates only app layer — cached rebuilds after dep change still hit the 285 MB install layer.

## Observations / opportunities

- **285 MB deps** = main size driver. Multi-stage build (compile wheels, copy site-packages only) could trim build tooling residue.
- **`COPY . .` before `useradd`** → `chown -R /app` rewrites all app files into new 1.09 MB layer. Use `COPY --chown=app:app` to fold into copy layer.
- **No `.dockerignore` check** — verify `.git`, tests, scripts excluded to shrink `COPY . .` and bust-cache surface.
- Cold build 18.5 s is fine; dep install (~10.6 s) is bulk. uv already fast.
- Efficiency 98.4 % = already good for single-stage. Multi-stage gain mostly in size, not waste %.
