// Vercel Serverless Function — DeepSeek SSE 代理
import type { VercelRequest, VercelResponse } from '@vercel/node'
import OpenAI from 'openai'

const client = new OpenAI({
  apiKey: process.env.DEEPSEEK_API_KEY || '',
  baseURL: 'https://api.deepseek.com',
})

const SYSTEM_PROMPT = `你是零食电商AI选品助手，为淘宝/京东卖家提供数据驱动建议。
基于用户提供的商品数据上下文给出具体推荐。
回复用简洁中文，每条建议标注证据和局限。`

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') { res.status(405).json({ error: 'POST only' }); return }

  const { messages } = req.body || {}
  if (!messages?.length) { res.status(400).json({ error: 'messages required' }); return }

  const apiMsgs: any[] = [{ role: 'system', content: SYSTEM_PROMPT }]
  for (const m of messages.slice(-12)) {
    apiMsgs.push({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content })
  }

  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')

  try {
    const stream = await client.chat.completions.create({
      model: 'deepseek-chat', messages: apiMsgs, max_tokens: 2048, temperature: 0.3, stream: true,
    })
    let inputTokens = 0, outputTokens = 0
    for await (const c of stream) {
      if (c.choices[0]?.delta?.content) {
        res.write(`data: ${JSON.stringify({ type: 'text', text: c.choices[0].delta.content })}\n\n`)
      }
      if (c.usage) { inputTokens = c.usage.prompt_tokens; outputTokens = c.usage.completion_tokens }
    }
    res.write(`data: ${JSON.stringify({ type: 'done', usage: { input_tokens: inputTokens, output_tokens: outputTokens } })}\n\n`)
    res.end()
  } catch (err: any) {
    res.write(`data: ${JSON.stringify({ type: 'error', message: err.message || 'API error' })}\n\n`)
    res.end()
  }
}
