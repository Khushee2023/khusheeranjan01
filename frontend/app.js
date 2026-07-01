// State Management
const state = {
    files: { csv: [], json: [], notes: [], resumes: [] },
    candidates: [],
    projectedOutput: [],
    selectedCandidateId: null,
    activeTab: 'dashboard', // dashboard, schema, files
    lastRunSuccess: false
};

// DOM Elements
const DOM = {
    btnNavDashboard: document.getElementById('btn-nav-dashboard'),
    btnNavSchema: document.getElementById('btn-nav-schema'),
    btnNavFiles: document.getElementById('btn-nav-files'),
    
    viewDashboard: document.getElementById('view-dashboard'),
    viewSchema: document.getElementById('view-schema'),
    viewFiles: document.getElementById('view-files'),
    
    btnResetData: document.getElementById('btn-reset-data'),
    btnRunPipeline: document.getElementById('btn-run-pipeline'),
    btnApplySchema: document.getElementById('btn-apply-schema'),
    btnCopyJson: document.getElementById('btn-copy-json'),
    btnSelectFiles: document.getElementById('btn-select-files'),
    themeToggleBtn: document.getElementById('theme-toggle-btn'),
    
    metricSources: document.getElementById('metric-sources'),
    metricCandidates: document.getElementById('metric-candidates'),
    metricTrust: document.getElementById('metric-trust'),
    metricErrors: document.getElementById('metric-errors'),
    
    candidateSearch: document.getElementById('candidate-search'),
    candidatesList: document.getElementById('candidates-list-items'),
    candidateDetailsPane: document.getElementById('candidate-details-pane'),
    detailsEmptyState: document.getElementById('details-empty-state'),
    profileContent: document.getElementById('profile-content'),
    
    profAvatar: document.getElementById('prof-avatar'),
    profName: document.getElementById('prof-name'),
    profHeadline: document.getElementById('prof-headline'),
    profLocation: document.getElementById('prof-location'),
    profTrustScore: document.getElementById('prof-trust-score'),
    profTrustBadge: document.getElementById('prof-trust-badge'),
    profLinks: document.getElementById('prof-links'),
    profTimelineExperience: document.getElementById('prof-timeline-experience'),
    profGridEducation: document.getElementById('prof-grid-education'),
    profSkillsContainer: document.getElementById('prof-skills-container'),
    profEmailsList: document.getElementById('prof-emails-list'),
    profPhonesList: document.getElementById('prof-phones-list'),
    profProvenanceTbody: document.getElementById('prof-provenance-tbody'),
    linkageSourcesList: document.getElementById('linkage-sources-list'),
    linkageCenterName: document.getElementById('linkage-center-name'),
    
    fileDropzone: document.getElementById('file-dropzone'),
    fileInputHidden: document.getElementById('file-input-hidden'),
    uploadProgressContainer: document.getElementById('upload-progress-container'),
    
    fileListCsv: document.getElementById('file-list-csv'),
    fileListJson: document.getElementById('file-list-json'),
    fileListNotes: document.getElementById('file-list-notes'),
    fileListResumes: document.getElementById('file-list-resumes'),
    
    schemaJsonOutput: document.getElementById('schema-json-output'),
    toastContainer: document.getElementById('toast-container')
};

// Initial Setup
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupTheme();
    setupFileUpload();
    setupEventListeners();
    fetchStatus();
});

// Theme Setup
function setupTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.body.classList.remove('dark-theme');
        document.body.classList.add('light-theme');
        DOM.themeToggleBtn.querySelector('span').textContent = 'Light Mode';
        DOM.themeToggleBtn.querySelector('i').className = 'fa-solid fa-sun';
    }
    
    DOM.themeToggleBtn.addEventListener('click', () => {
        if (document.body.classList.contains('dark-theme')) {
            document.body.classList.remove('dark-theme');
            document.body.classList.add('light-theme');
            DOM.themeToggleBtn.querySelector('span').textContent = 'Light Mode';
            DOM.themeToggleBtn.querySelector('i').className = 'fa-solid fa-sun';
            localStorage.setItem('theme', 'light');
        } else {
            document.body.classList.remove('light-theme');
            document.body.classList.add('dark-theme');
            DOM.themeToggleBtn.querySelector('span').textContent = 'Dark Mode';
            DOM.themeToggleBtn.querySelector('i').className = 'fa-solid fa-moon';
            localStorage.setItem('theme', 'dark');
        }
    });
}

// Navigation Handling
function setupNavigation() {
    const tabs = [
        { btn: DOM.btnNavDashboard, view: DOM.viewDashboard, name: 'dashboard' },
        { btn: DOM.btnNavSchema, view: DOM.viewSchema, name: 'schema' },
        { btn: DOM.btnNavFiles, view: DOM.viewFiles, name: 'files' }
    ];
    
    tabs.forEach(tab => {
        tab.btn.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Toggle active buttons
            tabs.forEach(t => t.btn.classList.remove('active'));
            tab.btn.classList.add('active');
            
            // Toggle active views
            tabs.forEach(t => t.view.classList.add('hidden'));
            tab.view.classList.remove('hidden');
            
            state.activeTab = tab.name;
        });
    });
    
    // Candidate details tabs (within dashboard view)
    const profTabButtons = document.querySelectorAll('.profile-tab');
    const profTabPanes = document.querySelectorAll('.tab-pane');
    
    profTabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            profTabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const targetTab = btn.getAttribute('data-tab');
            profTabPanes.forEach(pane => {
                pane.classList.remove('active');
                if (pane.id === targetTab) {
                    pane.classList.add('active');
                }
            });
        });
    });
}

// Event Listeners setup
function setupEventListeners() {
    DOM.btnResetData.addEventListener('click', resetData);
    DOM.btnRunPipeline.addEventListener('click', () => runPipeline());
    DOM.btnApplySchema.addEventListener('click', applyCustomSchema);
    DOM.btnCopyJson.addEventListener('click', copyJsonOutput);
    DOM.candidateSearch.addEventListener('input', filterCandidatesList);
}

// Drag and Drop Upload Setup
function setupFileUpload() {
    DOM.btnSelectFiles.addEventListener('click', () => {
        DOM.fileInputHidden.click();
    });
    
    DOM.fileInputHidden.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
    
    // Drag activities
    ['dragenter', 'dragover'].forEach(eventName => {
        DOM.fileDropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            DOM.fileDropzone.classList.add('active');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        DOM.fileDropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            DOM.fileDropzone.classList.remove('active');
        }, false);
    });
    
    DOM.fileDropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }, false);
}

// Upload Handling
async function handleFiles(files) {
    if (!files.length) return;
    
    showToast(`Uploading ${files.length} file(s)...`, 'info');
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const progressItem = document.createElement('div');
        progressItem.className = 'progress-item';
        progressItem.innerHTML = `<span>${file.name}</span><span class="progress-status"><i class="fa-solid fa-spinner fa-spin"></i></span>`;
        DOM.uploadProgressContainer.appendChild(progressItem);
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            
            if (response.ok) {
                progressItem.querySelector('.progress-status').className = 'progress-status progress-success';
                progressItem.querySelector('.progress-status').innerHTML = '<i class="fa-solid fa-circle-check"></i> Uploaded';
                showToast(`Uploaded ${file.name}`, 'success');
            } else {
                throw new Error(result.detail || 'Upload failed');
            }
        } catch (error) {
            progressItem.querySelector('.progress-status').className = 'progress-status progress-error';
            progressItem.querySelector('.progress-status').innerHTML = '<i class="fa-solid fa-circle-xmark"></i> Failed';
            showToast(`Error uploading ${file.name}: ${error.message}`, 'error');
        }
        
        // Remove after 5 seconds
        setTimeout(() => progressItem.remove(), 5000);
    }
    
    fetchStatus();
}

// Fetch files list and status
async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        if (response.ok) {
            state.files = data.files;
            renderFilesList();
            updateMetricsPlaceholder();
        }
    } catch (err) {
        console.error('Error fetching status:', err);
    }
}

// Update basic stats before running pipeline
function updateMetricsPlaceholder() {
    const totalFilesCount = state.files.csv.length + state.files.json.length + state.files.notes.length + state.files.resumes.length;
    DOM.metricSources.textContent = `0 / ${totalFilesCount}`;
}

// Render files categories list
function renderFilesList() {
    const renderCol = (list, container, iconClass) => {
        container.innerHTML = '';
        if (!list.length) {
            container.innerHTML = '<li class="text-muted font-normal">No files</li>';
            return;
        }
        list.forEach(item => {
            const li = document.createElement('li');
            li.innerHTML = `<i class="${iconClass}"></i> <span>${item}</span>`;
            container.appendChild(li);
        });
    };
    
    renderCol(state.files.csv, DOM.fileListCsv, 'fa-solid fa-table');
    renderCol(state.files.json, DOM.fileListJson, 'fa-solid fa-file-code');
    renderCol(state.files.notes, DOM.fileListNotes, 'fa-solid fa-file-lines');
    renderCol(state.files.resumes, DOM.fileListResumes, 'fa-solid fa-file-pdf');
}

// Execute Pipeline
async function runPipeline(customConfig = null) {
    showToast('Running Candidate Data Transformer Pipeline...', 'info');
    DOM.btnRunPipeline.disabled = true;
    DOM.btnRunPipeline.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing...';
    
    try {
        const options = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        };
        if (customConfig) {
            options.body = JSON.stringify(customConfig);
        }
        
        const response = await fetch('/api/run', options);
        const data = await response.json();
        
        if (response.ok) {
            state.candidates = data.candidates;
            state.projectedOutput = data.projected_output;
            state.lastRunSuccess = true;
            
            // Update stats
            const totalFiles = state.files.csv.length + state.files.json.length + state.files.notes.length + state.files.resumes.length;
            DOM.metricSources.textContent = `${data.sources_processed.length} / ${totalFiles}`;
            DOM.metricCandidates.textContent = data.candidates.length;
            DOM.metricErrors.textContent = data.errors.length;
            
            // Calculate avg trust score
            let totalTrust = 0;
            data.candidates.forEach(c => totalTrust += c.overall_confidence);
            const avgTrust = data.candidates.length ? Math.round((totalTrust / data.candidates.length) * 100) : 0;
            DOM.metricTrust.textContent = `${avgTrust}%`;
            
            showToast('Pipeline run completed successfully!', 'success');
            renderCandidatesList();
            
            // Update schema output
            DOM.schemaJsonOutput.textContent = JSON.stringify(data.projected_output, null, 2);
            
            if (data.errors.length) {
                showToast(`Encountered ${data.errors.length} non-fatal extraction warnings. Check metrics.`, 'warning');
            }
        } else {
            throw new Error(data.detail || 'Pipeline run failed');
        }
    } catch (error) {
        showToast(error.message, 'error');
        DOM.metricErrors.textContent = 'Err';
    } finally {
        DOM.btnRunPipeline.disabled = false;
        DOM.btnRunPipeline.innerHTML = '<i class="fa-solid fa-play"></i> Run Transformer';
    }
}

// Reset uploads directory back to original samples
async function resetData() {
    if (!confirm('Are you sure you want to delete current uploads and reset to sample inputs?')) return;
    
    showToast('Resetting data...', 'info');
    try {
        const response = await fetch('/api/reset', { method: 'POST' });
        const result = await response.json();
        if (response.ok) {
            showToast('Sandbox reset completed.', 'success');
            
            // Clear details card
            DOM.profileContent.classList.add('hidden');
            DOM.detailsEmptyState.classList.remove('hidden');
            state.selectedCandidateId = null;
            state.candidates = [];
            state.projectedOutput = [];
            
            DOM.metricCandidates.textContent = '0';
            DOM.metricTrust.textContent = '0%';
            DOM.metricErrors.textContent = '0';
            
            fetchStatus();
        } else {
            throw new Error(result.detail || 'Reset failed');
        }
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Draw Candidates List Card items
function renderCandidatesList() {
    DOM.candidatesList.innerHTML = '';
    if (!state.candidates.length) {
        DOM.candidatesList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-users-slash"></i>
                <p>No candidates processed. Ensure uploads contain valid records.</p>
            </div>
        `;
        return;
    }
    
    state.candidates.forEach(c => {
        const card = document.createElement('div');
        card.className = `candidate-card-item ${state.selectedCandidateId === c.candidate_id ? 'selected' : ''}`;
        card.setAttribute('data-id', c.candidate_id);
        
        // Build badges for sources merged
        const sourceTypes = Array.from(new Set(c.source_records_merged));
        let badgesHtml = '';
        sourceTypes.forEach(src => {
            if (src === 'ats_json') badgesHtml += '<span class="source-badge badge-ats"><i class="fa-solid fa-file-code"></i> ATS</span>';
            if (src === 'recruiter_csv') badgesHtml += '<span class="source-badge badge-csv"><i class="fa-solid fa-table"></i> CSV</span>';
            if (src === 'recruiter_notes') badgesHtml += '<span class="source-badge badge-notes"><i class="fa-solid fa-file-lines"></i> Note</span>';
            if (src === 'resume') badgesHtml += '<span class="source-badge badge-resume"><i class="fa-solid fa-file-pdf"></i> PDF</span>';
        });
        
        const trustPercent = Math.round(c.overall_confidence * 100);
        
        card.innerHTML = `
            <div class="candidate-card-header">
                <span class="candidate-card-name">${c.full_name || 'Unknown Name'}</span>
                <span class="candidate-card-score">${trustPercent}% Trust</span>
            </div>
            <div class="candidate-card-headline">${c.headline || 'No Profile Headline'}</div>
            <div class="candidate-card-badges">${badgesHtml}</div>
        `;
        
        card.addEventListener('click', () => selectCandidate(c.candidate_id));
        DOM.candidatesList.appendChild(card);
    });
}

// Select and display details for a candidate
function selectCandidate(candidateId) {
    state.selectedCandidateId = candidateId;
    
    // Highlight list item
    document.querySelectorAll('.candidate-card-item').forEach(card => {
        if (card.getAttribute('data-id') === candidateId) {
            card.classList.add('selected');
        } else {
            card.classList.remove('selected');
        }
    });
    
    const candidate = state.candidates.find(c => c.candidate_id === candidateId);
    if (!candidate) return;
    
    // Hide empty state, show content card
    DOM.detailsEmptyState.classList.add('hidden');
    DOM.profileContent.classList.remove('hidden');
    
    // Populate header
    const initials = (candidate.full_name || 'UN').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
    DOM.profAvatar.textContent = initials;
    DOM.profName.textContent = candidate.full_name || 'Unknown Candidate';
    DOM.profHeadline.textContent = candidate.headline || 'No professional title provided';
    
    if (candidate.location) {
        const locStr = [candidate.location.city, candidate.location.region, candidate.location.country].filter(Boolean).join(', ');
        DOM.profLocation.querySelector('span').textContent = locStr || 'Location not specified';
        DOM.profLocation.style.display = 'block';
    } else {
        DOM.profLocation.style.display = 'none';
    }
    
    const trustScore = Math.round(candidate.overall_confidence * 100);
    DOM.profTrustScore.textContent = `${trustScore}% Profile Trust`;
    
    // Trust Badge color styling
    if (trustScore >= 80) {
        DOM.profTrustBadge.style.backgroundColor = 'rgba(16, 185, 129, 0.15)';
        DOM.profTrustBadge.style.color = '#34d399';
    } else if (trustScore >= 50) {
        DOM.profTrustBadge.style.backgroundColor = 'rgba(245, 158, 11, 0.15)';
        DOM.profTrustBadge.style.color = '#fbbf24';
    } else {
        DOM.profTrustBadge.style.backgroundColor = 'rgba(239, 68, 68, 0.15)';
        DOM.profTrustBadge.style.color = '#f87171';
    }
    
    // Links
    DOM.profLinks.innerHTML = '';
    const l = candidate.links;
    if (l.linkedin) DOM.profLinks.innerHTML += `<a href="${l.linkedin}" target="_blank" class="link-btn linkedin"><i class="fa-brands fa-linkedin"></i> LinkedIn</a>`;
    if (l.github) DOM.profLinks.innerHTML += `<a href="${l.github}" target="_blank" class="link-btn github"><i class="fa-brands fa-github"></i> GitHub</a>`;
    if (l.portfolio) DOM.profLinks.innerHTML += `<a href="${l.portfolio}" target="_blank" class="link-btn portfolio"><i class="fa-solid fa-globe"></i> Portfolio</a>`;
    l.other.forEach(url => {
        DOM.profLinks.innerHTML += `<a href="${url}" target="_blank" class="link-btn"><i class="fa-solid fa-link"></i> Website</a>`;
    });
    
    // Experience timeline
    DOM.profTimelineExperience.innerHTML = '';
    if (candidate.experience && candidate.experience.length) {
        candidate.experience.forEach(exp => {
            const item = document.createElement('div');
            item.className = 'timeline-item';
            
            const startVal = exp.start || 'Unknown';
            const endVal = exp.end || 'Present';
            
            item.innerHTML = `
                <div class="timeline-meta">
                    <span class="timeline-title">${exp.title || 'Role Name'}</span>
                    <span class="timeline-date">${startVal} - ${endVal}</span>
                </div>
                <div class="timeline-company">${exp.company || 'Company Name'}</div>
                ${exp.summary ? `<div class="timeline-summary">${exp.summary}</div>` : ''}
            `;
            DOM.profTimelineExperience.appendChild(item);
        });
    } else {
        DOM.profTimelineExperience.innerHTML = '<p class="text-muted font-normal">No professional history recorded.</p>';
    }
    
    // Education Cards Grid
    DOM.profGridEducation.innerHTML = '';
    if (candidate.education && candidate.education.length) {
        candidate.education.forEach(edu => {
            const item = document.createElement('div');
            item.className = 'education-card';
            
            const degStr = [edu.degree, edu.field].filter(Boolean).join(' in ') || 'Degree Details';
            
            item.innerHTML = `
                <div class="edu-degree">${degStr}</div>
                <div class="edu-institution">${edu.institution || 'Institution'}</div>
                <div class="edu-meta">
                    <span>Graduation</span>
                    <span>${edu.end_year || 'N/A'}</span>
                </div>
            `;
            DOM.profGridEducation.appendChild(item);
        });
    } else {
        DOM.profGridEducation.innerHTML = '<p class="text-muted font-normal">No educational background recorded.</p>';
    }
    
    // Skills tags
    DOM.profSkillsContainer.innerHTML = '';
    if (candidate.skills && candidate.skills.length) {
        candidate.skills.forEach(skill => {
            const tag = document.createElement('div');
            const confVal = Math.round(skill.confidence * 100);
            tag.className = `skill-tag ${confVal >= 70 ? 'high' : 'medium'}`;
            tag.innerHTML = `<span>${skill.name}</span><span class="skill-conf">${confVal}%</span>`;
            DOM.profSkillsContainer.appendChild(tag);
        });
    } else {
        DOM.profSkillsContainer.innerHTML = '<p class="text-muted font-normal">No skills keywords detected.</p>';
    }
    
    // Contact list
    DOM.profEmailsList.innerHTML = '';
    if (candidate.emails && candidate.emails.length) {
        candidate.emails.forEach(email => {
            const li = document.createElement('li');
            li.innerHTML = `<i class="fa-regular fa-envelope"></i> <span>${email}</span>`;
            DOM.profEmailsList.appendChild(li);
        });
    } else {
        DOM.profEmailsList.innerHTML = '<li>No email addresses</li>';
    }
    
    DOM.profPhonesList.innerHTML = '';
    if (candidate.phones && candidate.phones.length) {
        candidate.phones.forEach(phone => {
            const li = document.createElement('li');
            li.innerHTML = `<i class="fa-solid fa-phone"></i> <span>${phone}</span>`;
            DOM.profPhonesList.appendChild(li);
        });
    } else {
        DOM.profPhonesList.innerHTML = '<li>No phone numbers</li>';
    }
    
    // Provenance auditor table
    DOM.profProvenanceTbody.innerHTML = '';
    if (candidate.provenance && candidate.provenance.length) {
        candidate.provenance.forEach(prov => {
            const row = document.createElement('tr');
            
            const cleanSource = prov.source.replace('_', ' ').toUpperCase();
            const cleanMethod = prov.method.replace('_', ' ');
            const rawValEscaped = prov.raw_value ? prov.raw_value.replace(/</g, '&lt;').replace(/>/g, '&gt;') : 'N/A';
            const trustScore = Math.round(prov.confidence * 100);
            
            row.innerHTML = `
                <td><code>${prov.field}</code></td>
                <td>${rawValEscaped}</td>
                <td><span class="source-badge badge-${prov.source === 'ats_json' ? 'ats' : prov.source === 'recruiter_csv' ? 'csv' : prov.source === 'recruiter_notes' ? 'notes' : 'resume'}">${cleanSource}</span></td>
                <td class="text-capitalize">${cleanMethod}</td>
                <td><strong>${trustScore}%</strong></td>
            `;
            DOM.profProvenanceTbody.appendChild(row);
        });
    } else {
        DOM.profProvenanceTbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No provenance entries generated.</td></tr>';
    }
    
    // Linkage Map Connected Nodes
    DOM.linkageSourcesList.innerHTML = '';
    DOM.linkageCenterName.textContent = candidate.full_name || 'Canonical Profile';
    
    const matchedSources = Array.from(new Set(candidate.source_records_merged));
    matchedSources.forEach(src => {
        const item = document.createElement('div');
        item.className = 'linkage-source-node';
        
        let icon = '<i class="fa-solid fa-file-lines"></i>';
        let name = 'Recruiter Notes';
        if (src === 'ats_json') { icon = '<i class="fa-solid fa-file-code"></i>'; name = 'ATS Database (ats.json)'; }
        if (src === 'recruiter_csv') { icon = '<i class="fa-solid fa-table"></i>'; name = 'Recruiter CSV Export'; }
        if (src === 'resume') { icon = '<i class="fa-solid fa-file-pdf"></i>'; name = 'Candidate Resume PDF'; }
        
        item.innerHTML = `${icon} <span>${name}</span>`;
        DOM.linkageSourcesList.appendChild(item);
    });
}

// Search and filter candidates
function filterCandidatesList() {
    const query = DOM.candidateSearch.value.toLowerCase().trim();
    const cards = document.querySelectorAll('.candidate-card-item');
    
    cards.forEach(card => {
        const id = card.getAttribute('data-id');
        const cand = state.candidates.find(c => c.candidate_id === id);
        if (!cand) return;
        
        const name = (cand.full_name || '').toLowerCase();
        const headline = (cand.headline || '').toLowerCase();
        const location = cand.location ? [cand.location.city, cand.location.region, cand.location.country].filter(Boolean).join(' ').toLowerCase() : '';
        const skills = cand.skills.map(s => s.name.toLowerCase()).join(' ');
        
        if (name.includes(query) || headline.includes(query) || location.includes(query) || skills.includes(query)) {
            card.classList.remove('hidden');
        } else {
            card.classList.add('hidden');
        }
    });
}

// Apply runtime schema editor settings and trigger custom API run
function applyCustomSchema() {
    const fields = [];
    if (document.getElementById('schema-field-name').checked) fields.push('full_name');
    if (document.getElementById('schema-field-emails').checked) fields.push('emails');
    if (document.getElementById('schema-field-phones').checked) fields.push('phones');
    if (document.getElementById('schema-field-location').checked) fields.push('location');
    if (document.getElementById('schema-field-links').checked) fields.push('links');
    if (document.getElementById('schema-field-skills').checked) fields.push('skills');
    if (document.getElementById('schema-field-experience').checked) fields.push('experience');
    if (document.getElementById('schema-field-education').checked) fields.push('education');
    
    const remappings = {};
    const nameRemap = document.getElementById('map-name').value.trim();
    const emailRemap = document.getElementById('map-email').value.trim();
    const phoneRemap = document.getElementById('map-phone').value.trim();
    
    if (nameRemap) remappings['full_name'] = nameRemap;
    if (emailRemap) remappings['emails[0]'] = emailRemap;
    if (phoneRemap) remappings['phones[0]'] = phoneRemap;
    
    const missingPolicy = document.getElementById('policy-missing').value;
    
    const customConfig = {
        fields: fields,
        remappings: remappings,
        missing_value_policy: missingPolicy
    };
    
    runPipeline(customConfig);
}

// Copy JSON Output to clipboard
function copyJsonOutput() {
    const jsonText = DOM.schemaJsonOutput.textContent;
    if (jsonText.startsWith('//') || !jsonText.trim()) {
        showToast('No JSON output available to copy.', 'error');
        return;
    }
    
    navigator.clipboard.writeText(jsonText)
        .then(() => showToast('Copied JSON to clipboard!', 'success'))
        .catch(err => showToast(`Copy failed: ${err.message}`, 'error'));
}

// Toast Notification Manager
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = '<i class="fa-solid fa-info-circle"></i>';
    if (type === 'success') icon = '<i class="fa-solid fa-circle-check"></i>';
    if (type === 'error') icon = '<i class="fa-solid fa-circle-exclamation"></i>';
    if (type === 'warning') icon = '<i class="fa-solid fa-triangle-exclamation"></i>';
    
    toast.innerHTML = `${icon} <span>${message}</span>`;
    DOM.toastContainer.appendChild(toast);
    
    // Auto remove
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.25s reverse ease-out';
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}
