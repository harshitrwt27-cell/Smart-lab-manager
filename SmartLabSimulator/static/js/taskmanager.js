// Task Manager page: polls the server every 2 seconds and draws the tables.

let sortBy = 'cpu';
let timer = null;

function stateBadge(state) {
    return `<span class="badge state-${esc(state)}">${esc(state)}</span>`;
}

async function refreshMachine() {
    const m = await fetchJson('/api/machine');
    $('mCpu').textContent = m.cpu_percent.toFixed(0) + '%';
    $('mRam').textContent = m.ram_percent.toFixed(0) + '%';
    $('mRamBar').style.width = m.ram_percent + '%';
    $('mProcs').textContent = m.process_count;
    $('mCores').textContent = m.cpu_cores;
}

async function refreshTasks() {
    const data = await fetchJson('/api/tasks');
    $('stateStrip').innerHTML = Object.entries(data.states)
        .map(([state, n]) => `${stateBadge(state)} <span class="muted">${n}</span>`).join(' &nbsp; ');

    if (!data.tasks.length) return;
    $('taskBody').innerHTML = data.tasks.map((t) => {
        const finished = t.state === 'TERMINATED';
        const paused = t.state === 'SUSPENDED';
        const actions = finished ? '<span class="muted">exit ' + t.exit_code + '</span>' : `
            <button class="small neutral" data-pid="${t.pid}" data-action="${paused ? 'resume' : 'suspend'}">${paused ? 'Resume' : 'Suspend'}</button>
            <button class="small warn" data-pid="${t.pid}" data-action="kill">Kill</button>
            <select class="prio" data-pid="${t.pid}" aria-label="Priority of ${t.pid}">
                ${['low', 'normal', 'high'].map((l) => `<option ${l === t.priority ? 'selected' : ''}>${l}</option>`).join('')}
            </select>`;
        return `<tr>
            <td>${t.pid}</td><td>${t.ppid}</td><td>${esc(t.name)}</td><td>${stateBadge(t.state)}</td>
            <td>${esc(t.priority)}</td><td class="num">${t.cpu.toFixed(1)}</td><td class="num">${t.memory_mb}</td>
            <td class="num">${t.threads}</td><td class="num">${t.runtime_s}s</td><td>${actions}</td></tr>`;
    }).join('');
}

async function refreshSystem() {
    const rows = await fetchJson('/api/processes?limit=12&sort=' + sortBy);
    $('sysBody').innerHTML = rows.map((p) => `<tr>
        <td>${p.pid}</td><td>${esc(p.name)}</td><td>${esc(p.status)}</td>
        <td class="num">${p.cpu.toFixed(1)}</td><td class="num">${p.memory.toFixed(2)}</td><td class="num">${p.threads}</td></tr>`).join('');
}

async function refreshTrace() {
    const calls = await fetchJson('/api/syscalls/trace?limit=30');
    if (!calls.length) return;
    $('traceBox').innerHTML = calls.map((c) => `<div class="trace-row">
        <span class="muted">${esc(c.time)}</span>
        <span class="${c.status === 'OK' ? 'ok' : 'err'}">${esc(c.syscall)}</span>
        <span>${esc(JSON.stringify(c.args))} &rarr; ${esc(JSON.stringify(c.result)).slice(0, 90)}</span>
        <span class="muted">${c.duration_ms} ms</span></div>`).join('');
}

async function refreshAll() {
    try {
        await Promise.all([refreshMachine(), refreshTasks(), refreshSystem(), refreshTrace()]);
    } catch (error) {
        console.error(error);
    }
}

async function spawnTask() {
    const msg = $('spawnMsg');
    try {
        const task = await fetchJson('/api/tasks', {
            method: 'POST',
            body: JSON.stringify({
                program: $('progSelect').value,
                seconds: Number($('secInput').value),
                user_id: Number($('userSelect').value),
                computer_id: Number($('compSelect').value),
                priority: $('prioSelect').value,
            }),
        });
        msg.textContent = 'spawn() created process ' + task.pid + ' (' + task.name + ').';
        refreshAll();
    } catch (error) {
        msg.textContent = 'spawn() failed: ' + error.message;
    }
}

async function controlTask(pid, action, level) {
    try {
        await fetchJson(`/api/tasks/${pid}/${action}`, { method: 'POST', body: JSON.stringify({ level }) });
    } catch (error) {
        $('spawnMsg').textContent = action + '() failed: ' + error.message;
    }
    refreshAll();
}

// Example arguments shown when a system call is selected.
const EXAMPLES = {
    write_file: { name: 'notes.txt', text: 'hello from the lab' },
    read_file: { name: 'notes.txt' },
    stat: { name: 'notes.txt' },
    delete_file: { name: 'notes.txt' },
    spawn: { program: 'editor-sim', seconds: 20 },
    pipe: { message: 'hello child' },
};

async function loadSyscallTable() {
    const table = await fetchJson('/api/syscalls');
    $('callSelect').innerHTML = table.map((c) =>
        `<option value="${esc(c.name)}" data-help="${esc(c.description)}">${esc(c.name)} (${esc(c.category)})</option>`).join('');
    updateCallHelp();
}

function updateCallHelp() {
    const option = $('callSelect').selectedOptions[0];
    if (!option) return;
    $('callHelp').textContent = option.dataset.help;
    $('callArgs').value = JSON.stringify(EXAMPLES[option.value] || {});
}

async function invokeCall() {
    let args;
    try {
        args = JSON.parse($('callArgs').value || '{}');
    } catch (error) {
        $('callResult').textContent = 'Arguments must be valid JSON.';
        return;
    }
    const response = await fetch('/api/syscall', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: $('callSelect').value, args }),
    });
    $('callResult').textContent = JSON.stringify(await response.json(), null, 2);
    refreshAll();
}

document.addEventListener('DOMContentLoaded', () => {
    $('spawnBtn').addEventListener('click', spawnTask);
    $('callBtn').addEventListener('click', invokeCall);
    $('callSelect').addEventListener('change', updateCallHelp);
    $('sortCpu').addEventListener('click', () => { sortBy = 'cpu'; refreshSystem(); });
    $('sortMem').addEventListener('click', () => { sortBy = 'memory'; refreshSystem(); });

    // One listener for all buttons inside the task table (they are re-drawn every refresh).
    $('taskBody').addEventListener('click', (e) => {
        const b = e.target.closest('button[data-action]');
        if (b) controlTask(b.dataset.pid, b.dataset.action);
    });
    $('taskBody').addEventListener('change', (e) => {
        if (e.target.classList.contains('prio')) controlTask(e.target.dataset.pid, 'nice', e.target.value);
    });

    loadSyscallTable();
    refreshAll();
    timer = setInterval(refreshAll, 2000);

    // Do not poll while the tab is hidden.
    document.addEventListener('visibilitychange', () => {
        clearInterval(timer);
        if (!document.hidden) { refreshAll(); timer = setInterval(refreshAll, 2000); }
    });
});
