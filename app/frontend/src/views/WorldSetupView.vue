<template>
  <div class="world-view">
    <!-- 顶部导航（与主界面一致） -->
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="goBack">MIROFISH</div>
        <div class="step-divider"></div>
        <div class="workflow-step">
          <span class="step-num">WORLD</span>
          <span class="step-name">{{ $t('world.headerTitle') }}</span>
        </div>
      </div>
      <div class="header-right">
        <span class="project-id">{{ projectId }}</span>
        <button class="back-btn" :disabled="snapshotBusy" @click="exportSnapshot">{{ $t('world.exportSnapshot') }}</button>
        <button class="back-btn" :disabled="snapshotBusy" @click="importFileInput.click()">{{ $t('world.importSnapshot') }}</button>
        <input ref="importFileInput" type="file" accept=".json,.mirofish.json,application/json" style="display:none" @change="onImportSnapshot" />
        <button class="back-btn" @click="assistantOpen = true">{{ $t('assistant.open') }}</button>
        <button class="back-btn" @click="goBack">← {{ $t('world.backProject') }}</button>
      </div>
    </header>

    <div class="world-body">
      <!-- 加载失败提示 + 重试（设定库读取失败时不至于页面空白无解释） -->
      <div v-if="loadError" class="load-error-bar">
        <span>⚠ {{ loadError }}</span>
        <button class="action-btn" @click="retryLoad">{{ $t('world.retry') }}</button>
      </div>

      <!-- 输入区 -->
      <div class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">01</span>
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
                accept=".txt,.md,.markdown,.pdf"
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
                accept=".txt,.md,.markdown,.pdf"
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
      <div v-if="report" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">02</span>
            <span class="step-title">{{ $t('world.conflictTitle') }}</span>
          </div>
          <div class="step-status">
            <span v-if="report.conflicts.length" class="badge processing">
              {{ $t('world.conflictCount', { count: report.conflicts.length }) }}
            </span>
            <span v-else class="badge success">{{ $t('world.noConflict') }}</span>
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
          <div v-for="c in report.conflicts" :key="c.conflict_id" class="conflict-item" :class="'sev-' + c.severity">
            <div class="conflict-head">
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
                class="mini-btn"
                :class="{ active: c.status === 'justified' }"
                :disabled="justifyingId === c.conflict_id"
                @click="toggleJustify(c)"
              >
                {{ c.justifyOpen ? $t('world.justifyCancel') : $t('world.justifyConflict') }}
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
          </div>
        </div>
      </div>

      <!-- 世界模拟（独立模式） -->
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">03</span>
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
          <button class="action-btn sim-start" :disabled="simStarting || simStatus === 'running'" @click="handleStartSim">
            <span v-if="simStarting" class="spinner-sm"></span>
            {{ simStarting ? $t('world.simStarting') : simStatus === 'running' ? $t('world.simRunning') : $t('world.simStartBtn') }}
          </button>
        </div>

        <div v-if="simMsg" class="msg-line" :class="{ error: simMsgError }">{{ simMsg }}</div>

        <!-- 事件流 -->
        <div v-if="simEvents.length" class="sim-events">
          <div class="sim-events-title">{{ $t('world.eventStream') }}</div>
          <div v-for="(e, i) in simEvents" :key="i" class="sim-event">
            <span class="sim-event-time">{{ e.time }}</span>
            <span class="sim-event-who">{{ e.character_name }}</span>
            <span class="sim-event-where">{{ e.location }}</span>
            <span class="sim-event-what">{{ e.action_desc }}</span>
            <span class="sim-event-result">{{ e.result }}</span>
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
        <div v-if="characters.length" class="sim-interview">
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

        <!-- 世界报告 -->
        <div v-if="reportSimulationId" class="sim-report">
          <div class="sim-report-head">
            <div class="sim-report-title">
              <span>{{ $t('world.reportTitle') }}</span>
              <span v-if="reportSimulationLabel" class="sim-report-sub">{{ reportSimulationLabel }}</span>
            </div>
            <button
              class="mini-btn"
              :disabled="reportGenerating"
              @click="handleGenerateReport"
            >
              <span v-if="reportGenerating" class="spinner-xs"></span>
              {{ reportGenerating ? $t('world.reportGenerating') : reportText ? $t('world.reportRegenerate') : $t('world.reportGenerate') }}
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

        <div v-if="simHistory.length" class="sim-history">
          <div class="sim-history-title">{{ $t('world.reportHistoryTitle') }}</div>
          <div v-for="(h, i) in simHistory" :key="i" class="sim-history-item">
            <span class="sim-history-time">{{ formatTime(h.created_at) }}</span>
            <span class="sim-history-status" :class="h.status">{{ statusLabel(h.status) }}</span>
            <span class="sim-history-count">{{ $t('world.eventCount', { count: (h.result || {}).event_count || 0 }) }}</span>
            <span v-if="(h.result || {}).meta && (h.result || {}).meta.whatif_question" class="sim-history-flag">{{ $t('world.whatifFlag') }}</span>
            <template v-if="h.status === 'completed' && !((h.result || {}).meta || {}).whatif_question">
              <button class="mini-btn" :disabled="whatIfing === h.simulation_id" @click="startWhatIf(h)">
                <span v-if="whatIfing === h.simulation_id" class="spinner-xs"></span>
                {{ $t('world.whatifBtn') }}
              </button>
              <button class="mini-btn ghost" @click="openChartRecord(h)">{{ $t('world.chronicleBtn') }}</button>
            </template>
          </div>
          <!-- 当前模拟的 what-if 推演对话框 -->
          <div v-if="whatIfBaseId" class="whatif-box">
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
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">04</span>
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
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">05</span>
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
      <div v-if="stats" class="step-card">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">06</span>
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
            <div v-if="assistantAnswer" class="assistant-answer">{{ assistantAnswer }}</div>
            <div v-if="assistantMsg" class="msg-line" :class="{ error: assistantMsgError }">{{ assistantMsg }}</div>
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
  updateConflictStatus,
  searchWorld,
  startWorldSimulation,
  listWorldSimulations,
  getWorldSimulation,
  controlWorldSimulation,
  simulateWorldWhatIf,
  generateWorldReport,
  getWorldReport,
  buildWorldGraph,
  getWorldGraph,
  refillWorldGraphEdges
} from '../api/world'
import { getTaskStatus, exportProjectSnapshot, importProjectSnapshot } from '../api/graph'
import { askAssistant } from '../api/assistant'
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

const background = ref('')
const story = ref('')
const saving = ref(false)
const detecting = ref(false)
const saveMsg = ref('')
const saveMsgError = ref(false)
const loadError = ref('')
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
const simGoal = ref('')  // 任务目标（可选，决定推演走向）
const simStarting = ref(false)
const simStatus = ref('idle')
const simMsg = ref('')
const simMsgError = ref(false)
const simEvents = ref([])
const simHistory = ref([])
let simPollTimer = null
let simPollingId = ''
let whatIfPollTimer = null

// 世界图谱状态
const GV_W = 780
const GV_H = 420
const graphInfo = ref(null)          // { nodes, edges, node_count, edge_count }
const graphPos = ref({})             // uuid -> {x, y}（力导向布局结果）
const graphBuilding = ref(false)
const graphProgressMsg = ref('')
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
        graphMsg.value = task.message || (status === 'completed' ? t('world.msgGraphBuilt') : t('world.msgGraphBuildFailed'))
        graphMsgError.value = !(status === 'completed' || status === 'COMPLETED')
        await fetchGraph()
      } else {
        graphProgressMsg.value = task.message || t('world.msgGraphBuilding')
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
  try {
    const res = await buildWorldGraph(projectId, {
      goal: simGoal.value.trim() || undefined,
      force: !!graphInfo.value
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
    a.download = `${projectId}.mirofish.json`
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
  } catch (e) {
    console.error('更新冲突状态失败', e)
  }
}

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
    conflict.status = 'justified'
    conflict.resolution_note = note
    conflict.justifyOpen = false
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
      simPollingId = latest.simulation_id
      loadCharacters(latest.simulation_id)
      startSimPolling(latest.simulation_id)
    } else if (latest && latest.status === 'completed') {
      simStatus.value = 'completed'
      simEvents.value = (latest.result || {}).events || []
      loadCharacters(latest.simulation_id)
    }
  } catch (e) {
    console.error('加载模拟历史失败', e)
  }
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
      if (sim.status === 'completed') {
        clearInterval(simPollTimer)
        simPollTimer = null
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
    simMsg.value = (e.message || t('world.msgSimStartFailed')) + t('world.checkModelConfig')
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

// ---------------- 世界报告 ----------------

async function openChartRecord(sim) {
  // sim 可能是 dict 或 {simulation_id, created_at}
  const simId = typeof sim === 'object' ? (sim.simulation_id || sim['simulation_id']) : sim
  if (!simId) return
  reportSimulationId.value = simId
  reportText.value = ''
  reportEmptyNote.value = ''
  const time = (sim.created_at || '').replace('T', ' ').slice(0, 16)
  reportSimulationLabel.value = time ? `（${time}）` : ''
  // 先尝试读取已生成报告
  try {
    const res = await getWorldReport(projectId, simId)
    if (res.report && res.report.text) {
      reportText.value = res.report.text
      return
    }
  } catch (e) {
    // 报告不存在，保持生成按钮
  }
}

async function handleGenerateReport() {
  if (!reportSimulationId.value) return
  reportGenerating.value = true
  reportText.value = ''
  reportEmptyNote.value = ''
  try {
    const res = await generateWorldReport(projectId, reportSimulationId.value)
    if (res.report && res.report.text) {
      reportText.value = res.report.text
    } else {
      reportEmptyNote.value = t('world.msgReportEmpty')
    }
  } catch (e) {
    reportEmptyNote.value = e.message || t('world.msgReportFailed')
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
})

onUnmounted(() => {
  // 离开页面立即停止所有轮询，避免计时器泄漏与后台请求堆积
  if (graphPollTimer) { clearInterval(graphPollTimer); graphPollTimer = null }
  if (refillPollTimerId) { clearInterval(refillPollTimerId); refillPollTimerId = null }
  if (simPollTimer) { clearInterval(simPollTimer); simPollTimer = null }
  if (whatIfPollTimer) { clearInterval(whatIfPollTimer); whatIfPollTimer = null }
})
</script>

<style scoped>
/* 与主界面一致的视觉规范 */
.world-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #000;
}

/* Header（与 MainView 一致） */
.app-header {
  height: 60px;
  border-bottom: 1px solid #EAEAEA;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #FFF;
  z-index: 100;
  position: relative;
  flex-shrink: 0;
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

/* Body */
.world-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1000px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}
.load-error-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-left: 3px solid #D32F2F;
  background: #FFF0EF;
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

/* 卡片（与 Step1 的 step-card 一致） */
.step-card {
  background: #FFF;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  border: 1px solid #EAEAEA;
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
.badge.processing { background: #FF5722; color: #FFF; }
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
  border-color: #FF5722;
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
  border-color: #FF5722;
}
.drop-zone.drag-over {
  border-color: #FF5722;
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
  border-color: #FF5722;
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
  border-color: #FF5722;
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
  grid-template-columns: 74px 72px 90px 1fr;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #F0F0F0;
  font-size: 12px;
  align-items: start;
}
.sim-event:last-child {
  border-bottom: none;
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
.sim-history-status.running { background: #FFF3E0; color: #E65100; }
.sim-history-status.preparing { background: #FFF3E0; color: #E65100; }
.sim-history-status.created { background: #F5F5F5; color: #666; }
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
.severity-tag.sev-medium { background: #FFF3E0; color: #E65100; }
.severity-tag.sev-low { background: #E8F5E9; color: #2E7D32; }
.conflict-topic {
  font-weight: 600;
  font-size: 13px;
  flex: 1;
}
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
  border-color: #FF5722;
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
  border-color: #FF5722;
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
  stroke: #FF5722;
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
  color: #FF5722;
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
</style>
