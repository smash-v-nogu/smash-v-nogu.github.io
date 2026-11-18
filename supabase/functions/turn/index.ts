// Временные ключи ретранслятора (TURN Cloudflare) для онлайна «Смэш мне в ногу».
// Напрямую соединяются не все пары сетей (мобильный интернет, VPN, рабочий Wi‑Fi). Тогда игра идёт через TURN.
// Ключ Cloudflare хранится только здесь, в секретах функции; игра получает ключи на TTL секунд.
//
// Секреты (Supabase → Edge Functions → Secrets):
//   CF_TURN_KEY_ID     — Turn Token ID из Cloudflare (Realtime → TURN Server)
//   CF_TURN_API_TOKEN  — API Token того же ключа
// Проверку JWT у функции выключить: игра зовёт её с публичным ключом sb_publishable_…, он не JWT.

const TTL = 6 * 3600; // партия плюс запас: ключи нужны всё время, пока идёт соединение
const ALLOW = [
  /^https:\/\/smash-v-nogu\.github\.io$/,
  /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/,
];

Deno.serve(async (req) => {
  const origin = req.headers.get('origin') || '';
  const ok = ALLOW.some((r) => r.test(origin));
  const cors: Record<string, string> = {
    'Access-Control-Allow-Origin': ok ? origin : 'https://smash-v-nogu.github.io',
    'Access-Control-Allow-Headers': 'apikey, authorization, content-type, x-client-info',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Vary': 'Origin',
  };
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { ...cors, 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });

  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  // Ключи раздаём только странице игры: чужой сайт из браузера ретранслятор не получит
  if (!ok) return json({ error: 'origin' }, 403);
  if (req.method !== 'POST') return json({ error: 'method' }, 405);

  const id = Deno.env.get('CF_TURN_KEY_ID'), token = Deno.env.get('CF_TURN_API_TOKEN');
  if (!id || !token) return json({ error: 'not configured' }, 500);

  try {
    const r = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${id}/credentials/generate-ice-servers`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ ttl: TTL }),
    });
    if (!r.ok) return json({ error: 'cloudflare ' + r.status }, 502);
    const data = await r.json();
    const raw = Array.isArray(data.iceServers) ? data.iceServers : [data.iceServers];
    // Порт 53 браузеры не пускают: убираем, чтобы не ждать таймаута на нём
    const iceServers = raw
      .filter((s: { urls?: unknown }) => s && s.urls)
      .map((s: { urls: string | string[] }) => ({ ...s, urls: ([] as string[]).concat(s.urls).filter((u) => !/:53(\?|$)/.test(u)) }))
      .filter((s: { urls: string[] }) => s.urls.length);
    return json({ iceServers, ttl: TTL });
  } catch (_) {
    return json({ error: 'cloudflare unreachable' }, 502);
  }
});
