// Real system telemetry: values come from the local backend; unavailable metrics stay unavailable.
(function () {
  'use strict';

  let telemetryBusy = false;

  const iconCache = {};
  async function loadInlineIcons() {
    const icons = document.querySelectorAll('[data-icon]');
    for (const el of icons) {
      const name = el.dataset.icon;
      if (!name) continue;
      if (!iconCache[name]) {
        try {
          const res = await fetch('/icons/' + encodeURIComponent(name) + '.svg', { cache: 'force-cache' });
          if (!res.ok) continue;
          const text = await res.text();
          const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
          const svg = doc.querySelector('svg');
          if (svg) {
            svg.setAttribute('width', '18');
            svg.setAttribute('height', '18');
            svg.setAttribute('aria-hidden', 'true');
            iconCache[name] = svg;
          }
        } catch (_) { continue; }
      }
      if (iconCache[name]) {
        el.replaceChildren(iconCache[name].cloneNode(true));
      }
    }
  }
  document.addEventListener('DOMContentLoaded', loadInlineIcons);

  const HISTORY_MAX = 60;
  const history = { cpu: [], ram: [], gpu: [] };
  let currentChart = 'cpu';

  function setConnectionStatus(online, port) {
    const server = document.getElementById('server-status');
    const serverDot = document.getElementById('server-running-dot');
    const apiDot = document.getElementById('api-connection-dot');
    [serverDot, apiDot].forEach(dot => {
      if (!dot) return;
      dot.classList.toggle('is-online', online);
      dot.classList.toggle('is-offline', !online);
    });
    if (server) server.textContent = online ? 'Работает · :' + (port || window.location.port || '8765') : 'Нет соединения';
    const api = document.getElementById('footer-status');
    if (api) api.textContent = online ? 'API подключён' : 'API недоступен';
  }

  async function fetchStats() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);
    try {
      const response = await fetch('/api/system/stats', {
        cache: 'no-store',
        signal: controller.signal
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      setConnectionStatus(true, window.location.port || '8765');
      return data;
    } catch (error) {
      setConnectionStatus(false);
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  function setBar(id, percent) {
    const bar = document.getElementById(id);
    if (!bar) return;
    const track = bar.parentElement;
    const valid = Number.isFinite(percent);
    bar.style.width = valid ? Math.min(100, Math.max(0, percent)) + '%' : '0%';
    track.classList.toggle('warn', valid && percent >= 70 && percent < 90);
    track.classList.toggle('danger', valid && percent >= 90);
    track.classList.toggle('unavailable', !valid);
  }

  function displayPercent(value) {
    return Number.isFinite(value) ? Math.round(value) + '%' : '—';
  }

  function displayGb(value, digits) {
    return Number.isFinite(value) ? value.toFixed(digits) : '—';
  }

  function renderState(stats, error) {
    const state = document.getElementById('sysmon-state');
    if (!state) return;
    if (error) {
      state.textContent = 'нет данных от локального сервера';
      state.title = String(error.message || error);
      return;
    }
    const time = stats.timestamp ? new Date(stats.timestamp) : new Date();
    const unavailable = [stats.cpu, stats.ram, stats.gpu].filter(item => !item || item.available === false).length;
    state.textContent = 'обновлено ' + time.toLocaleTimeString('ru-RU') + (unavailable ? ' · часть данных недоступна' : '');
    state.title = 'Данные получены с локального сервера';
  }

  function updateMetric(key, percent) {
    if (Number.isFinite(percent)) {
      history[key].push(percent);
      if (history[key].length > HISTORY_MAX) history[key].shift();
    }
  }

  function render(stats) {
    updateMetric('cpu', stats.cpu && stats.cpu.available ? stats.cpu.percent : null);
    updateMetric('ram', stats.ram && stats.ram.available ? stats.ram.percent : null);
    updateMetric('gpu', stats.gpu && stats.gpu.available ? stats.gpu.percent : null);

    const cpu = stats.cpu || {};
    const cpuVal = document.getElementById('sysmon-cpu-val');
    const cpuName = document.getElementById('sysmon-cpu-name');
    if (cpuVal) cpuVal.textContent = cpu.available ? displayPercent(cpu.percent) : '—';
    if (cpuName) cpuName.textContent = (cpu.name || 'Процессор') + ' · ' + (cpu.available ? displayPercent(cpu.percent) + ' загрузки' : 'загрузка недоступна');
    setBar('sysmon-cpu-bar', cpu.available ? cpu.percent : null);

    const ram = stats.ram || {};
    const ramVal = document.getElementById('sysmon-ram-val');
    const ramDetail = document.getElementById('sysmon-ram-detail');
    if (ramVal) ramVal.textContent = ram.available ? displayPercent(ram.percent) : '—';
    if (ramDetail) ramDetail.textContent = ram.available ? displayGb(ram.used, 1) + ' ГБ из ' + displayGb(ram.total, 1) + ' ГБ' : 'Данные памяти недоступны';
    setBar('sysmon-ram-bar', ram.available ? ram.percent : null);

    const gpu = stats.gpu || {};
    const gpuVal = document.getElementById('sysmon-gpu-val');
    const gpuDetail = document.getElementById('sysmon-gpu-detail');
    if (gpuVal) gpuVal.textContent = gpu.available ? displayPercent(gpu.percent) : '—';
    if (gpuDetail) gpuDetail.textContent = gpu.available
      ? gpu.name + ' · VRAM ' + displayGb(gpu.vramUsed, 1) + ' / ' + displayGb(gpu.vramTotal, 1) + ' ГБ'
      : gpu.pending === true
        ? 'Ожидание данных…'
        : 'Данные GPU недоступны (требуется nvidia-smi)';
    setBar('sysmon-gpu-bar', gpu.pending === true ? 0 : (gpu.available ? gpu.percent : null));

    // Компактная панель показывает только CPU, RAM и GPU; сбор дисков отключён.


    renderState(stats, null);
    const modal = document.getElementById('sysmon-chart-modal');
    if (modal && !modal.hidden) drawChart(currentChart);
  }

  function drawChart(kind) {
    const data = history[kind];
    if (!data || !data.length) return;
    const width = 600, height = 200, padding = 10;
    const stepX = (width - padding * 2) / (HISTORY_MAX - 1);
    const offset = HISTORY_MAX - data.length;
    const points = data.map((value, index) => {
      const x = padding + (offset + index) * stepX;
      const y = height - padding - (value / 100) * (height - padding * 2);
      return [x, y];
    });
    const line = 'M ' + points.map((point) => point[0].toFixed(1) + ' ' + point[1].toFixed(1)).join(' L ');
    const area = line + ' L ' + (padding + (HISTORY_MAX - 1) * stepX).toFixed(1) + ' ' + (height - padding) + ' L ' + padding + ' ' + (height - padding) + ' Z';
    const lineEl = document.getElementById('sysmon-chart-line');
    const areaEl = document.getElementById('sysmon-chart-area');
    const dotEl = document.getElementById('sysmon-chart-dot');
    if (lineEl) lineEl.setAttribute('d', line);
    if (areaEl) areaEl.setAttribute('d', area);
    if (dotEl) {
      const last = points[points.length - 1];
      dotEl.setAttribute('cx', last[0]);
      dotEl.setAttribute('cy', last[1]);
    }
    let grid = '';
    for (let i = 0; i <= 4; i++) {
      const y = padding + i * (height - padding * 2) / 4;
      grid += '<line class="sysmon-grid-line" x1="' + padding + '" y1="' + y + '" x2="' + (width - padding) + '" y2="' + y + '"/>';
      grid += '<text class="sysmon-axis-label" x="' + (width - padding + 4) + '" y="' + (y + 3) + '">' + (100 - i * 25) + '%</text>';
    }
    const gridEl = document.getElementById('sysmon-chart-grid');
    if (gridEl) gridEl.innerHTML = grid;
    const now = data[data.length - 1];
    const average = data.reduce((sum, value) => sum + value, 0) / data.length;
    const maximum = Math.max.apply(null, data);
    const nowEl = document.getElementById('sysmon-chart-now');
    const averageEl = document.getElementById('sysmon-chart-avg');
    const maxEl = document.getElementById('sysmon-chart-max');
    if (nowEl) nowEl.textContent = Math.round(now) + '%';
    if (averageEl) averageEl.textContent = Math.round(average) + '%';
    if (maxEl) maxEl.textContent = Math.round(maximum) + '%';
  }

  const chartTitles = {
    cpu: 'Процессор · история нагрузки',
    ram: 'Память · история нагрузки',
    gpu: 'Видеокарта · история нагрузки'
  };

  function bind() {
    document.querySelectorAll('[data-sysmon-chart]').forEach((card) => {
      card.addEventListener('click', () => {
        currentChart = card.dataset.sysmonChart;
        const title = document.getElementById('sysmon-chart-title');
        if (title) title.textContent = chartTitles[currentChart];
        const modal = document.getElementById('sysmon-chart-modal');
        if (modal) modal.hidden = false;
        drawChart(currentChart);
      });
    });
    const close = document.getElementById('sysmon-chart-close');
    if (close) close.addEventListener('click', () => {
      const modal = document.getElementById('sysmon-chart-modal');
      if (modal) modal.hidden = true;
    });
  }

  async function tick() {
    if (telemetryBusy) return;
    telemetryBusy = true;
    try {
      try {
        render(await fetchStats());
      } catch (error) {
        renderState(null, error);
        ['cpu', 'ram', 'gpu'].forEach(key => {
          const value = document.getElementById('sysmon-' + key + '-val');
          if (value) value.textContent = '—';
          setBar('sysmon-' + key + '-bar', null);
        });
        const cpuName = document.getElementById('sysmon-cpu-name');
        const ramDetail = document.getElementById('sysmon-ram-detail');
        const gpuDetail = document.getElementById('sysmon-gpu-detail');
        if (cpuName) cpuName.textContent = 'Нет соединения с локальным сервером';
        if (ramDetail) ramDetail.textContent = 'Данные памяти недоступны';
        if (gpuDetail) gpuDetail.textContent = 'Данные GPU недоступны';
        // В компактной телеметрии отображаются только CPU, RAM и GPU.
      }
      const modal = document.getElementById('sysmon-chart-modal');
      if (modal && !modal.hidden) drawChart(currentChart);
    } finally {
      telemetryBusy = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    bind();
    tick();
    // Обновляем компактную телеметрию раз в 2 секунды, чтобы снизить нагрузку на сбор системных данных.
    setInterval(tick, 2000);
  });
})();