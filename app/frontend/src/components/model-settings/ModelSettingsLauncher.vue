<template>
  <button
    type="button"
    class="model-settings-launcher"
    :class="{ active: open }"
    :title="$t('modelSettings.open')"
    :aria-label="$t('modelSettings.open')"
    @click="$emit('toggle')"
  >
    <Settings2 :size="18" :stroke-width="1.8" />
    <span class="launcher-copy">
      <strong>{{ $t('modelSettings.shortTitle') }}</strong>
      <small>{{ summary }}</small>
    </span>
    <span class="launcher-dot" :class="status"></span>
  </button>
</template>

<script setup>
import { Settings2 } from '@lucide/vue'

defineProps({
  open: Boolean,
  summary: { type: String, default: '' },
  status: { type: String, default: 'idle' }
})

defineEmits(['toggle'])
</script>

<style scoped>
.model-settings-launcher {
  position: fixed;
  right: 18px;
  top: 72px;
  z-index: 890;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 8px;
  align-items: center;
  gap: 9px;
  width: min(230px, calc(100vw - 36px));
  min-height: 46px;
  padding: 8px 10px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: saturate(160%) blur(12px);
  -webkit-backdrop-filter: saturate(160%) blur(12px);
  color: #10203a;
  box-shadow: 0 7px 20px rgba(16, 32, 58, 0.14);
  cursor: pointer;
  text-align: left;
}

.model-settings-launcher:hover,
.model-settings-launcher.active {
  border-color: #a1c50a;
}

.launcher-copy {
  min-width: 0;
}

.launcher-copy strong,
.launcher-copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.launcher-copy strong {
  font-size: 11px;
}

.launcher-copy small {
  margin-top: 3px;
  color: #686868;
  font-size: 9px;
}

.launcher-dot {
  width: 8px;
  height: 8px;
  background: #9b9b9b;
}

.launcher-dot.ready { background: #1e9d5c; }
.launcher-dot.warning { background: #d99b00; }
.launcher-dot.error { background: #d33b32; }

@media (max-width: 700px) {
  .model-settings-launcher {
    top: auto;
    right: 12px;
    bottom: 12px;
    width: 48px;
    height: 48px;
    min-height: 48px;
    grid-template-columns: 1fr;
    place-items: center;
    padding: 0;
  }

  .launcher-copy,
  .launcher-dot { display: none; }
}
</style>
