import { onMounted, onUnmounted, ref } from 'vue'

type UseResourceOptions = {
  immediate?: boolean
  refreshIntervalMs?: number
}

type RefreshOptions = {
  silent?: boolean
}

type QueuedRefreshOptions = RefreshOptions & {
  requestId: number
}

export function useResource<T>(
  loader: () => Promise<T>,
  optionsOrImmediate: UseResourceOptions | boolean = true,
) {
  const options =
    typeof optionsOrImmediate === 'boolean' ? { immediate: optionsOrImmediate } : optionsOrImmediate
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let refreshTimer: ReturnType<typeof setInterval> | undefined
  let inFlight = false
  let pendingRefresh: QueuedRefreshOptions | null = null
  let latestRequestId = 0

  async function refresh(refreshOptionsOrEvent: RefreshOptions | Event = {}) {
    const nextOptions =
      refreshOptionsOrEvent instanceof Event ? {} : refreshOptionsOrEvent
    const requestId = ++latestRequestId
    if (inFlight) {
      pendingRefresh = { ...nextOptions, requestId }
      return
    }

    const isSilent = nextOptions.silent === true

    inFlight = true
    if (!isSilent) {
      loading.value = true
    }
    error.value = null
    try {
      const loadedData = await loader()
      if (requestId === latestRequestId) {
        data.value = loadedData
      }
    } catch (err) {
      if (requestId === latestRequestId) {
        error.value = err instanceof Error ? err.message : 'Unknown request error'
      }
    } finally {
      if (!isSilent) {
        loading.value = false
      }
      inFlight = false
      if (pendingRefresh) {
        const queuedOptions = pendingRefresh
        pendingRefresh = null
        void runQueuedRefresh(queuedOptions)
      }
    }
  }

  async function runQueuedRefresh(options: QueuedRefreshOptions) {
    const { requestId, ...refreshOptions } = options
    if (requestId < latestRequestId) {
      return
    }
    await refresh(refreshOptions)
  }

  onMounted(() => {
    if (options.immediate ?? true) {
      void refresh()
    }

    if (options.refreshIntervalMs && options.refreshIntervalMs > 0) {
      refreshTimer = setInterval(() => {
        void refresh({ silent: true })
      }, options.refreshIntervalMs)
    }
  })

  onUnmounted(() => {
    if (refreshTimer) {
      clearInterval(refreshTimer)
    }
  })

  return { data, loading, error, refresh }
}
