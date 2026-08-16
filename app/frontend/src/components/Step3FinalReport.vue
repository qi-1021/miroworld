<template>
  <div class="final-report">
    <!-- 顶部操作条 -->
    <div class="fr-toolbar">
      <div class="fr-toolbar-title">
        <span class="fr-title-num">FINAL</span>
        <span class="fr-title-text">{{ $t('finalReport.title') }}</span>
      </div>
      <div class="fr-toolbar-actions">
        <button class="mini-btn" :disabled="generating" @click="generate">
          {{ generating ? $t('finalReport.generating') : (hasReport ? $t('finalReport.regenerate') : $t('finalReport.generate')) }}
        </button>
        <a
          v-if="hasReport"
          class="mini-btn primary"
          :href="downloadUrl"
          download
          :title="$t('finalReport.downloadHint')"
        >⬇ {{ $t('finalReport.download') }}</a>
      </div>
    </div>

    <!-- 👑 最佳流向徽标 -->
    <div v-if="bestFlow" class="fr-bestflow" :title="$t('finalReport.bestFlowHint')">
      <span class="fr-crown">👑</span>
      <span class="fr-bestflow-body">
        <span class="fr-bestflow-label">{{ $t('finalReport.bestFlow') }}</span>
        <span class="fr-bestflow-id">{{ bestFlow.simulation_id }}</span>
      </span>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="fr-state">{{ $t('finalReport.loading') }}</div>

    <!-- 空态：尚未生成 -->
    <div v-else-if="!hasReport" class="fr-state empty">
      <p>{{ $t('finalReport.empty') }}</p>
    </div>

    <!-- 有报告：梗概 + 正文 -->
    <template v-else>
      <div class="fr-tabs" role="tablist">
        <button
          class="fr-tab"
          :class="{ active: tab === 'synopsis' }"
          @click="tab = 'synopsis'"
        >{{ $t('finalReport.tabSynopsis') }}</button>
        <button
          class="fr-tab"
          :class="{ active: tab === 'novel' }"
          @click="tab = 'novel'"
        >{{ $t('finalReport.tabNovel') }}</button>
      </div>

      <div class="fr-meta">
        <span v-if="report.generated_at" class="fr-meta-item">🕒 {{ report.generated_at }}</span>
        <span v-if="report.events_count != null" class="fr-meta-item">◈ {{ report.events_count }} {{ $t('finalReport.events') }}</span>
        <span v-if="report.structure?.type" class="fr-meta-item">⊞ {{ structureLabel }}</span>
        <span v-if="report.deterministic" class="fr-meta-item">✓ {{ $t('finalReport.deterministic') }}</span>
      </div>

      <div class="fr-body">
        <pre v-if="tab === 'synopsis'" class="fr-pre">{{ report.synopsis || $t('finalReport.noSynopsis') }}</pre>
        <pre v-else class="fr-pre">{{ report.novel || $t('finalReport.noNovel') }}</pre>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getFinalReport, generateFinalReport, finalReportDownloadUrl } from '../api/timeline'

const props = defineProps({
  projectId: { type: String, default: '' }
})
const emit = defineEmits(['add-log', 'next-step', 'go-back'])

const { t } = useI18n()

const loading = ref(false)
const generating = ref(false)
const hasReport = ref(false)
const report = ref({})
const tab = ref('synopsis')
const bestFlow = ref(null)

const downloadUrl = computed(() => (props.projectId ? finalReportDownloadUrl(props.projectId) : '#'))

const structureLabel = computed(() => {
  const s = report.value?.structure
  if (!s?.type) return ''
  const map = {
    single: t('finalReport.structureSingle'),
    parallel: t('finalReport.structureParallel'),
    tree: t('finalReport.structureTree'),
    network: t('finalReport.structureNetwork'),
    meta: t('finalReport.structureMeta'),
    mixed: t('finalReport.structureMixed')
  }
  return map[s.type] || s.type
})

const addLog = (msg) => emit('add-log', msg)

const load = async () => {
  if (!props.projectId) return
  loading.value = true
  try {
    const res = await getFinalReport(props.projectId)
    if (res?.success && res.data) {
      hasReport.value = !!res.data.has_report
      if (hasReport.value) {
        report.value = res.data
        bestFlow.value = res.data.best_flow || null
        // 默认优先展示梗概（整体先看大结构）
        tab.value = 'synopsis'
      }
    } else if (res?.error) {
      addLog(res.error)
    }
  } catch (e) {
    addLog('读取最终时间线报告失败：' + (e?.message || String(e)))
  } finally {
    loading.value = false
  }
}

const generate = async () => {
  if (!props.projectId || generating.value) return
  generating.value = true
  try {
    const res = await generateFinalReport(props.projectId)
    if (res?.success && res.data) {
      hasReport.value = true
      report.value = res.data
      bestFlow.value = res.data.best_flow || null
      addLog('最终时间线报告已生成。')
    } else if (res?.error) {
      addLog(res.error)
    }
  } catch (e) {
    addLog('生成最终时间线报告失败：' + (e?.message || String(e)))
  } finally {
    generating.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.final-report {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  min-height: 0;
}

.fr-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}
.fr-toolbar-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.fr-title-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: #E0E0E0;
}
.fr-title-text { font-size: 15px; font-weight: 600; color: #10203a; }
.fr-toolbar-actions { display: flex; gap: 8px; flex-shrink: 0; }

.mini-btn {
  border: 1px solid rgba(16,32,58,0.14);
  background: #fff;
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 13px;
  font-family: inherit;
  color: #10203a;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: border-color 0.2s, background 0.2s, transform 0.12s;
}
.mini-btn:hover:not(:disabled) { border-color: #a1c50a; }
.mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mini-btn.primary {
  background: #a1c50a;
  border-color: #a1c50a;
  color: #fff;
  font-weight: 600;
}

/* 👑 最佳流向徽标 */
.fr-bestflow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid rgba(161,197,10,0.4);
  border-radius: 12px;
  background: rgba(161,197,10,0.10);
  flex-shrink: 0;
}
.fr-crown { font-size: 20px; line-height: 1; }
.fr-bestflow-body { display: flex; flex-direction: column; min-width: 0; }
.fr-bestflow-label { font-size: 11px; font-weight: 600; color: #5f7008; text-transform: uppercase; letter-spacing: 0.05em; }
.fr-bestflow-id { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #10203a; word-break: break-all; }

.fr-state { padding: 32px 16px; text-align: center; color: #7b879e; font-size: 14px; }
.fr-state.empty { border: 1px dashed var(--mf-hairline, rgba(16,32,58,0.14)); border-radius: 12px; }

.fr-tabs {
  display: inline-flex;
  gap: 4px;
  background: #ececee;
  border-radius: 999px;
  padding: 4px;
  align-self: flex-start;
  flex-shrink: 0;
}
.fr-tab {
  border: none;
  background: transparent;
  border-radius: 999px;
  padding: 7px 22px;
  font-size: 13px;
  font-family: inherit;
  color: #7b879e;
  cursor: pointer;
  transition: background 0.18s, color 0.18s;
}
.fr-tab.active { background: #fff; color: #10203a; font-weight: 600; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }

.fr-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: #7b879e; flex-shrink: 0; }

.fr-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border: 1px solid rgba(16,32,58,0.08);
  border-radius: 12px;
  background: rgba(255,255,255,0.4);
}
.fr-pre {
  margin: 0;
  padding: 16px 18px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.75;
  color: #10203a;
}
</style>
