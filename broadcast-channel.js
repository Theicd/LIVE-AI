/**
 * TV broadcast UI — display-only mode: simulates slow HTML "typing" from archive files.
 */
(function () {
	'use strict';

	const CONFIG = Object.assign({
		displayOnly: true,
		apiListCreations: '/api/list_creations',
		apiStats: '/api/stats',
		apiLive: '/api/live',
		archivePrefix: 'archive/',
		model: 'ARCHIVE SIMULATION',
		statsIntervalMs: 1500,
		archiveRefreshMs: 30000,
		charsPerSecond: 2,
		typingTickMs: 100,
		fileCooldownMs: 60000,
		liveSegmentMs: 10000,
		archiveSegmentMs: 40000,
		archiveSlots: 2,
		comingUpMs: 1600,
		eventToastMs: 12000,
		toastVisibleMs: 9000,
		promoIntervalMs: 180000,
		promoShowMs: 8000,
		sfxEnabled: true,
		sfxVolume: 1,
		countdownUrgentMs: 5000,
		promptRevealMs: 5000,
		staticMode: null,
		basePath: null,
		archiveManifest: 'archive/manifest.json'
	}, window.BROADCAST_CONFIG || {});

	function appBase() {
		if (CONFIG.basePath != null && CONFIG.basePath !== '') {
			const b = String(CONFIG.basePath);
			return b.endsWith('/') ? b : `${b}/`;
		}
		const path = location.pathname || '/';
		if (/broadcast\.html$/i.test(path)) {
			return path.replace(/broadcast\.html.*$/i, '');
		}
		if (path.endsWith('/')) return path;
		return '/';
	}

	function assetUrl(relPath) {
		return appBase() + String(relPath || '').replace(/^\//, '');
	}

	function useStaticArchive() {
		if (CONFIG.staticMode === true) return true;
		if (CONFIG.staticMode === false) return false;
		const h = location.hostname;
		return h !== 'localhost' && h !== '127.0.0.1';
	}

	const PROMO_LINES = [
		'AMBIENT 3D BACKGROUNDS',
		'JAZZ VISUAL CHANNEL',
		'LOCAL RTX 3050 CREATIONS',
		'ARCHIVE PLAYBACK MODE',
		'100% ON-DEVICE LIBRARY'
	];

	const EVENT_POOL = [
		'LOADING CREATION FROM ARCHIVE',
		'SIMULATING LIVE CODE STREAM',
		'ROTATING ARCHIVE LIBRARY',
		'PREPARING NEXT SHOWCASE',
		'100% LOCAL INFERENCE',
		'NO CLOUD SERVICES USED'
	];

	const TICKER_PHRASES = [
		'ARCHIVE LIBRARY PLAYBACK',
		'EXTERNAL PIPELINE FEEDS NEW HTML',
		'100% LOCAL INFERENCE',
		'AI LIVE CHANNEL — DISPLAY MODE'
	];

	const state = {
		cycle: 0,
		creations: [],
		usingModel: CONFIG.model,
		rotationIndex: 0,
		transitioning: false,
		archiveLoading: false,
		logFeed: [],
		bootAt: Date.now(),
		charsSession: 0,
		segmentEndAt: Date.now() + CONFIG.liveSegmentMs,
		segmentLabel: 'ARCHIVE IN',
		broadcastPhase: 'live',
		promoIndex: 0,
		eventPoolIndex: 0,
		lastSavedSeen: '',
		simFileIndex: 0,
		simPos: 0,
		simSource: '',
		simStartedAt: 0,
		simTickTimer: null,
		simGenerating: false,
		simCharCarry: 0,
		simCooldownUntil: 0,
		sfxReady: false,
		lastCountdownSecPlayed: 0
	};

	const ui = {
		modelName: document.getElementById('modelName'),
		strapLine: document.getElementById('strapLine'),
		onAir: document.getElementById('onAir'),
		onAirText: document.getElementById('onAirText'),
		clock: document.getElementById('clock'),
		topTrack: document.getElementById('topTrack'),
		gpuName: document.getElementById('gpuName'),
		gpuPct: document.getElementById('gpuPct'),
		gpuBar: document.getElementById('gpuBar'),
		gpuMini: document.getElementById('gpuMini'),
		streamHint: document.getElementById('streamHint'),
		streamOutput: document.getElementById('streamOutput'),
		lowerTrack: document.getElementById('lowerTrack'),
		archiveCount: document.getElementById('archiveCount'),
		rightTag: document.getElementById('rightTag'),
		overlay: document.getElementById('overlay'),
		overlayFrame: document.getElementById('overlayFrame'),
		overlayTitle: document.getElementById('overlayTitle'),
		closeOverlay: document.getElementById('closeOverlay'),
		tvwipe: document.getElementById('tvwipe'),
		tvwipeKicker: document.getElementById('tvwipeKicker'),
		tvwipeTitle: document.getElementById('tvwipeTitle'),
		tvwipeSub: document.getElementById('tvwipeSub'),
		tvwipeCountLabel: document.getElementById('tvwipeCountLabel'),
		tvwipeCountTime: document.getElementById('tvwipeCountTime'),
		heroCreations: document.getElementById('heroCreations'),
		heroUptime: document.getElementById('heroUptime'),
		liveBadge: document.getElementById('liveBadge'),
		statusPunch: document.getElementById('statusPunch'),
		heroCountdown: document.getElementById('heroCountdown'),
		countdownLabel: document.getElementById('countdownLabel'),
		countdownTime: document.getElementById('countdownTime'),
		tvwipeCountdown: document.getElementById('tvwipeCountdown'),
		audioPrime: document.getElementById('audioPrime'),
		toastStack: document.getElementById('toastStack'),
		promo: document.getElementById('promo'),
		promoLine: document.getElementById('promoLine'),
		overlayCountdown: document.getElementById('overlayCountdown'),
		overlayCountdownLabel: document.getElementById('overlayCountdownLabel'),
		overlayCountdownTime: document.getElementById('overlayCountdownTime'),
		overlayPrompt: document.getElementById('overlayPrompt'),
		overlayPromptText: document.getElementById('overlayPromptText'),
		engineStatus: document.getElementById('engineStatus'),
		cycleStatus: document.getElementById('cycleStatus'),
		charsStatus: document.getElementById('charsStatus'),
		timeStatus: document.getElementById('timeStatus'),
		modeNowText: document.getElementById('modeNowText'),
		modeDesc: document.getElementById('modeDesc')
	};

	const ARCHIVE_ROTATION_KEY = 'aiLiveArchiveRotation';
	const SIM_STATE_KEY = 'aiLiveSimStreamState';
	const SIM_STATE_VERSION = 1;
	const wait = ms => new Promise(r => setTimeout(r, ms));
	let lastSimPersistAt = 0;
	let overlayPromptTimer = null;
	let firstLiveSegment = true;
	let sfxPrimeTimer = null;
	const wavCache = new Map();

	function makeWavBlob(freq, durSec, vol, noise) {
		const sampleRate = 22050;
		const n = Math.max(1, Math.floor(sampleRate * durSec));
		const attack = Math.max(1, Math.floor(sampleRate * 0.006));
		const release = Math.max(1, Math.floor(sampleRate * 0.04));
		const pcm = new Int16Array(n);
		for (let i = 0; i < n; i++) {
			let env = 1;
			if (i < attack) env = i / attack;
			else if (i > n - release) env = Math.max(0, (n - i) / release);
			const t = i / sampleRate;
			const s = noise
				? (Math.random() * 2 - 1) * vol * env
				: Math.sin(2 * Math.PI * freq * t) * vol * env;
			pcm[i] = Math.max(-32767, Math.min(32767, Math.floor(s * 32767)));
		}
		const header = new ArrayBuffer(44);
		const v = new DataView(header);
		const w = (o, s) => { for (let j = 0; j < s.length; j++) v.setUint8(o + j, s.charCodeAt(j)); };
		w(0, 'RIFF');
		v.setUint32(4, 36 + n * 2, true);
		w(8, 'WAVE');
		w(12, 'fmt ');
		v.setUint32(16, 16, true);
		v.setUint16(20, 1, true);
		v.setUint16(22, 1, true);
		v.setUint32(24, sampleRate, true);
		v.setUint32(28, sampleRate * 2, true);
		v.setUint16(32, 2, true);
		v.setUint16(34, 16, true);
		w(36, 'data');
		v.setUint32(40, n * 2, true);
		return new Blob([header, pcm], { type: 'audio/wav' });
	}

	function sfxBeepUrl(freq, durSec, vol, noise) {
		const key = `${freq}|${durSec}|${vol}|${noise ? 1 : 0}`;
		if (wavCache.has(key)) return wavCache.get(key);
		const url = URL.createObjectURL(makeWavBlob(freq, durSec, vol, !!noise));
		wavCache.set(key, url);
		return url;
	}

	function silentPrimeUrl() {
		if (wavCache.has('__prime__')) return wavCache.get('__prime__');
		const url = URL.createObjectURL(makeWavBlob(60, 1.2, 0.02, false));
		wavCache.set('__prime__', url);
		return url;
	}

	function playSfx(freq, durSec, vol, delaySec, noise) {
		if (!CONFIG.sfxEnabled) return;
		const fire = () => {
			const a = new Audio(sfxBeepUrl(freq, durSec, vol, !!noise));
			a.volume = Math.min(1, CONFIG.sfxVolume ?? 1);
			const attempt = () => {
				a.play().then(() => { state.sfxReady = true; }).catch(() => {
					primeHtmlAudio();
					setTimeout(() => a.play().catch(() => {}), 120);
				});
			};
			attempt();
		};
		if (delaySec > 0) setTimeout(fire, delaySec * 1000);
		else fire();
	}

	function primeHtmlAudio() {
		let el = ui.audioPrime;
		if (!el) {
			el = document.createElement('audio');
			el.id = 'audioPrime';
			el.setAttribute('playsinline', '');
			el.setAttribute('preload', 'auto');
			el.loop = true;
			el.src = silentPrimeUrl();
			el.style.cssText = 'position:fixed;width:0;height:0;opacity:0;pointer-events:none';
			document.body.appendChild(el);
			ui.audioPrime = el;
		}
		el.muted = true;
		el.volume = 1;
		const p = el.play();
		if (p && typeof p.then === 'function') {
			p.then(() => {
				el.muted = false;
				state.sfxReady = true;
			}).catch(() => {});
		}
	}

	function startAutoAudio() {
		if (ui.audioPrime && !ui.audioPrime._bound) {
			ui.audioPrime._bound = true;
			ui.audioPrime.addEventListener('playing', () => { state.sfxReady = true; });
		}
		primeHtmlAudio();
		setTimeout(() => playSfx(523, 0.1, 0.5), 400);
		setTimeout(() => playSfx(659, 0.12, 0.45), 900);
		if (sfxPrimeTimer) return;
		sfxPrimeTimer = setInterval(() => {
			if (!state.sfxReady) primeHtmlAudio();
		}, 1200);
	}

	function playTone(freq, dur, peak, type, delay) {
		void type;
		playSfx(freq, dur, peak, delay || 0, false);
	}

	function playNoiseBurst(dur, peak, delay) {
		playSfx(200, dur, peak, delay || 0, true);
	}

	function playCountdownBeep(secLeft) {
		const freqs = { 5: 523, 4: 587, 3: 659, 2: 784, 1: 988 };
		const freq = freqs[secLeft] || 440;
		const dur = secLeft === 1 ? 0.38 : 0.14;
		const peak = secLeft === 1 ? 0.65 : 0.5;
		playSfx(freq, dur, peak, 0, false);
		if (secLeft === 1) {
			playSfx(1318, 0.22, 0.5, 0.14, false);
			playSfx(196, 0.45, 0.4, 0.08, false);
		}
	}

	function playSting(kind) {
		if (kind === 'save') {
			playSfx(659, 0.18, 0.5);
			playSfx(988, 0.28, 0.45, 0.1);
		} else if (kind === 'transition') {
			playNoiseBurst(0.22, 0.45);
			playSfx(196, 0.45, 0.55);
			playSfx(392, 0.35, 0.5, 0.08);
			playSfx(784, 0.25, 0.45, 0.18);
		} else if (kind === 'archive') {
			playSfx(147, 0.5, 0.5);
			playSfx(294, 0.35, 0.45, 0.12);
			playNoiseBurst(0.15, 0.35, 0.05);
		} else if (kind === 'live') {
			playSfx(330, 0.2, 0.5);
			playSfx(440, 0.2, 0.5, 0.1);
			playSfx(554, 0.28, 0.55, 0.2);
			playSfx(880, 0.35, 0.45, 0.32);
		} else if (kind === 'tick') {
			playSfx(880, 0.1, 0.55);
		} else {
			playSfx(440, 0.15, 0.45);
		}
	}

	function escapeHtml(s) {
		return String(s).replace(/[<&>]/g, m => ({ '<': '&lt;', '&': '&amp;', '>': '&gt;' }[m]));
	}

	function promptTopic(p) {
		if (!p) return 'ARCHIVE CREATION';
		const m = p.match(/Create (?:a |an )?(.{0,48})/i);
		return (m ? m[1] : p).trim().toUpperCase();
	}

	function formatCountdown(ms) {
		const s = Math.max(0, Math.ceil(ms / 1000));
		const m = Math.floor(s / 60);
		const r = s % 60;
		return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
	}

	function syncCountdownDisplays() {
		const left = state.segmentEndAt - Date.now();
		const timeStr = formatCountdown(left);
		const label = state.segmentLabel || 'NEXT IN';
		if (ui.countdownLabel) ui.countdownLabel.textContent = label;
		if (ui.countdownTime) ui.countdownTime.textContent = timeStr;
		if (ui.overlayCountdownLabel) ui.overlayCountdownLabel.textContent = label;
		if (ui.overlayCountdownTime) ui.overlayCountdownTime.textContent = timeStr;
		if (ui.tvwipeCountLabel) ui.tvwipeCountLabel.textContent = label;
		if (ui.tvwipeCountTime) ui.tvwipeCountTime.textContent = timeStr;
		const urgentMs = CONFIG.countdownUrgentMs || 5000;
		const urgent = left > 0 && left <= urgentMs;
		for (const el of [ui.heroCountdown, ui.overlayCountdown, ui.tvwipeCountdown]) {
			if (el) el.classList.toggle('urgent', urgent);
		}
		document.body.classList.toggle('segment-urgent', urgent);
	}

	function setSegmentEnd(at, label) {
		state.segmentEndAt = at;
		if (label) state.segmentLabel = label;
		state.lastCountdownSecPlayed = 0;
		syncCountdownDisplays();
	}

	function tickCountdown() {
		const left = state.segmentEndAt - Date.now();
		syncCountdownDisplays();
		const secLeft = Math.ceil(left / 1000);
		const urgentMs = CONFIG.countdownUrgentMs || 5000;
		if (secLeft > 0 && left <= urgentMs && secLeft <= 5 && secLeft !== state.lastCountdownSecPlayed) {
			state.lastCountdownSecPlayed = secLeft;
			playCountdownBeep(secLeft);
		} else if (secLeft > 5) {
			state.lastCountdownSecPlayed = 0;
		}
	}

	function formatUptime(ms) {
		const m = Math.floor(ms / 60000);
		if (m < 60) return `${m}m`;
		const h = Math.floor(m / 60);
		return `${h}h ${m % 60}m`;
	}

	function formatElapsed(ms) {
		const s = Math.floor(ms / 1000);
		const m = Math.floor(s / 60);
		const r = s % 60;
		if (m >= 60) {
			const h = Math.floor(m / 60);
			return `${h}h ${m % 60}m`;
		}
		return `${m}:${String(r).padStart(2, '0')}`;
	}

	function updateHeroStats() {
		if (ui.heroCreations) ui.heroCreations.textContent = String(state.creations.length);
		if (ui.heroUptime) ui.heroUptime.textContent = formatUptime(Date.now() - state.bootAt);
		if (ui.archiveCount) ui.archiveCount.textContent = `${state.creations.length} IN ARCHIVE`;
	}

	function updateEnginePanel() {
		if (ui.engineStatus) ui.engineStatus.textContent = 'ARCHIVE FEED';
		if (ui.cycleStatus) ui.cycleStatus.textContent = String(state.cycle);
		if (ui.charsStatus) ui.charsStatus.textContent = String(state.simPos);
		if (ui.timeStatus && state.simStartedAt) {
			ui.timeStatus.textContent = formatElapsed(Date.now() - state.simStartedAt);
		}
	}

	function showToast(msg, breaking = false) {
		if (!ui.toastStack) return;
		const el = document.createElement('div');
		el.className = 'toast' + (breaking ? ' breaking' : '');
		const life = CONFIG.toastVisibleMs || 9000;
		const outAt = Math.max(1200, life - 650);
		el.style.animation = `toastIn 0.55s ease, toastOut 0.65s ease ${outAt}ms forwards`;
		if (breaking) {
			const tag = document.createElement('span');
			tag.className = 'toast__tag';
			tag.textContent = 'BREAKING';
			el.appendChild(tag);
		}
		const body = document.createElement('span');
		body.className = 'toast__msg';
		body.textContent = msg;
		el.appendChild(body);
		ui.toastStack.appendChild(el);
		if (breaking) playSting('tick');
		setTimeout(() => el.remove(), life + 200);
		while (ui.toastStack.children.length > 2) ui.toastStack.firstChild.remove();
	}

	function logEntry(message) {
		const stamp = new Date().toLocaleTimeString('en-GB', { hour12: false });
		state.logFeed.unshift({ stamp, message });
		if (state.logFeed.length > 10) state.logFeed.length = 10;
		renderLowerCrawl();
	}

	function renderLowerCrawl() {
		if (!ui.lowerTrack) return;
		const events = state.logFeed.slice(0, 4).map(e =>
			`<span>${escapeHtml(e.message)} <span class="sep">\u25C6</span></span>`
		).join('');
		const chunk = events + events;
		ui.lowerTrack.innerHTML = chunk || '<span>AI LIVE CHANNEL — ARCHIVE MODE</span>';
	}

	function buildTopMarquee() {
		if (!ui.topTrack) return;
		const n = state.creations.length;
		const dyn = [
			`ARCHIVE LIBRARY — ${n} CREATIONS`,
			`SIMULATED BUILD — ${CONFIG.charsPerSecond} CHARS/SEC`,
			`UPTIME ${formatUptime(Date.now() - state.bootAt)}`,
			...TICKER_PHRASES
		];
		const html = dyn.map(t => `<span>${escapeHtml(t)}<span class="pip">\u25B6</span></span>`).join('');
		ui.topTrack.innerHTML = html + html;
	}

	function setOnAir(live) {
		if (!ui.onAir) return;
		ui.onAir.classList.toggle('live', live);
		if (ui.onAirText) ui.onAirText.textContent = live ? 'ON AIR' : 'STANDBY';
	}

	function setStatusPunch(text, mode) {
		if (!ui.statusPunch) return;
		ui.statusPunch.textContent = text;
		ui.statusPunch.classList.remove('warn', 'archive');
		if (mode) ui.statusPunch.classList.add(mode);
	}

	function formatModelDisplay(name) {
		return String(name || CONFIG.model).toUpperCase();
	}

	function setArchiveScreen(on, slotNum) {
		document.body.classList.toggle('archive-mode', !!on);
		state.broadcastPhase = on ? 'archive' : 'live';
		if (ui.rightTag) {
			ui.rightTag.textContent = on ? 'ARCHIVE \u00B7 FULL SCREEN' : 'ARCHIVE SIMULATION \u00B7 LOCAL';
		}
		if (on) {
			const pill = ui.overlay?.querySelector('.pill');
			if (pill) pill.textContent = `ARCHIVE #${slotNum || 1}`;
		}
	}

	function setLiveMode(archive, slotNum) {
		setArchiveScreen(archive, slotNum);
		if (ui.liveBadge && !archive) {
			ui.liveBadge.textContent = 'SIMULATED LIVE BUILD';
		}
	}

	function renderStream(withCursor) {
		if (!ui.streamOutput) return;
		ui.streamOutput.classList.remove('idle');
		const full = state.simSource || '';
		const pos = Math.max(0, Math.min(state.simPos, full.length));
		const shown = full.slice(0, pos);
		ui.streamOutput.textContent = shown || '// Loading archive source\u2026';
		if (withCursor && state.simGenerating) {
			const cur = document.createElement('span');
			cur.className = 'cursor';
			ui.streamOutput.appendChild(cur);
		}
		ui.streamOutput.scrollTop = ui.streamOutput.scrollHeight;
		state.charsSession = Math.max(state.charsSession, state.simPos);
		updateEnginePanel();
	}

	function sortedCreations() {
		return [...state.creations].sort((a, b) => {
			const ver = tag => {
				const m = String(tag).match(/VER(\d+)/i);
				return m ? parseInt(m[1], 10) : 9999;
			};
			const d = ver(a.sourceTag) - ver(b.sourceTag);
			return d !== 0 ? d : a.createdAt - b.createdAt;
		});
	}

	function pickSimFile(offset) {
		const sorted = sortedCreations();
		if (!sorted.length) return null;
		return sorted[(state.simFileIndex + offset) % sorted.length];
	}

	function findCreationBySaved(saved) {
		if (!saved || !state.creations.length) return null;
		if (saved.title) {
			const byTitle = state.creations.find(c => c.title === saved.title);
			if (byTitle) return byTitle;
		}
		if (saved.sourceTag) {
			const byTag = state.creations.find(c => c.sourceTag === saved.sourceTag);
			if (byTag) return byTag;
		}
		return null;
	}

	function persistSimState(force) {
		const now = Date.now();
		if (!force && now - lastSimPersistAt < 400) return;
		lastSimPersistAt = now;
		try {
			const file = pickSimFile(0);
			const payload = {
				v: SIM_STATE_VERSION,
				title: file?.title || '',
				sourceTag: file?.sourceTag || '',
				simFileIndex: state.simFileIndex,
				simPos: state.simPos,
				simGenerating: state.simGenerating,
				simCooldownUntil: state.simCooldownUntil || 0,
				savedAt: now
			};
			if (!payload.title && !payload.sourceTag && !state.simSource) return;
			localStorage.setItem(SIM_STATE_KEY, JSON.stringify(payload));
		} catch { /* storage unavailable */ }
	}

	function applySimFileUi(file) {
		if (!file) return;
		if (ui.strapLine) {
			ui.strapLine.textContent = `NOW BUILDING: ${promptTopic(file.prompt)}`;
		}
		if (ui.modelName) ui.modelName.textContent = formatModelDisplay(CONFIG.model);
	}

	function beginSimulatedFile(file, opts) {
		opts = opts || {};
		if (!file || !file.html) return false;
		const len = file.html.length;
		state.simSource = file.html;
		if (opts.resumePos != null) {
			state.simPos = Math.max(0, Math.min(opts.resumePos | 0, len));
			state.simGenerating = opts.generating !== false && state.simPos < len;
		} else {
			state.simPos = 0;
			state.simGenerating = true;
		}
		state.simStartedAt = Date.now();
		state.simCooldownUntil = 0;
		applySimFileUi(file);
		if (state.simGenerating) {
			setStatusPunch('GENERATING HTML');
			if (ui.streamHint) {
				ui.streamHint.textContent = `Simulated stream \u00B7 ${CONFIG.charsPerSecond} chars/s`;
			}
			logEntry(opts.resuming ? `RESUMED: ${file.title} @ ${state.simPos}` : `STREAMING: ${file.title}`);
			renderStream(true);
		} else {
			setStatusPunch('COOLDOWN', 'warn');
			renderStream(false);
		}
		state.simCharCarry = 0;
		persistSimState(true);
		return true;
	}

	function restoreSimState() {
		try {
			const raw = localStorage.getItem(SIM_STATE_KEY);
			if (!raw) return false;
			const saved = JSON.parse(raw);
			if (!saved || saved.v !== SIM_STATE_VERSION) return false;
			if (!state.creations.length) return false;

			const sorted = sortedCreations();
			let file = findCreationBySaved(saved);
			if (!file && Number.isFinite(saved.simFileIndex)) {
				state.simFileIndex = ((saved.simFileIndex | 0) % sorted.length + sorted.length) % sorted.length;
				file = pickSimFile(0);
			}
			if (!file || !file.html) return false;

			const len = file.html.length;
			const now = Date.now();
			const cooldownUntil = saved.simCooldownUntil || 0;
			let pos = Math.max(0, Math.min(saved.simPos | 0, len));

			state.simFileIndex = Number.isFinite(saved.simFileIndex)
				? ((saved.simFileIndex | 0) % sorted.length + sorted.length) % sorted.length
				: state.simFileIndex;
			state.simSource = file.html;

			if (cooldownUntil > now) {
				state.simPos = len;
				state.simGenerating = false;
				state.simCooldownUntil = cooldownUntil;
				applySimFileUi(file);
				setStatusPunch('COOLDOWN', 'warn');
				if (ui.streamHint) ui.streamHint.textContent = 'Cooldown 60s — next archive file';
				renderStream(false);
				persistSimState(true);
				logEntry(`RESUMED COOLDOWN: ${file.title}`);
				return true;
			}

			if (pos >= len) {
				state.simCooldownUntil = 0;
				startNextFileAfterCooldown();
				return !!state.simGenerating;
			}

			state.simPos = pos;
			state.simGenerating = saved.simGenerating !== false;
			state.simCooldownUntil = 0;
			state.simCharCarry = 0;
			applySimFileUi(file);
			if (state.simGenerating) {
				setStatusPunch('GENERATING HTML');
				if (ui.streamHint) {
					ui.streamHint.textContent = `Resumed stream \u00B7 ${CONFIG.charsPerSecond} chars/s`;
				}
				logEntry(`RESUMED @ ${pos}: ${file.title}`);
				renderStream(true);
			}
			persistSimState(true);
			return true;
		} catch {
			return false;
		}
	}

	function onSimFileComplete() {
		const done = pickSimFile(0);
		showToast(`FILE COMPLETE — ${(done?.title || 'ARCHIVE').replace(/\.html/i, '')}`, true);
		playSting('save');
		logEntry('FILE COMPLETE — COOLDOWN 60s');
		state.simGenerating = false;
		state.simCooldownUntil = Date.now() + (CONFIG.fileCooldownMs || 60000);
		state.cycle += 1;
		updateHeroStats();
		setStatusPunch('COOLDOWN', 'warn');
		if (ui.streamHint) ui.streamHint.textContent = 'Cooldown 60s — next file loading';
		renderStream(false);
		persistSimState(true);
	}

	function startNextFileAfterCooldown() {
		if (!state.creations.length) return;
		state.simFileIndex = (state.simFileIndex + 1) % state.creations.length;
		const next = pickSimFile(0);
		if (next) beginSimulatedFile(next);
	}

	function ensureSimStarted() {
		if (state.simSource && (state.simGenerating || state.simCooldownUntil > Date.now())) return;
		if (state.simCooldownUntil > Date.now()) return;
		if (!state.creations.length) return;
		const file = pickSimFile(0);
		if (file) beginSimulatedFile(file);
	}

	function simTick() {
		const now = Date.now();

		if (state.simCooldownUntil > now) {
			const left = Math.ceil((state.simCooldownUntil - now) / 1000);
			if (ui.streamHint) ui.streamHint.textContent = `Cooldown ${left}s — next archive file`;
			if (ui.timeStatus) ui.timeStatus.textContent = `CD ${left}s`;
			persistSimState(false);
			return;
		}

		if (state.simCooldownUntil && state.simCooldownUntil <= now && !state.simGenerating) {
			state.simCooldownUntil = 0;
			startNextFileAfterCooldown();
			return;
		}

		if (!state.simGenerating || !state.simSource) {
			ensureSimStarted();
			return;
		}

		const cps = CONFIG.charsPerSecond || 2;
		const tickMs = CONFIG.typingTickMs || 100;
		state.simCharCarry += cps * (tickMs / 1000);
		let n = Math.floor(state.simCharCarry);
		if (n < 1) return;
		state.simCharCarry -= n;
		n = Math.min(n, Math.max(1, Math.ceil(cps * (tickMs / 1000) * 2)));

		state.simPos = Math.min(state.simSource.length, state.simPos + n);
		renderStream(true);

		if (state.simPos >= state.simSource.length) {
			onSimFileComplete();
		} else {
			persistSimState(false);
		}
	}

	function startSimulatedTyping() {
		if (state.simTickTimer) return;
		if (!state.creations.length) {
			if (ui.streamOutput) {
				ui.streamOutput.classList.add('idle');
				ui.streamOutput.textContent = '// No archive HTML files found in library';
			}
			return;
		}
		state.simTickTimer = setInterval(simTick, CONFIG.typingTickMs || 100);
	}

	function stopSimulatedTyping() {
		if (state.simTickTimer) {
			clearInterval(state.simTickTimer);
			state.simTickTimer = null;
		}
	}

	function archiveFetchUrl(publicPath) {
		const p = String(publicPath || '').replace(/^\//, '');
		const rel = p.startsWith(CONFIG.archivePrefix) ? p : CONFIG.archivePrefix + p;
		return assetUrl(rel);
	}

	async function fetchArchiveFileList() {
		const manifestPath = CONFIG.archiveManifest || 'archive/manifest.json';
		try {
			const res = await fetch(assetUrl(manifestPath), { cache: 'no-store' });
			if (res.ok) {
				const data = await res.json();
				if (data.ok && Array.isArray(data.files)) return data.files;
			}
		} catch { /* manifest missing */ }
		if (useStaticArchive()) return [];
		try {
			const listRes = await fetch(CONFIG.apiListCreations, { cache: 'no-store' });
			if (!listRes.ok) return [];
			const data = await listRes.json();
			if (!data.ok || !Array.isArray(data.files)) return [];
			return data.files;
		} catch {
			return [];
		}
	}

	async function fetchCreationMeta(publicPath) {
		try {
			const url = archiveFetchUrl(publicPath).replace(/\.html$/i, '.json');
			const res = await fetch(url, { cache: 'no-store' });
			if (!res.ok) return null;
			return await res.json();
		} catch {
			return null;
		}
	}

	function addCreation(publicPath, html, modified, meta) {
		const base = publicPath.split('/').pop() || publicPath;
		const m = meta && typeof meta === 'object' ? meta : {};
		state.creations.unshift({
			title: base,
			html,
			sourceTag: publicPath,
			createdAt: Date.parse(modified) || Date.now(),
			prompt: String(m.prompt || '').trim(),
			promptIndex: m.promptIndex ?? null
		});
		if (state.creations.length > 120) state.creations.length = 120;
	}

	async function refreshArchive() {
		if (state.archiveLoading) return;
		state.archiveLoading = true;
		try {
			const files = await fetchArchiveFileList();
			if (!files.length) return;
			const known = new Set(state.creations.map(c => c.sourceTag));
			let added = 0;
			for (const f of files) {
				if (known.has(f.name)) continue;
				try {
					const r = await fetch(archiveFetchUrl(f.name), { cache: 'no-store' });
					if (!r.ok) continue;
					const text = await r.text();
					if (text.length < 500 || !/<\/html>/i.test(text)) continue;
					let meta = null;
					if (f.prompt) {
						meta = { prompt: f.prompt, promptIndex: f.promptIndex ?? null };
					} else {
						meta = await fetchCreationMeta(f.name);
					}
					addCreation(f.name, text, f.modified, meta);
					added++;
				} catch { /* skip */ }
			}
			if (added > 0) {
				buildTopMarquee();
				updateHeroStats();
				showToast(`${added} NEW ARCHIVE FILE(S) DETECTED`, true);
			}
		} finally {
			state.archiveLoading = false;
		}
	}

	function pickCreationAt(offset) {
		const sorted = sortedCreations();
		if (!sorted.length) return null;
		return sorted[(state.rotationIndex + offset) % sorted.length];
	}

	async function ensureCreationMeta(chosen) {
		if (!chosen) return chosen;
		if (chosen.prompt && chosen.prompt.length > 20) return chosen;
		const meta = await fetchCreationMeta(chosen.sourceTag);
		if (meta?.prompt) chosen.prompt = String(meta.prompt).trim();
		return chosen;
	}

	function showArchivePromptBanner(promptText) {
		if (!ui.overlayPrompt || !ui.overlayPromptText) return;
		clearTimeout(overlayPromptTimer);
		let text = String(promptText || '').trim();
		let ms = CONFIG.promptRevealMs || 5000;
		if (!text) {
			text = 'Prompt metadata not stored for this file.';
			ms = 3500;
		}
		ui.overlayPromptText.textContent = text;
		ui.overlayPrompt.classList.remove('hide');
		overlayPromptTimer = setTimeout(() => ui.overlayPrompt.classList.add('hide'), ms);
	}

	function showCreationInOverlay(chosen, slotLabel) {
		const ago = Math.max(1, Math.round((Date.now() - chosen.createdAt) / 60000));
		const topic = chosen.title.replace(/index-4\.7-/i, '').replace(/\.html/i, '');
		const idxLabel = chosen.promptIndex != null ? ` \u00B7 PROMPT #${chosen.promptIndex + 1}` : '';
		if (ui.overlayTitle) {
			ui.overlayTitle.textContent = `${topic} \u00B7 ${ago} min ago${idxLabel}`;
		}
		if (ui.overlayFrame) ui.overlayFrame.srcdoc = chosen.html;
		if (ui.overlay) ui.overlay.classList.add('show');
		const pill = ui.overlay?.querySelector('.pill');
		if (pill) pill.textContent = slotLabel;
		setArchiveScreen(true, parseInt(String(slotLabel).replace(/\D/g, ''), 10) || 1);
		setStatusPunch(slotLabel, 'archive');
		showArchivePromptBanner(chosen.prompt);
		playSting('archive');
	}

	function hideOverlay() {
		clearTimeout(overlayPromptTimer);
		if (ui.overlayPrompt) ui.overlayPrompt.classList.add('hide');
		if (ui.overlay) ui.overlay.classList.remove('show');
		setArchiveScreen(false);
		if (ui.overlayCountdown) ui.overlayCountdown.classList.remove('urgent');
	}

	async function showComingUp(chosen, slotIndex) {
		const topic = chosen ? chosen.title.replace(/\.html/i, '').replace(/index-4\.7-/i, '') : 'ARCHIVE';
		const ago = chosen ? Math.max(1, Math.round((Date.now() - chosen.createdAt) / 60000)) : 0;
		const slotNum = typeof slotIndex === 'number' ? slotIndex + 1 : 1;
		if (ui.tvwipeKicker) ui.tvwipeKicker.textContent = 'COMING UP NEXT';
		if (ui.tvwipeTitle) ui.tvwipeTitle.textContent = topic.toUpperCase();
		if (ui.tvwipeSub) ui.tvwipeSub.textContent = chosen
			? `ARCHIVE #${slotNum} \u00B7 ${ago} MIN AGO`
			: 'FROM THE ARCHIVE';
		if (ui.tvwipe) {
			ui.tvwipe.classList.add('archive');
			ui.tvwipe.classList.add('show');
		}
		setSegmentEnd(Date.now() + CONFIG.comingUpMs, 'COMING UP IN');
		playSting('transition');
		await wait(CONFIG.comingUpMs);
		if (ui.tvwipe) ui.tvwipe.classList.remove('show');
	}

	async function showBackToLiveWipe() {
		if (ui.tvwipeKicker) ui.tvwipeKicker.textContent = 'NOW LIVE';
		if (ui.tvwipeTitle) ui.tvwipeTitle.textContent = 'SIMULATED LIVE BUILD';
		if (ui.tvwipeSub) ui.tvwipeSub.textContent = 'ARCHIVE LIBRARY \u00B7 DISPLAY MODE';
		if (ui.tvwipe) {
			ui.tvwipe.classList.remove('archive');
			ui.tvwipe.classList.add('show');
		}
		setSegmentEnd(Date.now() + CONFIG.liveSegmentMs, 'ARCHIVE IN');
		playSting('live');
		await wait(CONFIG.comingUpMs);
		if (ui.tvwipe) ui.tvwipe.classList.remove('show');
	}

	function archiveSegmentLabel(slotIndex) {
		const slot = slotIndex + 1;
		if (slotIndex >= CONFIG.archiveSlots - 1) return 'LIVE BUILD IN';
		return `ARCHIVE #${slot + 1} IN`;
	}

	async function runBroadcastCycle() {
		if (state.transitioning) return;
		state.transitioning = true;
		hideOverlay();
		setLiveMode(false);
		setStatusPunch('GENERATING HTML');
		setOnAir(true);

		setSegmentEnd(Date.now() + CONFIG.liveSegmentMs, 'ARCHIVE IN');
		if (firstLiveSegment) {
			firstLiveSegment = false;
			playSting('live');
		}
		await wait(CONFIG.liveSegmentMs);

		if (!state.creations.length) {
			state.transitioning = false;
			setTimeout(runBroadcastCycle, 5000);
			return;
		}

		for (let slot = 0; slot < CONFIG.archiveSlots; slot++) {
			let chosen = pickCreationAt(slot);
			if (!chosen) break;
			chosen = await ensureCreationMeta(chosen);
			await showComingUp(chosen, slot);
			showCreationInOverlay(chosen, `ARCHIVE #${slot + 1}`);
			setStatusPunch(`ARCHIVE #${slot + 1}`, 'archive');
			setSegmentEnd(Date.now() + CONFIG.archiveSegmentMs, archiveSegmentLabel(slot));
			showToast(`NOW PLAYING ARCHIVE #${slot + 1}`, true);
			await wait(CONFIG.archiveSegmentMs);
			hideOverlay();
		}

		state.rotationIndex += CONFIG.archiveSlots;
		try { localStorage.setItem(ARCHIVE_ROTATION_KEY, String(state.rotationIndex)); } catch { /* */ }

		await showBackToLiveWipe();
		state.transitioning = false;
		setTimeout(runBroadcastCycle, 400);
	}

	function rotateEventToast() {
		if (state.transitioning || state.broadcastPhase === 'archive') return;
		const msg = EVENT_POOL[state.eventPoolIndex % EVENT_POOL.length];
		state.eventPoolIndex++;
		showToast(msg);
	}

	function rotatePromo() {
		if (!ui.promo || !ui.promoLine) return;
		ui.promoLine.textContent = PROMO_LINES[state.promoIndex % PROMO_LINES.length];
		state.promoIndex++;
		ui.promo.classList.add('show');
		setTimeout(() => ui.promo.classList.remove('show'), CONFIG.promoShowMs);
	}

	async function pollStats() {
		if (useStaticArchive()) return;
		try {
			const res = await fetch(CONFIG.apiStats, { cache: 'no-store' });
			if (!res.ok) return;
			const data = await res.json();
			if (!data.ok || !data.stats) return;
			const s = data.stats;
			if (s.gpu && s.gpu.ok && ui.gpuMini) {
				ui.gpuMini.textContent = state.simGenerating
					? `RTX 3050 STREAMING ${s.gpu.util.toFixed(0)}%`
					: `GPU ${s.gpu.util.toFixed(0)}%`;
			}
			if (ui.gpuName && s.gpu) ui.gpuName.textContent = s.gpu.name || 'GPU';
			if (ui.gpuBar && s.gpu && s.gpu.ok) {
				const v = Math.max(0, Math.min(100, s.gpu.util));
				if (ui.gpuBar.firstElementChild) ui.gpuBar.firstElementChild.style.width = v + '%';
				if (ui.gpuPct) ui.gpuPct.textContent = `${v.toFixed(0)}%`;
			}
		} catch { /* best-effort */ }
	}

	function bindAudioFallback() {
		const kick = () => {
			primeHtmlAudio();
			playSfx(440, 0.06, 0.35);
		};
		['pointerdown', 'keydown', 'touchstart', 'mousemove'].forEach(ev => {
			document.addEventListener(ev, kick, { passive: true, once: true });
		});
		document.addEventListener('visibilitychange', () => {
			if (document.visibilityState === 'visible') startAutoAudio();
		});
	}

	function initOverlayEvents() {
		if (ui.closeOverlay) {
			ui.closeOverlay.addEventListener('click', () => { hideOverlay(); setLiveMode(false); });
		}
		document.addEventListener('keydown', e => {
			if (e.key === 'Escape') { hideOverlay(); setLiveMode(false); }
		});
		bindAudioFallback();
	}

	function initStarfield() {
		const canvas = document.getElementById('starfield');
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		const dpr = Math.min(2, window.devicePixelRatio || 1);
		let w = 0, h = 0, stars = [];
		function resize() {
			w = canvas.width = Math.floor(window.innerWidth * dpr);
			h = canvas.height = Math.floor(window.innerHeight * dpr);
			canvas.style.width = window.innerWidth + 'px';
			canvas.style.height = window.innerHeight + 'px';
		}
		function seed() {
			stars = [];
			const count = Math.max(120, Math.floor((window.innerWidth * window.innerHeight) / 9000));
			for (let i = 0; i < count; i++) {
				stars.push({ x: (Math.random() - 0.5) * w, y: (Math.random() - 0.5) * h, z: Math.random() * w, pz: 0 });
			}
		}
		function tick() {
			ctx.fillStyle = 'rgba(1,3,10,0.35)';
			ctx.fillRect(0, 0, w, h);
			ctx.save();
			ctx.translate(w / 2, h / 2);
			for (const s of stars) {
				s.pz = s.z;
				s.z -= 1.6 * dpr;
				if (s.z < 1) { s.z = w; s.x = (Math.random() - 0.5) * w; s.y = (Math.random() - 0.5) * h; s.pz = s.z; }
				const sx = (s.x / s.z) * w, sy = (s.y / s.z) * w;
				const px = (s.x / s.pz) * w, py = (s.y / s.pz) * w;
				ctx.strokeStyle = 'rgba(140,210,255,0.5)';
				ctx.beginPath();
				ctx.moveTo(px, py);
				ctx.lineTo(sx, sy);
				ctx.stroke();
			}
			ctx.restore();
			requestAnimationFrame(tick);
		}
		resize(); seed();
		window.addEventListener('resize', () => { resize(); seed(); }, { passive: true });
		requestAnimationFrame(tick);
	}

	async function boot() {
		try {
			const savedIdx = parseInt(localStorage.getItem(ARCHIVE_ROTATION_KEY) || '0', 10);
			if (Number.isFinite(savedIdx) && savedIdx > 0) state.rotationIndex = savedIdx;
		} catch { /* */ }

		if (ui.modelName) ui.modelName.textContent = formatModelDisplay(CONFIG.model);
		if (ui.modeNowText) ui.modeNowText.textContent = 'ARCHIVE SIMULATION';
		initStarfield();
		initOverlayEvents();
		setOnAir(true);
		setStatusPunch('LIVE');
		logEntry('ARCHIVE DISPLAY MODE ONLINE');
		showToast('ARCHIVE SIMULATION ONLINE', true);
		startAutoAudio();

		setInterval(() => {
			if (ui.clock) ui.clock.textContent = new Date().toLocaleTimeString('en-GB', { hour12: false });
		}, 1000);
		setInterval(tickCountdown, 250);
		setInterval(updateHeroStats, 5000);
		setInterval(updateEnginePanel, 500);

		const toastMs = CONFIG.eventToastMs || 12000;
		setInterval(rotateEventToast, toastMs);
		setInterval(rotatePromo, CONFIG.promoIntervalMs);

		await refreshArchive();
		buildTopMarquee();
		renderLowerCrawl();
		updateHeroStats();

		if (!state.creations.length) {
			await refreshArchive();
		}

		const restored = restoreSimState();
		if (!restored) ensureSimStarted();
		startSimulatedTyping();

		window.addEventListener('pagehide', () => persistSimState(true));
		document.addEventListener('visibilitychange', () => {
			if (document.visibilityState === 'hidden') persistSimState(true);
		});
		pollStats();
		setInterval(pollStats, CONFIG.statsIntervalMs);
		setInterval(refreshArchive, CONFIG.archiveRefreshMs);
		setInterval(buildTopMarquee, 60000);

		setSegmentEnd(Date.now() + CONFIG.liveSegmentMs, 'ARCHIVE IN');
		runBroadcastCycle();
	}

	startAutoAudio();
	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', boot);
	} else {
		boot();
	}
})();
