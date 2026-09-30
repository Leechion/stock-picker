import { onMounted, onUnmounted, ref, type Ref } from 'vue'
import { getQuotes } from '@/api/quotes'
import { monitorWs } from '@/utils/websocket'
import type { WSQuotesPayload } from '@/types/monitor'

export interface LiveQuote {
  code: string
  price: number
  change_pct: number
  high?: number
  low?: number
  volume?: number
  amount?: number
  /** True for ~600ms after a change, so the UI can flash the cell. */
  flash?: boolean
}

/**
 * Keep a set of stock codes priced in realtime.
 *
 * Two sources, deliberately:
 *   1. One REST call for the initial paint (works even if the socket is down).
 *   2. `quotes` WebSocket deltas thereafter — the server only sends codes whose
 *      price actually moved, so this stays cheap for thousands of stocks.
 *
 * Usage:
 *   const { quotes, connected } = useLiveQuotes(() => rows.value.map(r => r.code))
 */
export function useLiveQuotes(codesSource: () => string[]) {
  const quotes = ref<Map<string, LiveQuote>>(new Map()) as Ref<Map<string, LiveQuote>>
  const connected = ref(false)
  const lastUpdate = ref<string>('')
  const flashTimers = new Map<string, ReturnType<typeof setTimeout>>()

  /** Load a first snapshot for the currently visible codes. */
  async function loadSnapshot() {
    const codes = codesSource().filter(Boolean)
    if (codes.length === 0) return
    try {
      const { data } = await getQuotes(codes)
      const body = data as { items?: LiveQuote[] }
      const next = new Map(quotes.value)
      for (const q of body.items ?? []) {
        next.set(q.code, { ...q, flash: false })
      }
      quotes.value = next
      lastUpdate.value = new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    } catch {
      /* keep whatever we already have */
    }
  }

  function applyPush(payload: WSQuotesPayload) {
    if (!payload?.items?.length) return
    // Only track codes the caller cares about — the push covers the whole
    // market, but a view showing 20 rows should not re-render for 3000.
    const wanted = new Set(codesSource())
    const next = new Map(quotes.value)
    let touched = false

    for (const item of payload.items) {
      if (!wanted.has(item.code)) continue
      const prev = next.get(item.code)
      next.set(item.code, { ...prev, ...item, flash: true })
      touched = true

      // Clear the flash flag shortly after, so the cell highlight fades.
      const existing = flashTimers.get(item.code)
      if (existing) clearTimeout(existing)
      flashTimers.set(
        item.code,
        setTimeout(() => {
          const cur = next.get(item.code)
          if (cur) next.set(item.code, { ...cur, flash: false })
          quotes.value = new Map(next)
          flashTimers.delete(item.code)
        }, 600)
      )
    }

    if (touched) {
      quotes.value = next
      lastUpdate.value = new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    }
  }

  // `monitorWs.on()` does not return an unsubscribe function, so keep stable
  // handler references and call `off()` with them on teardown.
  const handler = (data: unknown) => applyPush(data as WSQuotesPayload)
  let teardown: (() => void) | null = null

  onMounted(() => {
    loadSnapshot()
    monitorWs.on('quotes', handler)
    monitorWs.subscribe(['quotes'])
    connected.value = monitorWs.state === 'connected'
    const onOpen = () => {
      connected.value = true
      // Re-subscribe after a reconnect: the server forgets us on close.
      monitorWs.subscribe(['quotes'])
      // And re-sync, since we may have missed deltas while disconnected.
      loadSnapshot()
    }
    const onClose = () => {
      connected.value = false
    }
    monitorWs.on('open', onOpen)
    monitorWs.on('close', onClose)
    teardown = () => {
      monitorWs.off('quotes', handler)
      monitorWs.off('open', onOpen)
      monitorWs.off('close', onClose)
    }
  })

  onUnmounted(() => {
    teardown?.()
    for (const t of flashTimers.values()) clearTimeout(t)
    flashTimers.clear()
    monitorWs.unsubscribe(['quotes'])
  })

  /** Re-fetch the snapshot (used when the visible page changes). */
  function refresh() {
    return loadSnapshot()
  }

  return { quotes, connected, lastUpdate, refresh }
}
