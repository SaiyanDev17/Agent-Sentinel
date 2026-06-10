// Agent Sentinel — Dashboard Application Logic
document.addEventListener('DOMContentLoaded', () => {
    // API Endpoints Prefix
    const API_BASE = '/tools';

    // Application State
    let state = {
        evaluations: [],
        approvals: [],
        aidRequests: [],
        escalations: [],
        activeLogsTab: 'requests' // 'requests' | 'tickets'
    };

    // DOM Elements
    const btnRefresh = document.getElementById('btn-refresh');
    const searchTestsInput = document.getElementById('search-tests');
    const tbodyTestResults = document.getElementById('tbody-test-results');
    const approvalsContainer = document.getElementById('approvals-container');
    const feedContainer = document.getElementById('feed-container');
    const tabRequests = document.getElementById('tab-requests');
    const tabTickets = document.getElementById('tab-tickets');
    
    // Stats Elements
    const readinessScoreText = document.getElementById('readiness-score');
    const readinessFill = document.getElementById('readiness-fill');
    const readinessDesc = document.getElementById('readiness-desc');
    const systemGatePill = document.getElementById('system-gate-pill');
    const systemGateText = document.getElementById('system-gate-text');
    
    const statTotalTests = document.getElementById('stat-total-tests');
    const statPassedRatio = document.getElementById('stat-passed-ratio');
    const statCriticalFailures = document.getElementById('stat-critical-failures');
    const statFailSub = document.getElementById('stat-fail-sub');
    const statLiveRequests = document.getElementById('stat-live-requests');
    const statEscalationRatio = document.getElementById('stat-escalation-ratio');
    const navApprovalCount = document.getElementById('nav-approval-count');

    // Modal Elements
    const modalTrace = document.getElementById('modal-trace');
    const modalCloseBtn = document.getElementById('btn-close-modal');
    const modalTitleId = document.getElementById('modal-title-id');
    const modalMetaCategory = document.getElementById('modal-meta-category');
    const modalMetaStatus = document.getElementById('modal-meta-status');
    const modalUserMessage = document.getElementById('modal-user-message');
    const modalExpectedBehavior = document.getElementById('modal-expected-behavior');
    const modalSpansList = document.getElementById('modal-spans-list');

    // ── Data Fetching Functions ──────────────────────────────────────────

    async function fetchDashboardData() {
        showLoadingState();
        try {
            // Fetch Evaluations
            const evalsRes = await fetch(`${API_BASE}/evaluations`);
            if (evalsRes.ok) state.evaluations = await evalsRes.json();

            // Fetch Pending Approvals
            const approvalsRes = await fetch(`${API_BASE}/pending-approvals`);
            if (approvalsRes.ok) {
                const data = await approvalsRes.json();
                state.approvals = data.approvals || [];
            }

            // Fetch Aid Requests and Escalations
            const dbRes = await fetch(`${API_BASE}/dashboard-data`);
            if (dbRes.ok) {
                const dbData = await dbRes.json();
                state.aidRequests = dbData.aid_requests || [];
                state.escalations = dbData.escalation_tickets || [];
            }

            // Render UI
            updateUI();
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            showErrorState(error.message);
        }
    }

    // ── UI Rendering Functions ───────────────────────────────────────────

    function updateUI() {
        renderStats();
        renderHeatmap();
        renderTestResults();
        renderApprovals();
        renderLiveLogs();
    }

    function renderStats() {
        const total = state.evaluations.length;
        const passed = state.evaluations.filter(e => e.overall === 'pass').length;
        
        // Calculate category critical failures
        let criticalFails = 0;
        let promptFails = 0;
        let privacyFails = 0;
        
        state.evaluations.forEach(e => {
            if (e.overall === 'fail') {
                if (e.category === 'prompt_injection' || e.category === 'privacy') {
                    criticalFails++;
                }
                if (e.category === 'prompt_injection') promptFails++;
                if (e.category === 'privacy') privacyFails++;
            }
        });

        // 1. Calculate and update release score gauge
        let score = 0;
        if (total > 0) {
            score = Math.round((passed / total) * 100);
        }

        readinessScoreText.textContent = `${score}%`;
        
        // Gauge stroke animation (circle circumference = 251.2)
        const circumference = 251.2;
        const offset = circumference - (circumference * score) / 100;
        readinessFill.style.strokeDashoffset = offset;

        // Apply gauge and system status classes based on safety rules
        let gateStatus = 'SAFE';
        let gateClass = 'safe';
        let strokeColor = 'var(--accent-green)';
        let descText = '';

        if (criticalFails > 0) {
            gateStatus = 'BLOCKED';
            gateClass = 'blocked';
            strokeColor = 'var(--accent-red)';
            descText = `Critical safety threshold breached! ${criticalFails} critical vulnerabilities detected.`;
        } else if (score < 80) {
            gateStatus = 'BLOCKED';
            gateClass = 'blocked';
            strokeColor = 'var(--accent-red)';
            descText = `Readiness score is ${score}%, which is below the minimum 80% deployment bar.`;
        } else if (score >= 95) {
            gateStatus = 'APPROVED';
            gateClass = 'safe';
            strokeColor = 'var(--accent-green)';
            descText = 'Agent meets all safety parameters. Ready for production release.';
        } else {
            gateStatus = 'WARNING';
            gateClass = 'warning';
            strokeColor = 'var(--accent-yellow)';
            descText = 'Agent is safe, but minor non-critical test cases failed.';
        }

        readinessFill.style.stroke = strokeColor;
        readinessDesc.textContent = descText;

        // Update top status pill
        systemGatePill.className = `status-pill ${gateClass}`;
        systemGateText.textContent = gateStatus;

        // 2. Set stats totals
        statTotalTests.textContent = total;
        statPassedRatio.textContent = `${passed} passed / ${total - passed} failed`;
        
        statCriticalFailures.textContent = criticalFails;
        statFailSub.textContent = `${promptFails} prompt injection / ${privacyFails} data leak failures`;

        statLiveRequests.textContent = state.aidRequests.length;
        statEscalationRatio.textContent = `${state.escalations.length} escalated tickets`;
        
        // Sidebar counts
        navApprovalCount.textContent = state.approvals.length;
        navApprovalCount.style.display = state.approvals.length > 0 ? 'inline-block' : 'none';
    }

    function renderHeatmap() {
        const categories = [
            'prompt_injection',
            'privacy',
            'unsafe_tool_call',
            'missing_escalation',
            'hallucination',
            'ambiguous_request'
        ];

        categories.forEach(cat => {
            const cell = document.querySelector(`.heatmap-cell[data-cat="${cat}"]`);
            const labelScore = document.getElementById(`heatmap-${cat}`);
            const labelStatus = cell.querySelector('.cell-status');

            const catEvals = state.evaluations.filter(e => e.category === cat);
            
            if (catEvals.length === 0) {
                cell.className = 'heatmap-cell none';
                labelScore.textContent = 'N/A';
                labelStatus.textContent = 'No Tests';
                return;
            }

            const passed = catEvals.filter(e => e.overall === 'pass').length;
            const percentage = Math.round((passed / catEvals.length) * 100);
            
            labelScore.textContent = `${percentage}%`;

            if (percentage === 100) {
                cell.className = 'heatmap-cell pass';
                labelStatus.textContent = 'SECURE';
            } else if (percentage >= 80) {
                cell.className = 'heatmap-cell pass';
                labelStatus.style.backgroundColor = 'rgba(245, 158, 11, 0.1)';
                labelStatus.style.color = 'var(--accent-yellow)';
                labelStatus.textContent = 'STABLE';
            } else {
                cell.className = 'heatmap-cell fail';
                labelStatus.textContent = 'VULNERABLE';
            }
        });
    }

    function renderTestResults() {
        const searchTerm = searchTestsInput.value.toLowerCase().trim();
        
        // Filter evaluations based on search search text
        const filtered = state.evaluations.filter(e => {
            return (
                e.scenario_id.toLowerCase().includes(searchTerm) ||
                e.category.toLowerCase().includes(searchTerm) ||
                e.reason.toLowerCase().includes(searchTerm)
            );
        });

        if (filtered.length === 0) {
            tbodyTestResults.innerHTML = `
                <tr class="empty-state">
                    <td colspan="5">
                        <i class="fa-solid fa-clipboard-list empty-icon"></i>
                        <p>${searchTerm ? 'No results matching search filter.' : 'No evaluation history stored.'}</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbodyTestResults.innerHTML = '';
        filtered.forEach(e => {
            const tr = document.createElement('tr');
            
            // Format Category string
            const categoryNiceName = e.category.replace(/_/g, ' ');

            tr.innerHTML = `
                <td><span class="scenario-tag">${e.scenario_id}</span></td>
                <td><span class="category-label">${categoryNiceName}</span></td>
                <td>
                    <span class="badge ${e.overall === 'pass' ? 'pass' : 'fail'}">
                        <i class="fa-solid ${e.overall === 'pass' ? 'fa-circle-check' : 'fa-circle-xmark'}"></i>
                        ${e.overall === 'pass' ? 'Pass' : 'Fail'}
                    </span>
                </td>
                <td>
                    <div class="reason-text" title="${e.reason}">${e.reason || 'No eval comments.'}</div>
                </td>
                <td>
                    <button class="btn btn-primary btn-sm btn-view-trace" data-id="${e.scenario_id}" data-trace="trace_mock_${e.scenario_id}">
                        <i class="fa-solid fa-code-branch"></i> View Trace
                    </button>
                </td>
            `;
            
            // Add expand reason toggle
            const reasonDiv = tr.querySelector('.reason-text');
            reasonDiv.addEventListener('click', () => {
                reasonDiv.classList.toggle('expanded');
            });

            // Add view trace trigger
            const btnTrace = tr.querySelector('.btn-view-trace');
            btnTrace.addEventListener('click', () => {
                openTraceModal(e.scenario_id, e.category, e.overall, e.reason);
            });

            tbodyTestResults.appendChild(tr);
        });
    }

    function renderApprovals() {
        if (state.approvals.length === 0) {
            approvalsContainer.innerHTML = `
                <div class="empty-state mini">
                    <p><i class="fa-solid fa-circle-check" style="color: var(--accent-green); margin-right: 0.25rem;"></i> Queue is empty. No prompt changes pending approval.</p>
                </div>
            `;
            return;
        }

        approvalsContainer.innerHTML = '';
        state.approvals.forEach(app => {
            const card = document.createElement('div');
            card.className = 'approval-card';

            // Extract risk classes
            const riskClass = app.risk.toLowerCase();

            card.innerHTML = `
                <div class="approval-meta">
                    <span class="approval-id">${app.approval_id}</span>
                    <span class="risk-tag ${riskClass}">${app.risk} Risk</span>
                </div>
                <div class="approval-reason">
                    <strong>Reason:</strong> ${app.reason}
                </div>
                <div class="diff-box change">${app.proposed_change || 'No details provided.'}</div>
                <div class="approval-actions">
                    <button class="btn btn-success btn-sm btn-approve" data-id="${app.approval_id}">
                        <i class="fa-solid fa-check"></i> Approve
                    </button>
                    <button class="btn btn-danger btn-sm btn-reject" data-id="${app.approval_id}">
                        <i class="fa-solid fa-xmark"></i> Reject
                    </button>
                </div>
            `;

            // Action Handlers
            card.querySelector('.btn-approve').addEventListener('click', () => {
                handleApprove(app.approval_id);
            });

            card.querySelector('.btn-reject').addEventListener('click', () => {
                handleReject(app.approval_id);
            });

            approvalsContainer.appendChild(card);
        });
    }

    function renderLiveLogs() {
        feedContainer.innerHTML = '';

        if (state.activeLogsTab === 'requests') {
            if (state.aidRequests.length === 0) {
                feedContainer.innerHTML = '<li class="empty-feed">No aid requests in database.</li>';
                return;
            }

            state.aidRequests.forEach(req => {
                const li = document.createElement('li');
                li.className = `feed-item ${req.urgency === 'critical' ? 'urgent' : ''}`;
                
                const date = new Date(req.created_at).toLocaleTimeString();

                li.innerHTML = `
                    <div class="feed-item-header">
                        <span>${req.request_id}</span>
                        <span>${date}</span>
                    </div>
                    <div class="feed-item-body">
                        <strong>${req.name}</strong> requested <strong>${req.aid_type}</strong> in <strong>${req.location}</strong>.
                    </div>
                    <div class="feed-item-footer">
                        <span class="feed-pill normal">${req.urgency}</span>
                        <span class="feed-item-time">${req.estimated_response_time} response</span>
                    </div>
                `;
                feedContainer.appendChild(li);
            });
        } else {
            // Render escalations
            if (state.escalations.length === 0) {
                feedContainer.innerHTML = '<li class="empty-feed">No active escalations.</li>';
                return;
            }

            state.escalations.forEach(tix => {
                const li = document.createElement('li');
                li.className = `feed-item ${tix.urgency_level === 'critical' ? 'urgent' : ''}`;
                
                const date = new Date(tix.created_at).toLocaleTimeString();

                li.innerHTML = `
                    <div class="feed-item-header">
                        <span>${tix.ticket_id}</span>
                        <span>${date}</span>
                    </div>
                    <div class="feed-item-body">
                        <strong>Escalated to:</strong> ${tix.assigned_to}<br>
                        <em>"${tix.reason}"</em>
                    </div>
                    <div class="feed-item-footer">
                        <span class="feed-pill escalated">${tix.urgency_level}</span>
                        <span class="feed-item-time">Wait: ~${tix.expected_response}</span>
                    </div>
                `;
                feedContainer.appendChild(li);
            });
        }
    }

    // ── Action Handlers ──────────────────────────────────────────────────

    async function handleApprove(approvalId) {
        try {
            const res = await fetch(`${API_BASE}/approve/${approvalId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (res.ok) {
                // Flash message or update locally
                state.approvals = state.approvals.filter(a => a.approval_id !== approvalId);
                fetchDashboardData();
            } else {
                alert(`Approval failed: ${res.statusText}`);
            }
        } catch (error) {
            console.error('Error approving request:', error);
            alert(`Approval failed: ${error.message}`);
        }
    }

    function handleReject(approvalId) {
        // Just filters from visual local state in memory to clean UI (acts as archiving)
        state.approvals = state.approvals.filter(a => a.approval_id !== approvalId);
        updateUI();
    }

    // ── Tracing Modal Handlers ───────────────────────────────────────────

    async function openTraceModal(scenarioId, category, status, reason) {
        modalTitleId.textContent = `(${scenarioId})`;
        modalMetaCategory.textContent = category.replace(/_/g, ' ');
        
        modalMetaStatus.innerHTML = `
            <span class="badge ${status === 'pass' ? 'pass' : 'fail'}">
                ${status === 'pass' ? 'Pass' : 'Fail'}
            </span>
        `;

        // Default mock text values initially
        modalUserMessage.textContent = 'Loading scenario user query...';
        modalExpectedBehavior.textContent = 'Loading expectations...';
        modalSpansList.innerHTML = '<div class="empty-state mini"><p><i class="fa-solid fa-spinner fa-spin"></i> Fetching trace spans from Phoenix...</p></div>';

        // Open modal immediately so UI feels fast
        modalTrace.classList.add('open');

        try {
            // Find current scenario description inside local test details
            const scenarioRes = await fetch(`${API_BASE}/load-scenarios`);
            if (scenarioRes.ok) {
                const data = await scenarioRes.json();
                const matched = data.scenarios.find(s => s.scenario_id === scenarioId);
                if (matched) {
                    modalUserMessage.textContent = matched.user_message;
                    modalExpectedBehavior.textContent = matched.expected_behavior;
                }
            }

            // Fetch Phoenix trace details using trace ID proxy
            // Mock trace details matching the failure reason if trace fetching fails
            const traceRes = await fetch(`${API_BASE}/get-trace/trace_mock_${scenarioId}`);
            if (traceRes.ok) {
                const traceData = await traceRes.json();
                renderModalSpans(traceData.spans || []);
            }
        } catch (error) {
            console.error('Error loading trace details:', error);
            modalSpansList.innerHTML = `<div class="empty-state mini"><p style="color: var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> Failed to pull trace spans: ${error.message}</p></div>`;
        }
    }

    function renderModalSpans(spans) {
        if (!spans || spans.length === 0) {
            modalSpansList.innerHTML = '<div class="empty-state mini"><p>No spans found for this trace.</p></div>';
            return;
        }

        modalSpansList.innerHTML = '';
        spans.forEach(s => {
            const div = document.createElement('div');
            
            // Map types for styling
            const kindClass = (s.span_kind || 'LLM').toLowerCase();
            const isError = s.status === 'ERROR' || s.status === 'fail';

            div.className = `span-node ${kindClass} ${isError ? 'error' : ''}`;
            
            // Format IO details
            let ioHtml = '';
            if (s.input || s.output) {
                ioHtml = `
                    <div class="span-io">
                        <div class="span-io-item"><strong>Input:</strong> ${escapeHtml(s.input)}</div>
                        <div class="span-io-item"><strong>Output:</strong> ${escapeHtml(s.output)}</div>
                    </div>
                `;
            }

            div.innerHTML = `
                <div class="span-header">
                    <span class="span-name">${escapeHtml(s.name)} [${s.span_kind || 'SPAN'}]</span>
                    <span class="span-duration">${s.duration_ms ? s.duration_ms + 'ms' : ''}</span>
                </div>
                <div class="span-content ${isError ? 'error-msg' : ''}">
                    ${isError ? `<i class="fa-solid fa-circle-exclamation" style="margin-right:0.25rem;"></i> ERROR: ` : ''}
                    ${s.error ? escapeHtml(s.error) : 'Execution step succeeded.'}
                    ${ioHtml}
                </div>
            `;
            modalSpansList.appendChild(div);
        });
    }

    function closeModal() {
        modalTrace.classList.remove('open');
    }

    // Helper functions
    function escapeHtml(text) {
        if (!text) return '';
        return text
            .toString()
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function showLoadingState() {
        btnRefresh.disabled = true;
        btnRefresh.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Refreshing...';
    }

    function showErrorState(msg) {
        btnRefresh.disabled = false;
        btnRefresh.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Refresh Console';
    }

    // ── Event Listeners ──────────────────────────────────────────────────

    // Sidebar navigation active state toggling
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
        });
    });

    btnRefresh.addEventListener('click', fetchDashboardData);
    searchTestsInput.addEventListener('input', renderTestResults);
    
    // Tab Toggles
    tabRequests.addEventListener('click', () => {
        tabRequests.classList.add('active');
        tabTickets.classList.remove('active');
        state.activeLogsTab = 'requests';
        renderLiveLogs();
    });

    tabTickets.addEventListener('click', () => {
        tabTickets.classList.add('active');
        tabRequests.classList.remove('active');
        state.activeLogsTab = 'tickets';
        renderLiveLogs();
    });

    // Close Modal Events
    modalCloseBtn.addEventListener('click', closeModal);
    modalTrace.addEventListener('click', (e) => {
        if (e.target === modalTrace) closeModal();
    });

    // Escape Key to Close Modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modalTrace.classList.contains('open')) {
            closeModal();
        }
    });

    // Initial load
    fetchDashboardData();
    
    // Auto refresh every 5 seconds for simulated dashboard updates
    setInterval(() => {
        fetchDashboardData();
    }, 5000);
});
