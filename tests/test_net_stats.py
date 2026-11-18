"""Сводка сети онлайн-матча (NetStats): каждая сторона отправляет свою вместе с матчем через bdm_sync.
1. Без сети (?net=local): хозяин и гость доигрывают партию, обе стороны шлют матч со своей сводкой (r h / g),
   номер матча в соединении растёт, сводка короче 1500 байт, после отправки очередь сводок пустая.
2. Настоящий PeerJS и настоящий ретранслятор Cloudflare (ключи из функции turn): гостю оставлен только ретранслятор.
   В сводке путь relay-udp у гостя и …>relay-udp у хозяина, пинг соединения из getStats.
   Если функция turn недоступна, часть 2 пропускается с пометкой.
Supabase подменён, в базу ничего не пишется (функция turn только выдаёт ключи)."""
import json
from _util import sync_playwright, BASE, launch, sign_up

TURN_URL = 'https://ktpeclypxevbfwtvuwbi.supabase.co/functions/v1/turn'
KEY = 'sb_publishable_zydu8BCg0hb0x92Vh0e1uQ_oMIMObKn'
syncs = []  # (pid, матч) из всех вызовов bdm_sync


def fake(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'], 'mode': 'new'}))
    if '/rpc/bdm_sync' in u:
        b = json.loads(req.post_data)
        for m in b.get('p_matches') or []: syncs.append((b['p_pid'], m))
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'saved': 0, 'skipped': []}))
    if '/rpc/' in u: return route.fulfill(status=200, content_type='application/json', body='{"ok":true}')
    return route.fulfill(status=200, content_type='application/json', body='[]')


def nets(match_id):
    return {pid: m['net'] for pid, m in syncs if m['id'] == match_id and 'net' in m}


def finish(H, G):
    """Хозяин доигрывает партию за пару секунд: ИИ за него, счёт 6:0. Ждём, пока матч дойдёт до гостя и обе стороны отправят его."""
    H.evaluate("() => { const b = __bdm; b.P[0].ai = { diff: 'hard' }; b.game.score[0] = b.game.target - 1; }")
    for _ in range(80):
        H.evaluate("() => __bdm.fastForward(2)")
        if H.evaluate("() => __bdm.game.state") == 'over': break
    H.evaluate("() => { __bdm.P[0].ai = null; }")
    assert H.evaluate("() => __bdm.game.state") == 'over', 'партия не закончилась'
    mid = H.evaluate("() => __bdm.store.recs.filter(r => r.k === 'net').slice(-1)[0].id")
    for _ in range(40):
        H.wait_for_timeout(250)
        got = nets(mid)
        if len(got) == 2: break
    return mid


def connect(H, G):
    H.click('#netHost'); H.wait_for_selector('.net-status .code', timeout=20000)
    code = H.inner_text('.net-status .code').strip()
    G.fill('#netCode', code); G.click('#netJoin')
    G.wait_for_function('() => __bdm.Net.connected', timeout=25000); H.wait_for_function('() => __bdm.Net.connected', timeout=25000)
    G.wait_for_function("() => __bdm.game.mode === 'online'", timeout=5000)


errs = []
with sync_playwright() as pw:
    br = launch(pw)

    def pages(ctx, a, b, script_a=None, script_b=None, local=True):
        out = []
        for slot, name, sc in ((a, 'Хост', script_a), (b, 'Гость', script_b)):
            pg = ctx.new_page(); pg.on('pageerror', lambda e, n=name: errs.append(n + ': ' + str(e)))
            if sc: pg.add_init_script(sc)
            pg.goto(BASE + ('?net=local&' if local else '?') + f'p={slot}'); out.append(pg)
        out[0].wait_for_timeout(900)
        sign_up(out[0], 'Хост'); sign_up(out[1], 'Гость')
        if not local:
            for pg in out: pg.wait_for_function('() => window.Peer', timeout=15000)
        return out

    # 1. Без сети
    ctx = br.new_context(viewport={'width': 1000, 'height': 600}); ctx.route('**/*supabase.co/**', fake)
    H, G = pages(ctx, 7, 8)
    connect(H, G)
    H.wait_for_timeout(2500)
    hp, gp = H.evaluate('() => __bdm.profile.pid'), G.evaluate('() => __bdm.profile.pid')
    m1 = finish(H, G)
    s = nets(m1)
    assert set(s) == {hp, gp}, f'матч со сводкой прислали обе стороны: {list(s)}'
    h, g = s[hp], s[gp]
    print('хозяин:', json.dumps(h, ensure_ascii=False)); print('гость: ', json.dumps(g, ensure_ascii=False))
    assert h['r'] == 'h' and g['r'] == 'g' and h['n'] == g['n'] == 1 and h['v'] == 1
    assert h['path'] == g['path'] == 'local' and h['sw'] == [[0, 'local']], 'путь без сети — local'
    for x in (h, g):
        assert x['dur'] >= 2 and 0 <= x['ct'] < 5000, x
        assert x['rx'] >= 20 and x['fps'] >= 20, f'темп сообщений и кадров: {x}'
        assert x['png'] and 0 < x['png'][0] <= x['png'][1] <= x['png'][2] < 1000, f'пинг из игры: {x}'
        assert x['ice'] is None and x['hid'] == 0 and x['ua'].startswith('mac chrome'), x
        assert len(json.dumps(x, ensure_ascii=False).encode()) < 1500, 'сводка влезает в net_stats'
    assert H.evaluate('() => Object.keys(__bdm.store.net).length') == 0 and G.evaluate('() => Object.keys(__bdm.store.net).length') == 0, 'после отправки сводки не копятся'
    # реванш в том же соединении — второй матч, окно с конца первого
    G.click('#again'); H.wait_for_function("() => __bdm.game.state !== 'over'", timeout=5000)
    H.wait_for_timeout(1500)
    m2 = finish(H, G)
    s2 = nets(m2)
    assert s2[hp]['n'] == 2 and s2[gp]['n'] == 2, f'второй матч в соединении: {s2}'
    assert s2[hp]['dur'] < h['dur'] + 30, 'окно второго матча — с конца первого'
    ctx.close()

    # 2. Настоящий PeerJS и ретранслятор Cloudflare
    api = pw.request.new_context()
    try:
        res = api.post(TURN_URL, headers={'apikey': KEY, 'Origin': 'http://127.0.0.1:8765'}, timeout=8000)
        ice = res.json().get('iceServers') if res.ok else None
    except Exception:
        ice = None
    api.dispose()
    if not ice:
        print('ПРОПУЩЕНО: функция turn не ответила, часть 2 (ретранслятор) не проверена')
    else:
        base = """(() => { const O = window.RTCPeerConnection, ICE = %s;
          window.RTCPeerConnection = function (c) { return new O({ ...(c || {}), iceServers: ICE%s }); };
          window.RTCPeerConnection.prototype = O.prototype; })();""" % (json.dumps(ice), '%s')
        ctx = br.new_context(viewport={'width': 1000, 'height': 600}); ctx.route('**/*supabase.co/**', fake)
        H, G = pages(ctx, 4, 5, base % '', base % ", iceTransportPolicy: 'relay'", local=False)
        connect(H, G)
        H.wait_for_timeout(4000)
        hp, gp = H.evaluate('() => __bdm.profile.pid'), G.evaluate('() => __bdm.profile.pid')
        m3 = finish(H, G)
        s3 = nets(m3)
        assert set(s3) == {hp, gp}, f'сводки обеих сторон: {list(s3)}'
        h, g = s3[hp], s3[gp]
        print('ретранслятор, хозяин:', json.dumps(h, ensure_ascii=False)); print('ретранслятор, гость: ', json.dumps(g, ensure_ascii=False))
        # Chrome иногда выбирает ретранслятор по TCP, даже когда UDP доступен (18.11: 1 прогон из 5) — путь пишется любой
        assert g['path'].split('>')[0] in ('relay-udp', 'relay-tcp', 'relay-tls'), f'у гостя путь через ретранслятор: {g["path"]}'
        assert h['path'].endswith('>relay-udp'), f'хозяин видит ретранслятор гостя: {h["path"]}'
        for x in (h, g):
            assert x['ice'] and 0 < x['ice'][0] < 500, f'пинг соединения из getStats: {x}'
            assert 0 < x['ct'] < 15000, f'время соединения: {x}'
        ctx.close()
    br.close()

assert not [e for e in errs if 'Failed to load resource' not in e], errs
print('OK: сводка сети уходит с матчем')
