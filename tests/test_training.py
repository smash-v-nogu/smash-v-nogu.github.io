"""Тренировка с многоволанкой целиком: бот на клавишах проходит 20 воланов, проверяем очки, рекорд и выгрузку best_train."""
import json, time
from _util import sync_playwright, BASE, launch, sign_up

posted = []


def handle(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'], 'mode': 'new'}))
    if req.method == 'GET':
        body = [{'pid': 'friend0001', 'name': 'Саша', 'best_smash': 250, 'best_rally': 9, 'best_train': 44, 'updated_at': '2026-11-17T10:00:00Z'}] if '/players' in u else []
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(body))
    if '/players' in u and req.method == 'POST': posted.extend(json.loads(req.post_data))
    return route.fulfill(status=201, body='')


BOT = """
() => {
  const b = window.__bdm; let last = 0;
  const KEY = { back: 'KeyQ', mid: 'KeyS', front: 'KeyE' };
  const press = code => { window.dispatchEvent(new KeyboardEvent('keydown', { code })); setTimeout(() => window.dispatchEvent(new KeyboardEvent('keyup', { code })), 40); };
  window.__bot = setInterval(() => {
    const me = b.P[0], sh = b.sh, g = b.game, now = performance.now();
    if (g.state !== 'rally' || !sh.inPlay || !sh.lastHitter || sh.lastHitter.idx !== 1) return;
    const pred = b.simulate(sh.x, sh.y, sh.vx, sh.vy, true);
    let tgt = null; for (const pt of pred.pts) { if (pt.x < 6.65 && pt.y < 2.4 && pt.y > 0.5) { tgt = pt; break; } }
    if (tgt) { const want = Math.max(-0.4, Math.min(6.3, tgt.x - 0.35)); me.x += (want - me.x) * 0.3; }
    const d = Math.hypot(sh.x - me.x, sh.y - (me.y + (sh.y < 0.9 ? 1.2 : 1.45)));
    if (sh.x < 6.7 && d < 1.0 && now - last > 600) { last = now; press(KEY[g.train.target]); }
  }, 8);
}
"""

errs = []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1200, 'height': 700}); ctx.route('**/*supabase.co/**', handle)
    A = ctx.new_page(); A.on('pageerror', lambda e: errs.append(str(e)))
    A.goto(BASE + '?p=9'); A.wait_for_timeout(600)
    sign_up(A, 'Кирилл')
    A.click('#playTrain'); A.wait_for_timeout(300)
    A.evaluate(BOT)
    t0 = time.time()
    while time.time() - t0 < 240 and A.evaluate("() => __bdm.game.state") != 'over':
        A.wait_for_timeout(300)
    r = A.evaluate("() => ({ state: __bdm.game.state, score: __bdm.game.train.score, left: __bdm.game.train.left, inZone: __bdm.game.train.inZone, title: document.getElementById('overTitle').textContent })")
    print('итог тренировки:', r)
    assert r['state'] == 'over' and r['left'] == 0 and r['score'] > 0
    A.wait_for_timeout(800)
    assert any(p.get('best_train') == r['score'] for p in posted), 'рекорд ушёл в общую таблицу'
    br.close()

assert not errs, errs
print('OK: тренировка')
