import { defineStore } from 'pinia'

import { api } from '../shared/api/client'
import type { SystemStatus } from '../shared/types/workbench'

export const useSystemStore = defineStore('system', {
  state: () => ({
    system: null as SystemStatus | null,
    paused: false,
  }),
  getters: {
    dataLatency: (state) => state.system?.data_latency_seconds ?? null,
    aiProxy: (state) => state.system?.ai_proxy ?? null,
    exchanges: (state) => state.system?.exchanges ?? [],
  },
  actions: {
    async refresh() {
      this.system = await api.getSystemStatus()
      this.paused = this.system.paused
    },
    async probe() {
      this.system = await api.getSystemStatus({ probe: true })
      this.paused = this.system.paused
    },
    async setPaused(paused: boolean, reason = 'manual_pause') {
      const control = await api.updateSystemControl({ paused, reason })
      this.paused = control.paused
      if (this.system) {
        this.system.paused = control.paused
        this.system.kill_switch_armed = control.kill_switch_armed
      }
    },
    async setKillSwitch(armed: boolean, reason = 'manual_kill_switch') {
      const control = await api.updateSystemControl({
        paused: armed ? true : undefined,
        kill_switch_armed: armed,
        reason,
      })
      this.paused = control.paused
      if (this.system) {
        this.system.paused = control.paused
        this.system.kill_switch_armed = control.kill_switch_armed
      }
    },
  },
})
