"""Вход в комнату через лобби «Ждут соперника», настоящий PeerJS (нужен интернет), Supabase подменён.
1. После нажатия «Играть» карточка не прыгает: под курсором не оказывается «Создать комнату» (широкий и средний экран).
2. Двойной клик по комнате — входишь гостем, а не создаёшь свою комнату.
3. Двое жмут одну комнату одновременно — входит один, второй быстро слышит «уже играют двое», а не висит 15 с.
4. Лобби с тем же списком не перерисовывается: кнопка под курсором не подменяется."""
import datetime, json, time
from _util import sync_playwright, BASE, launch, sign_up

ROOM = {}


def fake(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'], 'mode': 'new'}))
    if '/rest/v1/rooms' in u and req.method == 'GET':
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return route.fulfill(status=200, content_type='application/json', body=json.dumps([dict(r, updated_at=now) for r in ROOM.values()]))
    return route.fulfill(status=200, content_type='application/json', body='{"ok":true}' if '/rpc/' in u else '[]')


errs = []
with sync_playwright() as pw:
    br = launch(pw)

    def page(slot, name, width=1100):
        ctx = br.new_context(viewport={'width': width, 'height': 760}); ctx.route('**/*supabase.co/**', fake)
        pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(f'{name}: {e}'))
        pg.goto(f'{BASE}?p={slot}'); pg.wait_for_timeout(700); sign_up(pg, name)
        pg.wait_for_function('() => window.Peer', timeout=15000)
        return pg

    def host(name='Jason'):
        ROOM.clear()
        H = page(1, name)
        H.click('#netHost'); H.wait_for_selector('.net-status .code', timeout=15000)
        code = H.inner_text('.net-status .code').strip()
        ROOM[code] = {'code': code, 'host_pid': H.evaluate('() => __bdm.profile.pid'), 'host_name': name, 'status': 'open'}
        return H, code

    def state(pg):
        return pg.evaluate("() => ({ conn: __bdm.Net.connected, role: __bdm.Net.role, st: document.getElementById('netStatus').innerText })")

    def wait_conn(pg, secs=12):
        t0 = time.time()
        while time.time() - t0 < secs:
            if state(pg)['conn']: return True
            pg.wait_for_timeout(300)
        return False

    def bye(*pgs):
        for p in pgs: p.context.close()

    # 1. Карточка не прыгает, на двух ширинах
    for width in (1100, 800):
        H, code = host(); K = page(2, 'Kirill', width); K.wait_for_selector('.lobby-item', timeout=12000)
        before = K.evaluate("() => ['.lobby-item', '#netHost', '#netJoin'].map(s => document.querySelector(s).getBoundingClientRect().top)")
        bb = K.locator('.lobby-item').bounding_box(); x, y = bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2
        K.mouse.click(x, y); K.wait_for_timeout(150)
        assert 'Подключаемся' in state(K)['st'], state(K)
        under = K.evaluate('([x, y]) => document.elementFromPoint(x, y).closest("button").className', [x, y])
        assert under == 'lobby-item', f'{width}px: после клика под курсором {under}, а не комната'
        after = K.evaluate("() => ['.lobby-item', '#netHost', '#netJoin'].map(s => document.querySelector(s).getBoundingClientRect().top)")
        assert all(abs(a - b) < 1 for a, b in zip(before, after)), f'{width}px: карточка сдвинулась {before} → {after}'
        assert wait_conn(K), f'{width}px: не вошёл через лобби: {state(K)}'
        bye(H, K)

    # 2. Двойной клик
    H, code = host(); K = page(2, 'Kirill'); K.wait_for_selector('.lobby-item', timeout=12000)
    K.dblclick('.lobby-item')
    K.wait_for_timeout(300); s = state(K)
    assert s['role'] == 'guest', f'двойной клик сделал из гостя хозяина: {s}'
    assert wait_conn(K), f'после двойного клика не вошёл: {state(K)}'
    bye(H, K)

    # 3. Двое жмут одновременно
    H, code = host(); K = page(2, 'Kirill'); T = page(3, 'Тим')
    K.wait_for_selector('.lobby-item', timeout=12000); T.wait_for_selector('.lobby-item', timeout=12000)
    for pg in (K, T): pg.evaluate("() => setTimeout(() => document.querySelector('.lobby-item').click(), 400)")
    t0 = time.time(); res = None
    while time.time() - t0 < 9:
        time.sleep(0.3)
        k, t = state(K), state(T)
        busy = [n for n, s in (('Kirill', k), ('Тим', t)) if 'играют двое' in s['st']]
        inn = [n for n, s in (('Kirill', k), ('Тим', t)) if s['conn']]
        if len(busy) == 1 and len(inn) == 1: res = (inn[0], busy[0], round(time.time() - t0, 1)); break
    assert res, f'гонка: за 9 с нет «один вошёл, второй занято»: Kirill {state(K)} · Тим {state(T)}'
    H.wait_for_timeout(1000)
    assert H.evaluate('() => __bdm.Net.connected && __bdm.game.mode') == 'online', 'хост играет'
    print(f'гонка: вошёл {res[0]}, {res[1]} узнал «занято» через {res[2]} с')
    bye(H, K, T)

    # 4. Тот же список — та же кнопка
    ROOM.clear(); ROOM['QWER'] = {'code': 'QWER', 'host_pid': 'abcdef12', 'host_name': 'Jason', 'status': 'open'}
    K = page(2, 'Kirill'); K.wait_for_selector('.lobby-item', timeout=12000)
    K.evaluate("() => { document.querySelector('.lobby-item').__mark = 1; }")
    K.wait_for_timeout(5600)
    assert K.evaluate("() => document.querySelector('.lobby-item').__mark === 1"), 'лобби перерисовалось без изменений'
    ROOM['ABCD'] = {'code': 'ABCD', 'host_pid': 'abcdef34', 'host_name': 'Arkady', 'status': 'open'}
    K.wait_for_timeout(5600)
    assert K.evaluate("() => [...document.querySelectorAll('.lobby-item .ln')].map(e => e.textContent).join()") == 'Arkady,Jason', 'порядок по имени'
    bye(K)
    br.close()

assert not errs, errs
print('OK: лобби — карточка не прыгает, двойной клик и гонка двоих')
