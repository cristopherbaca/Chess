"""Bounded ASGI input handling and resource admission for the public chess API.

No application authentication secret is shipped to browsers. Origin checks limit
browser callers; global budgets also apply to clients that forge/omit Origin.
"""
import asyncio
from collections import OrderedDict
import ipaddress
import math
import threading
import time
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def allowed_origins(value):
    origins = []
    for item in value.split(','):
        item = item.strip().rstrip('/')
        if not item:
            continue
        url = urlsplit(item)
        local = url.hostname in ('localhost', '127.0.0.1', '::1')
        if (url.scheme not in (('http', 'https') if local else ('https',)) or not url.hostname
                or url.username or url.password or url.query or url.fragment or url.path
                or '*' in item):
            raise ValueError('Use exact HTTPS website origins without paths or wildcards (localhost HTTP is allowed).')
        origins.append(item)
    if not origins:
        raise ValueError('At least one website origin is required.')
    return tuple(dict.fromkeys(origins))


class PublicPolicy:
    def __init__(self, origins, *, trust_cloudflare=False, body_bytes=16384, body_seconds=5.,
                 requests_per_minute=120, request_burst=30, moves_per_minute=20, move_burst=4,
                 global_requests_per_minute=600, global_request_burst=60,
                 global_moves_per_minute=60, global_move_burst=8, max_clients=4096,
                 max_searches=2, clock=time.monotonic):
        self.origins = allowed_origins(','.join(origins))
        self.trust_cloudflare = trust_cloudflare
        self.body_bytes, self.body_seconds = body_bytes, body_seconds
        self.max_clients, self.clock = max_clients, clock
        self.rates = ((requests_per_minute/60, request_burst), (moves_per_minute/60, move_burst))
        self.global_rates = ((global_requests_per_minute/60, global_request_burst),
                             (global_moves_per_minute/60, global_move_burst))
        self.clients = OrderedDict()
        self.global_buckets = {}
        self.lock = threading.Lock()
        self.search_slots = threading.BoundedSemaphore(max_searches)
        self.counts = {'rate_limited': 0, 'busy': 0, 'oversized': 0, 'blocked_origin': 0}

    def client_key(self, scope, headers):
        peer = (scope.get('client') or ('unknown', 0))[0]
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        # Uvicorn proxy-header rewriting is disabled, and listens only on loopback.
        # Trust this header only on the explicit Cloudflare tunnel configuration.
        if self.trust_cloudflare and address.is_loopback:
            try:
                address = ipaddress.ip_address(headers.get(b'cf-connecting-ip', b'').decode('ascii'))
            except (ValueError, UnicodeError):
                pass
        if address.version == 6:
            return str(ipaddress.ip_network(f'{address}/64', strict=False))
        return str(address)

    def admit(self, key, is_move):
        now = self.clock()
        with self.lock:
            while self.clients and next(iter(self.clients.values()))['seen'] < now-120:
                self.clients.popitem(last=False)
            if key not in self.clients:
                if len(self.clients) >= self.max_clients:
                    # Never evict live clients to reset their budget under IP churn.
                    self.counts['rate_limited'] += 1
                    return 60
                self.clients[key] = {'seen': now, 'buckets': {}}
            client = self.clients[key]
            client['seen'] = now
            self.clients.move_to_end(key)
            pending, retry = [], 0
            for buckets, limits in ((client['buckets'], self.rates), (self.global_buckets, self.global_rates)):
                for index in range(2 if is_move else 1):
                    rate, burst = limits[index]
                    tokens, last = buckets.get(index, (burst, now))
                    tokens = min(burst, tokens + max(0, now-last)*rate)
                    buckets[index] = (tokens, now)
                    if tokens < 1:
                        retry = max(retry, math.ceil((1-tokens)/rate))
                    pending.append((buckets, index, tokens))
            if retry:
                self.counts['rate_limited'] += 1
                return retry
            for buckets, index, tokens in pending:
                buckets[index] = (tokens-1, now)
            return 0

    def snapshot(self):
        with self.lock:
            return dict(self.counts)


class SecurityBoundary:
    """Read at most body_bytes BEFORE JSON parsing, including chunked requests."""
    def __init__(self, app, policy):
        self.app, self.policy = app, policy

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        policy = self.policy
        headers = dict(scope['headers'])
        origin = headers.get(b'origin', b'').decode('latin1')
        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                message['headers'] = list(message.get('headers', [])) + [
                    (b'x-content-type-options', b'nosniff'), (b'x-frame-options', b'DENY'),
                    (b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer'),
                    (b'content-security-policy', b"default-src 'none'; frame-ancestors 'none'")]
            await send(message)
        async def reject(status, text, extra=None):
            response_headers = dict(extra or {})
            if origin in policy.origins:
                response_headers.update({'Access-Control-Allow-Origin': origin, 'Vary': 'Origin'})
            await JSONResponse({'error': text}, status_code=status, headers=response_headers)(scope, receive, secure_send)
        if origin and origin not in policy.origins:
            with policy.lock:
                policy.counts['blocked_origin'] += 1
            return await reject(403, 'This website origin is not allowed.')
        key = policy.client_key(scope, headers)
        retry = policy.admit(key, scope['method'] == 'POST' and scope['path'] == '/move')
        if retry:
            return await reject(429, 'Too many requests. Please wait before retrying.', {'Retry-After': str(retry)})
        if scope['method'] == 'POST' and scope['path'] == '/move':
            if headers.get(b'content-encoding', b'identity').lower() != b'identity':
                return await reject(415, 'Compressed request bodies are not accepted.')
            if headers.get(b'content-type', b'').split(b';')[0].strip().lower() != b'application/json':
                return await reject(415, 'Use application/json.')
            lengths = [v for k, v in scope['headers'] if k.lower() == b'content-length']
            try:
                size = int(lengths[0]) if lengths else 0
                if len(lengths) > 1 or size < 0:
                    raise ValueError()
            except ValueError:
                return await reject(400, 'Invalid Content-Length.')
            if size > policy.body_bytes:
                with policy.lock:
                    policy.counts['oversized'] += 1
                return await reject(413, 'Request body is too large.')
            chunks, total = [], 0
            deadline = policy.clock() + policy.body_seconds
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=max(.001, deadline-policy.clock()))
                except asyncio.TimeoutError:
                    return await reject(408, 'Request body timed out.')
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                total += len(chunk)
                if total > policy.body_bytes:
                    with policy.lock:
                        policy.counts['oversized'] += 1
                    return await reject(413, 'Request body is too large.')
                chunks.append(chunk)
                if not message.get('more_body', False):
                    break
            body, consumed = b''.join(chunks), False
            async def replay_body():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                return await receive()
            return await self.app(scope, replay_body, secure_send)
        await self.app(scope, receive, secure_send)
