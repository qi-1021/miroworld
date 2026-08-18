<template>
  <div class="step-card step-conflict">
    <div class="card-header">
      <div class="step-info">
        <span class="step-num">2</span>
        <span class="step-title">{{ $t('world.conflictTitle') }}</span>
      </div>
      <div class="step-status">
        <span v-if="report.conflicts.length" class="badge processing">
          {{ $t('world.conflictCount', { count: report.conflicts.length }) }}
        </span>
        <span v-else class="badge success">{{ $t('world.noConflict') }}</span>
        <button v-if="report.conflicts.length" class="mini-btn" :class="{ active: conflictSelMode }" @click="$emit('toggle-sel-mode')">
          {{ conflictSelMode ? $t('world.batchExit') : $t('world.batchSelect') }}
        </button>
        <template v-if="conflictSelMode">
          <span class="bat-count">{{ $t('world.batchSelectedCount', { n: selConflictIds.length }) }}</span>
          <button class="mini-btn primary" :disabled="!selConflictIds.length || batchConflictBusy" @click="$emit('batch-accept')">{{ $t('world.batchAccept') }}</button>
          <button class="mini-btn" :disabled="!selConflictIds.length || batchConflictBusy" @click="$emit('batch-dismiss')">{{ $t('world.batchDismiss') }}</button>
          <button class="mini-btn" @click="$emit('batch-clear')">{{ $t('world.batchClear') }}</button>
        </template>
      </div>
    </div>

    <div class="report-meta">
      <template v-if="report.meta">
        {{ $t('world.detectedAt') }} {{ formatTime(report.created_at) }} ·
        {{ $t('world.bgFacts', { count: report.meta.background_facts }) }} / {{ $t('world.storyFacts', { count: report.meta.story_facts }) }}
      </template>
      <template v-else>
        {{ $t('world.detectedAt') }} {{ formatTime(report.created_at) }}
      </template>
    </div>

    <div v-if="report.error" class="msg-line error">{{ report.error }}</div>

    <div v-if="!report.conflicts.length && report.status === 'completed'" class="empty-note">
      {{ $t('world.noConflictNote') }}
    </div>

    <div v-else class="conflict-list">
      <div v-for="c in report.conflicts" :key="c.conflict_id" class="conflict-item" :class="'sev-' + c.severity + (conflictSelMode ? ' sel-mode' : '')">
        <div class="conflict-head">
          <span v-if="conflictSelMode" class="conflict-sel" @click.stop="$emit('toggle-conflict-select', c)">
            <span class="sel-box" :class="{ checked: selConflictIds.includes(c.conflict_id) }"></span>
          </span>
          <span class="detail-type-badge">{{ typeLabel(c.conflict_type) }}</span>
          <span class="severity-tag" :class="'sev-' + c.severity">{{ sevLabel(c.severity) }}</span>
          <span class="conflict-topic">{{ c.topic }}</span>
          <span class="conflict-status" :class="c.status">{{ statusLabel(c.status) }}</span>
        </div>

        <div class="conflict-compare">
          <div class="side-box">
            <div class="side-label bg">{{ $t('world.bgSide') }}</div>
            <div class="side-fact">{{ c.background_fact }}</div>
            <div v-if="c.background_quote" class="side-quote">"{{ c.background_quote }}"</div>
          </div>
          <div class="vs-mark">⇄</div>
          <div class="side-box">
            <div class="side-label st">{{ $t('world.storySide') }}</div>
            <div class="side-fact">{{ c.story_fact }}</div>
            <div v-if="c.story_quote" class="side-quote">"{{ c.story_quote }}"</div>
          </div>
        </div>

        <div v-if="c.reason" class="conflict-reason">{{ $t('world.reason') }}{{ c.reason }}</div>
        <div v-if="c.suggestion" class="conflict-suggestion">{{ $t('world.suggestion') }}{{ c.suggestion }}</div>

        <div class="conflict-actions">
          <button
            class="mini-btn primary refute-btn"
            :class="{ active: c.status === 'justified' }"
            :disabled="justifyingId === c.conflict_id"
            @click="$emit('toggle-justify', c)"
          >
            ⚔️ {{ c.justifyOpen ? $t('world.justifyCancel') : $t('world.refuteConflict') }}
          </button>
          <button
            v-for="s in ['accepted', 'dismissed']"
            :key="s"
            class="mini-btn"
            :class="{ active: c.status === s }"
            :disabled="c.status === s || justifyingId === c.conflict_id"
            @click="$emit('set-conflict-status', { conflict: c, status: s })"
          >
            {{ s === 'accepted' ? $t('world.acceptBg') : $t('world.dismissConflict') }}
          </button>
          <button
            v-if="c.defense_rounds && c.defense_rounds.length"
            class="mini-btn"
            @click="$emit('toggle-conflict-history', c)"
          >
            {{ c.historyOpen ? $t('world.defenseHistoryHide') : $t('world.defenseHistoryShow') }}
          </button>
        </div>
        <div v-if="c.justifyOpen" class="conflict-justify">
          <textarea
            v-model="c.justifyNote"
            class="justify-input"
            rows="2"
            :placeholder="$t('world.justifyPlaceholder')"
          ></textarea>
          <button
            class="mini-btn primary"
            :disabled="justifyingId === c.conflict_id || !(c.justifyNote || '').trim()"
            @click="$emit('submit-justify', c)"
          >
            {{ justifyingId === c.conflict_id ? $t('world.justifying') : $t('world.justifySubmit') }}
          </button>
        </div>
        <div v-if="c.resolution_note" class="conflict-resolution-note">
          <span class="crn-label">{{ $t('world.justifyNoteLabel') }}</span>
          <span class="crn-text">{{ c.resolution_note }}</span>
        </div>
        <div v-if="c.follow_up_effect" class="conflict-followup">
          <span class="cfu-label">{{ $t('world.followUpEffectLabel') }}</span>
          <span class="cfu-text">{{ c.follow_up_effect }}</span>
        </div>
        <div v-if="c.defense_rounds && c.defense_rounds.length && (c.historyOpen || !c.defense_rounds.some(r => r.role === 'assistant'))" class="conflict-defense-history">
          <div class="cdh-title">{{ $t('world.defenseHistory') }}</div>
          <div
            v-for="(r, ri) in c.defense_rounds"
            :key="ri"
            class="defense-round"
            :class="{ user: r.role === 'user', assistant: r.role === 'assistant' }"
          >
            <div class="defense-round-head">
              <span class="defense-role">{{ r.role === 'user' ? $t('world.defenseUser') : $t('world.defenseAssistant') }}</span>
              <span v-if="r.verdict" class="defense-verdict">{{ defenseVerdictLabel(r.verdict) }}</span>
            </div>
            <p class="defense-content">{{ r.content }}</p>
            <div v-if="r.effect" class="defense-effect">
              <span class="de-label">{{ $t('world.effectLabel') }}</span>
              <span class="de-text">{{ r.effect }}</span>
            </div>
          </div>
        </div>
        <div class="correction-block">
          <!-- 成功/失败反馈条 -->
          <div v-if="c.corrNotice" class="corr-notice" :class="{ ok: c.corrNotice.ok, err: !c.corrNotice.ok }">
            <span class="corr-notice-ico">{{ c.corrNotice.ok ? '✓' : '✕' }}</span>
            <span class="corr-notice-text">{{ c.corrNotice.text }}</span>
          </div>
          <div class="correction-actions">
            <button
              class="mini-btn correction-gen"
              :disabled="corrGeneratingId === c.conflict_id"
              @click="$emit('load-conflict-corrections', { conflict: c, force: true })"
            >
              {{ corrGeneratingId === c.conflict_id
                  ? $t('world.corrGenerating')
                  : (c.corrections?.hasFiles ? $t('world.corrRegenerate') : $t('world.corrGenerate')) }}
            </button>
          </div>
          <div v-if="c.corrections && c.corrections.hasFiles" class="correction-files">
            <div class="correction-files-head">
              <span class="cfh-title">{{ $t('world.corrFilesTitle') }}（{{ c.corrections.patchCount }} {{ $t('world.corrPatchLabel') }}）</span>
              <button class="mini-btn" @click="c.corrOpen = !c.corrOpen">
                {{ c.corrOpen ? $t('world.corrHidePreview') : $t('world.corrShowPreview') }}
              </button>
            </div>
            <!-- 空结果说明 -->
            <div v-if="c.corrections.emptyReason" class="corr-empty-reason">
              {{ c.corrections.emptyReason === 'empty_annotations_only'
                  ? $t('world.corrEmptyReasonAnnotations')
                  : $t('world.corrEmptyReasonNoRulings') }}
            </div>
            <div v-if="c.corrOpen" class="correction-files-body">
              <!-- 注解清单：无文本补丁时也展示生效裁定注解，避免用户以为失败 -->
              <div v-if="c.corrections.annotations && c.corrections.annotations.length" class="correction-annotations">
                <div class="corr-ann-title">{{ $t('world.corrAnnotationsTitle') }}</div>
                <div
                  v-for="(a, ai) in c.corrections.annotations"
                  :key="ai"
                  class="correction-annotation"
                >
                  <span class="ca-status" :class="a.verdict || a.status">{{ a.status }}</span>
                  <span class="ca-topic">{{ a.topic }}</span>
                  <span v-if="a.action" class="ca-action">{{ a.action }}</span>
                  <p class="ca-note">{{ a.note }}</p>
                </div>
              </div>
              <!-- 文本补丁清单 -->
              <div v-if="c.corrections.patches && c.corrections.patches.length" class="correction-patch-list">
                <div
                  v-for="(p, pi) in c.corrections.patches"
                  :key="pi"
                  class="correction-patch"
                >
                  <div class="correction-patch-head">
                    <span class="cp-op">{{ p.op }}</span>
                    <span class="cp-src">{{ p.source }}</span>
                    <span class="cp-cid">{{ p.conflict_id }}</span>
                  </div>
                  <div class="cp-line"><span class="cp-label">{{ $t('world.corrLocator') }}</span>“{{ p.locator }}”</div>
                  <div v-if="p.new_text" class="cp-line"><span class="cp-label">{{ $t('world.corrNewText') }}</span>“{{ p.new_text }}”</div>
                  <div v-if="p.note" class="cp-note">{{ p.note }}</div>
                </div>
              </div>
              <div v-if="!c.corrections.patches.length && !(c.corrections.annotations && c.corrections.annotations.length)" class="correction-empty">{{ $t('world.corrNoPatch') }}</div>
              <!-- 渲染合并全文 -->
              <div class="correction-render">
                <span class="cr-label">{{ $t('world.corrRenderMerged') }}</span>
                <button class="mini-btn" :disabled="confRenderBusyId === c.conflict_id" @click="$emit('render-merged', { conflict: c, source: 'story' })">
                  {{ $t('world.corrRenderStory') }}
                </button>
                <button class="mini-btn" :disabled="confRenderBusyId === c.conflict_id" @click="$emit('render-merged', { conflict: c, source: 'settings' })">
                  {{ $t('world.corrRenderSettings') }}
                </button>
                <a
                  class="correction-download"
                  :href="confCorrectionRenderUrl(projectId, c.conflict_id, 'story', true)"
                  target="_blank"
                >{{ $t('world.corrDownloadStory') }}</a>
                <span class="cr-sep">|</span>
                <a class="correction-download" :href="correctionDownloadUrl(projectId, c.conflict_id, 'corrected_patches.md')" download>{{ $t('world.corrDownloadPatch') }}</a>
                <a class="correction-download" :href="correctionDownloadUrl(projectId, c.conflict_id, 'corrections.json')" download>corrections.json</a>
              </div>
              <div v-if="c.corrMerged" class="correction-merged">
                <div class="correction-merged-head">
                  <span class="cmh-title">{{ c.corrMerged.source === 'story' ? $t('world.corrMergedStory') : $t('world.corrMergedSettings') }}</span>
                  <span class="cmh-meta">{{ $t('world.corrApplied', { n: c.corrMerged.applied.length }) }} / {{ $t('world.corrSkipped', { n: c.corrMerged.skipped.length }) }}</span>
                </div>
                <pre class="correction-preview">{{ c.corrMerged.text }}</pre>
              </div>
            </div>
          </div>
          <div v-else-if="c.corrections && c.corrections.loaded && !c.corrections.hasFiles" class="correction-empty">
            {{ $t('world.corrEmpty') }}
          </div>
          <!-- 具体错误展示 -->
          <div v-if="c.corrections && c.corrections.error" class="corr-error">
            {{ c.corrections.error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { correctionDownloadUrl } from '../../api/world'

const { t } = useI18n()

defineProps({
  report: { type: Object, required: true },
  projectId: { type: String, required: true },
  conflictSelMode: { type: Boolean, default: false },
  selConflictIds: { type: Array, default: () => [] },
  batchConflictBusy: { type: Boolean, default: false },
  justifyingId: { type: String, default: '' },
  corrGeneratingId: { type: String, default: '' },
  confRenderBusyId: { type: String, default: '' }
})

defineEmits([
  'toggle-sel-mode',
  'batch-accept',
  'batch-dismiss',
  'batch-clear',
  'toggle-conflict-select',
  'toggle-justify',
  'set-conflict-status',
  'toggle-conflict-history',
  'submit-justify',
  'load-conflict-corrections',
  'render-merged'
])

function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

function typeLabel(type) {
  const map = {
    hard_contradiction: t('world.hardConflict'),
    soft_divergence: t('world.softConflict'),
    timeline_mismatch: t('world.timeConflict'),
    character_inconsistency: t('world.charConflict'),
    setting_gap: t('world.settingGap')
  }
  return map[type] || type
}

function sevLabel(s) {
  const map = { high: t('world.sevHigh'), medium: t('world.sevMed'), low: t('world.sevLow') }
  return map[s] || s
}

function statusLabel(s) {
  const map = {
    pending: t('world.statusPending'),
    justified: t('world.statusJustified'),
    accepted: t('world.statusAccepted'),
    dismissed: t('world.statusDismissed')
  }
  return map[s] || s
}

function defenseVerdictLabel(v) {
  const map = {
    overruled: t('world.verdictOverruled'),
    sustained: t('world.verdictSustained'),
    partial: t('world.verdictPartial')
  }
  return map[v] || v
}

function confCorrectionRenderUrl(pid, cid, source, dl) {
  return `/api/world/${encodeURIComponent(pid)}/conflicts/${encodeURIComponent(cid)}/render-correction?source=${source}&download=${dl ? '1' : '0'}`
}
</script>
