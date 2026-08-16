<template>
  <div class="world-view" :class="{ 'high-contrast': highContrast }">
    <!-- 顶部导航（与主界面一致） -->
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="goBack">MIROWORLD</div>
        <div class="step-divider"></div>
        <div class="workflow-step">
          <span class="step-num">WORLD</span>
          <span class="step-name">{{ $t('world.headerTitle') }}</span>
        </div>
      </div>
      <div class="header-right">
        <button class="back-btn ghost" @click="highContrast = !highContrast">{{ highContrast ? $t('world.contrastOff') : $t('world.contrastOn') }}</button>
        <span class="project-id">{{ projectId }}</span>
        <button class="back-btn" :disabled="snapshotBusy" @click="exportSnapshot">{{ $t('world.exportSnapshot') }}</button>
        <button class="back-btn" :disabled="snapshotBusy" @click="importFileInput.click()">{{ $t('world.importSnapshot') }}</button>
        <input ref="importFileInput" type="file" accept=".json,.miroworld.json,application/json" style="display:none" @change="onImportSnapshot" />
        <button class="back-btn" @click="assistantOpen = true; loadAgentTasks(); loadAgentTools()">{{ $t('assistant.open') }}</button>
        <button class="back-btn" @click="goBack">← {{ $t('world.backProject') }}</button>
      </div>
    </header>

    <!-- Miro World 新 5 步导航 -->
    <nav class="world-step-nav">
      <button
        v-for="(s, i) in worldSteps"
        :key="s.key"
        class="world-step-btn"
        @click="goStep(s.key)"
      >
        <span class="ws-num">Step{{ i + 1 }}</span>
        <span class="ws-label">{{ s.label }}</span>
      </button>
      <div class="world-search">
        <input
          v-model="globalSearch"
          class="world-search-input"
          :placeholder="$t('world.globalSearchPlaceholder')"
          @input="runGlobalSearch"
          @focus="globalSearchOpen = true"
          @blur="setTimeout(() => globalSearchOpen = false, 200)"
        />
        <div v-if="globalSearchOpen && globalSearchResults.length" class="world-search-results">
          <div v-for="(r, i) in globalSearchResults" :key="i" class="world-search-result">
            <span class="wsr-type">{{ r.type }}</span>
            <span class="wsr-text">{{ r.text }}</span>
          </div>
        </div>
      </div>
    </nav>

    <div class="world-body">
      <!-- 加载失败提示 + 重试（设定库读取失败时不至于页面空白无解释） -->
      <div v-if="loadError" class="load-error-bar">
        <span>⚠ {{ loadError }}</span>
        <button class="action-btn" @click="retryLoad">{{ $t('world.retry') }}</button>
      </div>

      <!-- 新手引导 -->
      <div class="world-guide">
        <div class="guide-title">👋 {{ $t('world.guideTitle') }}</div>
        <div class="guide-text">{{ $t('world.guideText') }}</div>
        <button class="action-btn guide-btn" @click="goStep('input')">{{ $t('world.guideStart') }} ➝</button>
      </div>

      <!-- 输入区 -->
      <div ref="inputSection" class="step-card step-input">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">1</span>
            <span class="step-title">{{ $t('world.inputTitle') }}</span>
          </div>
          <div class="step-status">
            <span class="badge hint">{{ $t('world.inputRequiredHint') }}</span>
          </div>
        </div>

        <div class="input-grid">
          <div class="input-col">
            <div class="input-label">
              {{ $t('world.bgLabel') }}
              <span class="char-count">{{ background.length }} {{ $t('world.charCountUnit') }}</span>
            </div>
            <div
              class="drop-zone"
              :class="{ 'drag-over': bgDragging }"
              @click="bgFileInput.click()"
              @dragover.prevent="bgDragging = true"
              @dragleave="bgDragging = false"
              @drop.prevent="onBgDrop"
            >
              <span class="drop-icon">📄</span>
              <span class="drop-text">
                {{ bgFiles.length ? $t('world.filesSelected', { count: bgFiles.length }) : $t('world.bgDropText') }}
              </span>
              <span class="drop-hint">{{ $t('world.dropHint') }}</span>
              <input
                ref="bgFileInput"
                type="file"
                multiple
                accept=".txt,.md,.markdown,.pdf,.docx,.html,.htm,.epub,.odt,.rtf"
                style="display: none"
                @change="onBgFilesChange"
              />
            </div>
            <div v-if="bgFiles.length" class="file-list">
              <div v-for="(f, i) in bgFiles" :key="i" class="file-item">
                <span class="file-name" :title="f.name">{{ f.name }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <button class="file-remove" @click.stop="bgFiles.splice(i, 1)">×</button>
              </div>
            </div>
            <div v-if="savedBgFiles.length" class="saved-file-list">
              <div class="saved-file-title">📁 {{ $t('world.savedFilesTitle', { count: savedBgFiles.length }) }}</div>
              <div v-for="(f, i) in savedBgFiles" :key="'saved-bg-' + i" class="file-item saved">
                <span class="file-name" :title="f.filename">{{ f.filename }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <span class="file-badge">✓</span>
              </div>
            </div>
            <textarea
              v-model="background"
              class="world-textarea"
              :placeholder="$t('world.bgTextPlaceholder')"
              rows="10"
            ></textarea>
          </div>
          <div class="input-col">
            <div class="input-label">
              {{ $t('world.storyLabel') }}
              <span class="char-count">{{ story.length }} {{ $t('world.charCountUnit') }}</span>
            </div>
            <div
              class="drop-zone"
              :class="{ 'drag-over': stDragging }"
              @click="stFileInput.click()"
              @dragover.prevent="stDragging = true"
              @dragleave="stDragging = false"
              @drop.prevent="onStDrop"
            >
              <span class="drop-icon">📖</span>
              <span class="drop-text">
                {{ stFiles.length ? $t('world.filesSelected', { count: stFiles.length }) : $t('world.stDropText') }}
              </span>
              <span class="drop-hint">{{ $t('world.dropHint') }}</span>
              <input
                ref="stFileInput"
                type="file"
                multiple
                accept=".txt,.md,.markdown,.pdf,.docx,.html,.htm,.epub,.odt,.rtf"
                style="display: none"
                @change="onStFilesChange"
              />
            </div>
            <div v-if="stFiles.length" class="file-list">
              <div v-for="(f, i) in stFiles" :key="i" class="file-item">
                <span class="file-name" :title="f.name">{{ f.name }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <button class="file-remove" @click.stop="stFiles.splice(i, 1)">×</button>
              </div>
            </div>
            <div v-if="savedStFiles.length" class="saved-file-list">
              <div class="saved-file-title">📁 {{ $t('world.savedFilesTitle', { count: savedStFiles.length }) }}</div>
              <div v-for="(f, i) in savedStFiles" :key="'saved-st-' + i" class="file-item saved">
                <span class="file-name" :title="f.filename">{{ f.filename }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <span class="file-badge">✓</span>
              </div>
            </div>
            <textarea
              v-model="story"
              class="world-textarea"
              :placeholder="$t('world.storyTextPlaceholder')"
              rows="10"
            ></textarea>
          </div>
        </div>

        <div class="btn-row">
          <button class="action-btn" :disabled="saving || !hasAnyInput" @click="handleSave">
            <span v-if="saving" class="spinner-sm"></span>
            {{ saving ? $t('world.saving') : $t('world.save') }}
          </button>
          <button
            class="action-btn"
            :class="{ 'btn-ghost': true }"
            :disabled="!canDetect || detecting"
            @click="handleDetect"
          >
            <span v-if="detecting" class="spinner-sm"></span>
            {{ detecting ? $t('world.detecting') : $t('world.detect') }}
          </button>
        </div>

        <div v-if="saveMsg" class="msg-line" :class="{ error: saveMsgError }">{{ saveMsg }}</div>

        <!-- 设定库统计 -->
        <div v-if="stats" class="stats-row">
          <div class="stat-item">
            <span class="stat-value">{{ stats.background_chunks }}</span>
            <span class="stat-label">{{ $t('world.bgChunks') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.story_chunks }}</span>
            <span class="stat-label">{{ $t('world.storyChunks') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.total_chunks }}</span>
            <span class="stat-label">{{ $t('world.totalChunks') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.background_chars }}</span>
            <span class="stat-label">{{ $t('world.bgChars') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ stats.story_chars }}</span>
            <span class="stat-label">{{ $t('world.storyChars') }}</span>
          </div>
        </div>
      </div>

      <!-- 冲突检测结果 -->
      <div v-if="report" class="step-card step-conflict">
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
            <button v-if="report.conflicts.length" class="mini-btn" :class="{ active: conflictSelMode }" @click="toggleConflictSelMode">
              {{ conflictSelMode ? $t('world.batchExit') : $t('world.batchSelect') }}
            </button>
            <template v-if="conflictSelMode">
              <span class="bat-count">{{ $t('world.batchSelectedCount', { n: selConflictIds.length }) }}</span>
              <button class="mini-btn primary" :disabled="!selConflictIds.length || batchConflictBusy" @click="runBatchAccept">{{ $t('world.batchAccept') }}</button>
              <button class="mini-btn" :disabled="!selConflictIds.length || batchConflictBusy" @click="runBatchDismiss">{{ $t('world.batchDismiss') }}</button>
              <button class="mini-btn" @click="selConflictIds = []">{{ $t('world.batchClear') }}</button>
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
              <span v-if="conflictSelMode" class="conflict-sel" @click.stop="toggleConflictSelect(c)"><span class="sel-box" :class="{ checked: isSelConflict(c) }"></span></span>
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
                @click="toggleJustify(c)"
              >
                ⚔️ {{ c.justifyOpen ? $t('world.justifyCancel') : $t('world.refuteConflict') }}
              </button>
              <button
                v-for="s in ['accepted', 'dismissed']"
                :key="s"
                class="mini-btn"
                :class="{ active: c.status === s }"
                :disabled="c.status === s || justifyingId === c.conflict_id"
                @click="setConflictStatus(c, s)"
              >
                {{ s === 'accepted' ? $t('world.acceptBg') : $t('world.dismissConflict') }}
              </button>
              <button
                v-if="c.defense_rounds && c.defense_rounds.length"
                class="mini-btn"
                @click="toggleConflictHistory(c)"
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
                @click="submitJustify(c)"
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
                  @click="loadConflictCorrections(c, true)"
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
                    <button class="mini-btn" :disabled="confRenderBusyId === c.conflict_id" @click="renderCorrectionMerged(c, 'story')">
                      {{ $t('world.corrRenderStory') }}
                    </button>
                    <button class="mini-btn" :disabled="confRenderBusyId === c.conflict_id" @click="renderCorrectionMerged(c, 'settings')">
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

      <!-- 世界模拟（独立模式） -->
      <div v-if="stats" ref="simSection" class="step-card step-sim">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">3</span>
            <span class="step-title">{{ $t('world.simTitle') }}</span>
          </div>
          <div class="step-status">
            <span v-if="simStatus === 'running'" class="badge processing">{{ $t('world.simStatusRunning') }}</span>
            <span v-else-if="simStatus === 'completed'" class="badge success">{{ $t('world.simStatusCompleted') }}</span>
            <span v-else-if="simStatus === 'failed'" class="badge processing">{{ $t('world.simStatusFailed') }}</span>
            <span v-else class="badge hint">{{ $t('world.simStatusHint') }}</span>
          </div>
        </div>

        <p class="description">
          {{ $t('world.simDesc') }}
        </p>

        <!-- 推演进度 -->
        <div v-if="(simStatus === 'running' || simStatus === 'preparing' || simStatus === 'paused') && simProgress.total_steps" class="sim-progress">
          <div class="sim-progress-bar">
            <div class="sim-progress-fill" :style="{ width: Math.min(100, ((simProgress.current_step || 0) / simProgress.total_steps) * 100) + '%' }"></div>
          </div>
          <span class="sim-progress-text">{{ simProgress.message || $t('world.simProgress', { current: simProgress.current_step || 0, total: simProgress.total_steps }) }}</span>
        </div>

        <div class="sim-controls">
          <div class="sim-field sim-field-wide">
            <label class="sim-label">{{ $t('world.simGoalLabel') }}</label>
            <textarea
              v-model="simGoal"
              class="sim-goal-input"
              rows="2"
              :placeholder="$t('world.simGoalPlaceholder')"
            ></textarea>
          </div>
          <div class="sim-field">
            <label class="sim-label">{{ $t('world.simStepsLabel') }}</label>
            <input v-model.number="simSteps" type="number" min="1" max="30" class="sim-input" />
          </div>
          <div class="sim-field">
            <label class="sim-label">{{ $t('world.simTimeModeLabel') }}</label>
            <select v-model="simTimeMode" class="sim-input">
              <option value="minutes">{{ $t('world.simTimeModeMinutes') }}</option>
              <option value="narrative">{{ $t('world.simTimeModeNarrative') }}</option>
            </select>
          </div>
          <div v-if="simTimeMode === 'minutes'" class="sim-field">
            <label class="sim-label">{{ $t('world.simStepMinLabel') }}</label>
            <input v-model.number="simStepMin" type="number" min="1" max="1440" class="sim-input" />
          </div>
          <div v-else class="sim-field sim-field-wide">
            <label class="sim-label">{{ $t('world.simTimeJumpsLabel') }}</label>
            <input
              v-model="simTimeJumps"
              class="sim-input"
              :placeholder="$t('world.simTimeJumpsPlaceholder')"
            />
          </div>
          <div class="sim-field sim-field-wide">
            <label class="sim-label">
              <input v-model="simUseTimeline" type="checkbox" class="sim-check" />
              {{ $t('world.simUseTimeline') }}
            </label>
          </div>
          <div class="sim-field sim-field-wide">
            <label class="sim-label">
              <input v-model="simStorySummaryLlm" type="checkbox" class="sim-check" />
              {{ $t('world.simStorySummaryLlm') }}
            </label>
          </div>
          <div class="sim-field">
            <label class="sim-label">{{ $t('world.simMaxConcurrencyLabel') }}</label>
            <input v-model.number="simMaxConcurrency" type="number" min="1" max="8" class="sim-input" />
          </div>
          <div class="sim-field sim-field-wide">
            <label class="sim-label">{{ $t('world.simStartEventLabel') }}</label>
            <select v-model="simStartEventId" class="sim-input">
              <option value="">{{ $t('world.simStartEventNone') }}</option>
              <option v-for="ev in simTimelineEvents" :key="ev.event_id" :value="ev.event_id">
                {{ ev.summary.length > 40 ? ev.summary.slice(0, 40) + '…' : ev.summary }}
              </option>
            </select>
          </div>
          <button class="action-btn sim-start" :disabled="simStarting || simStatus === 'running'" @click="handleStartSim">
            <span v-if="simStarting" class="spinner-sm"></span>
            {{ simStarting ? $t('world.simStarting') : simStatus === 'running' ? $t('world.simRunning') : $t('world.simStartBtn') }}
          </button>
        </div>

        <div v-if="simMsg" class="msg-line" :class="{ error: simMsgError }">{{ simMsg }}</div>

        <!-- 事件流（按 step 分组，更清晰） -->
        <div v-if="simEvents.length" class="sim-events">
          <div class="sim-events-title">{{ $t('world.eventStream') }}</div>
          <div v-if="simQualityIssues.length" class="sim-quality">
            <div v-for="(issue, i) in simQualityIssues" :key="i" class="sim-quality-item">⚠ {{ issue }}</div>
          </div>
          <div class="sim-playback">
            <button class="mini-btn" @click="playbackPrev">⏮</button>
            <button class="mini-btn" @click="playbackToggle">{{ playbackPlaying ? '⏸' : '▶' }}</button>
            <button class="mini-btn" @click="playbackNext">⏭</button>
            <button class="mini-btn" :disabled="simStarting" @click="rollbackCurrentStep">↩ {{ $t('world.rollbackWorldline') }}</button>
            <span class="sim-playback-info">
              {{ $t('world.simStepLabel', { step: groupedSimEvents[playbackIndex]?.step || 0 }) }} / {{ groupedSimEvents.length }}
            </span>
          </div>
          <div v-if="stepSummaries.length" class="sim-summary">
            <div v-for="s in stepSummaries" :key="s.step" class="sim-summary-item">
              <span class="sim-summary-step">{{ $t('world.simStepLabel', { step: s.step }) }}</span>
              <span class="sim-summary-text">{{ s.text }}</span>
            </div>
          </div>
          <div v-for="(group, gi) in visibleSimGroups" :key="gi" class="sim-step-group" :class="{ active: gi === playbackIndex }">
            <div class="sim-step-head">
              {{ $t('world.simStepLabel', { step: group.step }) }} · {{ group.time }}
            </div>
            <div v-for="(e, ei) in group.events" :key="ei" class="sim-event clickable" @click="openEventDetail(e)">
              <span class="sim-event-who">{{ e.character_name }}</span>
              <span class="sim-event-where">{{ e.location }}</span>
              <span class="sim-event-what">{{ e.action_desc }}</span>
              <span class="sim-event-result">{{ e.result }}</span>
            </div>
          </div>
          <button v-if="simGroupLimit < groupedSimEvents.length" class="mini-btn sim-load-more" @click="simGroupLimit += 50">
            {{ $t('world.loadMoreEvents') }}
          </button>
        </div>

        <!-- 事件因果图 -->
        <div v-if="eventGraphData.nodes.length" class="sim-graph">
          <div class="sim-graph-title">
            <span>{{ $t('world.eventGraphTitle') }}</span>
            <select v-model="graphFilterChar" class="sim-graph-filter">
              <option value="">{{ $t('world.allCharacters') }}</option>
              <option v-for="c in graphCharacters" :key="c" :value="c">{{ c }}</option>
            </select>
            <button class="mini-btn ghost" @click="graphZoom = Math.max(0.5, graphZoom - 0.2)">−</button>
            <span class="sim-graph-zoom">{{ Math.round(graphZoom * 100) }}%</span>
            <button class="mini-btn ghost" @click="graphZoom = Math.min(2, graphZoom + 0.2)">+</button>
            <button class="mini-btn ghost" @click="exportGraph">{{ $t('world.exportGraph') }}</button>
          </div>
          <div class="sim-graph-zoom-wrap" :style="{ transform: 'scale(' + graphZoom + ')', transformOrigin: 'top left' }">
            <svg :viewBox="`0 0 ${eventGraphData.width} ${eventGraphData.height}`" class="sim-graph-svg">
              <line
                v-for="(ed, i) in eventGraphData.edges"
                :key="'e' + i"
                :x1="graphPosMap[ed.source]?.x"
                :y1="graphPosMap[ed.source]?.y"
                :x2="graphPosMap[ed.target]?.x"
                :y2="graphPosMap[ed.target]?.y"
                class="sim-graph-edge"
              />
              <g
                v-for="(n, i) in eventGraphData.nodes"
                :key="'n' + i"
                :transform="`translate(${n.x},${n.y})`"
                @click="selectedGraphEvent = n.id"
              >
                <circle r="6" class="sim-graph-node" :class="{ active: selectedGraphEvent === n.id }" />
                <text y="-10" text-anchor="middle" class="sim-graph-label">{{ n.label }}</text>
              </g>
            </svg>
          </div>
          <div v-if="selectedGraphEvent" class="sim-graph-detail">
            <template v-for="(n, i) in eventGraphData.nodes" :key="i">
              <div v-if="n.id === selectedGraphEvent" class="sim-graph-detail-inner">
                <span class="sim-graph-detail-step">{{ $t('world.simStepLabel', { step: n.step }) }}</span>
                <span class="sim-graph-detail-who">{{ n.event.character_name }}</span>
                <span class="sim-graph-detail-text">{{ n.event.action_desc }} → {{ n.event.result }}</span>
              </div>
            </template>
          </div>
        </div>

        <!-- 运行中控制（IPC） -->
        <div v-if="simStatus === 'running' || simStatus === 'paused'" class="sim-ctl">
          <div class="sim-ctl-title">{{ $t('world.runControl') }}</div>
          <div class="sim-ctl-btns">
            <button
              class="mini-btn"
              :disabled="simStatus === 'paused'"
              @click="handleControl('pause')"
            >{{ $t('world.pause') }}</button>
            <button
              class="mini-btn"
              :disabled="simStatus !== 'paused'"
              @click="handleControl('resume')"
            >{{ $t('world.resume') }}</button>
            <button class="mini-btn danger" @click="handleControl('stop')">{{ $t('world.stop') }}</button>
          </div>
          <div v-if="simCtlMsg" class="msg-line" :class="{ error: simCtlMsgError }">{{ simCtlMsg }}</div>
        </div>

        <!-- 角色采访 -->
        <div v-if="characters.length" ref="interactionSection" class="sim-interview">
          <div class="sim-interview-title">{{ $t('world.interviewTitle') }}</div>
          <p class="sim-interview-hint">{{ $t('world.interviewHint') }}</p>
          <div class="sim-char-list">
            <button
              v-for="c in characters"
              :key="c"
              class="mini-btn"
              :class="{ active: interviewCharacter === c }"
              @click="selectCharacter(c)"
            >{{ c }}</button>
          </div>
          <div v-if="interviewCharacter" class="interview-box">
            <div class="interview-char">{{ $t('world.interviewWith') }}{{ interviewCharacter }}</div>
            <textarea
              v-model="interviewPrompt"
              class="interview-input"
              rows="2"
              :placeholder="$t('world.interviewPlaceholder')"
            ></textarea>
            <button
              class="mini-btn active"
              :disabled="interviewing || !interviewPrompt.trim()"
              @click="handleInterview"
            >
              <span v-if="interviewing" class="spinner-xs"></span>
              {{ interviewing ? $t('world.interviewing') : $t('world.sendInterview') }}
            </button>
            <div v-if="interviewAnswer" class="interview-answer">
              <div class="interview-answer-label">{{ $t('world.interviewAnswerLabel') }}</div>
              <div class="interview-answer-text">{{ interviewAnswer }}</div>
            </div>
            <div v-if="interviewMsgError" class="msg-line error">{{ interviewMsg }}</div>
          </div>
        </div>

        <!-- 世界小说续写 -->
        <div v-if="reportSimulationId" class="sim-report">
          <div class="sim-report-head">
            <div class="sim-report-title">
              <span>{{ $t('world.novelTitle') }}</span>
              <span v-if="reportSimulationLabel" class="sim-report-sub">{{ reportSimulationLabel }}</span>
            </div>
            <button
              class="mini-btn"
              :disabled="reportGenerating"
              @click="handleGenerateReport"
            >
              <span v-if="reportGenerating" class="spinner-xs"></span>
              {{ reportGenerating ? $t('world.novelGenerating') : reportText ? $t('world.novelRegenerate') : $t('world.novelGenerate') }}
            </button>
          </div>
          <div v-if="reportText" class="report-body">
            <div v-for="(block, bi) in reportBlocks" :key="bi" class="report-block">
              <div v-if="block.type === 'h2'" class="report-h2">{{ block.text }}</div>
              <div v-else-if="block.type === 'li'" class="report-li">· {{ block.text }}</div>
              <div v-else class="report-p">{{ block.text }}</div>
            </div>
          </div>
          <div v-else-if="reportEmptyNote" class="empty-note">{{ reportEmptyNote }}</div>
        </div>

        <!-- 世界线之树 -->
        <div v-if="worldTree.length" class="world-tree">
          <div class="world-tree-title">
            🌳 {{ $t('world.worldTreeTitle') }}
            <button v-if="metaUndoStack.length" class="mini-btn ghost" @click="undoLastMeta">{{ $t('world.undoMeta') }}</button>
          </div>
          <div v-for="root in worldTree" :key="root.simulation_id" class="tree-node root">
            <div class="tree-node-row">
              <button class="mini-btn ghost" @click="toggleRoot(root.simulation_id)">{{ collapsedRoots.has(root.simulation_id) ? '▶' : '▼' }}</button>
              <span class="tree-node-name">{{ root.result?.meta?.name || formatTime(root.created_at) }}</span>
              <span class="badge" :class="root.status">{{ statusLabel(root.status) }}</span>
              <span class="tree-node-count">{{ $t('world.eventCount', { count: (root.result || {}).event_count || 0 }) }}</span>
              <button class="mini-btn ghost" @click="editWorldlineMeta(root)">✎</button>
              <button class="mini-btn ghost" @click="loadSimulation(root)">{{ $t('world.loadSimulation') }}</button>
              <button class="mini-btn" :disabled="simStarting" @click="continueSimulation(root)">{{ $t('world.continueSimulation') }}</button>
              <button class="mini-btn ghost" @click="exportSimulation(root)">{{ $t('world.exportSimulation') }}</button>
              <button class="mini-btn ghost" @click="copyWorldline(root)">{{ $t('world.copyWorldline') }}</button>
              <button v-if="root.status === 'completed' && !((root.result || {}).meta || {}).whatif_question" class="mini-btn" @click="startWhatIf(root)">{{ $t('world.whatifBtn') }}</button>
              <button v-if="root.status === 'completed' && !((root.result || {}).meta || {}).whatif_question" class="mini-btn ghost" @click="batchWhatIf(root)">{{ $t('world.batchWhatif') }}</button>
            </div>
            <div v-if="!collapsedRoots.has(root.simulation_id)">
              <div v-for="child in root.children" :key="child.simulation_id" class="tree-node child">
              <div class="tree-node-row">
                <span class="tree-branch">└─</span>
                <span class="tree-node-name">{{ child.result?.meta?.name || child.result?.meta?.whatif_question || formatTime(child.created_at) }}</span>
                <span class="badge" :class="child.status">{{ statusLabel(child.status) }}</span>
                <span class="tree-node-count">{{ $t('world.eventCount', { count: (child.result || {}).event_count || 0 }) }}</span>
                <button class="mini-btn ghost" @click="editWorldlineMeta(child)">✎</button>
                <button class="mini-btn ghost" @click="loadSimulation(child)">{{ $t('world.loadSimulation') }}</button>
                <button class="mini-btn" :disabled="simStarting" @click="continueSimulation(child)">{{ $t('world.continueSimulation') }}</button>
                <button v-if="child.result?.meta?.whatif_question" class="mini-btn" :disabled="simStarting" @click="rerunBranchWithSettings(child)">{{ $t('world.rerunBranchWithSettings') }}</button>
                <button class="mini-btn ghost" @click="exportSimulation(child)">{{ $t('world.exportSimulation') }}</button>
                <button class="mini-btn ghost" @click="copyWorldline(child)">{{ $t('world.copyWorldline') }}</button>
              </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="simHistory.length" class="sim-history">
          <div class="sim-history-title">
            <span>{{ $t('world.reportHistoryTitle') }}</span>
            <button class="mini-btn ghost" @click="exportAllWorldlines">{{ $t('world.exportAllWorldlines') }}</button>
            <button v-if="simHistory.length >= 2" class="mini-btn ghost" @click="toggleCompareMode">
              {{ compareMode ? $t('world.cancel') : $t('world.compareWorldlines') }}
            </button>
            <button v-if="compareMode && compareSelected.length === 2" class="mini-btn" @click="openCompare">
              {{ $t('world.compare') }}
            </button>
            <button v-if="compareMode && compareSelected.length === 2" class="mini-btn" @click="mergeSelected">
              {{ $t('world.mergeWorldlines') }}
            </button>
          </div>
          <div v-for="(h, i) in simHistory" :key="i" class="sim-history-item">
            <input
              v-if="compareMode"
              type="checkbox"
              class="sim-compare-check"
              :checked="compareSelected.includes(h.simulation_id)"
              @change="toggleCompareSelect(h)"
            />
            <template v-else>
              <span class="sim-history-time">{{ formatTime(h.created_at) }}</span>
              <span class="sim-history-status" :class="h.status">{{ statusLabel(h.status) }}</span>
              <span class="sim-history-count">{{ $t('world.eventCount', { count: (h.result || {}).event_count || 0 }) }}</span>
              <span v-if="(h.result || {}).meta && (h.result || {}).meta.whatif_question" class="sim-history-flag">{{ $t('world.whatifFlag') }}</span>
              <button class="mini-btn ghost" @click="loadSimulation(h)">{{ $t('world.loadSimulation') }}</button>
              <button class="mini-btn" :disabled="simStarting" @click="continueSimulation(h)">{{ $t('world.continueSimulation') }}</button>
              <button class="mini-btn ghost" @click="exportSimulation(h)">{{ $t('world.exportSimulation') }}</button>
              <template v-if="h.status === 'completed' && !((h.result || {}).meta || {}).whatif_question">
                <button class="mini-btn" :disabled="whatIfing === h.simulation_id" @click="startWhatIf(h)">
                  <span v-if="whatIfing === h.simulation_id" class="spinner-xs"></span>
                  {{ $t('world.whatifBtn') }}
                </button>
                <button class="mini-btn ghost" @click="openChartRecord(h)">{{ $t('world.chronicleBtn') }}</button>
              </template>
            </template>
          </div>
          <!-- 当前模拟的 what-if 推演对话框 -->
          <div v-if="whatIfBaseId" ref="branchSection" class="whatif-box">
            <div class="whatif-title">
              {{ $t('world.whatifBaseTitle', { label: whatIfBaseLabel }) }}
            </div>
            <input
              v-model="whatIfQuestion"
              class="whatif-input"
              :placeholder="$t('world.whatifPlaceholder')"
              @keyup.enter="confirmWhatIf"
            />
            <div class="whatif-btns">
              <button class="mini-btn active" :disabled="whatIfStarting || !whatIfQuestion.trim()" @click="confirmWhatIf">
                <span v-if="whatIfStarting" class="spinner-xs"></span>
                {{ whatIfStarting ? $t('world.whatifStarting') : $t('world.startWhatif') }}
              </button>
              <button class="mini-btn" @click="cancelWhatIf">{{ $t('world.cancel') }}</button>
            </div>
            <div v-if="whatIfMsgError" class="msg-line error">{{ whatIfMsg }}</div>
          </div>
          <!-- what-if 推演结果 -->
          <div v-if="whatIfActive" class="whatif-result">
            <div class="whatif-result-title">{{ $t('world.whatifResultTitle', { question: whatIfQuestionAsked }) }}</div>
            <div v-if="whatIfEvents.length" class="sim-events">
              <div class="sim-events-title">{{ $t('world.whatifEventStream') }}</div>
              <div v-for="(e, i) in whatIfEvents" :key="i" class="sim-event">
                <span class="sim-event-time">{{ e.time }}</span>
                <span class="sim-event-who">{{ e.character_name }}</span>
                <span class="sim-event-where">{{ e.location }}</span>
                <span class="sim-event-what">{{ e.action_desc }}</span>
                <span class="sim-event-result">{{ e.result }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 设定检索 -->
      <div v-if="stats" class="step-card step-search">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">2</span>
            <span class="step-title">{{ $t('world.searchTitle') }}</span>
          </div>
          <div class="step-status">
            <span class="badge hint">{{ $t('world.searchHint') }}</span>
          </div>
        </div>

        <div class="search-row">
          <input
            v-model="searchQuery"
            class="search-input"
            :placeholder="$t('world.searchPlaceholder')"
            @keyup.enter="handleSearch"
          />
          <button class="search-btn" :disabled="!searchQuery.trim()" @click="handleSearch">
            {{ searching ? $t('world.searching') : $t('world.searchBtn') }}
          </button>
        </div>

        <label class="semantic-toggle">
          <input v-model="searchSemantic" type="checkbox" class="semantic-check" />
          <span class="semantic-mark"></span>
          <span class="semantic-label">{{ $t('world.semanticLabel') }}</span>
        </label>

        <div v-if="searchResults.length" class="search-results">
          <div v-for="r in searchResults" :key="r.chunk_id" class="search-item">
            <span class="search-src" :class="r.source">{{ r.source === 'background' ? $t('world.sourceBg') : $t('world.sourceStory') }}</span>
            <span class="search-text">{{ r.text }}</span>
            <span class="search-score">{{ $t('world.relevance', { score: r.score }) }}</span>
          </div>
        </div>
      </div>

      <!-- 世界图谱（GraphRAG · Neo4j） -->
      <div v-if="stats" class="step-card step-graph">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">2</span>
            <span class="step-title">{{ $t('world.graphTitle') }}</span>
          </div>
          <div class="step-status">
            <span v-if="graphBuilding" class="badge processing">{{ $t('world.graphBuilding') }}</span>
            <span v-else-if="graphInfo && graphInfo.node_count" class="badge success">{{ $t('world.graphCount', { nodes: graphInfo.node_count, edges: graphInfo.edge_count }) }}</span>
            <span v-else class="badge hint">{{ $t('world.graphHint') }}</span>
          </div>
        </div>

        <p class="description">
          {{ $t('world.graphDesc') }}
        </p>

        <div class="graph-actions">
          <button class="action-btn" :disabled="graphBuilding" @click="handleBuildGraph">
            <span v-if="graphBuilding" class="spinner-sm"></span>
            {{ graphBuilding ? (graphProgressMsg || $t('world.graphBuilding')) : graphInfo ? $t('world.graphRebuild') : $t('world.graphBuild') }}
          </button>
          <button
            class="action-btn btn-ghost"
            :disabled="refillEdgesRunning || !graphInfo || !graphInfo.node_count"
            @click="handleRefillEdges"
          >
            <span v-if="refillEdgesRunning" class="spinner-sm"></span>
            {{ refillEdgesRunning ? $t('world.refillEdgesRunning') : $t('world.refillEdges') }}
          </button>
          <span v-if="graphMsg" class="msg-line" :class="{ error: graphMsgError }">{{ graphMsg }}</span>
          <div v-if="graphBuilding" class="graph-progress">
            <div class="graph-progress-bar">
              <div class="graph-progress-fill" :style="{ width: (graphProgress || 0) + '%' }"></div>
            </div>
            <span class="graph-progress-text">{{ graphProgressMsg || $t('world.graphBuilding') }}</span>
          </div>
        </div>

        <!-- SVG 力导向可视化 -->
        <div v-if="graphInfo && graphNodes.length" class="graph-viz-wrap">
          <svg
            ref="graphSvg"
            :viewBox="`0 0 ${GV_W} ${GV_H}`"
            class="graph-svg"
            @click="selectedGraphNode = null"
          >
            <line
              v-for="(e, i) in graphEdges"
              :key="'e' + i"
              :x1="graphNodeX(e.source)"
              :y1="graphNodeY(e.source)"
              :x2="graphNodeX(e.target)"
              :y2="graphNodeY(e.target)"
              class="graph-edge"
            />
            <g
              v-for="(n, i) in graphNodes"
              :key="'n' + i"
              :transform="`translate(${graphNodeX(n.uuid)},${graphNodeY(n.uuid)})`"
              @click.stop="selectedGraphNode = n"
            >
              <circle
                :r="graphNodeR(n)"
                class="graph-node"
                :class="{ selected: selectedGraphNode && selectedGraphNode.uuid === n.uuid }"
                :style="{ fill: graphNodeColor(n) }"
              />
              <text class="graph-node-label" text-anchor="middle" :y="graphNodeR(n) + 14">{{ n.name }}</text>
            </g>
          </svg>

          <div v-if="selectedGraphNode" class="graph-node-info">
            <div class="graph-node-info-name">{{ selectedGraphNode.name }}</div>
            <div class="graph-node-info-type">{{ graphNodeType(selectedGraphNode) }}</div>
            <div v-if="selectedGraphNode.summary" class="graph-node-info-summary">{{ selectedGraphNode.summary }}</div>
            <div v-if="selectedGraphAttrs.length" class="graph-node-info-attrs">
              <div v-for="(row, ai) in selectedGraphAttrs" :key="ai" class="attr-row">
                <span class="attr-k">{{ row[0] }}</span>
                <span class="attr-v">{{ row[1] }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="graphInfo" class="empty-note">{{ $t('world.graphEmpty') }}</div>
      </div>

      <!-- 时间线 -->
      <div v-if="stats" ref="timelineSection" class="step-card step-timeline">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">2</span>
            <span class="step-title">{{ $t('timeline.tab') }}</span>
          </div>
        </div>
        <TimelineView :project-id="projectId" />
      </div>

      <!-- 内置项目助手 -->
      <div v-if="assistantOpen" class="assistant-modal-mask" @click.self="assistantOpen = false">
        <div class="assistant-modal">
          <div class="assistant-head">
            <span class="assistant-title">{{ $t('assistant.title') }}</span>
            <button class="assistant-close" @click="assistantOpen = false">×</button>
          </div>
          <div class="assistant-body">
            <p class="assistant-hint">{{ $t('assistant.hint') }}</p>
            <div class="assistant-quick">
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickStatus')">📋 {{ $t('assistant.quickStatus') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickGraph')">🕸️ {{ $t('assistant.quickGraph') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickExtract')">📜 {{ $t('assistant.quickExtract') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickTree')">🌳 {{ $t('assistant.quickTree') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickWorldlineSummary')">📊 {{ $t('assistant.quickWorldlineSummary') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickSim')">🌍 {{ $t('assistant.quickSim') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickCharacters')">👥 {{ $t('assistant.quickCharacters') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickReport')">📄 {{ $t('assistant.quickReport') }}</button>
              <button class="mini-btn" :disabled="assistantAsking" @click="quickAsk('assistant.quickExport')">💾 {{ $t('assistant.quickExport') }}</button>
            </div>
            <textarea
              v-model="assistantQuestion"
              rows="3"
              class="assistant-input"
              :placeholder="$t('assistant.placeholder')"
            ></textarea>
            <div class="assistant-actions">
              <button
                class="action-btn"
                :disabled="assistantAsking || !assistantQuestion.trim()"
                @click="askAssistantNow"
              >
                {{ assistantAsking ? $t('assistant.asking') : $t('assistant.ask') }}
              </button>
            </div>
            <div v-if="assistantAsking" class="assistant-running">
              <span class="spinner-sm"></span> {{ $t('assistant.executing') }}
            </div>
            <div v-if="assistantAnswer" class="assistant-answer">{{ assistantAnswer }}</div>
            <div v-if="assistantMsg" class="msg-line" :class="{ error: assistantMsgError }">{{ assistantMsg }}</div>
            <details class="agent-tools">
              <summary>{{ $t('assistant.toolList') }} ({{ Object.keys(agentTools).length }})</summary>
              <div class="agent-tools-grid">
                <div v-for="(tool, name) in agentTools" :key="name" class="agent-tool-item">
                  <span class="agent-tool-name">{{ name }}</span>
                  <span class="agent-tool-desc">{{ tool.description }}</span>
                </div>
              </div>
            </details>
            <div class="agent-tasks">
              <div class="agent-tasks-title">{{ $t('assistant.taskList') }}</div>
              <div v-if="agentTasks.length" class="agent-tasks-list">
                <div v-for="task in agentTasks" :key="task.task_id" class="agent-task-item">
                  <span class="agent-task-action">{{ task.action }}</span>
                  <span class="agent-task-status" :class="task.status">{{ task.status }}</span>
                  <span class="agent-task-time">{{ task.created_at }}</span>
                </div>
              </div>
              <div v-else class="empty-note">{{ $t('assistant.taskEmpty') }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 事件详情抽屉 -->
      <div v-if="selectedEventDetail" class="assistant-modal-mask" @click.self="selectedEventDetail = null">
        <div class="assistant-modal event-detail-modal">
          <div class="assistant-head">
            <span class="assistant-title">{{ $t('world.eventDetailTitle') }}</span>
            <button class="assistant-close" @click="selectedEventDetail = null">×</button>
          </div>
          <div class="event-detail-body">
            <div class="event-detail-row"><span class="ed-label">{{ $t('world.simStepLabel', { step: selectedEventDetail.step }) }}</span><span>{{ selectedEventDetail.time }}</span></div>
            <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventWho') }}</span><span>{{ selectedEventDetail.character_name }}</span></div>
            <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventWhere') }}</span><span>{{ selectedEventDetail.location }}</span></div>
            <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventAction') }}</span><span>{{ selectedEventDetail.action_desc }}</span></div>
            <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventResult') }}</span><span>{{ selectedEventDetail.result }}</span></div>
            <div v-if="selectedEventDetail.links && selectedEventDetail.links.length" class="event-detail-row">
              <span class="ed-label">{{ $t('world.eventLinks') }}</span><span>{{ selectedEventDetail.links.join(', ') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 新手引导 -->
      <div v-if="showGuide" class="assistant-modal-mask guide-mask" @click.self="closeGuide">
        <div class="assistant-modal guide-modal">
          <div class="assistant-head">
            <span class="assistant-title">👋 {{ $t('world.guideTitle') }}</span>
            <button class="assistant-close" @click="closeGuide">×</button>
          </div>
          <div class="guide-body">
            <p class="guide-text">{{ $t('world.guideText') }}</p>
            <ol class="guide-steps">
              <li v-for="(s, i) in worldSteps" :key="s.key">{{ i + 1 }}. {{ s.label }}</li>
            </ol>
            <button class="action-btn" @click="closeGuide">{{ $t('world.guideStart') }} ➝</button>
          </div>
        </div>
      </div>

      <!-- 世界线对比 -->
      <div v-if="compareOpen" class="assistant-modal-mask" @click.self="compareOpen = false">
        <div class="assistant-modal compare-modal">
          <div class="assistant-head">
            <span class="assistant-title">{{ $t('world.compareWorldlines') }}</span>
            <button class="mini-btn ghost" @click="exportCompareReport">{{ $t('world.exportCompare') }}</button>
            <button class="assistant-close" @click="compareOpen = false">×</button>
          </div>
          <div class="compare-grid">
            <div v-for="(item, idx) in compareData" :key="idx" class="compare-col">
              <div class="compare-col-head">
                <span>{{ formatTime(item.created_at) }}</span>
                <span class="badge" :class="item.status">{{ statusLabel(item.status) }}</span>
                <span>{{ $t('world.eventCount', { count: item.event_count }) }}</span>
              </div>
              <div v-if="item.events.length" class="compare-events">
                <div v-for="(g, gi) in groupEventsByStep(item.events)" :key="gi" class="compare-step">
                  <div class="compare-step-head">{{ $t('world.simStepLabel', { step: g.step }) }} · {{ g.time }}</div>
                  <div v-for="(e, ei) in g.events" :key="ei" class="sim-event">
                    <span class="sim-event-who">{{ e.character_name }}</span>
                    <span class="sim-event-where">{{ e.location }}</span>
                    <span class="sim-event-what">{{ e.action_desc }}</span>
                    <span class="sim-event-result">{{ e.result }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="empty-note">{{ $t('world.noEvents') }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  saveWorldInput,
  saveWorldInputMultipart,
  getWorldSettings,
  detectWorldConflicts,
  getWorldConflicts,
  getConflictHistory,
  updateConflictStatus,
  generateConflictCorrections,
  getConflictCorrections,
  renderConflictsCorrection,
  correctionDownloadUrl,
  searchWorld,
  startWorldSimulation,
  listWorldSimulations,
  getWorldSimulation,
  controlWorldSimulation,
  simulateWorldWhatIf,
  generateWorldReport,
  getWorldReport,
  generateWorldNovel,
  getWorldNovel,
  buildWorldGraph,
  getWorldGraph,
  refillWorldGraphEdges
} from '../api/world'
import { getTaskStatus, exportProjectSnapshot, importProjectSnapshot } from '../api/graph'
import { askAssistant, runAssistantAction, listAgentTasks, listAgentTools } from '../api/assistant'
import { getTimeline, generateTimelineCharacters } from '../api/timeline'
import TimelineView from '../components/TimelineView.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const projectId = route.params.projectId
const snapshotBusy = ref(false)
const importFileInput = ref(null)
const assistantOpen = ref(false)
const assistantQuestion = ref('')
const assistantAsking = ref(false)
const assistantAnswer = ref('')
const assistantMsg = ref('')
const assistantMsgError = ref(false)
const agentTasks = ref([])
const agentTools = ref({})
async function loadAgentTasks() {
  try {
    const res = await listAgentTasks()
    agentTasks.value = res?.data?.tasks || []
  } catch (e) {
    agentTasks.value = []
  }
}
async function loadAgentTools() {
  try {
    const res = await listAgentTools()
    agentTools.value = res?.data?.tools || {}
  } catch (e) {
    agentTools.value = {}
  }
}

const background = ref('')
const story = ref('')
const saving = ref(false)
const detecting = ref(false)
const saveMsg = ref('')
const saveMsgError = ref(false)
const loadError = ref('')
const showGuide = ref(false)
const highContrast = ref(false)
const globalSearch = ref('')
const globalSearchResults = ref([])
const globalSearchOpen = ref(false)
const stats = ref(null)
const report = ref(null)
const justifyingId = ref('')
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref([])

// 多文件上传状态
const bgFiles = ref([])
const stFiles = ref([])
const bgDragging = ref(false)
const stDragging = ref(false)
const bgFileInput = ref(null)
const stFileInput = ref(null)

// 已保存到设定库的文件清单（首页上传后在此展示，避免"下一页看不到文件"）
const savedFiles = ref([])
const savedBgFiles = computed(() => savedFiles.value.filter(f => f.source === 'background'))
const savedStFiles = computed(() => savedFiles.value.filter(f => f.source === 'story'))

// 世界模拟状态
const simSteps = ref(6)
const simStepMin = ref(30)
const simTimeMode = ref('minutes')
const simTimeJumps = ref('')
const simUseTimeline = ref(false)
const simStorySummaryLlm = ref(false)
const simMaxConcurrency = ref(1)
const simStartEventId = ref('')
const simTimelineEvents = ref([])
const simGoal = ref('')  // 任务目标（可选，决定推演走向）
const simStarting = ref(false)
const simStatus = ref('idle')
const simMsg = ref('')
const simMsgError = ref(false)
const simEvents = ref([])
const simHistory = ref([])
const simProgress = ref({})
const compareMode = ref(false)
const metaUndoStack = ref([])
const compareSelected = ref([])
const compareOpen = ref(false)
const compareData = ref([])

// 世界线之树：基础模拟为根，what-if 分支挂到父节点下
const worldTree = computed(() => {
  const byId = new Map()
  simHistory.value.forEach(s => byId.set(s.simulation_id, { ...s, children: [] }))
  const roots = []
  byId.forEach(node => {
    const base = node.result?.meta?.whatif_base
    if (base && byId.has(base)) {
      byId.get(base).children.push(node)
    } else {
      roots.push(node)
    }
  })
  const sortRec = (nodes) => {
    nodes.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
    nodes.forEach(n => sortRec(n.children))
  }
  sortRec(roots)
  return roots
})

// 把世界模拟事件按 step 分组，避免一长串杂乱平铺
const groupedSimEvents = computed(() => {
  const groups = []
  const map = new Map()
  for (const e of simEvents.value || []) {
    const key = `${e.step || 0}-${e.time || ''}`
    if (!map.has(key)) {
      const g = { step: e.step || 0, time: e.time || '', events: [] }
      map.set(key, g)
      groups.push(g)
    }
    map.get(key).events.push(e)
  }
  return groups
})

// 每步一句话剧情脉络，帮用户快速抓住主线
const stepSummaries = computed(() => {
  return groupedSimEvents.value.map(g => ({
    step: g.step,
    time: g.time,
    text: g.events
      .map(e => `${e.character_name}：${(e.action_desc || '').replace(/\s+/g, ' ').trim()}`)
      .join('；')
      .slice(0, 160),
  }))
})

// 模拟质量自检：重复动作/原地等待/因果链断裂提示
const simQualityIssues = computed(() => {
  const issues = []
  const events = simEvents.value || []
  if (!events.length) return issues
  let prevKey = null
  let repeat = 0
  for (const e of events) {
    const key = `${e.character_name}|${(e.action_desc || '').trim()}`
    if (key === prevKey) {
      repeat++
    } else {
      if (repeat >= 2 && prevKey) {
        const [who] = prevKey.split('|')
        issues.push(t('world.qualityRepeat', { who, count: repeat + 1 }))
      }
      repeat = 0
      prevKey = key
    }
  }
  if (repeat >= 2 && prevKey) {
    const [who] = prevKey.split('|')
    issues.push(t('world.qualityRepeat', { who, count: repeat + 1 }))
  }
  const waits = events.filter(e => /等待|停下来|wait/i.test(e.action_desc || '')).length
  if (events.length && waits / events.length > 0.4) {
    issues.push(t('world.qualityWaits', { count: waits, total: events.length }))
  }
  const noLink = events.filter(e => !e.links || !e.links.length).length
  if (noLink > events.length * 0.6) {
    issues.push(t('world.qualityNoLinks', { count: noLink, total: events.length }))
  }
  return issues
})

// 事件因果图：根据事件 links 生成节点/边，按 step 分层布局
const eventGraphData = computed(() => {
  const events = (simEvents.value || []).filter(
    e => !graphFilterChar.value || e.character_name === graphFilterChar.value
  )
  if (!events.length) return { nodes: [], edges: [], width: 600, height: 300 }
  const nodes = []
  const byId = new Map()
  const stepGroups = {}
  events.forEach((e, i) => {
    const id = e.id || `ev_${i}`
    const step = e.step || 0
    if (!stepGroups[step]) stepGroups[step] = []
    stepGroups[step].push(id)
    const node = { id, label: `${e.character_name || '?'}: ${(e.action_desc || '').replace(/\s+/g, ' ').slice(0, 18)}`, step, event: e }
    byId.set(id, node)
    nodes.push(node)
  })
  const edges = []
  events.forEach((e, i) => {
    const id = e.id || `ev_${i}`
    ;(e.links || []).forEach(linkId => {
      if (byId.has(linkId) && linkId !== id) edges.push({ source: linkId, target: id })
    })
  })
  const stepKeys = Object.keys(stepGroups).map(Number).sort((a, b) => a - b)
  const xGap = 150, yGap = 56
  const positions = {}
  stepKeys.forEach((step, si) => {
    const ids = stepGroups[step]
    const count = ids.length
    ids.forEach((id, idx) => {
      positions[id] = { x: 80 + si * xGap, y: 60 + (idx - (count - 1) / 2) * yGap }
    })
  })
  const width = Math.max(600, stepKeys.length * xGap + 160)
  const maxCount = Math.max(1, ...stepKeys.map(s => stepGroups[s].length))
  const height = Math.max(300, maxCount * yGap + 120)
  return {
    nodes: nodes.map(n => ({ ...n, ...positions[n.id] })),
    edges,
    width,
    height,
  }
})
const graphPosMap = computed(() => {
  const m = {}
  eventGraphData.value.nodes.forEach(n => { m[n.id] = { x: n.x, y: n.y } })
  return m
})
const selectedGraphEvent = ref('')
const selectedEventDetail = ref(null)
function openEventDetail(e) {
  selectedEventDetail.value = e
}
const collapsedRoots = ref(new Set())
function toggleRoot(id) {
  const next = new Set(collapsedRoots.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  collapsedRoots.value = next
}
const graphFilterChar = ref('')
const graphZoom = ref(1)
const graphCharacters = computed(() => {
  const set = new Set()
  ;(simEvents.value || []).forEach(e => { if (e.character_name) set.add(e.character_name) })
  return Array.from(set)
})

// 事件回放/时间轴播放器
const playbackIndex = ref(0)
const playbackPlaying = ref(false)
const simGroupLimit = ref(50)
const visibleSimGroups = computed(() => groupedSimEvents.value.slice(0, simGroupLimit.value))
let playbackTimer = null
function playbackToggle() {
  if (playbackPlaying.value) {
    stopPlayback()
  } else {
    startPlayback()
  }
}
function startPlayback() {
  if (!groupedSimEvents.value.length) return
  if (playbackIndex.value >= groupedSimEvents.value.length) playbackIndex.value = 0
  playbackPlaying.value = true
  playbackTimer = setInterval(() => {
    if (playbackIndex.value < groupedSimEvents.value.length - 1) {
      playbackIndex.value++
    } else {
      stopPlayback()
    }
  }, 2000)
}
function stopPlayback() {
  playbackPlaying.value = false
  if (playbackTimer) {
    clearInterval(playbackTimer)
    playbackTimer = null
  }
}
function playbackPrev() {
  playbackIndex.value = Math.max(0, playbackIndex.value - 1)
}
function playbackNext() {
  playbackIndex.value = Math.min(groupedSimEvents.value.length - 1, playbackIndex.value + 1)
}
async function rollbackCurrentStep() {
  const group = groupedSimEvents.value[playbackIndex.value]
  const simId = simPollingId || (simHistory.value[0]?.simulation_id)
  if (!group || !simId) return
  if (simStarting.value) return
  simStarting.value = true
  try {
    const res = await runAssistantAction(projectId, 'rollback_worldline', {
      simulation_id: simId,
      target_step: group.step,
      additional_steps: 3,
    })
    const actionResult = res?.data?.action_result || {}
    simMsg.value = t('world.msgRollbackStarted', { id: actionResult.simulation_id || '' })
    simMsgError.value = false
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  } finally {
    simStarting.value = false
  }
}
const simSection = ref(null)
const inputSection = ref(null)
const timelineSection = ref(null)
const branchSection = ref(null)
const interactionSection = ref(null)
let simPollTimer = null
let simPollingId = ''
let whatIfPollTimer = null

// Miro World 新 5 步导航
const worldSteps = computed(() => [
  { key: 'input', label: t('home.step01Title') },
  { key: 'timeline', label: t('home.step02Title') },
  { key: 'sim', label: t('home.step03Title') },
  { key: 'branch', label: t('home.step04Title') },
  { key: 'interaction', label: t('home.step05Title') },
])
function goStep(key) {
  const map = {
    input: inputSection,
    timeline: timelineSection,
    sim: simSection,
    branch: branchSection,
    interaction: interactionSection
  }
  const target = (map[key]?.value) || simSection.value
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// 世界图谱状态
const GV_W = 780
const GV_H = 420
const graphInfo = ref(null)          // { nodes, edges, node_count, edge_count }
const graphPos = ref({})             // uuid -> {x, y}（力导向布局结果）
const graphBuilding = ref(false)
const graphProgressMsg = ref('')
const graphProgress = ref(0)
const refillEdgesRunning = ref(false)
let refillPollTimerId = null
const graphMsg = ref('')
const graphMsgError = ref(false)
const selectedGraphNode = ref(null)
let graphPollTimer = null

const graphNodes = computed(() => (graphInfo.value && graphInfo.value.nodes) || [])
const graphEdges = computed(() => {
  if (!graphInfo.value || !graphInfo.value.edges) return []
  return graphInfo.value.edges.map(e => ({
    source: e.source_node_uuid,
    target: e.target_node_uuid,
    fact: e.fact || e.name || ''
  }))
})

const GRAPH_COLORS = ['#FF5722', '#2196F3', '#4CAF50', '#9C27B0', '#FF9800', '#00BCD4', '#795548', '#607D8B']

function graphNodeType(n) {
  const labels = (n.labels || []).filter(l => l !== 'Entity')
  return labels.join(' / ') || t('world.graphNodeEntity')
}

function graphNodeColor(n) {
  const type = graphNodeType(n)
  let hash = 0
  for (const ch of type) hash = (hash * 31 + ch.codePointAt(0)) >>> 0
  return GRAPH_COLORS[hash % GRAPH_COLORS.length]
}

function graphNodeR(n) {
  const name = (n.name || '').length
  return name > 6 ? 14 : 11
}

function graphNodeX(uuid) {
  const p = graphPos.value[uuid]
  return p ? p.x : GV_W / 2
}

function graphNodeY(uuid) {
  const p = graphPos.value[uuid]
  return p ? p.y : GV_H / 2
}

const selectedGraphAttrs = computed(() => {
  const n = selectedGraphNode.value
  if (!n || !n.attributes) return []
  return Object.entries(n.attributes).filter(([k, v]) => {
    if (typeof v === 'string' && v.length > 200) return false
    return true
  }).slice(0, 12)
})

// 简易力导向布局（斥力 + 弹簧 + 重力，纯前端计算）
function layoutGraph(nodes, edges) {
  const pos = {}
  nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2
    pos[n.uuid] = {
      x: GV_W / 2 + Math.cos(angle) * 170,
      y: GV_H / 2 + Math.sin(angle) * 130
    }
  })
  const linkMap = new Map()
  edges.forEach(e => {
    for (const k of [e.source, e.target]) {
      if (!linkMap.has(k)) linkMap.set(k, new Set())
    }
    linkMap.get(e.source).add(e.target)
    linkMap.get(e.target).add(e.source)
  })
  for (let iter = 0; iter < 260; iter++) {
    // 斥力
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos[nodes[i].uuid]
        const b = pos[nodes[j].uuid]
        let dx = a.x - b.x
        let dy = a.y - b.y
        let d = Math.sqrt(dx * dx + dy * dy) || 1
        const force = 3200 / (d * d)
        dx /= d
        dy /= d
        a.x += dx * force
        a.y += dy * force
        b.x -= dx * force
        b.y -= dy * force
      }
    }
    // 弹簧（相连节点靠近）
    edges.forEach(e => {
      const a = pos[e.source]
      const b = pos[e.target]
      if (!a || !b) return
      let dx = b.x - a.x
      let dy = b.y - a.y
      let d = Math.sqrt(dx * dx + dy * dy) || 1
      const force = (d - 120) * 0.03
      dx /= d
      dy /= d
      a.x += dx * force
      a.y += dy * force
      b.x -= dx * force
      b.y -= dy * force
    })
    // 向心重力
    nodes.forEach(n => {
      const p = pos[n.uuid]
      p.x += (GV_W / 2 - p.x) * 0.012
      p.y += (GV_H / 2 - p.y) * 0.012
    })
  }
  nodes.forEach(n => {
    const p = pos[n.uuid]
    p.x = Math.max(60, Math.min(GV_W - 60, p.x))
    p.y = Math.max(40, Math.min(GV_H - 40, p.y))
  })
  return pos
}

async function fetchGraph() {
  try {
    const res = await getWorldGraph(projectId)
    graphInfo.value = res.graph || null
    if (graphInfo.value && graphInfo.value.nodes) {
      const edges = (graphInfo.value.edges || []).map(e => ({
        source: e.source_node_uuid,
        target: e.target_node_uuid
      }))
      graphPos.value = layoutGraph(graphInfo.value.nodes, edges)
    }
  } catch (e) {
    graphMsg.value = e.message || t('world.msgReadGraphFailed')
    graphMsgError.value = true
  }
}

function pollGraphTask(taskId) {
  graphPollTimer = setInterval(async () => {
    try {
      const res = await getTaskStatus(taskId)
      const task = res.task || res.data || res
      const status = task.status
      if (status === 'completed' || status === 'failed' || status === 'COMPLETED' || status === 'FAILED') {
        clearInterval(graphPollTimer)
        graphPollTimer = null
        graphBuilding.value = false
        graphProgressMsg.value = ''
        graphProgress.value = 0
        graphMsg.value = task.message || (status === 'completed' ? t('world.msgGraphBuilt') : t('world.msgGraphBuildFailed'))
        graphMsgError.value = !(status === 'completed' || status === 'COMPLETED')
        await fetchGraph()
      } else {
        graphProgressMsg.value = task.message || t('world.msgGraphBuilding')
        if (task.progress != null) graphProgress.value = task.progress
      }
    } catch (e) {
      clearInterval(graphPollTimer)
      graphPollTimer = null
      graphBuilding.value = false
      graphProgressMsg.value = ''
      const lost = e?.response?.status === 404 || /任务不存在|not found|404/i.test(e?.message || '')
      graphMsg.value = lost ? t('world.msgGraphTaskLost') : (e.message || t('world.msgGraphStatusQueryFailed'))
      graphMsgError.value = true
    }
  }, 3000)
}

async function handleBuildGraph() {
  if (graphBuilding.value) return
  graphBuilding.value = true
  graphMsg.value = ''
  graphMsgError.value = false
  graphProgressMsg.value = ''
  graphProgress.value = 0
  try {
    const res = await buildWorldGraph(projectId, {
      goal: simGoal.value.trim() || undefined,
      force: !!graphInfo.value,
      resume: !!graphInfo.value
    })
    graphMsg.value = res.message || t('world.msgGraphStarted')
    pollGraphTask(res.task_id)
  } catch (e) {
    graphBuilding.value = false
    graphMsg.value = (e.message || t('world.msgGraphStartFailed')) + t('world.checkModelConfig')
    graphMsgError.value = true
  }
}

// 补边：为已有世界图谱补充缺失的关联边（复用任务轮询）
function pollRefillEdgesTask(taskId) {
  if (refillPollTimerId) clearInterval(refillPollTimerId)
  refillPollTimerId = setInterval(async () => {
    try {
      const res = await getTaskStatus(taskId)
      const task = res.task || res.data || res
      const status = task.status
      if (status === 'completed' || status === 'failed' || status === 'COMPLETED' || status === 'FAILED') {
        clearInterval(refillPollTimerId)
        refillPollTimerId = null
        refillEdgesRunning.value = false
        graphMsg.value = task.message || (status === 'completed' ? t('world.msgRefillEdgesDone') : t('world.msgRefillEdgesFailed'))
        graphMsgError.value = !(status === 'completed' || status === 'COMPLETED')
        await fetchGraph()
      } else {
        graphMsg.value = task.message || t('world.msgRefillEdgesRunning')
        graphMsgError.value = false
      }
    } catch (e) {
      clearInterval(refillPollTimerId)
      refillPollTimerId = null
      refillEdgesRunning.value = false
      const lost = e?.response?.status === 404 || /任务不存在|not found|404/i.test(e?.message || '')
      graphMsg.value = lost ? t('world.msgRefillTaskLost') : (e.message || t('world.msgRefillEdgesStatusFailed'))
      graphMsgError.value = true
    }
  }, 3000)
}

async function handleRefillEdges() {
  if (refillEdgesRunning.value || !graphInfo.value || !graphInfo.value.node_count) return
  refillEdgesRunning.value = true
  graphMsg.value = ''
  graphMsgError.value = false
  try {
    // 补边是对已建图谱的重放，无需 goal 参数（与后端契约一致）
    const res = await refillWorldGraphEdges(projectId)
    if (res && res.task_id) {
      graphMsg.value = res.message || t('world.msgRefillEdgesStarted')
      pollRefillEdgesTask(res.task_id)
    } else {
      graphMsg.value = res.message || t('world.msgRefillEdgesDone')
      await fetchGraph()
      refillEdgesRunning.value = false
    }
  } catch (e) {
    refillEdgesRunning.value = false
    graphMsg.value = e.message || t('world.msgRefillEdgesStartFailed')
    graphMsgError.value = true
  }
}

// IPC 控制
const simCtlMsg = ref('')
const simCtlMsgError = ref(false)
const characters = ref([])
const interviewCharacter = ref('')
const interviewPrompt = ref('')
const interviewing = ref(false)
const interviewAnswer = ref('')
const interviewMsg = ref('')
const interviewMsgError = ref(false)

// 世界报告
const reportSimulationId = ref('')
const reportSimulationLabel = ref('')
const reportText = ref('')
const reportGenerating = ref(false)
const reportEmptyNote = ref('')

// what-if 推演
const whatIfBaseId = ref('')
const whatIfBaseLabel = ref('')
const whatIfQuestion = ref('')
const whatIfStarting = ref(false)
const whatIfActive = ref(false)
const whatIfQuestionAsked = ref('')
const whatIfEvents = ref([])
const whatIfMsg = ref('')
const whatIfMsgError = ref(false)
const whatIfing = ref('')

// 语义检索
const searchSemantic = ref(true)

const hasAnyInput = computed(() =>
  background.value.trim() || story.value.trim() || bgFiles.value.length || stFiles.value.length
)
const canDetect = computed(() => stats.value?.has_background && stats.value?.has_story)

// 简单 Markdown 渲染：## 标题、- 列表项、普通段落
const reportBlocks = computed(() => {
  const text = reportText.value || ''
  if (!text.trim()) return []
  const blocks = []
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trimEnd()
    if (!line.trim()) continue
    if (/^##\s+/.test(line)) {
      blocks.push({ type: 'h2', text: line.replace(/^##\s+/, '') })
    } else if (/^[-*]\s+/.test(line)) {
      blocks.push({ type: 'li', text: line.replace(/^[-*]\s+/, '') })
    } else if (/^#\s+/.test(line)) {
      blocks.push({ type: 'h2', text: line.replace(/^#\s+/, '') })
    } else {
      blocks.push({ type: 'p', text: line })
    }
  }
  return blocks
})

const typeLabel = key => t(`world.conflictTypes.${key}`)
const sevLabel = key => t(`world.severity.${key}`)
const statusLabel = key => t(`world.status.${key}`)
const defenseVerdictLabel = key => t(`world.defenseVerdicts.${key}`)

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function formatTime(iso) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 19)
}

function goBack() {
  // 返回首页（历史项目数据库可重新进入世界项目）；
  // 历史：曾跳 /process/<pid>（媒体分析流程页），对世界项目是死胡同
  router.push('/')
}

// ---------------- 项目快照导出 / 导入 ----------------

async function exportSnapshot() {
  if (snapshotBusy.value) return
  snapshotBusy.value = true
  saveMsg.value = ''; saveMsgError.value = false
  try {
    const res = await exportProjectSnapshot(projectId)
    const snapshot = res.snapshot || (res.data && res.data.snapshot) || null
    if (!snapshot) throw new Error(t('world.snapshotExportFailed'))
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${projectId}.miroworld.json`
    a.click()
    URL.revokeObjectURL(url)
    saveMsg.value = t('world.snapshotExported')
  } catch (e) {
    saveMsg.value = e?.message || t('world.snapshotExportFailed')
    saveMsgError.value = true
  } finally {
    snapshotBusy.value = false
  }
}

async function onImportSnapshot(e) {
  const file = e.target.files && e.target.files[0]
  e.target.value = ''
  if (!file) return
  snapshotBusy.value = true
  saveMsg.value = ''; saveMsgError.value = false
  try {
    const text = await file.text()
    const snapshot = JSON.parse(text)
    const res = await importProjectSnapshot(snapshot)
    const newId = res && res.data && res.data.project_id
    if (!newId) throw new Error(t('world.snapshotImportFailed'))
    saveMsg.value = t('world.snapshotImported', { id: newId })
    // 通知首页历史数据库刷新（若首页保持挂载则立即刷新）
    window.dispatchEvent(new CustomEvent('miroworld:history-reload'))
    // 路由参数变化时组件复用不会刷新 projectId，直接整页跳转
    setTimeout(() => { window.location.href = '/world/' + newId }, 800)
  } catch (err) {
    saveMsg.value = err?.message || t('world.snapshotImportFailed')
    saveMsgError.value = true
  } finally {
    snapshotBusy.value = false
  }
}

// ---------------- 内置项目助手 ----------------

async function askAssistantNow() {
  const q = assistantQuestion.value.trim()
  if (assistantAsking.value || !q) return
  assistantAsking.value = true
  assistantAnswer.value = ''
  assistantMsg.value = ''; assistantMsgError.value = false
  try {
    const res = await askAssistant(projectId, q)
    const answer = res?.data?.answer || ''
    if (!answer) throw new Error(t('assistant.emptyAnswer'))
    const actionResult = res?.data?.action_result
    assistantAnswer.value = actionResult
      ? answer + '\n\n' + JSON.stringify(actionResult, null, 2)
      : answer
  } catch (e) {
    assistantMsg.value = e?.message || t('assistant.failed')
    assistantMsgError.value = true
  } finally {
    assistantAsking.value = false
  }
}

async function quickAsk(key) {
  if (assistantAsking.value) return
  assistantAsking.value = true
  assistantAnswer.value = ''
  assistantMsg.value = ''; assistantMsgError.value = false
  try {
    let res
    if (key === 'assistant.quickStatus') {
      res = await runAssistantAction(projectId, 'get_project_status')
    } else if (key === 'assistant.quickGraph') {
      res = await runAssistantAction(projectId, 'build_world_graph', { resume: true })
    } else if (key === 'assistant.quickExtract') {
      res = await runAssistantAction(projectId, 'start_timeline_extraction', { source: 'bg', resume: true })
    } else if (key === 'assistant.quickTree') {
      res = await runAssistantAction(projectId, 'list_world_tree')
    } else if (key === 'assistant.quickWorldlineSummary') {
      const sid = simPollingId || (simHistory.value[0]?.simulation_id)
      if (!sid) throw new Error(t('world.msgUnknownError'))
      res = await runAssistantAction(projectId, 'get_worldline_summary', { simulation_id: sid })
    } else if (key === 'assistant.quickSim') {
      res = await runAssistantAction(projectId, 'start_world_simulation', {
        goal: simGoal.value.trim() || undefined,
        total_steps: simSteps.value,
        time_mode: simTimeMode.value,
        time_jumps: simTimeMode.value === 'narrative'
          ? simTimeJumps.value.split(/[,，]/).map(s => s.trim()).filter(Boolean)
          : [],
        story_summary_mode: simStorySummaryLlm.value ? 'llm' : 'rule',
        max_concurrency: simMaxConcurrency.value || 1,
      })
    } else if (key === 'assistant.quickCharacters') {
      res = await generateTimelineCharacters(projectId)
    } else if (key === 'assistant.quickReport') {
      res = await runAssistantAction(projectId, 'generate_final_report', { regenerate: true })
    } else if (key === 'assistant.quickExport') {
      res = await runAssistantAction(projectId, 'export_snapshot')
    } else {
      assistantQuestion.value = t(key)
      return askAssistantNow()
    }
    const answer = res?.data?.answer || res?.message || t('assistant.emptyAnswer')
    const actionResult = res?.data?.action_result || res?.data || {}
    assistantAnswer.value = answer + (Object.keys(actionResult).length ? '\n\n' + JSON.stringify(actionResult, null, 2) : '')
  } catch (e) {
    assistantMsg.value = e?.message || t('assistant.failed')
    assistantMsgError.value = true
  } finally {
    assistantAsking.value = false
  }
}

// ---------------- 文件选择与拖拽 ----------------

function pushFiles(target, fileList) {
  for (const f of fileList) {
    if (!target.value.some(x => x.name === f.name && x.size === f.size)) {
      target.value.push(f)
    }
  }
}

function onBgFilesChange(e) {
  pushFiles(bgFiles, e.target.files)
  e.target.value = ''
}

function onStFilesChange(e) {
  pushFiles(stFiles, e.target.files)
  e.target.value = ''
}

function onBgDrop(e) {
  bgDragging.value = false
  pushFiles(bgFiles, e.dataTransfer.files)
}

function onStDrop(e) {
  stDragging.value = false
  pushFiles(stFiles, e.dataTransfer.files)
}

async function loadAll() {
  loadError.value = ''
  try {
    const [statsRes, conflictsRes] = await Promise.all([
      getWorldSettings(projectId),
      getWorldConflicts(projectId)
    ])
    stats.value = statsRes.stats || null
    savedFiles.value = (stats.value && stats.value.files) || []
    report.value = conflictsRes.report || null
    // 预填任务目标（来自首页或上次保存）
    if (stats.value && stats.value.goal) {
      simGoal.value = stats.value.goal
    }
    await fetchGraph()
  } catch (e) {
    console.error('加载世界设定失败', e)
    loadError.value = e.message || t('world.loadFailed')
  }
}

function retryLoad() {
  loadAll()
}

async function loadSimTimelineEvents() {
  try {
    const res = await getTimeline(projectId, '')
    const body = res?.data || res || {}
    const events = body.events || body.data?.events || []
    simTimelineEvents.value = events.map(e => ({
      event_id: e.event_id || e.id,
      summary: e.summary || e.time_text || ''
    })).filter(e => e.event_id)
  } catch (e) {
    console.error('加载时间线事件列表失败', e)
    simTimelineEvents.value = []
  }
}

async function handleSave() {
  if (!hasAnyInput.value) return
  saving.value = true
  saveMsg.value = ''
  saveMsgError.value = false
  try {
    // 有文件 → multipart 多文件上传；只有文本 → JSON
    if (bgFiles.value.length || stFiles.value.length) {
      const formData = new FormData()
      for (const f of bgFiles.value) formData.append('background_files', f)
      for (const f of stFiles.value) formData.append('story_files', f)
      if (background.value.trim()) formData.append('background_text', background.value)
      if (story.value.trim()) formData.append('story_text', story.value)
      const res = await saveWorldInputMultipart(projectId, formData)
      stats.value = res.stats
      savedFiles.value = (res.stats && res.stats.files) || []
      const files = res.stats.files || []
      saveMsg.value = t('world.msgSavedFiles', { files: files.length, chunks: res.stats.total_chunks })
    } else {
      const res = await saveWorldInput(projectId, {
        background: background.value,
        story: story.value
      })
      stats.value = res.stats
      savedFiles.value = (res.stats && res.stats.files) || []
      saveMsg.value = t('world.msgSavedChunks', {
        chunks: res.stats.total_chunks,
        bg: res.stats.background_chunks,
        st: res.stats.story_chunks
      })
    }
  } catch (e) {
    saveMsg.value = e.message || t('world.msgSaveFailed')
    saveMsgError.value = true
  } finally {
    saving.value = false
  }
}

async function handleDetect() {
  if (!canDetect.value) return
  detecting.value = true
  saveMsg.value = ''
  saveMsgError.value = false
  try {
    const res = await detectWorldConflicts(projectId)
    let finished = false
    for (let i = 0; i < 120 && !finished; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const task = await getTaskStatus(res.task_id)
      if (task.status === 'completed') {
        saveMsg.value = t('world.msgConflictDone', { count: task.result?.conflict_count ?? 0 })
        finished = true
      } else if (task.status === 'failed') {
        saveMsg.value = t('world.msgConflictFailed', { err: task.error || t('world.msgUnknownError') })
        saveMsgError.value = true
        finished = true
      }
    }
    const conflictsRes = await getWorldConflicts(projectId)
    report.value = conflictsRes.report || null
  } catch (e) {
    saveMsg.value = e.message || t('world.msgDetectFailed')
    saveMsgError.value = true
  } finally {
    detecting.value = false
  }
}

async function setConflictStatus(conflict, status) {
  try {
    await updateConflictStatus(projectId, conflict.conflict_id, status, conflict.resolution_note || '')
    conflict.status = status
    await refreshConflictDetail(conflict)
    if (status === 'accepted' || status === 'dismissed') {
      await loadConflictCorrections(conflict, true)  // 生效 → 刷新改正文件
    }
  } catch (e) {
    console.error('更新冲突状态失败', e)
  }
}

// ---------------- 多轮辩解：完整历史加载（含每轮 effect 与 follow_up_effect） ----

/**
 * 从后端拉取单条冲突的完整多轮辩解历史，并把 effect / follow_up_effect 合并回
 * 本地 conflict 对象，供卡片展示。不会失败时不影响主流程。
 */
async function refreshConflictDetail(conflict) {
  try {
    const res = await getConflictHistory(projectId, conflict.conflict_id)
    const detail = res.conflict
    if (!detail) return
    conflict.defense_rounds = detail.defense_rounds || conflict.defense_rounds || []
    conflict.follow_up_effect = detail.follow_up_effect || conflict.follow_up_effect || ''
    // 逐轮补齐 effect（assistant 轮）
    for (const r of conflict.defense_rounds) {
      if (r && r.role === 'assistant' && r.effect && !r._effectShown) {
        r._effectShown = true
      }
    }
  } catch (e) {
    console.error('加载辩解历史失败', e)
  }
}

async function toggleConflictHistory(conflict) {
  conflict.historyOpen = !conflict.historyOpen
  if (conflict.historyOpen) {
    await refreshConflictDetail(conflict)
  }
}

// ---------------- 冲突改正文件（corrected_settings/corrected_story/corrections.json） ----

const corrGeneratingId = ref('')
const confRenderBusyId = ref('')

/**
 * 生成或读取冲突改正文件并挂到冲突对象上。
 * @param {Object} conflict  - 冲突对象（会写入 conflict.corrections）
 * @param {Boolean} generate - true=强制重新生成；false=仅读取（已有则不重复拉取）
 */
let corrNotifyTimer = null

async function loadConflictCorrections(conflict, generate = false) {
  try {
    corrGeneratingId.value = conflict.conflict_id
    let res
    if (generate) {
      res = await generateConflictCorrections(projectId, conflict.conflict_id)
    } else if (conflict.corrections && conflict.corrections.loaded) {
      return
    } else {
      res = await getConflictCorrections(projectId, conflict.conflict_id)
    }
    const hasFiles = Boolean(res.has_files) && !!(res.files && Object.keys(res.files).length)
    conflict.corrections = {
      hasFiles,
      count: res.correction_count || 0,
      patchCount: res.patch_count || 0,
      patches: res.patches || [],
      annotations: res.annotations || res.corrections || [],
      emptyReason: res.empty_reason || null,
      files: res.files || {},
      loaded: true,
      corrOpen: hasFiles,
      // 反馈状态
      message: generate ? { ok: true, text: successCorrectionMsg(res) } : conflict.corrections?.message || null,
      error: null,
    }
    // 成功提示条自动淡出
    if (generate) {
      if (corrNotifyTimer) clearTimeout(corrNotifyTimer)
      conflict.corrNotice = { ok: true, text: successCorrectionMsg(res) }
      corrNotifyTimer = setTimeout(() => { conflict.corrNotice = null }, 2600)
    } else if (!res.has_files) {
      conflict.corrNotice = { ok: true, text: t('world.corrEmptyNotice') }
    }
  } catch (e) {
    console.error('加载/生成改正文件失败', e)
    const msg = (e?.response?.data?.error) || (e?.message) || 'load-error'
    conflict.corrections = {
      hasFiles: false, count: 0, patchCount: 0, patches: [], annotations: [],
      emptyReason: null, files: {}, loaded: true,
      message: null, error: msg,
    }
    conflict.corrNotice = { ok: false, text: correctionErrorLabel(msg) }
  } finally {
    corrGeneratingId.value = ''
  }
}

function successCorrectionMsg(res) {
  const n = res.correction_count || 0
  const p = res.patch_count || 0
  if (n === 0) return t('world.corrMsgNoRulings')
  if (p === 0) return t('world.corrMsgAnnotationsOnly', { n })
  return t('world.corrMsgDone', { p })
}

function correctionErrorLabel(err) {
  if (typeof err === 'string' && err.startsWith('corrErr_')) {
    return t(`world.${err}`)
  }
  return t('world.corrErrGeneric', { e: err })
}

/**
 * 动态渲染合并全文（原始语料 + 外挂补丁）到冲突卡片内。
 */
async function renderCorrectionMerged(conflict, source) {
  confRenderBusyId.value = conflict.conflict_id
  try {
    const res = await renderConflictsCorrection(projectId, conflict.conflict_id, source)
    conflict.corrMerged = {
      source,
      text: res.text || '',
      applied: res.applied || [],
      skipped: res.skipped || [],
    }
  } catch (e) {
    console.error('渲染合并全文失败', e)
    conflict.corrMerged = { source, text: '', applied: [], skipped: [] }
  } finally {
    confRenderBusyId.value = ''
  }
}

/** 构造动态渲染下载 URL（下载时直接以 md 附件返回）。 */
function confCorrectionRenderUrl(projectId, conflictId, source, download) {
  const q = download ? '&download=1' : ''
  return `/api/world/${projectId}/conflicts/${conflictId}/corrections/render?source=${source}${q}`
}

// 冲突列表多选标记 通过/驳回
const conflictSelMode = ref(false)
const selConflictIds = ref([])
const batchConflictBusy = ref(false)
function isSelConflict(c) {
  return selConflictIds.value.includes(c.conflict_id)
}
function toggleConflictSelect(c) {
  const i = selConflictIds.value.indexOf(c.conflict_id)
  if (i >= 0) selConflictIds.value.splice(i, 1)
  else selConflictIds.value.push(c.conflict_id)
}
function toggleConflictSelMode() {
  conflictSelMode.value = !conflictSelMode.value
  if (!conflictSelMode.value) selConflictIds.value = []
}
async function runBatchConflictStatus(status) {
  const targets = report.value.conflicts.filter(c => isSelConflict(c))
  if (!targets.length || batchConflictBusy.value) return
  if (!window.confirm(t('world.batchConflictConfirm', { n: targets.length, st: status === 'accepted' ? t('world.acceptBg') : t('world.dismissConflict') }))) return
  batchConflictBusy.value = true
  let failed = 0
  for (const c of targets) {
    try {
      await updateConflictStatus(projectId, c.conflict_id, status, c.resolution_note || '')
      c.status = status
    } catch (e) {
      failed++
    }
  }
  batchConflictBusy.value = false
  // 提示
  alert(t('world.batchConflictResult', { done: targets.length - failed, failed }))
  selConflictIds.value = []
}
function runBatchAccept() { return runBatchConflictStatus('accepted') }
function runBatchDismiss() { return runBatchConflictStatus('dismissed') }

function toggleJustify(conflict) {
  if (conflict.justifyOpen) {
    conflict.justifyOpen = false
    return
  }
  conflict.justifyOpen = true
  conflict.justifyNote = conflict.resolution_note || ''
}

async function submitJustify(conflict) {
  const note = (conflict.justifyNote || '').trim()
  if (!note) return
  justifyingId.value = conflict.conflict_id
  try {
    await updateConflictStatus(projectId, conflict.conflict_id, 'justified', note)
    conflict.resolution_note = note
    conflict.justifyOpen = false
    conflict.historyOpen = true  // 自动展开历史，立即看到本轮裁定与效果
    await refreshConflictDetail(conflict)
    await loadConflictCorrections(conflict, true)  // 辩驳成功 → 拉取/刷新改正文件
  } catch (e) {
    console.error('提交自定义辩解失败', e)
  } finally {
    justifyingId.value = ''
  }
}

async function handleSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  searching.value = true
  try {
    const res = await searchWorld(projectId, { query: q, limit: 6, semantic: searchSemantic.value })
    searchResults.value = res.results || []
  } catch (e) {
    console.error('检索失败', e)
  } finally {
    searching.value = false
  }
}

// ---------------- 世界模拟 ----------------

async function loadSimHistory() {
  try {
    const res = await listWorldSimulations(projectId)
    simHistory.value = res.simulations || []
    // 若最新一条正在运行，继续轮询
    const latest = simHistory.value[0]
    if (latest && (latest.status === 'preparing' || latest.status === 'running' || latest.status === 'paused')) {
      simStatus.value = latest.status
      simProgress.value = latest.progress || {}
      simPollingId = latest.simulation_id
      loadCharacters(latest.simulation_id)
      startSimPolling(latest.simulation_id)
    } else if (latest && latest.status === 'completed') {
      simStatus.value = 'completed'
      simProgress.value = latest.progress || { current_step: 1, total_steps: 1, message: '完成' }
      simEvents.value = (latest.result || {}).events || []
      loadCharacters(latest.simulation_id)
    }
  } catch (e) {
    console.error('加载模拟历史失败', e)
  }
}

async function loadSimulation(sim) {
  try {
    const res = await getWorldSimulation(projectId, sim.simulation_id)
    const s = res.simulation
    simStatus.value = s.status
    simProgress.value = s.progress || {}
    simEvents.value = (s.result || {}).events || []
    simPollingId = s.simulation_id
    loadCharacters(s.simulation_id)
    simMsg.value = ''
    simMsgError.value = false
    if (s.status === 'running' || s.status === 'preparing' || s.status === 'paused') {
      startSimPolling(s.simulation_id)
    }
    simSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

function toggleCompareMode() {
  compareMode.value = !compareMode.value
  compareSelected.value = []
}

function toggleCompareSelect(sim) {
  const id = sim.simulation_id
  const idx = compareSelected.value.indexOf(id)
  if (idx >= 0) {
    compareSelected.value.splice(idx, 1)
  } else {
    if (compareSelected.value.length >= 2) {
      compareSelected.value.shift()
    }
    compareSelected.value.push(id)
  }
}

async function openCompare() {
  if (compareSelected.value.length < 2) return
  compareOpen.value = true
  compareData.value = []
  try {
    const items = []
    for (const sid of compareSelected.value) {
      const res = await getWorldSimulation(projectId, sid)
      const s = res.simulation
      items.push({
        simulation_id: s.simulation_id,
        status: s.status,
        created_at: s.created_at,
        event_count: (s.result || {}).event_count || 0,
        events: ((s.result || {}).events || []).slice(0, 20),
      })
    }
    compareData.value = items
  } catch (e) {
    compareData.value = []
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

async function continueSimulation(sim) {
  if (simStarting.value) return
  simStarting.value = true
  try {
    const res = await runAssistantAction(projectId, 'continue_world_simulation', {
      simulation_id: sim.simulation_id,
      additional_steps: 3,
    })
    const actionResult = res?.data?.action_result || {}
    simMsg.value = t('world.msgSimContinueStarted', { id: actionResult.simulation_id || sim.simulation_id })
    simMsgError.value = false
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  } finally {
    simStarting.value = false
  }
}

async function editWorldlineMeta(sim) {
  const currentName = sim.result?.meta?.name || ''
  const currentNote = sim.result?.meta?.note || ''
  const name = window.prompt(t('world.metaNamePrompt'), currentName)
  if (name === null) return
  const note = window.prompt(t('world.metaNotePrompt'), currentNote)
  if (note === null) return
  try {
    const res = await runAssistantAction(projectId, 'update_worldline_meta', {
      simulation_id: sim.simulation_id,
      name,
      note,
    })
    simMsg.value = t('world.msgMetaSaved')
    simMsgError.value = false
    metaUndoStack.value.push({ simulation_id: sim.simulation_id, name: currentName, note: currentNote })
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

async function undoLastMeta() {
  const last = metaUndoStack.value.pop()
  if (!last) return
  try {
    await runAssistantAction(projectId, 'update_worldline_meta', {
      simulation_id: last.simulation_id,
      name: last.name,
      note: last.note,
    })
    simMsg.value = t('world.msgMetaUndone')
    simMsgError.value = false
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

async function rerunBranchWithSettings(sim) {
  const question = sim.result?.meta?.whatif_question || simGoal.value.trim() || ''
  if (!question) {
    simMsg.value = t('world.msgNoBranchQuestion')
    simMsgError.value = true
    return
  }
  if (simStarting.value) return
  simStarting.value = true
  try {
    const jumps = simTimeJumps.value.split(/[,，、;；]+/).map(s => s.trim()).filter(Boolean)
    const res = await startWorldSimulation(projectId, {
      total_steps: simSteps.value || 6,
      time_step_minutes: simStepMin.value || 30,
      time_mode: simTimeMode.value || 'minutes',
      time_jumps: jumps,
      include_timeline: simUseTimeline.value,
      goal: question,
      story_summary_mode: simStorySummaryLlm.value ? 'llm' : 'rule',
      max_concurrency: simMaxConcurrency.value || 1,
    })
    const sim = res.simulation
    simMsg.value = t('world.msgRerunBranchStarted', { id: sim.simulation_id })
    simMsgError.value = false
    simPollingId = sim.simulation_id
    startSimPolling(sim.simulation_id)
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgSimStartFailed')
    simMsgError.value = true
  } finally {
    simStarting.value = false
  }
}

async function copyWorldline(sim) {
  const target = window.prompt(t('world.copyWorldlinePrompt'))
  if (!target || !target.trim()) return
  try {
    const res = await runAssistantAction(projectId, 'copy_worldline', {
      simulation_id: sim.simulation_id,
      target_project_id: target.trim(),
    })
    const r = res?.data?.action_result || {}
    simMsg.value = t('world.msgCopiedWorldline', { id: r.simulation_id || '' })
    simMsgError.value = false
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

function exportGraph() {
  const data = {
    nodes: eventGraphData.value.nodes.map(n => ({ id: n.id, label: n.label, step: n.step, character: n.event?.character_name })),
    edges: eventGraphData.value.edges,
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `event-graph-${Date.now()}.json`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function batchWhatIf(sim) {
  const input = window.prompt(t('world.batchWhatifPrompt'))
  if (!input) return
  const questions = input.split('\n').map(s => s.trim()).filter(Boolean)
  if (!questions.length) return
  if (simStarting.value) return
  simStarting.value = true
  try {
    const res = await runAssistantAction(projectId, 'batch_whatif', {
      simulation_id: sim.simulation_id,
      questions,
      steps: 3,
    })
    const started = res?.data?.action_result?.started || []
    simMsg.value = t('world.msgBatchWhatifStarted', { count: started.length })
    simMsgError.value = false
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  } finally {
    simStarting.value = false
  }
}

async function exportSimulation(sim) {
  try {
    const res = await getWorldSimulation(projectId, sim.simulation_id)
    const s = res.simulation
    const data = {
      simulation_id: s.simulation_id,
      project_id: projectId,
      status: s.status,
      created_at: s.created_at,
      events: (s.result || {}).events || [],
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${s.simulation_id}.json`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

async function mergeSelected() {
  if (compareSelected.value.length !== 2) return
  const [a, b] = compareSelected.value
  try {
    const res = await runAssistantAction(projectId, 'merge_worldlines', {
      base_simulation_id: a,
      branch_simulation_id: b,
      label: 'merged',
    })
    const r = res?.data?.action_result || {}
    simMsg.value = t('world.msgMerged', { id: r.simulation_id || '' })
    simMsgError.value = false
    compareMode.value = false
    compareSelected.value = []
    loadSimHistory()
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

function groupEventsByStep(events) {
  const groups = []
  const map = new Map()
  for (const e of events || []) {
    const key = `${e.step || 0}-${e.time || ''}`
    if (!map.has(key)) {
      const g = { step: e.step || 0, time: e.time || '', events: [] }
      map.set(key, g)
      groups.push(g)
    }
    map.get(key).events.push(e)
  }
  return groups
}

function exportCompareReport() {
  if (compareData.value.length < 2) return
  const lines = ['# 世界线对比报告', '']
  compareData.value.forEach((item, idx) => {
    lines.push(`## 世界线 ${idx + 1}：${item.simulation_id}`)
    lines.push(`- 状态：${item.status}`)
    lines.push(`- 事件数：${item.event_count}`)
    lines.push('')
    groupEventsByStep(item.events).forEach(g => {
      lines.push(`### 第 ${g.step} 步 · ${g.time}`)
      g.events.forEach(e => {
        lines.push(`- ${e.character_name} 在 ${e.location}：${e.action_desc} → ${e.result}`)
      })
      lines.push('')
    })
  })
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `worldline-compare-${Date.now()}.md`
  a.style.display = 'none'
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function exportAllWorldlines() {
  try {
    const res = await runAssistantAction(projectId, 'export_all_worldlines')
    const sims = res?.data?.action_result?.simulations || []
    const blob = new Blob([JSON.stringify(sims, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `worldlines-${projectId}.json`
    a.style.display = 'none'
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    simMsg.value = e?.message || t('world.msgUnknownError')
    simMsgError.value = true
  }
}

function runGlobalSearch() {
  const q = globalSearch.value.trim().toLowerCase()
  if (!q) {
    globalSearchResults.value = []
    return
  }
  const results = []
  ;(simEvents.value || []).forEach((e) => {
    const hay = `${e.character_name || ''} ${e.action_desc || ''} ${e.result || ''} ${e.location || ''}`.toLowerCase()
    if (hay.includes(q)) {
      results.push({ type: 'sim', step: e.step, time: e.time, text: `${e.character_name}：${e.action_desc || ''}` })
    }
  })
  ;(simTimelineEvents.value || []).forEach((e) => {
    const hay = `${e.summary || ''} ${e.characters || ''}`.toLowerCase()
    if (hay.includes(q)) {
      results.push({ type: 'timeline', time: e.time_text || '', text: (e.summary || '').slice(0, 80) })
    }
  })
  globalSearchResults.value = results.slice(0, 30)
  globalSearchOpen.value = true
}

function closeGuide() {
  localStorage.setItem('miroworld.guide.v1', '1')
  showGuide.value = false
}

function extractCharacters(events) {
  const set = new Set()
  for (const e of events || []) {
    if (e.character_name) set.add(e.character_name)
  }
  return Array.from(set)
}

async function loadCharacters(simulationId) {
  try {
    const res = await getWorldSimulation(projectId, simulationId)
    const events = (res.simulation.result || {}).events || []
    characters.value = extractCharacters(events)
  } catch (e) {
    console.error('加载角色列表失败', e)
  }
}

function startSimPolling(simulationId) {
  if (simPollTimer) clearInterval(simPollTimer)
  simPollTimer = setInterval(async () => {
    try {
      const res = await getWorldSimulation(projectId, simulationId)
      const sim = res.simulation
      simStatus.value = sim.status
      simProgress.value = sim.progress || {}
      if (sim.status === 'completed') {
        clearInterval(simPollTimer)
        simPollTimer = null
        simProgress.value = sim.progress || { current_step: 1, total_steps: 1, message: '完成' }
        simEvents.value = (sim.result || {}).events || []
        characters.value = extractCharacters(simEvents.value)
        simMsg.value = t('world.msgSimDone', { count: (sim.result || {}).event_count || 0 })
        simMsgError.value = false
        // 完成后打开该模拟的报告（若有则直接显示）
        openChartRecord(sim)
        loadSimHistory()
      } else if (sim.status === 'failed' || sim.status === 'stopped') {
        clearInterval(simPollTimer)
        simPollTimer = null
        simMsg.value = sim.status === 'failed'
          ? t('world.msgSimFailed', { err: sim.error || t('world.msgUnknownError') })
          : t('world.msgSimStopped')
        simMsgError.value = sim.status === 'failed'
        loadSimHistory()
      }
    } catch (e) {
      console.error('轮询模拟状态失败', e)
    }
  }, 5000)
}

async function handleStartSim() {
  if (simStarting.value || simStatus.value === 'running') return
  simStarting.value = true
  simMsg.value = ''
  simMsgError.value = false
  simCtlMsg.value = ''
  simCtlMsgError.value = false
  try {
    const jumps = simTimeJumps.value
      .split(/[,，、;；]+/)
      .map(s => s.trim())
      .filter(Boolean)
    const res = await startWorldSimulation(projectId, {
      total_steps: simSteps.value || 6,
      time_step_minutes: simStepMin.value || 30,
      time_mode: simTimeMode.value || 'minutes',
      time_jumps: jumps,
      include_timeline: simUseTimeline.value,
      story_summary_mode: simStorySummaryLlm.value ? 'llm' : 'rule',
      max_concurrency: simMaxConcurrency.value || 1,
      from_event_id: simStartEventId.value || undefined,
      goal: simGoal.value.trim() || undefined
    })
    const sim = res.simulation
    simStatus.value = 'running'
    simMsg.value = t('world.msgSimStarted', { id: sim.simulation_id })
    simEvents.value = []
    characters.value = []
    reportSimulationId.value = ''
    reportText.value = ''
    reportEmptyNote.value = ''
    simPollingId = sim.simulation_id
    startSimPolling(sim.simulation_id)
  } catch (e) {
    // 优先展示后端真实 error；仅当错误明确与模型/配置相关时才追加"请检查模型配置"提示，
    // 避免把任意 400（校验、缺失字段、LLM 返回异常等）误报成配置问题。
    const backendError = e.message || t('world.msgSimStartFailed')
    const modelRelated = /模型|配置|model|config|LLM|api[ -_]?key|api.?key|not configured|unavailable/i.test(backendError)
    simMsg.value = modelRelated ? backendError + t('world.checkModelConfig') : backendError
    simMsgError.value = true
    simStatus.value = 'idle'
  } finally {
    simStarting.value = false
  }
}

// ---------------- IPC 控制 ----------------

async function handleControl(action) {
  if (!simPollingId) return
  simCtlMsg.value = ''
  simCtlMsgError.value = false
  try {
    const res = await controlWorldSimulation(projectId, simPollingId, { action })
    if (action === 'pause') {
      simStatus.value = 'paused'
      simCtlMsg.value = t('world.msgCtlPaused')
    } else if (action === 'resume') {
      simStatus.value = 'running'
      simCtlMsg.value = t('world.msgCtlResumed')
    } else if (action === 'stop') {
      clearInterval(simPollTimer)
      simPollTimer = null
      simStatus.value = 'stopped'
      simCtlMsg.value = t('world.msgCtlStopped', { cmd: res.command_id })
      // 刷新历史
      setTimeout(() => loadSimHistory(), 1500)
    }
  } catch (e) {
    simCtlMsg.value = e.message || t('world.msgCtlFailed')
    simCtlMsgError.value = true
  }
}

function selectCharacter(name) {
  interviewCharacter.value = name
  interviewAnswer.value = ''
  interviewMsg.value = ''
  interviewMsgError.value = false
}

async function handleInterview() {
  if (!interviewCharacter.value || !interviewPrompt.value.trim()) return
  if (!simPollingId) return
  interviewing.value = true
  interviewAnswer.value = ''
  interviewMsg.value = ''
  interviewMsgError.value = false
  try {
    const res = await controlWorldSimulation(projectId, simPollingId, {
      action: 'interview',
      character_name: interviewCharacter.value,
      prompt: interviewPrompt.value.trim()
    })
    const result = res.result || {}
    // 采访响应可能是字符串或结构化对象
    interviewAnswer.value = typeof result === 'string'
      ? result
      : (result.answer || result.text || result.response || result.content || JSON.stringify(result, null, 2))
  } catch (e) {
    interviewMsg.value = e.message || t('world.msgInterviewFailed')
    interviewMsgError.value = true
  } finally {
    interviewing.value = false
  }
}

// ---------------- 世界小说续写 ----------------

async function openChartRecord(sim) {
  // sim 可能是 dict 或 {simulation_id, created_at}
  const simId = typeof sim === 'object' ? (sim.simulation_id || sim['simulation_id']) : sim
  if (!simId) return
  reportSimulationId.value = simId
  reportText.value = ''
  reportEmptyNote.value = ''
  const time = (sim.created_at || '').replace('T', ' ').slice(0, 16)
  reportSimulationLabel.value = time ? `（${time}）` : ''
  // 先尝试读取已生成小说续写
  try {
    const res = await getWorldNovel(projectId, simId)
    if (res.novel && res.novel.text) {
      reportText.value = res.novel.text
      return
    }
  } catch (e) {
    // 小说尚未生成，保持生成按钮
  }
}

async function handleGenerateReport() {
  if (!reportSimulationId.value) return
  reportGenerating.value = true
  reportText.value = ''
  reportEmptyNote.value = ''
  try {
    const res = await generateWorldNovel(projectId, reportSimulationId.value)
    if (res.novel && res.novel.text) {
      reportText.value = res.novel.text
    } else {
      reportEmptyNote.value = t('world.msgNovelEmpty')
    }
  } catch (e) {
    reportEmptyNote.value = e.message || t('world.msgNovelFailed')
  } finally {
    reportGenerating.value = false
  }
}

// ---------------- what-if 推演 ----------------

function startWhatIf(h) {
  if (h.status !== 'completed') return
  whatIfBaseId.value = h.simulation_id
  whatIfBaseLabel.value = formatTime(h.created_at)
  whatIfQuestion.value = ''
  whatIfMsg.value = ''
  whatIfMsgError.value = false
  whatIfActive.value = false
  whatIfEvents.value = []
  whatIfQuestionAsked.value = ''
}

function cancelWhatIf() {
  whatIfBaseId.value = ''
  whatIfQuestion.value = ''
}

async function confirmWhatIf() {
  const q = whatIfQuestion.value.trim()
  if (!whatIfBaseId.value || !q) return
  whatIfStarting.value = true
  whatIfMsg.value = ''
  whatIfMsgError.value = false
  try {
    const res = await simulateWorldWhatIf(projectId, {
      base_simulation_id: whatIfBaseId.value,
      question: q,
      steps: 3
    })
    const sim = res.simulation
    whatIfActive.value = true
    whatIfQuestionAsked.value = q
    whatIfEvents.value = (sim.result || {}).events || []
    whatIfBaseId.value = ''
    whatIfQuestion.value = ''
    // 轮询该推演分支完成
    pollWhatIf(sim.simulation_id, q)
    // 刷新历史，把新推演记录加入
    loadSimHistory()
  } catch (e) {
    whatIfMsg.value = e.message || t('world.msgWhatifStartFailed')
    whatIfMsgError.value = true
  } finally {
    whatIfStarting.value = false
  }
}

function pollWhatIf(simulationId, question) {
  if (whatIfPollTimer) clearInterval(whatIfPollTimer)
  let tries = 0
  whatIfPollTimer = setInterval(async () => {
    tries++
    try {
      const r = await getWorldSimulation(projectId, simulationId)
      const sim = r.simulation
      if (sim.status === 'completed') {
        clearInterval(whatIfPollTimer)
        whatIfPollTimer = null
        whatIfEvents.value = (sim.result || {}).events || []
        whatIfMsg.value = t('world.msgWhatifDone', { count: (sim.result || {}).event_count || 0 })
        whatIfMsgError.value = false
      } else if (sim.status === 'failed' || tries > 120) {
        clearInterval(whatIfPollTimer)
        whatIfPollTimer = null
        whatIfMsg.value = sim.status === 'failed' ? t('world.msgWhatifFailed', { err: sim.error || t('world.msgUnknownError') }) : t('world.msgWhatifTimeout')
        whatIfMsgError.value = true
      }
    } catch (e) {
      console.error('轮询推演状态失败', e)
    }
  }, 5000)
}

onMounted(() => {
  loadAll()
  loadSimHistory()
  loadSimTimelineEvents()

  // 新手引导：首次进入显示 5 步说明
  if (!localStorage.getItem('miroworld.guide.v1')) {
    showGuide.value = true
  }

  // 从推演回放 Step2 进入时，自动滚动到世界模拟模块
  if (route.query.replay) {
    setTimeout(() => {
      simSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 600)
  }
})

onUnmounted(() => {
  // 离开页面立即停止所有轮询，避免计时器泄漏与后台请求堆积
  if (graphPollTimer) { clearInterval(graphPollTimer); graphPollTimer = null }
  if (refillPollTimerId) { clearInterval(refillPollTimerId); refillPollTimerId = null }
  if (simPollTimer) { clearInterval(simPollTimer); simPollTimer = null }
  if (whatIfPollTimer) { clearInterval(whatIfPollTimer); whatIfPollTimer = null }
  if (playbackTimer) { clearInterval(playbackTimer); playbackTimer = null }
})
</script>

<style scoped>
/* 与主界面一致的视觉规范 */
.world-view.high-contrast {
  background: #fff;
}
.world-view.high-contrast .step-card,
.world-view.high-contrast .sim-events,
.world-view.high-contrast .sim-graph,
.world-view.high-contrast .world-tree {
  border-color: #666 !important;
  box-shadow: none !important;
}
.world-view.high-contrast .step-title,
.world-view.high-contrast .tree-node-name,
.world-view.high-contrast .sim-event-who {
  color: #000 !important;
  font-weight: 700;
}
.world-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: transparent;   /* 透出全局渐变光底 */
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'PingFang SC',
    'Noto Sans SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
  color: #10203a;
}

/* Header（与 MainView 一致） */
.app-header {
  height: 60px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: saturate(180%) blur(18px);
  -webkit-backdrop-filter: saturate(180%) blur(18px);
  z-index: 100;
  position: relative;
  flex-shrink: 0;
  box-shadow: 0 1px 12px rgba(16, 32, 58, 0.06);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}
.step-divider {
  width: 1px;
  height: 14px;
  background-color: #E0E0E0;
}
.workflow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #999;
}
.step-name {
  font-weight: 700;
  color: #000;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.project-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #999;
}
.back-btn {
  border: none;
  background: #000;
  color: #FFF;
  padding: 8px 14px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}
.back-btn:hover {
  opacity: 0.8;
}
.back-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Miro World 新 5 步导航 */
.world-step-nav {
  display: flex;
  gap: 8px;
  padding: 10px 24px;
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.6);
  flex-shrink: 0;
  overflow-x: auto;
  z-index: 90;
}
.world-step-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.55);
  color: #10203a;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.18s ease;
}
.world-step-btn:hover {
  background: rgba(161, 197, 10, 0.15);
  border-color: #a1c50a;
}
.ws-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #a1c50a;
}
.ws-label {
  color: #10203a;
}
.world-search {
  position: relative;
  margin-left: auto;
  min-width: 200px;
}
.world-search-input {
  width: 100%;
  border: 1px solid #E0E0E0;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  background: rgba(255,255,255,0.8);
  color: #10203a;
}
.world-search-results {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: #fff;
  border: 1px solid #EAEAEA;
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
  max-height: 260px;
  overflow-y: auto;
  z-index: 200;
}
.world-search-result {
  display: flex;
  gap: 8px;
  padding: 7px 10px;
  font-size: 12px;
  border-bottom: 1px solid #F5F5F5;
  cursor: default;
}
.wsr-type {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #a1c50a;
  font-weight: 700;
}
.wsr-text {
  color: #333;
  line-height: 1.4;
}

/* Body */
.world-body {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1000px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
  position: relative;
}

/* Miro World 新 5 步：视觉排序 = 世界设定 → 时间线与图谱 → 世界模拟 */
.world-body > .step-card { order: 10; }
.step-input { order: 1; }
.step-timeline { order: 2; }
.step-graph { order: 3; }
.step-conflict { order: 4; }
.step-search { order: 5; }
.step-sim { order: 6; }

/* 新手引导 */
.world-guide {
  order: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 16px 20px;
  border: 1px solid rgba(161, 197, 10, 0.35);
  border-radius: 12px;
  background: rgba(161, 197, 10, 0.08);
}
.guide-title {
  font-size: 15px;
  font-weight: 700;
  color: #10203a;
}
.guide-text {
  flex: 1;
  min-width: 220px;
  font-size: 13px;
  color: #536078;
  line-height: 1.6;
}
.guide-btn {
  width: auto;
  padding: 10px 18px;
  background: #a1c50a;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.load-error-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-left: 3px solid #D32F2F;
  background: #f3f7e6;
  color: #8C211C;
  font-size: 12px;
  line-height: 1.5;
}
.load-error-bar .action-btn {
  flex-shrink: 0;
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid #8C211C;
  background: #fff;
  color: #8C211C;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

/* 卡片（与 Step1 的 step-card 一致；液态玻璃风格）—— 更透明，透出背景光晕 */
.step-card {
  background: rgba(255,255,255,0.16);
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.05), inset 0 1px 0 rgba(255,255,255,0.85);
  border: 1px solid rgba(255,255,255,0.68);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  transition: all 0.3s ease;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.step-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.step-title {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.5px;
}
.badge {
  font-size: 10px;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}
.badge.success { background: #E8F5E9; color: #2E7D32; }
.badge.processing { background: #a1c50a; color: #FFF; }
.badge.hint { background: #F5F5F5; color: #666; }

/* 输入区 */
.input-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 720px) {
  .input-grid { grid-template-columns: 1fr; }
}
.input-label {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  letter-spacing: 0.3px;
}
.char-count {
  color: #999;
  font-weight: 400;
  font-size: 11px;
}
.world-textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  padding: 10px 12px;
}
.world-textarea:focus {
  outline: none;
  border-color: #a1c50a;
  background: #FFF;
}
.world-textarea::placeholder {
  color: #BBB;
}

/* 文件上传区 */
.drop-zone {
  border: 1.5px dashed #CCC;
  border-radius: 4px;
  padding: 14px 12px;
  margin-bottom: 8px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: #FAFAFA;
}
.drop-zone:hover {
  border-color: #a1c50a;
}
.drop-zone.drag-over {
  border-color: #a1c50a;
  background: #FFF3EE;
}
.drop-icon {
  display: block;
  font-size: 18px;
  margin-bottom: 4px;
}
.drop-text {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  color: #000;
}
.drop-hint {
  display: block;
  font-size: 10.5px;
  color: #999;
  margin-top: 3px;
}
.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 5px 10px;
  background: #FAFAFA;
  font-size: 11.5px;
}
.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #000;
}
.file-size {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  flex-shrink: 0;
}
.file-remove {
  border: none;
  background: none;
  color: #999;
  font-size: 15px;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
  flex-shrink: 0;
}
.file-remove:hover {
  color: #D32F2F;
}
.saved-file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.saved-file-title {
  font-size: 10.5px;
  font-weight: 700;
  color: #5f7008;
}
.file-item.saved {
  border-style: dashed;
  border-color: #d5e0a8;
  background: #f7f9ef;
}
.file-badge {
  color: #5f7008;
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}

/* 世界模拟 */
.description {
  font-size: 12px;
  color: #666;
  line-height: 1.6;
  margin-bottom: 12px;
}
.sim-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.sim-progress-bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: #F0F0F0;
  overflow: hidden;
}
.sim-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: #a1c50a;
  transition: width 0.3s ease;
}
.sim-progress-text {
  font-size: 11px;
  color: #666;
  white-space: nowrap;
}
.sim-controls {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.sim-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sim-field-wide {
  flex-basis: 100%;
}
.sim-goal-input {
  width: 100%;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 8px 10px;
  resize: vertical;
}
.sim-goal-input:focus {
  outline: none;
  border-color: #a1c50a;
  background: #FFF;
}
.sim-label {
  font-size: 10.5px;
  color: #999;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sim-input {
  width: 90px;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12.5px;
  padding: 8px 10px;
}
.sim-input:focus {
  outline: none;
  border-color: #a1c50a;
  background: #FFF;
}
.sim-start {
  flex: 1;
  min-width: 160px;
}
.sim-events {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  overflow: hidden;
}
.sim-events-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 8px 12px;
  background: #F5F5F5;
  border-bottom: 1px solid #EAEAEA;
}
.sim-event {
  display: grid;
  grid-template-columns: 72px 90px 1fr;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #F0F0F0;
  font-size: 12px;
  align-items: start;
}
.sim-event.clickable {
  cursor: pointer;
}
.sim-event.clickable:hover {
  background: #F7F9E8;
}
.sim-event:last-child {
  border-bottom: none;
}
.sim-step-group {
  border-bottom: 1px solid #F0F0F0;
}
.sim-step-head {
  padding: 6px 12px;
  background: #FAFAFA;
  font-size: 11px;
  font-weight: 700;
  color: #a1c50a;
  border-bottom: 1px solid #F0F0F0;
}
.sim-playback {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #FAFAFA;
  border-bottom: 1px solid #F0F0F0;
}
.sim-quality {
  padding: 8px 12px;
  background: #FFF8F0;
  border-bottom: 1px solid #F0E0D0;
}
.sim-quality-item {
  font-size: 12px;
  color: #B26A00;
  line-height: 1.6;
}
.sim-playback-info {
  font-size: 11px;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}
.sim-step-group.active {
  background: #F7F9E8;
  box-shadow: inset 3px 0 0 #a1c50a;
}
.sim-summary {
  padding: 10px 12px;
  background: #FDFDF6;
  border-bottom: 1px solid #F0F0F0;
}
.sim-summary-item {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
  padding: 3px 0;
  color: #444;
}
.sim-summary-step {
  flex-shrink: 0;
  font-weight: 700;
  color: #a1c50a;
  font-family: 'JetBrains Mono', monospace;
}
.sim-summary-text {
  color: #333;
}
.sim-event-time {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.sim-event-who {
  font-weight: 600;
  color: #000;
}
.sim-event-where {
  color: #666;
  font-size: 11px;
}
.sim-event-what {
  color: #333;
  line-height: 1.5;
}
.sim-history {
  margin-top: 14px;
}
.sim-history-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.sim-history-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid #F5F5F5;
  font-size: 11.5px;
}
.sim-history-time {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.sim-history-status {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.sim-history-status.completed { background: #E8F5E9; color: #2E7D32; }
.sim-history-status.failed { background: #FFEBEE; color: #C62828; }
.sim-history-status.running { background: #f3f7e6; color: #5f7008; }
.sim-history-status.preparing { background: #f3f7e6; color: #5f7008; }
.sim-history-status.created { background: #F5F5F5; color: #666; }

/* 世界线之树 */
.world-tree {
  margin-top: 14px;
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  padding: 12px;
  background: #FCFCFC;
}
.world-tree-title {
  font-size: 12px;
  font-weight: 700;
  color: #10203a;
  margin-bottom: 8px;
}
.tree-node {
  margin-bottom: 6px;
}
.tree-node.child {
  margin-left: 22px;
  border-left: 1px dashed #D8D8D8;
  padding-left: 10px;
}
.tree-node-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 4px 0;
  font-size: 11.5px;
}
.tree-node-name {
  font-weight: 600;
  color: #10203a;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-node-count {
  color: #999;
  font-size: 11px;
}
.tree-branch {
  color: #a1c50a;
  font-family: 'JetBrains Mono', monospace;
}

/* 事件因果图 */
.sim-graph {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  padding: 12px;
  background: #FCFCFC;
  overflow-x: auto;
}
.sim-graph-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  font-weight: 700;
  color: #10203a;
  margin-bottom: 8px;
}
.sim-graph-filter {
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 3px 6px;
  font-size: 11px;
}
.sim-graph-zoom {
  font-size: 11px;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  min-width: 40px;
  text-align: center;
}
.sim-graph-zoom-wrap {
  transition: transform 0.2s ease;
}
.sim-graph-svg {
  width: 100%;
  height: auto;
  min-width: 600px;
  display: block;
}
.sim-graph-edge {
  stroke: #D8D8D8;
  stroke-width: 1.2;
}
.sim-graph-node {
  fill: #a1c50a;
  stroke: #fff;
  stroke-width: 1.5;
  cursor: pointer;
}
.sim-graph-node.active {
  fill: #10203a;
}
.sim-graph-label {
  font-size: 9px;
  fill: #536078;
  pointer-events: none;
}
.sim-graph-detail {
  margin-top: 10px;
  padding: 8px 10px;
  background: #F5F7E8;
  border-radius: 6px;
  font-size: 12px;
}
.sim-graph-detail-inner {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: baseline;
}
.sim-graph-detail-step {
  font-weight: 700;
  color: #a1c50a;
  font-family: 'JetBrains Mono', monospace;
}
.sim-graph-detail-who {
  font-weight: 600;
}
.sim-graph-detail-text {
  color: #333;
  line-height: 1.5;
}
.sim-history-count {
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

/* 按钮行 */
.btn-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.action-btn {
  flex: 1;
  background: #000;
  color: #FFF;
  border: none;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-family: inherit;
}
.action-btn:hover:not(:disabled) {
  opacity: 0.8;
}
.action-btn:disabled {
  background: #CCC;
  cursor: not-allowed;
}
.btn-ghost {
  background: #FFF;
  color: #000;
  border: 1px solid #000;
}
.btn-ghost:hover:not(:disabled) {
  opacity: 1;
  background: #F5F5F5;
}
.btn-ghost:disabled {
  background: #FFF;
  border-color: #E0E0E0;
  color: #999;
}
.spinner-sm {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
.btn-ghost .spinner-sm {
  border-color: #CCC;
  border-top-color: #000;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 消息 */
.msg-line {
  margin-top: 12px;
  font-size: 12px;
  color: #2E7D32;
}
.msg-line.error {
  color: #D32F2F;
}

/* 统计 */
.stats-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}
.stat-item {
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 8px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 80px;
  background: #FAFAFA;
}
.stat-value {
  font-size: 18px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', monospace;
}
.stat-label {
  font-size: 10px;
  color: #999;
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 报告元信息 */
.report-meta {
  font-size: 11px;
  color: #999;
  margin-bottom: 12px;
  font-family: 'JetBrains Mono', monospace;
}
.empty-note {
  font-size: 13px;
  color: #2E7D32;
  padding: 12px 0;
}

/* 冲突列表 */
.conflict-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.conflict-item {
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 14px;
  background: #FAFAFA;
}
.conflict-item.sev-high { border-left: 3px solid #D32F2F; }
.conflict-item.sev-medium { border-left: 3px solid #F57C00; }
.conflict-item.sev-low { border-left: 3px solid #388E3C; }
.conflict-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.detail-type-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: #E8EAF6;
  color: #3F51B5;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.severity-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
}
.severity-tag.sev-high { background: #FFEBEE; color: #C62828; }
.severity-tag.sev-medium { background: #f3f7e6; color: #5f7008; }
.severity-tag.sev-low { background: #E8F5E9; color: #2E7D32; }
.conflict-topic {
  font-weight: 600;
  font-size: 13px;
  flex: 1;
}
/* 冲突批量选择 */
.conflict-item.sel-mode { cursor: pointer; }
.conflict-sel { display: inline-flex; align-items: center; }
.conflict-sel .sel-box {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid #9CA3AF;
  border-radius: 4px;
  background: #FFF;
  cursor: pointer;
}
.conflict-sel .sel-box.checked { background: #a1c50a; border-color: #a1c50a; position: relative; }
.conflict-sel .sel-box.checked::after {
  content: '✓';
  position: absolute;
  inset: 0;
  color: #FFF;
  font-size: 11px;
  line-height: 12px;
  text-align: center;
}
.bat-count { font-size: 11px; color: #666; }
.step-status { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }

.conflict-status {
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: #F5F5F5;
  color: #999;
}
.conflict-status.accepted {
  background: #E8F5E9;
  color: #2E7D32;
}
.conflict-status.dismissed {
  opacity: 0.6;
}

/* 左右对比 */
.conflict-compare {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 12px;
  margin-top: 12px;
  align-items: start;
}
@media (max-width: 720px) {
  .conflict-compare { grid-template-columns: 1fr; }
}
.side-box {
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 10px 12px;
  background: #FFF;
}
.side-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.side-label.bg { color: #3F51B5; }
.side-label.st { color: #00838F; }
.side-fact {
  font-size: 12.5px;
  line-height: 1.6;
}
.side-quote {
  font-size: 11px;
  color: #999;
  margin-top: 4px;
  line-height: 1.5;
}
.vs-mark {
  align-self: center;
  color: #999;
  font-weight: 700;
  font-size: 14px;
}

/* 原因与建议 */
.conflict-reason {
  font-size: 12px;
  color: #666;
  margin-top: 10px;
  line-height: 1.6;
}
.conflict-suggestion {
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.6;
}
.conflict-suggestion::before {
  content: "💡 ";
}
.conflict-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.mini-btn {
  border: 1px solid #E0E0E0;
  background: #FFF;
  color: #666;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s;
}
.mini-btn:hover:not(:disabled) {
  border-color: #000;
  color: #000;
}
.mini-btn.active {
  background: #000;
  border-color: #000;
  color: #FFF;
}
.mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mini-btn.primary {
  background: #000;
  border-color: #000;
  color: #FFF;
}
.mini-btn.primary:hover:not(:disabled) {
  background: #333;
  border-color: #333;
}
.conflict-justify {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}
.justify-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  resize: vertical;
  font-family: inherit;
  color: #000;
}
.conflict-resolution-note {
  margin-top: 8px;
  padding: 8px 10px;
  background: #F3E8FF;
  border: 1px solid #E9D5FF;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
}
.crn-label {
  font-weight: 700;
  color: #6B21A8;
  margin-right: 6px;
}
.crn-text {
  color: #4A044E;
}

/* ---- 辩驳：明显按钮 ---- */
.refute-btn {
  background: #a1c50a;
  border-color: #a1c50a;
  color: #fff;
  font-weight: 700;
}
.refute-btn:hover:not(:disabled):not(.active) {
  background: #8fae09;
  border-color: #8fae09;
}
.refute-btn.active {
  background: #6f8a06;
  border-color: #6f8a06;
}

/* ---- 辩驳：后续影响（follow_up_effect）---- */
.conflict-followup {
  margin-top: 8px;
  padding: 8px 10px;
  background: #E8F5E9;
  border: 1px solid #C8E6C9;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
}
.cfu-label {
  font-weight: 700;
  color: #1B5E20;
  margin-right: 6px;
}
.cfu-text {
  color: #224B0E;
}

/* ---- 辩驳：历史时间线 ---- */
.conflict-defense-history {
  margin-top: 12px;
  border-top: 1px dashed #E0E0E0;
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cdh-title {
  font-size: 12px;
  font-weight: 700;
  color: #333;
  margin-bottom: 2px;
}
.defense-round {
  border: 1px solid #E3E3E3;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
  background: #FAFAFA;
}
.defense-round.user {
  border-left: 3px solid #333;
  background: #F5F5F5;
}
.defense-round.assistant {
  border-left: 3px solid #a1c50a;
  background: #FCFDF5;
}
.defense-round-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.defense-role {
  font-weight: 700;
  color: #333;
  font-size: 11px;
}
.defense-verdict {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  background: #EEEEEE;
  color: #555;
}
.defense-content {
  margin: 0;
  color: #333;
}
.defense-effect {
  margin-top: 6px;
  padding: 6px 8px;
  background: #FFF3E0;
  border: 1px solid #FFE0B2;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
}
.de-label {
  font-weight: 700;
  color: #E65100;
  margin-right: 6px;
}
.de-text {
  color: #BF360C;
}

/* ---- 冲突改正文件 ---- */
.correction-block {
  margin-top: 12px;
  border-top: 1px dashed #E0E0E0;
  padding-top: 10px;
}
.correction-actions {
  margin-bottom: 6px;
}
.correction-gen {
  border-color: #1565C0;
  color: #1565C0;
}
.correction-gen:disabled {
  opacity: 0.6;
}
.correction-files {
  margin-top: 8px;
}
.correction-files-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.cfh-title {
  font-size: 12px;
  font-weight: 700;
  color: #1565C0;
}
.correction-files-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.correction-file {
  border: 1px solid #E0E0E0;
  border-radius: 6px;
  overflow: hidden;
  background: #FAFAFA;
}
.correction-file-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #F1F5FB;
  border-bottom: 1px solid #E0E0E0;
}
.correction-filename {
  font-weight: 700;
  font-size: 12px;
  color: #0D47A1;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.correction-file-meta {
  font-size: 10px;
  color: #777;
  margin-left: auto;
}
.correction-download {
  font-size: 12px;
  color: #1565C0;
  text-decoration: none;
  border: 1px solid #90CAF9;
  border-radius: 4px;
  padding: 2px 8px;
}
.correction-download:hover {
  background: #E3F2FD;
}
.correction-preview {
  margin: 0;
  padding: 10px;
  max-height: 220px;
  overflow: auto;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.correction-empty {
  margin-top: 6px;
  font-size: 12px;
  color: #888;
}

/* ---- 成功/失败反馈条 ---- */
.corr-notice {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  transition: opacity 0.4s;
}
.corr-notice.ok {
  background: #E8F5E9;
  border: 1px solid #C8E6C9;
  color: #1B5E20;
}
.corr-notice.err {
  background: #FDECEA;
  border: 1px solid #F5C6CB;
  color: #B71C1C;
}
.corr-notice-ico {
  font-weight: 700;
}

/* ---- 空结果说明 ---- */
.corr-empty-reason {
  margin: 6px 0;
  padding: 7px 10px;
  background: #FFF8E1;
  border: 1px solid #FFE082;
  border-radius: 6px;
  font-size: 12px;
  color: #7A5900;
  line-height: 1.5;
}

/* ---- 注解清单 ---- */
.correction-annotations {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}
.corr-ann-title {
  font-size: 12px;
  font-weight: 700;
  color: #6B21A8;
}
.correction-annotation {
  border: 1px solid #E9D5FF;
  border-left: 3px solid #A78BFA;
  border-radius: 6px;
  padding: 7px 10px;
  background: #FBF7FF;
  font-size: 12px;
  line-height: 1.5;
}
.ca-status {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 8px;
  background: #EDE7F6;
  color: #5E35B1;
  margin-right: 6px;
}
.ca-topic {
  font-weight: 700;
  color: #333;
  margin-right: 6px;
}
.ca-action {
  font-size: 10px;
  color: #7C4DFF;
  background: #EDE7F6;
  border-radius: 4px;
  padding: 1px 6px;
}
.ca-note {
  margin: 4px 0 0;
  color: #555;
  font-size: 12px;
}

/* ---- 具体错误 ---- */
.corr-error {
  margin-top: 6px;
  padding: 7px 10px;
  background: #FDECEA;
  border: 1px solid #F5C6CB;
  border-radius: 6px;
  font-size: 12px;
  color: #B71C1C;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---- 外挂补丁清单 ---- */
.correction-patch-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}
.correction-patch {
  border: 1px solid #E0E0E0;
  border-radius: 6px;
  padding: 8px 10px;
  background: #FBFCFF;
}
.correction-patch-head {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
}
.cp-op {
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: #1565C0;
  border-radius: 4px;
  padding: 1px 6px;
}
.cp-src {
  font-size: 10px;
  color: #555;
  background: #EEEEEE;
  border-radius: 4px;
  padding: 1px 6px;
}
.cp-cid {
  font-size: 10px;
  color: #999;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.cp-line {
  font-size: 12px;
  color: #333;
  line-height: 1.5;
  margin: 2px 0;
  word-break: break-word;
}
.cp-label {
  font-weight: 700;
  color: #333;
  margin-right: 4px;
}
.cp-note {
  font-size: 11px;
  color: #555;
  background: #FAFAFA;
  border-left: 2px solid #90CAF9;
  padding: 3px 6px;
  margin-top: 4px;
  border-radius: 2px;
}
.correction-render {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 0;
  border-top: 1px dashed #E0E0E0;
}
.cr-label {
  font-size: 12px;
  font-weight: 700;
  color: #333;
  margin-right: 4px;
}
.cr-sep {
  color: #BBB;
}
.correction-merged {
  margin-top: 8px;
}
.correction-merged-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.cmh-title {
  font-size: 12px;
  font-weight: 700;
  color: #1B5E20;
}
.cmh-meta {
  font-size: 11px;
  color: #777;
}

/* 检索 */
.search-row {
  display: flex;
  gap: 8px;
}
.search-input {
  flex: 1;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FAFAFA;
  color: #000;
  font-family: inherit;
  font-size: 13px;
  padding: 10px 12px;
}
.search-input:focus {
  outline: none;
  border-color: #a1c50a;
  background: #FFF;
}
.search-btn {
  background: #000;
  color: #FFF;
  border: none;
  padding: 0 20px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
  font-family: inherit;
}
.search-btn:hover:not(:disabled) {
  opacity: 0.8;
}
.search-btn:disabled {
  background: #CCC;
  cursor: not-allowed;
}
.search-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}
.search-item {
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  background: #FAFAFA;
}
.search-src {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.search-src.background { background: #E8EAF6; color: #3F51B5; }
.search-src.story { background: #E0F7FA; color: #00838F; }
.search-text {
  font-size: 12.5px;
  flex: 1;
  line-height: 1.6;
  min-width: 200px;
}
.search-score {
  font-size: 10px;
  color: #999;
  flex-shrink: 0;
  font-family: 'JetBrains Mono', monospace;
}

/* 语义检索开关 */
.semantic-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  cursor: pointer;
  user-select: none;
}
.semantic-check {
  display: none;
}
.semantic-mark {
  width: 18px;
  height: 18px;
  border: 1px solid #CCC;
  border-radius: 4px;
  background: #FAFAFA;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #FFF;
  transition: all 0.2s;
  flex-shrink: 0;
}
.semantic-check:checked + .semantic-mark {
  background: #000;
  border-color: #000;
}
.semantic-check:checked + .semantic-mark::after {
  content: "✓";
}
.semantic-label {
  font-size: 12px;
  color: #333;
}

/* 运行控制（IPC） */
.sim-ctl {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
  background: #FAFAFA;
}
.sim-ctl-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.sim-ctl-btns {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 角色采访 */
.sim-interview {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
  background: #FAFAFA;
}
.sim-interview-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sim-interview-hint {
  font-size: 11px;
  color: #666;
  margin: 4px 0 10px;
  line-height: 1.5;
}
.sim-char-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.interview-box {
  border-top: 1px solid #EAEAEA;
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.interview-char {
  font-size: 12px;
  font-weight: 600;
  color: #000;
}
.interview-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FFF;
  color: #000;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 8px 10px;
  resize: vertical;
}
.interview-input:focus {
  outline: none;
  border-color: #a1c50a;
}
.interview-answer {
  border-left: 3px solid #000;
  background: #FFF;
  border-radius: 0 4px 4px 0;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.7;
}
.interview-answer-label {
  font-size: 10px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.interview-answer-text {
  color: #333;
  white-space: pre-wrap;
}

/* 世界报告 */
.sim-report {
  margin-top: 14px;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  overflow: hidden;
}
.sim-report-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  background: #F5F5F5;
  border-bottom: 1px solid #EAEAEA;
}
.sim-report-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #333;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.sim-report-sub {
  font-size: 10px;
  color: #999;
  text-transform: none;
  letter-spacing: normal;
}
.report-body {
  padding: 12px;
  max-height: 420px;
  overflow-y: auto;
}
.report-block {
  margin-bottom: 8px;
}
.report-h2 {
  font-size: 14px;
  font-weight: 700;
  color: #000;
  margin: 14px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #F0F0F0;
}
.report-h2:first-child {
  margin-top: 0;
}
.report-li {
  font-size: 12.5px;
  line-height: 1.7;
  color: #333;
  padding-left: 4px;
}
.report-p {
  font-size: 12.5px;
  line-height: 1.7;
  color: #333;
}

/* 历史记录增强 */
.sim-history-flag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  background: #E8EAF6;
  color: #3F51B5;
}
.sim-history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 按钮变体 */
.mini-btn.danger {
  background: #FFEBEE;
  color: #C62828;
  border-color: #FFCDD2;
}
.mini-btn.danger:hover:not(:disabled) {
  border-color: #C62828;
  background: #FFF;
}
.mini-btn.ghost {
  background: #E8F5E9;
  color: #2E7D32;
  border-color: #C8E6C9;
}
.mini-btn.ghost:hover:not(:disabled) {
  border-color: #2E7D32;
  background: #FFF;
}
.spinner-xs {
  width: 10px;
  height: 10px;
  border: 2px solid rgba(0,0,0,0.2);
  border-top-color: #FFF;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
  display: inline-block;
  vertical-align: middle;
}

/* what-if 推演 */
.whatif-box {
  margin-top: 10px;
  border: 1px solid #E8EAF6;
  border-radius: 4px;
  padding: 12px;
  background: #F5F7FF;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.whatif-title {
  font-size: 12px;
  font-weight: 600;
  color: #3F51B5;
}
.whatif-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #D0D7F4;
  border-radius: 4px;
  background: #FFF;
  color: #000;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 8px 10px;
}
.whatif-input:focus {
  outline: none;
  border-color: #3F51B5;
}
.whatif-btns {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.whatif-result {
  margin-top: 10px;
  border: 1px solid #E8EAF6;
  border-radius: 4px;
  padding: 12px;
  background: #F5F7FF;
}
.whatif-result-title {
  font-size: 12px;
  font-weight: 600;
  color: #3F51B5;
  margin-bottom: 8px;
}

/* ==================== 世界图谱 ==================== */
.graph-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.graph-progress {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
}
.graph-progress-bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: #F0F0F0;
  overflow: hidden;
}
.graph-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: #a1c50a;
  transition: width 0.3s ease;
}
.graph-progress-text {
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 240px;
}
.graph-viz-wrap {
  border: 1px solid #E8E8E8;
  border-radius: 6px;
  background: #FBFBFB;
  padding: 10px;
  position: relative;
}
.graph-svg {
  width: 100%;
  height: auto;
  display: block;
  cursor: grab;
}
.graph-edge {
  stroke: #D0D0D0;
  stroke-width: 1;
}
.graph-node {
  stroke: #FFF;
  stroke-width: 1.5;
  cursor: pointer;
  opacity: 0.92;
  transition: opacity 0.15s;
}
.graph-node:hover {
  opacity: 1;
}
.graph-node.selected {
  stroke: #a1c50a;
  stroke-width: 2.5;
}
.graph-node-label {
  font-size: 10px;
  fill: #333;
  font-family: 'JetBrains Mono', monospace;
  pointer-events: none;
}
.graph-node-info {
  margin-top: 10px;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  background: #FFF;
  padding: 12px;
}
.graph-node-info-name {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 2px;
}
.graph-node-info-type {
  font-size: 11px;
  color: #a1c50a;
  font-weight: 600;
  margin-bottom: 6px;
}
.graph-node-info-summary {
  font-size: 12px;
  line-height: 1.7;
  color: #444;
  margin-bottom: 6px;
}
.graph-node-info-attrs {
  border-top: 1px dashed #EEE;
  padding-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.attr-row {
  display: flex;
  gap: 8px;
  font-size: 11.5px;
}
.attr-k {
  color: #999;
  min-width: 90px;
  font-family: 'JetBrains Mono', monospace;
}
.attr-v {
  color: #333;
  word-break: break-all;
}

/* 内置项目助手 */
.guide-modal {
  width: 520px;
  max-width: 92vw;
}
.event-detail-modal {
  width: 560px;
  max-width: 94vw;
}
.event-detail-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.event-detail-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
}
.ed-label {
  flex-shrink: 0;
  min-width: 60px;
  font-weight: 700;
  color: #666;
}
.guide-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.guide-steps {
  margin: 0;
  padding-left: 20px;
  line-height: 2;
  font-size: 13px;
  color: #333;
}
.assistant-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9000;
}
.assistant-modal {
  background: #FFF;
  width: 560px;
  max-width: 92vw;
  max-height: 80vh;
  overflow-y: auto;
  border-radius: 8px;
  padding: 16px 18px;
}
.assistant-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.assistant-title {
  font-size: 14px;
  font-weight: 700;
}
.assistant-close {
  border: none;
  background: none;
  font-size: 20px;
  color: #999;
  cursor: pointer;
}
.assistant-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.assistant-hint {
  font-size: 12px;
  color: #666;
  line-height: 1.6;
}
.assistant-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.assistant-quick .mini-btn {
  font-size: 11px;
  padding: 5px 10px;
}
.assistant-running {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #a1c50a;
}
.assistant-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #E0E0E0;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  resize: vertical;
  font-family: inherit;
  color: #000;
}
.assistant-actions {
  display: flex;
  gap: 8px;
}
.assistant-answer {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  color: #111;
  background: #F9FAFB;
  border: 1px solid #EAEAEA;
  border-radius: 4px;
  padding: 10px 12px;
}
.agent-tasks {
  border: 1px solid #EAEAEA;
  border-radius: 6px;
  padding: 8px 10px;
  background: #FCFCFC;
}
.agent-tasks-title {
  font-size: 11px;
  font-weight: 700;
  color: #666;
  margin-bottom: 6px;
  text-transform: uppercase;
}
.agent-tasks-list {
  max-height: 160px;
  overflow-y: auto;
}
.agent-task-item {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
  padding: 3px 0;
  border-bottom: 1px solid #F5F5F5;
}
.agent-task-action {
  font-weight: 600;
  color: #10203a;
}
.agent-task-status {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  text-transform: uppercase;
}
.agent-task-status.completed { background: #E8F5E9; color: #2E7D32; }
.agent-task-status.failed { background: #FFEBEE; color: #C62828; }
.agent-task-status.running { background: #f3f7e6; color: #5f7008; }
.agent-task-time {
  color: #999;
  font-family: 'JetBrains Mono', monospace;
  margin-left: auto;
}
.agent-tools {
  border: 1px solid #EAEAEA;
  border-radius: 6px;
  padding: 8px 10px;
  background: #FCFCFC;
}
.agent-tools summary {
  font-size: 11px;
  font-weight: 700;
  color: #666;
  cursor: pointer;
  text-transform: uppercase;
}
.agent-tools-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 8px;
  margin-top: 6px;
  max-height: 160px;
  overflow-y: auto;
}
.agent-tool-item {
  display: flex;
  flex-direction: column;
  font-size: 11px;
  padding: 3px 0;
  border-bottom: 1px solid #F5F5F5;
}
.agent-tool-name {
  font-weight: 700;
  color: #10203a;
  font-family: 'JetBrains Mono', monospace;
}
.agent-tool-desc {
  color: #888;
}

/* 世界线对比 */
.sim-compare-check {
  width: 16px;
  height: 16px;
  accent-color: #a1c50a;
}
.compare-modal {
  width: 860px;
  max-width: 94vw;
}
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  max-height: 60vh;
  overflow-y: auto;
}
.compare-col {
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  padding: 12px;
  background: #FBFBFB;
}
.compare-col-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.compare-events {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.compare-step {
  border: 1px solid #F0F0F0;
  border-radius: 6px;
  overflow: hidden;
}
.compare-step-head {
  padding: 5px 8px;
  background: #FAFAFA;
  font-size: 11px;
  font-weight: 700;
  color: #a1c50a;
  border-bottom: 1px solid #F0F0F0;
}
@media (max-width: 720px) {
  .compare-grid { grid-template-columns: 1fr; }
}

/* ================= 手机端响应式 ================= */
@media (max-width: 768px) {
  /* 顶栏：按钮过多，压缩间距并允许高度自适应换行 */
  .app-header {
    height: auto;
    min-height: 56px;
    flex-wrap: wrap;
    padding: 10px 14px;
    gap: 8px;
  }
  .header-left { gap: 10px; }
  .header-right { gap: 8px; flex-wrap: wrap; }
  .back-btn { padding: 7px 10px; font-size: 11px; }
  .project-id { font-size: 10px; max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .brand { font-size: 15px; }
  .step-name { font-size: 13px; }
  .world-body { padding: 16px; }
  .step-card { padding: 16px; }
  .sim-controls { flex-direction: column; align-items: stretch; }
  .sim-field-wide { flex-basis: auto; }
  .sim-start { flex: none; width: 100%; }
  .world-step-nav { flex-wrap: wrap; padding: 8px 12px; }
  .world-search { margin-left: 0; min-width: 100%; }
  .sim-event { grid-template-columns: 1fr; gap: 2px; }
  .tree-node-row { gap: 6px; }
  .sim-playback { flex-wrap: wrap; }
  .sim-history-item { flex-wrap: wrap; }
}
@media (max-width: 480px) {
  /* 顶栏第二行：project-id / 导出 / 导入 / 助手 / 返回 在很窄时折行 */
  .app-header { gap: 6px; }
  .header-left .step-divider,
  .header-left .workflow-step .step-num { display: none; }
  .workflow-step { gap: 4px; }
  /* 卡片内边距与按钮单列 */
  .step-card { padding: 14px 12px; border-radius: 10px; }
  .card-header { flex-direction: column; align-items: flex-start; gap: 8px; }
  .input-grid { gap: 12px; }
  .btn-row { flex-direction: column; }
  .btn-row .action-btn { flex: none; width: 100%; }
  .world-body { gap: 14px; }
  /* 冲突项：确认/建议左右对比改为上下堆叠 */
  .conflict-item { padding: 12px; }
  .conflict-compare { margin-top: 8px; }
  .conflict-actions { flex-wrap: wrap; }
  .mini-btn { flex: 1; min-width: 72px; }
  .search-row { flex-direction: column; }
  .search-row .search-btn { padding: 10px; width: 100%; }
  /* 模拟：字段标签与控件更贴合，事件行允许换行 */
  .sim-label { font-size: 10px; }
  .sim-input { width: 100%; }
  .sim-events { overflow-x: auto; }
  /* 图论 SVG 自适应宽度 + 信息卡 */
  .graph-viz-wrap { overflow-x: auto; }
  .graph-svg { height: auto; }
  .graph-node-info { padding: 10px; }
  /* 助手弹窗接近全屏 */
  .assistant-modal {
    width: 100%;
    max-width: 100vw;
    max-height: 94vh;
    border-radius: 0;
    padding: 14px 12px;
  }
  .assistant-actions { flex-direction: column; }
  .assistant-actions .action-btn { width: 100%; }
}
@media (max-width: 360px) {
  .back-btn { font-size: 10px; padding: 6px 8px; }
  .header-right { gap: 6px; }
}

</style>
