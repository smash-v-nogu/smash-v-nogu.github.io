"""Общие помощники для сценариев: запуск браузера и адрес локального сервера."""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get('BASE_URL', 'http://localhost:8765/index.html')
CHROME = os.environ.get('CHROME')  # путь к своему Chrome, если не хочется качать Chromium от Playwright


def launch(pw):
    args = ['--no-sandbox']
    return pw.chromium.launch(executable_path=CHROME, args=args) if CHROME else pw.chromium.launch(args=args)


def sign_up(page, name, pin='1234'):
    """Первый вход: имя + ПИН, потом закрыть правила, которые открываются новичку."""
    page.fill('#nameInput', name)
    page.fill('#pinInput', pin)
    page.press('#pinInput', 'Enter')
    page.wait_for_timeout(500)
    if page.is_visible('#rClose'):
        page.click('#rClose')


# Ускоренная симуляция ИИ против ИИ в демо-режиме (__bdm.fastForward). a0 / a1 — объекты ИИ слева и справа:
# { diff } или с ботом для тестов { diff, bot: { key, place } | 'any' }. Считает очки, партии, длину розыгрышей
# и статистику «чтения» умного ИИ (сколько ударов соперника он угадывал).
AI_RUN = """
([a0, a1, s0, s1, seconds, stuck]) => {
  const b = window.__bdm, g = b.game, P = b.P;
  if (b.readReset) b.readReset();
  P[0].ai = { ...a0 }; P[1].ai = { ...a1 }; P[0].style = s0; P[1].style = s1;
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
  return { rallies: hits.length, pts, avgHits: +avg.toFixed(1), maxHits, maxQuiet, games, read: g.stats.read || null };
}
"""


def ai_case(page, a0, a1, s0='tech', s1='tech', secs=15000, stuck=180):
    """Прогоняет случай и добавляет доли: share0 — очков слева, win0 — партий слева, avgScore — средний счёт."""
    r = page.evaluate(AI_RUN, [a0, a1, s0, s1, secs, stuck])
    g, p = r['games'], r['pts']
    r['share0'] = p[0] / max(1, sum(p))
    r['win0'] = sum(1 for a, b in g if a > b) / max(1, len(g))
    r['n'] = len(g)
    r['avgScore'] = [round(sum(x[i] for x in g) / len(g), 1) for i in (0, 1)] if g else None
    return r


__all__ = ['sync_playwright', 'BASE', 'launch', 'sign_up', 'AI_RUN', 'ai_case']
