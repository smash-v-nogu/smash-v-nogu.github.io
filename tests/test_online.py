"""Онлайн без сети: две вкладки через BroadcastChannel (?net=local), хост создаёт комнату, гость входит по коду и бьёт.
Потом хост открывает комнату и уходит играть с ИИ: комната закрывается, и вошедший друг его из партии не выдёргивает."""
from _util import sync_playwright, BASE, launch, sign_up

errs = []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1100, 'height': 640}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    A = ctx.new_page(); B = ctx.new_page()
    for pg, n in ((A, 'A'), (B, 'B')): pg.on('pageerror', lambda e, n=n: errs.append(n + ': ' + str(e)))
    A.goto(BASE + '?net=local&p=7'); B.goto(BASE + '?net=local&p=8'); A.wait_for_timeout(800)
    sign_up(A, 'Хост'); sign_up(B, 'Гость')
    A.click('#netHost'); A.wait_for_timeout(400)
    code = A.inner_text('.net-status .code')
    B.fill('#netCode', code); B.click('#netJoin'); B.wait_for_timeout(1500)
    assert A.evaluate("() => __bdm.Net.connected") and B.evaluate("() => __bdm.Net.connected")
    assert A.evaluate("() => __bdm.game.mode") == 'online'
    B.keyboard.press('KeyS'); A.wait_for_timeout(400)
    assert A.evaluate("() => __bdm.Net.lastShotSeq") == 1, 'удар гостя дошёл до хоста'
    B.keyboard.press('Digit4'); A.wait_for_timeout(500)
    assert ['GG'] == A.evaluate("() => __bdm.game.bubbles.map(b => b.text)"), 'реакция гостя видна хосту'

    # хост открыл комнату и ушёл играть с ИИ — комната закрыта, друг по коду не входит
    C = ctx.new_page(); D = ctx.new_page()
    for pg, n in ((C, 'C'), (D, 'D')): pg.on('pageerror', lambda e, n=n: errs.append(n + ': ' + str(e)))
    C.goto(BASE + '?net=local&p=5'); D.goto(BASE + '?net=local&p=6'); C.wait_for_timeout(800)
    sign_up(C, 'Хост2'); sign_up(D, 'Гость2')
    C.click('#netHost'); C.wait_for_timeout(400)
    code2 = C.inner_text('.net-status .code')
    assert C.evaluate("() => __bdm.Net.role") == 'host'
    C.click('#playAi'); C.wait_for_timeout(300)
    assert C.evaluate("() => __bdm.game.mode") == '1p'
    assert not C.evaluate("() => __bdm.Net.role"), 'ушёл играть с ИИ — комната закрыта'
    D.fill('#netCode', code2); D.click('#netJoin'); D.wait_for_timeout(1500)
    assert not D.evaluate("() => __bdm.Net.connected"), 'в закрытую комнату не войти'
    assert C.evaluate("() => __bdm.game.mode") == '1p', 'хоста не выдернуло из партии с ИИ'
    br.close()

assert not errs, [e for e in errs if 'Failed to load resource' not in e] or None
print('OK: онлайн')
