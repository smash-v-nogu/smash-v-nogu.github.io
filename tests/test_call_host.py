"""Соперник пришёл, пока хозяин в другой вкладке: свисток, мигающий заголовок, повторный свисток через 12 с,
у гостя — надпись «Друг отошёл». Хозяин вернулся — заголовок снова счёт, у гостя надпись пропала.
Скрытую вкладку изображаем подменой document.hidden; свистки считаем по созданным осцилляторам
(в меню остальные звуки молчат, а у свистка 4 осциллятора: два гудка, у каждого тон и трель)."""
import os
from _util import sync_playwright, BASE, launch, sign_up

HIDE = """
window.__hid = false;
Object.defineProperty(document, 'hidden', { get: () => window.__hid, configurable: true });
Object.defineProperty(document, 'visibilityState', { get: () => window.__hid ? 'hidden' : 'visible', configurable: true });
window.__osc = 0;
const AC = window.AudioContext || window.webkitAudioContext, co = AC.prototype.createOscillator;
AC.prototype.createOscillator = function () { window.__osc++; return co.call(this); };
"""
SET_HIDDEN = "h => { window.__hid = h; document.dispatchEvent(new Event('visibilitychange')); }"
OUT = os.environ.get('SHOTS', '')


def room(pw, br, slots, host_hidden):
    ctx = br.new_context(viewport={'width': 1100, 'height': 640}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    ctx.add_init_script(HIDE)
    A = ctx.new_page(); B = ctx.new_page()
    for pg, n in ((A, 'A'), (B, 'B')): pg.on('pageerror', lambda e, n=n: errs.append(n + ': ' + str(e)))
    A.goto(BASE + f'?net=local&p={slots[0]}'); B.goto(BASE + f'?net=local&p={slots[1]}'); A.wait_for_timeout(800)
    sign_up(A, 'Хост'); sign_up(B, 'Гость')
    A.click('#netHost'); A.wait_for_timeout(400)
    assert 'свистнем' in A.inner_text('.net-status'), 'в ожидании сказано, что позовём свистком'
    code = A.inner_text('.net-status .code')
    if host_hidden: A.evaluate(SET_HIDDEN, True)
    osc0 = A.evaluate('window.__osc')
    B.fill('#netCode', code); B.click('#netJoin'); B.wait_for_timeout(1500)
    assert A.evaluate("() => __bdm.game.mode") == 'online' and B.evaluate("() => __bdm.Net.connected")
    return ctx, A, B, osc0


errs = []
with sync_playwright() as pw:
    br = launch(pw)

    # 1. Хозяин смотрит на вкладку: один свисток, заголовок — счёт, у гостя надписи нет
    ctx, A, B, osc0 = room(pw, br, (5, 6), False)
    A.wait_for_timeout(1500)
    assert A.evaluate('window.__osc') - osc0 == 4, ('один свисток', A.evaluate('window.__osc') - osc0)
    assert A.title().startswith('0:0'), A.title()
    assert B.evaluate("() => __bdm.Net.peerAway") == 0
    ctx.close()

    # 2. Хозяин в другой вкладке
    ctx, A, B, osc0 = room(pw, br, (3, 4), True)
    assert A.evaluate('window.__osc') - osc0 == 4, 'свисток сразу при входе гостя'
    titles = set()
    for _ in range(6): titles.add(A.title()); A.wait_for_timeout(500)
    assert '🏸 Соперник пришёл!' in titles and len(titles) >= 2, ('заголовок мигает', titles)
    assert B.evaluate("() => __bdm.Net.peerAway") == 2, 'гость знает, что хозяина позвали'
    if OUT: B.screenshot(path=os.path.join(OUT, 'guest_away.png'))
    A.wait_for_timeout(10000)  # к 12-й секунде — второй свисток
    assert A.evaluate('window.__osc') - osc0 == 8, ('второй свисток через 12 с', A.evaluate('window.__osc') - osc0)

    A.evaluate(SET_HIDDEN, False); A.wait_for_timeout(1200)
    assert A.title().startswith('0:0'), ('вернулся — в заголовке снова счёт', A.title())
    assert B.evaluate("() => __bdm.Net.peerAway") == 0, 'у гостя надпись пропала'

    # 3. Ушёл посреди игры: у гостя «игра стоит», без свистка
    osc1 = A.evaluate('window.__osc')
    A.evaluate(SET_HIDDEN, True); A.wait_for_timeout(600)
    assert B.evaluate("() => __bdm.Net.peerAway") == 1
    assert A.evaluate('window.__osc') == osc1, 'посреди игры хозяина не зовём'
    A.evaluate(SET_HIDDEN, False); A.wait_for_timeout(600)
    assert B.evaluate("() => __bdm.Net.peerAway") == 0
    ctx.close()
    br.close()

assert not [e for e in errs if 'Failed to load resource' not in e], errs
print('OK: хозяина зовут, когда соперник пришёл')
