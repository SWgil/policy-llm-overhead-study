// Stand-in guard sidecar: @stackone/defender (MiniLM, same team as the paper).
// Reads {tool, text} JSON lines on stdin, writes {allowed, risk, score} JSON lines.
import { createPromptDefense } from '@stackone/defender';
import readline from 'node:readline';
const defense = createPromptDefense({ blockHighRisk: true, sanitizeContent: false, requireTier2: true });
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const { tool, text } = JSON.parse(line);
  const t = Date.now();
  const r = await defense.defendToolResult(text, tool);
  process.stdout.write(JSON.stringify({ allowed: r.allowed, risk: r.riskLevel, score: r.tier2Score ?? null,
    detections: r.detections ?? [], ms: Date.now() - t }) + '\n');
}
