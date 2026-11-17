"""Длина партии «до 7 / до 15»: выбор запоминается, партия против ИИ кончается на 7 (при 6:6 — отрыв в 2, но не дольше 10),
в сети длину задаёт хозяин комнаты, и гость видит её на табло."""
from _util import sync_playwright, BASE, launch, sign_up

errs = []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1100, 'height': 640}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    A = ctx.new_page(); A.on('pageerror', lambda e: errs.append('A: ' + str(e)))
    A.goto(BASE + '?net=local&p=5'); A.wait_for_timeout(800)
    sign_up(A, 'Коротыш')

    # против ИИ: выбрать «до 7», выбор виден в обоих переключателях и переживает перезагрузку
    A.click('.t-ai .len button[data-len="7"]')
    assert A.evaluate("() => [...document.querySelectorAll('.len button[aria-checked=\"true\"]')].map(b => b.dataset.len)") == ['7', '7']
    A.reload(); A.wait_for_timeout(800)
    if A.is_visible('#nameLater'): A.click('#nameLater')  # база недоступна — профиль без ПИНа, окно «Защити профиль» откладываем
    assert A.get_attribute('.t-ai .len button[data-len="7"]', 'aria-checked') == 'true', 'выбор «до 7» запомнился'
    A.click('#playAi'); A.wait_for_timeout(300)
    assert A.evaluate("() => __bdm.game.target") == 7
    assert A.inner_text('#boardMid').lower() == 'до 7'
    # дальше за игрока слева тоже играет ИИ — проверяем только правило конца партии
    A.evaluate("() => { __bdm.P[0].ai = { diff: 'medium' }; }")
    for _ in range(400):
        if A.evaluate("() => __bdm.game.over !== null"): break
        A.evaluate("() => __bdm.fastForward(5)")
    sc = A.evaluate("() => __bdm.game.score")
    hi, lo = max(sc), min(sc)
    assert A.evaluate("() => __bdm.game.over !== null"), f'партия до 7 закончилась, счёт {sc}'
    assert (hi == 7 and lo <= 5) or (7 < hi <= 10 and (hi - lo == 2 or hi == 10)), f'счёт по правилам короткой партии: {sc}'

    # сеть: хозяин выбрал «до 7» — гость играет до 7, хотя у себя оставил «до 15»
    A.click('#toMenu2'); A.wait_for_timeout(300)
    B = ctx.new_page(); B.on('pageerror', lambda e: errs.append('B: ' + str(e)))
    B.goto(BASE + '?net=local&p=4'); B.wait_for_timeout(800); sign_up(B, 'Гостюшка')
    assert B.get_attribute('.t-net .len button[data-len="15"]', 'aria-checked') == 'true'
    A.click('#netHost'); A.wait_for_timeout(400)
    code = A.inner_text('.net-status .code')
    B.fill('#netCode', code); B.click('#netJoin'); B.wait_for_timeout(1500)
    assert A.evaluate("() => __bdm.Net.connected") and B.evaluate("() => __bdm.Net.connected")
    assert A.evaluate("() => __bdm.game.target") == 7 and B.evaluate("() => __bdm.game.target") == 7, 'гость получил длину партии от хозяина'
    assert B.inner_text('#boardMid').lower() == 'до 7'
    br.close()

assert not errs, [e for e in errs if 'Failed to load resource' not in e] or None
print(f'OK: длина партии (до 7 закончилась {hi}:{lo})')
