document.addEventListener("DOMContentLoaded", () => {
  const state = {
    activeChain: localStorage.getItem("iwa_active_chain") || "gnosis",
    activeTab: localStorage.getItem("iwa_active_tab") || "dashboard",
    chains: [],
    tokens: {},
    nativeCurrencies: {},
    accounts: [], // Basic account info
    balanceCache: {}, // { address: { native: "1.00", OLAS: "50.00", ... } }
    authToken: localStorage.getItem("iwa_auth_token") || "",
    activeTokens: new Set(["native", "OLAS"]), // Default: native and OLAS
    olasServicesCache: {}, // { chain: [services] }
    stakingContractsCache: null, // Cached staking contracts
    olasPriceCache: null, // Cached OLAS price in EUR
  };

  // Real-time countdown updater for unstake availability
  function updateUnstakeCountdowns() {
    document.querySelectorAll("[data-unstake-at]").forEach((el) => {
      const targetTime = new Date(el.dataset.unstakeAt);
      const diffMs = targetTime - new Date();
      if (diffMs <= 0) {
        el.innerHTML =
          '<span style="color: var(--success-color); font-weight: bold;">AVAILABLE</span>';
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
      const pwd = prompt("Enter Web UI Password:");
      if (pwd) {
        state.authToken = pwd;
        localStorage.setItem("iwa_auth_token", pwd);
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
      const savedTab = localStorage.getItem("iwa_active_tab");
      if (savedTab && document.getElementById(savedTab)) {
        state.activeTab = savedTab;
        tabBtns.forEach((b) => b.classList.remove("active"));
        tabPanes.forEach((p) => p.classList.remove("active"));
        const targetBtn = document.querySelector(`[data-tab="${savedTab}"]`);
        if (targetBtn) targetBtn.classList.add("active");
        document.getElementById(savedTab).classList.add("active");
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

  // Tabs - no refresh on switch, use cached data
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      tabPanes.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.getAttribute("data-tab");
      state.activeTab = target;
      localStorage.setItem("iwa_active_tab", target);
      document.getElementById(target).classList.add("active");
      if (target === "rpc") {
        loadRPCStatus(true);
      }
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
      body.innerHTML = `<tr><td colspan="${3 + allTokens.length}" style="text-align: center; opacity: 0.5;">No accounts found for ${escapeHtml(state.activeChain)}</td></tr>`;
      return;
    }

    body.innerHTML = state.accounts
      .map((acc) => {
        const cached = state.balanceCache[acc.address] || {};
        return `
                <tr data-address="${escapeHtml(acc.address)}">
                    <td><span class="tag-badge">${escapeHtml(acc.tag)}</span></td>
                    <td class="address-cell" onclick="copyToClipboard('${escapeHtml(acc.address)}')">${escapeHtml(shortenAddr(acc.address))}</td>
                    <td>${escapeHtml(acc.type)}</td>
                    ${allTokens
            .map((t) => {
              const isActive = state.activeTokens.has(t);
              if (!isActive) {
                return `<td class="val balance-cell" data-token="${t}" style="opacity: 0.3;">-</td>`;
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
                    <td><span style="color: #2ecc71">${escapeHtml(tx.status)}</span></td>
                    <td class="address-cell" onclick="copyToClipboard('${escapeHtml(tx.hash)}')">${escapeHtml(tx.hash.substring(0, 10))}...</td>
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
      container.innerHTML = `<div class="rpc-card glass" style="text-align: center; padding: 2rem;"><span class="loading-spinner"></span> Loading RPC status...</div>`;
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
                        <span style="color: ${data.status === "online" ? "#2ecc71" : "#e74c3c"}">${escapeHtml(data.status.toUpperCase())}</span>
                    </div>
                    ${data.block ? `<div class="rpc-meta"><span>Block:</span><span>${escapeHtml(String(data.block))}</span></div>` : ""}
                    ${data.latency ? `<div class="rpc-meta"><span>Latency:</span><span style="color: var(--accent-color)">${escapeHtml(data.latency)}</span></div>` : ""}
                </div>
            `,
        )
        .join("");
    } catch (err) {
      console.error(err);
      if (!container.innerHTML || container.innerHTML.includes("Loading")) {
        container.innerHTML = `<div class="rpc-card glass" style="text-align: center; color: #e74c3c;">Error loading RPC status</div>`;
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

    toSelect.innerHTML = state.accounts
      .map(
        (acc) =>
          `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`,
      )
      .join("");

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
        '<span style="color: var(--text-muted); font-size: 0.9rem;">No accounts available</span>';
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

  function showToast(msg, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerText = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
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
    const accountSelect = document.getElementById("swap-account");
    const sellTokenSelect = document.getElementById("swap-sell-token");
    const buyTokenSelect = document.getElementById("swap-buy-token");

    // Populate accounts
    accountSelect.innerHTML = state.accounts
      .map(
        (acc) =>
          `<option value="${escapeHtml(acc.tag)}">${escapeHtml(acc.tag)}</option>`,
      )
      .join("");

    // Populate tokens (only ERC20, no native for CowSwap)
    const chainTokens = state.tokens[state.activeChain] || [];
    const tokenOptions = chainTokens
      .map(
        (t) =>
          `<option value="${escapeHtml(t)}">${escapeHtml(t.toUpperCase())}</option>`,
      )
      .join("");

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

  // Debounced quote fetching
  async function fetchQuote() {
    const mode = document.querySelector(
      'input[name="swap-mode"]:checked',
    ).value;
    const account = document.getElementById("swap-account").value;
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

    outputField.value = "...";

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
    }
  }

  // Add input listeners for auto-quote
  function setupAmountListeners() {
    const debouncedFetch = () => {
      clearTimeout(quoteTimeout);
      quoteTimeout = setTimeout(fetchQuote, 500);
    };

    if (sellAmountInput) {
      sellAmountInput.addEventListener("input", debouncedFetch);
    }
    if (buyAmountInput) {
      buyAmountInput.addEventListener("input", debouncedFetch);
    }
  }

  setupAmountListeners();

  // Handle Max Sell button click
  async function handleMaxClick(isSellMode) {
    const account = document.getElementById("swap-account").value;
    const sellToken = document.getElementById("swap-sell-token").value;
    const buyToken = document.getElementById("swap-buy-token").value;
    const btn = isSellMode ? swapMaxSellBtn : swapMaxBuyBtn;
    const targetInput = isSellMode ? sellAmountInput : buyAmountInput;

    if (!account || !sellToken || !buyToken) {
      showToast("Select account and tokens first", "error");
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
        targetInput.value = result.max_amount.toFixed(2);
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
      const amount =
        swapMode === "sell"
          ? parseFloat(sellAmountInput.value)
          : parseFloat(buyAmountInput.value);

      const payload = {
        account: document.getElementById("swap-account").value,
        sell_token: document.getElementById("swap-sell-token").value,
        buy_token: document.getElementById("swap-buy-token").value,
        amount: amount,
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
          showToast(result.message || "Swap order placed!", "success");
          sellAmountInput.value = "";
          buyAmountInput.value = "";
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
      } else if (btn.dataset.tab === "olas") {
        loadOlasServices();
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

      if (!basicServices || basicServices.length === 0) {
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
      container.innerHTML = `<div class="empty-state glass" style="color: #e74c3c;"><p>Error loading services: ${escapeHtml(err.message)}</p></div>`;
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
          accounts: details.accounts,
          staking: details.staking,
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
  window.addNewServiceCard = async (serviceId, chain) => {
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
      name: `Service #${serviceId}`,
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
                <div class="olas-summary-header" style="margin: 0 auto 1rem auto; padding: 0.8rem 1.5rem; background: rgba(255,255,255,0.03); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); max-width: 700px;">
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; text-align: center;">
                        <div>
                            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.3rem;">Services</div>
                            <div style="font-size: 1.3rem; font-weight: 600; color: var(--accent-color);">${serviceCount}</div>
                        </div>
                        <div>
                            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.3rem;">Rewards</div>
                            <div style="font-size: 1.3rem; font-weight: 600; color: var(--success);">${rewardsDisplay} OLAS</div>
                        </div>
                        <div>
                            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.3rem;">OLAS Price</div>
                            <div style="font-size: 1.3rem; font-weight: 600;">${priceDisplay}</div>
                        </div>
                        <div>
                            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.3rem;">Rewards Value</div>
                            <div style="font-size: 1.3rem; font-weight: 600; color: var(--accent-color);">${valueDisplay}</div>
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
          '<span class="countdown" style="color: #e74c3c">Checkpoint pending</span>';
      } else {
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        epochCountdown = `<span class="countdown" data-end="${staking.epoch_end_utc}">${h}h ${m}m</span>`;
      }
    }

    // Build accounts table
    const roles = ["agent", "safe", "owner"];
    const accountsHtml = roles
      .map((role) => {
        const acc = service.accounts[role];
        if (!acc || !acc.address) {
          if (role === "owner") return "";
          return `
                    <tr>
                        <td>${escapeHtml(role.charAt(0).toUpperCase() + role.slice(1))}</td>
                        <td class="address-cell" style="color: var(--text-muted)">Not deployed</td>
                        <td class="val">-</td>
                        <td class="val">-</td>
                    </tr>
                `;
        }

        // Requirement: addresses for 'agent' and 'safe', but only 'tag' for 'owner'
        const displayText =
          role === "owner" && acc.tag ? acc.tag : shortenAddr(acc.address);
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

        return `
                <tr>
                    <td>${escapeHtml(role.charAt(0).toUpperCase() + role.slice(1))}</td>
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
                            <div class="progress-bar" style="width: 0%"></div>
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
                            <div class="progress-bar ${progressClass}" style="width: ${percentage}%"></div>
                            <span class="progress-text">${current}/${required} ${staking.liveness_ratio_passed ? "✓" : ""}</span>
                        </div>
                    </div>
                `;
      }
    }

    // Disable all buttons while loading
    const loadingDisabled = isLoading ? "disabled" : "";
    const loadingStyle = isLoading
      ? "opacity: 0.6; cursor: not-allowed; filter: grayscale(100%);"
      : "";

    return `
            <div class="service-card glass" data-service-key="${escapeHtml(service.key)}">
                <div class="service-header">
                    <h3>${escapeHtml(service.name || "Service")} <span class="service-id">#${service.service_id}</span></h3>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="chain-badge">${escapeHtml(service.chain)}</span>
                        <button class="btn-icon" onclick="refreshSingleService('${escapeHtml(service.key)}')" title="Refresh this service" ${loadingDisabled} style="padding: 0.3rem; ${loadingStyle}">
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
                        <span class="value ${isLoading ? "" : isStaked ? "staked" : "not-staked"}">
                            ${isLoading ? '<span class="cell-spinner"></span>' : service.state ? service.state : isStaked ? "✓ STAKED" : "○ NOT STAKED"}
                        </span>
                    </div>
                    <div class="staking-row">
                        <span class="label">Contract:</span>
                        <span class="value address-cell">
                            ${isLoading
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
                    ${isLoading
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
                        <span class="value" ${staking.unstake_available_at ? `data-unstake-at="${staking.unstake_available_at}"` : ""}>${isLoading
        ? '<span class="cell-spinner"></span>'
        : (() => {
          if (!isStaked) return "-";
          if (!staking.unstake_available_at) return "-";
          const diffMs =
            new Date(staking.unstake_available_at) -
            new Date();
          if (diffMs <= 0)
            return '<span style="color: var(--success-color); font-weight: bold;">AVAILABLE</span>';
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
                    <button class="btn-primary btn-sm" onclick="showFundServiceModal('${escapeHtml(service.key)}', '${escapeHtml(service.chain)}')" ${loadingDisabled} style="${loadingStyle}">
                        Fund
                    </button>
                    ${isStaked
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
                                <button class="btn-primary btn-sm btn-checkpoint" onclick="checkpointOlasService('${escapeHtml(service.key)}')" ${checkpointDisabled ? "disabled" : ""} style="${loadingStyle}" title="${escapeHtml(checkpointTitle)}">
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
                        <button class="btn-danger btn-sm" onclick="unstakeOlasService('${escapeHtml(service.key)}')" ${unstakeDisabled}
                                style="${isLoading || !canUnstake ? disabledStyle : ""}"
                                title="${isLoading ? "Loading..." : !canUnstake ? `Cannot unstake yet. Minimum staking duration (72h) ends in ${timeText}` : "Unstake service"}">
                            ${escapeHtml(unstakeLabel)}
                        </button>
                        `;
        })()}
                    `
        : service.state === "DEPLOYED"
          ? `
                        <button class="btn-danger btn-sm" onclick="showStakeModal('${escapeHtml(service.key)}', '${escapeHtml(service.chain)}')" ${loadingDisabled} style="${loadingStyle}">
                            Stake
                        </button>
                    `
          : service.state === "PRE_REGISTRATION"
            ? `
                        <button class="btn-primary btn-sm" onclick="showDeployModal('${escapeHtml(service.key)}', '${escapeHtml(service.chain)}', '${escapeHtml(service.name || "")}', '${escapeHtml(service.service_id)}')" ${loadingDisabled} style="${loadingStyle}">
                            Deploy
                        </button>
                    `
            : ""
      }
                ${service.state !== "PRE_REGISTRATION"
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

          if (isLoading) {
            terminateTitle = "Loading...";
          }

          return `
                        <button class="btn-danger btn-sm" onclick="showTerminateModal('${escapeHtml(service.key)}')" ${terminateDisabled}
                                style="${terminateStyle}"
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

        return `
                    <button class="btn-danger btn-sm" onclick="drainOlasService('${escapeHtml(service.key)}')" ${drainDisabled}
                            style="${drainStyle}"
                            title="${escapeHtml(drainTitle)}">
                        ${escapeHtml(drainLabel)}
                    </button>
                `;
      })()}
                ${isStaked && parseFloat(staking.accrued_reward_olas) > 0
        ? `
                    <button class="btn-primary btn-sm" onclick="claimOlasRewards('${escapeHtml(service.key)}')" ${loadingDisabled} style="${loadingStyle}">
                        Claim ${escapeHtml(staking.accrued_reward_olas)} OLAS
                    </button>
                `
        : ""
      }
            </div >
            </div >
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
      const resp = await authFetch(`/ api / olas / claim / ${serviceKey} `, {
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
      const resp = await authFetch(`/ api / olas / unstake / ${serviceKey} `, {
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
      const resp = await authFetch(
        `/ api / olas / checkpoint / ${serviceKey} `,
        { method: "POST" },
      );
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

    showToast("Draining service...", "info");
    try {
      const resp = await authFetch(`/ api / olas / drain / ${serviceKey} `, {
        method: "POST",
      });
      const result = await resp.json();
      if (resp.ok) {
        showToast("Service drained successfully!", "success");
        refreshSingleService(serviceKey);
        // Refresh main accounts too
        state.balanceCache = {};
        loadAccounts();
      } else {
        showToast(`Error: ${result.detail} `, "error");
      }
    } catch (err) {
      showToast("Error draining service", "error");
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
        const resp = await authFetch(
          `/ api / olas / terminate / ${serviceKey} `,
          { method: "POST" },
        );
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
    confirmBtn.disabled = true;
    modal.classList.add("active");

    try {
      const resp = await authFetch(
        `/ api / olas / staking - contracts ? chain = ${chain} `,
      );
      const contracts = await resp.json();

      if (contracts.length === 0) {
        select.innerHTML = '<option value="">No contracts available</option>';
      } else {
        select.innerHTML = contracts
          .map(
            (c) =>
              `< option value = "${escapeHtml(c.address)}" > ${escapeHtml(c.name)}</option > `,
          )
          .join("");
      }

      // Show select, hide spinner, enable button
      select.style.display = "";
      spinnerDiv.style.display = "none";
      confirmBtn.disabled = false;
    } catch (err) {
      select.innerHTML = '<option value="">Error loading contracts</option>';
      select.style.display = "";
      spinnerDiv.style.display = "none";
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
      modal.querySelector(".modal-header h3") || modal.querySelector("h3");

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
    spinnerDiv.style.display = "block";
    submitBtn.disabled = true;

    try {
      const resp = await authFetch(
        `/api/olas/staking-contracts?chain=${chain}`,
      );
      const contracts = await resp.json();
      // Filter out contracts with no available slots if they come unfiltered?
      // Assuming backend filters, but let's be safe if we can see slots.
      // Actually, backend should filter.
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
            const style = isDisabled ? "color: #999;" : "";

            return `<option value="${escapeHtml(c.address)}" ${disabledStr} style="${style}">${text}</option>`;
          })
          .join("");
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
          `/ api / olas / stake / ${serviceKey}?staking_contract = ${encodeURIComponent(contractAddress)} `,
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

  // Helper to render contract options
  function renderContractOptions(contracts) {
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
          const style = isDisabled ? "color: #999;" : "";

          return `<option value="${escapeHtml(c.address)}" ${disabledStr} style="${style}">${text}</option>`;
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
        contractSelect.style.display = "";
        spinnerDiv.style.display = "none";
      } else {
        // If cache not ready, show spinner and hide select
        const submitBtn = createServiceForm.querySelector(
          'button[type="submit"]',
        );
        contractSelect.style.display = "none";
        spinnerDiv.style.display = "block";
        submitBtn.disabled = true;
        authFetch("/api/olas/staking-contracts?chain=gnosis")
          .then((resp) => resp.json())
          .then((contracts) => {
            state.stakingContractsCache = contracts;
            contractSelect.innerHTML = renderContractOptions(contracts);
            contractSelect.style.display = "";
            spinnerDiv.style.display = "none";
            submitBtn.disabled = false;
          })
          .catch(() => {
            contractSelect.innerHTML =
              '<option value="">None (don\'t stake)</option>';
            contractSelect.style.display = "";
            spinnerDiv.style.display = "none";
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
        ? '<span class="loading-spinner" style="width: 14px; height: 14px; border-width: 2px; margin-right: 0.5rem;"></span>Deploying...'
        : '<span class="loading-spinner" style="width: 14px; height: 14px; border-width: 2px; margin-right: 0.5rem;"></span>Creating & Deploying...';
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
            addNewServiceCard(result.service_id, payload.chain);
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
        const modalTitle = createServiceModal.querySelector("h3");
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
        const resp = await authFetch(`/ api / olas / fund / ${serviceKey} `, {
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

  init();
});
