// 백엔드 없이 화면을 개발하기 위한 가짜 WebSocket 서버.
// contracts/scenarios/*.jsonl 의 "server" 이벤트를 시간 순서대로 화면에 보낸다.
//
// 실행: pnpm mock            (기본: day1_evening, 60배속)
//       pnpm mock -- day1_evening 10
// 화면은 ws://localhost:8000/ws 로 접속 (진짜 백엔드와 같은 주소)

import { readFileSync } from 'node:fs'
import { WebSocketServer } from 'ws'

const scenario = process.argv[2] ?? 'day1_evening'
const speed = Number(process.argv[3] ?? 60)
const path = new URL(`../../contracts/scenarios/${scenario}.jsonl`, import.meta.url)

const rows = readFileSync(path, 'utf-8')
  .split('\n')
  .filter((l) => l.trim())
  .map((l) => JSON.parse(l))

const toSec = (hms) => hms.split(':').reduce((a, b) => a * 60 + Number(b), 0)

const wss = new WebSocketServer({ port: 8000, path: '/ws' })
console.log(`[mock] ws://localhost:8000/ws  시나리오=${scenario}  배속=${speed}x`)

wss.on('connection', (socket) => {
  console.log('[mock] 화면 접속')
  const t0 = toSec(rows[0].at)
  const timers = rows
    .filter((r) => r.dir === 'server')
    .map((r) =>
      setTimeout(() => {
        socket.send(JSON.stringify({ ...r.event, ts: new Date().toISOString() }))
        console.log(`[mock] → ${r.event.type}`)
      }, ((toSec(r.at) - t0) * 1000) / speed),
    )
  socket.on('message', (m) => console.log(`[mock] ← ${JSON.parse(m).type}`))
  socket.on('close', () => timers.forEach(clearTimeout))
})
