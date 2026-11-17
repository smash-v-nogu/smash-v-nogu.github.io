"""Онлайн без сети: две вкладки через BroadcastChannel (?net=local), хост создаёт комнату, гость входит по коду и бьёт."""
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
    br.close()

assert not errs, [e for e in errs if 'Failed to load resource' not in e] or None
print('OK: онлайн')
