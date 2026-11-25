// TV 화면 뼈대 (webOS 위에 AI 친구가 떠 있는 모습).
// 프론트 담당자가 여기서부터 키워 나가면 된다. 이벤트 타입은 src/shared/api/ws.ts (자동 생성).
import { useEffect, useState } from 'react'

type Bubble = { text: string; mode: string } | null
type Nudge = { hint: string } | null

export default function App() {
  const [connected, setConnected] = useState(false)
  const [bubble, setBubble] = useState<Bubble>(null)
  const [nudge, setNudge] = useState<Nudge>(null)
  const [log, setLog] = useState<string[]>([])

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws')
    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ v: 1, type: 'ui.ready', ts: new Date().toISOString(), id: crypto.randomUUID(), data: { screen: 'tv' } }))
    }
    ws.onclose = () => setConnected(false)
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type !== 'clock.tick') setLog((l) => [msg.type, ...l].slice(0, 8))
      if (msg.type === 'buddy.say') setBubble({ text: msg.data.text, mode: msg.data.mode })
      if (msg.type === 'buddy.nudge') setNudge({ hint: msg.data.hint })
    }
    return () => ws.close()
  }, [])

  return (
    <div style={{ background: '#111', color: '#fff', height: '100vh', position: 'relative', fontSize: 28 }}>
      <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: '#555' }}>
        [가상 채널 플레이어 자리]
      </div>
      {nudge && !bubble && (
        <div style={{ position: 'absolute', right: 40, bottom: 40, background: '#A50034', borderRadius: 999, padding: '12px 24px' }}>
          AI 친구 · {nudge.hint}
        </div>
      )}
      {bubble && (
        <div style={{ position: 'absolute', left: 40, right: 40, bottom: 40, background: '#fff', color: '#111', borderRadius: 24, padding: 32 }}>
          {bubble.text}
        </div>
      )}
      <div style={{ position: 'absolute', top: 16, left: 16, fontSize: 14, color: connected ? '#6c6' : '#c66' }}>
        {connected ? '연결됨' : '연결 안 됨 (pnpm mock 또는 백엔드 실행)'} · {log.join(' ← ')}
      </div>
    </div>
  )
}
