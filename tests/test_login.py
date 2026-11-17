"""Вход по имени и ПИН: регистрация, неверный ПИН, вход с другого браузера, смена имени.
Supabase подменён фейковым сервером в памяти (логика как у функции bdm_login)."""
import json
from _util import sync_playwright, BASE, launch

accounts, aliases, matches, players, calls = {}, {}, [], {}, []


def handle(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data); n, pin, pid, md = b['p_name'].strip(), b['p_pin'], b['p_pid'], b.get('p_mode', 'new'); calls.append(md)
        a = accounts.get(n.lower())
        if a:
            if md == 'rename' and a['pid'] != pid: res = {'ok': False, 'err': 'taken'}
            elif a['pin'] != pin: res = {'ok': False, 'err': 'pin' if md == 'login' else 'taken'}
            else:
                if pid != a['pid'] and not any(x['pid'] == pid for x in accounts.values()): aliases[pid] = a['pid']
                res = {'ok': True, 'pid': a['pid'], 'name': a['name'], 'mode': 'login'}
        elif md == 'login': res = {'ok': False, 'err': 'noname'}
        else:
            own = next((x for x in accounts.values() if x['pid'] == pid), None)
            if own:
                if own['pin'] != pin: res = {'ok': False, 'err': 'pin'}
                else:
                    del accounts[own['name'].lower()]; own['name'] = n; accounts[n.lower()] = own
                    res = {'ok': True, 'pid': pid, 'name': n, 'mode': 'rename'}
            else:
                accounts[n.lower()] = {'pid': pid, 'name': n, 'pin': pin}; res = {'ok': True, 'pid': pid, 'name': n, 'mode': 'new'}
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(res))
    if req.method == 'GET':
        body = ([{'from_pid': k, 'to_pid': v} for k, v in aliases.items()] if '/aliases' in u
                else matches if '/matches' in u else list(players.values()) if '/players' in u else [])
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(body))
    if '/players' in u and req.method == 'POST':
        for p in json.loads(req.post_data): players[p['pid']] = p
    if '/matches' in u and req.method == 'POST':
        for m in json.loads(req.post_data):
            if not any(x['id'] == m['id'] for x in matches): matches.append(m)
    return route.fulfill(status=201, body='')


errs = []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1200, 'height': 860}); ctx.route('**/*supabase.co/**', handle)

    def page(slot):
        pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(f'{slot}: {e}')); pg.goto(f'{BASE}?p={slot}'); pg.wait_for_timeout(700); return pg

    A = page(1)
    assert A.inner_text('#nameTitle') == 'Как тебя зовут?'
    A.fill('#nameInput', 'Кирилл'); A.fill('#pinInput', '12'); A.click('#nameSubmit'); A.wait_for_timeout(200)
    assert 'ровно 4 цифры' in A.inner_text('#nameErr')
    A.fill('#pinInput', '1234'); A.click('#nameSubmit'); A.wait_for_timeout(600)
    pa = A.evaluate("() => __bdm.profile.pid")
    assert A.is_visible('#rules'), 'новичку открываются правила'
    A.click('#rClose')

    B = page(2)
    B.click('#authSeg button[data-m="login"]')
    assert B.inner_text('#nameTitle') == 'С возвращением'
    B.fill('#nameInput', 'Кирилл'); B.fill('#pinInput', '0000'); B.click('#nameSubmit'); B.wait_for_timeout(400)
    assert B.inner_text('#nameErr') == 'Неверный ПИН'
    B.fill('#nameInput', 'Кирил'); B.fill('#pinInput', '1234'); B.click('#nameSubmit'); B.wait_for_timeout(400)
    assert 'нет' in B.inner_text('#nameErr') and list(accounts) == ['кирилл'], 'вход с опечаткой не создаёт аккаунт'
    B.fill('#nameInput', 'Кирилл'); B.click('#nameSubmit'); B.wait_for_timeout(800)
    assert B.evaluate("() => __bdm.profile.pid") == pa, 'второй браузер вошёл в тот же аккаунт'
    assert not B.is_visible('#rules')

    D = page(4)
    D.fill('#nameInput', 'кирилл'); D.fill('#pinInput', '5555'); D.click('#nameSubmit'); D.wait_for_timeout(400)
    assert 'уже занято' in D.inner_text('#nameErr')

    n0 = len(calls)
    B.click('#editName'); B.click('#styleSeg button[data-style="attack"]'); B.click('#nameSubmit'); B.wait_for_timeout(300)
    assert len(calls) == n0, 'смена только стиля не ходит на сервер'
    B.click('#editName'); B.fill('#nameInput', 'Кир'); B.click('#nameSubmit'); B.wait_for_timeout(400)
    assert calls[-1] == 'rename' and list(accounts) == ['кир']
    br.close()

assert not errs, errs
print('OK: вход по ПИН')
