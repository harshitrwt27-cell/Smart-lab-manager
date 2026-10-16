// ---------------------------------------------------------------------------
// Shared helpers (used by every page)
// ---------------------------------------------------------------------------
async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || 'Request failed (' + response.status + ')');
    }
    return data;
}

// Process names and file names come from outside, so never put them into HTML raw.
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadSystemSummary() {
    if (!$('totalComputers')) return;
    const data = await fetchJson('/api/system');
    $('totalComputers').textContent = data.total_computers;
    $('availableComputers').textContent = data.available_computers;
    $('inUseComputers').textContent = data.in_use_computers;
    $('maintenanceComputers').textContent = data.maintenance_computers;
}

async function loadProcesses() {
    const list = $('processList');
    if (!list) return;
    const processes = await fetchJson('/api/processes?limit=10');
    list.innerHTML = processes.map((p) => `
        <tr>
            <td>${p.pid}</td>
            <td>${esc(p.name)}</td>
            <td>${p.cpu.toFixed(1)}</td>
            <td>${p.memory.toFixed(2)}</td>
        </tr>`).join('');
}

// "P1=5/0/2,P2=3" -> [{pid:'P1', burst:5, arrival:0, priority:2}, ...]
function parseProcesses(raw) {
    return raw.split(',').map((part) => {
        const [pid, rest] = part.split('=');
        const [burst, arrival, priority] = (rest || '').split('/').map((v) => Number(v));
        return { pid: pid.trim(), burst, arrival: arrival || 0, priority: priority || 0 };
    });
}

function drawGantt(gantt) {
    const end = gantt.length ? gantt[gantt.length - 1].end : 1;
    const bars = gantt.map((g) =>
        `<div class="gantt-bar" style="width:${((g.end - g.start) / end) * 100}%" title="${g.start} to ${g.end}">${esc(g.pid)}</div>`
    ).join('');
    const marks = gantt.map((g) =>
        `<span style="width:${((g.end - g.start) / end) * 100}%">${g.start}</span>`
    ).join('') + `<span>${end}</span>`;
    return `<div class="gantt">${bars}</div><div class="gantt-scale">${marks}</div>`;
}

async function simulateScheduling() {
    const resultBox = $('schedulingResult');
    try {
        const res = await fetchJson('/api/scheduling', {
            method: 'POST',
            body: JSON.stringify({
                processes: parseProcesses($('processInput').value.trim()),
                algorithm: $('algoSelect').value,
                quantum: Number($('quantumInput').value) || 2,
            }),
        });
        $('ganttBox').innerHTML = drawGantt(res.gantt);
        resultBox.textContent = JSON.stringify({
            average_waiting: res.average_waiting,
            average_turnaround: res.average_turnaround,
            average_response: res.average_response,
            processes: res.processes,
        }, null, 2);
    } catch (error) {
        resultBox.textContent = 'Error: ' + error.message;
    }
}

async function simulateMemory() {
    const resultBox = $('memoryResult');
    try {
        const [blocksText, processesText] = $('memoryInput').value.split('/');
        const toNumbers = (t) => t.split(',').map((v) => Number(v.trim()));
        const res = await fetchJson('/api/memory', {
            method: 'POST',
            body: JSON.stringify({
                strategy: $('strategySelect').value,
                blocks: toNumbers(blocksText),
                processes: toNumbers(processesText),
            }),
        });
        resultBox.textContent = JSON.stringify(res, null, 2);
    } catch (error) {
        resultBox.textContent = 'Error: ' + error.message + ' (format: 100,500 / 212,417)';
    }
}

async function simulatePaging() {
    const resultBox = $('pagingResult');
    try {
        const res = await fetchJson('/api/paging', {
            method: 'POST',
            body: JSON.stringify({
                algorithm: $('pagingAlgo').value,
                frames: Number($('framesInput').value),
                pages: $('pagesInput').value.split(',').map((v) => Number(v.trim())),
            }),
        });
        const lines = res.steps.map((s) =>
            `page ${s.page}  [${s.memory.join(', ')}]  ${s.fault ? 'FAULT' : 'hit'}`);
        resultBox.textContent = lines.join('\n') +
            `\n\npage faults: ${res.page_faults}   hit ratio: ${res.hit_ratio}`;
    } catch (error) {
        resultBox.textContent = 'Error: ' + error.message;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadSystemSummary();
    loadProcesses();

    const wire = (id, fn) => { if ($(id)) $(id).addEventListener('click', fn); };
    wire('scheduleBtn', simulateScheduling);
    wire('memoryBtn', simulateMemory);
    wire('pagingBtn', simulatePaging);

    if ($('processList')) setInterval(loadProcesses, 3000);
});
