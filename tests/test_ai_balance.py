"""Баланс ИИ на ускоренной симуляции: демо-режим, оба игрока под ИИ, __bdm.fastForward.
Проверяем, что стороны симметричны, уровни упорядочены и розыгрыши не бесконечные. Supabase отрезан.
SECS — игровых секунд на случай (по умолчанию 15000, около 10 с реального времени на случай).
HTML — путь к другой версии index.html, чтобы сравнить со старым коммитом:
    git show <коммит>:index.html > /tmp/old.html && HTML=/tmp/old.html python3 test_ai_balance.py"""
import json, os
from _util import sync_playwright, BASE, launch

SECS = float(os.environ.get('SECS', '15000'))
STUCK = 180  # игровых секунд без очка — розыгрыш завис (в норме самый долгий около 50 с на 35–40 ударов)

RUN = """
([d0, d1, s0, s1, seconds, stuck]) => {
  const b = window.__bdm, g = b.game, P = b.P;
  P[0].ai = { diff: d0 }; P[1].ai = { diff: d1 }; P[0].style = s0; P[1].style = s1;
  const pts = [0, 0], hits = [], games = []; let maxHits = 0, quiet = 0, maxQuiet = 0;
  let last = [...g.score], gid = g.gameId, lastOver = null, cur = 0;
  const CH = 0.25;
  for (let t = 0; t < seconds; t += CH) {
    b.fastForward(CH); quiet += CH; maxQuiet = Math.max(maxQuiet, quiet);
    if (quiet > stuck) break;
    cur = Math.max(cur, g.rallyHits || 0); maxHits = Math.max(maxHits, cur);
    if (g.gameId !== gid) { if (lastOver) games.push(lastOver); gid = g.gameId; last = [...g.score]; lastOver = null; cur = 0; quiet = 0; continue; }
    const s = g.score;
    if (s[0] !== last[0] || s[1] !== last[1]) {
      pts[0] += s[0] - last[0]; pts[1] += s[1] - last[1]; hits.push(cur); cur = 0; quiet = 0; last = [...s];
      if (g.over !== null) lastOver = [...s];
    }
  }
  const avg = hits.reduce((a, c) => a + c, 0) / Math.max(1, hits.length);
  return { rallies: hits.length, pts, avgHits: +avg.toFixed(1), maxHits, maxQuiet, games };
}
"""

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
        r = A.evaluate(RUN, [d0, d1, s0, s1, SECS, STUCK])
        g = r['games']; w0 = sum(1 for a, b in g if a > b); p = r['pts']
        avg = [round(sum(x[i] for x in g) / len(g), 1) for i in (0, 1)] if g else None
        r.update(d0=d0, d1=d1, s0=s0, s1=s1, share0=p[0] / max(1, sum(p)), win0=w0 / max(1, len(g)), n=len(g), avgScore=avg)
        rows.append(r)
        print(f"{d0}/{s0} vs {d1}/{s1}: очки {p[0]}:{p[1]} ({round(100 * r['share0'])}% слева) · партий {len(g)}, слева выиграно {w0} · "
              f"ср. счёт {avg} · ударов за розыгрыш {r['avgHits']}, макс {r['maxHits']} · дольше всего без очка {r['maxQuiet']} с")
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
