# Public deployment: GitHub Pages + Colab API

## Architecture and publication

The browser loads only static assets from GitHub Pages and sends chess positions to a separate HTTPS API. For the existing repository the expected website is `https://cristopherbaca.github.io/Chess/`. The browser Origin is **`https://cristopherbaca.github.io`**, with no repository path. `WEBSITE_ORIGINS` defaults to `*`, so the API accepts requests from any website origin, including local development and non-GitHub domains. You may optionally set exact origins to restrict callers.

[GitHub's Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) describes selecting Actions as the publishing source. The repository includes a **manual** `Publish Chess website` workflow. Supply the API URL from the deployment notebook. The build copies only approved frontend file types/directories into `_site/`, injects that public URL, and restricts `connect-src` to its origin. Notebook source, training modules, weights, tests, environment files and `.git` are excluded. Actions are pinned to commit hashes and the build job has read-only repository permissions; only the deployment job receives Pages/OIDC write permissions. No repository credentials are persisted by checkout.

The URL is public and needs no secret. Never add `API_ADMIN_TOKEN`, ngrok tokens, Drive credentials or model files to the workflow input or browser code. A public Git repository still exposes committed source files even when its Pages artifact excludes them. Review notebook outputs before committing; both distributed notebooks should remain free of runtime outputs. Enable [HTTPS in Pages settings](https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https).

The workflow is prepared, not remotely enabled or deployed. Push reviewed changes, select GitHub Actions under Settings → Pages, then run it. When a temporary tunnel changes URL, publish again with the new URL. Local development still permits configuring another HTTPS endpoint; the published artifact allows only its configured API origin.

## Implemented protections

| Area | Behavior |
| --- | --- |
| Browser origins | Default `*` permits any origin, including opaque (`null`) origins, without credentialed CORS. Optional exact-origin restrictions remain available. Methods GET/POST and request headers stay explicit. |
| Request bodies | JSON only; maximum 16 KiB, including chunked streams; five-second body-read deadline; compressed bodies rejected. |
| Input schema | Valid six-field FEN, maximum 200 characters; at most 1,024 UCI history entries of 4–5 characters; legal history replay and matching final position; fixed difficulty choices; unknown fields rejected. |
| Request budgets | Per client: 120 requests/minute with burst 30 and 20 move requests/minute with burst 4. Global: 600 requests/minute with burst 60 and 60 moves/minute with burst 8. Token buckets return 429 and Retry-After. |
| Client identity | Cloudflare visitor header is trusted only in Cloudflare mode from a loopback socket. Uvicorn proxy-header rewriting is disabled. Other forwarded headers are ignored. IPv6 clients share a /64 budget. In ngrok mode clients conservatively share the tunnel peer's budget. |
| Limiter memory | At most 4,096 client records; inactive records expire after two minutes. A full live table rejects new identities instead of evicting active clients and resetting quotas. |
| AI resource admission | At most two submitted searches: one engine call and at most one waiter. Additional calls receive 503/Retry-After. Admission is held until the actual worker finishes, including after HTTP timeout or disconnect. |
| Search caps | Easy 2 s, medium 4 s, hard 6 s. Existing engine budgets are clamped, not increased. Legal output and finite score checks remain. A native Torch/NumPy call cannot be forcibly interrupted by a Python deadline; its slot/lock remain occupied until completion. |
| Private diagnostics | `/stats` requires a random 256-bit runtime-only bearer token. No token is printed or sent to public players. Inspect `API_COUNTERS`, `API_LOG` or `API_POLICY.snapshot()` inside Colab. Only 50 bounded move-log entries are kept in memory. |
| API exposure | Loopback bind behind the tunnel; docs/OpenAPI endpoints disabled; bounded connection concurrency and keep-alive; generic errors; no static-file/model download route. |
| Browser policy | External scripts only, no inline/eval script allowance; same-origin styles/images; no objects, forms or child frames; no referrer. Public builds allow connections only to their configured API. |
| API headers | No-store, nosniff, DENY framing, no-referrer and restrictive response CSP. |
| Artifact loading | Requires the new Drive folder's manifest; verifies required engine/metadata and listed file hashes, rejects path escapes/symlinks, requires declared weights in the manifest. No legacy-model fallback. |
| Tunnel binary | Cloudflare Linux amd64 release **2026.10.5**, SHA-256 **e1bc0cf084fd9e590554fe769a86b1db46701c3f847a43d902f7b974a4e16298**; verifies downloads and cached binaries before execution. Review/update the pin when upgrading. |

The controls address resource abuse described in [OWASP API4](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/). Visitor-IP handling follows [Cloudflare's header documentation](https://developers.cloudflare.com/fundamentals/reference/http-headers/). Application limits and private diagnostics are tested locally with hostile inputs; there has been no independent penetration test or public load test.

## Operating limits and remaining risks

Public `/move` is intentionally anonymous. CORS is a browser policy, **not authentication**: scripts outside a browser can forge/omit Origin. Global rate limits and bounded computation still apply, but attackers can consume the available public quota. Local users and processes within the same Colab runtime are trusted; they could spoof tunnel headers or access Drive/admin state. Do not run untrusted code in that runtime.

Cloudflare/Colab quick deployment is temporary and suitable for a small demonstration. It is not a guarantee against distributed denial of service or a substitute for persistent infrastructure. Before relying on sustained public traffic, use a separately managed API service with a dedicated limited-access model volume, provider-level rate limiting/WAF, monitoring and a stable hostname. Per-process rate state resets on restart; multiple API replicas would need a shared limiter. GitHub Pages cannot serve the Python API.

Manifest hashes detect corruption, not an attacker who can rewrite both a trusted Drive model and its manifest. The exported engine is executable Python. Keep your Google/GitHub accounts and shared Drive permissions restricted; load only artifacts produced by your own training pipeline. Deleting files from this checkout does not erase Git history or remote Drive files.

GitHub Pages does not let this repository set arbitrary response headers. The HTML meta CSP supplies the supported restrictions; `frame-ancestors` cannot be enforced through a meta tag. The API does send framing/security headers. Dependencies installed by Colab should be kept current; no claim of zero vulnerabilities is made.

## GPU population/headroom error while loading a champion

Older dense exports applied their training population's GPU-memory budget to single-model deployment. This could reject a valid saved champion when the allocator already held training tensors or other GPU allocations. It does not mean the weights are damaged or the network needs retraining.

Upload the current `vendor/deploy.ipynb` and run all again. It verifies the saved artifact first, then installs the corrected inference loader in memory, including for old exports; no saved weights, manifest or model files are rewritten. `API_DEVICE = 'auto'` loads one network on CUDA when available and falls back to CPU on CUDA allocation failure during loading or evaluation. Use `API_DEVICE = 'cpu'` to force CPU, or `'cuda'` to require GPU and report allocation failures. The selected device is printed during loading. A separate deployment runtime avoids competing with training for VRAM; do not interrupt or reset your training runtime just to deploy.

Inference loads only the layer weights and positional prior, without population perturbations or training memory/headroom admission checks. GPU allocator-wide reserved memory is not treated as this model's memory use. Training retains its existing population guards. The updated training notebook embeds the same fix for future exports; existing exports can be served with the updated deployment notebook immediately.

The local suite passes **98 tests**, including simulated CUDA OOM during loading/evaluation and loading an older failing export without modifying saved artifacts. Actual CUDA execution with your Drive weights must be verified in Colab.

## Stop, recover, inspect

Once the tunnel provides its URL, public health/move checks retry every three seconds with no attempt limit until successful. Colab interruption stops retries and closes the tunnel. Initial tunnel creation/configuration failures still report their errors; this retry loop does not suppress setup errors.

- Run `shutdown_api()` or disconnect the Colab runtime to stop access.
- Rerun deployment after exporting a new champion or changing origins.
- Observe counters inside Colab. To call `/stats` yourself, use an Authorization bearer header containing `API_ADMIN_TOKEN`; never put it in a URL or screenshot/public output.
- 429 means wait for Retry-After; 503 means both search slots are occupied; 403 means the website origin does not match configuration. The frontend does not automatically hammer retries.
- If a native call remains stuck, restart the deployment runtime. HTTP timeouts do not kill native code or unlock the engine early.
