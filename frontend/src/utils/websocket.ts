import type { WSChannel, WSMessage, WSMessageHandler, WSSubscribeMessage } from '@/types/monitor'

type ConnectionState = 'connecting' | 'connected' | 'disconnected'

class MonitorWebSocket {
  private ws: WebSocket | null = null
  private url: string
  private channels = new Set<WSChannel>()
  private handlers = new Map<string, Set<WSMessageHandler>>()
  private lifecycleHandlers = new Map<string, Set<() => void>>()
  private reconnectAttempts = 0
  private maxReconnectDelay = 30000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private pingTimer: ReturnType<typeof setInterval> | null = null

  state: ConnectionState = 'disconnected'

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // Connect directly to backend, bypass Vite proxy for WebSocket
    const host = window.location.hostname
    this.url = `${protocol}//${host}:8000/api/ws/monitor`
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.state = 'connecting'
    console.log('[WS] connecting to', this.url)
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      this.state = 'connected'
      this.reconnectAttempts = 0
      console.log('[WS] connected')
      if (this.channels.size > 0) {
        this._send({ action: 'subscribe', channels: [...this.channels] })
      }
      this.pingTimer = setInterval(() => {
        this._send({ action: 'ping' })
      }, 30000)
      this._emitLifecycle('open')
    }

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        const channelHandlers = this.handlers.get(msg.channel)
        if (channelHandlers) {
          for (const handler of channelHandlers) {
            handler(msg.data)
          }
        }
      } catch { /* ignore parse errors */ }
    }

    this.ws.onclose = () => {
      this.state = 'disconnected'
      if (this.pingTimer) clearInterval(this.pingTimer)
      this._emitLifecycle('close')
      this._scheduleReconnect()
    }

    this.ws.onerror = (e) => {
      console.error('[WS] error:', e)
      this.ws?.close()
    }
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    if (this.pingTimer) clearInterval(this.pingTimer)
    this.ws?.close()
    this.ws = null
    this.state = 'disconnected'
  }

  subscribe(channels: WSChannel[]) {
    for (const ch of channels) this.channels.add(ch)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this._send({ action: 'subscribe', channels })
    }
  }

  unsubscribe(channels: WSChannel[]) {
    for (const ch of channels) this.channels.delete(ch)
    if (this.ws?.readyState === WebSocket.OPEN) {
      this._send({ action: 'unsubscribe', channels })
    }
  }

  on(event: string, handler: WSMessageHandler | (() => void)) {
    if (event === 'open' || event === 'close') {
      if (!this.lifecycleHandlers.has(event)) {
        this.lifecycleHandlers.set(event, new Set())
      }
      this.lifecycleHandlers.get(event)!.add(handler as () => void)
    } else {
      if (!this.handlers.has(event)) {
        this.handlers.set(event, new Set())
      }
      this.handlers.get(event)!.add(handler as WSMessageHandler)
    }
  }

  off(event: string, handler: WSMessageHandler | (() => void)) {
    if (event === 'open' || event === 'close') {
      this.lifecycleHandlers.get(event)?.delete(handler as () => void)
    } else {
      this.handlers.get(event)?.delete(handler as WSMessageHandler)
    }
  }

  private _emitLifecycle(event: string) {
    this.lifecycleHandlers.get(event)?.forEach((fn) => fn())
  }

  private _send(msg: WSSubscribeMessage | { action: 'ping' }) {
    this.ws?.send(JSON.stringify(msg))
  }

  private _scheduleReconnect() {
    if (this.reconnectTimer) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, this.maxReconnectDelay)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}

export const monitorWs = new MonitorWebSocket()
