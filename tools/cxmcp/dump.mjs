/**
 * 给 msgscan 用的薄封装：按 syncTtlSeconds 增量同步一次，然后把
 * 「since 之后的消息」以统一字段打出来。
 *
 * 用法：node dump.mjs [--since <ISO|epoch-ms>] [--limit N] [--force]
 * 输出：JSON 数组，元素 {time, conv, sender, kind, text}
 */
import { sync } from './src/sync.mjs';
import { readIndex, readSession } from './src/store.mjs';
import { loadConfig } from './src/config.mjs';

function parseArgs(argv) {
  const out = { since: 0, limit: 500, force: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--force') out.force = true;
    else if (a === '--since') out.since = toMs(argv[(i += 1)]);
    else if (a.startsWith('--since=')) out.since = toMs(a.slice(8));
    else if (a === '--limit') out.limit = Number(argv[(i += 1)]) || out.limit;
    else if (a.startsWith('--limit=')) out.limit = Number(a.slice(8)) || out.limit;
  }
  return out;
}

function toMs(value) {
  if (!value) return 0;
  if (/^\d+$/.test(value)) return Number(value);
  const t = Date.parse(value.replace(' ', 'T'));
  return Number.isNaN(t) ? 0 : t;
}

function fmt(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

const args = parseArgs(process.argv.slice(2));
const config = loadConfig();
process.stderr.write(`[cxmcp] ttl=${config.syncTtlSeconds}s since=${args.since || 0}\n`);

try {
  await sync({ force: args.force });
} catch (error) {
  process.stderr.write(`[cxmcp] 同步失败：${error.message}\n`);
  process.exit(4);
}

const index = readIndex();
const rows = [];
for (const conv of index.conversations || []) {
  let session;
  try {
    session = readSession(conv.id);
  } catch {
    continue;
  }
  for (const m of session.messages || []) {
    if (!m.ts || m.ts <= args.since) continue;
    const kind = m.kind && m.kind !== '文本' ? `[${m.kind}] ` : '';
    rows.push({
      time: fmt(m.ts),
      conv: session.name || conv.name || '',
      sender: m.sender || '',
      kind: m.kind || '',
      text: `${kind}${m.text || ''}`.trim(),
    });
  }
}

rows.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
process.stdout.write(`${JSON.stringify(rows.slice(-args.limit))}\n`);

// 子进程调用时 stdin 常是管道，不显式退出会卡在事件循环里
process.exit(0);
