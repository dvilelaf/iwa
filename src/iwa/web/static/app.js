document.addEventListener('DOMContentLoaded', () => {
    const state = {
        activeChain: 'gnosis',
        activeTab: 'dashboard',
        chains: [],
        tokens: {},
        nativeCurrencies: {},
        accounts: [],           // Basic account info
        balanceCache: {},       // { address: { native: "1.00", OLAS: "50.00", ... } }
        authToken: localStorage.getItem('iwa_auth_token') || '',
        activeTokens: new Set(['native', 'OLAS'])  // Default: native and OLAS
    };

    // DOM Elements
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const activeChainSelect = document.getElementById('active-chain');
    const refreshBtn = document.getElementById('refresh-btn');
    const createEoaBtn = document.getElementById('create-eoa-btn');
    const createSafeBtn = document.getElementById('create-safe-btn');
    const sendForm = document.getElementById('send-tx-form');
    const tokenTogglesContainer = document.getElementById('token-toggles');

    // Unified Fetch with Auth
    async function authFetch(url, options = {}) {
        if (state.authToken) {
            options.headers = {
                ...options.headers,
                'Authorization': `Bearer ${state.authToken}`
            };
        }

        const resp = await fetch(url, options);

        if (resp.status === 401) {
            const pwd = prompt("Enter Web UI Password:");
            if (pwd) {
                state.authToken = pwd;
                localStorage.setItem('iwa_auth_token', pwd);
                return authFetch(url, options);
            }
        }
        return resp;
    }

    const escapeHtml = (str) => {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    };

    function getNativeCurrencySymbol() {
        return state.nativeCurrencies[state.activeChain] || 'Native';
    }

    function getAllTokenColumns() {
        const nativeSymbol = getNativeCurrencySymbol();
        const chainTokens = state.tokens[state.activeChain] || [];
        return ['native', ...chainTokens];
    }

    // Initialize
    async function init() {
        try {
            const resp = await authFetch('/api/state');
            const data = await resp.json();
            state.chains = data.chains;
            state.tokens = data.tokens;
            state.nativeCurrencies = data.native_currencies || {};
            state.activeChain = data.default_chain;

            populateChainSelect();
            populateTokenToggles();
            updateFormSelectors();

            // Initial load
            loadAccounts();
            loadTransactions();

            // Setup Safe chains
            populateSafeChains();
        } catch (err) {
            console.error("Init error:", err);
            showToast('Error initializing: ' + escapeHtml(err.message), 'error');
        }
    }

    // Tabs - no refresh on switch, use cached data
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const target = btn.getAttribute('data-tab');
            state.activeTab = target;
            document.getElementById(target).classList.add('active');
            if (target === 'rpc') {
                loadRPCStatus(true);
            }
        });
    });

    // Chain Change Handling
    activeChainSelect.addEventListener('change', (e) => {
        state.activeChain = e.target.value;
        state.balanceCache = {};  // Clear cache on chain change
        populateTokenToggles();
        loadAccounts();
        loadTransactions();
        updateFormSelectors();
    });

    // Refresh button - forces full reload
    refreshBtn.addEventListener('click', () => {
        showToast(`Refreshing balances...`, 'info');
        state.balanceCache = {};  // Clear cache
        loadAccounts();
        fetchBalancesForTokens(Array.from(state.activeTokens));
    });

    function populateChainSelect() {
        activeChainSelect.innerHTML = state.chains.map(c =>
            `<option value="${c}" ${c === state.activeChain ? 'selected' : ''}>${c.charAt(0).toUpperCase() + c.slice(1)}</option>`
        ).join('');
    }

    function populateTokenToggles() {
        const chainTokens = state.tokens[state.activeChain] || [];
        const nativeSymbol = getNativeCurrencySymbol();

        let html = `
            <label class="token-toggle ${state.activeTokens.has('native') ? 'active' : ''}">
                <input type="checkbox" value="native" ${state.activeTokens.has('native') ? 'checked' : ''}>
                ${escapeHtml(nativeSymbol)}
            </label>
        `;

        for (const token of chainTokens) {
            html += `
                <label class="token-toggle ${state.activeTokens.has(token) ? 'active' : ''}">
                    <input type="checkbox" value="${escapeHtml(token)}" ${state.activeTokens.has(token) ? 'checked' : ''}>
                    ${escapeHtml(token.toUpperCase())}
                </label>
            `;
        }

        tokenTogglesContainer.innerHTML = html;

        // Add event listeners
        tokenTogglesContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const tokenName = e.target.value;
                if (e.target.checked) {
                    state.activeTokens.add(tokenName);
                    e.target.parentElement.classList.add('active');
                    // Re-render immediately to show spinners
                    renderAccounts();
                    // Then fetch balances (will re-render again when done)
                    fetchBalancesForTokens([tokenName]);
                } else {
                    state.activeTokens.delete(tokenName);
                    e.target.parentElement.classList.remove('active');
                    renderAccounts();  // Just re-render (hide this column's balances)
                }
            });
        });
    }

    function isTokenCached(tokenName) {
        // Check if we have balance data for this token
        for (const acc of state.accounts) {
            if (state.balanceCache[acc.address] && state.balanceCache[acc.address][tokenName] !== undefined) {
                return true;
            }
        }
        return false;
    }

    async function loadAccounts() {
        const body = document.getElementById('accounts-body');
        const allTokens = getAllTokenColumns();
        const nativeSymbol = getNativeCurrencySymbol();

        // Show loading
        body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" style="text-align: center;"><span class="loading-spinner"></span> Loading accounts...</td></tr>`;

        try {
            const resp = await authFetch(`/api/accounts?chain=${state.activeChain}`);
            const data = await resp.json();
            state.accounts = data;

            renderAccounts();
            updateFormSelectors();

            // Fetch balances for active tokens
            fetchBalancesForTokens(Array.from(state.activeTokens));
        } catch (err) {
            console.error(err);
            body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" style="text-align: center; color: #e74c3c;">Error loading accounts</td></tr>`;
        }
    }

    function renderAccounts() {
        const body = document.getElementById('accounts-body');
        const thead = document.querySelector('#accounts-table thead tr');
        const allTokens = getAllTokenColumns();
        const nativeSymbol = getNativeCurrencySymbol();

        // Build header with ALL token columns
        let headerHtml = `
            <th>Tag</th>
            <th>Address</th>
            <th>Type</th>
        `;
        allTokens.forEach(t => {
            const label = t === 'native' ? nativeSymbol : t.toUpperCase();
            headerHtml += `<th class="val">${escapeHtml(label)}</th>`;
        });
        thead.innerHTML = headerHtml;

        if (!state.accounts || state.accounts.length === 0) {
            body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" style="text-align: center; opacity: 0.5;">No accounts found for ${escapeHtml(state.activeChain)}</td></tr>`;
            return;
        }

        body.innerHTML = state.accounts.map(acc => {
            const cached = state.balanceCache[acc.address] || {};
            return `
                <tr data-address="${escapeHtml(acc.address)}">
                    <td><span class="tag-badge">${escapeHtml(acc.tag)}</span></td>
                    <td class="address-cell" onclick="copyToClipboard('${escapeHtml(acc.address)}')">${escapeHtml(shortenAddr(acc.address))}</td>
                    <td>${escapeHtml(acc.type)}</td>
                    ${allTokens.map(t => {
                const isActive = state.activeTokens.has(t);
                if (!isActive) {
                    return `<td class="val balance-cell" data-token="${t}" style="opacity: 0.3;">-</td>`;
                }
                const bal = cached[t];
                if (bal !== undefined && bal !== null) {
                    return `<td class="val balance-cell" data-token="${t}">${escapeHtml(bal)}</td>`;
                }
                return `<td class="val balance-cell" data-token="${t}"><span class="cell-spinner"></span></td>`;
            }).join('')}
                </tr>
            `;
        }).join('');
    }

    async function fetchBalancesForTokens(tokensList) {
        if (tokensList.length === 0) return;

        const tokensParam = tokensList.join(',');

        try {
            const resp = await authFetch(`/api/accounts?chain=${state.activeChain}&tokens=${encodeURIComponent(tokensParam)}`);
            const data = await resp.json();

            // Update cache
            data.forEach(acc => {
                if (!state.balanceCache[acc.address]) {
                    state.balanceCache[acc.address] = {};
                }
                tokensList.forEach(t => {
                    // Store balance even if null (so we don't keep showing spinner)
                    const bal = acc.balances[t];
                    state.balanceCache[acc.address][t] = bal !== null && bal !== undefined ? bal : '-';
                });
            });

            // Re-render to show updated balances
            renderAccounts();
        } catch (err) {
            console.error('Error loading balances:', err);
            // On error, set dashes for the failed tokens
            state.accounts.forEach(acc => {
                if (!state.balanceCache[acc.address]) {
                    state.balanceCache[acc.address] = {};
                }
                tokensList.forEach(t => {
                    if (state.balanceCache[acc.address][t] === undefined) {
                        state.balanceCache[acc.address][t] = '-';
                    }
                });
            });
            renderAccounts();
        }
    }

    async function loadTransactions() {
        try {
            const resp = await authFetch(`/api/transactions?chain=${state.activeChain}`);
            const data = await resp.json();
            const body = document.getElementById('tx-body');
            body.innerHTML = data.map(tx => `
                <tr>
                    <td>${escapeHtml(tx.timestamp.split('T')[1].split('.')[0])}</td>
                    <td>${escapeHtml(tx.chain)}</td>
                    <td class="address-cell" title="${escapeHtml(tx.from)}">${escapeHtml(formatAddressOrTag(tx.from))}</td>
                    <td class="address-cell" title="${escapeHtml(tx.to)}">${escapeHtml(formatAddressOrTag(tx.to))}</td>
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

    async function loadRPCStatus(showLoading = false) {
        const container = document.getElementById('rpc-cards');

        if (showLoading || !container.innerHTML || container.innerHTML.includes('No data')) {
            container.innerHTML = `<div class="rpc-card glass" style="text-align: center; padding: 2rem;"><span class="loading-spinner"></span> Loading RPC status...</div>`;
        }

        try {
            const resp = await authFetch('/api/rpc-status');
            const status = await resp.json();
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
                </div>
            `).join('');
        } catch (err) {
            console.error(err);
            if (!container.innerHTML || container.innerHTML.includes('Loading')) {
                container.innerHTML = `<div class="rpc-card glass" style="text-align: center; color: #e74c3c;">Error loading RPC status</div>`;
            }
        }
    }

    function updateFormSelectors(preserveToken = false) {
        const fromSelect = document.getElementById('tx-from');
        const toSelect = document.getElementById('tx-to');
        const tokenSelect = document.getElementById('tx-token');
        const nativeSymbol = getNativeCurrencySymbol();
        const chainTokens = state.tokens[state.activeChain] || [];

        // Save current selections
        const prevToken = tokenSelect.value;

        fromSelect.innerHTML = state.accounts.map(acc =>
            `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`
        ).join('');

        toSelect.innerHTML = state.accounts.map(acc =>
            `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`
        ).join('');

        tokenSelect.innerHTML = `<option value="native">${escapeHtml(nativeSymbol)}</option>` +
            chainTokens.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t.toUpperCase())}</option>`).join('');

        // Restore token selection if requested and valid
        if (preserveToken && prevToken) {
            const options = Array.from(tokenSelect.options).map(o => o.value);
            if (options.includes(prevToken)) {
                tokenSelect.value = prevToken;
            }
        }
    }

    // EOA Modal Logic
    const eoaModal = document.getElementById('eoa-modal');
    const closeEoaModal = document.getElementById('close-eoa-modal');
    const createEoaForm = document.getElementById('create-eoa-form');

    createEoaBtn.addEventListener('click', () => {
        eoaModal.classList.add('active');
        document.getElementById('eoa-tag').value = '';
    });

    closeEoaModal.addEventListener('click', () => {
        eoaModal.classList.remove('active');
    });

    createEoaForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = createEoaForm.querySelector('button[type="submit"]');
        const originalText = btn.innerText;
        btn.innerText = 'Creating...';
        btn.disabled = true;

        const tag = document.getElementById('eoa-tag').value || null;

        try {
            const resp = await authFetch('/api/accounts/eoa', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tag })
            });
            if (resp.ok) {
                showToast("EOA Created", "success");
                eoaModal.classList.remove('active');
                createEoaForm.reset();
                // Reload accounts list (new account will show spinners until balances load)
                loadAccounts();
            } else {
                const err = await resp.json();
                showToast(`Error: ${err.detail}`, "error");
            }
        } catch (err) {
            showToast("Error creating EOA", "error");
        } finally {
            btn.innerText = originalText;
            btn.disabled = false;
        }
    });

    // Safe Modal Logic
    const safeModal = document.getElementById('safe-modal');
    const closeSafeModal = document.getElementById('close-safe-modal');
    const createSafeForm = document.getElementById('create-safe-form');

    createSafeBtn.addEventListener('click', () => {
        safeModal.classList.add('active');
        document.getElementById('safe-tag').value = `Safe ${state.accounts.length + 1}`;
        populateSafeOwners();
    });

    closeSafeModal.addEventListener('click', () => {
        safeModal.classList.remove('active');
    });

    function populateSafeOwners() {
        const container = document.getElementById('safe-owners-list');
        if (!state.accounts || state.accounts.length === 0) {
            container.innerHTML = '<span style="color: var(--text-muted); font-size: 0.9rem;">No accounts available</span>';
            return;
        }
        container.innerHTML = state.accounts.map(acc => `
            <label class="checkbox-item">
                <input type="checkbox" name="safe-owner" value="${escapeHtml(acc.tag)}">
                ${escapeHtml(acc.tag)}
            </label>
        `).join('');
    }

    function populateSafeChains() {
        const container = document.getElementById('safe-chains-list');
        container.innerHTML = state.chains.map(c => `
            <label class="checkbox-item">
                <input type="checkbox" name="safe-chain" value="${c}" ${c === state.activeChain ? 'checked' : ''}>
                ${c.toUpperCase()}
            </label>
        `).join('');
    }

    createSafeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = createSafeForm.querySelector('button[type="submit"]');
        const originalText = btn.innerText;
        btn.innerText = 'Deploying...';
        btn.disabled = true;

        const tag = document.getElementById('safe-tag').value;
        const threshold = parseInt(document.getElementById('safe-threshold').value);

        // Get selected owners from checkboxes
        const owners = Array.from(document.querySelectorAll('input[name="safe-owner"]:checked')).map(cb => cb.value);
        const selectedChains = Array.from(document.querySelectorAll('input[name="safe-chain"]:checked')).map(cb => cb.value);

        if (owners.length === 0) {
            showToast("Select at least one owner", "error");
            btn.innerText = originalText;
            btn.disabled = false;
            return;
        }

        if (selectedChains.length === 0) {
            showToast("Select at least one chain", "error");
            btn.innerText = originalText;
            btn.disabled = false;
            return;
        }

        if (threshold > owners.length) {
            showToast("Threshold cannot exceed number of owners", "error");
            btn.innerText = originalText;
            btn.disabled = false;
            return;
        }

        try {
            const resp = await authFetch('/api/accounts/safe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tag, threshold, owners, chains: selectedChains })
            });
            if (resp.ok) {
                showToast("Safe Deployment Started", "success");
                safeModal.classList.remove('active');
                createSafeForm.reset();
                // Reload transactions immediately to show deployment
                loadTransactions();
                // Reload accounts after delay
                setTimeout(() => {
                    loadAccounts();
                }, 5000);
            } else {
                const err = await resp.json();
                showToast(`Error: ${err.detail}`, "error");
            }
        } catch (err) {
            showToast("Error deploying Safe", "error");
        } finally {
            btn.innerText = originalText;
            btn.disabled = false;
        }
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
            const resp = await authFetch('/api/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await resp.json();
            if (resp.ok) {
                const hashDisplay = result.hash ? `Hash: ${result.hash.substring(0, 10)}...` : 'Transaction submitted';
                showToast(`Success! ${hashDisplay}`, 'success');
                // Reset form but preserve token selection
                const selectedToken = document.getElementById('tx-token').value;
                sendForm.reset();
                document.getElementById('tx-token').value = selectedToken;
                loadTransactions();
                // Refresh balances after transaction
                state.balanceCache = {};
                fetchBalancesForTokens(Array.from(state.activeTokens));
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
        // Only shorten if it looks like an Ethereum address
        if (addr.startsWith('0x') && addr.length === 42) {
            return addr.substring(0, 6) + '...' + addr.substring(addr.length - 4);
        }
        return addr;
    }

    // Format address or tag for display
    function formatAddressOrTag(value) {
        if (!value) return '';
        // If it looks like an address, shorten it
        if (value.startsWith('0x') && value.length === 42) {
            return shortenAddr(value);
        }
        // Otherwise it's a tag, show it fully
        return value;
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

    // ===== CowSwap Functions =====
    const swapForm = document.getElementById('swap-form');
    const swapModeRadios = document.querySelectorAll('input[name="swap-mode"]');
    const sellCard = document.getElementById('sell-card');
    const buyCard = document.getElementById('buy-card');
    const sellAmountInput = document.getElementById('swap-sell-amount');
    const buyAmountInput = document.getElementById('swap-buy-amount');
    const swapMaxSellBtn = document.getElementById('swap-max-sell');
    const swapMaxBuyBtn = document.getElementById('swap-max-buy');
    let quoteTimeout = null;

    function populateSwapForm() {
        const accountSelect = document.getElementById('swap-account');
        const sellTokenSelect = document.getElementById('swap-sell-token');
        const buyTokenSelect = document.getElementById('swap-buy-token');

        // Populate accounts
        accountSelect.innerHTML = state.accounts.map(acc =>
            `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`
        ).join('');

        // Populate tokens (only ERC20, no native for CowSwap)
        const chainTokens = state.tokens[state.activeChain] || [];
        const tokenOptions = chainTokens.map(t =>
            `<option value="${escapeHtml(t)}">${escapeHtml(t.toUpperCase())}</option>`
        ).join('');

        sellTokenSelect.innerHTML = tokenOptions;
        buyTokenSelect.innerHTML = tokenOptions;

        // Set different default values for sell and buy
        if (chainTokens.length >= 2) {
            sellTokenSelect.value = chainTokens[0];
            buyTokenSelect.value = chainTokens[1];
        }

        // Initialize card states
        updateCardStates();
    }

    function updateCardStates() {
        const mode = document.querySelector('input[name="swap-mode"]:checked').value;
        if (mode === 'sell') {
            // Sell mode: sell amount editable, buy amount read-only (no spinners)
            sellAmountInput.removeAttribute('readonly');
            sellAmountInput.classList.remove('no-spinners');
            buyAmountInput.setAttribute('readonly', 'true');
            buyAmountInput.classList.add('no-spinners');
            sellCard.classList.add('active');
            buyCard.classList.remove('active');
            if (swapMaxSellBtn) swapMaxSellBtn.style.display = '';
            if (swapMaxBuyBtn) swapMaxBuyBtn.style.display = 'none';
        } else {
            // Buy mode: buy amount editable, sell amount read-only (no spinners)
            buyAmountInput.removeAttribute('readonly');
            buyAmountInput.classList.remove('no-spinners');
            sellAmountInput.setAttribute('readonly', 'true');
            sellAmountInput.classList.add('no-spinners');
            buyCard.classList.add('active');
            sellCard.classList.remove('active');
            if (swapMaxSellBtn) swapMaxSellBtn.style.display = 'none';
            if (swapMaxBuyBtn) swapMaxBuyBtn.style.display = '';
        }
    }

    // Update card states when mode changes
    swapModeRadios.forEach(radio => {
        radio.addEventListener('change', () => {
            updateCardStates();
            // Clear amounts
            sellAmountInput.value = '';
            buyAmountInput.value = '';
        });
    });

    // Debounced quote fetching
    async function fetchQuote() {
        const mode = document.querySelector('input[name="swap-mode"]:checked').value;
        const account = document.getElementById('swap-account').value;
        const sellToken = document.getElementById('swap-sell-token').value;
        const buyToken = document.getElementById('swap-buy-token').value;

        let inputAmount, outputField;
        if (mode === 'sell') {
            inputAmount = parseFloat(sellAmountInput.value);
            outputField = buyAmountInput;
        } else {
            inputAmount = parseFloat(buyAmountInput.value);
            outputField = sellAmountInput;
        }

        if (!account || !sellToken || !buyToken || !inputAmount || inputAmount <= 0) {
            outputField.value = '';
            return;
        }

        outputField.value = '...';

        try {
            const params = new URLSearchParams({
                account,
                sell_token: sellToken,
                buy_token: buyToken,
                amount: inputAmount,
                mode,
                chain: state.activeChain
            });
            const resp = await authFetch(`/api/swap/quote?${params}`);
            const result = await resp.json();
            if (resp.ok) {
                outputField.value = result.amount.toFixed(4);
            } else {
                outputField.value = '';
                showToast(result.detail || 'Error getting quote', 'error');
            }
        } catch (err) {
            outputField.value = '';
        }
    }

    // Add input listeners for auto-quote
    function setupAmountListeners() {
        const debouncedFetch = () => {
            clearTimeout(quoteTimeout);
            quoteTimeout = setTimeout(fetchQuote, 500);
        };

        if (sellAmountInput) {
            sellAmountInput.addEventListener('input', debouncedFetch);
        }
        if (buyAmountInput) {
            buyAmountInput.addEventListener('input', debouncedFetch);
        }
    }

    setupAmountListeners();

    // Handle Max Sell button click
    async function handleMaxClick(isSellMode) {
        const account = document.getElementById('swap-account').value;
        const sellToken = document.getElementById('swap-sell-token').value;
        const buyToken = document.getElementById('swap-buy-token').value;
        const btn = isSellMode ? swapMaxSellBtn : swapMaxBuyBtn;
        const targetInput = isSellMode ? sellAmountInput : buyAmountInput;

        if (!account || !sellToken || !buyToken) {
            showToast('Select account and tokens first', 'error');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<span class="btn-spinner"></span>';

        try {
            const params = new URLSearchParams({
                account,
                sell_token: sellToken,
                buy_token: buyToken,
                mode: isSellMode ? 'sell' : 'buy',
                chain: state.activeChain
            });
            const resp = await authFetch(`/api/swap/max-amount?${params}`);
            const result = await resp.json();
            if (resp.ok) {
                targetInput.value = result.max_amount.toFixed(4);
                // Trigger quote fetch
                fetchQuote();
            } else {
                showToast(result.detail || 'Error getting max amount', 'error');
            }
        } catch (err) {
            showToast('Network error fetching max amount', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = 'Max';
        }
    }

    if (swapMaxSellBtn) {
        swapMaxSellBtn.addEventListener('click', () => handleMaxClick(true));
    }
    if (swapMaxBuyBtn) {
        swapMaxBuyBtn.addEventListener('click', () => handleMaxClick(false));
    }

    // Handle swap form submission
    if (swapForm) {
        swapForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = swapForm.querySelector('button[type="submit"]');
            const originalText = btn.innerText;
            btn.innerText = 'Swapping...';
            btn.disabled = true;

            const swapMode = document.querySelector('input[name="swap-mode"]:checked').value;
            const amount = swapMode === 'sell'
                ? parseFloat(sellAmountInput.value)
                : parseFloat(buyAmountInput.value);

            const payload = {
                account: document.getElementById('swap-account').value,
                sell_token: document.getElementById('swap-sell-token').value,
                buy_token: document.getElementById('swap-buy-token').value,
                amount: amount,
                order_type: swapMode,
                chain: state.activeChain
            };

            try {
                const resp = await authFetch('/api/swap', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await resp.json();
                if (resp.ok) {
                    showToast(result.message || 'Swap order placed!', 'success');
                    sellAmountInput.value = '';
                    buyAmountInput.value = '';
                } else {
                    showToast(`Error: ${result.detail}`, 'error');
                }
            } catch (err) {
                showToast('Network error during swap', 'error');
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        });
    }

    // Populate swap form when switching to CowSwap tab
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'cowswap') {
                populateSwapForm();
            }
        });
    });

    init();
});
