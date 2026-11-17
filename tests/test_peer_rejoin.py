"""Онлайн через настоящий PeerJS: комнату не занимает призрак.
1. Гость начал подключаться и пропал — следующий гость входит, а не получает «уже играют двое».
2. Тот же игрок заходит со второй вкладки (ссылка открылась в Telegram, потом в Safari) — новая вкладка вытесняет старую.
3. Чужой третий, пока гость живой, — «уже играют двое», игра не ломается.
Supabase подменён. Нужен интернет (сервер PeerJS)."""
import json, time
from _util import sync_playwright, BASE, launch, sign_up


def fake(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'], 'mode': 'new'}))
    return route.fulfill(status=200, content_type='application/json', body='{"ok":true}' if '/rpc/' in u else '[]')


def join(pg, code, wait=20):
    pg.fill('#netCode', code); pg.click('#netJoin'); t0 = time.time()
    while time.time() - t0 < wait:
        pg.wait_for_timeout(300)
        if pg.evaluate("() => __bdm.Net.connected"): return 'вошёл'
        if 'играют двое' in pg.inner_text('#netStatus'): return 'занято'
    return 'не вошёл'


errs = []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1100, 'height': 640}); ctx.route('**/*supabase.co/**', fake)

    def page(slot, name=None):
        pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(f'{slot}: {e}')); pg.goto(f'{BASE}?p={slot}'); pg.wait_for_timeout(900)
        if name: sign_up(pg, name)
        return pg

    H = page(1, 'Хост')
    H.click('#netHost'); H.wait_for_selector('.net-status .code', timeout=15000)
    code = H.inner_text('.net-status .code').strip()

    # 1. Призрак: начал подключение и закрыл вкладку
    X = page(9); X.wait_for_function('() => window.Peer', timeout=15000)
    X.evaluate("c => { const p = new window.Peer(); p.on('open', () => p.connect('bdm-proto-26-' + c)); }", code)
    X.wait_for_timeout(1500); X.close(); H.wait_for_timeout(3500)  # призрак замолчал дольше 3 с
    G1 = page(2, 'Гость')
    r = join(G1, code)
    assert r == 'вошёл', f'после призрака гость: {r}'
    G1.wait_for_timeout(800); G1.keyboard.press('KeyS'); H.wait_for_timeout(800)
    assert H.evaluate('() => __bdm.Net.connected && __bdm.game.mode') == 'online'
    assert H.evaluate('() => __bdm.Net.lastShotSeq') >= 1, 'удар гостя дошёл до хоста'

    # 3. Чужой третий, пока гость живой
    T = page(3, 'Третий')
    assert join(T, code, 15) == 'занято', 'живого гостя не вытеснить чужому'
    assert G1.evaluate('() => __bdm.Net.connected'), 'гость остался в игре'

    # 2. Тот же игрок со второй вкладки (тот же профиль ?p=2)
    G2 = page(2)
    assert join(G2, code) == 'вошёл', 'тот же игрок со второй вкладки входит'
    G1.wait_for_timeout(1500)
    assert not G1.evaluate('() => __bdm.Net.connected'), 'старая вкладка отключена'
    G2.wait_for_timeout(800); n0 = H.evaluate('() => __bdm.Net.lastShotSeq')
    G2.keyboard.press('KeyS'); H.wait_for_timeout(800)
    assert H.evaluate('() => __bdm.Net.lastShotSeq') > n0 or H.evaluate('() => __bdm.game.state') != 'serve', 'хост слышит новую вкладку'
    assert H.evaluate('() => __bdm.Net.connected'), 'комната жива'
    br.close()

assert not errs, errs
print('OK: комнату не занимает призрак')
