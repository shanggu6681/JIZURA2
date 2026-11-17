/* ============================================================
   JIZURA — lyrics: auto-search, speech recognition & beat alignment
   歌词自动识别与匹配：在线搜索、语音识别、节拍自动对齐
   ============================================================ */
(() => {
'use strict';

/* ---------- 在线歌词搜索 ---------- */

// 后端服务地址（本地 Whisper 识别服务）
const WHISPER_API_BASE = (() => {
  // 默认使用当前页面同主机的 8080 端口（后端服务）
  // 如果页面本身就在 8080，就用相对路径
  return ''; // 相对路径，由同一个 Flask 服务提供
})();

/* ---------- Whisper 本地识别（后端服务） ---------- */

/**
 * 检查后端识别服务是否可用
 * @returns {Promise<{ok:boolean, model_loaded?:boolean, model_size?:string}>}
 */
J.checkWhisperService = async () => {
  try {
    const res = await fetch('/api/health', { cache: 'no-store' });
    if (!res.ok) return { ok: false };
    return await res.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
};

/**
 * 获取当前识别状态
 * @returns {Promise<Object>}
 */
J.getWhisperStatus = async () => {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    if (!res.ok) return { status: 'error', message: '服务不可用' };
    return await res.json();
  } catch (e) {
    return { status: 'error', message: e.message };
  }
};

/**
 * 上传音频文件并开始识别
 * @param {File} file - 音频文件对象
 * @param {string} modelSize - 模型大小
 * @param {string} language - 语言代码
 * @param {boolean} separateVocals - 是否先分离人声
 * @returns {Promise<{ok:boolean, message?:string, error?:string}>}
 */
J.startWhisperTranscribe = async (file, modelSize, language, separateVocals) => {
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('model', modelSize || 'small');
    if (language) formData.append('language', language);
    if (separateVocals !== undefined) formData.append('separate_vocals', separateVocals ? 'true' : 'false');

    const res = await fetch('/api/transcribe', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, error: data.error || '识别失败' };
    return { ok: true, message: data.message, separate_vocals: data.separate_vocals };
  } catch (e) {
    return { ok: false, error: e.message };
  }
};

/**
 * 轮询识别状态直到完成
 * @param {function} onProgress - 进度回调 (status)
 * @param {number} pollInterval - 轮询间隔（毫秒）
 * @returns {Promise<Object>} 识别结果
 */
J.waitForWhisperResult = async (onProgress, pollInterval) => {
  pollInterval = pollInterval || 1000;
  while (true) {
    const st = await J.getWhisperStatus();
    if (onProgress) onProgress(st);

    if (st.status === 'done') return st.result || {};
    if (st.status === 'error') {
      const err = new Error(st.message || st.error || '识别失败');
      err.traceback = st.traceback || '';
      err.detail = st.error || '';
      throw err;
    }

    await new Promise(r => setTimeout(r, pollInterval));
  }
};

// 歌词 API 列表（按优先级尝试）
const LYRICS_APIS = [
  {
    name: 'lrclib',
    search: async (title, artist) => {
      const q = encodeURIComponent(`${artist} ${title}`.trim());
      const url = `https://lrclib.net/api/search?q=${q}`;
      try {
        const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
        if (!res.ok) return null;
        const data = await res.json();
        if (!Array.isArray(data) || !data.length) return null;
        // 找到最佳匹配：优先有 syncedLyrics 的
        const best = data.find(item => item.syncedLyrics) || data[0];
        const lyrics = best.syncedLyrics || best.plainLyrics || best.lyrics || '';
        return {
          title: best.trackName || title,
          artist: best.artistName || artist,
          lyrics: lyrics,
          isSynced: !!best.syncedLyrics,
          source: 'lrclib.net'
        };
      } catch (e) { return null; }
    }
  }
];

/**
 * 搜索在线歌词
 * @param {string} title - 歌曲名
 * @param {string} artist - 艺术家（可选）
 * @returns {Promise<{title:string, artist:string, lyrics:string, isSynced:boolean, source:string}|null>}
 */
J.searchLyrics = async (title, artist) => {
  if (!title && !artist) return null;
  for (const api of LYRICS_APIS) {
    const result = await api.search(title || '', artist || '');
    if (result && result.lyrics) return result;
  }
  return null;
};

/* ---------- Web Speech API 语音识别 ---------- */

/**
 * 检查浏览器是否支持语音识别
 * @returns {boolean}
 */
J.supportsSpeechRecognition = () => {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
};

/**
 * 创建语音识别器
 * @param {string} lang - 语言代码 (如 'zh-CN', 'ja-JP', 'en-US')
 * @param {function} onResult - 结果回调 (text, isFinal, timestamp)
 * @param {function} onError - 错误回调
 * @param {function} onEnd - 结束回调
 * @returns {{start: function, stop: function, isRunning: function}}
 */
J.createSpeechRecognizer = (lang, onResult, onError, onEnd) => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;

  const recog = new SR();
  recog.lang = lang || 'zh-CN';
  recog.continuous = true;
  recog.interimResults = true;
  recog.maxAlternatives = 1;

  let running = false;
  const results = []; // {text, time, final}

  recog.onresult = (event) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        // 计算大致时间戳（基于结果索引和音频开始时间的近似）
        results.push({ text: transcript.trim(), final: true, idx: results.length });
        if (onResult) onResult(transcript.trim(), true, results.length - 1);
      } else {
        interim += transcript;
      }
    }
    if (interim && onResult) onResult(interim.trim(), false, results.length);
  };

  recog.onerror = (event) => {
    running = false;
    if (onError) onError(event.error || 'unknown');
  };

  recog.onend = () => {
    running = false;
    if (onEnd) onEnd(results);
  };

  return {
    start: () => {
      try {
        recog.start();
        running = true;
        results.length = 0;
      } catch (e) { /* already started */ }
    },
    stop: () => {
      try { recog.stop(); } catch (e) {}
      running = false;
    },
    abort: () => {
      try { recog.abort(); } catch (e) {}
      running = false;
    },
    isRunning: () => running,
    getResults: () => results.slice()
  };
};

/* ---------- 节拍自动对齐 ---------- */

/**
 * 根据节拍自动为歌词分配时间（改进版 v2）
 * 策略：
 * 1. 使用节拍网格作为骨架
 * 2. 估算人声开始位置（前奏长度）
 * 3. 按节拍小节（4拍）分配歌词行，每行占 N 个小节
 * 4. 根据每行字数微调，但保持节拍对齐
 * @param {string[]} lines - 歌词行数组
 * @param {{beats: number[], bpm: number, duration: number}} audio - 音频分析结果
 * @param {Object} options - 选项 { introPad, firstBeatIdx, linesPerBar, startBarOffset }
 * @returns {Array<{text: string, start: number, end: number}>}
 */
J.autoAlignLyrics = (lines, audio, options = {}) => {
  const result = [];
  if (!lines || !lines.length) return result;

  const beats = audio && audio.beats ? audio.beats : [];
  const duration = audio && audio.duration ? audio.duration : lines.length * 4;
  const bpm = audio && audio.bpm ? audio.bpm : 120;
  const beatPeriod = bpm > 0 ? 60 / bpm : 0.5;

  // 分离歌词行、空行、间奏行
  const allItems = [];
  const lyricItems = [];

  lines.forEach((line, idx) => {
    const trimmed = (line || '').trim();
    if (!trimmed) {
      allItems.push({ idx, type: 'gap' });
    } else if (/^\[\s*(間奏|间奏|interlude|instrumental|inst|간주)/i.test(trimmed)) {
      const m = trimmed.match(/^\[\s*(?:間奏|间奏|interlude|instrumental|inst|간주)(?:\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|秒|초)?)?\s*\]$/i);
      const secs = m && m[1] ? parseFloat(m[1]) : 4;
      allItems.push({ idx, type: 'interlude', text: trimmed, secs });
    } else {
      const li = lyricItems.length;
      lyricItems.push({ idx, text: trimmed });
      allItems.push({ idx, type: 'lyric', text: trimmed, lyricIdx: li });
    }
  });

  if (!lyricItems.length) return result;

  // ========== 估算前奏（人声开始位置）==========
  let introPad;
  if (options.introPad != null) {
    introPad = options.introPad;
  } else if (beats.length > 8) {
    // 有节拍数据：默认从第8拍（2个小节）开始，给前奏留余地
    // 选项可以指定从第几拍开始
    const firstBeatIdx = options.firstBeatIdx != null ? options.firstBeatIdx : 8;
    const bi = Math.min(firstBeatIdx, beats.length - 1);
    introPad = beats[bi];
  } else {
    introPad = Math.min(8, duration * 0.1);
  }

  // ========== 计算每行占几个小节 ==========
  // 一小节 = 4拍 = 4 * beatPeriod 秒
  const barDuration = beatPeriod * 4;
  const availDur = duration - introPad - Math.min(4, duration * 0.05);

  // 估算：平均每行占几个小节
  // 如果有节拍，用节拍总数来算
  let totalBars;
  if (beats.length > 4) {
    // 从 introPad 之后的节拍数
    const beatsAfterIntro = beats.filter(b => b >= introPad);
    totalBars = Math.max(lyricItems.length, beatsAfterIntro.length / 4);
  } else {
    totalBars = Math.max(lyricItems.length, availDur / barDuration);
  }

  // 每行平均占用的小节数
  let barsPerLine = options.barsPerLine || 0;
  if (!barsPerLine) {
    barsPerLine = Math.max(0.5, totalBars / lyricItems.length);
    // 限制在合理范围：半小节到4小节
    barsPerLine = Math.min(4, Math.max(0.5, barsPerLine));
  }

  // ========== 为每句歌词分配小节位置 ==========
  // 基础：按顺序排列，每句 barsPerLine 小节
  const lineStarts = []; // 每行的起始时间（秒）
  const lineBars = [];   // 每行占多少小节

  // 计算每行的"长度权重"（用于微调占用的小节数）
  const weights = lyricItems.map(ln => {
    const text = ln.text.replace(/[\s\p{P}]/gu, '');
    return Math.max(1, text.length);
  });
  const avgWeight = weights.reduce((a, b) => a + b, 0) / weights.length;

  let currentBar = 0; // 当前小节索引（相对 introPad）

  for (let i = 0; i < lyricItems.length; i++) {
    // 基础小节数
    let lineBarsCount = barsPerLine;

    // 根据字数微调：比平均长的多占一点，短的少占一点
    const weightRatio = weights[i] / avgWeight;
    lineBarsCount *= Math.min(1.5, Math.max(0.6, weightRatio));

    // 对齐到 0.5 小节
    lineBarsCount = Math.round(lineBarsCount * 2) / 2;
    lineBarsCount = Math.max(0.5, lineBarsCount); // 最少半小节

    lineBars.push(lineBarsCount);
    lineStarts.push(currentBar * barDuration + introPad);
    currentBar += lineBarsCount;
  }

  // ========== 如果有节拍数据，吸附到实际节拍上 ==========
  if (beats && beats.length > 4) {
    for (let i = 0; i < lineStarts.length; i++) {
      // 找到理论开始时间附近的节拍
      lineStarts[i] = snapToBeat(lineStarts[i], beats);
    }
  }

  // ========== 生成最终结果 ==========
  let resultIndex = 0;
  let lyricIdx = 0;
  let currentTime = introPad;

  allItems.forEach((item) => {
    if (item.type === 'gap') {
      // 空行：半小节停顿
      const gapDur = barDuration * 0.5;
      currentTime += gapDur;
      return;
    }

    if (item.type === 'interlude') {
      const dur = item.secs || (barDuration * 2);
      // 吸附到节拍
      let endTime = currentTime + dur;
      if (beats && beats.length > 2) {
        endTime = snapToBeat(endTime, beats);
      }
      result.push({
        index: item.idx,
        text: '',
        interlude: true,
        secs: dur,
        start: currentTime,
        end: endTime,
        lrc: currentTime
      });
      currentTime = endTime;
      return;
    }

    if (item.type === 'lyric') {
      const li = item.lyricIdx;
      const start = lineStarts[li];
      let end;

      if (li < lyricItems.length - 1) {
        end = lineStarts[li + 1] - beatPeriod * 0.1; // 留一点点间隙
      } else {
        // 最后一行
        end = start + lineBars[li] * barDuration;
        end = Math.min(end, duration - beatPeriod);
      }

      // 确保最小时长
      const minDur = beatPeriod * 1.5;
      if (end - start < minDur) end = start + minDur;

      // 结束时间也吸附到节拍
      if (beats && beats.length > 2) {
        const snappedEnd = snapToBeat(end, beats);
        if (snappedEnd > start + beatPeriod * 0.5) {
          end = snappedEnd;
        }
      }

      result.push({
        index: item.idx,
        text: item.text,
        interlude: false,
        start,
        end,
        lrc: start
      });
      currentTime = end;
      resultIndex++;
    }
  });

  return result;
};

// 吸附到最近的节拍（只往前后各找几个节拍，避免吸附太远）
function snapToBeat(t, beats, maxJump) {
  if (!beats || !beats.length) return t;
  maxJump = maxJump || 3; // 最多跳动几个节拍

  // 二分查找找到最接近的节拍索引
  let lo = 0, hi = beats.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (beats[mid] < t) lo = mid + 1; else hi = mid;
  }

  let bestIdx = lo;
  let bestDiff = Math.abs(t - beats[lo]);

  if (lo > 0 && Math.abs(t - beats[lo - 1]) < bestDiff) {
    bestIdx = lo - 1;
    bestDiff = Math.abs(t - beats[lo - 1]);
  }

  return beats[bestIdx];
}

/**
 * 整体偏移所有歌词时间（前移或后移）
 * @param {Object} lineTimes - 当前的 lineTimes 对象 {行索引: 开始时间}
 * @param {number} offset - 偏移秒数（正数=后移，负数=前移）
 * @returns {Object} 新的 lineTimes
 */
J.shiftAllLineTimes = (lineTimes, offset) => {
  const result = {};
  for (const key in lineTimes) {
    if (Object.prototype.hasOwnProperty.call(lineTimes, key)) {
      const t = +lineTimes[key] + offset;
      result[key] = +Math.max(0, t).toFixed(3);
    }
  }
  return result;
};

/**
 * 整体缩放所有歌词时间（拉伸或压缩）
 * @param {Object} lineTimes - 当前的 lineTimes 对象
 * @param {number} scale - 缩放比例（>1=拉长，<1=压缩）
 * @param {number} pivot - 基准时间点（通常是第一行的开始时间）
 * @returns {Object} 新的 lineTimes
 */
J.scaleLineTimes = (lineTimes, scale, pivot) => {
  const result = {};
  pivot = pivot || 0;
  for (const key in lineTimes) {
    if (Object.prototype.hasOwnProperty.call(lineTimes, key)) {
      const t = +lineTimes[key];
      const scaled = pivot + (t - pivot) * scale;
      result[key] = +Math.max(0, scaled).toFixed(3);
    }
  }
  return result;
};

/**
 * 逐行吸附到最近的节拍
 * @param {Object} lineTimes - 当前的 lineTimes 对象
 * @param {number[]} beats - 节拍数组
 * @returns {Object} 新的 lineTimes
 */
J.snapLineTimesToBeats = (lineTimes, beats) => {
  const result = {};
  if (!beats || !beats.length) return { ...lineTimes };
  for (const key in lineTimes) {
    if (Object.prototype.hasOwnProperty.call(lineTimes, key)) {
      result[key] = +snapToBeat(+lineTimes[key], beats).toFixed(3);
    }
  }
  return result;
};

/* ---------- LRC 解析增强 ---------- */

/**
 * 将自动对齐的歌词转换为 LRC 格式文本
 * @param {Array} alignedLines - J.autoAlignLyrics 的结果
 * @param {Object} meta - 元信息 {ti, ar, al}
 * @returns {string} LRC 格式文本
 */
J.linesToLRC = (alignedLines, meta = {}) => {
  const lines = [];
  if (meta.ti) lines.push(`[ti:${meta.ti}]`);
  if (meta.ar) lines.push(`[ar:${meta.ar}]`);
  if (meta.al) lines.push(`[al:${meta.al}]`);

  alignedLines.forEach(ln => {
    const t = ln.start != null ? ln.start : (ln.lrc != null ? ln.lrc : 0);
    const timeStr = formatLRCTime(t);
    if (ln.interlude) {
      lines.push(`[${timeStr}][间奏 ${ln.secs || 4}]`);
    } else {
      lines.push(`[${timeStr}]${ln.text || ''}`);
    }
  });

  return lines.join('\n');
};

function formatLRCTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  const ss = Math.floor(s);
  const ms = Math.round((s - ss) * 100);
  return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
}

/* ---------- 歌词行拆分 ---------- */

/**
 * 将一整段歌词文本智能拆分为多行
 * （根据标点、句子长度等自动分行）
 * @param {string} text - 原始歌词文本
 * @param {string} lang - 语言代码
 * @returns {string[]} 分行后的歌词数组
 */
J.splitLyricLines = (text, lang) => {
  if (!text) return [];
  const raw = text.replace(/\r/g, '').trim();

  // 如果已经有换行符，直接按换行拆分
  if (raw.includes('\n')) {
    return raw.split('\n').map(l => l.trim()).filter(Boolean);
  }

  // 智能分行：按标点符号拆分
  const isChinese = lang === 'zh-Hans' || lang === 'zh-Hant';
  const isJapanese = lang === 'ja';
  const isKorean = lang === 'ko';

  let lines = [];

  if (isChinese || isJapanese) {
    // 中文/日文：按句号、问号、感叹号、逗号拆分
    const sentences = raw.split(/([。！？!?…])/);
    let current = '';
    for (let i = 0; i < sentences.length; i++) {
      const s = sentences[i];
      if (/[。！？!?…]/.test(s)) {
        current += s;
        if (current.trim()) lines.push(current.trim());
        current = '';
      } else {
        current += s;
        // 如果句子太长，再按逗号等拆分
        if (current.length > 20) {
          const parts = current.split(/([，、,])/);
          let buf = '';
          for (let j = 0; j < parts.length; j++) {
            const p = parts[j];
            if (/[，、,]/.test(p)) {
              buf += p;
              if (buf.length > 6) {
                if (buf.trim()) lines.push(buf.trim());
                buf = '';
              }
            } else {
              buf += p;
            }
          }
          current = buf;
        }
      }
    }
    if (current.trim()) lines.push(current.trim());
  } else {
    // 英文/韩文等：按句号、问号、感叹号拆分
    const sentences = raw.split(/([.!?])/);
    let current = '';
    for (let i = 0; i < sentences.length; i++) {
      const s = sentences[i];
      if (/[.!?]/.test(s)) {
        current += s;
        if (current.trim()) lines.push(current.trim());
        current = '';
      } else {
        current += s;
        // 长句按逗号拆分
        if (current.length > 50) {
          const parts = current.split(/(,)/);
          let buf = '';
          for (let j = 0; j < parts.length; j++) {
            const p = parts[j];
            if (p === ',') {
              buf += p;
              if (buf.length > 20) {
                if (buf.trim()) lines.push(buf.trim());
                buf = '';
              }
            } else {
              buf += p;
            }
          }
          current = buf;
        }
      }
    }
    if (current.trim()) lines.push(current.trim());
  }

  return lines.filter(Boolean);
};

/* ---------- SRT 字幕解析 ---------- */

/**
 * 解析 SRT 字幕格式
 * @param {string} srtText - SRT 格式文本
 * @returns {{lines: Array<{text: string, start: number, end: number}>, isSynced: boolean}}
 */
J.parseSRT = (srtText) => {
  const result = { lines: [], isSynced: false };
  if (!srtText) return result;

  const text = srtText.replace(/\r\n?/g, '\n').trim();
  if (!text) return result;

  // SRT 格式：
  // 1
  // 00:00:01,000 --> 00:00:04,000
  // 字幕文本（可能多行）
  // （空行分隔）

  // 按空行分割成块
  const blocks = text.split(/\n\s*\n/);

  for (const block of blocks) {
    const lines = block.split('\n').filter(l => l.trim());
    if (!lines.length) continue;

    let startIdx = 0;
    // 第一行可能是序号（纯数字）
    if (/^\d+$/.test(lines[0].trim())) {
      startIdx = 1;
    }

    // 找时间轴行
    let timeLine = -1;
    let start = 0, end = 0;
    for (let i = startIdx; i < lines.length; i++) {
      const t = parseSRTTimeLine(lines[i]);
      if (t) { timeLine = i; start = t.start; end = t.end; break; }
    }

    if (timeLine < 0) continue; // 没有时间轴，跳过

    // 剩余的是字幕文本（可能多行）
    const textLines = lines.slice(timeLine + 1);
    const subtitleText = textLines.join(' ').trim();

    if (subtitleText) {
      result.lines.push({
        text: subtitleText,
        start,
        end
      });
    }
  }

  result.isSynced = result.lines.length > 0;
  return result;
};

// 解析 SRT 时间轴行："00:00:01,000 --> 00:00:04,000"
function parseSRTTimeLine(line) {
  const m = line.match(/(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/);
  if (!m) return null;
  const start = (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) + (+m[4]) / Math.pow(10, m[4].length);
  const end = (+m[5]) * 3600 + (+m[6]) * 60 + (+m[7]) + (+m[8]) / Math.pow(10, m[8].length);
  return { start, end };
}

/**
 * 将 SRT 解析结果转换为 JIZURA 可用的歌词 + lineTimes 格式
 * @param {Object} srtResult - J.parseSRT 的结果
 * @returns {{lyrics: string, lineTimes: Object}}
 */
J.srtToLyrics = (srtResult) => {
  const lyrics = [];
  const lineTimes = {};

  if (!srtResult || !srtResult.lines || !srtResult.lines.length) {
    return { lyrics: '', lineTimes: {} };
  }

  srtResult.lines.forEach((ln, idx) => {
    lyrics.push(ln.text);
    lineTimes[idx] = +ln.start.toFixed(3);
  });

  return {
    lyrics: lyrics.join('\n'),
    lineTimes
  };
};

/* ---------- ASS/SSA 字幕解析 ---------- */

/**
 * 解析 ASS/SSA 字幕格式
 * @param {string} assText - ASS 格式文本
 * @returns {{lines: Array<{text: string, start: number, end: number}>, isSynced: boolean}}
 */
J.parseASS = (assText) => {
  const result = { lines: [], isSynced: false };
  if (!assText) return result;

  const text = assText.replace(/\r\n?/g, '\n');
  const eventsMatch = text.match(/\[Events\][\s\S]*?(?=\n\[|$)/i);
  if (!eventsMatch) return result;

  const eventsSection = eventsMatch[0];
  const formatMatch = eventsSection.match(/Format:\s*(.*)/i);
  if (!formatMatch) return result;

  const formatFields = formatMatch[1].split(',').map(f => f.trim());
  const startIdx = formatFields.indexOf('Start');
  const endIdx = formatFields.indexOf('End');
  const textIdx = formatFields.indexOf('Text');

  if (startIdx < 0 || endIdx < 0 || textIdx < 0) return result;

  const dialogueLines = eventsSection.match(/^Dialogue:.*$/gim) || [];

  for (const line of dialogueLines) {
    const parts = line.substring(9).split(','); // 去掉 "Dialogue: "
    if (parts.length <= textIdx) continue;

    const start = parseASSTime(parts[startIdx]);
    const end = parseASSTime(parts[endIdx]);
    const subtitleText = parts.slice(textIdx).join(',').trim();

    // 清除 ASS 样式标签 {\an8} 等
    const cleanText = subtitleText.replace(/\{[^}]*\}/g, '').replace(/\\N/g, ' ').replace(/\\n/g, ' ').trim();

    if (cleanText && start != null) {
      result.lines.push({
        text: cleanText,
        start,
        end: end || start + 2
      });
    }
  }

  result.isSynced = result.lines.length > 0;
  return result;
};

function parseASSTime(timeStr) {
  if (!timeStr) return null;
  const m = timeStr.match(/(\d+):(\d{2}):(\d{2})\.(\d{1,2})/);
  if (!m) return null;
  return (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) + (+m[4]) / 100;
}

/* ---------- SRT 字幕导出 ---------- */

/**
 * 将秒数格式化为 SRT 时间格式 HH:MM:SS,mmm
 */
function formatSRTTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

/**
 * 从 JIZURA plan 导出 SRT 字幕
 * @param {Object} plan - JIZURA 的 plan 对象
 * @param {Object} [range] - 导出范围 {from, to}（行索引），可选
 * @returns {string} SRT 格式文本
 */
J.exportSRT = (plan, range) => {
  if (!plan || !plan.lines || !plan.lines.length) return '';

  let lines = plan.lines;
  
  // 过滤范围
  if (range && range.from != null && range.to != null) {
    lines = lines.slice(range.from, range.to + 1);
  }

  // 只导出有文字的歌词行（跳过间奏等空行）
  const lyricLines = lines.filter(l => l.text && l.text.trim() && !l.interlude);

  if (!lyricLines.length) return '';

  const srtLines = [];
  let index = 1;

  for (const ln of lyricLines) {
    const start = Math.max(0, ln.start || 0);
    const end = Math.max(start + 0.5, ln.end || start + 2);
    
    srtLines.push(String(index));
    srtLines.push(`${formatSRTTime(start)} --> ${formatSRTTime(end)}`);
    srtLines.push(ln.text.trim());
    srtLines.push(''); // 空行分隔
    index++;
  }

  return srtLines.join('\n').trim() + '\n';
};

})();
