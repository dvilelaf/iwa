document.addEventListener('DOMContentLoaded', () => {
    const state = {
        activeChain: 'gnosis',
        chains: [],
        tokens: {},
        accounts: [],
        transactions: []
    };

    // HTML escape utility to prevent XSS
    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    // UI Elements
    const chainSelect = document.getElementById('active-chain');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const refreshBtn = document.getElementById('refresh-btn');
    const sendForm = document.getElementById('send-tx-form');
    const createSafeBtn = document.getElementById('create-safe-btn');
    const createEoaBtn = document.getElementById('create-eoa-btn');

    // Initialize
    async function init() {
        try {
            const resp = await fetch('/api/state');
            const data = await resp.json();
            state.chains = data.chains;
            state.tokens = data.tokens;
            state.activeChain = data.default_chain;

            populateChainSelect();
            updateFormSelectors();
            loadWallets();
            loadTransactions();
            loadRPCStatus();

            setInterval(loadWallets, 15000);
            setInterval(loadTransactions, 10000);
            setInterval(loadRPCStatus, 30000);
        } catch (err) {
            showToast('Error initializing: ' + escapeHtml(err.message), 'error');
        }
    }

    function populateChainSelect() {
        chainSelect.innerHTML = state.chains.map(c =>
            `<option value="${escapeHtml(c)}" ${c === state.activeChain ? 'selected' : ''}>${escapeHtml(c.charAt(0).toUpperCase() + c.slice(1))}</option>`
        ).join('');
    }

    // Tabs
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const target = btn.getAttribute('data-tab');
            document.getElementById(target).classList.add('active');
        });
    });

    // Chain change
    chainSelect.addEventListener('change', (e) => {
        state.activeChain = e.target.value;
        refreshAll();
    });

    refreshBtn.addEventListener('click', refreshAll);

    function refreshAll() {
        showToast(`Refreshed ${escapeHtml(state.activeChain)}`, 'info');
        loadWallets();
        loadTransactions();
        loadRPCStatus();
        updateFormSelectors();
    }

    async function loadWallets() {
        try {
            const resp = await fetch(`/api/accounts?chain=${state.activeChain}`);
            const data = await resp.json();
            state.accounts = data;
            renderAccounts(data);
            updateFromSelector();
            updateFormSelectors();
        } catch (err) {
            console.error(err);
        }
    }

    function renderAccounts(accountsData) {
        const body = document.getElementById('accounts-body');
        const thead = document.querySelector('#accounts-table thead tr');

        // Dynamic Token Columns
        const chainTokens = (state.tokens[state.activeChain] || []).filter(t => t !== 'native');

        // Reset Header
        thead.innerHTML = `
            <th>Tag</th>
            <th>Address</th>
            <th>Type</th>
            <th class="val">Native</th>
            ${chainTokens.map(t => `<th class="val">${escapeHtml(t.toUpperCase())}</th>`).join('')}
        `;

        if (!accountsData || accountsData.length === 0) {
            body.innerHTML = `<tr><td colspan="${4 + chainTokens.length}" style="text-align: center; opacity: 0.5;">No accounts found for ${escapeHtml(state.activeChain)}</td></tr>`;
            return;
        }

        body.innerHTML = accountsData.map(acc => `
            <tr>
                <td><span class="tag-badge">${escapeHtml(acc.tag)}</span></td>
                <td class="address-cell" onclick="copyToClipboard('${escapeHtml(acc.address)}')">${escapeHtml(shortenAddr(acc.address))}</td>
                <td>${escapeHtml(acc.type)}</td>
                <td class="val">${escapeHtml(acc.balances.native)}</td>
                ${chainTokens.map(t => `<td class="val">${escapeHtml(acc.balances[t] || '-')}</td>`).join('')}
            </tr>
        `).join('');
    }

    async function loadTransactions() {
        try {
            const resp = await fetch(`/api/transactions?chain=${state.activeChain}`);
            const data = await resp.json();
            const body = document.getElementById('tx-body');
            body.innerHTML = data.map(tx => `
                <tr>
                    <td>${escapeHtml(tx.timestamp.split('T')[1].split('.')[0])}</td>
                    <td>${escapeHtml(tx.chain)}</td>
                    <td class="address-cell" title="${escapeHtml(tx.from)}">${escapeHtml(shortenAddr(tx.from))}</td>
                    <td class="address-cell" title="${escapeHtml(tx.to)}">${escapeHtml(shortenAddr(tx.to))}</td>
                    <td>${escapeHtml(tx.token.toUpperCase())}</td>
                    <td class="val">${escapeHtml(tx.amount)}</td>
                    <td class="val">${escapeHtml(tx.value_eur)}</td>
                    <td><span style="color: #2ecc71">${escapeHtml(tx.status)}</span></td>
                    <td class="address-cell" onclick="copyToClipboard('${escapeHtml(tx.hash)}')">${escapeHtml(tx.hash.substring(0, 10))}...</td>
                    <td>${escapeHtml(tx.gas_cost)}</td>
                    <td>${escapeHtml(tx.gas_value_eur)}</td>
                    <td class="tags-cell">${(tx.tags || []).map(t => `<span class="tag-badge">${escapeHtml(t)}</span>`).join('')}</td>
                </tr>
            `).join('');
        } catch (err) {
            console.error(err);
        }
    }

    async function loadRPCStatus() {
        try {
            const resp = await fetch('/api/rpc-status');
            const status = await resp.json();
            const container = document.getElementById('rpc-cards');
            container.innerHTML = Object.entries(status).map(([name, data]) => `
                <div class="rpc-card glass">
                    <div class="rpc-header">
                        <h3>${escapeHtml(name.toUpperCase())}</h3>
                        <span class="status-indicator ${escapeHtml(data.status)}"></span>
                    </div>
                    <div class="rpc-meta">
                        <span>Status:</span>
                        <span style="color: ${data.status === 'online' ? '#2ecc71' : '#e74c3c'}">${escapeHtml(data.status.toUpperCase())}</span>
                    </div>
                    ${data.block ? `<div class="rpc-meta"><span>Block:</span><span>${escapeHtml(String(data.block))}</span></div>` : ''}
                    ${data.latency ? `<div class="rpc-meta"><span>Latency:</span><span style="color: var(--accent-color)">${escapeHtml(data.latency)}</span></div>` : ''}
                    <div class="rpc-meta"><span>Node:</span><span style="font-size: 0.7rem; opacity: 0.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(data.url || 'N/A')}</span></div>
                </div>
            `).join('');
        } catch (err) {
            console.error(err);
        }
    }

    function updateFormSelectors() {
        updateFromSelector();
        const tokenSelect = document.getElementById('tx-token');
        const chainTokens = state.tokens[state.activeChain] || [];
        tokenSelect.innerHTML = `<option value="native">Native Currency</option>` +
            chainTokens.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t.toUpperCase())}</option>`).join('');
    }

    function updateFromSelector() {
        const fromSelect = document.getElementById('tx-from');
        fromSelect.innerHTML = state.accounts.map(acc =>
            `<option value="${escapeHtml(acc.address)}">${escapeHtml(acc.tag)} (${escapeHtml(shortenAddr(acc.address))})</option>`
        ).join('');
    }

    createEoaBtn.addEventListener('click', async () => {
        const tag = prompt("Enter tag for new account (optional):");
        try {
            const resp = await fetch('/api/accounts/eoa', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tag })
            });
            if (resp.ok) {
                showToast("EOA Created", "success");
                loadWallets();
            }
        } catch (err) { showToast("Error creating EOA", "error"); }
    });

    createSafeBtn.addEventListener('click', () => {
        showToast("Create Safe feature coming soon", "info");
    });

    sendForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = sendForm.querySelector('button');
        const originalText = btn.innerText;
        btn.innerText = 'Sending...';
        btn.disabled = true;

        const payload = {
            from_address: document.getElementById('tx-from').value,
            to_address: document.getElementById('tx-to').value,
            amount: parseFloat(document.getElementById('tx-amount').value),
            token: document.getElementById('tx-token').value,
            chain: state.activeChain
        };

        try {
            const resp = await fetch('/api/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await resp.json();
            if (resp.ok) {
                showToast(`Success! Hash: ${result.hash.substring(0, 10)}...`, 'success');
                sendForm.reset();
                loadTransactions();
                loadWallets();
            } else {
                showToast(`Error: ${result.detail}`, 'error');
            }
        } catch (err) {
            showToast('Network error', 'error');
        } finally {
            btn.innerText = originalText;
            btn.disabled = false;
        }
    });

    // Utils
    function shortenAddr(addr) {
        if (!addr) return '';
        return addr.substring(0, 6) + '...' + addr.substring(addr.length - 4);
    }

    window.copyToClipboard = (text) => {
        navigator.clipboard.writeText(text).then(() => {
            showToast('Copied to clipboard', 'info');
        });
    };

    function showToast(msg, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerText = msg;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    init();
});
