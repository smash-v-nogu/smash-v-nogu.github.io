"""Проверка живого сайта после деплоя. Локальный сервер не нужен.
1. Настоящая Supabase, но только чтение: любые не-GET запросы к ней обрываются. Общая таблица подтянулась, ошибок нет.
2. Телефон вертикально: меню без горизонтальной прокрутки.
3. Онлайн через настоящий PeerJS между двумя браузерами. Supabase здесь подменён, в базу ничего не пишется.
   Хост объявляет комнату в лобби и убирает её через bdm_room.
4. Матч против ИИ до конца (за игрока доигрывает ИИ через fastForward): экран итога, матч уходит через bdm_sync (подменённый).
5. Настоящая база закрыта на запись. Пробы безвредны: строки заведомо кривые, фильтры ни с чем не совпадают,
   id в функциях выдуманный, так что даже открытая база ничего бы не записала.
LIVE_URL — другой адрес сайта. Скриншоты кладутся в SHOTS, если задан."""
import json, os, time
from _util import sync_playwright, launch, sign_up

LIVE = os.environ.get('LIVE_URL', 'https://smash-v-nogu.github.io/')
LIVE += ('&' if '?' in LIVE else '?') + 'v=' + str(int(time.time()))  # мимо кэша Pages
SHOTS = os.environ.get('SHOTS')
errs, cons, blocked, got, posted, rooms = [], [], [], set(), {'matches': [], 'players': []}, []


def shot(page, name):
    if SHOTS: os.makedirs(SHOTS, exist_ok=True); page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def read_only(route):
    r = route.request
    if r.method not in ('GET', 'HEAD', 'OPTIONS'):
        blocked.append(r.method + ' ' + r.url.split('/rest/v1/')[-1][:60]); return route.abort()
    got.add(r.url.split('/rest/v1/')[-1].split('?')[0])
    return route.continue_()


def fake(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'], 'mode': 'new'}))
    if '/rpc/bdm_sync' in u:
        b = json.loads(req.post_data)
        for m in b.get('p_matches') or []:
            if not any(x['id'] == m['id'] for x in posted['matches']): posted['matches'].append(m)
        posted['players'].append(b.get('p_best'))
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'saved': 0, 'skipped': []}))
    if '/rpc/bdm_room' in u:
        b = json.loads(req.post_data); rooms.append((b['p_code'], b['p_status']))
        return route.fulfill(status=200, content_type='application/json', body='{"ok":true}')
    if req.method == 'GET':
        return route.fulfill(status=200, content_type='application/json', body='[]')
    blocked.append('прямая запись ' + req.method + ' ' + u.split('/rest/v1/')[-1][:60])
    return route.fulfill(status=401, body='')


def watch(page, tag):
    page.on('pageerror', lambda e: errs.append(tag + ': ' + str(e)))
    page.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text and cons.append(tag + ': ' + m.text[:160]))


with sync_playwright() as pw:
    br = launch(pw)

    # 1. Настоящая база, только чтение
    ctx = br.new_context(viewport={'width': 1280, 'height': 760}); ctx.route('**/*supabase.co/**', read_only)
    A = ctx.new_page(); watch(A, 'menu')
    t0 = time.time(); A.goto(LIVE, wait_until='load'); load = time.time() - t0
    A.wait_for_function("() => /Общая таблица/.test(document.getElementById('lbFoot')?.innerText || '')", timeout=15000)
    info = A.evaluate("""() => ({ rows: __bdm.standings().length, peer: typeof window.Peer,
      fonts: [...new Set([...document.fonts].filter(f => f.status === 'loaded').map(f => f.family))] })""")
    print(f'загрузка {load:.1f} с · строк в общей таблице {info["rows"]} · PeerJS {info["peer"]} · шрифты {info["fonts"]}')
    assert info['peer'] == 'function', 'PeerJS не загрузился'
    assert {'Unbounded', 'Golos Text'} <= set(info['fonts']), 'шрифты не загрузились'
    assert {'matches', 'players'} <= got, f'из базы не читали matches/players: {got}'
    shot(A, 'live_menu'); ctx.close()

    # 2. Телефон вертикально
    M = br.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    M.route('**/*supabase.co/**', read_only)
    m = M.new_page(); watch(m, 'phone'); m.goto(LIVE, wait_until='load'); m.wait_for_timeout(1500)
    over = m.evaluate("() => document.documentElement.scrollWidth - innerWidth")
    assert over <= 0, f'на телефоне страница шире экрана на {over} px'
    shot(m, 'live_phone'); M.close()

    # 3. Настоящий PeerJS
    ctx = br.new_context(viewport={'width': 1100, 'height': 640}); ctx.route('**/*supabase.co/**', fake)
    H = ctx.new_page(); G = ctx.new_page(); watch(H, 'host'); watch(G, 'guest')
    H.goto(LIVE + '&p=4'); G.goto(LIVE + '&p=5'); H.wait_for_timeout(1200)
    sign_up(H, 'Хост'); sign_up(G, 'Гость')
    H.click('#netHost')
    H.wait_for_selector('.net-status .code', timeout=15000)
    code = H.inner_text('.net-status .code').strip()
    G.fill('#netCode', code); G.click('#netJoin'); t0 = time.time()
    H.wait_for_function("() => __bdm.Net.connected", timeout=20000); G.wait_for_function("() => __bdm.Net.connected", timeout=20000)
    print(f'PeerJS: комната {code}, соединились за {time.time() - t0:.1f} с')
    H.wait_for_timeout(300)
    assert (code, 'open') in rooms and (code, 'gone') in rooms, f'хост объявил и убрал комнату через bdm_room: {rooms}'
    assert G.evaluate("() => __bdm.game.mode") == 'online' and G.evaluate("() => __bdm.Net.myIdx") == 1
    H.wait_for_timeout(600)
    G.keyboard.press('KeyS'); H.wait_for_function("() => __bdm.Net.lastShotSeq >= 1", timeout=5000)
    G.keyboard.press('Digit4'); H.wait_for_function("() => __bdm.game.bubbles.some(b => b.text === 'GG')", timeout=5000)
    shot(G, 'live_online_guest'); ctx.close()

    # 4. Матч против ИИ до конца
    ctx = br.new_context(viewport={'width': 1280, 'height': 760}); ctx.route('**/*supabase.co/**', fake)
    A = ctx.new_page(); watch(A, '1p')
    A.goto(LIVE + '&p=3'); A.wait_for_timeout(1200)
    sign_up(A, 'Тест')
    A.click('#diffSeg button[data-diff="hard"]'); A.click('#playAi'); A.wait_for_timeout(500)
    assert A.evaluate("() => [__bdm.game.mode, __bdm.game.diff]") == ['1p', 'hard']
    A.evaluate("() => { __bdm.P[0].ai = { diff: 'medium' }; }")
    for _ in range(60):
        A.evaluate("() => __bdm.fastForward(30)")
        if A.evaluate("() => __bdm.game.state") == 'over': break
    A.evaluate("() => { __bdm.P[0].ai = null; }")
    A.wait_for_function("() => !document.getElementById('over')?.hidden || /Партия/.test(document.getElementById('overTitle')?.innerText || '')", timeout=5000)
    A.wait_for_timeout(1500)
    r = A.evaluate("() => ({ state: __bdm.game.state, score: __bdm.game.score, title: document.getElementById('overTitle').innerText })")
    print('матч против ИИ:', r['score'], r['title'], '· в облако ушло матчей', len(posted['matches']))
    assert r['state'] == 'over' and max(r['score']) >= 15 and r['title'].startswith('Партия')
    assert len(posted['matches']) == 1 and posted['matches'][0]['k'] == 'ai' and posted['matches'][0]['lv'] == 'hard'
    shot(A, 'live_1p_over')
    br.close()

# 5. Настоящая база закрыта на запись
SB = 'https://ktpeclypxevbfwtvuwbi.supabase.co/rest/v1/'
KEY = 'sb_publishable_zydu8BCg0hb0x92Vh0e1uQ_oMIMObKn'


def sb(method, path, body=None):
    with sync_playwright() as pw:
        api = pw.request.new_context(extra_http_headers={'apikey': KEY, 'Content-Type': 'application/json', 'Prefer': 'return=minimal'})
        r = api.fetch(SB + path, method=method, data=None if body is None else json.dumps(body), timeout=15000)
        res = r.status, r.text(); api.dispose(); return res


probes = {
    'добавить матч': ('POST', 'matches', {'id': 'x'}),                          # кривой id: открытая база тоже не запишет
    'изменить игрока': ('PATCH', 'players?pid=eq.0', {'name': 'x'}),            # pid '0' не бывает
    'добавить игрока': ('POST', 'players', {'pid': 'x', 'name': 'x'}),
    'добавить комнату': ('POST', 'rooms', {'code': 'x', 'host_pid': 'x', 'host_name': 'x'}),
    'удалить комнату': ('DELETE', 'rooms?code=eq.0', None),
    'изменить комнату': ('PATCH', 'rooms?code=eq.0', {'host_name': 'x'}),
}
for name, (m, path, body) in probes.items():
    st, txt = sb(m, path, body)
    assert st in (401, 403) and '42501' in txt, f'настоящая база: «{name}» не закрыто ({st} {txt[:120]})'
for fn, body in (('bdm_sync', {'p_pid': 'zzprobe01', 'p_pin': '0000', 'p_matches': []}),
                 ('bdm_room', {'p_pid': 'zzprobe01', 'p_pin': '0000', 'p_code': 'ZZZZ', 'p_status': 'gone'})):
    st, txt = sb('POST', 'rpc/' + fn, body)
    assert st == 200 and json.loads(txt) == {'ok': False, 'err': 'noacc'}, f'настоящая база: {fn} отвечает {st} {txt[:120]}'
st, _ = sb('POST', 'rpc/bdm_auth', {'p_pid': 'zzprobe01', 'p_pin': '0000'})
assert st in (401, 403, 404), f'bdm_auth доступна снаружи ({st})'
print('настоящая база: прямая запись закрыта, функции записи на месте')

assert not blocked, f'страница пыталась писать в настоящую базу: {blocked}'
assert not errs, errs
assert not cons, cons
print('OK: живой сайт')
