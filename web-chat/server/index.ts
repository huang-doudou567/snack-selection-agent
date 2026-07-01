// ── 零食选品 AI 助手 · DeepSeek SSE 代理 ──
import 'dotenv/config';
import express from 'express';
import type { Request, Response } from 'express';
import { spawnSync } from 'child_process';
import OpenAI from 'openai';

const PORT = parseInt(process.env.SERVER_PORT || '3004', 10);
const API_KEY = process.env.DEEPSEEK_API_KEY;
const MODEL = process.env.DEEPSEEK_MODEL || 'deepseek-chat';

if (!API_KEY) {
  console.error('❌ 缺少 DEEPSEEK_API_KEY');
  process.exit(1);
}

const client = new OpenAI({ apiKey: API_KEY, baseURL: 'https://api.deepseek.com' });

// ── 系统提示词 ──
const SYSTEM_PROMPT = `你是零食电商的AI选品决策助手。你有13,400种零食商品数据（价格、品牌、品类、销量）。

## 核心能力
- 📊 品类竞争分析：品牌梯队、价格带、集中度
- 🎯 选品推荐：按品类+预算推荐高性价比商品
- 🏷️ 精准比价：品牌×品类的每克单价对比
- 💰 促销策略：满减/直降/优惠券效果分析
- 📦 清仓定价：基于市场数据给出清仓方案
- 😡 差评归因：分类差评原因，给改品建议

## 行为准则
🔴 先查询数据，后给建议。绝不凭记忆编造商品信息。
🔴 每条建议标注数据来源（文件名/行号）和置信度。
如果不知道该回答什么，说"当前数据不支持该结论"。

## 回复格式
1. 先一句话回应用户的选品需求
2. 展示关键数据发现（表格）
3. 给2-3条具体建议，每条标注证据和局限
4. 如果数据覆盖率<10%，明确标注

## 禁止：编造商品名/价格/品牌、隐藏数据局限、替用户做进货决策
回复用中文，简洁专业。`;

// ── 上下文构建：读取 CSV 数据摘要 ──
function buildContextBlock(): string {
  const lines: string[] = ['[数据上下文]', ''];

  // 数据源概况
  const projectDir = process.env.PROJECT_DIR || '..';
  lines.push(`商品数据：${projectDir}/integrated_selection_products.csv（13,400 条）`);
  lines.push(`价格历史：${projectDir}/price_history.csv（慢慢买数据）`);
  lines.push('覆盖情况：京东评论 3.2%，慢慢买价格 2.4%');
  lines.push('');

  // 品类概览
  try {
    const result = spawnSync('python', [
      '-c',
      `import pandas as pd
df = pd.read_csv("../integrated_selection_products.csv")
cats = df["二级分类"].value_counts().head(10)
for c, n in cats.items():
    print(f"  {c}: {n} 种")`,
    ], { encoding: 'utf-8', timeout: 5000 });
    if (result.stdout) {
      lines.push('## 品类分布（TOP 10）');
      lines.push(result.stdout.trim());
    }
  } catch { lines.push('（品类数据加载失败）'); }

  lines.push('');
  lines.push('## 品牌 TOP 10');
  try {
    const result = spawnSync('python', [
      '-c',
      `import pandas as pd
df = pd.read_csv("../integrated_selection_products.csv")
brands = df["品牌"].value_counts().head(10)
for b, n in brands.items():
    print(f"  {b}: {n} 种")`,
    ], { encoding: 'utf-8', timeout: 5000 });
    if (result.stdout) {
      lines.push(result.stdout.trim());
    }
  } catch { lines.push('（品牌数据加载失败）'); }

  lines.push('');
  lines.push('## 价格带概览');
  try {
    const result = spawnSync('python', [
      '-c',
      `import pandas as pd
df = pd.read_csv("../integrated_selection_products.csv")
prices = pd.to_numeric(df["现价"], errors="coerce").dropna()
print(f"  最低: {prices.min():.1f}元  最高: {prices.max():.1f}元  均价: {prices.mean():.1f}元")`,
    ], { encoding: 'utf-8', timeout: 5000 });
    if (result.stdout) lines.push(result.stdout.trim());
  } catch { lines.push('（价格数据加载失败）'); }

  lines.push('');
  lines.push('[/数据上下文]');
  return lines.join('\n');
}

// ── Express ──
const app = express();
app.use(express.json({ limit: '1mb' }));
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (_req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', model: MODEL, provider: 'deepseek' });
});

app.post('/api/chat', async (req: Request, res: Response) => {
  const { messages } = req.body as {
    messages: { role: 'user' | 'assistant'; content: string }[];
  };
  if (!messages?.length) { res.status(400).json({ error: 'messages required' }); return; }

  const contextBlock = buildContextBlock();
  const apiMessages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'system', content: contextBlock },
  ];
  for (const msg of messages) {
    apiMessages.push({
      role: msg.role === 'assistant' ? 'assistant' : 'user',
      content: msg.content,
    });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  try {
    const stream = await client.chat.completions.create({
      model: MODEL, messages: apiMessages, max_tokens: 4096, stream: true,
    });
    const heartbeat = setInterval(() => { res.write(': heartbeat\n\n'); }, 15000);
    let finishReason = 'stop', inputTokens = 0, outputTokens = 0;
    for await (const chunk of stream) {
      if (chunk.choices[0]?.delta?.content) {
        res.write(`data: ${JSON.stringify({ type: 'text', text: chunk.choices[0].delta.content })}\n\n`);
      }
      if (chunk.choices[0]?.finish_reason) finishReason = chunk.choices[0].finish_reason;
      if (chunk.usage) { inputTokens = chunk.usage.prompt_tokens; outputTokens = chunk.usage.completion_tokens; }
    }
    clearInterval(heartbeat);
    res.write(`data: ${JSON.stringify({ type: 'done', stop_reason: finishReason, usage: { input_tokens: inputTokens, output_tokens: outputTokens, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } })}\n\n`);
    res.end();
  } catch (error: unknown) {
    let msg = '未知错误'; let type = 'unknown';
    if (error instanceof OpenAI.AuthenticationError) { msg = 'API Key 无效'; type = 'auth_error'; }
    else if (error instanceof OpenAI.RateLimitError) { msg = '速率限制'; type = 'rate_limit'; }
    else if (error instanceof Error) { msg = error.message; }
    res.write(`data: ${JSON.stringify({ type: 'error', message: msg, errorType: type })}\n\n`);
    res.end();
  }
});

app.listen(PORT, () => {
  console.log(`🛒 零食选品 AI 助手 · API 已启动`);
  console.log(`   http://localhost:${PORT}/api/chat`);
  console.log(`   模型：${MODEL}`);
});
