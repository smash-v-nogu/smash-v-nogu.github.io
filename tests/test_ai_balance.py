"""Баланс ИИ на ускоренной симуляции: демо-режим, оба игрока под ИИ, __bdm.fastForward.
Проверяем, что стороны симметричны, уровни упорядочены и розыгрыши не бесконечные, а однообразный соперник
(бот на физике сложного жмёт одну кнопку с одним прицелом) не обыгрывает сложного. Supabase отрезан.
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
# Однообразные боты против сложного: (название, бот, минимальная доля очков у сложного).
# До 18.11.2026 у сложного было 39–44% против дропера и 31–33% против смэша на заднюю. С тактикой (tact) и добиванием
# у сетки — около 64% и 56%. Пороги с запасом на шум (при 15000 с около 2,5 п.п.), старое поведение они ловят.
BOTS = [
    ('острый дроп / тугая сетка', {'key': 'drop', 'place': 1}, 0.55),
    ('смэш на заднюю (снизу драйв)', {'key': 'smash', 'place': -1}, 0.5),
    ('смэш в ноги (снизу драйв)', {'key': 'smash', 'place': 1}, 0.55),
]
# «Человек»: бот без случайных срывов ИИ (err 0), как живой игрок — ошибается только от плохого контакта.
# Всегда острый дроп: до 18.11 брал у сложного 88% очков, с одной тактикой 75%, с тактикой и добиванием около 53%.
# Порог — не больше 60%. Срыв тугого прицела (slip) 18.11 решили не выкатывать.
HUMAN = {'label': 'человек', 'react': 0.22, 'speed': 1, 'spread': 1, 'err': 0, 'perfect': 0.35, 'judgeOut': 0.9, 'aggr': 1,
         'power': 1, 'timing': 0.03, 'risk': 0}
HUMAN_MAX = 0.6

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
    bots = []
    for name, bot, low in BOTS:
        r = ai_case(A, {'diff': 'hard', 'bot': bot}, {'diff': 'hard'}, 'tech', 'tech', SECS, STUCK)
        bots.append((name, low, r))
        print(f"бот «{name}» против сложного: у сложного {1 - r['share0']:.1%} очков, {1 - r['win0']:.0%} партий из {r['n']} · "
              f"ударов за розыгрыш {r['avgHits']}, макс {r['maxHits']}")
    A.evaluate("h => { __bdm.DIFFS.human = h; }", HUMAN)
    hum = ai_case(A, {'diff': 'human', 'bot': {'key': 'drop', 'place': 1}}, {'diff': 'hard'}, 'tech', 'tech', SECS, STUCK)
    print(f"«человек» (острый дроп) против сложного: у человека {hum['share0']:.1%} очков, "
          f"{hum['win0']:.0%} партий из {hum['n']} · ударов за розыгрыш {hum['avgHits']}, макс {hum['maxHits']}")
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
for name, low, r in bots:
    assert r['maxQuiet'] <= STUCK and r['maxHits'] < 100, f"бот «{name}»: розыгрыш завис"
    assert 1 - r['share0'] >= low, f"бот «{name}» обыгрывает сложного: у сложного {1 - r['share0']:.1%} очков"
assert hum['maxQuiet'] <= STUCK and hum['maxHits'] < 100, '«человек»: розыгрыш завис'
assert hum['share0'] <= HUMAN_MAX, f"«человек» с острым дропом обыгрывает сложного: {hum['share0']:.1%} очков (добивание или тактика не работают?)"
assert not errs, errs
print('OK: баланс ИИ')
