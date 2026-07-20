# CHANGELOG


## v0.8.0 (2026-07-20)

### Features

- **dashboard**: Show the upstream path in the traffic log
  ([`8813534`](https://github.com/Nya-Foundation/NyaProxy/commit/881353458dbb3c519e7ec5543d6f58dd38decf95))

The traffic log could tell you an API returned a 401 but not which endpoint it was calling, which is
  the first thing you want when one route on an upstream starts failing.

Record the trail path — the segment after the API name, no query string — on every history entry,
  and surface it two ways: a Path column in the traffic log, and a per-API "Top paths" breakdown
  with request count, error rate and p95 in the detail band. Paths in both are click-to-filter
  handles like the API and key columns, and stack with them.

The path is kept in the history buffer only, never as a Prometheus label: paths are unbounded, and a
  series per distinct path would grow the registry without limit. A test asserts it stays out of the
  exposition output.

The breakdown is derived from the recent sample rather than a new counter, so it needs no extra
  endpoint and is labelled "recent" beside the all-time figures it sits next to.

Path cells constrain the inner control rather than the cell, since a max-width on a <td> is advisory
  under automatic table layout and the column would otherwise squeeze the key column down to
  "sk-...o". Long paths truncate from the left so the distinguishing tail stays readable.

Verified against a running dashboard: headers read Time/API/Path/Status/ Latency/Key, rows show the
  real path, clicking one filters the log to that path alone, and the API detail lists its top paths
  with error rates and p95. No console errors.

### Refactoring

- Drop loguru for the standard library
  ([`7db9137`](https://github.com/Nya-Foundation/NyaProxy/commit/7db9137f66537577a9122ffa4d0a0f611502c47b))

Uvicorn, Starlette, watchfiles, httpx, and nacho all log through the standard library, so logging
  through loguru meant bridging the two with an intercepting handler. That bridge was pure
  accidental complexity, and it was where both of yesterday's logging bugs lived: the frame walk
  that reported logging's own internals as the origin, and third-party loggers keeping an explicit
  level that quietly outranked the configured one.

The coupling turned out to be one file deep. All 84 call sites used only debug/info/warning/error,
  which are identical in the standard library, and every loguru-specific call lived in
  nya/common/logging.py. Nothing else in the dependency tree wanted loguru, so it leaves the install
  entirely.

Also simplify the format. The emitting function and line were noise on every line:

before: ... | INFO | nya.server.app:setup_proxy_routes:370 - Setting up routes

after: ... | INFO | nya.server.app - Setting up routes

The logger name already says which subsystem spoke, and anything worth locating precisely arrives
  with a traceback carrying the exact position. Levels are still padded and coloured on a terminal,
  never in the file, and NO_COLOR is honoured. rotation="10 MB"/retention=5 becomes
  RotatingFileHandler(maxBytes=10MiB, backupCount=5).

Verified with loguru uninstalled from the environment: every module imports, the server starts, and
  stderr and app.log carry one format for both sources:

2026-07-19 23:17:47.507 | INFO | nya.server.app - Setting up generic proxy routes 2026-07-19
  23:17:55.203 | INFO | uvicorn.access - 127.0.0.1:37762 - "GET /health HTTP/1.1" 200

- Unify the log format across NyaProxy and Uvicorn
  ([`77d751b`](https://github.com/Nya-Foundation/NyaProxy/commit/77d751b513f4cf7f227734bdd61d73b418f30ca1))

NyaProxy logs through loguru while Uvicorn, Starlette, and watchfiles log through the standard
  library, so a running gateway interleaved two shapes:

2026-07-18 19:10:01.938 | INFO | nya.server.app:trigger_reload:536 - ... INFO: 172.17.0.1:44650 -
  "GET /api/novelai/... HTTP/1.0" 200 OK

The second carries neither a timestamp nor a logger name, so the two cannot be correlated and the
  access log cannot be parsed alongside everything else.

Route the standard library through loguru with an intercepting handler so every line shares one
  format. Applied at import as well as after the configuration is read, so Uvicorn's own startup
  lines are covered, and log_config=None is passed to uvicorn.run — its default config would
  otherwise reinstall its formatters over ours.

Two details worth recording, both found by running a server rather than by reading the code:

- The origin is taken from the LogRecord instead of by walking frames. The usual frame walk reports
  logging's own internals, so every intercepted line read "logging:callHandlers:1736"; the record
  already knows it came from uvicorn.access, which is the more useful name. - Managed loggers are
  reset to NOTSET. Uvicorn sets an explicit level on them (that is what --log-level does) and an
  explicit level beats the root's, so the level from the configuration file was being silently
  overridden. This surfaced as two tests failing only when the e2e suite ran first, because its
  in-process Uvicorn had left uvicorn.access pinned at WARNING.

Access logs now read:

2026-07-19 23:08:50.770 | INFO | uvicorn.access:send:482 - 127.0.0.1 - "GET /health HTTP/1.1" 200

### Testing

- Cover forwarded client IPs from a trusted proxy
  ([`3365905`](https://github.com/Nya-Foundation/NyaProxy/commit/33659054880b19cb9ad1c0b7f5ca6caf22c18c51))

Behind a reverse proxy the socket peer is the proxy, so if forwarding headers are ignored every user
  shares one IP quota. Only the negative case was covered — an untrusted peer cannot spoof its
  address — and nothing asserted that a trusted peer's headers are actually honoured.

Add e2e coverage for both header shapes nginx sends: quotas apply per X-Forwarded-For client, and
  X-Real-IP alone is enough. The harness gains a trusted_proxies knob.

Also log the resolution at debug level. The uvicorn access log always prints the socket peer, which
  makes a correctly configured deployment look broken and gives an operator no way to tell the two
  apart. Both branches are logged, so an untrusted peer says so rather than staying silent.


## v0.7.2 (2026-07-19)

### Bug Fixes

- Release the credential when stream teardown fails
  ([`b9d5cb5`](https://github.com/Nya-Foundation/NyaProxy/commit/b9d5cb55befe0ecb7400e316b9b454953ad0f3a8))

finalize() marked itself done, then awaited the upstream stream's __aexit__, and only afterwards ran
  the finalizers. The finalizers are what release the key locked by `key_concurrency: false`, so if
  that await raised — a broken upstream connection, or cancellation from the request timeout — the
  release was skipped. `finalized` was already True, so no later call could recover it, and nothing
  expires a key lock: the key left rotation permanently. With a two-key pool that is an outage.

Run the finalizers from a finally block, and swallow errors within each so one bad finalizer cannot
  strand the rest.

Add e2e coverage for credential release under key_concurrency: false, driving a real proxy process
  against a real upstream — client hangs up mid-stream, upstream fails mid-stream, request timeout
  cancels a stalled stream, and the happy path so a fix cannot work by never locking. These already
  passed before the change, which is worth recording: the paths I could drive end to end were
  releasing correctly, and the defect above is one I could only reproduce by forcing teardown to
  fail. The two unit tests do fail without the fix.

Also document the behaviour that actually looks like a stuck queue. Key rate limits are not a
  fast-fail path like the IP and user quotas: a request waits for a key until the queue expiry and
  then 504s. Sustained demand above `keys x key_rate_limit` therefore leaves a permanently full
  queue, and a max_size far above `rate x expiry` only buys a longer wait before the same failure.
  Measured: 1 key at 1/2s with a 6s expiry serves 3 of 12 concurrent requests and expires the other
  9 at 6.1s.

Test harness gains key_concurrency and request_timeout_seconds knobs and a stream-hang upstream
  endpoint.


## v0.7.1 (2026-07-18)

### Bug Fixes

- Apply config changes reliably and keep quotas across restarts
  ([`ddede03`](https://github.com/Nya-Foundation/NyaProxy/commit/ddede03265c6dabd28312cf24c6328b4062af330))

Editing configuration through the UI did not take effect. Three separate faults, each of which alone
  was enough to break it:

1. Docker could not save at all. Nacho writes config by renaming a temporary file over the target,
  and that rename fails with EBUSY against a bind-mounted file:

StorageError: Cannot save /app/config.yaml: [Errno 16] Resource busy:
  '/app/.config.yaml.qk9ed65s.tmp' -> '/app/config.yaml'

The documented compose file also mounted it read-only. Mount the directory, read-write, and run as a
  user that can write it.

2. The image shipped --no-reload, which makes trigger_reload a no-op. Restarting is how a config
  change is applied, so this stranded every edit until the container was restarted by hand.

3. Restarting reset the state that enforces quotas. Rate-limit windows and key cool-downs live only
  in memory, so each edit handed out a fresh burst allowance and released every quarantined key —
  also true of any ordinary deploy or crash.

Persist limiter windows and cool-downs across restarts. Limiters are rebuilt lazily so the rate
  always comes from the current configuration and only the consumed window carries over; a limit
  raised while the process was down therefore applies immediately. Entries are keyed by a hash of
  the limiter name because that name embeds the upstream credential and client IPs, and the file is
  written 0600 via a temporary file and rename. A missing, corrupt, or version-mismatched file is
  ignored: cold counters are a degradation, refusing to start is an outage.

Also debounce reload triggers. A single save emits several change events and every restart drops
  in-flight requests, including streaming responses.

The state file lives beside the configuration, taken from the config manager rather than CONFIG_PATH
  — the path can arrive as a constructor argument, and falling back to the working directory made
  two instances started from one directory share quotas. That bug surfaced as e2e tests leaking
  rate-limit state between runs.

Not persisted: queued requests. Each owns an asyncio.Future tied to a client socket that does not
  survive the restart, so replaying one would spend upstream quota on a response nobody is waiting
  for. Shutdown already fails them so clients can retry.

Verified end to end in Docker: a UI save now returns 200, persists to the host, triggers "WatchFiles
  detected changes in 'watch.txt'. Reloading...", and writes .nya_state.json on the way out. 28 new
  tests, checked by mutation: disabling restoration fails 4 of them, and removing the name hashing
  fails the credential-leak test.

### Documentation

- Document the data directory mount for Docker
  ([`15e37cf`](https://github.com/Nya-Foundation/NyaProxy/commit/15e37cfe07de45154b197a3c2fe13d430bc14b4e))

The documented `docker run` reproduced every fault that made config edits fail in containers: it
  bind-mounted config.yaml as a single file, mounted it read-only, and passed --no-reload.

Mount the directory instead. Saving from the /config UI writes a temporary file and renames it over
  the target, which fails with EBUSY against a bind-mounted file, so every save returned a 500
  before the read-only flag was even reached. Add --user, because the image runs as uid 100 and
  cannot otherwise write a directory the operator owns, and note that Docker Desktop maps ownership
  itself. Drop --no-reload, which stranded any edit that did manage to save.

Also describe what the directory now holds: config.yaml plus .nya_state.json, which carries
  rate-limit windows and key cool-downs across the restart that applies a configuration change.

Applied to the Chinese and Japanese READMEs as well, since all three carried the same command.

Verified by running the documented command verbatim against a build of this tree: the container
  starts, a UI save returns 200 and persists to ./data on the host, the reload fires ("WatchFiles
  detected changes in 'watch.txt'"), .nya_state.json is written 0600 beside the config, and the
  service stays healthy afterwards.

- Show key_blocking in the provider example configs
  ([`b02fc8d`](https://github.com/Nya-Foundation/NyaProxy/commit/b02fc8d0fa5d8e8c6d0073c783ad2a1db77edc05))

The credential quarantine setting shipped with the starter config in nya/config.yaml and is listed
  in the README feature table, but none of the provider examples mentioned it, so anyone copying one
  as a starting point had no sign the option exists.

Add the block to the openai, gemini, and novelai examples, mirroring the starter config's values
  (disabled, 403, 300s) rather than asserting per-provider status codes. Left disabled deliberately:
  quarantining on a wrongly chosen status code removes keys from rotation, which should be an
  explicit choice.

Verified: all five configs validate against nya/schema.json and load through ConfigManager, which
  reports key_blocking for every API.


## v0.7.0 (2026-07-18)

### Bug Fixes

- Restore the nyaproxy console script and project URLs
  ([`cdc4d5e`](https://github.com/Nya-Foundation/NyaProxy/commit/cdc4d5e0cb00454c7fb070456e58deabe8ac5e0a))

The merge f2ff54e ("Merge branch 'main' into dev") dropped [project.scripts] and [project.urls] from
  pyproject.toml. Both parents of that merge still contained the tables, so this was not something
  git resolved badly on its own — the conflict on the version line (0.4.6 on dev against the 0.6.0
  release bump on main) was resolved by hand and the two tables were deleted along with the markers.

Without [project.scripts] the wheel carries no entry_points.txt, so the `nyaproxy` command does not
  exist and the Docker image, whose ENTRYPOINT is that script, cannot start at all. Restore both
  tables verbatim.

Published artifacts are unaffected: v0.6.0 was built from 2595a47, which predates the bad merge, and
  its wheel on PyPI does contain the console script. The quality gate blocked every release attempt
  after the merge, so no broken artifact ever reached PyPI or the registries.

Verified: the wheel now ships entry_points.txt, the CI smoke gate exits 0 printing "NyaProxy 0.6.0",
  and the container starts and reports the same version.

### Continuous Integration

- Smoke-test the wheel in an isolated venv
  ([`d4a588a`](https://github.com/Nya-Foundation/NyaProxy/commit/d4a588aeb0594fc067afe460f3243b48fe90218a))

The smoke test installed the freshly built wheel over the editable install that lint and typecheck
  ran against. That editable install owns the `nyaproxy` script, so the test could not distinguish a
  working wheel from one whose console script was missing: either way the script was present until
  the reinstall, and its absence afterwards surfaced only as a bare "nyaproxy: command not found"
  with nothing naming the cause.

Install into a throwaway venv instead, which is what a user gets from PyPI, and assert the entry
  point through importlib.metadata before invoking it so a missing console script reports itself.
  Installing with dependencies rather than --no-deps also covers the declared runtime requirements,
  which previously rode on the dev environment and were never actually exercised.

Also: - rm -rf dist first; `make build` does not clean, so a stale artifact makes the dist/*.whl
  glob ambiguous. - Assert the packaged dashboard assets. They are data files, so no import failure
  would catch their loss, and the service 404s at runtime if they are dropped.

Verified by rebuilding with [project.scripts] removed: the new assertion fails with "wheel is
  missing the nyaproxy console script" instead of the old opaque shell error.

- Start the image before publishing it
  ([`85236fa`](https://github.com/Nya-Foundation/NyaProxy/commit/85236fa179e9069e438d8eb6c4f4ee30bbde6a5a))

`docker build` never validates ENTRYPOINT, so an image whose console script is missing builds
  cleanly, pushes to both registries, takes the :latest tag, and passes the Trivy scan — then dies
  on `docker run` with "exec: nyaproxy: not found". Nothing in the release path ever ran the
  container, so that failure could only be discovered by a user pulling it.

Build a single-arch image and start it before the publishing steps. The amd64 layers are reused from
  the gha cache by the multi-arch build that follows, so the extra build is close to free.

Verified both ways: the image built from this tree prints its version, and an image built with
  [project.scripts] removed builds successfully but exits 127 at the new step, before anything is
  pushed.


## v0.6.0 (2026-07-18)


## v0.5.0 (2026-05-22)

### Bug Fixes

- Reject blank API-key entries; adopt nacho-python 0.1.1
  ([`2ef6eda`](https://github.com/Nya-Foundation/NyaProxy/commit/2ef6eda9665c20a54d7fddbee1f3fc973150bf26))

nacho 0.1.1 validates api_key at construction (both AuthGuard and NachoOrchestrator) instead of
  failing with a 500 at request time, and closes a hole where a falsy api_key such as [] skipped
  auth construction entirely and served the config API unauthenticated. Upstream also documented the
  embedded-UI contract we depend on (localStorage nacho_api_key for REST, NACHO_api_key cookie for
  the WebSocket) and pinned it with a UI test.

Their release note prompted an audit of our own falsy-key handling, which found an equivalent hole
  on this side.

A blank first entry — an unset "${MASTER_KEY}" (nacho substitutes env vars), or a stray '-' in YAML
  — produced a configuration NyaProxy considered authenticated while leaving the master key empty:

api_key: ["", "app-key"] -> is_auth_disabled() False verify_api_key("", verify_master=True) True

so "Authorization: Bearer " with an empty value authenticated as master and opened the dashboard and
  config UI. A None entry was worse in a different way: configured_key[0].strip() raised
  AttributeError, 500ing every authenticated request.

Fix: - usable_keys() drops blank and non-str entries, so a blank entry can never authenticate
  anything and can never be presented as a credential - master_key() resolves the first *configured*
  entry, not the first usable one: a blank master locks the admin surfaces rather than silently
  promoting a proxy key to admin - a list holding only blank entries now reads as "no key
  configured", matching api_key: "" and api_key: [] - an unrecognised config shape still fails
  closed - ConfigManager mirrors the rule so nacho only ever receives the master key or None, never
  a blank string - startup warns when auth is on but the master entry is blank, since the admin
  surfaces then reject every key

Verified live on 0.1.1 with api_key: ["", "app-key-e2e"]: empty-bearer and proxy-key requests to
  /dashboard and /config all return 401, proxy traffic still returns 200, and the warning fires.
  With a correct config, the config SSO flow, WebSocket live updates, and config writes all still
  work.

Tests: 12 further regressions covering blank/None/whitespace entries in every position, the
  empty-bearer bypass end to end, all-blank lists, and the unexpected-shape case.

- Restrict dashboard and config UI to the master key
  ([`58739bc`](https://github.com/Nya-Foundation/NyaProxy/commit/58739bca72651f54672ffa06d27feecd1ddcf65d))

server.api_key is a list of two different roles: the first entry is the master key (administers the
  proxy), and the rest are access keys that may route traffic through the proxy but must not change
  configuration or read operational data.

AuthMiddleware only enforced that split on the session cookie. verify_api_key_header() called
  verify_api_key() with the default verify_master=False, so ANY configured key presented as a Bearer
  token was accepted on EVERY path — including the dashboard and its control actions.

Verified against a running instance before the fix, with a non-master key:

GET /dashboard/api/metrics -> 200 GET /dashboard/ -> 200 POST /dashboard/api/metrics/reset -> 200
  POST /dashboard/api/queue/clear -> 200

so any client holding a proxy key could read traffic metrics, request history and key usage, and
  wipe queues and metrics. /config happened to return 401 only because nacho's own guard is
  configured with the master key alone; NyaProxy's middleware was letting those requests through, so
  the config UI would have been exposed too had the whole list been passed down.

Fix: classify dashboard and config paths as admin surfaces and require the master key there, for
  both the cookie and the Authorization header. Proxy traffic is unchanged and still accepts any
  configured key. The mount prefix is stripped before matching so the rule holds behind a
  reverse-proxy path prefix, and prefix matching is segment-aware so a proxied upstream path that
  merely contains "dashboard" is not misclassified.

After the fix, same instance: every admin path returns 401 for a non-master key while
  /api/test/v1/echo still returns 200 for it; the master key retains full access; /health, /info and
  /metrics stay public.

Tests: 12 new regressions covering non-master denial on each admin surface, master acceptance, proxy
  access retained, non-master cookies, the single-string-key case, both ASGI root_path conventions,
  and the path-containing-"dashboard" false positive.

### Chores

- Drop python 3.10 support
  ([`5b62536`](https://github.com/Nya-Foundation/NyaProxy/commit/5b6253655dae3374a3d955ac711531350d1efb48))

- **deps**: Bump dependencies and adopt nacho-python 0.1.0
  ([`bec6f29`](https://github.com/Nya-Foundation/NyaProxy/commit/bec6f2994d0b2cf1c1d0609500084c1f9468ef3d))

Raise version floors to current releases: fastapi 0.139, uvicorn 0.51, httpx 0.28, orjson 3.11,
  prometheus-client 0.25, plus dev/lint tooling (pytest 8.3, black 25, isort 6, mypy 1.14). Lockfile
  regenerated.

nacho-python 0.0.3 -> 0.1.0 (major refactor). The public API NyaProxy relies on (Nacho,
  FileStorageBackend, RemoteStorageBackend, NachoOrchestrator, the get_* getters, on_change,
  validate) survived the refactor, with one behavioural change:

- NachoOrchestrator's auth guard now compares the api_key via hmac.compare_digest, which requires a
  str. NyaProxy configures api_key as a list (first entry = master key), so pass the master key
  rather than the list — otherwise config-UI auth raises TypeError on first request.

Config-UI single sign-on: the Nacho SPA reads its key from localStorage (nacho_api_key) and sends it
  as a Bearer header, while its live-update WebSocket authenticates from the NACHO_api_key cookie.
  The NyaProxy login page now seeds both on sign-in (and clears them on rejection), so one sign-in
  unlocks /config without a second Nacho login.

Verified live against nacho 0.1.0: sign-in -> config editor loads authenticated, full config
  renders, WebSocket connects ("live"), and an edit round-trips to disk and triggers reload. All 279
  tests pass; mypy clean.

### Features

- Force version bump
  ([`f8020fe`](https://github.com/Nya-Foundation/NyaProxy/commit/f8020fe7fbc2acd85742504620630531fd743ae9))

- Harden defaults, map upstream failures to 502/504, close e2e gaps, trim dead code
  ([`bee0207`](https://github.com/Nya-Foundation/NyaProxy/commit/bee02071fcaeec06f593edfaadcc4d8a3d9d316c))

Security / operational fixes: - startup warning when server.api_key is unset while bound to a
  non-loopback host (unset key disables auth entirely); consolidated the "auth disabled" logic into
  AuthManager.is_auth_disabled() - README (all languages) falsely claimed a SUPER_SECURE_PASSWORD!!!
  fallback when api_key is unset — the real behavior is "no auth"; docs now say so - upstream
  connection failures now return 502 and upstream timeouts 504 (previously both surfaced as generic
  500 "Internal proxy error") - /metrics no longer raises AttributeError when hit before startup
  completes - log file now rotates at 10 MB, keeping 5 files (was unbounded) - new --no-reload flag
  disables the file-watch supervisor for deployments where restarts should be explicit; config
  templates ship info-level logging, an auth warning comment, and placeholder proxy keys instead of
  a shared literal password

UX: - /health liveness endpoint (auth-excluded), python -m nya entry point - yaml-language-server
  $schema modelines in shipped configs for IDE autocomplete; key_weights example; schema marks
  retry.mode deprecated (accepted for compatibility, never read)

Cleanup: - removed dead code: ConfigManager.{get_default_settings,reload} (reload was an unused
  second reload mechanism), RateLimiter.{can_proceed,remaining_quota}, RequestQueue.get_queue_size,
  dashboard get_metrics hasattr dead branch, duplicate substitution-rules getter (merged into
  get_api_request_subst_rules), stale "singleton" docstrings, triplicated host/port resolution

Tests: - split the 887-line test_core_components.py into per-module files with shared fakes in
  core_helpers.py - new e2e suite for upstream failure modes: dead upstream -> 502, slow upstream ->
  504 within the proxy's own budget, mid-stream upstream error does not wedge subsequent buffered or
  streaming requests - coverage ratchet raised 60 -> 90 (actual: 95); tracked scripts/burst.py

docs: README rewritten around accurate auth/bind behavior, all five LB strategies, aliases, retries,
  endpoints table incl. /health and /metrics, CLI reference, and operational notes (reload
  semantics, in-memory state)

- Harden gateway and add credential quarantine
  ([`71d54ef`](https://github.com/Nya-Foundation/NyaProxy/commit/71d54ef45aec5864bd1b2778b7477ffb891d6024))

Improve proxy fidelity, queue lifecycle, trusted-client handling, configuration validation,
  dashboard UX, documentation, packaging, and CI. Replace Black/isort with Ruff, add configurable
  upstream-status key quarantine, expand E2E coverage, and upgrade nacho-python to 1.0.0.

- Harden rate limiting and retry pipeline, wire weighted LB, sweep dead code
  ([`382c9f6`](https://github.com/Nya-Foundation/NyaProxy/commit/382c9f62978ec103ab5c87f953aca742d18798b5))

Correctness fixes: - key cool-down (block_for) now works when key_rate_limit is "0"/unlimited, using
  an explicit blocked_until deadline instead of the timestamp-fill hack - retry delays run as
  detached tasks so a retrying request no longer stalls the per-API worker pipeline under concurrent
  429/5xx responses - requests whose client already timed out or disconnected are dropped before
  spending upstream quota; their resources are released - dashboard "clear all queues" no longer
  500s (RequestQueue.clear_all_queues was never implemented; the unit test passed against a drifted
  mock) - malformed x-forwarded-for/forwarded headers are ignored instead of raising ValueError and
  turning into 500s - queued-request expiry maps to 504 (was generic 500), blocked paths return 403
  (405 is now method-only), and quota 429s carry a Retry-After header - request path is parsed once
  per request instead of twice

Features: - weighted load balancing is configurable via new per-API key_weights; fastest_response
  now receives real per-key latencies from the queue - schema accepts "0" (unlimited) rate limits
  and the HEAD method, matching what the code already supports

Cleanup (~350 lines removed): - unused RootPathMiddleware, _init_auth, 8 never-raised exception
  classes, dead config getters, dashboard uvicorn runners, redundant worker semaphore, misnamed
  MAX_QUEUE_SIZE constant, no-op retry.mode config knob

Tests: - new unit regressions for cool-down, forwarded-header parsing, weighted wiring,
  clear_all_queues, and non-blocking retry - new e2e suite covering rate limiting under load (burst
  throttling, queue overflow 503/504, IP quota 429 + Retry-After) and the retry strategy (429/5xx
  key rotation, single-key cool-down, retries not blocking traffic), plus dashboard controls,
  aliases, HEAD, and auth rejection - coverage ratchet raised 42 -> 60 (actual: 95%)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Rebrand to the Coin Cat identity
  ([`f9e7013`](https://github.com/Nya-Foundation/NyaProxy/commit/f9e70130dbeadb085ae6bb4d4e5a28f8ebfea0ee))

New visual identity: a cat's head as negative space in a solid disc, closed by a horizon line. Flat,
  geometric, two colors (midnight #23264B, indigo #6C6FE0) plus neutrals. Wordmark set in Space
  Grotesk Medium, outlined to paths so the SVGs embed no fonts.

- assets/brand/: horizontal lockups (light/dark), standalone marks, square icon (SVG + 512px PNG,
  legible at 16px), GitHub social banner (1280x640 PNG + SVG source), and a usage README with the
  palette - nya/html/static/logo.svg: replaced the auto-traced 400-line raster trace with the new
  mark in accent indigo (holds on both dashboard themes) - nya/html/favicon.ico: regenerated at
  16/32/48 from the new icon - assets/banner.png removed; READMEs (en/zh/ja) now point at
  assets/brand/banner-1280x640.png

Mockups for direction review were generated via codex image tooling; final assets are precise
  generated geometry.

- Redesign dashboard and login UI around the Coin Cat identity
  ([`5b3310f`](https://github.com/Nya-Foundation/NyaProxy/commit/5b3310f3dc5653d3a551903be7bc5193f407e178))

Complete rewrite of the web UI (index.html, login.html, styles.css, dashboard.js) designed by a UX
  panel (information architecture, visual language, interaction) and verified by adversarial parity
  + design review, then exercised live in both themes at desktop and mobile widths.

Design: - Coin Cat token system: midnight/indigo palette with equal-care light and dark themes
  (data-theme + prefers-color-scheme, pre-paint anti-flash) - self-hosted Space Grotesk variable
  font (woff2 + OFL license, no CDN) - brand motifs applied sparingly: the horizon status bar and
  the coin mark resting on the login page's horizon rule - flat, minimalist: tabular numerals for
  metrics, quiet status pills, visible focus states, prefers-reduced-motion respected

Functionality (full parity plus enhancements): - overview tiles (error rate, requests, pressure,
  uptime) with a 2xx/5xx ratio bar; expandable per-API rows; key-usage detail; queue state;
  recent-request table with status filter chips, text search (rendered fields only), and a 60-row
  cap; API name filter - refresh model: adaptive polling with backoff, manual refresh, last-updated
  stamp, per-section failure indicators - control actions (clear queue per-API/all, reset metrics)
  gated by enable_control with inline non-blocking confirmation - login: show-password toggle,
  inline error state, theme toggle

Hardening (auth.py): - return_path is substituted as a JSON-escaped literal (closes a reflected XSS
  on the pre-auth login page via percent-encoded paths; <> \u-escaped) - session cookie value is
  URI-encoded client-side and decoded server-side so keys with cookie-grammar characters survive;
  Secure flag added on https - login-page assets (logo, favicon, font) excluded from auth by suffix
  so they resolve behind reverse-proxy path prefixes

- Update default passwd... doc update
  ([`b71b20b`](https://github.com/Nya-Foundation/NyaProxy/commit/b71b20b5423d065aac477be9a4a5730cf8920ece))

- **dashboard**: Surface latency, trends, and credential health
  ([`6561776`](https://github.com/Nya-Foundation/NyaProxy/commit/656177666de94ba35fd60a2b82c2c706d3aa2ada))

The dashboard fetched up to 2000 timestamped responses every cycle and used almost none of them: no
  time dimension, no latency distribution, and no per-credential view — on a gateway whose main job
  is rotating credentials. Everything added here is folded out of that existing sample in one pass,
  so it costs no extra requests and no new endpoints.

Close the gaps against the metrics API: - Latency, previously absent from the overview entirely: a
  p95 tile, and a distribution chart with p50/p95/p99 pinned under a shared 0→p99 axis. Percentiles
  come from the response sample and are labelled "recent"; the counters stay authoritative for
  all-time totals. - Per-bucket trend sparklines on the tiles and in the API ledger. - A credential
  board: share of pool, recent error rate, and last use per key, with a concentration note — an
  unevenly rotated or failing key is the operational signal this product exists to expose. - p95 per
  API in the ledger and its detail band.

Interaction and layout: - Sortable ledger columns, with aria-sort. - Cross-filtering: any API or key
  in the traffic log, the credential board, or a detail band narrows the log; filters stack, show as
  removable tags, and clear with Escape. - Rebuild the overview as a four-tile pulse row over a
  health/credentials pair; uptime moves to the page header, freeing a tile for latency. - Raise the
  traffic log from 60 to 200 rows and add in-view latency bars.

Charts are inline SVG on the existing horizon rule, so the new surfaces read as part of the Coin Cat
  system rather than a charting library bolted on. No new dependencies.


## v0.4.6 (2025-07-07)

### Bug Fixes

- Refine rate limit config, where 0/d means no rate limit
  ([`2179a49`](https://github.com/Nya-Foundation/NyaProxy/commit/2179a490390bf44bbb425feb3ecd2ceb3bb4a489))

### Chores

- Update config example
  ([`bd814a5`](https://github.com/Nya-Foundation/NyaProxy/commit/bd814a5cfab40edb3db8a5d41f4714952b40f95c))


## v0.4.5 (2025-07-06)

### Bug Fixes

- Fix proxy setting, add support for socks5
  ([`cd2e6e7`](https://github.com/Nya-Foundation/NyaProxy/commit/cd2e6e74ce80768f864ed2e9de12b67955929632))

- Performace enhancement, add max_workers config
  ([`e9159b4`](https://github.com/Nya-Foundation/NyaProxy/commit/e9159b421266f335b312bd0eaf1618f2683b744a))


## v0.4.4 (2025-07-04)

### Bug Fixes

- App restart logic on config changes (file backend), add ZH, JA support for README
  ([`43138b1`](https://github.com/Nya-Foundation/NyaProxy/commit/43138b1de25e8b39d7b663c57489460b75250fa4))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`d0b4ec9`](https://github.com/Nya-Foundation/NyaProxy/commit/d0b4ec999c1f27e885cb532b1a8de6b3c9646faf))


## v0.4.3 (2025-06-25)

### Bug Fixes

- Fix lb strategy bug
  ([`9be7f8e`](https://github.com/Nya-Foundation/NyaProxy/commit/9be7f8e4088c371bf1df743a4e65d8ed841b7da5))


## v0.4.2 (2025-06-25)

### Bug Fixes

- Code refactor, refine code comment, and update README.md file
  ([`960dfb0`](https://github.com/Nya-Foundation/NyaProxy/commit/960dfb0e1d0cc44f1bb074e550c131d0f8df3117))

- Remove brotli dependency
  ([`9b578dc`](https://github.com/Nya-Foundation/NyaProxy/commit/9b578dc2abdbd061d8e939d365437cd16d87dc8f))

### Chores

- Black code formating
  ([`b8dad84`](https://github.com/Nya-Foundation/NyaProxy/commit/b8dad84ff23229d0ae56a2bc0303e2bb4ac04e18))


## v0.4.1 (2025-06-23)

### Bug Fixes

- Add path filtering and method filtering
  ([`da9a67c`](https://github.com/Nya-Foundation/NyaProxy/commit/da9a67c805edff30693169be32c272c1a321dc75))


## v0.4.0 (2025-06-23)

### Bug Fixes

- Add js-yaml
  ([`88d5ec1`](https://github.com/Nya-Foundation/NyaProxy/commit/88d5ec15cc1497f386e6fa93421fc14eed096201))

- Adjust backend API url
  ([`3866e0a`](https://github.com/Nya-Foundation/NyaProxy/commit/3866e0a6ab1518b39f9cddcce873a61f6e4c41dd))

- Improve encode/decode handling logic
  ([`6ad75a9`](https://github.com/Nya-Foundation/NyaProxy/commit/6ad75a9ee3d521ad54f10450ac547c2a2adf7bb0))

- Type error
  ([`2afdb2e`](https://github.com/Nya-Foundation/NyaProxy/commit/2afdb2eab73eecd6b66936d0c49066d23cf7c437))

### Chores

- Add manualChunks
  ([`b11a1e4`](https://github.com/Nya-Foundation/NyaProxy/commit/b11a1e40948ee6663237505edc9642e8d8242db7))

- Black code formating
  ([`16c3abd`](https://github.com/Nya-Foundation/NyaProxy/commit/16c3abd5950b6bd2b37ea95618a7664bc96ebae8))

- Formatting
  ([`d95dda6`](https://github.com/Nya-Foundation/NyaProxy/commit/d95dda6072846b940834f3b3c830857f6c94b85e))

- Layout finish
  ([`745c82f`](https://github.com/Nya-Foundation/NyaProxy/commit/745c82f1e1830284f592521215e932428d346ca8))

- Minor changes on error handling
  ([`fd880d6`](https://github.com/Nya-Foundation/NyaProxy/commit/fd880d6023d7d95e6f2a407859860e0bdc4be2fd))

- Resolve merge
  ([`ef0afeb`](https://github.com/Nya-Foundation/NyaProxy/commit/ef0afebc0b307a5d23fb0f09e710858b0671069d))

- Update README.md and images
  ([`a971753`](https://github.com/Nya-Foundation/NyaProxy/commit/a971753eeed2fe5f5cb58cbbe9c76fecca555a75))

- **format**: Apply automatic formatting [skip ci]
  ([`0e85be6`](https://github.com/Nya-Foundation/NyaProxy/commit/0e85be62bc73d0893a501a3e9d4bbb60c795e3b1))

- **format**: Apply automatic formatting [skip ci]
  ([`8d95f6e`](https://github.com/Nya-Foundation/NyaProxy/commit/8d95f6e167eba14547fe9d6a91399f5cf38934f7))

- **format**: Apply automatic formatting [skip ci]
  ([`6a81c8d`](https://github.com/Nya-Foundation/NyaProxy/commit/6a81c8ddfd6304a0527d98dce3e665939429a402))

- **format**: Apply automatic formatting [skip ci]
  ([`cf57feb`](https://github.com/Nya-Foundation/NyaProxy/commit/cf57feb899f3a5a58c0f9e67156e7d6b3296ae42))

### Features

- According config.yaml generate .env.production
  ([`06b4179`](https://github.com/Nya-Foundation/NyaProxy/commit/06b4179dc7cc15e7d04ca0a87c6aeec98eb6ec37))

- Login&404
  ([`95dd9dc`](https://github.com/Nya-Foundation/NyaProxy/commit/95dd9dccd8970244398f6165023f396de17c1085))

### Refactoring

- Config page layout
  ([`2643c92`](https://github.com/Nya-Foundation/NyaProxy/commit/2643c92be36cabb747088382503784f02cf733d1))

- Dashboard
  ([`53ec6b2`](https://github.com/Nya-Foundation/NyaProxy/commit/53ec6b25e0bd6944636a7c78cd4463538b979338))

- Embedded config page
  ([`87d731c`](https://github.com/Nya-Foundation/NyaProxy/commit/87d731ca2be3a4f764be2a7a6b963c638544fff8))

- Frontend init
  ([`f6bd416`](https://github.com/Nya-Foundation/NyaProxy/commit/f6bd416487122ffcd044c0e900bd51740ba7c4fd))


## v0.3.6 (2025-06-07)

### Bug Fixes

- Fix security issues by bumping python version, add support for ip_rate_limit, user_rate_limit, and
  randomness
  ([`b714a39`](https://github.com/Nya-Foundation/NyaProxy/commit/b714a396fb3a0fd2c73329778a37818d17d69437))


## v0.3.5 (2025-06-06)

### Bug Fixes

- Remove uvicorn 'optimition'
  ([`df112b8`](https://github.com/Nya-Foundation/NyaProxy/commit/df112b813cd7342c253f9afea4f92eff500ff83b))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`7088dd6`](https://github.com/Nya-Foundation/NyaProxy/commit/7088dd6c5c1917c4064bd27f038f55055aae6fb5))

- **format**: Apply automatic formatting [skip ci]
  ([`47d7af7`](https://github.com/Nya-Foundation/NyaProxy/commit/47d7af703d0ead7627413253ef94afd161314d87))


## v0.3.4 (2025-06-04)

### Bug Fixes

- Config nekoconf integration issue, add shutdown logging
  ([`29d7a47`](https://github.com/Nya-Foundation/NyaProxy/commit/29d7a47ea42fc7480f954cc23cf10d8f86aa35eb))


## v0.3.3 (2025-06-03)

### Bug Fixes

- Fix content-encoding/accept encoding issue when dealing with streamed request
  ([`817e9b6`](https://github.com/Nya-Foundation/NyaProxy/commit/817e9b6d3f39e6cdf2566da65336fd534e4e2bca))


## v0.3.2 (2025-06-02)

### Bug Fixes

- Refined and optimized request queue, update config settings and schema, performce optimization
  ([`6e347ff`](https://github.com/Nya-Foundation/NyaProxy/commit/6e347ff1bd4b7e345deb7018276aa0eff1a9b323))

### Chores

- Black format
  ([`6e87482`](https://github.com/Nya-Foundation/NyaProxy/commit/6e87482be10b5769d04895d388543ba8eb851942))

- **format**: Apply automatic formatting [skip ci]
  ([`459c671`](https://github.com/Nya-Foundation/NyaProxy/commit/459c67184668bc588ac545f199e15dd55c5c278b))

- **format**: Apply automatic formatting [skip ci]
  ([`707320f`](https://github.com/Nya-Foundation/NyaProxy/commit/707320f861f14a53621573a618d9f303659c7e48))


## v0.3.1 (2025-06-02)

### Bug Fixes

- Request_body_substitution logic refinement
  ([`b25ca72`](https://github.com/Nya-Foundation/NyaProxy/commit/b25ca7289fbee103041b62cc622529f624a188be))


## v0.3.0 (2025-06-02)

### Features

- Major refactor and architecture re-design, simplify workflow, improve throughput
  ([`d24ff13`](https://github.com/Nya-Foundation/NyaProxy/commit/d24ff131058ad5c6f50029c6b00aa89783dae941))


## v0.2.5 (2025-05-31)

### Bug Fixes

- Bump nekoconf version to 1.1.1
  ([`c239589`](https://github.com/Nya-Foundation/NyaProxy/commit/c23958954b6b39d97e34e490d281df8019872caf))


## v0.2.4 (2025-05-31)

### Bug Fixes

- Add logic to exclude Cloudflare headers
  ([`172cca3`](https://github.com/Nya-Foundation/NyaProxy/commit/172cca3224369625558e6bf11092ee9bbd532955))

- Bump nekoconf version to 1.1.0, remove simulated streaming, add loguru for logging, add support
  for python 3.10
  ([`2043c0f`](https://github.com/Nya-Foundation/NyaProxy/commit/2043c0f3f1bca878b53e448126d76a85655c1331))

### Chores

- Black code format
  ([`61a8707`](https://github.com/Nya-Foundation/NyaProxy/commit/61a8707ad08601f0fe70225904a6470369c5c388))

### Documentation

- Update README.md
  ([`4986383`](https://github.com/Nya-Foundation/NyaProxy/commit/498638336138489908bc1db6d690a87bb4dd2f32))


## v0.2.3 (2025-05-12)

### Bug Fixes

- Fix header processing issue, implement OPTIONS request hijack
  ([`9ad3902`](https://github.com/Nya-Foundation/NyaProxy/commit/9ad3902c9299067a07f4b7c687d8824f5cad580a))


## v0.2.2 (2025-05-12)

### Bug Fixes

- Add cors config support
  ([`f496918`](https://github.com/Nya-Foundation/NyaProxy/commit/f496918d7248ede8ac22754488f3c9a49a95255d))


## v0.2.1 (2025-05-09)

### Bug Fixes

- Patch config ui not save issue, update dashboard and login page logo
  ([`bb01039`](https://github.com/Nya-Foundation/NyaProxy/commit/bb010396e63bb8d7c9e7814a32aad77d1a5b0f3a))

### Chores

- Add PyPI stats
  ([`61681a9`](https://github.com/Nya-Foundation/NyaProxy/commit/61681a98ae5123391ba421c8f38adc72e8f55862))

### Documentation

- Add DeepWiki badge
  ([`a85d88d`](https://github.com/Nya-Foundation/NyaProxy/commit/a85d88dd16300e070b880ebcff0a4824499a5baf))

- Update python version requirements
  ([`b3110e5`](https://github.com/Nya-Foundation/NyaProxy/commit/b3110e54bed39e7d8ffae9a0c1163335b810b356))

- Update README.md
  ([`4346954`](https://github.com/Nya-Foundation/NyaProxy/commit/43469542c91f46947b63a37da4b67fa2a9e6294a))


## v0.2.0 (2025-05-08)

### Bug Fixes

- Upload missing folder... fix test cases
  ([`888356f`](https://github.com/Nya-Foundation/NyaProxy/commit/888356f237e88ad569ea4e26cf3240c5cbef1606))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`dc40648`](https://github.com/Nya-Foundation/NyaProxy/commit/dc40648f66a90c66d1af8df675ade20aaf851edc))

### Features

- Major refactor, support remote config server for central management, drop python 3.9-3.10 support
  ([`546b5c6`](https://github.com/Nya-Foundation/NyaProxy/commit/546b5c60cf19137c7b2c7b32f43c5ba180f85293))


## v0.1.3 (2025-05-03)

### Bug Fixes

- Decompressing logic, bump nekoconf version 0.1.11
  ([`bf89242`](https://github.com/Nya-Foundation/NyaProxy/commit/bf892425864195e05bfa759ad7c4a7cb52de397b))


## v0.1.2 (2025-05-01)

### Bug Fixes

- Fix decompressing logic
  ([`07efb41`](https://github.com/Nya-Foundation/NyaProxy/commit/07efb4125a9ac5fb931b843f7c5b564dd00576c8))


## v0.1.1 (2025-05-01)

### Bug Fixes

- Tune content-encoding logic... attempting to support complex env such as... behindng cloudfare
  proxy -> nginx -> docker
  ([`d2f96be`](https://github.com/Nya-Foundation/NyaProxy/commit/d2f96bedc280398d07d53e2c89fde87f841d400a))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`2d4695c`](https://github.com/Nya-Foundation/NyaProxy/commit/2d4695c4fbe155ed5c5ad40de37b1f1950a56f5a))

- **format**: Apply automatic formatting [skip ci]
  ([`7609dcb`](https://github.com/Nya-Foundation/NyaProxy/commit/7609dcb5c502d87251827c95a3a22c44b89160d4))

### Documentation

- Add doc for docker and pip deployment
  ([`74f8881`](https://github.com/Nya-Foundation/NyaProxy/commit/74f8881550e13935a842b6870e82295196f07006))


## v0.1.0 (2025-04-30)

### Features

- **key**: Multi api_key support, refine README, more test cases
  ([`77f3748`](https://github.com/Nya-Foundation/NyaProxy/commit/77f3748a0a0131d6ac31e8e258afbc4379b8ae4a))


## v0.0.8 (2025-04-30)

### Bug Fixes

- **test**: Fix some minor issue on f-string escpate sequence for backward compatiblities
  ([`c89f862`](https://github.com/Nya-Foundation/NyaProxy/commit/c89f862ea2b5eaccd06a4a08ffcad181a0e7afe4))

### Chores

- **CI**: Remove python 3.14 from unit tests workflow
  ([`1b9468d`](https://github.com/Nya-Foundation/NyaProxy/commit/1b9468d4cad239b9801d672fb00e2621b10ae891))

- **format**: Apply automatic formatting [skip ci]
  ([`c034383`](https://github.com/Nya-Foundation/NyaProxy/commit/c03438366743837866805df0732c1f419e3d5046))

- **README**: Update one-click deploy for Railway
  ([`88bf6b4`](https://github.com/Nya-Foundation/NyaProxy/commit/88bf6b40a2fee015ec430292d2d3212a8e4235df))


## v0.0.7 (2025-04-28)

### Bug Fixes

- Docker startup issue, add one click deploy via render and Railway
  ([`ec6ecae`](https://github.com/Nya-Foundation/NyaProxy/commit/ec6ecae75a4ebca061f40c10525a1dbc998df3af))

### Chores

- **README**: Refine README.md
  ([`053733e`](https://github.com/Nya-Foundation/NyaProxy/commit/053733e238a828976c466a3cb765a322237de093))


## v0.0.6 (2025-04-28)

### Bug Fixes

- **NekoConf**: Bump NekoConf version, refine integration, refine reload logic
  ([`32bc8f2`](https://github.com/Nya-Foundation/NyaProxy/commit/32bc8f2b494115ed91e45a48e2e6fa23a958f3ae))

### Chores

- **CI**: Adjust publish.yml
  ([`56e3f02`](https://github.com/Nya-Foundation/NyaProxy/commit/56e3f0272e4fbe752486faa0cfb13c56355d79ed))

- **CI**: Fix package version #
  ([`0860737`](https://github.com/Nya-Foundation/NyaProxy/commit/0860737c62d8dd4536836f313192b8d86e275e05))

- **format**: Apply automatic formatting [skip ci]
  ([`567c517`](https://github.com/Nya-Foundation/NyaProxy/commit/567c5172f4dd7568db6011a54c922bb8e3b8cbff))

- **format**: Apply automatic formatting [skip ci]
  ([`0109179`](https://github.com/Nya-Foundation/NyaProxy/commit/0109179df2052ca6eeb43879423ce36ef169e822))

- **version**: Bump verion to 0.0.5
  ([`0762eb7`](https://github.com/Nya-Foundation/NyaProxy/commit/0762eb7eb57f21543b2a6bbbb767d392c011e5d0))


## v0.0.5 (2025-04-27)

### Bug Fixes

- Move config.yaml and schema.json into the build folder.. fix build issue
  ([`69fff5b`](https://github.com/Nya-Foundation/NyaProxy/commit/69fff5bfeb079e13cbaba999c2d07a4cf5bd57e6))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`5ad007c`](https://github.com/Nya-Foundation/NyaProxy/commit/5ad007c6f1f7e2ee5b02329a644f5ac8af5851c2))

- **README**: Fix README error
  ([`0b1c4b2`](https://github.com/Nya-Foundation/NyaProxy/commit/0b1c4b21c623b61a0e24227b52811f3c6e13c099))

- **README**: Update README.md user guide
  ([`3b1b05c`](https://github.com/Nya-Foundation/NyaProxy/commit/3b1b05c755e78e1b85139999a7d8b37c155cff1e))


## v0.0.4 (2025-04-27)

### Bug Fixes

- Adjust image size
  ([`9d4386a`](https://github.com/Nya-Foundation/NyaProxy/commit/9d4386affd4b5407df0a1860df047eb690382189))

### Chores

- **README**: Update README.md file, add project banner image, update discord link, fix pypi upload,
  bump version to v0.0.4
  ([`d9a70ee`](https://github.com/Nya-Foundation/NyaProxy/commit/d9a70ee546811b2336de81c63dccbf438d1d6a5f))


## v0.0.3 (2025-04-27)


## v0.0.2 (2025-04-27)


## v0.0.1 (2025-04-27)

### Bug Fixes

- Fix broken stream request, response encoding handling; feature: add Ignore path config logic,
  exclue certain path from being record as key usage rate and limit exclusion
  ([`d31553e`](https://github.com/Nya-Foundation/NyaProxy/commit/d31553e86e7d2581f109787257bd2262eb33fac4))

- Resolve conflict
  ([`187d23a`](https://github.com/Nya-Foundation/NyaProxy/commit/187d23a566cfb3751985b6cb9a7c1c88b419c2db))

- Resolve conflict
  ([`2bd8457`](https://github.com/Nya-Foundation/NyaProxy/commit/2bd8457f9143f07a27b67be6cc1abee3337124e9))

- **ci**: Ad step to upload pypi, fix dependency-review.yml, bump version to v0.0.3
  ([`ecc50d9`](https://github.com/Nya-Foundation/NyaProxy/commit/ecc50d955ad8f5f39b577e359b258f183fb13bc2))

- **ci**: Fix pyproject.toml [dev] optional-dependencies
  ([`cdf6978`](https://github.com/Nya-Foundation/NyaProxy/commit/cdf6978bd739011760c58c71bac1bc9db26ef8cf))

- **ci**: Fix test.yml pytest issue
  ([`6a46b12`](https://github.com/Nya-Foundation/NyaProxy/commit/6a46b12e8ddd46e751e62ea43b4ee4c987aa0acd))

- **major**: Retry config consolidation, retry logic handling, metrics timeout issue, rate limit
  queue fix
  ([`4bb2773`](https://github.com/Nya-Foundation/NyaProxy/commit/4bb277337b3b49b0331050d89055365b4e7ba69a))

- **security**: Remediate 2 critial vulnerabilities, optimize Dockerfil, reduce image size with
  Alpine, fix config_path priority issue, fix pypi upload logic in ci, fix pyproject.toml format
  issue
  ([`ba1f338`](https://github.com/Nya-Foundation/NyaProxy/commit/ba1f33894acaa2a60256c1463cf94e2d0923168c))

### Chores

- **format**: Apply automatic formatting [skip ci]
  ([`9829453`](https://github.com/Nya-Foundation/NyaProxy/commit/98294531c352f2fc72fb6f4dbd3f6303f27c5cdc))
