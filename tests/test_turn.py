"""Ретранслятор (TURN) и честные ошибки входа, через настоящий PeerJS.
1. Функция `turn` отдала ключи — хозяин и гость создают соединения с ними (и с Google STUN), игра начинается.
2. Функция сломана (500) или молчит дольше 3 с — комната всё равно создаётся, напрямую, как раньше.
3. Сеть гостя не пускает прямое соединение, ретранслятор недоступен — через 15 с гость видит
   «ваши сети не смогли соединиться», а не «друг закрыл комнату».
Supabase подменён. Нужен интернет (сервер PeerJS)."""
import json, time
from _util import sync_playwright, BASE, launch, sign_up

FAKE_TURN = {'urls': ['turn:127.0.0.1:9?transport=udp'], 'username': 'u', 'credential': 'c'}
mode = {'turn': 'ok'}  # ok | fail
calls = []


def fake(route):
    req = route.request; u = req.url
    if '/functions/v1/turn' in u:
        calls.append(req.method)
        if mode['turn'] == 'fail':
            return route.fulfill(status=500, content_type='application/json', body='{"error":"x"}')
        return route.fulfill(status=200, content_type='application/json',
                             body=json.dumps({'iceServers': [{'urls': 'stun:stun.cloudflare.com:3478'}, FAKE_TURN], 'ttl': 21600}))
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'], 'mode': 'new'}))
    return route.fulfill(status=200, content_type='application/json', body='{"ok":true}' if '/rpc/' in u else '[]')


# Сеть без прямого пути: браузер гостя ищет только через ретранслятор, а ретранслятор недоступен
NO_DIRECT = """(() => { const O = window.RTCPeerConnection;
  window.RTCPeerConnection = function (c) { return new O({ ...(c || {}), iceServers: [FAKE], iceTransportPolicy: 'relay' }); };
  window.RTCPeerConnection.prototype = O.prototype; })();""".replace('FAKE', json.dumps(FAKE_TURN))

# Функция не отвечает вовсе
SILENT = """(() => { const f = window.fetch;
  window.fetch = (u, o) => String(u).includes('/functions/v1/turn') ? new Promise(() => {}) : f(u, o); })();"""

ICE = "() => { const p = __bdm.Net.transport && __bdm.Net.transport.peer; return p ? JSON.stringify(p.options.config.iceServers) : '' }"


def join(pg, code, wait=20):
    pg.fill('#netCode', code); pg.click('#netJoin'); t0 = time.time()
    while time.time() - t0 < wait:
        pg.wait_for_timeout(300)
        if pg.evaluate("() => __bdm.Net.connected"): return 'вошёл', time.time() - t0
        if pg.query_selector('#netStatus .err'): return pg.inner_text('#netStatus'), time.time() - t0
    return 'не вошёл', time.time() - t0


errs = []
with sync_playwright() as pw:
    br = launch(pw)

    def page(ctx, slot, name=None, script=None):
        pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(f'{slot}: {e}'))
        if script: pg.add_init_script(script)
        pg.goto(f'{BASE}?p={slot}'); pg.wait_for_timeout(900)
        if name: sign_up(pg, name)
        pg.wait_for_function('() => window.Peer', timeout=15000)
        return pg

    def host(H):
        H.click('#netHost'); t0 = time.time(); H.wait_for_selector('.net-status .code', timeout=20000)
        return H.inner_text('.net-status .code').strip(), time.time() - t0

    def ctx_new():
        c = br.new_context(viewport={'width': 1100, 'height': 640}); c.route('**/*supabase.co/**', fake); return c

    # 1. Ключи пришли
    c1 = ctx_new(); H = page(c1, 1, 'Хост'); G = page(c1, 2, 'Гость')
    assert 'POST' in calls, 'ключи берутся заранее, при загрузке'
    code, _ = host(H)
    hi = H.evaluate(ICE)
    assert '127.0.0.1:9' in hi and 'stun.l.google.com' in hi and 'stun.cloudflare.com' in hi, f'хозяин без ретранслятора: {hi}'
    r, _ = join(G, code)
    assert r == 'вошёл', f'с ключами гость: {r}'
    assert '127.0.0.1:9' in G.evaluate(ICE), 'гость без ретранслятора'
    H.wait_for_timeout(600); assert H.evaluate('() => __bdm.game.mode') == 'online'
    c1.close()

    # 2а. Функция сломана
    mode['turn'] = 'fail'; c2 = ctx_new(); H = page(c2, 1, 'Хост'); G = page(c2, 2, 'Гость')
    code, _ = host(H)
    hi = H.evaluate(ICE)
    assert 'stun.l.google.com' in hi and 'turn:' not in hi, f'без функции — только STUN: {hi}'
    r, _ = join(G, code)
    assert r == 'вошёл', f'без функции гость: {r}'
    c2.close()

    # 2б. Функция молчит: комната не ждёт дольше 3 с
    mode['turn'] = 'ok'; c3 = ctx_new(); H = page(c3, 1, 'Хост', SILENT)
    code, dt = host(H)
    assert dt < 6 and 'turn:' not in H.evaluate(ICE), f'комната создавалась {dt:.1f} с'
    c3.close()

    # 3. Сети не соединяются
    mode['turn'] = 'ok'; c4 = ctx_new(); H = page(c4, 1, 'Хост'); G = page(c4, 2, 'Гость', NO_DIRECT)
    code, _ = host(H)
    r, dt = join(G, code, 25)
    assert 'сети не смогли соединиться' in r, f'гость без прямого пути видит: {r!r} через {dt:.1f} с'
    assert H.evaluate('() => !__bdm.Net.connected && !!__bdm.Net.code'), 'комната хозяина осталась открытой'
    c4.close()
    br.close()

assert not errs, errs
print('OK: ретранслятор подключается, без функции играем напрямую, сбой сети назван честно')
