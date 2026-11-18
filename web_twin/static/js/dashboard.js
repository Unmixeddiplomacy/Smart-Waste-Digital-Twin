/**
 * Dashboard Logic — Smart Waste Sorting Digital Twin
 * Connects WebSocket events and REST APIs to DOM updates, Chart.js, and the 3D scene.
 */

// 1. Constants
const BIN_COLORS = {
  cardboard: '#8B4513',
  glass: '#00ff88',
  metal: '#cccccc',
  paper: '#ffff00',
  plastic: '#0088ff',
  trash: '#ff4444'
};

// Track active waste animation & hide timer so rapid events stay clean
let hideWasteTimer = null;
let wasteAnimFrame = null;

const BIN_TARGET_X_NORM = {
  cardboard: (-3 + 4.5) / 9,
  glass: (-1 + 4.5) / 9,
  metal: (1 + 4.5) / 9,
  paper: (3 + 4.5) / 9,
  plastic: (1 + 4.5) / 9,
  trash: (-1 + 4.5) / 9
};

// 2. Chart.js Setup
let sortingChart = null;

function initChart() {
  const canvas = document.getElementById('sorting-chart');
  if (!canvas || typeof Chart === 'undefined') {
    console.warn('Chart.js or #sorting-chart canvas unavailable.');
    return;
  }

  const ctx = canvas.getContext('2d');
  sortingChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Total Sorted',
          data: [],
          borderColor: '#00ff88',
          backgroundColor: 'rgba(0, 255, 136, 0.12)',
          borderWidth: 2,
          pointRadius: 2,
          pointBackgroundColor: '#00ff88',
          fill: true,
          tension: 0.25
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 2.2,
      animation: false,
      plugins: {
        legend: {
          display: true,
          labels: {
            color: '#888'
          }
        }
      },
      scales: {
        x: {
          ticks: {
            color: '#888',
            maxTicksLimit: 8
          },
          grid: {
            color: '#333'
          }
        },
        y: {
          beginAtZero: true,
          ticks: {
            color: '#888',
            precision: 0
          },
          grid: {
            color: '#333'
          }
        }
      }
    }
  });
}

// Initialize chart immediately (script loads at end of body)
initChart();

// 3. WebSocket Event Handlers
if (typeof wsClient !== 'undefined') {
  wsClient.on('sort_event', function (data) {
    if (!data) return;

    // Update live detection log
    addDetectionLog(data);

    // Update 3D scene — smoothly move waste down conveyor toward target bin
    if (window.setWasteColor) {
      window.setWasteColor(data.detected_class);
    }

    if (wasteAnimFrame) {
      cancelAnimationFrame(wasteAnimFrame);
      wasteAnimFrame = null;
    }
    if (hideWasteTimer) {
      clearTimeout(hideWasteTimer);
      hideWasteTimer = null;
    }

    const targetNorm = BIN_TARGET_X_NORM[data.assigned_bin] !== undefined
      ? BIN_TARGET_X_NORM[data.assigned_bin]
      : 0.5;
    const durationMs = 1000;
    const startTime = performance.now();

    function stepWaste(now) {
      const progress = Math.min((now - startTime) / durationMs, 1);
      if (window.updateWastePosition) {
        window.updateWastePosition(progress * targetNorm);
      }
      if (progress < 1) {
        wasteAnimFrame = requestAnimationFrame(stepWaste);
      } else {
        wasteAnimFrame = null;
        if (window.animateGate && data.assigned_bin) {
          window.animateGate(data.assigned_bin);
        }
        hideWasteTimer = setTimeout(function () {
          if (window.hideWaste) {
            window.hideWaste();
          }
          hideWasteTimer = null;
        }, 500);
      }
    }

    if (typeof requestAnimationFrame === 'function' && window.updateWastePosition) {
      wasteAnimFrame = requestAnimationFrame(stepWaste);
    } else {
      if (window.updateWastePosition) window.updateWastePosition(targetNorm);
      if (window.animateGate && data.assigned_bin) window.animateGate(data.assigned_bin);
      hideWasteTimer = setTimeout(function () {
        if (window.hideWaste) window.hideWaste();
        hideWasteTimer = null;
      }, 1500);
    }
  });

  wsClient.on('stats_update', function (data) {
    if (!data) return;
    updateStatsCards(data);
    updateChart(data);
  });

  wsClient.on('bins_update', function (data) {
    if (!Array.isArray(data)) return;
    updateBinBars(data);
    updateBin3D(data);
  });

  wsClient.on('init', function (data) {
    if (!data) return;
    if (Array.isArray(data.bins)) {
      updateBinBars(data.bins);
      updateBin3D(data.bins);
    }
    if (data.stats) {
      updateStatsCards(data.stats);
    }
  });

  wsClient.on('connect', function () {
    addAlert('Connected to server', 'info');
  });

  wsClient.on('close', function () {
    addAlert('Lost connection to server', 'error');
  });
}

// 4. UI Update Functions

function addAlert(message, severity = 'info') {
  const list = document.getElementById('alerts-list');
  if (!list) return;

  const item = document.createElement('div');
  item.className = `alert-item alert-${severity}`;
  item.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  list.prepend(item);

  // Cap alerts at 20 entries
  while (list.children.length > 20) {
    list.removeChild(list.lastChild);
  }
}

function addDetectionLog(data) {
  const log = document.getElementById('detection-log');
  if (!log) return;

  const detectedClass = (data.detected_class || 'unknown').toLowerCase();
  const assignedBin = data.assigned_bin || detectedClass;
  const confidencePct = ((Number(data.confidence) || 0) * 100).toFixed(1);
  const time = new Date().toLocaleTimeString();
  const color = BIN_COLORS[detectedClass] || '#fff';
  const icon = data.success ? '✅' : '❌';

  const entry = document.createElement('div');
  entry.className = 'detection-entry';
  entry.innerHTML =
    `<span style="color:${color}">[${time}] ${icon} ${detectedClass.toUpperCase()}</span>` +
    ` → Bin: ${assignedBin} (${confidencePct}%)`;

  log.prepend(entry);

  // Keep max 50 entries
  while (log.children.length > 50) {
    log.removeChild(log.lastChild);
  }
}

function updateStatsCards(stats) {
  if (!stats) return;
  const totalEl = document.getElementById('val-total');
  const accEl = document.getElementById('val-accuracy');
  const rateEl = document.getElementById('val-rate');

  if (totalEl) {
    totalEl.textContent = stats.total_sorted || 0;
  }
  if (accEl) {
    accEl.textContent = ((stats.accuracy || 0) * 100).toFixed(1) + '%';
  }
  if (rateEl) {
    rateEl.textContent = (stats.sorting_rate || 0).toFixed(1);
  }
}

function updateBin3D(bins) {
  if (!Array.isArray(bins) || !window.updateBinFill) return;
  for (const bin of bins) {
    const pct = Math.min(Math.max(Number(bin.fill_percentage) || 0, 0), 100);
    window.updateBinFill(bin.bin_name, pct);
  }
}

function updateBinBars(bins) {
  const container = document.getElementById('bin-bars');
  if (!container || !Array.isArray(bins)) return;

  // Build HTML once instead of mutating innerHTML inside a loop
  const htmlParts = [];
  for (const bin of bins) {
    const color = BIN_COLORS[bin.bin_name] || '#888';
    const pct = Math.min(Math.max(Number(bin.fill_percentage) || 0, 0), 100);
    htmlParts.push(
      `<div class="bin-bar-container">` +
      `<div class="bin-bar-label">` +
      `<span>${bin.bin_name.toUpperCase()}</span>` +
      `<span>${bin.item_count}/${bin.capacity} (${pct.toFixed(0)}%)</span>` +
      `</div>` +
      `<div class="bin-bar-outer">` +
      `<div class="bin-bar-inner" style="width:${pct}%; background:${color}"></div>` +
      `</div>` +
      `</div>`
    );

    if (window.updateBinFill) {
      window.updateBinFill(bin.bin_name, pct);
    }

    // Bin-full alert when fill reaches 90% or more
    if (pct >= 90) {
      addAlert(`Bin ${bin.bin_name} is ${pct.toFixed(0)}% full!`, 'warning');
    }
  }

  container.innerHTML = htmlParts.join('');
}

function updateChart(stats) {
  if (!sortingChart || !stats) return;

  const now = new Date().toLocaleTimeString();
  sortingChart.data.labels.push(now);
  sortingChart.data.datasets[0].data.push(stats.total_sorted || 0);

  // Keep last 30 points
  if (sortingChart.data.labels.length > 30) {
    sortingChart.data.labels.shift();
    sortingChart.data.datasets[0].data.shift();
  }

  sortingChart.update('none');
}

// 5. Control Functions (called by HTML buttons)

async function startSimulation() {
  const startBtn = document.getElementById('btn-start-sim');
  const stopBtn = document.getElementById('btn-stop-sim');
  const controls = document.getElementById('controls');
  if (controls) controls.classList.add('loading');
  try {
    const res = await fetch('/api/simulate/start', { method: 'POST' });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;
    addAlert('Simulation started', 'info');
  } catch (err) {
    console.error('API error:', err);
    addAlert(`Failed to start simulation: ${err.message}`, 'error');
  } finally {
    if (controls) controls.classList.remove('loading');
  }
}

async function stopSimulation() {
  const startBtn = document.getElementById('btn-start-sim');
  const stopBtn = document.getElementById('btn-stop-sim');
  const controls = document.getElementById('controls');
  if (controls) controls.classList.add('loading');
  try {
    const res = await fetch('/api/simulate/stop', { method: 'POST' });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    addAlert('Simulation stopped', 'info');
  } catch (err) {
    console.error('API error:', err);
    addAlert(`Failed to stop simulation: ${err.message}`, 'error');
  } finally {
    if (controls) controls.classList.remove('loading');
  }
}

async function resetSystem() {
  if (!confirm('Reset all data?')) return;
  const controls = document.getElementById('controls');
  if (controls) controls.classList.add('loading');
  try {
    const res = await fetch('/api/reset', { method: 'POST' });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    location.reload();
  } catch (err) {
    console.error('API error:', err);
    addAlert(`Failed to reset system: ${err.message}`, 'error');
    if (controls) controls.classList.remove('loading');
  }
}

// 6. Initial Data Load
window.addEventListener('DOMContentLoaded', async function () {
  const dashboard = document.getElementById('dashboard-panel');
  if (dashboard) dashboard.classList.add('loading');
  try {
    const [statsRes, binsRes] = await Promise.all([
      fetch('/api/stats').then(function (r) {
        if (!r.ok) throw new Error(`Stats HTTP ${r.status}`);
        return r.json();
      }),
      fetch('/api/bins').then(function (r) {
        if (!r.ok) throw new Error(`Bins HTTP ${r.status}`);
        return r.json();
      })
    ]);
    updateStatsCards(statsRes);
    updateBinBars(binsRes);
  } catch (err) {
    console.error('API error:', err);
    addAlert(`Failed to load initial data: ${err.message}`, 'error');
  } finally {
    if (dashboard) dashboard.classList.remove('loading');
  }
});
