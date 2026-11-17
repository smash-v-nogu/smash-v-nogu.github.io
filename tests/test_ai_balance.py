"""Баланс ИИ на ускоренной симуляции: демо-режим, оба игрока под ИИ, __bdm.fastForward.
Проверяем, что стороны симметричны, уровни упорядочены и розыгрыши не бесконечные. Supabase отрезан.
SECS — игровых секунд на случай (по умолчанию 15000, около 10 с реального времени на случай).
HTML — путь к другой версии index.html, чтобы сравнить со старым коммитом:
    git show <коммит>:index.html > /tmp/old.html && HTML=/tmp/old.html python3 test_ai_balance.py"""
import json, os
from _util import sync_playwright, BASE, launch, ai_case

SECS = float(os.environ.get('SECS', '15000'))
STUCK = 180  # игровых секунд без очка — розыгрыш завис (в норме самый долгий около 50 с на 35–40 ударов)

# (левый, правый, стиль левого, стиль правого)
CASES = [
    ('medium', 'medium', 'tech', 'tech'),
    ('hard', 'medium', 'tech', 'tech'),
    ('medium', 'hard', 'tech', 'tech'),
    ('easy', 'medium', 'tech', 'tech'),
    ('hard', 'medium', 'defense', 'attack'),
]

errs, rows = [], []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1200, 'height': 700}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    if os.environ.get('HTML'):
        html = open(os.environ['HTML'], encoding='utf-8').read()
        ctx.route('**/index.html*', lambda r: r.fulfill(status=200, content_type='text/html; charset=utf-8', body=html))
    A = ctx.new_page(); A.on('pageerror', lambda e: errs.append(str(e)))
    A.goto(BASE + '?p=6'); A.wait_for_timeout(800)
    assert A.evaluate("() => __bdm.game.mode") == 'demo', 'на старте крутится демо'
    for d0, d1, s0, s1 in CASES:
        r = ai_case(A, {'diff': d0}, {'diff': d1}, s0, s1, SECS, STUCK)
        r.update(d0=d0, d1=d1, s0=s0, s1=s1); rows.append(r); p = r['pts']
        print(f"{d0}/{s0} vs {d1}/{s1}: очки {p[0]}:{p[1]} ({round(100 * r['share0'])}% слева) · партий {r['n']}, слева выиграно {round(r['win0'] * r['n'])} · "
              f"ср. счёт {r['avgScore']} · ударов за розыгрыш {r['avgHits']}, макс {r['maxHits']} · дольше всего без очка {r['maxQuiet']} с")
    br.close()

by = {(r['d0'], r['d1'], r['s0'], r['s1']): r for r in rows}
for r in rows:
    assert r['maxQuiet'] <= STUCK, f"{r['d0']} vs {r['d1']}: розыгрыш завис, {r['maxQuiet']} с без очка"
    assert 6 <= r['avgHits'] <= 18, f"{r['d0']} vs {r['d1']}: в среднем {r['avgHits']} ударов за розыгрыш"
    assert r['maxHits'] < 100, f"{r['d0']} vs {r['d1']}: розыгрыш на {r['maxHits']} ударов"
    assert r['n'] >= 20, f"{r['d0']} vs {r['d1']}: всего {r['n']} партий, мало для выводов"
mm = by[('medium', 'medium', 'tech', 'tech')]
assert 0.42 <= mm['share0'] <= 0.58, f"средний против среднего несимметричен: {mm['share0']:.0%} очков слева"
assert by[('hard', 'medium', 'tech', 'tech')]['win0'] >= 0.75, 'сложный слева должен уверенно обыгрывать среднего'
assert by[('medium', 'hard', 'tech', 'tech')]['win0'] <= 0.25, 'сложный справа должен уверенно обыгрывать среднего'
assert by[('easy', 'medium', 'tech', 'tech')]['win0'] <= 0.25, 'средний должен уверенно обыгрывать лёгкого'
assert by[('hard', 'medium', 'defense', 'attack')]['win0'] >= 0.75, 'стиль не должен переворачивать уровень'
assert not errs, errs
print('OK: баланс ИИ')
