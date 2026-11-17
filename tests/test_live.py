"""Проверка живого сайта после деплоя. Локальный сервер не нужен.
1. Настоящая Supabase, но только чтение: любые не-GET запросы к ней обрываются. Общая таблица подтянулась, ошибок нет.
2. Телефон вертикально: меню без горизонтальной прокрутки.
3. Онлайн через настоящий PeerJS между двумя браузерами. Supabase здесь подменён, в базу ничего не пишется.
4. Матч против ИИ до конца (за игрока доигрывает ИИ через fastForward): экран итога, запись матча уходит в облако (подменённое).
LIVE_URL — другой адрес сайта. Скриншоты кладутся в SHOTS, если задан."""
import json, os, time
from _util import sync_playwright, launch, sign_up

LIVE = os.environ.get('LIVE_URL', 'https://smash-v-nogu.github.io/')
LIVE += ('&' if '?' in LIVE else '?') + 'v=' + str(int(time.time()))  # мимо кэша Pages
SHOTS = os.environ.get('SHOTS')
errs, cons, blocked, got, posted = [], [], [], set(), {'matches': [], 'players': []}


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
    if req.method == 'GET':
        return route.fulfill(status=200, content_type='application/json', body='[]')
    for k in posted:
        if '/' + k in u and req.post_data: posted[k].extend(json.loads(req.post_data))
    return route.fulfill(status=201, body='')


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

assert not blocked, f'страница пыталась писать в настоящую базу: {blocked}'
assert not errs, errs
assert not cons, cons
print('OK: живой сайт')
