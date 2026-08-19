<template>
  <Teleport to="body">
    <Transition name="erd-fade">
      <div
        v-if="open"
        class="erd-overlay"
        @click.self="onOverlayClick"
      >
        <Transition name="erd-scale">
          <div
            v-if="open"
            ref="dialogRef"
            class="erd-dialog liquid-glass"
            role="dialog"
            aria-modal="true"
            aria-labelledby="erd-title"
            tabindex="-1"
          >
            <button
              type="button"
              class="erd-close"
              :aria-label="t('common.close')"
              @click="close"
            >
              <X :size="18" :stroke-width="1.8" />
            </button>

            <div class="erd-header">
              <div class="erd-icon" :class="iconVariant">
                <component :is="iconComponent" :size="24" :stroke-width="1.8" />
              </div>
              <h2 id="erd-title" class="erd-title">{{ title }}</h2>
            </div>

            <p class="erd-body">{{ bodyText }}</p>

            <div v-if="step === 'form'" class="erd-form">
              <label class="erd-label" for="erd-description">
                {{ t('feedback.textareaLabel') }}
              </label>
              <textarea
                id="erd-description"
                v-model="description"
                class="erd-textarea"
                rows="4"
                :placeholder="t('feedback.textareaPlaceholder')"
              />
              <button
                type="button"
                class="erd-primary-btn"
                :disabled="loading"
                @click="generate"
              >
                <LoaderCircle
                  v-if="loading"
                  class="erd-spin"
                  :size="16"
                  :stroke-width="1.8"
                />
                <span>{{ loading ? t('feedback.generating') : t('feedback.primaryButton') }}</span>
              </button>
            </div>

            <div v-else-if="step === 'success'" class="erd-success">
              <div class="erd-path-row">
                <code class="erd-path">{{ reportPath }}</code>
                <button
                  type="button"
                  class="erd-copy-btn"
                  :class="{ copied: copied }"
                  @click="copyPath"
                >
                  <Check v-if="copied" :size="14" :stroke-width="2" />
                  <Copy v-else :size="14" :stroke-width="2" />
                  <span>{{ copied ? t('feedback.copied') : t('feedback.copyPath') }}</span>
                </button>
              </div>
              <p class="erd-instruction">{{ t('feedback.sendInstructions') }}</p>
              <p class="erd-privacy">{{ t('feedback.privacyNote') }}</p>
              <button type="button" class="erd-secondary-btn" @click="close">
                {{ t('common.close') }}
              </button>
            </div>

            <div v-else-if="step === 'error'" class="erd-error">
              <p>{{ t('feedback.errorBody') }}</p>
              <button
                type="button"
                class="erd-primary-btn"
                :disabled="loading"
                @click="generate"
              >
                <LoaderCircle
                  v-if="loading"
                  class="erd-spin"
                  :size="16"
                  :stroke-width="1.8"
                />
                <span>{{ loading ? t('feedback.generating') : t('feedback.retry') }}</span>
              </button>
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  MessageSquare,
  FileCheck,
  RefreshCw,
  LoaderCircle,
  X,
  Copy,
  Check
} from '@lucide/vue'
import { generateSupportReport } from '../api'

const props = defineProps({
  open: Boolean,
  triggeredByError: { type: Boolean, default: false }
})

const emit = defineEmits(['close'])

const { t } = useI18n()

const step = ref('form') // form | success | error
const loading = ref(false)
const description = ref('')
const reportPath = ref('')
const copied = ref(false)
const dialogRef = ref(null)

let lastFocusedElement = null
let copyTimer = null

const title = computed(() => {
  if (step.value === 'success') return t('feedback.successTitle')
  if (step.value === 'error') return t('feedback.errorTitle')
  return props.triggeredByError ? t('feedback.title') : t('feedback.titleManual')
})

const bodyText = computed(() => {
  if (step.value === 'success') return t('feedback.successBody')
  if (step.value === 'error') return ''
  return t('feedback.body')
})

const iconComponent = computed(() => {
  if (step.value === 'success') return FileCheck
  if (step.value === 'error') return RefreshCw
  return MessageSquare
})

const iconVariant = computed(() => {
  if (step.value === 'success') return 'success'
  if (step.value === 'error') return 'error'
  return 'form'
})

function resetState() {
  step.value = 'form'
  description.value = ''
  reportPath.value = ''
  copied.value = false
  if (copyTimer) {
    clearTimeout(copyTimer)
    copyTimer = null
  }
}

function close() {
  if (loading.value) return
  emit('close')
}

function onOverlayClick() {
  close()
}

function onKeydown(event) {
  if (event.key === 'Escape' && props.open && !loading.value) {
    close()
  }
}

async function generate() {
  loading.value = true
  try {
    const frontendErrors = typeof window.getFrontendErrors === 'function'
      ? window.getFrontendErrors()
      : []
    const response = await generateSupportReport({
      description: description.value.trim(),
      frontendErrors
    })
    reportPath.value = response.data?.report_path || ''
    step.value = 'success'
  } catch (err) {
    console.error('Failed to generate support report:', err)
    step.value = 'error'
  } finally {
    loading.value = false
  }
}

async function copyPath() {
  if (!reportPath.value) return
  const text = reportPath.value
  let succeeded = false
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      succeeded = true
    }
  } catch {
    succeeded = false
  }
  if (!succeeded) {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    textarea.style.pointerEvents = 'none'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      succeeded = document.execCommand('copy')
    } catch {
      succeeded = false
    }
    document.body.removeChild(textarea)
  }
  if (succeeded) {
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copied.value = false
    }, 2000)
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      lastFocusedElement = document.activeElement
      resetState()
      document.addEventListener('keydown', onKeydown)
      nextTick(() => {
        const textarea = dialogRef.value?.querySelector('textarea')
        if (textarea) {
          textarea.focus()
        } else {
          dialogRef.value?.focus()
        }
      })
    } else {
      document.removeEventListener('keydown', onKeydown)
      resetState()
      nextTick(() => {
        if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
          lastFocusedElement.focus()
        }
      })
    }
  }
)
</script>

<style scoped>
.erd-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(16, 32, 58, 0.28);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.erd-dialog {
  position: relative;
  width: min(520px, calc(100vw - 32px));
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  padding: 28px;
  border-radius: 18px;
  outline: none;
  /* 与 liquid-glass 伪元素共享圆角，保持玻璃边缘一致 */
  --lggc-radius: 18px;
}

.erd-close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--mf-ink-muted);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.erd-close:hover {
  background: rgba(255, 255, 255, 0.75);
  color: var(--mf-ink);
}

.erd-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.erd-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #4f6ef7;
  background: rgba(79, 110, 247, 0.12);
}

.erd-icon.success {
  color: #1e9d5c;
  background: rgba(30, 157, 92, 0.12);
}

.erd-icon.error {
  color: #d99b00;
  background: rgba(217, 155, 0, 0.12);
}

.erd-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--mf-ink);
  letter-spacing: -0.2px;
  line-height: 1.3;
}

.erd-body {
  color: var(--mf-ink-muted);
  font-size: 14px;
  line-height: 1.65;
  margin-bottom: 20px;
}

.erd-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.erd-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--mf-ink);
}

.erd-textarea {
  width: 100%;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(16, 32, 58, 0.12);
  background: rgba(255, 255, 255, 0.55);
  font-size: 14px;
  line-height: 1.5;
  color: var(--mf-ink);
  resize: vertical;
  min-height: 96px;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.erd-textarea:focus {
  border-color: rgba(79, 110, 247, 0.5);
  box-shadow: 0 0 0 3px rgba(79, 110, 247, 0.12);
}

.erd-textarea::placeholder {
  color: var(--mf-ink-subtle);
}

.erd-primary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 20px;
  border: none;
  border-radius: 10px;
  background: #4f6ef7;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.15s ease;
}

.erd-primary-btn:hover:not(:disabled) {
  background: #3d5be0;
}

.erd-primary-btn:disabled {
  opacity: 0.75;
  cursor: not-allowed;
}

.erd-secondary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  border: 1px solid rgba(16, 32, 58, 0.14);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--mf-ink);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.erd-secondary-btn:hover {
  background: rgba(255, 255, 255, 0.85);
}

.erd-spin {
  animation: erd-spin 1s linear infinite;
}

@keyframes erd-spin {
  to {
    transform: rotate(360deg);
  }
}

.erd-success {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.erd-path-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.erd-path {
  flex: 1 1 auto;
  min-width: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(16, 32, 58, 0.1);
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--mf-ink);
  word-break: break-all;
}

.erd-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border: 1px solid rgba(16, 32, 58, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.6);
  color: var(--mf-ink);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;
  white-space: nowrap;
}

.erd-copy-btn:hover,
.erd-copy-btn.copied {
  background: rgba(255, 255, 255, 0.92);
  border-color: rgba(79, 110, 247, 0.35);
}

.erd-instruction {
  color: var(--mf-ink);
  font-size: 14px;
  line-height: 1.55;
}

.erd-privacy {
  color: var(--mf-ink-subtle);
  font-size: 12px;
  line-height: 1.55;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(79, 110, 247, 0.06);
}

.erd-error {
  display: flex;
  flex-direction: column;
  gap: 16px;
  color: var(--mf-ink-muted);
  font-size: 14px;
  line-height: 1.65;
}

/* 过渡动画 */
.erd-fade-enter-active,
.erd-fade-leave-active {
  transition: opacity 0.25s ease;
}

.erd-fade-enter-from,
.erd-fade-leave-to {
  opacity: 0;
}

.erd-scale-enter-active,
.erd-scale-leave-active {
  transition: opacity 0.25s ease, transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.erd-scale-enter-from,
.erd-scale-leave-to {
  opacity: 0;
  transform: scale(0.96) translateY(10px);
}

@media (max-width: 480px) {
  .erd-dialog {
    padding: 22px 18px;
    width: min(100%, calc(100vw - 24px));
  }

  .erd-title {
    font-size: 18px;
  }

  .erd-path-row {
    flex-direction: column;
    align-items: stretch;
  }

  .erd-copy-btn {
    justify-content: center;
  }
}
</style>
