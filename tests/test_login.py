"""Вход по имени и ПИН: регистрация, неверный ПИН, вход с другого браузера, смена имени, запись своего через bdm_sync.
Supabase подменён фейковым сервером в памяти (логика как у функций bdm_login и bdm_sync); прямая запись в таблицы роняет тест."""
import json
from _util import sync_playwright, BASE, launch

accounts, aliases, matches, players, calls, syncs, direct = {}, {}, [], {}, [], [], []


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
    if '/rpc/bdm_sync' in u:
        b = json.loads(req.post_data); syncs.append(b)
        a = next((x for x in accounts.values() if x['pid'] == b['p_pid']), None)
        if not a: res = {'ok': False, 'err': 'noacc'}
        elif a['pin'] != b['p_pin']: res = {'ok': False, 'err': 'pin'}
        else:
            mine = {a['pid']} | {k for k, v in aliases.items() if v == a['pid']}
            for m in b.get('p_matches') or []:
                if ((m['k'] == 'ai' and m['p'] in mine) or (m['k'] == 'net' and (m['a'] in mine or m['b'] in mine))) \
                        and not any(x['id'] == m['id'] for x in matches): matches.append(m)
            best, pl = b.get('p_best') or {}, players.setdefault(a['pid'], {'pid': a['pid'], 'best_smash': 0, 'best_rally': 0, 'best_train': 0})
            pl.update(name=a['name'], updated_at='2026-11-17T12:00:00Z', best_smash=max(pl['best_smash'], best.get('smash', 0)),
                      best_rally=max(pl['best_rally'], best.get('rally', 0)), best_train=max(pl['best_train'], best.get('train', 0)))
            res = {'ok': True, 'saved': 0, 'skipped': []}
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(res))
    if req.method == 'GET':
        body = ([{'from_pid': k, 'to_pid': v} for k, v in aliases.items()] if '/aliases' in u
                else matches if '/matches' in u else list(players.values()) if '/players' in u else [])
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(body))
    direct.append(req.method + ' ' + u.split('/rest/v1/')[-1])  # прямая запись в таблицу — в настоящей базе закрыта
    return route.fulfill(status=401, content_type='application/json', body='{"code":"42501"}')


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
    assert players.get(pa, {}).get('name') == 'Кирилл', 'после регистрации игрок записан через bdm_sync'
    assert syncs and all(x['p_pid'] == pa and x['p_pin'] == '1234' for x in syncs), 'запись подписана своим ПИНом'
    A.evaluate("""() => { const b = __bdm; b.store.recs.push(
        { id: 'mineai0001', t: Date.now(), k: 'ai', p: b.profile.pid, lv: 'hard', win: true, s: [15, 9] },
        { id: 'foreign001', t: Date.now(), k: 'ai', p: 'stranger01', lv: 'easy', win: true, s: [15, 2] }); return b.cloudSync(); }""")
    A.wait_for_timeout(300)
    assert [m['id'] for m in matches] == ['mineai0001'], 'в базу ушёл только свой матч'
    assert A.evaluate("() => __bdm.store.cloud.has('foreign001')"), 'чужой матч больше не отправляется'
    n_sync = len(syncs)
    A.evaluate("() => __bdm.cloudSync()"); A.wait_for_timeout(300)
    assert syncs[-1]['p_matches'] == [] and len(syncs) == n_sync + 1, 'отправленное не повторяется'

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
    B.wait_for_timeout(300)
    assert players[pa]['name'] == 'Кир', 'имя в таблице берётся из аккаунта'

    # ПИН сменили в базе — клиент перестаёт писать и при следующем входе спросит ПИН заново
    accounts['кир']['pin'] = '9999'; n_sync = len(syncs)
    B.evaluate("() => __bdm.cloudSync()"); B.wait_for_timeout(400)
    assert B.evaluate("() => [__bdm.profile.acc, 'pin' in __bdm.profile]") == [False, False]
    B.evaluate("() => __bdm.cloudSync()"); B.wait_for_timeout(300)
    assert len(syncs) == n_sync + 1, 'без ПИНа запись не отправляется'
    br.close()

assert not direct, f'игра писала в таблицы напрямую: {direct}'

assert not errs, errs
print('OK: вход по ПИН')
