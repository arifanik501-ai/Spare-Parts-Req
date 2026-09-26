// MEP Floor Requisition Portal Frontend Application (Mobile UI + LocalStorage + Instant Firebase Sync)
document.addEventListener('DOMContentLoaded', () => {
  const LOCAL_STORAGE_KEY = 'mep_physical_checks_v1';

  // Load saved physical checks from LocalStorage
  function loadLocalPhysicalChecks() {
    try {
      const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function saveLocalPhysicalChecks(map) {
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(map));
    } catch (e) {}
  }

  // State
  const state = {
    viewMode: 'items', // 'items' | 'reqs'
    page: 1,
    pageSize: 25,
    totalPages: 1,
    totalRecords: 0,
    filters: {
      entry_by: '',
      type: '',
      status: '',
      search: '',
      fdate: '',
      tdate: ''
    },
    expandedReqs: new Set(),
    physicalMap: loadLocalPhysicalChecks(),
    syncTimer: null
  };

  // DOM Elements
  const el = {
    // Stats
    statTotalReqs: document.getElementById('stat-total-reqs'),
    statSyncedReqs: document.getElementById('stat-synced-reqs'),
    statSpareReqs: document.getElementById('stat-spare-reqs'),
    statTotalItems: document.getElementById('stat-total-items'),
    statPhysCount: document.getElementById('stat-phys-count'),
    statAppQty: document.getElementById('stat-app-qty'),
    statReqQty: document.getElementById('stat-req-qty'),
    firebaseStatusBadge: document.getElementById('firebase-status-badge'),
    firebaseStatusText: document.getElementById('firebase-status-text'),

    // Bot & Sync
    botStatusPill: document.getElementById('bot-status-pill'),
    botStatusText: document.getElementById('bot-status-text'),
    lastSyncTime: document.getElementById('last-sync-time'),
    syncBanner: document.getElementById('sync-progress-banner'),
    syncStepLabel: document.getElementById('sync-step-label'),
    syncPercentageLabel: document.getElementById('sync-percentage-label'),
    syncProgressFill: document.getElementById('sync-progress-fill'),
    syncCounterLabel: document.getElementById('sync-counter-label'),
    cancelSyncBtn: document.getElementById('cancel-sync-btn'),
    openSyncBtn: document.getElementById('open-sync-btn'),

    // Sync Modal
    syncModal: document.getElementById('sync-modal'),
    closeSyncModalBtn: document.getElementById('close-sync-modal-btn'),
    cancelSyncModalBtn: document.getElementById('cancel-sync-modal-btn'),
    startSyncConfirmBtn: document.getElementById('start-sync-confirm-btn'),
    syncModalFdate: document.getElementById('sync-modal-fdate'),
    syncModalTdate: document.getElementById('sync-modal-tdate'),
    syncModalDetails: document.getElementById('sync-modal-details'),
    syncPresetBtns: document.querySelectorAll('.sync-preset-btn'),

    // Filters
    filterEntryBy: document.getElementById('filter-entry-by'),
    filterType: document.getElementById('filter-type'),
    filterStatus: document.getElementById('filter-status'),
    filterSearch: document.getElementById('filter-search'),
    filterFdate: document.getElementById('filter-fdate'),
    filterTdate: document.getElementById('filter-tdate'),
    filterResetBtn: document.getElementById('filter-reset-btn'),

    // Views & Switcher
    viewModeReqsBtn: document.getElementById('view-mode-reqs'),
    viewModeItemsBtn: document.getElementById('view-mode-items'),
    mobileCardsWrapper: document.getElementById('mobile-cards-wrapper'),
    reqsTableWrapper: document.getElementById('requisitions-table-wrapper'),
    itemsTableWrapper: document.getElementById('items-table-wrapper'),
    reqsTbody: document.getElementById('requisitions-tbody'),
    itemsTbody: document.getElementById('items-tbody'),
    tableTitle: document.getElementById('table-title'),
    tableCountBadge: document.getElementById('table-count-badge'),

    // Pagination
    paginationInfo: document.getElementById('pagination-info'),
    prevPageBtn: document.getElementById('prev-page-btn'),
    nextPageBtn: document.getElementById('next-page-btn'),
    pageNumDisplay: document.getElementById('page-num-display'),
    pageSizeSelect: document.getElementById('page-size-select'),

    // Export
    exportBtn: document.getElementById('export-btn'),

    // Detail Modal
    detailModal: document.getElementById('detail-modal'),
    closeModalBtn: document.getElementById('close-modal-btn'),
    printModalBtn: document.getElementById('print-modal-btn'),
    modalReqTitle: document.getElementById('modal-req-title'),
    modalSlNo: document.getElementById('modal-sl-no'),
    modalManualReq: document.getElementById('modal-manual-req'),
    modalSection: document.getElementById('modal-section'),
    modalDate: document.getElementById('modal-date'),
    modalEntryBy: document.getElementById('modal-entry-by'),
    modalStatusBadge: document.getElementById('modal-status-badge'),
    modalItemsTbody: document.getElementById('modal-items-tbody'),
    modalPreparedBy: document.getElementById('modal-prepared-by'),
    modalWarehouseText: document.getElementById('modal-warehouse-text')
  };

  function fmt(n) {
    if (n === null || n === undefined) return '0';
    return Number(n).toLocaleString('en-US');
  }

  function makeItemKey(reqNo, itemCode, sl) {
    const r = String(reqNo || '').trim();
    const c = String(itemCode || '').trim().replace(/[/.]/g, '_');
    const s = String(sl || '1').trim();
    return `${r}_${c}_${s}`;
  }

  function getPhysicalState(item) {
    const ikey = item.item_key || makeItemKey(item.req_no, item.item_code, item.sl);
    const localEntry = state.physicalMap[ikey];
    const reqQty = parseFloat(item.req_qty) || 0;

    let physRec = localEntry !== undefined
      ? (localEntry.physical_received ? 1 : 0)
      : (item.physical_received ? 1 : 0);

    let physQty = localEntry !== undefined
      ? (parseFloat(localEntry.physical_rec_qty) || 0)
      : (parseFloat(item.physical_rec_qty) || 0);

    const physPending = Math.max(0, Number((reqQty - physQty).toFixed(2)));
    return { itemKey: ikey, physRec, physQty, physPending, reqQty };
  }

  function updatePhysCountUI() {
    if (!el.statPhysCount) return;
    const count = Object.values(state.physicalMap).filter(v => v && v.physical_received).length;
    el.statPhysCount.textContent = fmt(count);
  }

  // Save Physical Receive & Qty instantly to LocalStorage + Firebase + Backend SQLite
  function handlePhysicalUpdate(item, newChecked, newQty) {
    const ikey = item.item_key || makeItemKey(item.req_no, item.item_code, item.sl);
    const reqQty = parseFloat(item.req_qty) || 0;
    const cleanQty = Math.max(0, parseFloat(newQty) || 0);
    const checkedInt = newChecked ? 1 : 0;
    const pending = Math.max(0, Number((reqQty - cleanQty).toFixed(2)));

    const record = {
      item_key: ikey,
      req_no: String(item.req_no || ''),
      item_code: String(item.item_code || ''),
      sl: String(item.sl || '1'),
      physical_received: checkedInt,
      physical_rec_qty: cleanQty,
      physical_pending: pending,
      updated_at: new Date().toISOString()
    };

    // 1. Instant LocalStorage save
    state.physicalMap[ikey] = record;
    saveLocalPhysicalChecks(state.physicalMap);
    updatePhysCountUI();

    // 2. Update all matching DOM elements on screen (both Desktop & Mobile)
    document.querySelectorAll(`[data-item-key="${ikey}"]`).forEach(node => {
      if (node.classList.contains('phys-row-container')) {
        if (checkedInt) {
          node.classList.add('phys-row-checked');
        } else {
          node.classList.remove('phys-row-checked');
        }
      }
      const cb = node.querySelector('.phys-checkbox');
      if (cb && cb.checked !== Boolean(checkedInt)) {
        cb.checked = Boolean(checkedInt);
      }
      const inp = node.querySelector('.phys-qty-input');
      if (inp && document.activeElement !== inp) {
        inp.value = cleanQty > 0 ? cleanQty : (checkedInt ? cleanQty : '');
      }
      const pendBadge = node.querySelector('.phys-pending-badge');
      if (pendBadge) {
        pendBadge.textContent = pending;
        pendBadge.className = `phys-pending-badge inline-block px-2.5 py-1 rounded text-xs font-black ${
          pending === 0 && (checkedInt || cleanQty > 0)
            ? 'bg-emerald-600 text-white'
            : 'bg-amber-100 text-amber-900 border border-amber-300'
        }`;
      }
    });

    // 3. Instant Firebase Realtime Database sync
    if (window.firebaseRealtime) {
      window.firebaseRealtime.savePhysicalCheck(ikey, record).then(() => {
        if (el.firebaseStatusBadge) {
          el.firebaseStatusBadge.className = 'bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1';
          el.firebaseStatusText.textContent = 'Synced ✓';
        }
      }).catch(() => {});
    }

    // 4. Backend SQLite sync
    fetch('/api/physical-check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(record)
    }).catch(() => {});
  }

  // Subscribe to Firebase Realtime Database for live multi-device updates
  function initFirebaseListeners() {
    if (!window.firebaseRealtime) return;
    window.firebaseRealtime.subscribePhysicalChecks((remoteMap) => {
      if (!remoteMap) return;
      state.physicalMap = { ...state.physicalMap, ...remoteMap };
      saveLocalPhysicalChecks(state.physicalMap);
      updatePhysCountUI();

      // Update live DOM elements if visible
      Object.entries(remoteMap).forEach(([ikey, rec]) => {
        if (!rec) return;
        document.querySelectorAll(`[data-item-key="${ikey}"]`).forEach(node => {
          const checkedInt = rec.physical_received ? 1 : 0;
          const cleanQty = parseFloat(rec.physical_rec_qty) || 0;
          const reqQty = parseFloat(node.dataset.reqQty) || 0;
          const pending = Math.max(0, Number((reqQty - cleanQty).toFixed(2)));

          if (node.classList.contains('phys-row-container')) {
            if (checkedInt) node.classList.add('phys-row-checked');
            else node.classList.remove('phys-row-checked');
          }
          const cb = node.querySelector('.phys-checkbox');
          if (cb) cb.checked = Boolean(checkedInt);
          const inp = node.querySelector('.phys-qty-input');
          if (inp && document.activeElement !== inp) {
            inp.value = cleanQty > 0 ? cleanQty : '';
          }
          const pendBadge = node.querySelector('.phys-pending-badge');
          if (pendBadge) {
            pendBadge.textContent = pending;
            pendBadge.className = `phys-pending-badge inline-block px-2.5 py-1 rounded text-xs font-black ${
              pending === 0 && (checkedInt || cleanQty > 0)
                ? 'bg-emerald-600 text-white'
                : 'bg-amber-100 text-amber-900 border border-amber-300'
            }`;
          }
        });
      });
    });
  }

  if (window.firebaseRealtime) {
    initFirebaseListeners();
  } else {
    window.addEventListener('firebase-ready', initFirebaseListeners);
  }

  // Load KPI Stats
  async function loadStats() {
    try {
      const res = await fetch('/api/stats');
      if (!res.ok) return;
      const data = await res.json();
      el.statTotalReqs.textContent = fmt(data.total_requisitions);
      el.statSyncedReqs.textContent = fmt(data.synced_details_count);
      el.statSpareReqs.textContent = fmt(data.spare_parts_requisitions);
      el.statTotalItems.textContent = fmt(data.total_items);
      el.statAppQty.textContent = fmt(data.total_app_qty);
      el.statReqQty.textContent = fmt(data.total_req_qty);
      updatePhysCountUI();
    } catch (e) {
      console.error('Failed to load stats:', e);
    }
  }

  // Load Dropdown Filter Options
  async function loadFilters() {
    try {
      const res = await fetch('/api/filters');
      if (!res.ok) return;
      const data = await res.json();

      const curEntryBy = el.filterEntryBy.value;
      el.filterEntryBy.innerHTML = '<option value="">All Entry Persons</option>';
      data.entry_by.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        if (name === curEntryBy) opt.selected = true;
        el.filterEntryBy.appendChild(opt);
      });

      const curType = el.filterType.value;
      el.filterType.innerHTML = '<option value="">All Types</option>';
      data.types.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        if (t === curType) opt.selected = true;
        el.filterType.appendChild(opt);
      });

      const curStatus = el.filterStatus.value;
      el.filterStatus.innerHTML = '<option value="">All Statuses</option>';
      data.statuses.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        if (s === curStatus) opt.selected = true;
        el.filterStatus.appendChild(opt);
      });
    } catch (e) {
      console.error('Failed to load filter options:', e);
    }
  }

  async function loadData() {
    if (state.viewMode === 'reqs') {
      await loadRequisitions();
    } else {
      await loadItems();
    }
  }

  function buildQuery() {
    const p = new URLSearchParams();
    if (state.filters.entry_by) p.append('entry_by', state.filters.entry_by);
    if (state.filters.type) p.append('type', state.filters.type);
    if (state.filters.status) p.append('status', state.filters.status);
    if (state.filters.search) p.append('search', state.filters.search);
    if (state.filters.fdate) p.append('fdate', state.filters.fdate);
    if (state.filters.tdate) p.append('tdate', state.filters.tdate);
    p.append('page', state.page);
    p.append('page_size', state.pageSize);
    return p.toString();
  }

  // Bind Physical Receive Checkbox & Qty Input events to a DOM row or card
  function bindPhysicalControls(container, item) {
    const cb = container.querySelector('.phys-checkbox');
    const inp = container.querySelector('.phys-qty-input');

    if (cb) {
      cb.addEventListener('change', (e) => {
        e.stopPropagation();
        const isChecked = cb.checked;
        let currentQty = parseFloat(inp ? inp.value : 0) || 0;
        handlePhysicalUpdate(item, isChecked, currentQty);
      });
    }

    if (inp) {
      inp.addEventListener('click', (e) => e.stopPropagation());
      inp.addEventListener('input', (e) => {
        e.stopPropagation();
        const val = parseFloat(inp.value);
        const numVal = isNaN(val) ? 0 : val;
        const autoCheck = numVal > 0 ? true : (cb ? cb.checked : false);
        handlePhysicalUpdate(item, autoCheck, numVal);
      });
    }
  }

  // Render Flattened Items View (Desktop Table + Mobile Cards)
  async function loadItems() {
    el.itemsTbody.innerHTML = `
      <tr>
        <td colspan="15" class="py-8 text-center text-slate-400">
          <i class="fa-solid fa-spinner fa-spin text-xl text-blue-600 mb-2"></i>
          <p>Loading items and physical receive status...</p>
        </td>
      </tr>
    `;
    el.mobileCardsWrapper.innerHTML = `
      <div class="py-8 text-center text-slate-400 bg-white rounded-xl">
        <i class="fa-solid fa-spinner fa-spin text-xl text-blue-600 mb-2"></i>
        <p class="text-xs">Loading mobile cards...</p>
      </div>
    `;

    try {
      const res = await fetch(`/api/items?${buildQuery()}`);
      if (!res.ok) throw new Error('API error');
      const data = await res.json();

      state.totalRecords = data.total;
      state.totalPages = data.total_pages;

      el.tableTitle.textContent = 'All Line Items with Apply Qty & Physical Receive';
      el.tableCountBadge.textContent = `${fmt(data.total)} Items`;
      updatePaginationControls();

      if (!data.items || data.items.length === 0) {
        const emptyHtml = `
          <div class="py-12 text-center text-slate-400">
            <i class="fa-solid fa-boxes-stacked text-3xl mb-2 text-slate-300"></i>
            <p class="font-medium text-xs sm:text-sm">No items found matching current filters.</p>
          </div>
        `;
        el.itemsTbody.innerHTML = `<tr><td colspan="15">${emptyHtml}</td></tr>`;
        el.mobileCardsWrapper.innerHTML = emptyHtml;
        return;
      }

      el.itemsTbody.innerHTML = '';
      el.mobileCardsWrapper.innerHTML = '';

      data.items.forEach(it => {
        const { itemKey, physRec, physQty, physPending, reqQty } = getPhysicalState(it);
        const statusClass = `status-${(it.req_status || '').replace(/\s+/g, '-')}`;
        const appQtyNum = parseFloat(it.app_qty) || 0;
        const appBadgeClass = appQtyNum > 0
          ? 'bg-emerald-600 text-white shadow-2xs'
          : 'bg-amber-100 text-amber-800 border border-amber-300';
        const pendBadgeClass = (physPending === 0 && (physRec || physQty > 0))
          ? 'bg-emerald-600 text-white'
          : 'bg-amber-100 text-amber-900 border border-amber-300';

        // 1. Desktop Row
        const tr = document.createElement('tr');
        tr.className = `phys-row-container hover:bg-blue-50/40 transition-colors border-b border-slate-100 ${physRec ? 'phys-row-checked' : ''}`;
        tr.dataset.itemKey = itemKey;
        tr.dataset.reqQty = reqQty;

        tr.innerHTML = `
          <td class="py-2.5 px-3">
            <a href="#" class="item-req-link font-mono font-bold text-blue-600 hover:underline" data-req-no="${it.req_no}">
              ${it.req_no}
            </a>
          </td>
          <td class="py-2.5 px-3 text-slate-600 whitespace-nowrap">${it.req_date || '-'}</td>
          <td class="py-2.5 px-3 font-medium text-slate-800">${it.req_from || '-'}</td>
          <td class="py-2.5 px-3">
            <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ${it.req_type === 'Spare Parts' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'}">
              ${it.req_type || 'General'}
            </span>
          </td>
          <td class="py-2.5 px-3 font-medium text-slate-700">${it.entry_by || '-'}</td>
          <td class="py-2.5 px-3 font-mono font-bold text-slate-800">${it.item_code || '-'}</td>
          <td class="py-2.5 px-3 font-semibold text-slate-900">${it.product_name || '-'}</td>
          <td class="py-2.5 px-3 text-right font-bold text-slate-800">${it.req_qty}</td>
          <td class="py-2.5 px-3 text-right bg-emerald-50/70 border-x border-emerald-100">
            <span class="inline-block px-2.5 py-1 rounded text-xs font-black ${appBadgeClass}">
              ${it.app_qty}
            </span>
          </td>
          <td class="py-2.5 px-3 font-medium text-slate-600">${it.unit || '-'}</td>
          <td class="py-2.5 px-3 text-slate-500 whitespace-nowrap">${it.delivery_date || '-'}</td>
          <td class="py-2.5 px-3 text-center whitespace-nowrap">
            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${statusClass}">
              ${it.req_status || 'N/A'}
            </span>
          </td>
          <!-- PHYSICAL RECEIVE TICK -->
          <td class="py-2.5 px-3 text-center bg-blue-50/30 border-l border-blue-100">
            <label class="inline-flex items-center justify-center cursor-pointer space-x-1.5">
              <input type="checkbox" class="phys-checkbox" ${physRec ? 'checked' : ''}>
              <span class="text-[11px] font-bold text-slate-700">Receive</span>
            </label>
          </td>
          <!-- PHYSICAL RECEIVE QTY INPUT -->
          <td class="py-2.5 px-3 text-right bg-blue-50/30">
            <input type="number" step="any" min="0" placeholder="0" value="${physQty > 0 ? physQty : ''}" class="phys-qty-input">
          </td>
          <!-- PHYSICAL PENDING -->
          <td class="py-2.5 px-3 text-right bg-amber-50/40 border-r border-amber-100">
            <span class="phys-pending-badge inline-block px-2.5 py-1 rounded text-xs font-black ${pendBadgeClass}">
              ${physPending}
            </span>
          </td>
        `;

        tr.querySelector('.item-req-link').addEventListener('click', (e) => {
          e.preventDefault();
          showRequisitionModal(it.req_no);
        });
        bindPhysicalControls(tr, it);
        el.itemsTbody.appendChild(tr);

        // 2. Mobile Card
        const card = document.createElement('div');
        card.className = `phys-row-container bg-white rounded-xl border border-slate-200 p-3.5 shadow-xs space-y-2.5 ${physRec ? 'phys-row-checked border-emerald-300' : ''}`;
        card.dataset.itemKey = itemKey;
        card.dataset.reqQty = reqQty;

        card.innerHTML = `
          <div class="flex items-center justify-between border-b border-slate-100 pb-2">
            <div class="flex items-center space-x-2">
              <button class="mobile-req-link font-mono font-black text-xs text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                #${it.req_no}
              </button>
              <span class="text-[11px] text-slate-500 font-medium">${it.req_date || '-'}</span>
            </div>
            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${statusClass}">
              ${it.req_status || 'N/A'}
            </span>
          </div>

          <div>
            <h4 class="font-bold text-slate-900 text-sm leading-snug">${it.product_name || '-'}</h4>
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500 mt-1">
              <span><strong class="text-slate-700">Code:</strong> <span class="font-mono">${it.item_code || '-'}</span></span>
              <span><strong class="text-slate-700">Section:</strong> ${it.req_from || '-'}</span>
              <span><strong class="text-slate-700">By:</strong> ${it.entry_by || '-'}</span>
              <span class="px-1.5 py-0.2 rounded text-[10px] font-semibold ${it.req_type === 'Spare Parts' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'}">${it.req_type || ''}</span>
            </div>
          </div>

          <!-- 3-Box Qty Summary on Mobile -->
          <div class="grid grid-cols-3 gap-2 bg-slate-50 p-2 rounded-lg border border-slate-200/80 text-center">
            <div>
              <p class="text-[10px] font-bold text-slate-400 uppercase">Req Qty</p>
              <p class="text-sm font-black text-slate-800 mt-0.5">${it.req_qty} <span class="text-[10px] font-normal text-slate-500">${it.unit || ''}</span></p>
            </div>
            <div class="border-x border-slate-200">
              <p class="text-[10px] font-bold text-emerald-700 uppercase">App. Qty</p>
              <p class="mt-0.5"><span class="inline-block px-2 py-0.5 rounded text-xs font-black ${appBadgeClass}">${it.app_qty}</span></p>
            </div>
            <div>
              <p class="text-[10px] font-bold text-amber-800 uppercase">Phys. Pending</p>
              <p class="mt-0.5"><span class="phys-pending-badge inline-block px-2 py-0.5 rounded text-xs font-black ${pendBadgeClass}">${physPending}</span></p>
            </div>
          </div>

          <!-- Touch-Friendly Physical Receive Bar -->
          <div class="grid grid-cols-2 gap-2 pt-1 items-center">
            <label class="flex items-center space-x-2.5 bg-blue-50/80 hover:bg-blue-100/70 border border-blue-200 rounded-lg px-3 py-2 cursor-pointer select-none">
              <input type="checkbox" class="phys-checkbox" ${physRec ? 'checked' : ''}>
              <span class="text-xs font-extrabold text-blue-950">Physical Receive</span>
            </label>
            <div>
              <input type="number" step="any" min="0" placeholder="Write Rec. Qty..." value="${physQty > 0 ? physQty : ''}" class="phys-qty-input">
            </div>
          </div>
        `;

        card.querySelector('.mobile-req-link').addEventListener('click', () => {
          showRequisitionModal(it.req_no);
        });
        bindPhysicalControls(card, it);
        el.mobileCardsWrapper.appendChild(card);
      });

    } catch (e) {
      console.error('Error loading items:', e);
    }
  }

  // Render Requisitions View (Desktop Table + Mobile Cards)
  async function loadRequisitions() {
    el.reqsTbody.innerHTML = `
      <tr>
        <td colspan="12" class="py-8 text-center text-slate-400">
          <i class="fa-solid fa-spinner fa-spin text-xl text-blue-600 mb-2"></i>
          <p>Loading requisitions data...</p>
        </td>
      </tr>
    `;
    el.mobileCardsWrapper.innerHTML = `
      <div class="py-8 text-center text-slate-400 bg-white rounded-xl">
        <i class="fa-solid fa-spinner fa-spin text-xl text-blue-600 mb-2"></i>
        <p class="text-xs">Loading requisitions...</p>
      </div>
    `;

    try {
      const res = await fetch(`/api/requisitions?${buildQuery()}`);
      if (!res.ok) throw new Error('API error');
      const data = await res.json();

      state.totalRecords = data.total;
      state.totalPages = data.total_pages;

      el.tableTitle.textContent = 'Requisitions List (Tap row to view & check items)';
      el.tableCountBadge.textContent = `${fmt(data.total)} Records`;
      updatePaginationControls();

      if (!data.items || data.items.length === 0) {
        const emptyHtml = `<div class="py-12 text-center text-slate-400">No requisitions found.</div>`;
        el.reqsTbody.innerHTML = `<tr><td colspan="12">${emptyHtml}</td></tr>`;
        el.mobileCardsWrapper.innerHTML = emptyHtml;
        return;
      }

      el.reqsTbody.innerHTML = '';
      el.mobileCardsWrapper.innerHTML = '';

      data.items.forEach(r => {
        const isExpanded = state.expandedReqs.has(r.req_no);
        const statusClass = `status-${(r.status || '').replace(/\s+/g, '-')}`;

        // Desktop Row
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-blue-50/40 cursor-pointer transition-colors duration-150 border-b border-slate-100';
        tr.dataset.reqNo = r.req_no;

        tr.innerHTML = `
          <td class="py-3 px-3 text-center text-slate-400">
            <button class="toggle-btn w-6 h-6 rounded flex items-center justify-center hover:bg-slate-200 transition">
              <i class="fa-solid fa-chevron-${isExpanded ? 'down' : 'right'} text-xs"></i>
            </button>
          </td>
          <td class="py-3 px-3 font-bold font-mono text-blue-700">${r.req_no}</td>
          <td class="py-3 px-3 font-medium text-slate-700">${r.manual_req_no || '-'}</td>
          <td class="py-3 px-3 text-slate-600 whitespace-nowrap">${r.req_date || '-'}</td>
          <td class="py-3 px-3 font-medium text-slate-800">${r.req_from || '-'}</td>
          <td class="py-3 px-3">
            <span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${r.req_type === 'Spare Parts' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'}">
              ${r.req_type || 'General'}
            </span>
          </td>
          <td class="py-3 px-3 font-medium text-slate-700">${r.entry_by || '-'}</td>
          <td class="py-3 px-3 text-center">
            <span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700">${r.item_count}</span>
          </td>
          <td class="py-3 px-3 text-right font-medium text-slate-700">${fmt(r.total_req_qty)}</td>
          <td class="py-3 px-3 text-right">
            <span class="inline-block px-2.5 py-1 rounded text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
              ${fmt(r.total_app_qty)}
            </span>
          </td>
          <td class="py-3 px-3 text-center whitespace-nowrap">
            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${statusClass}">${r.status || 'N/A'}</span>
          </td>
          <td class="py-3 px-3 text-center whitespace-nowrap">
            <button class="view-voucher-btn px-2.5 py-1 rounded text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50">
              <i class="fa-solid fa-eye mr-1"></i> Voucher
            </button>
          </td>
        `;

        tr.addEventListener('click', (e) => {
          if (e.target.closest('.view-voucher-btn')) {
            showRequisitionModal(r.req_no);
            return;
          }
          toggleRowExpand(r.req_no, tr);
        });

        el.reqsTbody.appendChild(tr);
        if (isExpanded) {
          renderExpandedRow(r.req_no, tr);
        }

        // Mobile Requisition Card
        const mCard = document.createElement('div');
        mCard.className = 'bg-white rounded-xl border border-slate-200 p-3.5 shadow-xs space-y-2';
        mCard.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="font-mono font-black text-sm text-blue-700">#${r.req_no} <span class="text-xs font-normal text-slate-400">(${r.manual_req_no || '-'})</span></span>
            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${statusClass}">${r.status || 'N/A'}</span>
          </div>
          <div class="text-xs text-slate-600 flex flex-wrap gap-x-3 gap-y-1">
            <span><strong>Section:</strong> ${r.req_from || '-'}</span>
            <span><strong>By:</strong> ${r.entry_by || '-'}</span>
            <span><strong>Date:</strong> ${r.req_date || '-'}</span>
          </div>
          <div class="flex items-center justify-between pt-2 border-t border-slate-100 text-xs">
            <span>Items: <strong>${r.item_count}</strong> | Req: <strong>${fmt(r.total_req_qty)}</strong> | App: <strong class="text-emerald-700">${fmt(r.total_app_qty)}</strong></span>
            <button class="m-open-voucher px-3 py-1 bg-blue-600 text-white font-semibold rounded-lg text-xs">
              View Items
            </button>
          </div>
        `;
        mCard.querySelector('.m-open-voucher').addEventListener('click', () => {
          showRequisitionModal(r.req_no);
        });
        el.mobileCardsWrapper.appendChild(mCard);
      });

    } catch (e) {
      console.error('Error fetching requisitions:', e);
    }
  }

  async function toggleRowExpand(reqNo, parentTr) {
    if (state.expandedReqs.has(reqNo)) {
      state.expandedReqs.delete(reqNo);
      const icon = parentTr.querySelector('.toggle-btn i');
      if (icon) icon.className = 'fa-solid fa-chevron-right text-xs';
      const child = parentTr.nextElementSibling;
      if (child && child.classList.contains('child-detail-row')) {
        child.remove();
      }
    } else {
      state.expandedReqs.add(reqNo);
      const icon = parentTr.querySelector('.toggle-btn i');
      if (icon) icon.className = 'fa-solid fa-chevron-down text-xs';
      await renderExpandedRow(reqNo, parentTr);
    }
  }

  async function renderExpandedRow(reqNo, parentTr) {
    let childTr = parentTr.nextElementSibling;
    if (childTr && childTr.classList.contains('child-detail-row')) {
      childTr.remove();
    }

    childTr = document.createElement('tr');
    childTr.className = 'child-detail-row bg-slate-50/70 border-b border-slate-200';
    childTr.innerHTML = `
      <td colspan="12" class="p-4 pl-10">
        <div class="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
          <div class="flex items-center justify-between border-b pb-2">
            <span class="font-bold text-xs text-slate-700 uppercase">
              <i class="fa-solid fa-boxes-stacked text-blue-600 mr-1"></i> Requisition #${reqNo} Line Items & Physical Receive
            </span>
            <button class="fetch-refresh-btn text-xs text-blue-600 hover:text-blue-800 font-semibold">
              <i class="fa-solid fa-arrows-rotate mr-1"></i> Re-fetch from ERP
            </button>
          </div>
          <div class="items-content-box">
            <div class="py-4 text-center text-slate-400 text-xs">
              <i class="fa-solid fa-spinner fa-spin mr-1 text-blue-600"></i> Loading line item details...
            </div>
          </div>
        </div>
      </td>
    `;

    parentTr.parentNode.insertBefore(childTr, parentTr.nextSibling);
    const contentBox = childTr.querySelector('.items-content-box');
    const refreshBtn = childTr.querySelector('.fetch-refresh-btn');

    refreshBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      contentBox.innerHTML = `<div class="py-4 text-center text-slate-400 text-xs"><i class="fa-solid fa-spinner fa-spin mr-1 text-blue-600"></i> Scraping latest details from ERP...</div>`;
      await fetch(`/api/requisitions/${reqNo}/sync`, { method: 'POST' });
      await fetchAndRenderChildItems(reqNo, contentBox);
      loadStats();
    });

    await fetchAndRenderChildItems(reqNo, contentBox);
  }

  async function fetchAndRenderChildItems(reqNo, container) {
    try {
      const res = await fetch(`/api/requisitions/${reqNo}?auto_fetch=true`);
      if (!res.ok) throw new Error('Failed to fetch requisition details');
      const data = await res.json();
      const items = data.items || [];

      if (items.length === 0) {
        container.innerHTML = `<div class="py-3 text-xs text-amber-700">No items found.</div>`;
        return;
      }

      const table = document.createElement('table');
      table.className = 'min-w-full divide-y divide-slate-200 text-xs border border-slate-200 rounded-lg overflow-hidden';
      table.innerHTML = `
        <thead class="bg-slate-100 text-slate-700 font-semibold">
          <tr>
            <th class="py-2 px-3 text-center">SL</th>
            <th class="py-2 px-3">Item Code</th>
            <th class="py-2 px-3">Product Name</th>
            <th class="py-2 px-3 text-right">Req. Qty</th>
            <th class="py-2 px-3 text-right bg-emerald-50 text-emerald-800 font-extrabold">App. Qty</th>
            <th class="py-2 px-3">Unit</th>
            <th class="py-2 px-3 text-center bg-blue-50 text-blue-900 font-bold">Physical Receive</th>
            <th class="py-2 px-3 text-right bg-blue-50 text-blue-900 font-bold">Physical Rec. Qty</th>
            <th class="py-2 px-3 text-right bg-amber-50 text-amber-900 font-bold">Physical Pending</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100 bg-white"></tbody>
      `;

      const tbody = table.querySelector('tbody');
      items.forEach(item => {
        const { itemKey, physRec, physQty, physPending, reqQty } = getPhysicalState(item);
        const appQtyNum = parseFloat(item.app_qty) || 0;
        const appBadgeClass = appQtyNum > 0
          ? 'bg-emerald-600 text-white'
          : 'bg-amber-100 text-amber-800 border border-amber-300';
        const pendBadgeClass = (physPending === 0 && (physRec || physQty > 0))
          ? 'bg-emerald-600 text-white'
          : 'bg-amber-100 text-amber-900 border border-amber-300';

        const tr = document.createElement('tr');
        tr.className = `phys-row-container hover:bg-slate-50 ${physRec ? 'phys-row-checked' : ''}`;
        tr.dataset.itemKey = itemKey;
        tr.dataset.reqQty = reqQty;

        tr.innerHTML = `
          <td class="py-2 px-3 text-center text-slate-400 font-mono">${item.sl || '-'}</td>
          <td class="py-2 px-3 font-mono font-bold text-slate-800">${item.item_code || '-'}</td>
          <td class="py-2 px-3 font-semibold text-slate-900">${item.product_name || '-'}</td>
          <td class="py-2 px-3 text-right font-bold text-slate-700">${item.req_qty}</td>
          <td class="py-2 px-3 text-right bg-emerald-50/70">
            <span class="inline-block px-2 py-0.5 rounded font-black text-xs ${appBadgeClass}">${item.app_qty}</span>
          </td>
          <td class="py-2 px-3 font-medium text-slate-600">${item.unit || '-'}</td>
          <td class="py-2 px-3 text-center bg-blue-50/30">
            <input type="checkbox" class="phys-checkbox" ${physRec ? 'checked' : ''}>
          </td>
          <td class="py-2 px-3 text-right bg-blue-50/30">
            <input type="number" step="any" min="0" placeholder="0" value="${physQty > 0 ? physQty : ''}" class="phys-qty-input">
          </td>
          <td class="py-2 px-3 text-right bg-amber-50/30">
            <span class="phys-pending-badge inline-block px-2.5 py-1 rounded text-xs font-black ${pendBadgeClass}">${physPending}</span>
          </td>
        `;

        bindPhysicalControls(tr, item);
        tbody.appendChild(tr);
      });

      container.innerHTML = '';
      container.appendChild(table);
    } catch (e) {
      container.innerHTML = `<div class="py-3 text-red-500 text-xs">Error loading line items: ${e.message}</div>`;
    }
  }

  function updatePaginationControls() {
    el.pageNumDisplay.textContent = state.page;
    el.prevPageBtn.disabled = (state.page <= 1);
    el.nextPageBtn.disabled = (state.page >= state.totalPages);

    const start = state.totalRecords === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
    const end = Math.min(state.page * state.pageSize, state.totalRecords);
    el.paginationInfo.textContent = `Showing ${start}-${end} of ${fmt(state.totalRecords)}`;
  }

  async function showRequisitionModal(reqNo) {
    el.detailModal.classList.remove('hidden');
    el.modalReqTitle.textContent = `Store Requisition #${reqNo}`;
    el.modalSlNo.textContent = reqNo;
    el.modalItemsTbody.innerHTML = `<tr><td colspan="9" class="py-6 text-center text-slate-400">Loading voucher...</td></tr>`;

    try {
      const res = await fetch(`/api/requisitions/${reqNo}?auto_fetch=true`);
      if (!res.ok) throw new Error('Voucher not found');
      const r = await res.json();

      el.modalManualReq.textContent = r.manual_req_no || '-';
      el.modalSection.textContent = r.req_from || '-';
      el.modalDate.textContent = r.req_date || '-';
      el.modalEntryBy.textContent = r.entry_by || '-';
      el.modalWarehouseText.textContent = `Warehouse/Store: ${r.warehouse || 'FAN Store'}`;
      el.modalPreparedBy.textContent = r.entry_by || 'Prepared By';

      const statusClass = `status-${(r.status || '').replace(/\s+/g, '-')}`;
      el.modalStatusBadge.innerHTML = `<span class="px-2 py-0.5 rounded text-[10px] font-bold ${statusClass}">${r.status}</span>`;

      const items = r.items || [];
      el.modalItemsTbody.innerHTML = '';
      items.forEach(it => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td class="py-2 px-3 text-center text-slate-500 font-mono">${it.sl || '-'}</td>
          <td class="py-2 px-3 font-mono font-bold text-slate-800">${it.item_code || '-'}</td>
          <td class="py-2 px-3 font-semibold text-slate-900">${it.product_name || '-'}</td>
          <td class="py-2 px-3 text-slate-500">${it.item_desc || '-'}</td>
          <td class="py-2 px-3 text-right font-medium text-slate-700">${it.req_qty}</td>
          <td class="py-2 px-3 text-right bg-emerald-50 font-black text-emerald-800 text-xs">
            <span class="px-2 py-0.5 rounded bg-emerald-600 text-white">${it.app_qty}</span>
          </td>
          <td class="py-2 px-3 font-medium text-slate-600">${it.unit || '-'}</td>
          <td class="py-2 px-3 text-slate-500">${it.delivery_date || '-'}</td>
          <td class="py-2 px-3 text-slate-400 italic">${it.remarks || '-'}</td>
        `;
        el.modalItemsTbody.appendChild(row);
      });
    } catch (e) {
      el.modalItemsTbody.innerHTML = `<tr><td colspan="9" class="py-4 text-center text-red-500">Error loading voucher.</td></tr>`;
    }
  }

  // Poll Sync Status
  let wasSyncing = false;
  let liveRefreshCounter = 0;
  async function checkSyncStatus() {
    try {
      const res = await fetch('/api/sync/status');
      if (!res.ok) return;
      const data = await res.json();

      if (data.last_synced_at && el.lastSyncTime) {
        el.lastSyncTime.textContent = `Last Synced: ${data.last_synced_at}`;
      }

      if (data.status === 'syncing') {
        wasSyncing = true;
        if (el.botStatusText) el.botStatusText.textContent = 'Bot: 12x Syncing...';
        el.syncBanner.classList.remove('hidden');
        el.syncStepLabel.textContent = data.current_step || 'Collecting & syncing to Firebase...';
        el.syncPercentageLabel.textContent = `${data.percentage}%`;
        el.syncProgressFill.style.width = `${data.percentage}%`;
        el.syncCounterLabel.textContent = `${data.synced_reqs} / ${data.total_reqs}`;

        liveRefreshCounter++;
        if (liveRefreshCounter % 2 === 0) {
          loadStats();
          loadData();
        }
      } else {
        el.syncBanner.classList.add('hidden');
        if (el.botStatusText) el.botStatusText.textContent = 'Bot: Ready';

        if (wasSyncing) {
          wasSyncing = false;
          liveRefreshCounter = 0;
          await loadStats();
          await loadFilters();
          await loadData();
        }
      }
    } catch (e) {}
  }

  state.syncTimer = setInterval(checkSyncStatus, 2000);

  // View Switcher Events
  el.viewModeItemsBtn.addEventListener('click', () => {
    state.viewMode = 'items';
    state.page = 1;
    el.viewModeItemsBtn.className = 'px-3 sm:px-4 py-2 text-xs font-bold rounded-md bg-white text-blue-700 shadow-sm transition-all flex items-center justify-center space-x-1.5';
    el.viewModeReqsBtn.className = 'px-3 sm:px-4 py-2 text-xs font-bold rounded-md text-slate-600 hover:text-slate-900 transition-all flex items-center justify-center space-x-1.5';
    el.itemsTableWrapper.classList.remove('hidden');
    el.itemsTableWrapper.classList.add('md:block');
    el.reqsTableWrapper.classList.add('hidden');
    el.reqsTableWrapper.classList.remove('md:block');
    loadData();
  });

  el.viewModeReqsBtn.addEventListener('click', () => {
    state.viewMode = 'reqs';
    state.page = 1;
    el.viewModeReqsBtn.className = 'px-3 sm:px-4 py-2 text-xs font-bold rounded-md bg-white text-blue-700 shadow-sm transition-all flex items-center justify-center space-x-1.5';
    el.viewModeItemsBtn.className = 'px-3 sm:px-4 py-2 text-xs font-bold rounded-md text-slate-600 hover:text-slate-900 transition-all flex items-center justify-center space-x-1.5';
    el.reqsTableWrapper.classList.remove('hidden');
    el.reqsTableWrapper.classList.add('md:block');
    el.itemsTableWrapper.classList.add('hidden');
    el.itemsTableWrapper.classList.remove('md:block');
    loadData();
  });

  // Filters
  el.filterEntryBy.addEventListener('change', () => {
    state.filters.entry_by = el.filterEntryBy.value;
    state.page = 1;
    loadData();
  });

  el.filterType.addEventListener('change', () => {
    state.filters.type = el.filterType.value;
    state.page = 1;
    loadData();
  });

  el.filterStatus.addEventListener('change', () => {
    state.filters.status = el.filterStatus.value;
    state.page = 1;
    loadData();
  });

  let searchTimeout = null;
  el.filterSearch.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      state.filters.search = el.filterSearch.value;
      state.page = 1;
      loadData();
    }, 300);
  });

  el.filterFdate.addEventListener('change', () => {
    state.filters.fdate = el.filterFdate.value;
    state.page = 1;
    loadData();
  });

  el.filterTdate.addEventListener('change', () => {
    state.filters.tdate = el.filterTdate.value;
    state.page = 1;
    loadData();
  });

  el.filterResetBtn.addEventListener('click', () => {
    el.filterEntryBy.value = '';
    el.filterType.value = '';
    el.filterStatus.value = '';
    el.filterSearch.value = '';
    el.filterFdate.value = '';
    el.filterTdate.value = '';
    state.filters = { entry_by: '', type: '', status: '', search: '', fdate: '', tdate: '' };
    state.page = 1;
    loadData();
  });

  el.prevPageBtn.addEventListener('click', () => {
    if (state.page > 1) {
      state.page--;
      loadData();
    }
  });

  el.nextPageBtn.addEventListener('click', () => {
    if (state.page < state.totalPages) {
      state.page++;
      loadData();
    }
  });

  el.pageSizeSelect.addEventListener('change', () => {
    state.pageSize = parseInt(el.pageSizeSelect.value, 10);
    state.page = 1;
    loadData();
  });

  el.exportBtn.addEventListener('click', () => {
    const q = new URLSearchParams();
    q.append('mode', state.viewMode === 'reqs' ? 'requisitions' : 'items');
    if (state.filters.entry_by) q.append('entry_by', state.filters.entry_by);
    if (state.filters.type) q.append('type', state.filters.type);
    if (state.filters.status) q.append('status', state.filters.status);
    if (state.filters.search) q.append('search', state.filters.search);
    if (state.filters.fdate) q.append('fdate', state.filters.fdate);
    if (state.filters.tdate) q.append('tdate', state.filters.tdate);
    window.location.href = `/api/export?${q.toString()}`;
  });

  el.openSyncBtn.addEventListener('click', () => el.syncModal.classList.remove('hidden'));
  el.closeSyncModalBtn.addEventListener('click', () => el.syncModal.classList.add('hidden'));
  el.cancelSyncModalBtn.addEventListener('click', () => el.syncModal.classList.add('hidden'));

  el.syncPresetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      el.syncPresetBtns.forEach(b => {
        b.className = 'sync-preset-btn px-2.5 py-2 text-xs font-semibold rounded-lg border border-slate-200 hover:bg-blue-50 transition';
      });
      btn.className = 'sync-preset-btn px-2.5 py-2 text-xs font-semibold rounded-lg border border-blue-500 bg-blue-50 text-blue-700 transition';

      const days = parseInt(btn.dataset.days, 10);
      const today = new Date();
      const tdateStr = today.toISOString().split('T')[0];

      if (days === 0) {
        el.syncModalFdate.value = tdateStr;
        el.syncModalTdate.value = tdateStr;
      } else {
        const fromDate = new Date();
        fromDate.setDate(today.getDate() - days);
        el.syncModalFdate.value = fromDate.toISOString().split('T')[0];
        el.syncModalTdate.value = tdateStr;
      }
    });
  });

  const today = new Date();
  const threeDaysAgo = new Date();
  threeDaysAgo.setDate(today.getDate() - 3);
  el.syncModalFdate.value = threeDaysAgo.toISOString().split('T')[0];
  el.syncModalTdate.value = today.toISOString().split('T')[0];

  el.startSyncConfirmBtn.addEventListener('click', async () => {
    el.syncModal.classList.add('hidden');
    const fdate = el.syncModalFdate.value || null;
    const tdate = el.syncModalTdate.value || null;
    const syncDetails = el.syncModalDetails.checked;

    try {
      const res = await fetch('/api/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fdate, tdate, sync_details: syncDetails })
      });
      if (res.ok) checkSyncStatus();
    } catch (e) {}
  });

  el.cancelSyncBtn.addEventListener('click', async () => {
    await fetch('/api/sync/stop', { method: 'POST' });
    checkSyncStatus();
  });

  el.closeModalBtn.addEventListener('click', () => el.detailModal.classList.add('hidden'));
  el.printModalBtn.addEventListener('click', () => window.print());

  // Initialize
  init_db_checks();
  async function init_db_checks() {
    try {
      const res = await fetch('/api/physical-checks');
      if (res.ok) {
        const dbChecks = await res.json();
        state.physicalMap = { ...dbChecks, ...state.physicalMap };
        saveLocalPhysicalChecks(state.physicalMap);
      }
    } catch (e) {}
    loadStats();
    loadFilters();
    loadData();
    checkSyncStatus();
  }
});
