// Reports page: draws each report returned by /api/reports/<name> as a table.

function toTable(rows) {
    if (!rows.length) return '<p class="muted">No data yet. Use the Task Manager and Bookings first.</p>';
    const cols = Object.keys(rows[0]);
    return '<table><thead><tr>' + cols.map((c) => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map((r) => '<tr>' + cols.map((c) => `<td>${esc(r[c])}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>';
}

document.addEventListener('DOMContentLoaded', async () => {
    for (const name of ['syscalls', 'users', 'computers', 'tasks', 'audit']) {
        try {
            $('rep-' + name).innerHTML = toTable(await fetchJson('/api/reports/' + name));
        } catch (error) {
            $('rep-' + name).textContent = 'Could not load: ' + error.message;
        }
    }
});
