let latestScanResult = null;

// ── Error message extractor ───────────────────────────────────────────────────
// FastAPI can return `detail` as:
//   - a plain string  → "Only public GitHub URLs are supported"
//   - an array        → [{"loc": [...], "msg": "...", "type": "..."}]  (422 validation)
//   - an object       → {"detail": "..."}
function extractErrorMessage(detail) {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        // Pick the first validation error's msg field
        return detail.map(e => e.msg || JSON.stringify(e)).join('; ');
    }
    if (typeof detail === 'object' && detail !== null) {
        return detail.msg || detail.message || JSON.stringify(detail);
    }
    return String(detail);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function setRepo(url) {
    document.getElementById('repoInput').value = url;
    return false;
}

function showLoader() {
    document.getElementById('loader').classList.remove('hidden');
    document.getElementById('results').classList.add('hidden');
    document.getElementById('errorBox').classList.add('hidden');
    const btn = document.querySelector('.input-group button');
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
}

function hideLoader() {
    document.getElementById('loader').classList.add('hidden');
    const btn = document.querySelector('.input-group button');
    if (btn) { btn.disabled = false; btn.textContent = 'Analyze'; }
}

function showError(msg) {
    const box = document.getElementById('errorBox');
    box.textContent = msg;
    box.classList.remove('hidden');
}

// ── Main entry ────────────────────────────────────────────────────────────────

async function analyzeRepo() {
    const repo = document.getElementById('repoInput').value.trim();
    if (!repo) { showError('Please enter a GitHub repository URL.'); return; }

    showLoader();
    latestScanResult = null;

    let response;
    try {
        response = await fetch('/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo })
        });
    } catch (err) {
        hideLoader();
        showError('Could not reach the server. Make sure the application is running.');
        return;
    }

    // Try to parse JSON regardless of status code
    let data;
    try {
        data = await response.json();
    } catch (e) {
        hideLoader();
        showError(`Server returned an unexpected response (HTTP ${response.status}).`);
        return;
    }

    if (!response.ok || data.error || data.detail) {
        hideLoader();
        const raw = data.detail || data.error || `Server error (HTTP ${response.status}).`;
        // FastAPI validation errors return detail as an array of objects
        const msg = extractErrorMessage(raw);
        showError(`${msg}`);
        return;
    }

    latestScanResult = data;
    hideLoader();
    renderAll(data);
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function renderAll(data) {
    const info = data.scan_info;

    // ── Score gauge ──────────────────────────────────────────────────────────
    const score = info.repo_risk_score_100 || 0;
    const mean = info.weighted_mean_score_100 || 0;

    document.getElementById('scoreValue').textContent = score;
    document.getElementById('needle').style.transform =
        `rotate(${(score / 100) * 160 - 80}deg)`;

    const statusEl = document.getElementById('repoStatus');
    statusEl.textContent = info.repo_status;
    if (info.repo_status.startsWith('SAFE')) {
        statusEl.style.color = '#18b870';
    } else if (info.repo_status.startsWith('WARNING')) {
        statusEl.style.color = '#d4900a';
    } else {
        statusEl.style.color = '#e03030';
    }

    document.getElementById('meanScore').textContent =
        `Weighted Mean: ${mean} / 100`;

    // ── Summary cards ────────────────────────────────────────────────────────
    document.getElementById('totalDeps').textContent = info.total_dependencies;
    document.getElementById('vulnFound').textContent = info.vulnerable_found;
    document.getElementById('zombiesFound').textContent = info.zombies_found;

    // ── Source file pill ─────────────────────────────────────────────────────
    const sourceFile = data.source_file || 'unknown';
    const deps = data.dependencies || {};
    const depCount = Object.keys(deps).length;
    document.getElementById('sourceFilePill').innerHTML =
        `<strong>Source file:</strong>&nbsp;${sourceFile}&nbsp;&nbsp;•&nbsp;&nbsp;${depCount} packages detected`;

    // ── Sections ─────────────────────────────────────────────────────────────
    const analysis = data.analysis || [];

    renderPackageList(deps, analysis);
    renderVulnerabilityReport(data);
    renderVitalityTable(analysis);

    document.getElementById('results').classList.remove('hidden');
}

// ── Package list ──────────────────────────────────────────────────────────────

function renderPackageList(deps, analysis) {
    const container = document.getElementById('packageList');
    container.innerHTML = '';

    if (!Object.keys(deps).length) {
        container.innerHTML = '<p style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text-dim)">No packages detected.</p>';
        return;
    }

    const analysisMap = {};
    analysis.forEach(a => { analysisMap[a.package] = a; });

    Object.entries(deps).forEach(([name, version]) => {
        const entry = analysisMap[name];
        const isZombie = entry && entry.status === 'ZOMBIE';
        const isVuln   = entry && entry.cve_count && entry.cve_count > 0;
        const hasEntry = !!entry;

        let modClass  = 'pkg-chip--safe';
        let badgeHtml = '';
        if (isZombie) { modClass = 'pkg-chip--zombie'; badgeHtml = '<span class="badge zombie">ZOMBIE</span>'; }
        if (isVuln)   { modClass = 'pkg-chip--vuln';   badgeHtml = '<span class="badge vuln">VULN</span>'; }
        if (!isZombie && !isVuln && hasEntry) badgeHtml = '<span class="badge clean">OK</span>';

        const chip = document.createElement('div');
        chip.className = `pkg-chip ${modClass}`;
        chip.innerHTML = `
            <span class="pkg-name">${escHtml(name)}</span>
            <span class="pkg-ver">${escHtml(version || 'any')}</span>
            ${badgeHtml}
        `;
        container.appendChild(chip);
    });
}

// ── Vulnerability report ───────────────────────────────────────────────────────

function renderVulnerabilityReport(data) {
    const container = document.getElementById('vulnReport');
    container.innerHTML = '';

    const vulnReport = data.scan_info && data.analysis
        ? null   // we'll derive from analysis
        : null;

    // Try to get data from analysis
    const analysis = data.analysis || [];
    const vulnerable = analysis.filter(a => a.cve_details && a.cve_details.length > 0);
    const clean = analysis.filter(a => !a.cve_details || a.cve_details.length === 0);

    if (!vulnerable.length) {
        container.innerHTML = '<div class="no-vulns">[ OK ] No vulnerabilities found in any scanned package.</div>';
    } else {
        vulnerable.forEach(pkg => {
            const block = document.createElement('div');
            block.className = 'vuln-pkg-block';

            // Filter out UNKNOWN severity CVEs — they are not actionable
            const actionableCves = pkg.cve_details.filter(cve => {
                const sev = (cve.severity || '').toUpperCase();
                return sev !== 'UNKNOWN' && sev !== '';
            });

            if (!actionableCves.length) return; // skip packages with only unknown-severity vulns

            const vulnItems = actionableCves.map(cve => {
                const sev = cve.severity || 'UNKNOWN';
                return `
                    <div class="vuln-item">
                        <span class="sev-tag sev-${sev}">${sev}</span>
                        <span class="vuln-id">${escHtml(cve.id || '')}</span>
                        <span class="vuln-summary">${escHtml(cve.summary || 'No description available.')}</span>
                    </div>`;
            }).join('');

            block.innerHTML = `
                <div class="vuln-pkg-header">
                    <span class="pkg-name">${escHtml(pkg.package)}</span>
                    <span class="pkg-ver">${escHtml(pkg.version || 'any')}</span>
                    <span class="badge vuln">${actionableCves.length} CVE${actionableCves.length !== 1 ? 's' : ''}</span>
                </div>
                <div class="vuln-list">${vulnItems}</div>
            `;
            container.appendChild(block);
        });

        // If all vulnerable packages had only UNKNOWN severity, show clean message
        if (!container.querySelector('.vuln-pkg-block')) {
            container.innerHTML = '<div class="no-vulns">[ OK ] No actionable vulnerabilities found (only unclassified advisories).</div>';
        }
    }

    // Clean packages section
    if (clean.length) {
        const cleanSection = document.createElement('div');
        cleanSection.className = 'clean-section';
        cleanSection.innerHTML = `
            <div class="clean-header">[ OK ] Clean Packages (${clean.length})</div>
            <div class="clean-grid">
                ${clean.map(p => `<span class="clean-chip">${escHtml(p.package)}</span>`).join('')}
            </div>
        `;
        container.appendChild(cleanSection);
    }
}

// ── Vitality table ────────────────────────────────────────────────────────────

function renderVitalityTable(analysis) {
    const container = document.getElementById('vitalityTable');

    if (!analysis.length) {
        container.innerHTML = '<p style="color:#6b7280;font-size:13px">No vitality data available.</p>';
        return;
    }

    const rows = analysis.map(pkg => {
        const m = pkg.metrics || {};
        const score = pkg.risk_score_100 || 0;
        const color = score >= 70 ? '#ff4d4d' : score >= 40 ? '#f5c542' : '#19c37d';
        const status = pkg.status || 'ACTIVE';

        const days = m.days_since_last_commit != null ? m.days_since_last_commit + 'd' : '—';
        const issues = m.open_issues != null ? m.open_issues : '—';
        const maint = m.maintainer_count != null ? m.maintainer_count : '—';

        return `
            <tr>
                <td><span class="tbl-pkg-name">${escHtml(pkg.package)}</span></td>
                <td>${days}</td>
                <td>${issues}</td>
                <td>${maint}</td>
                <td>
                    <div class="score-bar-wrap">
                        <div class="score-bar">
                            <div class="score-bar-fill" style="width:${score}%;background:${color}"></div>
                        </div>
                        <span class="score-num" style="color:${color}">${score}</span>
                    </div>
                </td>
                <td><span class="status-tag status-${status}">${status}</span></td>
            </tr>`;
    }).join('');

    container.innerHTML = `
        <table class="vitality-table">
            <thead>
                <tr>
                    <th>Package</th>
                    <th>Last Commit</th>
                    <th>Open Issues</th>
                    <th>Maintainers</th>
                    <th>Risk Score</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

// ── Download ──────────────────────────────────────────────────────────────────

function downloadJson() {
    if (!latestScanResult) { alert('No scan result to download.'); return; }
    const blob = new Blob([JSON.stringify(latestScanResult, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'ship_happens_report.json';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Expose to HTML onclick
window.analyzeRepo = analyzeRepo;
window.setRepo = setRepo;
window.downloadJson = downloadJson;