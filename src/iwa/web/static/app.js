document.addEventListener("DOMContentLoaded", () => {
  const state = {
    activeChain: localStorage.getItem("iwa_active_chain") || "gnosis",
    activeTab: localStorage.getItem("iwa_active_tab") || "dashboard",
    chains: [],
    tokens: {},
    nativeCurrencies: {},
    accounts: [], // Basic account info
    balanceCache: {}, // { address: { native: "1.00", OLAS: "50.00", ... } }
    authToken: sessionStorage.getItem("iwa_auth_token") || "",
    activeTokens: new Set(["native", "OLAS"]), // Default: native and OLAS
    olasServicesCache: {}, // { chain: [services] }
    stakingContractsCache: null, // Cached staking contracts
    olasPriceCache: null, // Cached OLAS price in EUR
    whitelist: {}, // { tag: address } from config
  };

  // Real-time countdown updater for unstake availability
  function updateUnstakeCountdowns() {
    document.querySelectorAll("[data-unstake-at]").forEach((el) => {
      const targetTime = new Date(el.dataset.unstakeAt);
      const diffMs = targetTime - new Date();
      if (diffMs <= 0) {
        el.innerHTML = '<span class="text-success font-bold">AVAILABLE</span>';
        el.removeAttribute("data-unstake-at");
      } else {
        const totalMins = Math.ceil(diffMs / 60000);
        const hours = Math.floor(totalMins / 60);
        const mins = totalMins % 60;
        el.textContent = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
      }
    });
  }
  // Update every minute
  setInterval(updateUnstakeCountdowns, 60000);

  // DOM Elements
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");
  const activeChainSelect = document.getElementById("active-chain");
  const refreshBtn = document.getElementById("refresh-btn");
  const createEoaBtn = document.getElementById("create-eoa-btn");
  const createSafeBtn = document.getElementById("create-safe-btn");
  const sendForm = document.getElementById("send-tx-form");
  const tokenTogglesContainer = document.getElementById("token-toggles");

  // Login modal handling
  let loginResolver = null;
  const loginModal = document.getElementById("login-modal");
  const loginForm = document.getElementById("login-form");
  const loginPasswordInput = document.getElementById("login-password");

  function showLoginModal() {
    return new Promise((resolve) => {
      loginResolver = resolve;
      loginPasswordInput.value = "";
      loginModal.classList.add("active");
      loginPasswordInput.focus();
    });
  }

  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const pwd = loginPasswordInput.value;
      loginModal.classList.remove("active");
      if (loginResolver) {
        loginResolver(pwd);
        loginResolver = null;
      }
    });
  }

  // Close login modal on backdrop click
  if (loginModal) {
    loginModal.addEventListener("click", (e) => {
      if (e.target === loginModal) {
        loginModal.classList.remove("active");
        if (loginResolver) {
          loginResolver(null);
          loginResolver = null;
        }
      }
    });
  }

  // Unified Fetch with Auth
  async function authFetch(url, options = {}) {
    if (state.authToken) {
      options.headers = {
        ...options.headers,
        Authorization: `Bearer ${state.authToken}`,
      };
    }

    const resp = await fetch(url, options);

    if (resp.status === 401) {
      const pwd = await showLoginModal();
      if (pwd) {
        state.authToken = pwd;
        sessionStorage.setItem("iwa_auth_token", pwd);
        return authFetch(url, options);
      }
    }
    return resp;
  }

  const escapeHtml = (str) => {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  };

  // Format balance to 2 decimals
  function formatBalance(value) {
    if (value === null || value === undefined || value === "-") return value;
    const num = parseFloat(value);
    if (isNaN(num)) return value;
    return num.toFixed(2);
  }

  function getNativeCurrencySymbol() {
    return state.nativeCurrencies[state.activeChain] || "Native";
  }

  function getAllTokenColumns() {
    const nativeSymbol = getNativeCurrencySymbol();
    const chainTokens = state.tokens[state.activeChain] || [];
    return ["native", ...chainTokens];
  }

  // Initialize
  async function init() {
    try {
      const resp = await authFetch("/api/state");
      const data = await resp.json();
      state.chains = data.chains;
      state.tokens = data.tokens;
      state.nativeCurrencies = data.native_currencies || {};
      state.whitelist = data.whitelist || {};

      // Update status indicator for testing mode
      const statusText = document.getElementById("status-text");
      if (data.testing) {
        statusText.textContent = "Testing";
        statusText.style.color = "var(--warning-color)";
      } else {
        statusText.textContent = "Connected";
      }

      // Restore saved chain or use default
      const savedChain = localStorage.getItem("iwa_active_chain");
      state.activeChain =
        savedChain && data.chains.includes(savedChain)
          ? savedChain
          : data.default_chain;

      populateChainSelect();
      populateTokenToggles();
      updateFormSelectors();

      // Restore saved tab
      // Restore saved tab or default to "dashboard"
      const savedTab = localStorage.getItem("iwa_active_tab");
      if (savedTab && document.getElementById(savedTab)) {
        activateTab(savedTab);
      } else {
        // Fallback or explicit default
        activateTab("dashboard");
      }

      // Initial load
      loadAccounts();
      loadTransactions();
      loadOlasServices(); // Preload Olas services
      preloadStakingContracts(); // Preload staking contracts

      // Setup Safe chains
      populateSafeChains();
    } catch (err) {
      console.error("Init error:", err);
      showToast("Error initializing: " + escapeHtml(err.message), "error");
    }
  }

  // Preload staking contracts for fast modal opening
  async function preloadStakingContracts() {
    try {
      const resp = await authFetch("/api/olas/staking-contracts?chain=gnosis");
      state.stakingContractsCache = await resp.json();
    } catch (err) {
      console.error("Failed to preload staking contracts:", err);
    }
  }

  // Tab Switching Logic
  function activateTab(tabId) {
    if (!document.getElementById(tabId)) return;

    // Update State & Storage
    state.activeTab = tabId;
    localStorage.setItem("iwa_active_tab", tabId);

    // Update UI
    tabBtns.forEach((b) => b.classList.remove("active"));
    tabPanes.forEach((p) => p.classList.remove("active"));

    const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
    if (btn) btn.classList.add("active");

    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add("active");

    // Tab-specific data loading
    if (tabId === "rpc") {
      loadRPCStatus(true);
    } else if (tabId === "cowswap") {
      populateSwapForm();
      loadMasterBalanceTable();
    }
  }

  // Event Listeners for Tabs
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      activateTab(btn.dataset.tab);
    });
  });

  // Chain Change Handling
  activeChainSelect.addEventListener("change", (e) => {
    state.activeChain = e.target.value;
    localStorage.setItem("iwa_active_chain", e.target.value);
    state.balanceCache = {}; // Clear cache on chain change
    populateTokenToggles();
    loadAccounts();
    loadTransactions();
    updateFormSelectors();
  });

  // Refresh button - forces full reload
  refreshBtn.addEventListener("click", () => {
    showToast(`Refreshing balances...`, "info");
    state.balanceCache = {}; // Clear cache
    loadAccounts();
    fetchBalancesForTokens(Array.from(state.activeTokens));
  });

  function populateChainSelect() {
    activeChainSelect.innerHTML = state.chains
      .map(
        (c) =>
          `<option value="${c}" ${c === state.activeChain ? "selected" : ""}>${c.charAt(0).toUpperCase() + c.slice(1)}</option>`,
      )
      .join("");
  }

  function populateTokenToggles() {
    const chainTokens = state.tokens[state.activeChain] || [];
    const nativeSymbol = getNativeCurrencySymbol();

    let html = `
            <label class="token-toggle ${state.activeTokens.has("native") ? "active" : ""}">
                <input type="checkbox" value="native" ${state.activeTokens.has("native") ? "checked" : ""}>
                ${escapeHtml(nativeSymbol)}
            </label>
        `;

    for (const token of chainTokens) {
      html += `
                <label class="token-toggle ${state.activeTokens.has(token) ? "active" : ""}">
                    <input type="checkbox" value="${escapeHtml(token)}" ${state.activeTokens.has(token) ? "checked" : ""}>
                    ${escapeHtml(token.toUpperCase())}
                </label>
            `;
    }

    tokenTogglesContainer.innerHTML = html;

    // Add event listeners
    tokenTogglesContainer
      .querySelectorAll('input[type="checkbox"]')
      .forEach((cb) => {
        cb.addEventListener("change", (e) => {
          const tokenName = e.target.value;
          if (e.target.checked) {
            state.activeTokens.add(tokenName);
            e.target.parentElement.classList.add("active");
            // Re-render immediately to show spinners
            renderAccounts();
            // Then fetch balances (will re-render again when done)
            fetchBalancesForTokens([tokenName]);
          } else {
            state.activeTokens.delete(tokenName);
            e.target.parentElement.classList.remove("active");
            renderAccounts(); // Just re-render (hide this column's balances)
          }
        });
      });
  }

  function isTokenCached(tokenName) {
    // Check if we have balance data for this token
    for (const acc of state.accounts) {
      if (
        state.balanceCache[acc.address] &&
        state.balanceCache[acc.address][tokenName] !== undefined
      ) {
        return true;
      }
    }
    return false;
  }

  async function loadAccounts() {
    const body = document.getElementById("accounts-body");
    const allTokens = getAllTokenColumns();
    const nativeSymbol = getNativeCurrencySymbol();

    // Show loading
    body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" class="text-center"><span class="loading-spinner"></span> Loading accounts...</td></tr>`;

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
      body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" class="text-center text-error">Error loading accounts</td></tr>`;
    }
  }

  function renderAccounts() {
    const body = document.getElementById("accounts-body");
    const thead = document.querySelector("#accounts-table thead tr");
    const allTokens = getAllTokenColumns();
    const nativeSymbol = getNativeCurrencySymbol();

    // Build header with ALL token columns
    let headerHtml = `
            <th>Tag</th>
            <th>Address</th>
            <th>Type</th>
        `;
    allTokens.forEach((t) => {
      const label = t === "native" ? nativeSymbol : t.toUpperCase();
      headerHtml += `<th class="val">${escapeHtml(label)}</th>`;
    });
    thead.innerHTML = headerHtml;

    if (!state.accounts || state.accounts.length === 0) {
      body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" class="text-center opacity-50">No accounts found for ${escapeHtml(state.activeChain)}</td></tr>`;
      return;
    }

    body.innerHTML = state.accounts
      .map((acc) => {
        const cached = state.balanceCache[acc.address] || {};
        return `
                <tr data-address="${escapeHtml(acc.address)}">
                    <td><span class="tag-badge">${escapeHtml(acc.tag)}</span></td>
                    <td class="address-cell" data-action="copy" data-value="${escapeHtml(acc.address)}">${escapeHtml(shortenAddr(acc.address))}</td>
                    <td>${escapeHtml(acc.type)}</td>
                    ${allTokens
                      .map((t) => {
                        const isActive = state.activeTokens.has(t);
                        if (!isActive) {
                          return `<td class="val balance-cell opacity-30" data-token="${t}">-</td>`;
                        }
                        const bal = cached[t];
                        if (bal !== undefined && bal !== null) {
                          return `<td class="val balance-cell" data-token="${t}">${escapeHtml(formatBalance(bal))}</td>`;
                        }
                        return `<td class="val balance-cell" data-token="${t}"><span class="cell-spinner"></span></td>`;
                      })
                      .join("")}
                </tr>
            `;
      })
      .join("");
  }

  async function fetchBalancesForTokens(tokensList) {
    if (tokensList.length === 0) return;

    const tokensParam = tokensList.join(",");

    try {
      const resp = await authFetch(
        `/api/accounts?chain=${state.activeChain}&tokens=${encodeURIComponent(tokensParam)}`,
      );
      const data = await resp.json();

      // Update cache
      data.forEach((acc) => {
        if (!state.balanceCache[acc.address]) {
          state.balanceCache[acc.address] = {};
        }
        tokensList.forEach((t) => {
          // Store balance even if null (so we don't keep showing spinner)
          const bal = acc.balances[t];
          state.balanceCache[acc.address][t] =
            bal !== null && bal !== undefined ? bal : "-";
        });
      });

      // Re-render to show updated balances
      renderAccounts();
    } catch (err) {
      console.error("Error loading balances:", err);
      // On error, set dashes for the failed tokens
      state.accounts.forEach((acc) => {
        if (!state.balanceCache[acc.address]) {
          state.balanceCache[acc.address] = {};
        }
        tokensList.forEach((t) => {
          if (state.balanceCache[acc.address][t] === undefined) {
            state.balanceCache[acc.address][t] = "-";
          }
        });
      });
      renderAccounts();
    }
  }

  async function loadTransactions() {
    try {
      const resp = await authFetch(
        `/api/transactions?chain=${state.activeChain}`,
      );
      const data = await resp.json();
      const body = document.getElementById("tx-body");
      body.innerHTML = data
        .map(
          (tx) => `
                <tr>
                    <td>${escapeHtml(new Date(tx.timestamp).toLocaleString().replace(",", ""))}</td>
                    <td>${escapeHtml(tx.chain)}</td>
                    <td class="address-cell" title="${escapeHtml(tx.from)}">${escapeHtml(formatAddressOrTag(tx.from))}</td>
                    <td class="address-cell" title="${escapeHtml(tx.to)}">${escapeHtml(formatAddressOrTag(tx.to))}</td>
                    <td>${escapeHtml(tx.token.toUpperCase())}</td>
                    <td class="val">${escapeHtml(formatBalance(tx.amount))}</td>
                    <td class="val">${escapeHtml(formatBalance(tx.value_eur))}</td>
                    <td><span class="text-success">${escapeHtml(tx.status)}</span></td>
                    <td class="address-cell" data-action="copy" data-value="${escapeHtml(tx.hash)}">${escapeHtml(tx.hash.substring(0, 10))}...</td>
                    <td>${escapeHtml(tx.gas_cost)}</td>
                    <td>${escapeHtml(formatBalance(tx.gas_value_eur))}</td>
                    <td class="tags-cell">${(tx.tags || []).map((t) => `<span class="tag-badge">${escapeHtml(t)}</span>`).join("")}</td>
                </tr>
            `,
        )
        .join("");
    } catch (err) {
      console.error(err);
    }
  }

  async function loadRPCStatus(showLoading = false) {
    const container = document.getElementById("rpc-cards");

    if (
      showLoading ||
      !container.innerHTML ||
      container.innerHTML.includes("No data")
    ) {
      container.innerHTML = `<div class="rpc-card glass text-center mb-2"><span class="loading-spinner"></span> Loading RPC status...</div>`;
    }

    try {
      const resp = await authFetch("/api/rpc-status");
      const status = await resp.json();
      container.innerHTML = Object.entries(status)
        .map(
          ([name, data]) => `
                <div class="rpc-card glass">
                    <div class="rpc-header">
                        <h3>${escapeHtml(name.toUpperCase())}</h3>
                        <span class="status-indicator ${escapeHtml(data.status)}"></span>
                    </div>
                    <div class="rpc-meta">
                        <span>Status:</span>
                        <span class="${data.status === "online" ? "text-success" : "text-error"}">${escapeHtml(data.status.toUpperCase())}</span>
                    </div>
                    ${data.block ? `<div class="rpc-meta"><span>Block:</span><span>${escapeHtml(String(data.block))}</span></div>` : ""}
                    ${data.latency ? `<div class="rpc-meta"><span>Latency:</span><span class="accent-color">${escapeHtml(data.latency)}</span></div>` : ""}
                </div>
            `,
        )
        .join("");
    } catch (err) {
      console.error(err);
      if (!container.innerHTML || container.innerHTML.includes("Loading")) {
        container.innerHTML = `<div class="rpc-card glass text-center text-error">Error loading RPC status</div>`;
      }
    }
  }

  function updateFormSelectors(preserveToken = false) {
    const fromSelect = document.getElementById("tx-from");
    const toSelect = document.getElementById("tx-to");
    const tokenSelect = document.getElementById("tx-token");
    const nativeSymbol = getNativeCurrencySymbol();
    const chainTokens = state.tokens[state.activeChain] || [];

    // Save current selections
    const prevToken = tokenSelect.value;

    fromSelect.innerHTML = state.accounts
      .map(
        (acc) =>
          `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`,
      )
      .join("");

    // Build To options: own accounts + whitelisted addresses
    const accountOptions = state.accounts
      .map(
        (acc) =>
          `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`,
      )
      .join("");
    const whitelistOptions = Object.entries(state.whitelist)
      .map(
        ([tag, addr]) =>
          `<option value="${escapeHtml(addr)}">${escapeHtml(tag)} (whitelist)</option>`,
      )
      .join("");
    toSelect.innerHTML =
      accountOptions +
      (whitelistOptions
        ? `<optgroup label="Whitelist">${whitelistOptions}</optgroup>`
        : "");

    tokenSelect.innerHTML =
      `<option value="native">${escapeHtml(nativeSymbol)}</option>` +
      chainTokens
        .map(
          (t) =>
            `<option value="${escapeHtml(t)}">${escapeHtml(t.toUpperCase())}</option>`,
        )
        .join("");

    // Restore token selection if requested and valid
    if (preserveToken && prevToken) {
      const options = Array.from(tokenSelect.options).map((o) => o.value);
      if (options.includes(prevToken)) {
        tokenSelect.value = prevToken;
      }
    }
  }

  // EOA Modal Logic
  const eoaModal = document.getElementById("eoa-modal");
  const closeEoaModal = document.getElementById("close-eoa-modal");
  const createEoaForm = document.getElementById("create-eoa-form");

  createEoaBtn.addEventListener("click", () => {
    eoaModal.classList.add("active");
    document.getElementById("eoa-tag").value = "";
  });

  closeEoaModal.addEventListener("click", () => {
    eoaModal.classList.remove("active");
  });

  createEoaForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = createEoaForm.querySelector('button[type="submit"]');
    const originalText = btn.innerText;
    btn.innerText = "Creating...";
    btn.disabled = true;

    const tag = document.getElementById("eoa-tag").value || null;

    try {
      const resp = await authFetch("/api/accounts/eoa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag }),
      });
      if (resp.ok) {
        showToast("EOA Created", "success");
        eoaModal.classList.remove("active");
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
  const safeModal = document.getElementById("safe-modal");
  const closeSafeModal = document.getElementById("close-safe-modal");
  const createSafeForm = document.getElementById("create-safe-form");

  createSafeBtn.addEventListener("click", () => {
    safeModal.classList.add("active");
    document.getElementById("safe-tag").value =
      `Safe ${state.accounts.length + 1}`;
    populateSafeOwners();
  });

  closeSafeModal.addEventListener("click", () => {
    safeModal.classList.remove("active");
  });

  function populateSafeOwners() {
    const container = document.getElementById("safe-owners-list");
    if (!state.accounts || state.accounts.length === 0) {
      container.innerHTML =
        '<span class="text-muted text-sm">No accounts available</span>';
      return;
    }
    container.innerHTML = state.accounts
      .map(
        (acc) => `
            <label class="checkbox-item">
                <input type="checkbox" name="safe-owner" value="${escapeHtml(acc.tag)}">
                ${escapeHtml(acc.tag)}
            </label>
        `,
      )
      .join("");
  }

  function populateSafeChains() {
    const container = document.getElementById("safe-chains-list");
    container.innerHTML = state.chains
      .map(
        (c) => `
            <label class="checkbox-item">
                <input type="checkbox" name="safe-chain" value="${c}" ${c === state.activeChain ? "checked" : ""}>
                ${c.toUpperCase()}
            </label>
        `,
      )
      .join("");
  }

  createSafeForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = createSafeForm.querySelector('button[type="submit"]');
    const originalText = btn.innerText;
    btn.innerText = "Deploying...";
    btn.disabled = true;

    const tag = document.getElementById("safe-tag").value;
    const threshold = parseInt(document.getElementById("safe-threshold").value);

    // Get selected owners from checkboxes
    const owners = Array.from(
      document.querySelectorAll('input[name="safe-owner"]:checked'),
    ).map((cb) => cb.value);
    const selectedChains = Array.from(
      document.querySelectorAll('input[name="safe-chain"]:checked'),
    ).map((cb) => cb.value);

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
      const resp = await authFetch("/api/accounts/safe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tag,
          threshold,
          owners,
          chains: selectedChains,
        }),
      });
      if (resp.ok) {
        showToast("Safe Deployment Started", "success");
        safeModal.classList.remove("active");
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

  sendForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = sendForm.querySelector("button");
    const originalText = btn.innerText;
    btn.innerText = "Sending...";
    btn.disabled = true;

    const payload = {
      from_address: document.getElementById("tx-from").value,
      to_address: document.getElementById("tx-to").value,
      amount_eth: parseFloat(document.getElementById("tx-amount").value),
      token: document.getElementById("tx-token").value,
      chain: state.activeChain,
    };

    try {
      const resp = await authFetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await resp.json();
      if (resp.ok) {
        const hashDisplay = result.hash
          ? `Hash: ${result.hash.substring(0, 10)}...`
          : "Transaction submitted";
        showToast(`Success! ${hashDisplay}`, "success");
        // Reset form but preserve token selection
        const selectedToken = document.getElementById("tx-token").value;
        sendForm.reset();
        document.getElementById("tx-token").value = selectedToken;
        loadTransactions();
        // Refresh balances after transaction
        state.balanceCache = {};
        fetchBalancesForTokens(Array.from(state.activeTokens));
      } else {
        showToast(`Error: ${result.detail}`, "error");
      }
    } catch (err) {
      showToast("Network error", "error");
    } finally {
      btn.innerText = originalText;
      btn.disabled = false;
    }
  });

  // Utils
  function shortenAddr(addr) {
    if (!addr) return "";
    // Only shorten if it looks like an Ethereum address
    if (addr.startsWith("0x") && addr.length === 42) {
      return addr.substring(0, 6) + "..." + addr.substring(addr.length - 4);
    }
    return addr;
  }

  // Format address or tag for display
  function formatAddressOrTag(value) {
    if (!value) return "";
    // If it looks like an address, shorten it
    if (value.startsWith("0x") && value.length === 42) {
      return shortenAddr(value);
    }
    // Otherwise it's a tag, show it fully
    return value;
  }

  function getExplorerUrl(address, chain) {
    if (!address) return "#";
    if (chain === "gnosis") return `https://gnosisscan.io/address/${address}`;
    if (chain === "base") return `https://basescan.org/address/${address}`;
    if (chain === "ethereum") return `https://etherscan.io/address/${address}`;
    return `https://gnosisscan.io/address/${address}`;
  }

  window.copyToClipboard = (text) => {
    navigator.clipboard.writeText(text).then(() => {
      showToast("Copied to clipboard", "info");
    });
  };

  function showToast(msg, type = "info", duration = 4000) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerText = msg;
    container.appendChild(toast);
    const remove = () => {
      if (toast.parentElement) toast.remove();
    };
    setTimeout(remove, duration);
    return remove;
  }

  // Custom themed confirm dialog
  function showConfirm(title, message) {
    return new Promise((resolve) => {
      const modal = document.getElementById("confirm-modal");
      const titleEl = document.getElementById("confirm-title");
      const messageEl = document.getElementById("confirm-message");
      const okBtn = document.getElementById("confirm-ok");
      const cancelBtn = document.getElementById("confirm-cancel");

      titleEl.textContent = title;
      messageEl.textContent = message;
      modal.classList.add("active");

      const cleanup = () => {
        modal.classList.remove("active");
        okBtn.onclick = null;
        cancelBtn.onclick = null;
      };

      okBtn.onclick = () => {
        cleanup();
        resolve(true);
      };

      cancelBtn.onclick = () => {
        cleanup();
        resolve(false);
      };
    });
  }

  // ===== CowSwap Functions =====
  const swapForm = document.getElementById("swap-form");
  const swapModeRadios = document.querySelectorAll('input[name="swap-mode"]');
  const sellCard = document.getElementById("sell-card");
  const buyCard = document.getElementById("buy-card");
  const sellAmountInput = document.getElementById("swap-sell-amount");
  const buyAmountInput = document.getElementById("swap-buy-amount");
  const swapMaxSellBtn = document.getElementById("swap-max-sell");
  const swapMaxBuyBtn = document.getElementById("swap-max-buy");
  let quoteTimeout = null;

  function populateSwapForm() {
    const sellTokenSelect = document.getElementById("swap-sell-token");
    const buyTokenSelect = document.getElementById("swap-buy-token");

    // Populate tokens (CowSwap supports ERC20s like WXDAI, but not native xDAI)
    const chainTokens = state.tokens[state.activeChain] || [];
    const tokenOptions = chainTokens
      .map(
        (t) =>
          `<option value="${escapeHtml(t)}">${escapeHtml(t.toUpperCase())}</option>`,
      )
      .join("");

    sellTokenSelect.innerHTML = tokenOptions;
    buyTokenSelect.innerHTML = tokenOptions;

    // Set default values (prefer WXDAI -> OLAS)
    if (chainTokens.includes("WXDAI") && chainTokens.includes("OLAS")) {
      sellTokenSelect.value = "WXDAI";
      buyTokenSelect.value = "OLAS";
    } else if (chainTokens.length >= 2) {
      sellTokenSelect.value = chainTokens[0];
      buyTokenSelect.value = chainTokens[1];
    }

    // Initialize card states
    updateCardStates();
  }

  function updateCardStates() {
    const mode = document.querySelector(
      'input[name="swap-mode"]:checked',
    ).value;
    if (mode === "sell") {
      // Sell mode: sell amount editable, buy amount read-only (no spinners)
      sellAmountInput.removeAttribute("readonly");
      sellAmountInput.classList.remove("no-spinners");
      buyAmountInput.setAttribute("readonly", "true");
      buyAmountInput.classList.add("no-spinners");
      sellCard.classList.add("active");
      buyCard.classList.remove("active");
      if (swapMaxSellBtn) swapMaxSellBtn.style.display = "";
      if (swapMaxBuyBtn) swapMaxBuyBtn.style.display = "none";
    } else {
      // Buy mode: buy amount editable, sell amount read-only (no spinners)
      buyAmountInput.removeAttribute("readonly");
      buyAmountInput.classList.remove("no-spinners");
      sellAmountInput.setAttribute("readonly", "true");
      sellAmountInput.classList.add("no-spinners");
      buyCard.classList.add("active");
      sellCard.classList.remove("active");
      if (swapMaxSellBtn) swapMaxSellBtn.style.display = "none";
      if (swapMaxBuyBtn) swapMaxBuyBtn.style.display = "";
    }
  }

  // Update card states when mode changes
  swapModeRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      updateCardStates();
      // Clear amounts
      sellAmountInput.value = "";
      buyAmountInput.value = "";
    });
  });

  // Swap tokens button handler (click on arrow to swap sell/buy)
  const swapTokensBtn = document.getElementById("swap-tokens-btn");
  if (swapTokensBtn) {
    swapTokensBtn.addEventListener("click", () => {
      const sellTokenSelect = document.getElementById("swap-sell-token");
      const buyTokenSelect = document.getElementById("swap-buy-token");

      // Swap token values
      const tempToken = sellTokenSelect.value;
      sellTokenSelect.value = buyTokenSelect.value;
      buyTokenSelect.value = tempToken;

      // Clear amounts since they need to be recalculated
      sellAmountInput.value = "";
      buyAmountInput.value = "";

      // Clear isMax flag
      delete sellAmountInput.dataset.isMax;
    });
  }

  // Debounced quote fetching
  async function fetchQuote() {
    const mode = document.querySelector(
      'input[name="swap-mode"]:checked',
    ).value;
    const account = "master";
    const sellToken = document.getElementById("swap-sell-token").value;
    const buyToken = document.getElementById("swap-buy-token").value;

    let inputAmount, outputField;
    if (mode === "sell") {
      inputAmount = parseFloat(sellAmountInput.value);
      outputField = buyAmountInput;
    } else {
      inputAmount = parseFloat(buyAmountInput.value);
      outputField = sellAmountInput;
    }

    if (
      !account ||
      !sellToken ||
      !buyToken ||
      !inputAmount ||
      inputAmount <= 0
    ) {
      outputField.value = "";
      return;
    }

    // Show loading indicator in output field
    outputField.value = "";
    outputField.placeholder = "Loading...";

    try {
      const params = new URLSearchParams({
        account,
        sell_token: sellToken,
        buy_token: buyToken,
        amount: inputAmount,
        mode,
        chain: state.activeChain,
      });
      const resp = await authFetch(`/api/swap/quote?${params}`);
      const result = await resp.json();
      if (resp.ok) {
        outputField.value = result.amount.toFixed(2);
      } else {
        outputField.value = "";
        showToast(result.detail || "Error getting quote", "error");
      }
    } catch (err) {
      outputField.value = "";
    } finally {
      outputField.placeholder = "0.00";
    }
  }

  // Add input listeners for auto-quote
  function setupAmountListeners() {
    const debouncedFetch = () => {
      clearTimeout(quoteTimeout);
      quoteTimeout = setTimeout(fetchQuote, 500);
    };

    if (sellAmountInput) {
      sellAmountInput.addEventListener("input", () => {
        // Clear the isMax flag when user manually edits the value
        delete sellAmountInput.dataset.isMax;
        debouncedFetch();
      });
    }
    if (buyAmountInput) {
      buyAmountInput.addEventListener("input", debouncedFetch);
    }

    // Also trigger quote on token change
    const sellTokenSelect = document.getElementById("swap-sell-token");
    const buyTokenSelect = document.getElementById("swap-buy-token");
    if (sellTokenSelect) {
      sellTokenSelect.addEventListener("change", debouncedFetch);
    }
    if (buyTokenSelect) {
      buyTokenSelect.addEventListener("change", debouncedFetch);
    }
  }

  setupAmountListeners();

  // Handle Max Sell button click
  async function handleMaxClick(isSellMode) {
    const account = "master";
    const sellToken = document.getElementById("swap-sell-token").value;
    const buyToken = document.getElementById("swap-buy-token").value;
    const btn = isSellMode ? swapMaxSellBtn : swapMaxBuyBtn;
    const targetInput = isSellMode ? sellAmountInput : buyAmountInput;

    if (!sellToken || !buyToken) {
      showToast("Select tokens first", "error");
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spinner"></span>';

    try {
      const params = new URLSearchParams({
        account,
        sell_token: sellToken,
        buy_token: buyToken,
        mode: isSellMode ? "sell" : "buy",
        chain: state.activeChain,
      });
      const resp = await authFetch(`/api/swap/max-amount?${params}`);
      const result = await resp.json();
      if (resp.ok) {
        // Use up to 6 decimals but remove trailing zeros
        targetInput.value = parseFloat(result.max_amount.toFixed(6));
        // Mark that this is a "max" amount to avoid precision loss
        if (isSellMode) {
          targetInput.dataset.isMax = "true";
        }
        // Trigger quote fetch
        fetchQuote();
      } else {
        showToast(result.detail || "Error getting max amount", "error");
      }
    } catch (err) {
      showToast("Network error fetching max amount", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = "Max";
    }
  }

  if (swapMaxSellBtn) {
    swapMaxSellBtn.addEventListener("click", () => handleMaxClick(true));
  }
  if (swapMaxBuyBtn) {
    swapMaxBuyBtn.addEventListener("click", () => handleMaxClick(false));
  }

  // Handle swap form submission
  if (swapForm) {
    swapForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = swapForm.querySelector('button[type="submit"]');
      const originalText = btn.innerText;
      btn.innerText = "Swapping...";
      btn.disabled = true;

      const swapMode = document.querySelector(
        'input[name="swap-mode"]:checked',
      ).value;

      // Check if user used Max button (to avoid float precision loss)
      const isMaxSell =
        swapMode === "sell" && sellAmountInput.dataset.isMax === "true";

      const amount = isMaxSell
        ? null // Send null to use exact wei balance on backend
        : swapMode === "sell"
          ? parseFloat(sellAmountInput.value)
          : parseFloat(buyAmountInput.value);

      const payload = {
        account: "master",
        sell_token: document.getElementById("swap-sell-token").value,
        buy_token: document.getElementById("swap-buy-token").value,
        amount_eth: amount,
        order_type: swapMode,
        chain: state.activeChain,
      };

      try {
        const resp = await authFetch("/api/swap", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const result = await resp.json();
        if (resp.ok) {
          let msg = result.message || "Swap executed!";
          if (result.analytics) {
            const execPrice =
              result.analytics.execution_price ||
              result.analytics.executed_buy_amount /
                result.analytics.executed_sell_amount;
            // value_change_pct comes from backend now

            msg += `\nPrice: ${execPrice.toFixed(4)}`;

            const valChange = result.analytics.value_change_pct;
            if (valChange !== undefined) {
              if (valChange === "N/A") {
                msg += `\nValue Change: N/A`;
              } else {
                msg += `\nValue Change: ${valChange > 0 ? "+" : ""}${valChange.toFixed(2)}%`;
              }
            }
          }
          showToast(msg, "success", 7000); // Longer duration for reading

          sellAmountInput.value = "";
          buyAmountInput.value = "";

          // Refresh orders immediately (balance refresh happens on fulfillment)
          loadRecentOrders();
        } else {
          showToast(`Error: ${result.detail}`, "error");
        }
      } catch (err) {
        showToast("Network error during swap", "error");
      } finally {
        btn.innerText = originalText;
        btn.disabled = false;
      }
    });
  }

  // Populate swap form when switching to CowSwap tab
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "cowswap") {
        populateSwapForm();
        populateWrapForm();
        loadMasterBalanceTable();
        loadRecentOrders();
      } else if (btn.dataset.tab === "olas") {
        loadOlasServices();
      }
    });
  });

  // Token symbol mapping cache
  const tokenSymbolCache = {};

  async function getTokenSymbol(address, chainTokens) {
    if (tokenSymbolCache[address]) return tokenSymbolCache[address];

    // Try to find in known tokens
    for (const [symbol, addr] of Object.entries(chainTokens || {})) {
      if (addr && addr.toLowerCase() === address.toLowerCase()) {
        tokenSymbolCache[address] = symbol;
        return symbol;
      }
    }

    // Return truncated address if not found
    return address.substring(0, 6) + "...";
  }

  function formatSecondsToTime(seconds) {
    if (seconds <= 0) return "Expired";
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  }

  function formatOrderDate(isoString) {
    if (!isoString) return "-";
    try {
      const date = new Date(isoString);
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      const hours = String(date.getHours()).padStart(2, "0");
      const mins = String(date.getMinutes()).padStart(2, "0");
      return `${year}-${month}-${day} ${hours}:${mins}`;
    } catch (e) {
      return "-";
    }
  }

  async function loadRecentOrders() {
    const tableBody = document.getElementById("recent-orders-body");
    if (!tableBody) return;

    // Do not show loading spinner if we already have content (prevents flicker)
    if (
      tableBody.children.length === 0 ||
      tableBody.innerHTML.includes("Loading...")
    ) {
      // Only show loading on initial load or if empty
      // tableBody.innerHTML = `<tr><td colspan="4" class="text-center"><span class="cell-spinner"></span> Loading...</td></tr>`;
    }

    let hasPendingOrders = false;

    try {
      const resp = await authFetch(
        `/api/swap/orders?chain=${state.activeChain}`,
      );
      if (!resp.ok) throw new Error("Failed to fetch orders");

      const data = await resp.json();
      const orders = data.orders || [];

      // Detect status transitions to "fulfilled" and refresh balances
      for (const order of orders) {
        const prevStatus = previousOrderStatuses[order.uid];
        if (
          prevStatus &&
          prevStatus !== "fulfilled" &&
          order.status === "fulfilled"
        ) {
          // Order just became fulfilled - refresh balances
          loadMasterBalanceTable(true);
          break; // Only need to refresh once per poll cycle
        }
        previousOrderStatuses[order.uid] = order.status;
      }

      if (orders.length === 0) {
        const noOrdersHtml = `<tr><td colspan="6" class="text-center text-muted">No recent orders</td></tr>`;
        if (tableBody.innerHTML !== noOrdersHtml) {
          tableBody.innerHTML = noOrdersHtml;
        }
        // Stop polling when no orders - will restart when new swap is placed
        isPolling = false;
        return;
      }

      let html = "";
      for (const order of orders) {
        // Use backend provided names (which are symbols) and formatted amounts
        const sellSymbol = order.sellToken;
        const buySymbol = order.buyToken;
        const sellAmt = order.sellAmount;
        const buyAmt = order.buyAmount;

        // Format creation date
        const dateStr = formatOrderDate(order.created);

        // Status badge class
        const statusClass = order.status
          .replace(/([A-Z])/g, "-$1")
          .toLowerCase();

        // Progress bar for open orders
        let progressHtml = "-";

        // Detect pending status for adaptive polling
        if (order.status === "open" || order.status === "presignaturePending") {
          if (order.timeRemaining > 0) {
            hasPendingOrders = true;
            progressHtml = `
                    <div class="order-progress">
                    <div class="progress-bar-container">
                        <div class="progress-bar" style="width: ${order.progressPct}%"></div>
                    </div>
                    <span class="progress-time" data-valid-to="${order.validTo}">${formatSecondsToTime(order.timeRemaining)}</span>
                    </div>
                `;
          } else {
            progressHtml = `<span class="text-muted">Expiring...</span>`;
            // Even if expiring, we might want to poll fast to catch the "expired" state update
            hasPendingOrders = true;
          }
        }

        // Build CowSwap explorer URL
        const explorerUrl = `https://explorer.cow.fi/gc/orders/${order.full_uid}`;
        const shortUid = order.uid;

        html += `
          <tr>
            <td class="text-muted">${dateStr}</td>
            <td><a href="${explorerUrl}" target="_blank" rel="noopener noreferrer" class="order-link">${escapeHtml(shortUid)}</a></td>
            <td><span class="order-status ${statusClass}">${order.status}</span></td>
            <td>${sellAmt} ${escapeHtml(sellSymbol)}</td>
            <td>${buyAmt} ${escapeHtml(buySymbol)}</td>
            <td>${progressHtml}</td>
          </tr>
        `;
      }

      // Only update DOM if content changed to avoid focus loss/scroll jumps
      if (tableBody.innerHTML !== html) {
        tableBody.innerHTML = html;
      }
    } catch (err) {
      console.error("Error loading orders:", err);
      // Don't wipe table on error, just log
    } finally {
      // Only continue polling if there are pending orders
      if (hasPendingOrders) {
        scheduleNextPoll(5000);
      } else {
        isPolling = false;
      }
    }
  }

  // Client-side countdown timer for smooth updates
  setInterval(() => {
    const timers = document.querySelectorAll(".progress-time[data-valid-to]");
    if (timers.length === 0) return;

    const now = Math.floor(Date.now() / 1000);

    timers.forEach((timer) => {
      const validTo = parseInt(timer.dataset.validTo);
      const remaining = validTo - now;

      if (remaining > 0) {
        timer.textContent = formatSecondsToTime(remaining);
      } else {
        timer.textContent = "Expiring...";
      }
    });
  }, 1000);

  // Adaptive polling for orders
  let ordersTimeoutId = null;
  let isPolling = false;
  const previousOrderStatuses = {}; // Track order status for detecting fulfilled transitions

  function scheduleNextPoll(delay) {
    if (ordersTimeoutId) clearTimeout(ordersTimeoutId);

    ordersTimeoutId = setTimeout(() => {
      const cowswapTab = document.getElementById("cowswap");
      if (cowswapTab && cowswapTab.classList.contains("active")) {
        loadRecentOrders();
      } else {
        // If tab not active, stop polling (it will resume on tab click)
        isPolling = false;
      }
    }, delay);
    isPolling = true;
  }

  function startOrdersPolling() {
    // Force immediate load and start cycle
    loadRecentOrders();
  }

  // Start polling
  startOrdersPolling();

  // Load Master Balance Table for CowSwap tab
  let masterTableLoadedChain = null;

  async function loadMasterBalanceTable(forceRefresh = false) {
    const tableBody = document.getElementById("cowswap-master-body");
    const headerRow = document.getElementById("cowswap-master-header");

    // Check if reload needed
    const currentChain = state.activeChain || "gnosis";
    if (
      !forceRefresh &&
      masterTableLoadedChain === currentChain &&
      tableBody.children.length > 0 &&
      !tableBody.innerHTML.includes("Loading")
    ) {
      return;
    }

    // Clear loading state
    tableBody.innerHTML = `<tr><td colspan="10" class="text-center"><span class="cell-spinner"></span> Loading master balances...</td></tr>`;

    // Determine tokens based on active chain
    const chain = currentChain;
    const nativeSymbol = state.nativeCurrencies[chain] || "Native";
    const erc20s = state.tokens[chain] || [];

    // Header Generation
    let headerHtml = "<th>Account</th>";
    headerHtml += `<th>${escapeHtml(nativeSymbol)}</th>`; // Native column
    erc20s.forEach((t) => {
      headerHtml += `<th>${escapeHtml(t)}</th>`;
    });
    headerRow.innerHTML = headerHtml;

    try {
      // Fetch balances for master only
      // Must include 'native' explicitly to get native balance
      const tokensToFetch = ["native", ...erc20s];
      const tokensParam = tokensToFetch.join(",");

      const resp = await authFetch(
        `/api/accounts?chain=${chain}&tokens=${tokensParam}`,
      );
      if (!resp.ok) throw new Error("Failed to fetch accounts");

      const accounts = await resp.json();
      const master = accounts.find((a) => a.tag === "master");

      const colSpan = 2 + erc20s.length; // Account + Native + ERC20s

      if (!master) {
        tableBody.innerHTML = `<tr><td colspan="${colSpan}" class="text-center">Master account not found</td></tr>`;
        return;
      }

      // Render Row
      let rowHtml = `
            <tr>
                <td class="account-cell" title="${master.address}">
                    <span class="tag-badge">${escapeHtml(master.tag)}</span>
                </td>
        `;

      // Native Balance (remove color classes)
      const nativeBalance =
        master.balances["native"] !== undefined ? master.balances["native"] : 0;
      rowHtml += `<td class="val font-bold">${formatBalance(nativeBalance)}</td>`;

      // ERC20 Balances (remove color classes)
      erc20s.forEach((token) => {
        const balance =
          master.balances && master.balances[token] !== undefined
            ? master.balances[token]
            : 0;
        rowHtml += `<td class="val">${formatBalance(balance)}</td>`;
      });

      rowHtml += `</tr>`;
      tableBody.innerHTML = rowHtml;
      masterTableLoadedChain = currentChain;
    } catch (err) {
      console.error("Error loading master table:", err);
      tableBody.innerHTML = `<tr><td colspan="10" class="text-center text-error">Error loading balances</td></tr>`;
      masterTableLoadedChain = null;
    }
  }

  // ===== Wrap/Unwrap Functions =====
  const wrapForm = document.getElementById("wrap-form");
  const wrapModeRadios = document.querySelectorAll('input[name="wrap-mode"]');
  const wrapAmountInput = document.getElementById("wrap-amount");
  const wrapMaxBtn = document.getElementById("wrap-max-btn");
  const wrapSubmitBtn = document.getElementById("wrap-submit-btn");

  function populateWrapForm() {
    // Nothing to populate - uses master account
  }

  function updateWrapButtonText() {
    if (!wrapSubmitBtn) return;
    const mode =
      document.querySelector('input[name="wrap-mode"]:checked')?.value ||
      "wrap";
    wrapSubmitBtn.textContent = mode === "wrap" ? "Wrap xDAI" : "Unwrap WXDAI";
  }

  // Mode change handler
  if (wrapModeRadios) {
    wrapModeRadios.forEach((radio) => {
      radio.addEventListener("change", () => {
        updateWrapButtonText();
        if (wrapAmountInput) wrapAmountInput.value = "";
      });
    });
  }

  // Max button handler - fetches balance from API
  if (wrapMaxBtn) {
    wrapMaxBtn.addEventListener("click", async () => {
      const mode =
        document.querySelector('input[name="wrap-mode"]:checked')?.value ||
        "wrap";

      wrapMaxBtn.disabled = true;
      wrapMaxBtn.innerHTML = '<span class="btn-spinner"></span>';

      try {
        const resp = await authFetch(
          `/api/swap/wrap/balance?account=master&chain=${state.activeChain}`,
        );
        if (resp.ok) {
          const data = await resp.json();
          const maxAmount = mode === "wrap" ? data.native : data.wxdai;
          if (wrapAmountInput && maxAmount > 0) {
            wrapAmountInput.value = maxAmount.toFixed(2);
          }
        }
      } catch (err) {
        console.error("Error getting max amount:", err);
      } finally {
        wrapMaxBtn.disabled = false;
        wrapMaxBtn.innerHTML = "Max";
      }
    });
  }

  // Form submission
  if (wrapForm) {
    wrapForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!wrapSubmitBtn) return;

      const originalText = wrapSubmitBtn.textContent;
      wrapSubmitBtn.textContent = "Processing...";
      wrapSubmitBtn.disabled = true;

      const mode =
        document.querySelector('input[name="wrap-mode"]:checked')?.value ||
        "wrap";
      const account = "master";
      const amount = parseFloat(wrapAmountInput.value);

      if (!account || !amount || amount <= 0) {
        showToast("Please enter a valid amount", "error");
        wrapSubmitBtn.textContent = originalText;
        wrapSubmitBtn.disabled = false;
        return;
      }

      const endpoint = mode === "wrap" ? "/api/swap/wrap" : "/api/swap/unwrap";
      const payload = {
        account: account,
        amount_eth: amount,
        chain: state.activeChain,
      };

      try {
        const resp = await authFetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const result = await resp.json();

        if (resp.ok) {
          const hashDisplay = result.hash
            ? `TX: ${result.hash.substring(0, 10)}...`
            : "";
          showToast(`${result.message} ${hashDisplay}`, "success", 5000);
          wrapAmountInput.value = "";

          // Refresh balances safely (don't fail the whole operation if this fails)
          try {
            await Promise.all([
              loadWrapBalances(),
              loadMasterBalanceTable(true),
            ]);
          } catch (e) {
            console.error("Error refreshing balances after wrap/unwrap:", e);
          }
        } else {
          showToast(`Error: ${result.detail}`, "error");
        }
      } catch (err) {
        console.error("Wrap/Unwrap error:", err);
        showToast("Network error during wrap/unwrap", "error");
      } finally {
        wrapSubmitBtn.textContent = originalText;
        wrapSubmitBtn.disabled = false;
      }
    });
  }

  // Update tab handler to include wrap form population
  const originalTabClickHandler = tabBtns.forEach.bind(tabBtns);
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "cowswap") {
        populateWrapForm();
      }
    });
  });

  // ===== Olas Services Functions =====
  const olasRefreshBtn = document.getElementById("refresh-olas-btn");
  if (olasRefreshBtn) {
    olasRefreshBtn.addEventListener("click", () => loadOlasServices(true));
  }

  window.loadOlasServices = async (forceRefresh = false) => {
    if (!state.activeChain) return;

    const container = document.getElementById("olas-services-container");
    if (!container) return;

    // Render cached data immediately if available (even on forceRefresh to prevent flash)
    if (
      state.olasServicesCache[state.activeChain] &&
      state.olasServicesCache[state.activeChain].length > 0
    ) {
      renderOlasSummaryAndCards(
        container,
        state.olasServicesCache[state.activeChain],
        state.olasPriceCache,
      );
    } else if (!state.olasServicesCache[state.activeChain]) {
      // Only show loading spinner if no data is visible
      container.innerHTML = `<div class="empty-state glass"><span class="loading-spinner"></span> Loading services...</div>`;
    }

    // If not force refresh and we have valid cache, we are done
    if (!forceRefresh && state.olasServicesCache[state.activeChain]) {
      return;
    }

    try {
      // Step 1: Fetch basic data and OLAS price in parallel
      const [basicResp, priceResp] = await Promise.all([
        authFetch(`/api/olas/services/basic?chain=${state.activeChain}`),
        authFetch("/api/olas/price"),
      ]);
      const basicServices = await basicResp.json();
      const priceData = await priceResp.json();

      // Cache price
      state.olasPriceCache = priceData.price_eur;

      // Handle API error response - if not OK, basicServices is an error object, not an array
      if (!basicResp.ok) {
        throw new Error(basicServices.detail || "Failed to load services");
      }

      if (!Array.isArray(basicServices) || basicServices.length === 0) {
        container.innerHTML = `<div class="empty-state glass"><p>No Olas services found for ${state.activeChain}.</p></div>`;
        return;
      }

      // Render cards immediately with spinners for dynamic fields
      renderOlasSummaryAndCards(
        container,
        basicServices,
        state.olasPriceCache,
        true,
      );

      // Step 2: Fetch full details per service in parallel
      const detailPromises = basicServices.map(async (service) => {
        try {
          const detailResp = await authFetch(
            `/api/olas/services/${service.key}/details`,
          );
          if (detailResp.ok) {
            const details = await detailResp.json();
            // Merge details into service
            return {
              ...service,
              state: details.state || service.state,
              accounts: details.accounts,
              staking: details.staking,
            };
          }
        } catch (e) {
          console.error(`Failed to load details for ${service.key}:`, e);
        }
        return service;
      });

      const fullServices = await Promise.all(detailPromises);

      // Cache the full results
      state.olasServicesCache[state.activeChain] = fullServices;

      // Re-render with full data
      renderOlasSummaryAndCards(
        container,
        fullServices,
        state.olasPriceCache,
        false,
      );

      // Trigger countdown update
      updateUnstakeCountdowns();
    } catch (err) {
      console.error("Error loading Olas services:", err);
      // If we have cached data, show it with a warning toast instead of breaking UI
      if (
        state.olasServicesCache[state.activeChain] &&
        state.olasServicesCache[state.activeChain].length > 0
      ) {
        showToast(`Failed to refresh services: ${err.message}`, "error");
        return;
      }
      container.innerHTML = `<div class="empty-state glass text-error"><p>Error loading services: ${escapeHtml(err.message)}</p></div>`;
    }
  };

  // Refresh a single service card without affecting others
  window.refreshSingleService = async (serviceKey) => {
    const cardElement = document.querySelector(
      `.service-card[data-service-key="${serviceKey}"]`,
    );
    if (!cardElement) return;

    // Find service in cache
    const cachedServices = state.olasServicesCache[state.activeChain] || [];
    const serviceIndex = cachedServices.findIndex((s) => s.key === serviceKey);
    if (serviceIndex === -1) {
      // Service not in cache, reload all
      loadOlasServices(true);
      return;
    }

    // Render card with loading state (spinners)
    const serviceData = cachedServices[serviceIndex];
    cardElement.outerHTML = renderOlasServiceCard(serviceData, true);

    // Also update summary to show loading
    renderOlasSummary(cachedServices, state.olasPriceCache, true);

    try {
      const detailResp = await authFetch(
        `/api/olas/services/${serviceKey}/details`,
      );
      if (detailResp.ok) {
        const details = await detailResp.json();
        // Merge details into cached service
        const updatedService = {
          ...serviceData,
          state: details.state,
          accounts: details.accounts,
          staking: details.staking,
          agent_bond: details.agent_bond,
        };
        cachedServices[serviceIndex] = updatedService;
        state.olasServicesCache[state.activeChain] = cachedServices;

        // Re-render card with actual data
        const newCardElement = document.querySelector(
          `.service-card[data-service-key="${serviceKey}"]`,
        );
        if (newCardElement) {
          newCardElement.outerHTML = renderOlasServiceCard(
            updatedService,
            false,
          );
        }

        // Update summary totals
        renderOlasSummary(cachedServices, state.olasPriceCache, false);
      } else {
        showToast(`Failed to refresh service: ${serviceKey}`, "error");
        // Re-render with old data
        const newCardElement = document.querySelector(
          `.service-card[data-service-key="${serviceKey}"]`,
        );
        if (newCardElement) {
          newCardElement.outerHTML = renderOlasServiceCard(serviceData, false);
        }
        renderOlasSummary(cachedServices, state.olasPriceCache, false);
      }
    } catch (err) {
      console.error(`Error refreshing service ${serviceKey}:`, err);
      showToast(`Error refreshing service: ${err.message}`, "error");
      // Re-render with old data
      const newCardElement = document.querySelector(
        `.service-card[data-service-key="${serviceKey}"]`,
      );
      if (newCardElement) {
        newCardElement.outerHTML = renderOlasServiceCard(serviceData, false);
      }
      renderOlasSummary(cachedServices, state.olasPriceCache, false);
    }
  };

  // Add a newly created service card without reloading all services
  window.addNewServiceCard = async (serviceId, chain, serviceName) => {
    const container = document.getElementById("olas-services-container");
    if (!container) {
      console.error("Container not found, falling back to full reload");
      loadOlasServices(true);
      return;
    }

    // Create a basic service object for the new card with loading state
    const serviceKey = `${chain}:${serviceId}`;
    const newService = {
      key: serviceKey,
      service_id: serviceId,
      chain: chain,
      name: serviceName || `Service #${serviceId}`,
      accounts: {},
      staking: {},
    };

    // Add to cache
    if (!state.olasServicesCache[chain]) {
      state.olasServicesCache[chain] = [];
    }
    state.olasServicesCache[chain].push(newService);

    // Clear empty state message if present
    const emptyState = container.querySelector(".empty-state");
    if (emptyState) {
      emptyState.remove();
    }

    // Append new card with loading state
    container.insertAdjacentHTML(
      "beforeend",
      renderOlasServiceCard(newService, true),
    );

    // Update summary
    renderOlasSummary(
      state.olasServicesCache[chain],
      state.olasPriceCache,
      true,
    );

    // Fetch details for the new service
    try {
      const detailResp = await authFetch(
        `/api/olas/services/${serviceKey}/details`,
      );
      if (detailResp.ok) {
        const details = await detailResp.json();
        // Update cache with full data
        const serviceIndex = state.olasServicesCache[chain].findIndex(
          (s) => s.key === serviceKey,
        );
        if (serviceIndex !== -1) {
          const updatedService = {
            ...newService,
            state: details.state,
            accounts: details.accounts,
            staking: details.staking,
          };
          state.olasServicesCache[chain][serviceIndex] = updatedService;

          // Re-render the card with actual data
          const cardElement = document.querySelector(
            `.service-card[data-service-key="${serviceKey}"]`,
          );
          if (cardElement) {
            cardElement.outerHTML = renderOlasServiceCard(
              updatedService,
              false,
            );
          }

          // Update summary
          renderOlasSummary(
            state.olasServicesCache[chain],
            state.olasPriceCache,
            false,
          );
        }
      }
    } catch (err) {
      console.error(`Error loading new service details: ${err}`);
    }
  };

  function renderOlasSummaryAndCards(
    container,
    services,
    olasPrice,
    isLoading = false,
  ) {
    // Render summary
    renderOlasSummary(services, olasPrice, isLoading);

    // Render cards in services container
    container.innerHTML = services
      .map((service) => renderOlasServiceCard(service, isLoading))
      .join("");
  }

  function renderOlasSummary(services, olasPrice, isLoading = false) {
    // Calculate summary
    const serviceCount = services.length;
    let totalRewards = 0;
    services.forEach((s) => {
      if (s.staking && s.staking.accrued_reward_olas) {
        totalRewards += parseFloat(s.staking.accrued_reward_olas) || 0;
      }
    });

    const priceDisplay = olasPrice
      ? `€${olasPrice.toFixed(2)}`
      : '<span class="cell-spinner"></span>';
    const rewardsDisplay = isLoading
      ? '<span class="cell-spinner"></span>'
      : totalRewards.toFixed(2);
    const valueEur =
      olasPrice && !isLoading ? (totalRewards * olasPrice).toFixed(2) : null;
    const valueDisplay = valueEur
      ? `€${valueEur}`
      : isLoading
        ? '<span class="cell-spinner"></span>'
        : "-";

    // Render summary in separate container
    const summaryContainer = document.getElementById("olas-summary-container");
    if (summaryContainer) {
      summaryContainer.innerHTML = `
                <div class="olas-summary-header">
                    <div class="olas-summary-grid">
                        <div class="olas-summary-item">
                            <div class="olas-summary-item-label">Services</div>
                            <div class="olas-summary-item-value accent">${serviceCount}</div>
                        </div>
                        <div class="olas-summary-item">
                            <div class="olas-summary-item-label">Rewards</div>
                            <div class="olas-summary-item-value success">${rewardsDisplay} OLAS</div>
                        </div>
                        <div class="olas-summary-item">
                            <div class="olas-summary-item-label">OLAS Price</div>
                            <div class="olas-summary-item-value">${priceDisplay}</div>
                        </div>
                        <div class="olas-summary-item">
                            <div class="olas-summary-item-label">Rewards Value</div>
                            <div class="olas-summary-item-value accent">${valueDisplay}</div>
                        </div>
                    </div>
                </div>
            `;
    }
  }

  function renderOlasServiceCard(service, isLoading = false) {
    const staking = service.staking || {};
    const isStaked = staking.is_staked || false;

    // Format epoch countdown
    let epochCountdown = "";
    if (
      staking.remaining_epoch_seconds !== undefined &&
      staking.remaining_epoch_seconds !== null
    ) {
      const diff = Math.floor(staking.remaining_epoch_seconds);
      if (diff <= 0) {
        epochCountdown =
          '<span class="countdown text-error">Checkpoint pending</span>';
      } else {
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        epochCountdown = `<span class="countdown" data-end="${staking.epoch_end_utc}">${h}h ${m}m</span>`;
      }
    }

    // Build accounts table
    const roles = ["agent", "safe", "owner", "owner_signer"];
    const accountsHtml = roles
      .map((role) => {
        const acc = service.accounts[role];
        if (!acc || !acc.address) {
          if (role === "owner") return "";
          // For Owner Signer (EOA owner case) or other missing roles
          const label =
            role === "owner_signer"
              ? "Owner Signer"
              : role.charAt(0).toUpperCase() + role.slice(1);
          const addrText = role === "owner_signer" ? "-" : "Not deployed";
          return `
                    <tr>
                        <td>${escapeHtml(label)}</td>
                        <td class="address-cell text-muted">${escapeHtml(addrText)}</td>
                        <td class="val">-</td>
                        <td class="val">-</td>
                    </tr>
                `;
        }

        // Requirement: Prefer TAG if available, otherwise shorten address
        const displayText = acc.tag ? acc.tag : shortenAddr(acc.address);
        const explorerUrl = getExplorerUrl(acc.address, service.chain);

        // Show spinner if loading, otherwise show balance
        const nativeDisplay =
          isLoading || acc.native === null
            ? '<span class="cell-spinner"></span>'
            : escapeHtml(formatBalance(acc.native));
        const olasDisplay =
          isLoading || acc.olas === null
            ? '<span class="cell-spinner"></span>'
            : escapeHtml(formatBalance(acc.olas));

        const label =
          role === "owner_signer"
            ? "Owner Signer"
            : role.charAt(0).toUpperCase() + role.slice(1);
        return `
                <tr>
                    <td>${escapeHtml(label)}</td>
                    <td class="address-cell">
                        <a href="${explorerUrl}" target="_blank" class="explorer-link" title="${escapeHtml(acc.address)}">
                            ${escapeHtml(displayText)}
                        </a>
                    </td>
                    <td class="val">${nativeDisplay}</td>
                    <td class="val">${olasDisplay}</td>
                </tr>
            `;
      })
      .join("");

    // Build liveness progress bar
    let livenessProgressHtml = "";
    if (isStaked) {
      if (isLoading) {
        livenessProgressHtml = `
                    <div class="staking-row">
                        <span class="label">Liveness:</span>
                        <div class="liveness-progress">
                            <div class="progress-bar"></div>
                            <span class="progress-text"><span class="cell-spinner"></span></span>
                        </div>
                    </div>
                `;
      } else {
        const current = staking.mech_requests_this_epoch || 0;
        const required = staking.required_mech_requests || 1;
        const percentage = Math.min(
          100,
          Math.round((current / required) * 100),
        );
        const progressClass = staking.liveness_ratio_passed
          ? "progress-success"
          : "progress-warning";
        livenessProgressHtml = `
                    <div class="staking-row">
                        <span class="label">Liveness:</span>
                        <div class="liveness-progress">
                            <div class="progress-bar ${progressClass}" style="--width: ${percentage}%"></div>
                            <span class="progress-text">${current}/${required} ${staking.liveness_ratio_passed ? "✓" : ""}</span>
                        </div>
                    </div>
                `;
      }
    }

    // Disable all buttons while loading
    const loadingDisabled = isLoading ? "disabled" : "";
    const loadingClass = isLoading ? "opacity-60 not-allowed grayscale" : "";

    return `
            <div class="service-card glass" data-service-key="${escapeHtml(service.key)}">
                <div class="service-header">
                    <h3>${escapeHtml(service.name || "Service")} <span class="service-id">#${service.service_id}</span></h3>
                    <div class="flex-center-gap">
                        <span class="chain-badge">${escapeHtml(service.chain)}</span>
                        <button class="btn-icon btn-icon-sm ${loadingClass}" data-action="refresh-service" data-key="${escapeHtml(service.key)}" title="Refresh this service" ${loadingDisabled}>
                            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="23 4 23 10 17 10"></polyline>
                                <polyline points="1 20 1 14 7 14"></polyline>
                                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                            </svg>
                        </button>
                    </div>
                </div>

                <table class="service-accounts-table">
                    <thead>
                        <tr>
                            <th>Role</th>
                            <th>Account</th>
                            <th class="val">${escapeHtml(state.nativeCurrencies[service.chain] || "Native")}</th>
                            <th class="val">OLAS</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${accountsHtml}
                    </tbody>
                </table>

                <div class="staking-info">
                    <div class="staking-row">
                        <span class="label">Status:</span>
                        <span class="value ${
                          isLoading
                            ? ""
                            : staking.staking_state === "EVICTED"
                              ? "evicted"
                              : isStaked
                                ? "staked"
                                : service.state === "DEPLOYED"
                                  ? "deployed"
                                  : "not-staked"
                        }">
                            ${
                              isLoading
                                ? '<span class="cell-spinner"></span>'
                                : (service.state || "UNKNOWN") +
                                  (staking.staking_state
                                    ? `, ${staking.staking_state.replace(/_/g, " ")}`
                                    : isStaked
                                      ? ", STAKED"
                                      : ", NOT STAKED")
                            }
                        </span>
                    </div>
                    <div class="staking-row">
                        <span class="label">Staking contract:</span>
                        <span class="value address-cell">
                            ${
                              isLoading
                                ? '<span class="cell-spinner"></span>'
                                : isStaked && staking.staking_contract_address
                                  ? `
                                <a href="${getExplorerUrl(staking.staking_contract_address, service.chain)}" target="_blank" class="explorer-link" title="${escapeHtml(staking.staking_contract_address)}">
                                    ${escapeHtml(staking.staking_contract_name || shortenAddr(staking.staking_contract_address))}
                                </a>
                            `
                                  : "-"
                            }
                        </span>
                    </div>
                    <div class="staking-row">
                        <span class="label">Rewards:</span>
                        <span class="value rewards">${isLoading ? '<span class="cell-spinner"></span>' : isStaked ? escapeHtml(formatBalance(staking.accrued_reward_olas) || "0") + " OLAS" : "-"}</span>
                    </div>
                    ${
                      isLoading
                        ? `
                    <div class="staking-row">
                        <span class="label">Liveness:</span>
                        <span class="value"><span class="cell-spinner"></span></span>
                    </div>
                    `
                        : isStaked && livenessProgressHtml
                          ? livenessProgressHtml
                          : `
                    <div class="staking-row">
                        <span class="label">Liveness:</span>
                        <span class="value">-</span>
                    </div>
                    `
                    }
                    <div class="staking-row">
                        <span class="label">${isStaked && staking.epoch_number !== undefined ? `Epoch #${staking.epoch_number} ends in:` : "Epoch:"}</span>
                        <span class="value">${isLoading ? '<span class="cell-spinner"></span>' : isStaked ? epochCountdown || "-" : "-"}</span>
                    </div>
                    <div class="staking-row">
                        <span class="label">Unstake available:</span>
                        <span class="value" ${staking.unstake_available_at ? `data-unstake-at="${staking.unstake_available_at}"` : ""}>${
                          isLoading
                            ? '<span class="cell-spinner"></span>'
                            : (() => {
                                if (!isStaked) return "-";
                                if (!staking.unstake_available_at) return "-";
                                const diffMs =
                                  new Date(staking.unstake_available_at) -
                                  new Date();
                                if (diffMs <= 0)
                                  return '<span class="text-success font-bold">AVAILABLE</span>';
                                const diffMins = Math.ceil(diffMs / 60000);
                                const hours = Math.floor(diffMins / 60);
                                const mins = diffMins % 60;
                                return hours > 0
                                  ? `${hours}h ${mins}m`
                                  : `${mins}m`;
                              })()
                        }</span>
                    </div>
                </div>

                <div class="service-actions">
                    <button class="btn-primary btn-sm" data-action="fund-service" data-key="${escapeHtml(service.key)}" data-chain="${escapeHtml(service.chain)}" ${loadingDisabled}>
                        Fund
                    </button>
                    ${
                      isStaked
                        ? `
                        ${(() => {
                          const checkpointDisabled =
                            isLoading || staking.remaining_epoch_seconds > 0;
                          let checkpointTitle =
                            "Call checkpoint to close the epoch";
                          if (isLoading) {
                            checkpointTitle = "Loading...";
                          } else if (staking.remaining_epoch_seconds > 0) {
                            const h = Math.floor(
                              staking.remaining_epoch_seconds / 3600,
                            );
                            const m = Math.floor(
                              (staking.remaining_epoch_seconds % 3600) / 60,
                            );
                            checkpointTitle = `Checkpoint not needed yet. Epoch ends in ${h}h ${m}m.`;
                          }
                          return `
                        <button class="btn-primary btn-sm btn-checkpoint ${loadingClass}" data-action="checkpoint" data-key="${escapeHtml(service.key)}" ${checkpointDisabled ? "disabled" : ""} title="${escapeHtml(checkpointTitle)}">
                            Checkpoint
                        </button>
                            `;
                        })()}
                        ${(() => {
                          const canUnstake =
                            !staking.unstake_available_at ||
                            new Date() >=
                              new Date(staking.unstake_available_at);
                          const unstakeLabel = "Unstake";
                          let unstakeDisabled = isLoading ? "disabled" : "";
                          const disabledStyle =
                            "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);";
                          let timeText = "";

                          if (!canUnstake) {
                            unstakeDisabled = "disabled";
                            const diffMs =
                              new Date(staking.unstake_available_at) -
                              new Date();
                            const diffMins = Math.ceil(diffMs / 60000);
                            timeText =
                              diffMins > 60
                                ? `~${Math.ceil(diffMins / 60)}h`
                                : `${diffMins}m`;
                          }

                          return `
                        <button class="btn-danger btn-sm" data-action="unstake" data-key="${escapeHtml(service.key)}" ${unstakeDisabled}
                                title="${isLoading ? "Loading..." : !canUnstake ? `Cannot unstake yet. Minimum staking duration (72h) ends in ${timeText}` : "Unstake service"}">
                            ${escapeHtml(unstakeLabel)}
                        </button>
                        `;
                        })()}
                    `
                        : service.state === "DEPLOYED"
                          ? `
                        <button class="btn-danger btn-sm" disabled
                                title="Cannot stake a deployed service. Terminate first to change staking configuration.">
                            Stake
                        </button>
                    `
                          : service.state === "PRE_REGISTRATION"
                            ? `
                        <button class="btn-primary btn-sm ${loadingClass}" data-action="deploy" data-key="${escapeHtml(service.key)}" data-chain="${escapeHtml(service.chain)}" data-name="${escapeHtml(service.name || "")}" data-id="${escapeHtml(service.service_id)}" ${loadingDisabled}>
                            Deploy
                        </button>
                    `
                            : ""
                    }
                ${
                  service.state !== "PRE_REGISTRATION"
                    ? (() => {
                        // Terminate button - now uses wind_down which handles unstake automatically
                        // Only show if service is not in PRE_REGISTRATION (nothing to wind down)
                        const terminateLabel = "Terminate";
                        let terminateDisabled = isLoading ? "disabled" : "";
                        let terminateStyle = isLoading
                          ? "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);"
                          : "";
                        let terminateTitle =
                          "Wind down service: unstake (if staked) → terminate → unbond";

                        // If staked, check if we can unstake
                        if (isStaked) {
                          const canUnstake =
                            !staking.unstake_available_at ||
                            new Date() >=
                              new Date(staking.unstake_available_at);

                          if (!canUnstake) {
                            terminateDisabled = "disabled";
                            terminateStyle =
                              "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);";

                            const diffMs =
                              new Date(staking.unstake_available_at) -
                              new Date();
                            const diffMins = Math.ceil(diffMs / 60000);
                            const timeText =
                              diffMins > 60
                                ? `~${Math.ceil(diffMins / 60)}h`
                                : `${diffMins}m`;

                            terminateTitle = `Cannot terminate yet (must unstake first). Minimum staking duration ends in ${timeText}`;
                          }
                        }

                        if (isLoading) {
                          terminateTitle = "Loading...";
                        }

                        const isDisabled = terminateDisabled === "disabled";
                        return `
                        <button class="btn-danger btn-sm" data-action="terminate" data-key="${escapeHtml(service.key)}" ${terminateDisabled}
                                title="${escapeHtml(terminateTitle)}">
                            ${escapeHtml(terminateLabel)}
                        </button>
                    `;
                      })()
                    : ""
                }
            ${(() => {
              const drainLabel = "Drain";
              let drainDisabled = isLoading ? "disabled" : "";
              let drainStyle = isLoading
                ? "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);"
                : "";
              let drainTitle = isLoading
                ? "Loading..."
                : "Drain all service funds to master account";

              // Check if there's anything to drain (Agent or Safe have non-zero balance)
              const agentBalance = service.accounts?.agent
                ? (parseFloat(service.accounts.agent.native) || 0) +
                  (parseFloat(service.accounts.agent.olas) || 0)
                : 0;
              const safeBalance = service.accounts?.safe
                ? (parseFloat(service.accounts.safe.native) || 0) +
                  (parseFloat(service.accounts.safe.olas) || 0)
                : 0;
              const hasBalanceToDrain = agentBalance > 0 || safeBalance > 0;

              if (!hasBalanceToDrain && !isLoading) {
                drainDisabled = "disabled";
                drainStyle =
                  "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);";
                drainTitle =
                  "Nothing to drain (Agent and Safe have zero balance)";
              } else if (isStaked && !isLoading) {
                // Check if we can unstake yet
                const canUnstake =
                  !staking.unstake_available_at ||
                  new Date() >= new Date(staking.unstake_available_at);
                if (!canUnstake) {
                  drainDisabled = "disabled";
                  drainStyle =
                    "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);";
                  const diffMs =
                    new Date(staking.unstake_available_at) - new Date();
                  const diffMins = Math.ceil(diffMs / 60000);
                  const timeText =
                    diffMins > 60
                      ? `~${Math.ceil(diffMins / 60)}h`
                      : `${diffMins}m`;
                  drainTitle = `Cannot drain while staked. Unstake available in ${timeText}.`;
                } else {
                  drainTitle =
                    "Service is staked. Will unstake and claim rewards first.";
                }
              }

              const isDisabled = drainDisabled === "disabled";
              return `
                    <button class="btn-danger btn-sm" data-action="drain" data-key="${escapeHtml(service.key)}" ${drainDisabled}
                            title="${escapeHtml(drainTitle)}">
                        ${escapeHtml(drainLabel)}
                    </button>
                `;
            })()}
                ${
                  isStaked
                    ? (() => {
                        const hasRewards =
                          parseFloat(staking.accrued_reward_olas) > 0;
                        const claimDisabled = isLoading || !hasRewards;
                        const claimTitle = isLoading
                          ? "Loading..."
                          : hasRewards
                            ? "Claim staking rewards"
                            : "No rewards available to claim";
                        const claimLabel = hasRewards
                          ? `Claim ${escapeHtml(formatBalance(staking.accrued_reward_olas))} OLAS`
                          : "Claim";
                        return `
                        <button class="btn-primary btn-sm"
                                data-action="claim-rewards"
                                data-key="${escapeHtml(service.key)}"
                                ${claimDisabled ? "disabled" : ""}
                                title="${escapeHtml(claimTitle)}">
                            ${claimLabel}
                        </button>
                        `;
                      })()
                    : ""
                }
            </div>
            </div>
    `;
  }

  window.claimOlasRewards = async (serviceKey) => {
    const confirmed = await showConfirm(
      "Claim Rewards",
      "Claim staking rewards for this service?",
    );
    if (!confirmed) return;

    showToast("Claiming rewards...", "info");
    try {
      const resp = await authFetch(`/api/olas/claim/${serviceKey}`, {
        method: "POST",
      });
      const result = await resp.json();
      if (resp.ok) {
        showToast(`Claimed ${result.claimed_olas.toFixed(2)} OLAS!`, "success");
        refreshSingleService(serviceKey);
      } else {
        showToast(`Error: ${result.detail} `, "error");
      }
    } catch (err) {
      showToast("Error claiming rewards", "error");
    }
  };

  window.unstakeOlasService = async (serviceKey) => {
    const confirmed = await showConfirm(
      "Unstake Service",
      "Unstake this service? This will withdraw from the staking contract.",
    );
    if (!confirmed) return;

    showToast("Unstaking service...", "info");
    try {
      const resp = await authFetch(`/api/olas/unstake/${serviceKey}`, {
        method: "POST",
      });
      const result = await resp.json();
      if (resp.ok) {
        showToast("Service unstaked successfully!", "success");
        refreshSingleService(serviceKey);
      } else {
        showToast(`Error: ${result.detail} `, "error");
      }
    } catch (err) {
      showToast("Error unstaking service", "error");
    }
  };

  window.checkpointOlasService = async (serviceKey) => {
    showToast("Calling checkpoint...", "info");
    try {
      const resp = await authFetch(`/api/olas/checkpoint/${serviceKey}`, {
        method: "POST",
      });
      const result = await resp.json();
      if (resp.ok) {
        showToast("Checkpoint successful! Epoch closed.", "success");
        refreshSingleService(serviceKey);
      } else {
        showToast(`Error: ${result.detail} `, "error");
      }
    } catch (err) {
      showToast("Error calling checkpoint", "error");
    }
  };

  // Global countdown timer for Olas services
  setInterval(() => {
    const countdowns = document.querySelectorAll(
      ".service-card .countdown[data-end]",
    );
    countdowns.forEach((el) => {
      const endTime = new Date(el.dataset.end).getTime();
      const now = new Date().getTime();
      const diff = Math.floor((endTime - now) / 1000);

      const card = el.closest(".service-card");
      const btn = card.querySelector(".btn-checkpoint");

      if (diff <= 0) {
        el.innerText = "Checkpoint pending";
        el.style.color = "#e74c3c";
        if (btn) btn.disabled = false;
      } else {
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        el.innerText = `${h}h ${m} m`;
        el.style.color = "";
        // Add a small grace period (30s) to avoid race conditions with contract
        if (btn) btn.disabled = diff > 30;
      }
    });
  }, 1000);

  window.drainOlasService = async (serviceKey) => {
    const confirmed = await showConfirm(
      "Drain Service",
      "This will drain ALL service accounts (Safe, Agent, and Owner) to your master account. If staked, the service will be unstaked and rewards claimed first.",
    );
    if (!confirmed) return;

    const removeLoadingToast = showToast(
      "Draining service... This may take up to 30 seconds.",
      "info",
      60000,
    );

    try {
      const resp = await authFetch(`/api/olas/drain/${serviceKey}`, {
        method: "POST",
      });

      removeLoadingToast();

      if (resp.ok) {
        const result = await resp.json();
        showToast("Service drained successfully!", "success");

        // SRE Fix: Wait for RPC to index new balances before refreshing
        console.log("Waiting for RPC indexer...");
        setTimeout(async () => {
          await refreshSingleService(serviceKey);
          loadAccounts(); // Refresh main accounts list too
        }, 5000);
      } else {
        const result = await resp.json();
        showToast(`Drain failed: ${result.detail}`, "error");
      }
    } catch (err) {
      removeLoadingToast();
      console.error(err);
      showToast(`Error draining service: ${err.message}`, "error");
    }
  };

  // ===== Terminate Modal Functions =====
  const terminateModal = document.getElementById("terminate-modal");
  const terminateCancel = document.getElementById("terminate-cancel");
  const terminateConfirm = document.getElementById("terminate-confirm");

  window.showTerminateModal = (serviceKey) => {
    document.getElementById("terminate-service-key").value = serviceKey;
    terminateModal.classList.add("active");
  };

  if (terminateCancel) {
    terminateCancel.addEventListener("click", () => {
      terminateModal.classList.remove("active");
    });
  }

  if (terminateConfirm) {
    terminateConfirm.addEventListener("click", async () => {
      const serviceKey = document.getElementById("terminate-service-key").value;
      terminateModal.classList.remove("active");

      showToast("Terminating service...", "info");
      try {
        const resp = await authFetch(`/api/olas/terminate/${serviceKey}`, {
          method: "POST",
        });
        const result = await resp.json();
        if (resp.ok) {
          showToast("Service terminated successfully!", "success");
          refreshSingleService(serviceKey);
        } else {
          showToast(`Error: ${result.detail} `, "error");
        }
      } catch (err) {
        showToast("Error terminating service", "error");
      }
    });
  }

  // ===== Stake Modal Functions =====
  window.showStakeModal = async (serviceKey, chain) => {
    const modal = document.getElementById("stake-modal");
    const select = document.getElementById("stake-contract-select");
    const spinnerDiv = document.getElementById("stake-contract-spinner");
    const keyInput = document.getElementById("stake-service-key");
    const confirmBtn = document.getElementById("stake-confirm");

    keyInput.value = serviceKey;

    // Show spinner, hide select, disable button
    select.style.display = "none";
    spinnerDiv.style.display = "block";
    spinnerDiv.innerHTML =
      '<span class="loading-spinner"></span> Loading contracts...';
    confirmBtn.disabled = true;
    modal.classList.add("active");

    try {
      const resp = await authFetch(
        `/api/olas/staking-contracts?chain=${chain}&service_key=${encodeURIComponent(serviceKey)}`,
      );
      const data = await resp.json();
      // Handle new response format with filter_info
      const contracts = data.contracts || data; // Fallback for backwards compat
      const filterInfo = data.filter_info;

      // Remove any existing help text
      const existingHelp = select.parentNode.querySelector(".stake-help-text");
      if (existingHelp) existingHelp.remove();

      // Create help text element
      const helpText = document.createElement("small");
      helpText.className = "stake-help-text";
      helpText.style.color = "#888";
      helpText.style.display = "block";
      helpText.style.marginTop = "8px";
      helpText.style.fontSize = "12px";

      if (contracts.length === 0) {
        select.innerHTML = '<option value="">No compatible contracts</option>';
        if (filterInfo && filterInfo.service_bond_olas !== null) {
          helpText.innerHTML = `
            <strong>Why?</strong> Your service bond (<strong>${filterInfo.service_bond_olas.toFixed(0)} OLAS</strong>)
            is lower than what staking contracts require.<br>
            <em>Tip: Recreate the service with a higher bond (e.g., 5000 OLAS) to enable staking.</em>
          `;
        } else {
          helpText.textContent =
            "No staking contracts available for this chain.";
        }
        select.parentNode.appendChild(helpText);
        confirmBtn.disabled = true;
      } else {
        select.innerHTML = contracts
          .map(
            (c) =>
              `<option value="${escapeHtml(c.address)}">${escapeHtml(c.name)} (${c.usage?.available_slots ?? "?"} slots)</option>`,
          )
          .join("");

        // Show filter info if some contracts were filtered
        if (
          filterInfo &&
          filterInfo.total_contracts > filterInfo.filtered_count
        ) {
          const hidden = filterInfo.total_contracts - filterInfo.filtered_count;
          helpText.innerHTML = `
            Showing <strong>${filterInfo.filtered_count}</strong> of ${filterInfo.total_contracts} contracts
            (${hidden} hidden - require higher bond than your <strong>${filterInfo.service_bond_olas?.toFixed(0) || "?"} OLAS</strong>).
          `;
          select.parentNode.appendChild(helpText);
        }
        confirmBtn.disabled = false;
      }

      // Show select, hide spinner
      select.style.display = "";
      spinnerDiv.classList.add("hidden");
    } catch (err) {
      select.innerHTML = '<option value="">Error loading contracts</option>';
      select.style.display = "";
      spinnerDiv.classList.add("hidden");
      confirmBtn.disabled = false;
    }
  };

  // ===== Deploy Modal Functions =====
  window.showDeployModal = async (
    serviceKey,
    chain,
    serviceName,
    serviceId,
  ) => {
    const modal = document.getElementById("create-service-modal");
    const form = document.getElementById("create-service-form");
    const nameInput = document.getElementById("new-service-name");
    const chainSelect = document.getElementById("new-service-chain");
    const agentTypeSelect = document.getElementById("new-service-agent-type");
    const contractSelect = document.getElementById(
      "new-service-staking-contract",
    );
    const spinnerDiv = document.getElementById("staking-contract-spinner");
    const submitBtn = form.querySelector('button[type="submit"]');
    const modalTitle =
      modal.querySelector(".modal-header h2") ||
      modal.querySelector("h2") ||
      modal.querySelector(".modal-header h3") ||
      modal.querySelector("h3");

    // Store deploy mode info
    form.dataset.deployMode = "true";
    form.dataset.deployServiceKey = serviceKey;

    // Show modal immediately
    modal.classList.add("active");

    // Update modal title
    if (modalTitle) modalTitle.textContent = "Deploy Olas Service";

    // Pre-fill and disable fields with better styling
    nameInput.value = serviceName || `Service #${serviceId}`;
    nameInput.disabled = true;
    nameInput.style.opacity = "1"; // Full opacity for readability
    nameInput.style.backgroundColor = "#e9ecef"; // Bootstrap readonly gray
    nameInput.style.color = "#495057";
    chainSelect.value = chain;
    chainSelect.disabled = true;
    chainSelect.style.opacity = "1";
    chainSelect.style.backgroundColor = "#e9ecef";
    chainSelect.style.color = "#495057";
    agentTypeSelect.disabled = true;
    agentTypeSelect.style.opacity = "1";
    agentTypeSelect.style.backgroundColor = "#e9ecef";
    agentTypeSelect.style.color = "#495057";
    submitBtn.innerHTML = "Deploy & Stake";

    // Load staking contracts
    contractSelect.style.display = "none";
    spinnerDiv.classList.remove("hidden");
    spinnerDiv.style.display = "block"; // Ensure display block for visibility
    spinnerDiv.innerHTML =
      '<span class="loading-spinner"></span> Loading contracts...';
    submitBtn.disabled = true;

    try {
      const resp = await authFetch(
        `/api/olas/staking-contracts?chain=${chain}&service_key=${encodeURIComponent(serviceKey)}`,
      );
      const data = await resp.json();
      // Handle new response format with filter_info
      const contracts = Array.isArray(data) ? data : data.contracts || [];
      const filterInfo = data.filter_info;

      // Remove any existing help text
      const existingHelp =
        contractSelect.parentNode.querySelector(".stake-help-text");
      if (existingHelp) existingHelp.remove();

      // Create help text element for filter explanation
      const helpText = document.createElement("small");
      helpText.className = "stake-help-text";
      helpText.style.color = "#888";
      helpText.style.display = "block";
      helpText.style.marginTop = "8px";
      helpText.style.fontSize = "12px";

      if (contracts.length === 0) {
        contractSelect.innerHTML =
          '<option value="">No compatible contracts</option>';
        if (filterInfo && filterInfo.service_bond_olas !== null) {
          helpText.innerHTML = `
            <strong>Why?</strong> Your service bond (<strong>${filterInfo.service_bond_olas.toFixed(0)} OLAS</strong>)
            is lower than what staking contracts require.<br>
            <em>You can still deploy without staking.</em>
          `;
        } else {
          helpText.textContent =
            "No staking contracts available for this chain.";
        }
        contractSelect.parentNode.appendChild(helpText);
      } else {
        contractSelect.innerHTML =
          '<option value="">None (don\'t stake)</option>' +
          contracts
            .map((c) => {
              const usage = c.usage;
              const slots = usage ? usage.available_slots : null;
              const isDisabled = slots !== null && slots <= 0;
              const disabledStr = isDisabled ? "disabled" : "";
              let slotText = "Status Unknown";
              if (slots !== null) {
                slotText = `${slots} slots`;
              }
              const text = `${escapeHtml(c.name)} (${slotText})`;
              const optionClass = isDisabled ? "text-muted" : "";
              return `<option value="${escapeHtml(c.address)}" ${disabledStr} class="${optionClass}">${text}</option>`;
            })
            .join("");

        // Show filter info if some contracts were filtered
        if (
          filterInfo &&
          filterInfo.total_contracts > filterInfo.filtered_count
        ) {
          const hidden = filterInfo.total_contracts - filterInfo.filtered_count;
          helpText.innerHTML = `
            Showing <strong>${filterInfo.filtered_count}</strong> of ${filterInfo.total_contracts} contracts
            (${hidden} hidden - require higher bond than your <strong>${filterInfo.service_bond_olas?.toFixed(0) || "?"} OLAS</strong>).
          `;
          contractSelect.parentNode.appendChild(helpText);
        }
      }

      contractSelect.style.display = "";
      spinnerDiv.style.display = "none";
      submitBtn.disabled = false;
    } catch (err) {
      contractSelect.innerHTML =
        '<option value="">None (don\'t stake)</option>';
      contractSelect.style.display = "";
      spinnerDiv.style.display = "none";
      submitBtn.disabled = false;
    }
  };

  const stakeModal = document.getElementById("stake-modal");
  const stakeCancel = document.getElementById("stake-cancel");
  const stakeConfirm = document.getElementById("stake-confirm");

  if (stakeCancel) {
    stakeCancel.addEventListener("click", () => {
      stakeModal.classList.remove("active");
    });
  }

  if (stakeConfirm) {
    stakeConfirm.addEventListener("click", async () => {
      const serviceKey = document.getElementById("stake-service-key").value;
      const contractAddress = document.getElementById(
        "stake-contract-select",
      ).value;

      if (!contractAddress) {
        showToast("Please select a staking contract", "error");
        return;
      }

      stakeModal.classList.remove("active");
      showToast("Staking service...", "info");

      try {
        const resp = await authFetch(
          `/api/olas/stake/${serviceKey}?staking_contract=${encodeURIComponent(contractAddress)}`,
          {
            method: "POST",
          },
        );
        const result = await resp.json();

        if (resp.ok) {
          showToast("Service staked successfully!", "success");
          refreshSingleService(serviceKey);
        } else {
          showToast(`Error: ${result.detail} `, "error");
        }
      } catch (err) {
        showToast("Error staking service", "error");
      }
    });
  }

  // ===== Create Service Modal Functions =====
  const createServiceBtn = document.getElementById("create-service-btn");
  const createServiceModal = document.getElementById("create-service-modal");
  const closeCreateServiceModal = document.getElementById(
    "close-create-service-modal",
  );
  const createServiceForm = document.getElementById("create-service-form");

  // Helper to render contract options - handles both new {contracts, filter_info} and old array format
  function renderContractOptions(data) {
    // Extract contracts array from new format or use directly if array
    const contracts = Array.isArray(data) ? data : data.contracts || [];

    if (!contracts.length)
      return '<option value="">No contracts available</option>';

    return (
      '<option value="">None (don\'t stake)</option>' +
      contracts
        .map((c) => {
          const usage = c.usage;
          const slots = usage ? usage.available_slots : null;

          const isDisabled = slots !== null && slots <= 0;
          const disabledStr = isDisabled ? "disabled" : "";

          let slotText = "Status Unknown";
          if (slots !== null) {
            slotText = `${slots} slots`;
          }

          const text = `${escapeHtml(c.name)} (${slotText})`;
          const optionClass = isDisabled ? "text-muted" : "";
          return `<option value="${escapeHtml(c.address)}" ${disabledStr} class="${optionClass}">${text}</option>`;
        })
        .join("")
    );
  }

  if (createServiceBtn) {
    createServiceBtn.addEventListener("click", () => {
      createServiceModal.classList.add("active");
      // Use cached staking contracts for faster loading
      const contractSelect = document.getElementById(
        "new-service-staking-contract",
      );
      const spinnerDiv = document.getElementById("staking-contract-spinner");
      if (state.stakingContractsCache) {
        contractSelect.innerHTML = renderContractOptions(
          state.stakingContractsCache,
        );
        contractSelect.classList.remove("hidden");
        spinnerDiv.classList.add("hidden");
      } else {
        // If cache not ready, show spinner and hide select
        const submitBtn = createServiceForm.querySelector(
          'button[type="submit"]',
        );
        contractSelect.style.display = "none";

        // Remove hidden class to ensure visibility (overrides CSS !important)
        spinnerDiv.classList.remove("hidden");
        spinnerDiv.style.display = "block";
        spinnerDiv.innerHTML =
          '<span class="loading-spinner"></span> Loading contracts...';

        submitBtn.disabled = true;

        authFetch("/api/olas/staking-contracts?chain=gnosis")
          .then((resp) => resp.json())
          .then((contracts) => {
            state.stakingContractsCache = contracts;
            contractSelect.innerHTML = renderContractOptions(contracts);

            contractSelect.style.display = "";
            contractSelect.classList.remove("hidden");

            // Hide spinner
            spinnerDiv.style.display = "none";
            spinnerDiv.classList.add("hidden");

            submitBtn.disabled = false;
          })
          .catch(() => {
            contractSelect.innerHTML =
              '<option value="">None (don\'t stake)</option>';
            contractSelect.style.display = "";
            contractSelect.classList.remove("hidden");

            // Hide spinner even on error
            spinnerDiv.style.display = "none";
            spinnerDiv.classList.add("hidden");

            submitBtn.disabled = false;
          });
      }
    });
  }

  if (closeCreateServiceModal) {
    closeCreateServiceModal.addEventListener("click", () => {
      createServiceModal.classList.remove("active");
    });
  }

  if (createServiceForm) {
    createServiceForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = createServiceForm.querySelector('button[type="submit"]');
      const originalText = btn.innerHTML;

      const isDeployMode = createServiceForm.dataset.deployMode === "true";
      const serviceKey = createServiceForm.dataset.deployServiceKey;

      btn.innerHTML = isDeployMode
        ? '<span class="loading-spinner spinner-sm"></span>Deploying...'
        : '<span class="loading-spinner spinner-sm"></span>Creating & Deploying...';
      btn.disabled = true;

      const stakingContract = document.getElementById(
        "new-service-staking-contract",
      ).value;

      try {
        let resp, result;

        if (isDeployMode) {
          const url = `/api/olas/deploy/${serviceKey}${stakingContract ? "?staking_contract=" + encodeURIComponent(stakingContract) : ""}`;
          resp = await authFetch(url, { method: "POST" });
          result = await resp.json();
          if (resp.ok) {
            showToast("Service deployed successfully!", "success");
            createServiceModal.classList.remove("active");
            refreshSingleService(serviceKey);
          } else {
            showToast(`Error: ${result.detail}`, "error");
          }
        } else {
          const payload = {
            service_name: document.getElementById("new-service-name").value,
            chain: document.getElementById("new-service-chain").value,
            agent_type: document.getElementById("new-service-agent-type").value,
            token_address: "OLAS",
            stake_on_create: !!stakingContract,
            staking_contract: stakingContract || null,
          };
          resp = await authFetch("/api/olas/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          result = await resp.json();
          if (resp.ok) {
            showToast(`Service created! ID: ${result.service_id}`, "success");
            createServiceModal.classList.remove("active");
            createServiceForm.reset();
            addNewServiceCard(
              result.service_id,
              payload.chain,
              payload.service_name,
            );
          } else {
            showToast(`Error: ${result.detail}`, "error");
          }
        }
      } catch (err) {
        showToast(
          isDeployMode ? "Error deploying service" : "Error creating service",
          "error",
        );
      } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
        // Reset modal to create mode
        const modalTitle =
          createServiceModal.querySelector("h2") ||
          createServiceModal.querySelector("h3");
        if (modalTitle) modalTitle.textContent = "Create Olas Service";
        const nameInput = document.getElementById("new-service-name");
        const chainSelect = document.getElementById("new-service-chain");
        const agentTypeSelect = document.getElementById(
          "new-service-agent-type",
        );
        nameInput.disabled = false;
        nameInput.style.opacity = "";
        nameInput.style.backgroundColor = "";
        nameInput.style.color = "";
        chainSelect.disabled = false;
        chainSelect.style.opacity = "";
        chainSelect.style.backgroundColor = "";
        chainSelect.style.color = "";
        agentTypeSelect.disabled = false;
        agentTypeSelect.style.opacity = "";
        agentTypeSelect.style.backgroundColor = "";
        agentTypeSelect.style.color = "";
        delete createServiceForm.dataset.deployMode;
        delete createServiceForm.dataset.deployServiceKey;
      }
    });
  }

  // ===== Fund Service Modal Functions =====
  const fundServiceModal = document.getElementById("fund-service-modal");
  const closeFundModal = document.getElementById("close-fund-modal");
  const fundConfirmBtn = document.getElementById("fund-confirm");

  window.showFundServiceModal = (serviceKey, chain) => {
    document.getElementById("fund-service-key").value = serviceKey;
    document.getElementById("fund-agent-amount").value = "0";
    document.getElementById("fund-safe-amount").value = "0";
    // Update native currency symbol
    const nativeSymbol = state.nativeCurrencies[chain] || "Native";
    document.getElementById("fund-native-symbol").textContent = nativeSymbol;
    document.getElementById("fund-safe-symbol").textContent = nativeSymbol;
    fundServiceModal.classList.add("active");
  };

  if (closeFundModal) {
    closeFundModal.addEventListener("click", () => {
      fundServiceModal.classList.remove("active");
    });
  }

  if (fundConfirmBtn) {
    fundConfirmBtn.addEventListener("click", async () => {
      const serviceKey = document.getElementById("fund-service-key").value;
      const agentAmount =
        parseFloat(document.getElementById("fund-agent-amount").value) || 0;
      const safeAmount =
        parseFloat(document.getElementById("fund-safe-amount").value) || 0;

      if (agentAmount <= 0 && safeAmount <= 0) {
        showToast("Enter at least one amount", "error");
        return;
      }

      fundServiceModal.classList.remove("active");
      showToast("Funding service...", "info");

      try {
        const resp = await authFetch(`/api/olas/fund/${serviceKey}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            agent_amount_eth: agentAmount,
            safe_amount_eth: safeAmount,
          }),
        });
        const result = await resp.json();
        if (resp.ok) {
          const fundedAccounts = Object.keys(result.funded || {});
          showToast(`Funded ${fundedAccounts.join(", ")} !`, "success");
          refreshSingleService(serviceKey);
        } else {
          showToast(`Error: ${result.detail} `, "error");
        }
      } catch (err) {
        showToast("Error funding service", "error");
      }
    });
  }

  // Global Click listener for delegation
  document.body.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;

    const action = btn.dataset.action;
    const key = btn.dataset.key;
    const chain = btn.dataset.chain;

    if (action === "copy") {
      copyToClipboard(btn.dataset.value);
    } else if (action === "refresh-service") {
      refreshSingleService(key);
    } else if (action === "fund-service") {
      showFundServiceModal(key, chain);
    } else if (action === "checkpoint") {
      checkpointOlasService(key);
    } else if (action === "unstake") {
      unstakeOlasService(key);
    } else if (action === "deploy") {
      showDeployModal(key, chain, btn.dataset.name, btn.dataset.id);
    } else if (action === "terminate") {
      showTerminateModal(key);
    } else if (action === "drain") {
      drainOlasService(key);
    } else if (action === "claim-rewards") {
      claimOlasRewards(key);
    }
  });

  init();
});
