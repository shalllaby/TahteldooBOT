/**
 * جريدة تحت الضوء الإخبارية — تطبيق الويب المركزي v4.0
 * Client-side Single Page Application (SPA) Engine
 */

// =============================================================================
// GLOBAL STATE STORE
// =============================================================================
function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  if (match) return decodeURIComponent(match[2]);
  return '';
}

const State = {
  token: localStorage.getItem('td_auth_token') || getCookie('td_auth_token') || '',
  user: null,
  hasAiKey: false,
  maskedAiKey: '',
  currentView: 'create',
  currentArticle: null,
  uploadedImagePath: '',
  cooldownSeconds: 0,
  cooldownInterval: null,
  ws: null,
  debounceTimer: null,
  filterMyArticlesOnly: false,
  accountingTimeRange: 'all',
  accountingCustomStart: '',
  accountingCustomEnd: '',
  officialPrice: 150,
  userEffectiveCut: 75,
  unbilledArticles: [],
};

// =============================================================================
// API CLIENT UTILITY
// =============================================================================
async function apiCall(endpoint, method = 'GET', body = null, isFormData = false) {
  const headers = {};
  if (State.token) {
    headers['Authorization'] = `Bearer ${State.token}`;
  }
  if (!isFormData && body) {
    headers['Content-Type'] = 'application/json';
  }

  const options = {
    method,
    headers,
  };

  if (body) {
    options.body = isFormData ? body : JSON.stringify(body);
  }

  try {
    const res = await fetch(endpoint, options);

    // Handle Session Expiry
    if (res.status === 401) {
      showLoginModal();
      throw new Error('انتهت الجلسة، يرجى إعادة تسجيل الدخول');
    }

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || data.message || 'حدث خطأ غير متوقع');
    }
    return data;
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

// Toast Notification
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  let icon = 'ℹ️';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '❌';
  if (type === 'warning') icon = '⚠️';

  toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// =============================================================================
// PUBLISH CELEBRATION & PROGRESS MODAL CONTROLLER
// =============================================================================
let publishSmoothInterval = null;
let publishTimerInterval = null;
let publishStartTime = 0;
let publishTargetPercent = 1;
let publishVisualPercent = 1;
let currentPublishResult = null;

const publishNotificationSound = new Audio('/assets/universfield-new-notification-051-494246.mp3');
publishNotificationSound.preload = 'auto';

function updatePublishModalStep(percent, text) {
  publishTargetPercent = percent;
  const stageTxt = document.getElementById('publish-stage-text');
  if (stageTxt && text) {
    stageTxt.textContent = text;
  }
}

function showPublishProgressModal() {
  const overlay = document.getElementById('publish-modal-overlay');
  const progressSec = document.getElementById('publish-modal-progress');
  const successSec = document.getElementById('publish-modal-success');
  const bar = document.getElementById('publish-progress-bar');
  const percentTxt = document.getElementById('publish-percent-text');
  const stageTxt = document.getElementById('publish-stage-text');
  const timerTxt = document.getElementById('publish-elapsed-timer');
  const logTxt = document.getElementById('publish-live-log-text');

  if (!overlay) return;

  overlay.style.display = 'flex';
  progressSec.style.display = 'block';
  successSec.style.display = 'none';
  bar.style.width = '1%';
  percentTxt.textContent = '1%';
  stageTxt.textContent = '⚡ جاري الاتصال بالسيرفر وبدء معالجة الخبر...';
  timerTxt.textContent = 'الوقت: 00:00 ث';
  if (logTxt) logTxt.textContent = 'بدء البث المباشر للعمليات...';

  publishStartTime = Date.now();
  publishTargetPercent = 8;
  publishVisualPercent = 1;

  if (publishSmoothInterval) clearInterval(publishSmoothInterval);
  if (publishTimerInterval) clearInterval(publishTimerInterval);

  // Live Timer
  publishTimerInterval = setInterval(() => {
    const elapsedSec = Math.floor((Date.now() - publishStartTime) / 1000);
    const mm = String(Math.floor(elapsedSec / 60)).padStart(2, '0');
    const ss = String(elapsedSec % 60).padStart(2, '0');
    timerTxt.textContent = `الوقت: ${mm}:${ss} ث`;
  }, 1000);

  // Smooth animation tracking towards REAL target percent received from server
  publishSmoothInterval = setInterval(() => {
    if (publishVisualPercent < publishTargetPercent) {
      publishVisualPercent += (publishTargetPercent - publishVisualPercent) > 12 ? 2 : 1;
      const rounded = Math.min(Math.round(publishVisualPercent), 99);
      bar.style.width = `${rounded}%`;
      percentTxt.textContent = `${rounded}%`;
    }
  }, 70);
}

function showPublishSuccessModal(res, articleTitle = '') {
  if (publishSmoothInterval) clearInterval(publishSmoothInterval);
  if (publishTimerInterval) clearInterval(publishTimerInterval);

  const bar = document.getElementById('publish-progress-bar');
  const percentTxt = document.getElementById('publish-percent-text');
  const stageTxt = document.getElementById('publish-stage-text');
  const progressSec = document.getElementById('publish-modal-progress');
  const successSec = document.getElementById('publish-modal-success');
  const logTxt = document.getElementById('publish-live-log-text');

  if (bar) bar.style.width = '100%';
  if (percentTxt) percentTxt.textContent = '100%';
  if (stageTxt) stageTxt.textContent = '✅ اكتمل النشر والاعتماد بنجاح!';
  if (logTxt) logTxt.textContent = `[نجاح]: تم البث على Blogger برابط: ${res.post_url || 'مباشر'}`;

  currentPublishResult = res;

  setTimeout(() => {
    try {
      publishNotificationSound.currentTime = 0;
      publishNotificationSound.play().catch(e => console.log('Audio error:', e));
    } catch (e) { }

    progressSec.style.display = 'none';
    successSec.style.display = 'block';

    const finalTitle = res.title || articleTitle || 'خبر صحفي — جريدة تحت الضوء';
    document.getElementById('pub-result-title').textContent = finalTitle;
    document.getElementById('pub-result-client').textContent = res.client_name || 'العميل';
    document.getElementById('pub-result-phone').textContent = res.client_phone || 'غير مسجل';

    const blockedAlert = document.getElementById('pub-popup-blocked-alert');
    if (blockedAlert) blockedAlert.style.display = 'none';
    const retryBtn = document.getElementById('btn-pub-popup-retry-wa');
    if (retryBtn) retryBtn.href = res.whatsapp_url || '#';

    const btnWa = document.getElementById('btn-pub-open-wa');
    if (btnWa) {
      btnWa.style.opacity = res.whatsapp_url ? '1' : '0.4';
    }
  }, 450);
}

function hidePublishModal() {
  if (publishSmoothInterval) clearInterval(publishSmoothInterval);
  if (publishTimerInterval) clearInterval(publishTimerInterval);
  const overlay = document.getElementById('publish-modal-overlay');
  if (overlay) overlay.style.display = 'none';
}

// =============================================================================
// AUTHENTICATION CONTROLLER
// =============================================================================
function showLoginModal() {
  document.getElementById('login-overlay').style.display = 'flex';
}

function hideLoginModal() {
  document.getElementById('login-overlay').style.display = 'none';
}

async function checkAuth() {
  if (!State.token) {
    showLoginModal();
    return false;
  }
  try {
    const res = await apiCall('/api/auth/me');
    if (res.success && res.user) {
      State.user = res.user;
      updateUserProfileUI();
      hideLoginModal();
      await checkUserAiKeyStatus();
      return true;
    }
  } catch (err) {
    showLoginModal();
    return false;
  }
  return false;
}

async function checkUserAiKeyStatus() {
  if (!State.token) return;
  try {
    const res = await apiCall('/api/user/ai-key');
    State.hasAiKey = !!(res && res.has_key);
    State.maskedAiKey = res?.masked_key || '';
    updateAiKeyUI();
  } catch (e) {
    console.warn('Could not check AI key status:', e);
  }
}

function updateAiKeyUI() {
  const alertEl = document.getElementById('create-missing-ai-key-alert');
  const statusBadge = document.getElementById('settings-ai-key-status');
  const maskedDisp = document.getElementById('ai-key-masked-display');
  const btnClear = document.getElementById('btn-clear-ai-key');

  if (alertEl) {
    alertEl.style.display = State.hasAiKey ? 'none' : 'block';
  }

  if (statusBadge) {
    if (State.hasAiKey) {
      statusBadge.textContent = '🟢 مفتاحك مفعل وجاهز للنشر';
      statusBadge.className = 'badge badge-success';
      statusBadge.style.background = '';
      statusBadge.style.color = '';
      statusBadge.style.border = '';
    } else {
      statusBadge.textContent = '🔴 غير محدد (مطلوب إجبارياً)';
      statusBadge.className = 'badge';
      statusBadge.style.background = 'rgba(239, 68, 68, 0.15)';
      statusBadge.style.color = '#EF4444';
      statusBadge.style.border = '1px solid rgba(239, 68, 68, 0.3)';
    }
  }

  if (maskedDisp) {
    if (State.hasAiKey && State.maskedAiKey) {
      maskedDisp.textContent = `المفتاح النشط حالياً: ${State.maskedAiKey}`;
      maskedDisp.style.display = 'block';
    } else {
      maskedDisp.style.display = 'none';
      maskedDisp.textContent = '';
    }
  }

  if (btnClear) {
    btnClear.style.display = State.hasAiKey ? 'block' : 'none';
  }
}

function updateUserProfileUI() {
  if (!State.user) return;
  const nameEl = document.getElementById('topbar-fullname');
  const roleEl = document.getElementById('topbar-role');
  const avatarEl = document.getElementById('topbar-avatar');

  const displayName = State.user.full_name || State.user.username;
  if (nameEl) nameEl.textContent = displayName;
  if (roleEl) {
    let roleText = '✍️ صحفي معتمد';
    let roleColor = '#60A5FA';
    if (State.user.role === 'admin') {
      roleText = '👑 رئيس التحرير (Admin)';
      roleColor = '#F59E0B';
    } else if (State.user.role === 'editor') {
      roleText = '⭐ صحفي مميز (مدير تحرير)';
      roleColor = '#C084FC';
    }
    roleEl.textContent = roleText;
    roleEl.style.color = roleColor;
  }
  if (avatarEl) {
    if (State.user.avatar) {
      avatarEl.innerHTML = `<img src="${State.user.avatar}" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`;
    } else {
      avatarEl.textContent = displayName.charAt(0);
    }
  }

  // Toggle visibility of admin-only elements
  const adminEls = document.querySelectorAll('.admin-only');
  adminEls.forEach(el => {
    el.style.display = (State.user.role === 'admin') ? '' : 'none';
  });

  if (State.user.role === 'admin') {
    fetchBotTelemetry();
  }
}

// =============================================================================
// ROUTER & VIEW SWITCHING
// =============================================================================
function switchView(viewName) {
  State.currentView = viewName;

  // Update Nav Items
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.view === viewName);
  });

  // Update Sections
  document.querySelectorAll('.view-section').forEach(sec => {
    sec.classList.toggle('active', sec.id === `view-${viewName}`);
  });

  // Security guard for admin-only views
  if ((viewName === 'reporters' || viewName === 'bot-control') && State.user?.role !== 'admin') {
    showToast('عفواً، هذا القسم مخصص لإدارة ورئاسة التحرير فقط 🔒', 'warning');
    switchView('create');
    return;
  }

  // Trigger lazy loading
  if (viewName === 'create') checkUserAiKeyStatus();
  if (viewName === 'articles') loadArticlesArchive();
  if (viewName === 'reporters') loadReportersGrid();
  if (viewName === 'bot-control') loadBotControlDashboard();
  else stopBotTelemetryPolling();
  if (viewName === 'settings') loadSettingsData();
  if (viewName === 'logs') loadLogsTerminal();
  if (viewName === 'accounting') loadAccountingDashboard();
}

// =============================================================================
// RATE LIMIT COOLDOWN WORKER
// =============================================================================
async function syncPublishCooldown() {
  try {
    const res = await apiCall('/api/publish-cooldown');
    State.cooldownSeconds = res.wait_seconds || 0;
    updateCooldownHUD();
  } catch (err) {
    // Silent fail
  }
}

function updateCooldownHUD() {
  const el = document.getElementById('hud-cooldown');
  const txt = document.getElementById('cooldown-text');
  if (!el || !txt) return;

  if (State.cooldownSeconds > 0) {
    el.className = 'hud-pill warning';
    txt.textContent = `انتظار: ${State.cooldownSeconds} ثانية`;
  } else {
    el.className = 'hud-pill success';
    txt.textContent = 'تدفق النشر: متاح فوراً';
  }
}

function startCooldownTicker() {
  if (State.cooldownInterval) clearInterval(State.cooldownInterval);
  State.cooldownInterval = setInterval(() => {
    if (State.cooldownSeconds > 0) {
      State.cooldownSeconds--;
      updateCooldownHUD();
    }
  }, 1000);
}

// =============================================================================
// BLOGGER QUOTA WORKER
// =============================================================================
async function syncBloggerQuota() {
  try {
    const q = await apiCall('/api/blogger/quota');
    const txt = document.getElementById('quota-text');
    if (txt && q) {
      txt.textContent = `كوتا Blogger: ${q.remaining?.toLocaleString()} متبقي (${q.status || 'OK'})`;
    }
    const setTxt = document.getElementById('settings-quota-text');
    if (setTxt && q) {
      setTxt.textContent = `${q.used?.toLocaleString()} من ${q.limit?.toLocaleString()} طلب (${q.remaining?.toLocaleString()} متبقي)`;
    }
  } catch (err) {
    // Silent fail
  }
}

// =============================================================================
// VIEW 1: STUDIO & QUICK CREATE CONTROLLER
// =============================================================================
function initCreateView() {
  const rawInput = document.getElementById('input-raw-notes');
  const charCount = document.getElementById('char-count-raw');
  const dupAlert = document.getElementById('create-duplicate-alert');
  const dupDetails = document.getElementById('dup-alert-details');
  const btnDupPost = document.getElementById('btn-dup-open-post');
  const btnDupWa = document.getElementById('btn-dup-open-wa');
  const btnDupDismiss = document.getElementById('btn-dup-dismiss');

  if (btnDupDismiss) {
    btnDupDismiss.addEventListener('click', () => {
      dupAlert.style.display = 'none';
      showToast('يمكنك المتابعة والنشر بشكل طبيعي دون أي مشكلة 🚀', 'info');
    });
  }

  // Input listener with debounced duplicate checking
  rawInput.addEventListener('input', () => {
    const val = rawInput.value.trim();
    charCount.textContent = `${val.length} حرف`;

    clearTimeout(State.debounceTimer);
    if (val.length < 5) {
      dupAlert.style.display = 'none';
      return;
    }

    State.debounceTimer = setTimeout(async () => {
      try {
        const checkRes = await apiCall(`/api/verification/check?q=${encodeURIComponent(val)}`);
        if (checkRes && checkRes.exists) {
          dupDetails.textContent = `العميل: ${checkRes.client_name || 'مسجل'} | الهاتف: ${checkRes.client_phone || '-'} | المقال: "${checkRes.article_title || ''}"`;
          btnDupPost.href = checkRes.post_url || '#';
          btnDupWa.href = checkRes.whatsapp_direct_url || checkRes.clean_chat_url || '#';
          dupAlert.style.display = 'block';
          showToast('⚠️ تم العثور على خبر سابق لهذا العميل (خيار النشر مرة أخرى متاح)!', 'warning');
        } else {
          dupAlert.style.display = 'none';
        }
      } catch (e) {
        dupAlert.style.display = 'none';
      }
    }, 600);
  });

  // Image Upload File Picker
  const fileInput = document.getElementById('file-image-input');
  const thumb = document.getElementById('img-thumb');
  const placeholder = document.getElementById('img-placeholder');
  const btnRemoveImg = document.getElementById('btn-remove-image');

  fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    await handleImageUpload(file);
  });

  // Clipboard Paste Image Support
  window.addEventListener('paste', async (e) => {
    if (State.currentView !== 'create') return;
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let item of items) {
      if (item.type.indexOf('image') !== -1) {
        const blob = item.getAsFile();
        showToast('جاري رفع الصورة الملصقة من الحافظة...', 'info');
        await handleImageUpload(blob);
        break;
      }
    }
  });

  btnRemoveImg.addEventListener('click', () => {
    State.uploadedImagePath = '';
    thumb.src = '';
    thumb.style.display = 'none';
    placeholder.style.display = 'block';
    btnRemoveImg.style.display = 'none';
    fileInput.value = '';
  });

  async function handleImageUpload(file) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      showToast('جاري معالجة ورفع الصورة...', 'info');
      const res = await apiCall('/api/upload', 'POST', formData, true);
      if (res.success) {
        State.uploadedImagePath = res.local_path;
        thumb.src = res.url;
        thumb.style.display = 'block';
        placeholder.style.display = 'none';
        btnRemoveImg.style.display = 'inline-block';
        showToast('تم رفع الصورة بنجاح ✅', 'success');
      }
    } catch (err) {
      showToast(`فشل رفع الصورة: ${err.message}`, 'error');
    }
  }

  // Button to navigate to Settings for missing AI key
  const btnGotoSettingsKey = document.getElementById('btn-goto-settings-ai-key');
  if (btnGotoSettingsKey) {
    btnGotoSettingsKey.addEventListener('click', () => {
      switchView('settings');
      setTimeout(() => {
        const inp = document.getElementById('settings-user-zai-key');
        if (inp) {
          inp.focus();
          inp.style.borderColor = '#EF4444';
          inp.style.boxShadow = '0 0 14px rgba(239, 68, 68, 0.5)';
        }
      }, 200);
    });
  }

  // 1-Click Direct Rocket Publish
  const btnDirectPub = document.getElementById('btn-direct-publish');
  btnDirectPub.addEventListener('click', async () => {
    const text = rawInput.value.trim();
    if (!text) {
      showToast('يرجى كتابة تفاصيل ومعلومات الخبر أولاً', 'warning');
      return;
    }

    if (!State.hasAiKey) {
      showToast('⚠️ تنبيه إجباري: يجب إدخال وتفعيل مفتاح Z.AI API الخاص بك في الإعدادات أولاً قبل النشر!', 'error');
      switchView('settings');
      setTimeout(() => {
        const inp = document.getElementById('settings-user-zai-key');
        if (inp) {
          inp.focus();
          inp.style.borderColor = '#EF4444';
          inp.style.boxShadow = '0 0 14px rgba(239, 68, 68, 0.5)';
        }
      }, 200);
      return;
    }

    if (State.cooldownSeconds > 0) {
      showToast(`⚠️ ليمت الجريدة: يرجى الانتظار ${State.cooldownSeconds} ثانية لتنظيم الأرشفة`, 'warning');
      return;
    }

    const entityType = document.querySelector('input[name="create-entity-type"]:checked')?.value || 'plural';

    btnDirectPub.disabled = true;
    btnDirectPub.innerHTML = '⏳ جاري الصياغة والنشر المباشر...';

    // Show Progress Modal (1% to 100%)
    showPublishProgressModal();

    try {
      const res = await apiCall('/api/articles/direct-publish', 'POST', {
        raw_notes: text,
        local_image_path: State.uploadedImagePath,
        entity_type: entityType,
      });

      syncPublishCooldown();
      syncBloggerQuota();

      // Show Celebration Dialog with Sound and Multi-Action buttons
      showPublishSuccessModal(res, res.title);

      rawInput.value = '';
      btnRemoveImg.click();
    } catch (err) {
      hidePublishModal();
      showToast(err.message, 'error');
    } finally {
      btnDirectPub.disabled = false;
      btnDirectPub.innerHTML = '🚀   صياغة ونشر الخبر والواتساب فوراً (ضغطة واحدة)';
    }
  });

}

// =============================================================================
// VIEW 3: VERIFICATION CONTROLLER
// =============================================================================
function initVerificationView() {
  const input = document.getElementById('verify-query-input');
  const btn = document.getElementById('btn-do-verify');
  const resultBox = document.getElementById('verify-result-box');
  if (!input || !resultBox) return;

  const defaultPlaceholder = `
    <div class="glass-card" style="text-align: center; padding: 50px 20px;">
      <span style="font-size: 48px; color: var(--text-muted);">🔍</span>
      <h3 style="font-size: 16px; margin: 12px 0 6px;">أدخل رقم هاتف العميل واضغط فحص أو اكتب للتحقق التلقائي</h3>
      <p style="font-size: 13px; color: var(--text-muted); max-width: 500px; margin: 0 auto;">
        سيقوم النظام بالتحقق اللحظي عبر السيرفر المركزي ومطابقة كافة الأخبار المنشورة سواء من صحفيي بوت التليجرام أو محرري المنظومة السحابية.
      </p>
    </div>
  `;

  let verifyDebounceTimer = null;

  async function executeCheck(showLoadingCard = true) {
    const q = input.value.trim();
    if (!q) {
      resultBox.innerHTML = defaultPlaceholder;
      return;
    }

    if (showLoadingCard) {
      resultBox.innerHTML = `
        <div class="glass-card" style="text-align: center; padding: 40px; border-color: rgba(245, 158, 11, 0.3);">
          <div style="font-size: 28px; margin-bottom: 10px;">⏳</div>
          <div style="font-size: 15px; color: var(--accent-gold); font-weight: 700;">جاري الاستعلام اللحظي في قاعدة البيانات المركزية...</div>
          <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 6px;">فحص أرقام الهواتف والأسماء وسجلات النشر المعتمدة</div>
        </div>
      `;
    }

    try {
      const res = await apiCall(`/api/verification/check?q=${encodeURIComponent(q)}`);

      // If user cleared or changed input while fetching, avoid stale render
      if (input.value.trim() !== q) return;

      if (res.exists) {
        const title = res.article_title || res.title || 'خبر صحفي منشور';
        const clientName = res.client_name || 'مسجل بالنظام';
        const clientPhone = res.client_phone || res.cleaned_phone || q;
        const pubDate = res.published_at ? res.published_at.substring(0, 10) : (res.created_at ? res.created_at.substring(0, 10) : 'سابقاً');
        const author = res.author_name || res.reporter_name || 'إدارة الجريدة';
        const postUrl = res.post_url || '';
        const waLink = res.whatsapp_direct_url || res.clean_chat_url || (clientPhone ? `https://wa.me/${clientPhone}` : '');
        const isManual = res.blogger_status === 'REGISTERED_MANUAL' || (title && title.includes('مسجل يدوياً'));

        const badgeHtml = isManual ? `
          <div style="display: inline-flex; align-items: center; gap: 6px; background: rgba(217, 119, 6, 0.2); color: #FBBF24; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 800; margin-bottom: 12px; border: 1px solid rgba(217, 119, 6, 0.4);">
            <span>🔒</span>
            <span>العميل مسجل مسبقاً — تواصل خارجي (محجوز ومحمي من التكرار)</span>
          </div>
        ` : `
          <div style="display: inline-flex; align-items: center; gap: 6px; background: rgba(239, 68, 68, 0.2); color: #F87171; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 800; margin-bottom: 12px; border: 1px solid rgba(239, 68, 68, 0.3);">
            <span>⚠️</span>
            <span>العميل مكرر — منشور له مسبقاً في الجريدة!</span>
          </div>
        `;

        const cardStyle = isManual
          ? 'border-color: #D97706; background: rgba(217, 119, 6, 0.08); box-shadow: 0 4px 25px rgba(217, 119, 6, 0.15);'
          : 'border-color: #EF4444; background: rgba(239, 68, 68, 0.08); box-shadow: 0 4px 25px rgba(239, 68, 68, 0.15);';

        resultBox.innerHTML = `
          <div class="glass-card" style="${cardStyle}">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px;">
              <div style="flex: 1; min-width: 280px; text-align: right;">
                ${badgeHtml}
                <h3 style="font-size: 17px; font-weight: 800; color: var(--text-primary); margin-bottom: 8px; line-height: 1.4;">${title}</h3>
                
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; font-size: 13px; margin-bottom: 14px;">
                  <div>👤 العميل: <strong style="color: var(--accent-gold);">${clientName}</strong></div>
                  <div>📞 الهاتف: <strong style="font-family: var(--font-code); color: #60A5FA;">${clientPhone}</strong></div>
                  <div>📅 ${isManual ? 'تاريخ التسجيل' : 'تاريخ النشر'}: <span style="color: var(--text-secondary);">${pubDate}</span></div>
                  <div>✍️ ${isManual ? 'المسجل بواسطة' : 'المحرر'}: <span style="color: var(--text-secondary);">${author}</span></div>
                </div>
              </div>

              <div style="display: flex; flex-direction: column; gap: 8px; min-width: 180px;">
                <button onclick="window.republishForClient('${encodeURIComponent(clientName)}', '${encodeURIComponent(clientPhone)}')" class="btn btn-gold" style="font-size: 13px; font-weight: 800; min-height: 40px; display: flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 4px 15px rgba(245, 158, 11, 0.3);">
                  <span>🚀</span>
                  <span>النشر مرة أخرى لهذا العميل</span>
                </button>
                ${postUrl ? `
                  <a href="${postUrl}" target="_blank" class="btn btn-secondary" style="font-size: 12.5px; font-weight: 700; height: 38px; display: flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none;">
                    <span>🔗</span>
                    <span>عرض المقال في بلوجر</span>
                  </a>
                ` : ''}
                ${waLink ? `
                  <a href="${waLink}" target="_blank" class="btn btn-success" style="font-size: 12.5px; font-weight: 700; height: 38px; display: flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none;">
                    <span>💬</span>
                    <span>فتح شات واتساب نظيف</span>
                  </a>
                ` : ''}
              </div>
            </div>
          </div>
        `;
      } else {
        const displayPhone = res.cleaned_phone || q;
        resultBox.innerHTML = `
          <div class="glass-card" style="border-color: var(--color-success); background: rgba(16, 185, 129, 0.08); text-align: center; padding: 40px 20px; box-shadow: 0 4px 25px rgba(16, 185, 129, 0.15);">
            <div style="font-size: 42px; margin-bottom: 12px;">✅</div>
            <div style="display: inline-block; background: rgba(16, 185, 129, 0.2); color: #34D399; padding: 4px 14px; border-radius: 20px; font-size: 13.5px; font-weight: 800; margin-bottom: 10px; border: 1px solid rgba(16, 185, 129, 0.3);">
              العميل غير مسجل مسبقاً (سجل نظيف وجاهز للنشر)
            </div>
            <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 6px; color: var(--text-primary);">
              الرقم / العميل: <span style="font-family: var(--font-code); color: #34D399;">${displayPhone}</span>
            </h3>
            <p style="font-size: 13px; color: var(--text-muted); max-width: 450px; margin: 0 auto 20px; line-height: 1.5;">
              لم يتم العثور على أي سوابق نشر سابقة لهذا الرقم أو الاسم في أرشيف الجريدة، يمكنك نشر الخبر بأمان تام دون تعارض.
            </p>
            <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
              <button onclick="document.getElementById('input-raw-notes').value='العميل: ' + '${q}' + '\\nالهاتف: ' + '${displayPhone}'; switchView('create');" class="btn btn-gold btn-lg" style="box-shadow: 0 4px 20px rgba(245, 158, 11, 0.3); font-weight: 800; padding: 12px 30px; font-size: 14px;">
                ⚡ إنشاء خبر لهذا العميل الآن
              </button>
              <button id="btn-quick-manual-from-clean" class="btn btn-secondary btn-lg" style="font-weight: 700; padding: 12px 24px; font-size: 13.5px; border: 1px solid rgba(217, 119, 6, 0.4); color: var(--accent-gold);">
                ➕ تسجيل الرقم يدوياً لحجزه
              </button>
            </div>
          </div>
        `;

        const btnQuick = document.getElementById('btn-quick-manual-from-clean');
        if (btnQuick) {
          btnQuick.addEventListener('click', () => {
            const modal = document.getElementById('modal-manual-register');
            const phoneInput = document.getElementById('manual-reg-phone');
            if (phoneInput) phoneInput.value = displayPhone;
            if (modal) modal.style.display = 'flex';
          });
        }
      }
    } catch (err) {
      resultBox.innerHTML = `
        <div class="glass-card" style="border-color: var(--color-error); text-align: center; padding: 30px;">
          <div style="font-size: 28px; margin-bottom: 8px;">❌</div>
          <div style="font-size: 14px; color: var(--color-error); font-weight: bold;">فشل التحقق: ${err.message}</div>
        </div>
      `;
    }
  }

  // Live input listener with debouncing (triggers in real time as the user types!)
  input.addEventListener('input', () => {
    const q = input.value.trim();
    clearTimeout(verifyDebounceTimer);

    if (!q || q.length < 3) {
      resultBox.innerHTML = defaultPlaceholder;
      return;
    }

    // Live typing indicator
    resultBox.innerHTML = `
      <div class="glass-card" style="text-align: center; padding: 30px; border-color: rgba(245, 158, 11, 0.25);">
        <div style="font-size: 22px; margin-bottom: 6px;">⏳</div>
        <div style="font-size: 13.5px; color: var(--accent-gold); font-weight: 700;">جاري التحقق اللحظي أثناء الكتابة (${q})...</div>
      </div>
    `;

    verifyDebounceTimer = setTimeout(() => {
      executeCheck(false);
    }, 320);
  });

  if (btn) {
    btn.addEventListener('click', () => {
      clearTimeout(verifyDebounceTimer);
      executeCheck(true);
    });
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      clearTimeout(verifyDebounceTimer);
      executeCheck(true);
    }
  });

  // --- MANUAL REGISTRATION MODAL LOGIC ---
  const btnOpenManual = document.getElementById('btn-open-manual-register');
  const modalManual = document.getElementById('modal-manual-register');
  const btnCloseManual = document.getElementById('btn-close-manual-modal');
  const btnCancelManual = document.getElementById('btn-cancel-manual-modal');
  const formManual = document.getElementById('form-manual-register');
  const phoneManualInput = document.getElementById('manual-reg-phone');

  function openManualModal() {
    if (!modalManual) return;
    const currentQ = input.value.trim();
    const digits = currentQ.replace(/\D/g, '');
    if (digits.length >= 8 && phoneManualInput) {
      phoneManualInput.value = currentQ;
    }
    modalManual.style.display = 'flex';
    setTimeout(() => {
      if (phoneManualInput) phoneManualInput.focus();
    }, 100);
  }

  function closeManualModal() {
    if (modalManual) modalManual.style.display = 'none';
  }

  window.openManualRegisterModal = openManualModal;
  window.closeManualRegisterModal = closeManualModal;

  if (btnOpenManual) {
    btnOpenManual.addEventListener('click', openManualModal);
  }
  if (btnCloseManual) {
    btnCloseManual.addEventListener('click', closeManualModal);
  }
  if (btnCancelManual) {
    btnCancelManual.addEventListener('click', closeManualModal);
  }

  // Close modal when clicking on backdrop outside modal content
  if (modalManual) {
    modalManual.addEventListener('click', (e) => {
      if (e.target === modalManual) {
        closeManualModal();
      }
    });
  }

  if (formManual) {
    formManual.addEventListener('submit', async (e) => {
      e.preventDefault();
      const phoneVal = phoneManualInput?.value.trim() || '';
      const nameVal = document.getElementById('manual-reg-name')?.value.trim() || '';
      const methodVal = document.getElementById('manual-reg-method')?.value || 'تواصل خارجي';
      const notesVal = document.getElementById('manual-reg-notes')?.value.trim() || '';
      const btnSubmit = document.getElementById('btn-save-manual-client');

      if (!phoneVal) {
        showToast('يرجى كتابة رقم هاتف العميل أولاً', 'warning');
        return;
      }

      if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.innerHTML = '⏳ جاري الحفظ والتسجيل...';
      }

      try {
        const res = await apiCall('/api/verification/manual-register', 'POST', {
          phone: phoneVal,
          client_name: nameVal,
          contact_method: methodVal,
          notes: notesVal
        });

        showToast(res.message || '✅ تم تسجيل العميل بنجاح في قاعدة البيانات', 'success');
        closeManualModal();
        formManual.reset();

        // Put the registered phone into the verification search box and run live check immediately!
        input.value = res.client_phone || phoneVal;
        executeCheck(true);
      } catch (err) {
        showToast(err.message || 'فشل تسجيل العميل يدوياً', 'error');
      } finally {
        if (btnSubmit) {
          btnSubmit.disabled = false;
          btnSubmit.innerHTML = '💾 حفظ وتسجيل الرقم';
        }
      }
    });
  }
}

// Global helper: pre-fills raw notes with client details and switches to Studio view for re-publishing
window.republishForClient = function(encodedName, encodedPhone) {
  const name = decodeURIComponent(encodedName || '');
  const phone = decodeURIComponent(encodedPhone || '');
  const rawInput = document.getElementById('input-raw-notes');
  if (rawInput) {
    rawInput.value = `العميل: ${name}\nالهاتف: ${phone}\nتفاصيل ومعلومات الخبر الجديد:\n`;
    rawInput.focus();
    // Trigger input event to update char count
    rawInput.dispatchEvent(new Event('input'));
  }
  switchView('create');
  showToast(`تم تجهيز بيانات العميل (${name}) للنشر مرة أخرى بنجاح 🚀`, 'success');
};

// =============================================================================
// VIEW 4: ARTICLES ARCHIVE CONTROLLER
// =============================================================================
async function loadArticlesArchive() {
  const tbody = document.getElementById('articles-table-body');
  const search = document.getElementById('archive-search-input')?.value || '';
  const category = document.getElementById('archive-category-select')?.value || '';
  const author = (State.filterMyArticlesOnly && State.user?.email) ? State.user.email : '';

  tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 30px;">⏳ جاري تحميل الأرشيف...</td></tr>';

  try {
    let url = `/api/articles?search=${encodeURIComponent(search)}&category=${encodeURIComponent(category)}`;
    if (author) {
      url += `&author=${encodeURIComponent(author)}`;
    }
    const res = await apiCall(url);
    if (!res.articles || res.articles.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 30px; color: var(--text-muted);">لا توجد مقالات مسجلة</td></tr>';
      return;
    }

    tbody.innerHTML = res.articles.map((a, i) => `
      <tr>
        <td style="color: var(--text-muted); font-weight: bold;">${i + 1}</td>
        <td style="font-weight: 700; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          ${a.post_url ? `<a href="${a.post_url}" target="_blank" style="color: var(--text-primary); text-decoration: none;">${a.title}</a>` : a.title}
        </td>
        <td style="font-size: 12px; color: var(--accent-gold); font-weight: 600;">
          ${a.author_name || a.author_email || 'إدارة الجريدة'}
        </td>
        <td>${a.client_name || '-'}</td>
        <td style="font-family: var(--font-code);">${a.client_phone || '-'}</td>
        <td><span class="badge badge-gold">${a.labels || 'أخبار'}</span></td>
        <td>
          <span class="badge ${a.blogger_status === 'PUBLISHED' ? 'badge-success' : 'badge-warning'}">
            ${a.blogger_status === 'PUBLISHED' ? 'منشور' : 'مسودة'}
          </span>
        </td>
        <td style="font-size: 11.5px; color: var(--text-muted);">${(a.published_at || a.created_at || '').substring(0, 10)}</td>
        <td style="text-align: center;">
          <div style="display: flex; gap: 6px; justify-content: center;">
            ${a.post_url ? `<a href="${a.post_url}" target="_blank" class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;">🔗 عرض</a>` : ''}
            <button onclick="editArticle(${a.id})" class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;">✏️</button>
            <button onclick="deleteArticle(${a.id})" class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;">🗑️</button>
          </div>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--color-error); padding: 20px;">خطأ: ${err.message}</td></tr>`;
  }
}

async function editArticle(id) {
  try {
    const res = await apiCall(`/api/articles/${id}`);
    if (res.article) {
      State.currentArticle = res.article;
      const rawInp = document.getElementById('input-raw-notes');
      if (rawInp) {
        rawInp.value = res.article.raw_notes || res.article.title || '';
        document.getElementById('char-count-raw').textContent = `${rawInp.value.length} حرف`;
      }
      switchView('create');
      showToast('تم تحميل بيانات المقال في صفحة الصياغة 📝', 'info');
    }
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function deleteArticle(id) {
  if (!confirm('هل أنت متأكد من حذف هذا المقال من السجلات؟')) return;
  try {
    await apiCall(`/api/articles/${id}`, 'DELETE');
    showToast('تم حذف المقال بنجاح', 'success');
    loadArticlesArchive();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// =============================================================================
// VIEW 5: REPORTERS HUB & TELEMETRY CONTROLLER (PREMIUM REDESIGN)
// =============================================================================

let reportersData = [];
let reportersFilter = 'all';
let reportersSearch = '';
let reportersViewMode = 'cards';
const reporterKeyVisibility = new Map(); // telegramId -> boolean

function getReporterAvatarGradient(name) {
  const gradients = [
    'linear-gradient(135deg, #3B82F6, #1D4ED8)',
    'linear-gradient(135deg, #10B981, #047857)',
    'linear-gradient(135deg, #F59E0B, #D97706)',
    'linear-gradient(135deg, #8B5CF6, #6D28D9)',
    'linear-gradient(135deg, #EC4899, #BE185D)',
    'linear-gradient(135deg, #06B6D4, #0E7490)',
    'linear-gradient(135deg, #6366F1, #4338CA)',
    'linear-gradient(135deg, #14B8A6, #0F766E)'
  ];
  let hash = 0;
  const str = String(name || 'صحفي');
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % gradients.length;
  return gradients[index];
}

function getReporterInitials(name) {
  if (!name) return 'ص';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].substring(0, 1);
  return (parts[0].substring(0, 1) + ' ' + parts[parts.length - 1].substring(0, 1));
}

function isCustomApiKey(key) {
  if (!key) return false;
  const k = key.trim();
  return k.length > 0 && k !== 'غير محدد' && !k.startsWith('TD-SYSTEM');
}

function maskApiKey(key) {
  if (!key || key === 'غير محدد') return 'غير محدد';
  const trimmed = key.trim();
  if (trimmed.length <= 8) return trimmed;
  return '••••••••••••' + trimmed.slice(-4);
}

function copyReporterKey(key) {
  if (!key || key === 'غير محدد') {
    showToast('لا يوجد مفتاح مسجل لهذا الصحفي', 'warning');
    return;
  }
  navigator.clipboard.writeText(key).then(() => {
    showToast('تم نسخ مفتاح الربط بنجاح ✅', 'success');
  }).catch(() => {
    showToast('تعذر نسخ المفتاح تلقائياً', 'error');
  });
}

function toggleReporterKeyVisibility(telegramId) {
  const current = !!reporterKeyVisibility.get(telegramId);
  reporterKeyVisibility.set(telegramId, !current);
  
  const displayEl = document.getElementById(`key-val-${telegramId}`);
  const eyeBtn = document.getElementById(`eye-btn-${telegramId}`);
  const reporter = reportersData.find(r => String(r.telegram_id) === String(telegramId));
  
  if (displayEl && reporter) {
    const rawKey = reporter.api_key || 'غير محدد';
    if (!current) {
      displayEl.textContent = rawKey;
      displayEl.style.color = '#10B981';
      if (eyeBtn) eyeBtn.textContent = '🙈';
    } else {
      displayEl.textContent = maskApiKey(rawKey);
      displayEl.style.color = 'var(--accent-gold)';
      if (eyeBtn) eyeBtn.textContent = '👁️';
    }
  }
}

function updateReportersKPIs() {
  const total = reportersData.length;
  const customCount = reportersData.filter(r => isCustomApiKey(r.api_key)).length;
  const systemCount = total - customCount;
  const totalArticles = reportersData.reduce((acc, r) => acc + (parseInt(r.articles_total) || 0), 0);
  const todayArticles = reportersData.reduce((acc, r) => acc + (parseInt(r.articles_today) || 0), 0);

  const setTxt = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };

  setTxt('rep-header-total-badge', `${total} صحفي`);
  setTxt('rep-stat-total', total);
  setTxt('rep-stat-active-keys', customCount);
  setTxt('rep-stat-system-keys', systemCount);
  setTxt('rep-stat-total-articles', totalArticles.toLocaleString('ar-EG'));
  setTxt('rep-stat-today-articles', todayArticles.toLocaleString('ar-EG'));

  setTxt('tab-count-all', total);
  setTxt('tab-count-custom', customCount);
  setTxt('tab-count-system', systemCount);
}

function getFilteredReporters() {
  let list = [...reportersData];

  // Search filter
  if (reportersSearch) {
    const q = reportersSearch.toLowerCase().trim();
    list = list.filter(r => {
      const nameMatch = (r.name || '').toLowerCase().includes(q);
      const idMatch = String(r.telegram_id || '').includes(q);
      const keyMatch = (r.api_key || '').toLowerCase().includes(q);
      const roleMatch = (r.role || '').toLowerCase().includes(q);
      return nameMatch || idMatch || keyMatch || roleMatch;
    });
  }

  // Tab filter
  if (reportersFilter === 'custom-key') {
    list = list.filter(r => isCustomApiKey(r.api_key));
  } else if (reportersFilter === 'system-key') {
    list = list.filter(r => !isCustomApiKey(r.api_key));
  } else if (reportersFilter === 'top-producers') {
    list.sort((a, b) => (parseInt(b.articles_total) || 0) - (parseInt(a.articles_total) || 0));
    return list;
  }

  // Default sorting: today's articles desc, then total articles desc, then name
  list.sort((a, b) => {
    const tdDiff = (parseInt(b.articles_today) || 0) - (parseInt(a.articles_today) || 0);
    if (tdDiff !== 0) return tdDiff;
    const totDiff = (parseInt(b.articles_total) || 0) - (parseInt(a.articles_total) || 0);
    if (totDiff !== 0) return totDiff;
    return (a.name || '').localeCompare(b.name || '');
  });

  return list;
}

function renderReportersList() {
  const cardsContainer = document.getElementById('reporters-cards-container');
  const tableContainer = document.getElementById('reporters-table-container');
  const tableBody = document.getElementById('reporters-table-body');
  const filtered = getFilteredReporters();

  if (reportersViewMode === 'table') {
    if (cardsContainer) cardsContainer.style.display = 'none';
    if (tableContainer) tableContainer.style.display = 'block';

    if (!tableBody) return;
    if (filtered.length === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; padding: 35px; color: var(--text-muted);">
            🔍 لم يتم العثور على مراسلين يطابقون معايير البحث أو التصفية الحالية.
          </td>
        </tr>`;
      return;
    }

    tableBody.innerHTML = filtered.map(r => {
      const isCustom = isCustomApiKey(r.api_key);
      const isRevealed = !!reporterKeyVisibility.get(r.telegram_id);
      const rawKey = r.api_key || 'غير محدد';
      const displayKey = isRevealed ? rawKey : maskApiKey(rawKey);
      const grad = getReporterAvatarGradient(r.name);
      const initials = getReporterInitials(r.name);
      const safeName = (r.name || '').replace(/'/g, "\\'");
      const safeKey = (r.api_key || '').replace(/'/g, "\\'");

      return `
        <tr>
          <td>
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 34px; height: 34px; border-radius: 8px; background: ${grad}; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 800; font-size: 13px; flex-shrink: 0;">
                ${initials}
              </div>
              <div>
                <div style="font-weight: 700; color: var(--text-primary); font-size: 13.5px;">${r.name}</div>
                <span style="font-size: 11px; color: var(--text-muted);">${(r.created_at || '').substring(0, 10)}</span>
              </div>
            </div>
          </td>
          <td>
            <span class="badge" style="font-family: var(--font-code); background: rgba(56,189,248,0.12); color: #38BDF8; letter-spacing: 0.5px;">
              ${r.telegram_id}
            </span>
          </td>
          <td>
            <span class="badge ${isCustom ? 'badge-gold' : 'badge-secondary'}">
              ${r.role || 'صحفي لدى'}
            </span>
          </td>
          <td>
            <div style="display: flex; align-items: center; gap: 6px; max-width: 260px;">
              <code id="key-val-${r.telegram_id}" style="font-family: var(--font-code); color: ${isRevealed ? '#10B981' : 'var(--accent-gold)'}; font-size: 11px; background: rgba(0,0,0,0.4); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.08); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: ltr; flex: 1;">
                ${displayKey}
              </code>
              <button type="button" id="eye-btn-${r.telegram_id}" onclick="toggleReporterKeyVisibility('${r.telegram_id}')" class="btn btn-secondary" style="padding: 3px 6px; font-size: 11px;" title="إظهار/إخفاء">
                ${isRevealed ? '🙈' : '👁️'}
              </button>
              <button type="button" onclick="copyReporterKey('${safeKey}')" class="btn btn-secondary" style="padding: 3px 7px; font-size: 11px;" title="نسخ المفتاح">
                📋
              </button>
            </div>
          </td>
          <td style="text-align: center;">
            <span class="badge ${r.articles_today > 0 ? 'badge-success' : ''}" style="font-family: var(--font-code); font-weight: bold;">
              ${r.articles_today || 0}
            </span>
          </td>
          <td style="text-align: center;">
            <span style="font-family: var(--font-code); font-weight: bold; color: var(--accent-gold); font-size: 13.5px;">
              ${r.articles_total || 0}
            </span>
          </td>
          <td style="font-size: 12px; color: var(--text-muted);">
            ${(r.created_at || '').substring(0, 10) || '--'}
          </td>
          <td style="text-align: center;">
            <div style="display: flex; align-items: center; justify-content: center; gap: 6px;">
              <button type="button" onclick="openEditReporterModal('${r.telegram_id}')" class="btn btn-secondary" style="padding: 4px 8px; font-size: 11.5px;" title="تعديل">
                ✏️
              </button>
              <button type="button" onclick="deleteTelegramReporter('${r.telegram_id}', '${safeName}')" class="btn btn-danger" style="padding: 4px 8px; font-size: 11.5px;" title="حذف">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

  } else {
    // CARDS VIEW
    if (tableContainer) tableContainer.style.display = 'none';
    if (cardsContainer) cardsContainer.style.display = 'grid';

    if (!cardsContainer) return;
    if (filtered.length === 0) {
      cardsContainer.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 45px 20px; background: var(--bg-card); border-radius: 16px; border: 1px dashed var(--border-subtle);">
          <div style="font-size: 40px; margin-bottom: 12px;">🔍</div>
          <h4 style="font-size: 16px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px;">لم يتم العثور على أي صحفيين</h4>
          <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 16px;">لا توجد نتائج تطابق بحثك الحالي أو عامل التصفية المحدد.</p>
          <button type="button" onclick="resetReportersFilters()" class="btn btn-secondary" style="font-size: 12.5px;">
            إعادة تعيين الفلاتر
          </button>
        </div>`;
      return;
    }

    cardsContainer.innerHTML = filtered.map(r => {
      const isCustom = isCustomApiKey(r.api_key);
      const isRevealed = !!reporterKeyVisibility.get(r.telegram_id);
      const rawKey = r.api_key || 'غير محدد';
      const displayKey = isRevealed ? rawKey : maskApiKey(rawKey);
      const grad = getReporterAvatarGradient(r.name);
      const initials = getReporterInitials(r.name);
      const safeName = (r.name || '').replace(/'/g, "\\'");
      const safeKey = (r.api_key || '').replace(/'/g, "\\'");

      return `
        <div class="reporter-card">
          <div>
            <!-- Header: Avatar + Name + Title -->
            <div class="reporter-card-header">
              <div class="reporter-avatar" style="background: ${grad};">
                ${initials}
              </div>
              <div class="reporter-header-info">
                <h3 class="reporter-name" title="${r.name}">${r.name}</h3>
                <div class="reporter-role-title">${r.role || 'صحفي لدى'}</div>
              </div>
            </div>

            <!-- Badges Row -->
            <div class="reporter-badges-row">
              ${isCustom
                ? '<span class="rep-badge-pill rep-badge-emerald">🔑 مفتاح خاص</span>'
                : '<span class="rep-badge-pill rep-badge-amber">⚡ مفتاح النظام</span>'
              }
              <span class="rep-badge-pill rep-badge-stats">
                📰 ${r.articles_total || 0} خبر
                ${r.articles_today > 0 ? `<strong style="color: #10B981; margin-right: 3px;">(+${r.articles_today} اليوم)</strong>` : ''}
              </span>
            </div>

            <!-- Key & Telegram Metadata Container -->
            <div class="rep-key-container">
              <div class="rep-key-label-row">
                <span>معرّف تليجرام:</span>
                <span style="font-family: var(--font-code); color: #38BDF8; font-weight: 700; letter-spacing: 0.5px;">${r.telegram_id}</span>
              </div>
              
              <div class="rep-key-label-row" style="margin-top: 8px;">
                <span>مفتاح الربط (API Key):</span>
                <span style="font-size: 10.5px; color: ${isCustom ? '#10B981' : 'var(--accent-gold)'};">
                  ${isCustom ? 'حصة مستقلة' : 'مشترك مع البوت'}
                </span>
              </div>

              <!-- Strictly bounded & ellipsis key box -->
              <div class="rep-key-box">
                <span id="key-val-${r.telegram_id}" class="rep-key-value" title="${isRevealed ? rawKey : 'انقر على العين لإظهار المفتاح'}">
                  ${displayKey}
                </span>
                <div class="rep-key-actions">
                  <button type="button" id="eye-btn-${r.telegram_id}" onclick="toggleReporterKeyVisibility('${r.telegram_id}')" class="rep-icon-btn" title="${isRevealed ? 'إخفاء المفتاح' : 'إظهار المفتاح'}">
                    ${isRevealed ? '🙈' : '👁️'}
                  </button>
                  <button type="button" onclick="copyReporterKey('${safeKey}')" class="rep-icon-btn" title="نسخ المفتاح">
                    📋
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer Card Actions -->
          <div class="reporter-card-actions">
            <button type="button" onclick="copyReporterKey('${safeKey}')" class="btn btn-secondary" title="نسخ المفتاح للحافظة">
              📋 نسخ
            </button>
            <button type="button" onclick="openEditReporterModal('${r.telegram_id}')" class="btn btn-secondary" style="color: var(--accent-gold); border-color: rgba(245,158,11,0.3);" title="تعديل بيانات المراسل">
              ✏️ تعديل
            </button>
            <button type="button" onclick="deleteTelegramReporter('${r.telegram_id}', '${safeName}')" class="btn btn-danger" style="padding: 5px 9px;" title="حذف المراسل من النظام">
              🗑️
            </button>
          </div>
        </div>
      `;
    }).join('');
  }
}

function resetReportersFilters() {
  reportersSearch = '';
  reportersFilter = 'all';
  const searchInput = document.getElementById('reporters-search-input');
  if (searchInput) searchInput.value = '';
  const clearBtn = document.getElementById('reporters-clear-search');
  if (clearBtn) clearBtn.style.display = 'none';
  document.querySelectorAll('.rep-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === 'all');
  });
  renderReportersList();
}

async function loadReportersGrid() {
  const cardsContainer = document.getElementById('reporters-cards-container');
  const tableBody = document.getElementById('reporters-table-body');
  if (cardsContainer) {
    cardsContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">⏳ جاري تحميل بيانات وسجلات فريق المراسلين...</div>';
  }
  if (tableBody) {
    tableBody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 30px; color: var(--text-muted);">⏳ جاري جلب البيانات...</td></tr>';
  }

  try {
    const res = await apiCall('/api/reporters');
    reportersData = res.reporters || [];
    updateReportersKPIs();
    renderReportersList();
  } catch (err) {
    if (cardsContainer) {
      cardsContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--color-error); padding: 30px;">❌ خطأ في تحميل المراسلين: ${err.message}</div>`;
    }
  }
}

function openEditReporterModal(telegramId) {
  const reporter = reportersData.find(r => String(r.telegram_id) === String(telegramId));
  if (!reporter) {
    showToast('تعذر العثور على بيانات المراسل المحدد', 'error');
    return;
  }

  const modal = document.getElementById('modal-edit-reporter');
  if (!modal) return;

  document.getElementById('edit-reporter-original-id').value = reporter.telegram_id;
  document.getElementById('edit-reporter-id').value = reporter.telegram_id;
  document.getElementById('edit-reporter-name').value = reporter.name || '';
  document.getElementById('edit-reporter-role').value = reporter.role || 'صحفي لدى';
  document.getElementById('edit-reporter-key').value = (reporter.api_key && reporter.api_key !== 'غير محدد') ? reporter.api_key : '';

  modal.style.display = 'flex';
  document.getElementById('edit-reporter-name')?.focus();
}

function initReportersView() {
  // 1. Search input with live debounced filtering
  const searchInput = document.getElementById('reporters-search-input');
  const clearBtn = document.getElementById('reporters-clear-search');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      reportersSearch = e.target.value.trim();
      if (clearBtn) clearBtn.style.display = reportersSearch ? 'block' : 'none';
      renderReportersList();
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      reportersSearch = '';
      clearBtn.style.display = 'none';
      renderReportersList();
      searchInput?.focus();
    });
  }

  // 2. Filter tabs
  document.querySelectorAll('.rep-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.rep-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      reportersFilter = btn.dataset.filter || 'all';
      renderReportersList();
    });
  });

  // 3. View Mode Toggle (Cards vs Table)
  const btnCards = document.getElementById('rep-btn-view-cards');
  const btnTable = document.getElementById('rep-btn-view-table');
  if (btnCards && btnTable) {
    btnCards.addEventListener('click', () => {
      reportersViewMode = 'cards';
      btnCards.classList.add('active');
      btnTable.classList.remove('active');
      renderReportersList();
    });
    btnTable.addEventListener('click', () => {
      reportersViewMode = 'table';
      btnTable.classList.add('active');
      btnCards.classList.remove('active');
      renderReportersList();
    });
  }

  // 4. Refresh Button
  document.getElementById('btn-refresh-reporters')?.addEventListener('click', () => {
    loadReportersGrid();
    showToast('جاري تحديث بيانات الصحفيين... 🔄', 'info');
  });

  // 5. Add Reporter Modal Triggers from Reporters View
  const addModal = document.getElementById('modal-add-reporter');
  document.getElementById('btn-open-add-reporter-modal')?.addEventListener('click', () => {
    if (addModal) addModal.style.display = 'flex';
    document.getElementById('reporter-modal-name')?.focus();
  });

  // 6. Edit Reporter Modal Controls
  const editModal = document.getElementById('modal-edit-reporter');
  const closeEditBtns = [
    document.getElementById('btn-close-edit-reporter-modal'),
    document.getElementById('btn-cancel-edit-reporter')
  ];
  closeEditBtns.forEach(btn => {
    btn?.addEventListener('click', () => {
      if (editModal) editModal.style.display = 'none';
    });
  });

  // Generate Key in Edit Modal
  document.getElementById('btn-gen-new-rep-key')?.addEventListener('click', () => {
    const chars = '0123456789ABCDEF';
    let rand = '';
    for (let i = 0; i < 16; i++) rand += chars[Math.floor(Math.random() * chars.length)];
    const keyInput = document.getElementById('edit-reporter-key');
    if (keyInput) keyInput.value = `TD-${rand}`;
    showToast('تم توليد مفتاح ربط جديد ⚡', 'info');
  });

  // Edit Reporter Form Submit
  document.getElementById('form-edit-reporter')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const telegramId = document.getElementById('edit-reporter-id')?.value.trim();
    const name = document.getElementById('edit-reporter-name')?.value.trim();
    const role = document.getElementById('edit-reporter-role')?.value.trim() || 'صحفي لدى';
    const apiKey = document.getElementById('edit-reporter-key')?.value.trim() || undefined;

    if (!name || !telegramId) {
      showToast('يرجى ملء اسم الصحفي ومعرف تليجرام', 'warning');
      return;
    }

    try {
      const res = await apiCall('/api/reporters', 'POST', {
        name,
        telegram_id: telegramId,
        role,
        api_key: apiKey
      });

      showToast(res.message || 'تم تحديث بيانات الصحفي واعتماد المفتاح بنجاح 💾', 'success');
      if (editModal) editModal.style.display = 'none';
      await loadReportersGrid();
      await loadBotReportersTable();
      fetchBotTelemetry();
    } catch (err) {
      showToast(`فشل حفظ التعديلات: ${err.message}`, 'error');
    }
  });
}

// Expose globals for inline event handlers
window.toggleReporterKeyVisibility = toggleReporterKeyVisibility;
window.copyReporterKey = copyReporterKey;
window.openEditReporterModal = openEditReporterModal;
window.resetReportersFilters = resetReportersFilters;

// =============================================================================
// VIEW: TELEGRAM BOT CONTROL & LIFECYCLE (ADMIN EXCLUSIVE)
// =============================================================================

let botTelemetryTimer = null;

async function loadBotControlDashboard() {
  await fetchBotTelemetry();
  await loadBotReportersTable();
  await loadBotConsoleLogs();

  // Start fast polling every 4 seconds while on this view
  if (!botTelemetryTimer) {
    botTelemetryTimer = setInterval(async () => {
      if (State.currentView === 'bot-control') {
        await fetchBotTelemetry();
        await loadBotConsoleLogs();
      } else {
        stopBotTelemetryPolling();
      }
    }, 4000);
  }
}

function stopBotTelemetryPolling() {
  if (botTelemetryTimer) {
    clearInterval(botTelemetryTimer);
    botTelemetryTimer = null;
  }
}

let botUptimeTicker = null;
let currentUptimeSec = 0;

function formatUptimeDuration(totalSeconds) {
  const s = Math.max(0, parseInt(totalSeconds) || 0);
  const hrs = String(Math.floor(s / 3600)).padStart(2, '0');
  const mins = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const secs = String(s % 60).padStart(2, '0');
  return `${hrs}:${mins}:${secs}`;
}

function startClientUptimeTicker() {
  if (botUptimeTicker) clearInterval(botUptimeTicker);
  botUptimeTicker = setInterval(() => {
    const el = document.getElementById('bot-stat-uptime');
    if (el && State.botIsRunning) {
      currentUptimeSec++;
      el.textContent = formatUptimeDuration(currentUptimeSec);
    }
  }, 1000);
}

function stopClientUptimeTicker() {
  if (botUptimeTicker) {
    clearInterval(botUptimeTicker);
    botUptimeTicker = null;
  }
}

async function fetchBotTelemetry() {
  try {
    const res = await apiCall('/api/admin/bot/status');
    if (!res || !res.telemetry) return;
    const t = res.telemetry;

    State.botIsRunning = !!t.is_running;

    // Update Master Badge
    const mainBadge = document.getElementById('bot-main-badge');
    const navBadge = document.getElementById('nav-bot-status-badge');
    const btnStart = document.getElementById('btn-bot-start');
    const btnStop = document.getElementById('btn-bot-stop');
    const btnRestart = document.getElementById('btn-bot-restart');

    if (t.is_running) {
      if (mainBadge) {
        mainBadge.className = 'badge badge-success';
        mainBadge.textContent = '🟢 متصل ويعمل بنشاط';
      }
      if (navBadge) {
        navBadge.style.background = 'rgba(16,185,129,0.2)';
        navBadge.style.color = '#10B981';
        navBadge.style.borderColor = 'rgba(16,185,129,0.3)';
        navBadge.textContent = '🟢 متصل';
      }
      if (btnStart) btnStart.disabled = true;
      if (btnStop) btnStop.disabled = false;
      if (btnRestart) btnRestart.disabled = false;

      currentUptimeSec = t.uptime_seconds || 0;
      startClientUptimeTicker();
    } else {
      if (mainBadge) {
        mainBadge.className = 'badge';
        mainBadge.style.background = 'rgba(239,68,68,0.2)';
        mainBadge.style.color = '#EF4444';
        mainBadge.style.border = '1px solid rgba(239,68,68,0.3)';
        mainBadge.textContent = '🔴 متوقف حالياً';
      }
      if (navBadge) {
        navBadge.style.background = 'rgba(239,68,68,0.2)';
        navBadge.style.color = '#EF4444';
        navBadge.style.borderColor = 'rgba(239,68,68,0.3)';
        navBadge.textContent = '🔴 متوقف';
      }
      if (btnStart) btnStart.disabled = false;
      if (btnStop) btnStop.disabled = true;
      if (btnRestart) btnRestart.disabled = false;

      stopClientUptimeTicker();
    }

    // Telemetry Stats with full fallback support
    const artToday = t.articles_today_count ?? t.today_articles ?? 0;
    const artTotal = t.articles_total_count ?? t.total_articles ?? 0;
    const sessions = t.active_sessions_count ?? t.active_sessions ?? 0;
    const memMb = t.memory_rss_mb ?? t.memory_mb ?? 0;
    const repCount = t.reporters_count ?? t.total_reporters ?? 0;
    const startTimeStr = t.started_at_iso || t.start_time || '';

    const uptimeEl = document.getElementById('bot-stat-uptime');
    if (uptimeEl) {
      uptimeEl.textContent = t.is_running ? (t.uptime_formatted || formatUptimeDuration(t.uptime_seconds)) : '--:--:--';
    }

    const startedEl = document.getElementById('bot-stat-started-at');
    if (startedEl) {
      startedEl.textContent = (t.is_running && startTimeStr) ? `منذ: ${startTimeStr.replace('T', ' ').substring(0, 19)}` : 'متوقف حالياً';
    }

    const artTodayEl = document.getElementById('bot-stat-articles-today');
    if (artTodayEl) artTodayEl.textContent = artToday;

    const artTotalEl = document.getElementById('bot-stat-articles-total');
    if (artTotalEl) artTotalEl.textContent = artTotal;

    const sessionsEl = document.getElementById('bot-stat-sessions');
    if (sessionsEl) sessionsEl.textContent = sessions;

    const memEl = document.getElementById('bot-stat-memory');
    if (memEl) memEl.textContent = `${memMb} MB`;

    const repCountEl = document.getElementById('bot-stat-reporters-count');
    if (repCountEl) repCountEl.textContent = repCount;

    const handleEl = document.getElementById('bot-handle-text');
    if (handleEl && (t.bot_handle || t.bot_name)) handleEl.textContent = t.bot_handle || t.bot_name;

    const syncEl = document.getElementById('bot-last-sync-time');
    if (syncEl) syncEl.textContent = new Date().toLocaleTimeString('ar-EG');

    // Error Alert Box
    const errBox = document.getElementById('bot-error-alert');
    const errTxt = document.getElementById('bot-error-alert-text');
    if (errBox && errTxt) {
      if (t.last_error && !t.is_running) {
        errBox.style.display = 'block';
        errTxt.textContent = t.last_error;
      } else {
        errBox.style.display = 'none';
      }
    }
  } catch (err) {
    // Silent fail if not admin or network glitch
  }
}

async function loadBotReportersTable() {
  const tbody = document.getElementById('bot-reporters-table-body');
  if (!tbody) return;

  try {
    const res = await apiCall('/api/reporters');
    if (!res.reporters || res.reporters.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 25px; color: var(--text-muted);">لا يوجد مراسلين مسجلين بعد في قاعدة البيانات.</td></tr>';
      return;
    }

    tbody.innerHTML = res.reporters.map(r => `
      <tr>
        <td>
          <div style="font-weight: 700; color: var(--text-primary);">${r.name}</div>
          <span style="font-size: 11px; color: var(--text-muted);">${(r.created_at || '').substring(0, 10)}</span>
        </td>
        <td>
          <span class="badge" style="font-family: var(--font-code); background: rgba(56,189,248,0.15); color: #38BDF8; letter-spacing: 0.5px;">${r.telegram_id}</span>
        </td>
        <td>
          <span class="badge badge-gold">${r.role || 'صحفي لدى'}</span>
        </td>
        <td>
          <div style="display: flex; align-items: center; gap: 6px;">
            <code style="font-family: var(--font-code); color: var(--accent-gold); font-weight: bold; background: rgba(0,0,0,0.4); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(245,158,11,0.2);">${r.api_key || 'غير محدد'}</code>
            <button onclick="navigator.clipboard.writeText('${r.api_key}'); showToast('تم نسخ مفتاح الربط ✅', 'success');" class="btn btn-secondary" style="padding: 2px 7px; font-size: 11px;" title="نسخ المفتاح">📋</button>
          </div>
        </td>
        <td style="text-align: center;">
          <span class="badge ${r.articles_today > 0 ? 'badge-success' : ''}" style="font-family: var(--font-code); font-weight: bold;">${r.articles_today || 0}</span>
        </td>
        <td style="text-align: center;">
          <span style="font-family: var(--font-code); font-weight: bold; color: var(--text-primary);">${r.articles_total || 0}</span>
        </td>
        <td style="text-align: center;">
          <button onclick="deleteTelegramReporter('${r.telegram_id}', '${r.name}')" class="btn btn-danger" style="padding: 3px 8px; font-size: 11px;" title="حذف المراسل">🗑️ حذف</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--color-error); padding: 20px;">خطأ في جلب بيانات المراسلين: ${err.message}</td></tr>`;
  }
}

window.deleteTelegramReporter = async function (telegramId, name) {
  if (!confirm(`هل أنت متأكد من حذف المراسل: "${name}" (ID: ${telegramId})؟`)) return;
  try {
    const res = await apiCall(`/api/reporters/${telegramId}`, 'DELETE');
    showToast(res.message || 'تم حذف المراسل بنجاح', 'success');
    await loadBotReportersTable();
    loadReportersGrid();
    fetchBotTelemetry();
  } catch (err) {
    showToast(`فشل حذف المراسل: ${err.message}`, 'error');
  }
};

async function loadBotConsoleLogs() {
  const terminal = document.getElementById('bot-terminal-stream');
  if (!terminal) return;
  const filter = document.getElementById('bot-terminal-level-filter')?.value || 'ALL';

  try {
    const res = await apiCall('/api/admin/bot/logs?limit=80');
    if (!res.logs || res.logs.length === 0) {
      terminal.innerHTML = '<div style="color: var(--text-muted); padding: 10px;">لا توجد سجلات خاصة بالبوت حالياً.</div>';
      return;
    }

    let filtered = res.logs;
    if (filter !== 'ALL') {
      filtered = filtered.filter(l => l.level === filter);
    }

    // Sort chronologically (oldest top, newest bottom)
    const sorted = [...filtered].reverse();

    terminal.innerHTML = sorted.map(l => {
      let color = '#94A3B8';
      let icon = 'ℹ️';
      if (l.level === 'ERROR') { color = '#EF4444'; icon = '❌'; }
      else if (l.level === 'WARNING') { color = '#F59E0B'; icon = '⚠️'; }
      else if (l.level === 'INFO') { color = '#10B981'; icon = '⚡'; }

      const timeStr = (l.created_at || '').substring(11, 19) || '--:--:--';
      const userTag = l.user_name ? ` [${l.user_name}]` : '';

      return `<div style="line-height: 1.5; color: ${color};">
        <span style="color: #64748B;">[${timeStr}]</span>
        <strong>[${l.level}]</strong>
        <span style="color: #38BDF8;">[${l.module}${userTag}]:</span>
        <span>${l.message}</span>
      </div>`;
    }).join('');

    terminal.scrollTop = terminal.scrollHeight;
  } catch (err) {
    // Silent fail
  }
}

function initBotControlView() {
  // 1. Start Bot Button
  document.getElementById('btn-bot-start')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-bot-start');
    btn.disabled = true;
    showToast('⚡ جاري إطلاق بوت التليجرام...', 'info');
    try {
      const res = await apiCall('/api/admin/bot/start', 'POST');
      if (res.success) {
        showToast(res.message || 'تم تشغيل البوت بنجاح', 'success');
      } else {
        showToast(res.error || 'تعذر بدء تشغيل البوت', 'error');
      }
    } catch (err) {
      showToast(`خطأ: ${err.message}`, 'error');
    } finally {
      await fetchBotTelemetry();
      await loadBotConsoleLogs();
    }
  });

  // 2. Stop Bot Button
  document.getElementById('btn-bot-stop')?.addEventListener('click', async () => {
    if (!confirm('هل أنت متأكد من إيقاف تشغيل بوت التليجرام مؤقتاً؟ لن يتمكن الصحفيون من النشر عبره حتى إعادة تشغيله.')) return;
    const btn = document.getElementById('btn-bot-stop');
    btn.disabled = true;
    showToast('⏹️ جاري إيقاف البوت...', 'warning');
    try {
      const res = await apiCall('/api/admin/bot/stop', 'POST');
      showToast(res.message || 'تم إيقاف البوت', 'info');
    } catch (err) {
      showToast(`خطأ: ${err.message}`, 'error');
    } finally {
      await fetchBotTelemetry();
      await loadBotConsoleLogs();
    }
  });

  // 3. Restart Bot Button
  document.getElementById('btn-bot-restart')?.addEventListener('click', async () => {
    if (!confirm('هل تريد إعادة تشغيل بوت التليجرام وتنشيط اتصاله بالخادم؟')) return;
    const btn = document.getElementById('btn-bot-restart');
    btn.disabled = true;
    showToast('🔄 جاري إعادة تشغيل البوت...', 'info');
    try {
      const res = await apiCall('/api/admin/bot/restart', 'POST');
      if (res.success) {
        showToast(res.message || 'تمت إعادة تشغيل البوت بنجاح', 'success');
      } else {
        showToast(res.error || 'تعذر إعادة تشغيل البوت', 'error');
      }
    } catch (err) {
      showToast(`خطأ: ${err.message}`, 'error');
    } finally {
      await fetchBotTelemetry();
      await loadBotConsoleLogs();
    }
  });

  // 4. Refresh Button
  document.getElementById('btn-bot-refresh')?.addEventListener('click', async () => {
    showToast('🔄 جاري تحديث بيانات البوت...', 'info');
    await fetchBotTelemetry();
    await loadBotReportersTable();
    await loadBotConsoleLogs();
    showToast('تم تحديث القياسات اللحظية ✅', 'success');
  });

  // 5. Broadcast Message Button
  document.getElementById('btn-bot-send-broadcast')?.addEventListener('click', async () => {
    const input = document.getElementById('bot-broadcast-message');
    const msg = (input?.value || '').trim();
    if (!msg) {
      showToast('يرجى كتابة نص التعميم أولاً', 'warning');
      input?.focus();
      return;
    }

    if (!confirm(`هل أنت متأكد من بث هذا التعميم فوراً لجميع المراسلين على تليجرام؟\n\nنص الرسالة: "${msg.substring(0, 60)}..."`)) return;

    const btn = document.getElementById('btn-bot-send-broadcast');
    const statusEl = document.getElementById('bot-broadcast-status');
    btn.disabled = true;
    btn.innerHTML = '⏳ جاري البث...';
    if (statusEl) statusEl.textContent = 'جاري إرسال الرسالة للمراسلين...';

    try {
      const res = await apiCall('/api/admin/bot/broadcast', 'POST', { message: msg });
      if (res.success) {
        showToast(res.message || 'تم بث التعميم بنجاح 🚀', 'success');
        if (input) input.value = '';
        if (statusEl) {
          statusEl.style.color = '#10B981';
          statusEl.textContent = `✅ وصل إلى ${res.sent_count || 0} مراسل`;
          setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 6000);
        }
      } else {
        showToast(res.error || 'فشل إرسال التعميم', 'error');
        if (statusEl) {
          statusEl.style.color = '#EF4444';
          statusEl.textContent = `❌ ${res.error || 'خطأ أثناء الإرسال'}`;
        }
      }
    } catch (err) {
      showToast(`خطأ: ${err.message}`, 'error');
      if (statusEl) {
        statusEl.style.color = '#EF4444';
        statusEl.textContent = `❌ ${err.message}`;
      }
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<span>🚀</span><span>إرسال التعميم لجميع الصحفيين</span>';
      await loadBotConsoleLogs();
    }
  });

  // 6. Terminal filters & buttons
  document.getElementById('bot-terminal-level-filter')?.addEventListener('change', loadBotConsoleLogs);
  document.getElementById('btn-refresh-bot-terminal')?.addEventListener('click', loadBotConsoleLogs);
  document.getElementById('btn-clear-bot-terminal')?.addEventListener('click', () => {
    const term = document.getElementById('bot-terminal-stream');
    if (term) term.innerHTML = '<div style="color: var(--text-muted);">تم مسح شاشة الكونسول. في انتظار أحداث جديدة...</div>';
  });

  // 7. Add Reporter Modal Trigger
  const modal = document.getElementById('modal-add-reporter');
  const openBtns = [document.getElementById('btn-open-add-bot-reporter'), document.getElementById('btn-open-add-reporter-modal')];
  openBtns.forEach(b => {
    b?.addEventListener('click', () => {
      if (modal) modal.style.display = 'flex';
      document.getElementById('reporter-modal-name')?.focus();
    });
  });

  const closeBtns = [document.getElementById('btn-close-add-reporter-modal'), document.getElementById('btn-cancel-add-reporter')];
  closeBtns.forEach(b => {
    b?.addEventListener('click', () => {
      if (modal) modal.style.display = 'none';
    });
  });

  // 8. Add Reporter Form Submit
  document.getElementById('form-add-reporter')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('reporter-modal-name')?.value.trim();
    const telegramId = document.getElementById('reporter-modal-id')?.value.trim();
    const role = document.getElementById('reporter-modal-role')?.value.trim() || 'صحفي لدى';
    const apiKey = document.getElementById('reporter-modal-key')?.value.trim() || undefined;

    if (!name || !telegramId) {
      showToast('يرجى ملء اسم الصحفي ومعرف تليجرام', 'warning');
      return;
    }

    try {
      const res = await apiCall('/api/reporters', 'POST', {
        name,
        telegram_id: telegramId,
        role,
        api_key: apiKey
      });

      showToast(res.message || 'تم اعتماد الصحفي بنجاح 🔑', 'success');
      if (modal) modal.style.display = 'none';
      document.getElementById('form-add-reporter')?.reset();
      await loadBotReportersTable();
      loadReportersGrid();
      fetchBotTelemetry();
    } catch (err) {
      showToast(`فشل حفظ المراسل: ${err.message}`, 'error');
    }
  });
}

// =============================================================================
// VIEW 6: SETTINGS & JOURNALIST ROLES CONTROLLER
// =============================================================================
async function loadSettingsData() {
  try {
    const s = await apiCall('/api/settings');
    const blogIdEl = document.getElementById('settings-blog-id');
    const aiModelEl = document.getElementById('settings-ai-model');
    const statusBadge = document.getElementById('settings-blogger-status');
    const quotaText = document.getElementById('settings-quota-text');

    if (blogIdEl) blogIdEl.textContent = s.blog_id || 'غير محدد';
    if (aiModelEl) aiModelEl.value = s.zai_model || 'glm-4.7-flash';
    if (statusBadge) {
      if (s.is_blogger_auth) {
        statusBadge.textContent = '🟢 متصل بنجاح';
        statusBadge.className = 'badge badge-success';
        statusBadge.style.background = '';
        statusBadge.style.color = '';
      } else {
        statusBadge.textContent = '🔴 غير متصل';
        statusBadge.className = 'badge';
        statusBadge.style.background = 'rgba(239, 68, 68, 0.15)';
        statusBadge.style.color = '#EF4444';
        statusBadge.style.border = '1px solid rgba(239, 68, 68, 0.3)';
      }
    }

    if (quotaText && s.quota) {
      const used = s.quota.used || 0;
      const limit = s.quota.limit || 10000;
      const rem = s.quota.remaining || Math.max(0, limit - used);
      quotaText.textContent = `${used.toLocaleString()} من ${limit.toLocaleString()} طلب (${rem.toLocaleString()} متبقي)`;
    }

    // Update Journalist Personal AI Key Status
    if (s.user_ai_key) {
      State.hasAiKey = !!s.user_ai_key.has_key;
      State.maskedAiKey = s.user_ai_key.masked_key || '';
      updateAiKeyUI();
    } else {
      await checkUserAiKeyStatus();
    }

    // Google Account Identity & State Controller
    const connectedCard = document.getElementById('google-account-card-connected');
    const disconnectedCard = document.getElementById('google-account-card-disconnected');
    const nameEl = document.getElementById('google-account-name');
    const emailEl = document.getElementById('google-account-email');
    const avatarEl = document.getElementById('google-account-avatar');
    const btnLoginNew = document.getElementById('btn-login-new-google');

    const g = s.google_account;
    if (s.is_blogger_auth && g && g.is_connected) {
      if (connectedCard) connectedCard.style.display = 'flex';
      if (disconnectedCard) disconnectedCard.style.display = 'none';
      if (nameEl) nameEl.textContent = g.name || 'حساب Google المتصل';
      if (emailEl) emailEl.textContent = g.email || '—';
      if (avatarEl) {
        if (g.picture) {
          avatarEl.src = g.picture;
        } else {
          avatarEl.src = '/assets/google_icon.png';
        }
      }
      if (btnLoginNew) {
        btnLoginNew.innerHTML = '<span>🔄</span><span>تسجيل بحساب Google جديد (أو تبديل الحساب)</span>';
      }
    } else {
      if (connectedCard) connectedCard.style.display = 'none';
      if (disconnectedCard) disconnectedCard.style.display = 'block';
      if (btnLoginNew) {
        btnLoginNew.innerHTML = '<span>🔑</span><span>تسجيل الدخول وربط حساب Google جديد</span>';
      }
    }
  } catch (e) {
    console.error('Failed to load settings data:', e);
  }

  // Load Journalist Roles and Activation Codes if Admin
  if (State.user?.role === 'admin') {
    loadUsersManagementTable();
    loadActivationCodesTable();
  }
}

async function loadUsersManagementTable() {
  const tbody = document.getElementById('users-table-body');
  if (!tbody) return;

  try {
    const res = await apiCall('/api/auth/users');
    if (res.success && res.users) {
      tbody.innerHTML = res.users.map(u => {
        const isCurrent = u.id === State.user?.id;
        let roleBadge = '<span class="badge badge-info" style="background: rgba(59,130,246,0.2); color:#60A5FA;">✍️ صحفي معتمد</span>';
        if (u.role === 'admin') {
          roleBadge = '<span class="badge badge-gold">👑 رئيس التحرير</span>';
        } else if (u.role === 'editor') {
          roleBadge = '<span class="badge badge-purple" style="background: rgba(168,85,247,0.2); color:#C084FC;">⭐ صحفي مميز</span>';
        }

        const avatar = u.google_avatar
          ? `<img src="${u.google_avatar}" style="width:28px;height:28px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-left:8px;">`
          : `<span style="display:inline-block;width:28px;height:28px;border-radius:50%;background:var(--bg-card);text-align:center;line-height:28px;margin-left:8px;font-size:12px;">👤</span>`;

        return `
          <tr>
            <td>
              <div style="display: flex; align-items: center;">
                ${avatar}
                <strong>${u.full_name || u.username}</strong>
                ${isCurrent ? ' <span style="font-size:10px;color:var(--accent-gold);margin-right:6px;">(أنت)</span>' : ''}
              </div>
            </td>
            <td style="font-family: var(--font-code); color: var(--text-secondary);">${u.email || 'حساب محلي'}</td>
            <td style="font-size: 11.5px; color: var(--text-muted);">${(u.created_at || '').substring(0, 10)}</td>
            <td>${roleBadge}</td>
            <td style="text-align: center;">
              <div style="display: flex; justify-content: center; gap: 8px; align-items: center;">
                <select id="role-select-${u.id}" class="form-input" style="padding: 4px 8px; font-size: 12px; width: 140px;">
                  <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>👑 رئيس تحرير</option>
                  <option value="editor" ${u.role === 'editor' ? 'selected' : ''}>⭐ صحفي مميز</option>
                  <option value="journalist" ${u.role === 'journalist' ? 'selected' : ''}>✍️ صحفي معتمد</option>
                </select>
                <button onclick="changeUserRole(${u.id})" class="btn btn-gold" style="font-size: 11.5px; padding: 4px 10px;">حفظ</button>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--color-error);">خطأ: ${err.message}</td></tr>`;
  }
}

window.changeUserRole = async function (userId) {
  const select = document.getElementById(`role-select-${userId}`);
  if (!select) return;
  const newRole = select.value;

  try {
    const res = await apiCall(`/api/auth/users/${userId}/role`, 'POST', { role: newRole });
    showToast(res.message || 'تم تحديث الرتبة بنجاح ✅', 'success');
    if (userId === State.user?.id) {
      State.user.role = newRole;
      updateUserProfileUI();
    }
    loadUsersManagementTable();
  } catch (err) {
    showToast(`فشل تحديث الرتبة: ${err.message}`, 'error');
  }
};

async function loadActivationCodesTable() {
  const tbody = document.getElementById('activation-codes-table-body');
  if (!tbody) return;

  try {
    const res = await apiCall('/api/admin/activation-codes');
    if (res.success && res.codes) {
      if (res.codes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">لا توجد أكواد تفعيل مصدرة حالياً. يمكنك توليد كود جديد من النموذج أعلاه.</td></tr>';
        return;
      }
      tbody.innerHTML = res.codes.map(c => {
        let statusBadge = '<span class="badge badge-warning" style="background: rgba(245,158,11,0.15); color: var(--accent-gold);">⏳ قيد الانتظار</span>';
        if (c.status === 'USED') {
          statusBadge = `<span class="badge badge-success" title="مفعل بواسطة: ${c.used_by_email}">✅ مفعل (${(c.used_by_email || '').split('@')[0]})</span>`;
        } else if (c.status === 'REVOKED') {
          statusBadge = '<span class="badge" style="background: rgba(239,68,68,0.15); color: #EF4444;">❌ ملغي</span>';
        }

        let roleBadge = '<span class="badge badge-info">✍️ صحفي معتمد</span>';
        if (c.role === 'admin') roleBadge = '<span class="badge badge-gold">👑 رئيس تحرير</span>';
        else if (c.role === 'editor') roleBadge = '<span class="badge badge-purple" style="background: rgba(168,85,247,0.2); color:#C084FC;">⭐ صحفي مميز</span>';

        return `
          <tr>
            <td>
              <span style="font-family: var(--font-code); font-weight: bold; color: var(--accent-gold); letter-spacing: 1px;">${c.code}</span>
              <button onclick="navigator.clipboard.writeText('${c.code}'); showToast('تم نسخ كود التفعيل ✅', 'success');" class="btn btn-secondary" style="padding: 2px 6px; font-size: 11px; margin-right: 6px;">📋</button>
            </td>
            <td><strong>${c.journalist_name}</strong></td>
            <td style="font-family: var(--font-code);">${c.journalist_phone}</td>
            <td>${roleBadge}</td>
            <td>${statusBadge}</td>
            <td style="font-size: 11px; color: var(--text-muted);">${(c.created_at || '').substring(0, 16)}</td>
            <td style="text-align: center;">
              ${c.status === 'PENDING' ? `<button onclick="revokeActivationCode('${c.code}')" class="btn btn-secondary" style="font-size: 11px; color: #EF4444; border-color: rgba(239,68,68,0.3); padding: 3px 8px;">إلغاء</button>` : '—'}
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--color-error);">خطأ: ${err.message}</td></tr>`;
  }
}

window.revokeActivationCode = async function (code) {
  if (!confirm(`هل أنت متأكد من إلغاء كود التفعيل: ${code}؟`)) return;
  try {
    const res = await apiCall(`/api/admin/activation-codes/${code}`, 'DELETE');
    showToast(res.message || 'تم إيقاف الكود', 'info');
    loadActivationCodesTable();
  } catch (e) {
    showToast(`فشل إلغاء الكود: ${e.message}`, 'error');
  }
};

// =============================================================================
// VIEW 7: LOGS & WEBSOCKET RADAR
// =============================================================================
async function loadLogsTerminal() {
  const term = document.getElementById('logs-terminal');
  const level = document.getElementById('logs-filter-level')?.value || 'ALL';

  try {
    const res = await apiCall(`/api/logs?level=${level}`);
    if (res.logs) {
      term.innerHTML = res.logs.map(l => {
        let color = '#94A3B8';
        if (l.level === 'ERROR') color = '#EF4444';
        if (l.level === 'WARNING') color = '#F59E0B';
        if (l.level === 'INFO') color = '#10B981';
        return `<div style="line-height: 1.5;"><span style="color: #64748B;">[${(l.created_at || '').substring(11, 19)}]</span> <span style="color: ${color}; font-weight: bold;">[${l.level}]</span> <span style="color: var(--accent-gold);">[${l.module}]</span> ${l.message}</div>`;
      }).join('');
      term.scrollTop = 0;
    }
  } catch (err) {
    term.innerHTML = `<div style="color: var(--color-error);">فشل جلب السجلات: ${err.message}</div>`;
  }
}

function initWebSocketLogs() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/ws/logs`;

  try {
    State.ws = new WebSocket(wsUrl);
    State.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // 1. LIVE BACKEND PUBLISH STEPS
        if (data.type === 'publish_step') {
          updatePublishModalStep(data.percent, data.text);
        }

        // 2. LIVE SYSTEM LOGS STREAM
        if (data.type === 'log') {
          // Update View 7 Terminal
          const term = document.getElementById('logs-terminal');
          if (term) {
            const div = document.createElement('div');
            div.style.lineHeight = '1.5';
            div.innerHTML = `<span style="color: #64748B;">[الآن]</span> <span style="color: #10B981; font-weight: bold;">[${data.level}]</span> <span style="color: var(--accent-gold);">[${data.module}]</span> ${data.message}`;
            term.insertBefore(div, term.firstChild);
          }

          // Update Live Modal Terminal Strip if modal is open
          const modalLog = document.getElementById('publish-live-log-text');
          if (modalLog) {
            modalLog.textContent = `[${data.module || 'سيرفر'}]: ${data.message}`;
          }
        }
      } catch (e) { }
    };
    State.ws.onclose = () => {
      setTimeout(initWebSocketLogs, 5000);
    };
  } catch (e) { }
}

// =============================================================================
// VIEW 8: ACCOUNTING & REVENUE HUB CONTROLLER
// =============================================================================

function normalizeArabicText(str) {
  if (!str) return '';
  return String(str)
    .toLowerCase()
    .replace(/[أإآء]/g, 'ا')
    .replace(/ة/g, 'ه')
    .replace(/ى/g, 'ي')
    .replace(/[\u064B-\u065F]/g, '')
    .trim();
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function loadAccountingDashboard() {
  try {
    // 1. Fetch Financial Settings & Role Effective Cut
    const settingsRes = await apiCall('/api/accounting/settings');
    if (settingsRes.success) {
      State.officialPrice = Number(settingsRes.settings?.official_article_price) || 150;
      State.userEffectiveCut = Number(settingsRes.effective_cut);
      if (isNaN(State.userEffectiveCut)) {
        State.userEffectiveCut = (State.user?.role === 'admin' ? 0 : 75);
      }

      // Update Policy Info Bar
      const officialPriceEl = document.getElementById('acc-official-price-banner');
      const userCutEl = document.getElementById('acc-user-cut-banner');
      const userNetEl = document.getElementById('acc-user-net-banner');
      const roleBadgeEl = document.getElementById('acc-user-role-badge');

      if (officialPriceEl) officialPriceEl.textContent = `${State.officialPrice.toFixed(2)} ج.م`;
      if (userCutEl) {
        if (settingsRes.user_custom_cut !== null && settingsRes.user_custom_cut !== undefined) {
          userCutEl.innerHTML = `<span style="color:var(--accent-gold); font-weight:700;">${State.userEffectiveCut.toFixed(2)} ج.م</span> <span style="font-size:10.5px;color:var(--text-muted);">(نسبة مخصصة لك ⭐)</span>`;
        } else {
          userCutEl.textContent = `${State.userEffectiveCut.toFixed(2)} ج.م`;
        }
      }

      if (userNetEl) {
        const estNet = Math.max(0, State.officialPrice - State.userEffectiveCut);
        const estPct = State.officialPrice > 0 ? Math.round((estNet / State.officialPrice) * 100) : 0;
        userNetEl.innerHTML = `<span style="font-weight:800;">${estNet.toFixed(2)} ج.م</span> <span style="font-size:11px; color:var(--text-muted);">(${estPct}%)</span>`;
      }

      if (roleBadgeEl) {
        if (settingsRes.user_role === 'admin') {
          roleBadgeEl.textContent = '👑 رئيس تحرير (إعفاء كامل 0%)';
          roleBadgeEl.className = 'badge badge-gold';
        } else if (settingsRes.user_role === 'editor') {
          roleBadgeEl.textContent = '⭐ صحفي مميز (استقطاع مخفض)';
          roleBadgeEl.className = 'badge badge-gold';
        } else {
          roleBadgeEl.textContent = '✍️ صحفي معتمد';
          roleBadgeEl.className = 'badge badge-success';
        }
      }

      // Default amount in new tx modal
      const amountInput = document.getElementById('tx-amount-paid');
      if (amountInput && (!amountInput.value || amountInput.value === '150')) {
        amountInput.value = State.officialPrice;
      }
    }
  } catch (err) {
    console.error('Failed to load accounting settings:', err);
  }

  // 2. Load Stats
  await loadAccountingStats();

  // 3. Load Transactions Table
  await loadAccountingTransactions();

  // 4. Load Unbilled Articles Picker
  await loadUnbilledPicker();

  // 5. If Admin, load Master Financial Vault
  if (State.user?.role === 'admin') {
    await loadAdminVault();
  }
}

async function loadAccountingStats() {
  try {
    let url = `/api/accounting/my-stats?time_range=${encodeURIComponent(State.accountingTimeRange)}`;
    if (State.accountingTimeRange === 'custom') {
      if (State.accountingCustomStart) url += `&start_date=${encodeURIComponent(State.accountingCustomStart)}`;
      if (State.accountingCustomEnd) url += `&end_date=${encodeURIComponent(State.accountingCustomEnd)}`;
    }

    const res = await apiCall(url);
    if (res.success && res.stats) {
      const s = res.stats;
      const countEl = document.getElementById('acc-stat-count');
      const grossEl = document.getElementById('acc-stat-gross');
      const cutEl = document.getElementById('acc-stat-cut');
      const pendingEl = document.getElementById('acc-stat-pending');
      const netEl = document.getElementById('acc-stat-net');

      const grossVal = Number(s.gross_revenue ?? s.total_gross ?? 0);
      const cutVal = Number(s.newspaper_cut ?? s.total_newspaper_cut ?? 0);
      const pendingVal = Number(s.pending_due ?? s.pending_newspaper_cut ?? 0);
      const netVal = Number(s.net_profit ?? s.total_net_profit ?? s.journalist_net ?? 0);

      if (countEl) countEl.textContent = s.total_articles || 0;
      if (grossEl) grossEl.textContent = isNaN(grossVal) ? '0.00' : grossVal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (cutEl) cutEl.textContent = isNaN(cutVal) ? '0.00' : cutVal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (pendingEl) pendingEl.textContent = isNaN(pendingVal) ? '0.00' : pendingVal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (netEl) netEl.textContent = isNaN(netVal) ? '0.00' : netVal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

      if (s.effective_cut !== undefined && !isNaN(Number(s.effective_cut))) {
        State.userEffectiveCut = Number(s.effective_cut);
      }
    }
  } catch (err) {
    console.error('Failed to load accounting stats:', err);
  }
}

async function loadAccountingTransactions() {
  const tbody = document.getElementById('accounting-table-body');
  if (!tbody) return;

  try {
    let url = `/api/accounting/my-transactions?time_range=${encodeURIComponent(State.accountingTimeRange)}`;
    if (State.accountingTimeRange === 'custom') {
      if (State.accountingCustomStart) url += `&start_date=${encodeURIComponent(State.accountingCustomStart)}`;
      if (State.accountingCustomEnd) url += `&end_date=${encodeURIComponent(State.accountingCustomEnd)}`;
    }

    const res = await apiCall(url);
    if (res.success && res.transactions) {
      if (res.transactions.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 30px;">
              لا توجد عمليات تحصيل مسجلة لهذه الفترة. اضغط على <strong>"تسجيل تحصيل خبر جديد"</strong> لإضافة معاملة.
            </td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = res.transactions.map(tx => {
        const titleHtml = tx.article_url
          ? `<a href="${escapeHtml(tx.article_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--text-primary); text-decoration:none; font-weight:600; display:flex; align-items:center; gap:6px;">
               <span>${escapeHtml(tx.article_title)}</span>
               <span style="font-size:11px; color:var(--accent-gold);">🔗</span>
             </a>`
          : `<strong>${escapeHtml(tx.article_title)}</strong>`;

        const authorBadge = tx.author_name ? `<div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">✍️ ${escapeHtml(tx.author_name)}</div>` : '';

        let methodBadge = '<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #F87171; border: 1px solid rgba(239,68,68,0.3); font-size: 11px;">📱 فودافون كاش</span>';
        if (tx.payment_method === 'instapay') {
          methodBadge = '<span class="badge" style="background: rgba(168, 85, 247, 0.15); color: #C084FC; border: 1px solid rgba(168,85,247,0.3); font-size: 11px;">⚡ إنستاباي</span>';
        }

        const isSettled = Boolean(tx.is_settled || tx.settlement_status === 'SETTLED');
        const settlementBadge = isSettled
          ? `<span class="badge badge-success" style="font-size: 11px;" title="تمت التسوية بواسطة: ${escapeHtml(tx.settled_by || 'الإدارة')} في ${(tx.settled_at || '').substring(0, 10)}">✅ تم التوريد</span>`
          : '<span class="badge badge-warning" style="font-size: 11px; background: rgba(245,158,11,0.15); color: #F59E0B;">⏳ معلق للتوريد</span>';

        const canDelete = !isSettled || State.user?.role === 'admin';
        const deleteBtn = canDelete
          ? `<button onclick="deleteAccountingTx(${tx.id})" class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px; color: #EF4444; border-color: rgba(239,68,68,0.3);" title="حذف السجل">🗑️ حذف</button>`
          : '—';

        const amountPaid = Number(tx.amount_paid || 0);
        const newspaperCut = Number(tx.newspaper_cut || 0);
        const rawNet = (tx.net_profit !== undefined && tx.net_profit !== null && !isNaN(tx.net_profit)) 
          ? Number(tx.net_profit) 
          : ((tx.journalist_net !== undefined && tx.journalist_net !== null && !isNaN(tx.journalist_net)) 
              ? Number(tx.journalist_net) 
              : Math.max(0, amountPaid - newspaperCut));
        const netProfit = isNaN(rawNet) ? 0 : rawNet;
        const profitPct = amountPaid > 0 ? Math.round((netProfit / amountPaid) * 100) : 0;

        return `
          <tr>
            <td style="max-width: 240px; word-break: break-word;">
              ${titleHtml}
              ${authorBadge}
            </td>
            <td>${escapeHtml(tx.client_name || '—')}</td>
            <td style="font-family: var(--font-code); font-size: 12px; color: var(--text-secondary);">${escapeHtml(tx.client_phone || '—')}</td>
            <td style="text-align: center; font-family: var(--font-code); font-weight: bold; color: #38BDF8;">${amountPaid.toFixed(2)} ج.م</td>
            <td style="text-align: center; font-family: var(--font-code); color: #F87171;">${newspaperCut.toFixed(2)} ج.م</td>
            <td style="text-align: center;">
              <div style="font-family: var(--font-code); font-weight: 800; color: #10B981; font-size: 13.5px;">${netProfit.toFixed(2)} ج.م</div>
              <div style="font-size: 10px; color: var(--text-muted); font-weight: 600;">(${profitPct}% صافي ربحك)</div>
            </td>
            <td>${methodBadge}</td>
            <td style="font-size: 11.5px; color: var(--text-muted);">${(tx.created_at || '').substring(0, 16)}</td>
            <td>${settlementBadge}</td>
            <td style="text-align: center;">${deleteBtn}</td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--color-error); padding: 20px;">فشل جلب المعاملات: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderUnbilledPickerOptions(articles, searchQuery = '') {
  const picker = document.getElementById('tx-unbilled-picker');
  const countBadge = document.getElementById('tx-unbilled-count-badge');
  const searchHint = document.getElementById('tx-unbilled-search-hint');
  const clearBtn = document.getElementById('btn-clear-unbilled-search');
  if (!picker) return;

  if (clearBtn) {
    clearBtn.style.display = searchQuery ? 'block' : 'none';
  }

  const allArticles = articles || State.unbilledArticles || [];
  if (countBadge) {
    countBadge.textContent = `${allArticles.length} متاح`;
  }

  if (allArticles.length === 0) {
    picker.innerHTML = '<option value="">-- لا توجد مقالات منشورة غير محاسب عليها (أدخل البيانات يدوياً) --</option>';
    if (searchHint) searchHint.style.display = 'none';
    return;
  }

  let filtered = allArticles;
  if (searchQuery) {
    const q = normalizeArabicText(searchQuery);
    filtered = allArticles.filter(a => {
      const titleNorm = normalizeArabicText(a.title);
      const clientNorm = normalizeArabicText(a.client_name);
      const phoneNorm = normalizeArabicText(a.client_phone);
      return titleNorm.includes(q) || clientNorm.includes(q) || phoneNorm.includes(q);
    });
  }

  if (filtered.length === 0) {
    picker.innerHTML = `<option value="">-- لا توجد نتائج مطابقة لبحثك ("${escapeHtml(searchQuery)}") --</option>`;
    if (searchHint) {
      searchHint.style.display = 'block';
      searchHint.textContent = '💡 لم نجد خبراً مطابقاً للبحث، يمكنك كتابة بيانات الخبر يدوياً بالأسفل ✍️';
    }
    return;
  }

  if (searchHint) {
    if (searchQuery) {
      searchHint.style.display = 'block';
      searchHint.textContent = `⚡ تم العثور على ${filtered.length} خبر مطابق — اختر من القائمة لملء الحقول تلقائياً`;
    } else {
      searchHint.style.display = 'none';
    }
  }

  picker.innerHTML = `
    <option value="">-- اختر خبراً لملء البيانات تلقائياً (${filtered.length} ${searchQuery ? 'مطابق' : 'متاح'}) --</option>
    ${filtered.map(a => `
      <option value="${a.id}">
        📰 ${escapeHtml(a.title)} | ${escapeHtml(a.client_name || 'عميل')} (${escapeHtml(a.client_phone || 'بدون هاتف')})
      </option>
    `).join('')}
  `;
}

async function loadUnbilledPicker() {
  const picker = document.getElementById('tx-unbilled-picker');
  const searchInput = document.getElementById('tx-unbilled-search');
  if (!picker) return;

  try {
    const res = await apiCall('/api/accounting/unbilled-articles');
    if (res.success && res.articles) {
      State.unbilledArticles = res.articles;
      const currentQuery = searchInput ? searchInput.value.trim() : '';
      renderUnbilledPickerOptions(res.articles, currentQuery);
    }
  } catch (err) {
    console.error('Failed to load unbilled articles:', err);
  }
}

function updateTxLivePreview() {
  const amountInput = document.getElementById('tx-amount-paid');
  const previewCut = document.getElementById('tx-preview-cut');
  const previewNet = document.getElementById('tx-preview-net');
  if (!amountInput || !previewCut || !previewNet) return;

  const amount = parseFloat(amountInput.value) || 0;
  let effectiveCut = 75;
  if (State.user?.role === 'admin') {
    effectiveCut = 0;
  } else if (State.userEffectiveCut !== undefined && !isNaN(Number(State.userEffectiveCut))) {
    effectiveCut = Number(State.userEffectiveCut);
  }

  const cut = Math.min(amount, Math.max(0, effectiveCut));
  const net = Math.max(0, amount - cut);
  const pct = amount > 0 ? Math.round((net / amount) * 100) : 0;

  previewCut.textContent = `${cut.toFixed(2)} ج.م`;
  previewNet.innerHTML = `${net.toFixed(2)} ج.م <span style="font-size: 11px; color: var(--text-muted); font-weight: normal;">(${pct}%)</span>`;
}

// Admin Vault Functions
async function loadAdminVault() {
  try {
    let url = `/api/admin/accounting/overview?time_range=${encodeURIComponent(State.accountingTimeRange)}`;
    if (State.accountingTimeRange === 'custom') {
      if (State.accountingCustomStart) url += `&start_date=${encodeURIComponent(State.accountingCustomStart)}`;
      if (State.accountingCustomEnd) url += `&end_date=${encodeURIComponent(State.accountingCustomEnd)}`;
    }

    const res = await apiCall(url);
    if (res.success && res.overview) {
      const o = res.overview;
      const totalCutEl = document.getElementById('vault-stat-total-cut');
      const payoutsEl = document.getElementById('vault-stat-payouts');
      const pendingEl = document.getElementById('vault-stat-pending');
      const txCountEl = document.getElementById('vault-stat-tx-count');

      if (totalCutEl) totalCutEl.textContent = Number(o.total_newspaper_vault || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (payoutsEl) payoutsEl.textContent = Number(o.total_journalist_payouts ?? o.total_reporters_net ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (pendingEl) pendingEl.textContent = Number(o.total_pending_vault ?? o.pending_vault_cut ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (txCountEl) txCountEl.textContent = o.total_transactions || 0;

      const priceInput = document.getElementById('setting-official-price');
      const certInput = document.getElementById('setting-cut-certified');
      const premInput = document.getElementById('setting-cut-premium');

      if (priceInput && !priceInput.matches(':focus')) priceInput.value = o.official_article_price ?? o.official_price ?? 150;
      if (certInput && !certInput.matches(':focus')) certInput.value = o.cut_certified_journalist ?? o.cut_certified ?? 75;
      if (premInput && !premInput.matches(':focus')) premInput.value = o.cut_premium_editor ?? o.cut_premium ?? 50;
    }
  } catch (err) {
    console.error('Failed to load admin vault overview:', err);
  }

  // Load Reporters Financial Ledger
  const tbody = document.getElementById('vault-reporters-ledger-body');
  if (!tbody) return;

  try {
    const res = await apiCall('/api/admin/accounting/reporters-ledger');
    if (res.success && res.ledger) {
      if (res.ledger.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 20px;">لا يوجد صحفيين مسجلين في الجريدة حتى الآن.</td></tr>';
        return;
      }

      tbody.innerHTML = res.ledger.map(r => {
        let roleBadge = '<span class="badge badge-info" style="font-size: 11px;">✍️ صحفي معتمد</span>';
        if (r.role === 'admin') roleBadge = '<span class="badge badge-gold" style="font-size: 11px;">👑 رئيس تحرير</span>';
        else if (r.role === 'editor') roleBadge = '<span class="badge badge-purple" style="font-size: 11px; background: rgba(168,85,247,0.2); color:#C084FC;">⭐ صحفي مميز</span>';

        const appliedCutBadge = (r.custom_deduction !== null && r.custom_deduction !== undefined)
          ? `<span class="badge badge-gold" style="font-size: 11px;" title="نسبة مخصصة فردية">⭐ ${r.effective_cut} ج.م (مخصص)</span>`
          : `<span class="badge badge-secondary" style="font-size: 11px;">${r.effective_cut} ج.م (افتراضي)</span>`;

        const avatar = r.avatar
          ? `<img src="${r.avatar}" style="width:26px;height:26px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-left:6px;">`
          : `<span style="display:inline-block;width:26px;height:26px;border-radius:50%;background:var(--bg-card);text-align:center;line-height:26px;margin-left:6px;font-size:11px;">👤</span>`;

        const nameSafe = escapeHtml(r.full_name || r.username);
        const pendingAmount = Number(r.pending_due ?? r.pending_newspaper_cut ?? 0);
        const hasPending = pendingAmount > 0;
        const settleBtn = hasPending
          ? `<button onclick="settleReporterTransactions(${r.user_id}, '${nameSafe.replace(/'/g, "\\'")}', ${pendingAmount})" class="btn btn-gold" style="font-size: 11px; padding: 3px 8px; font-weight: 700;">💵 تسوية (${pendingAmount} ج.م)</button>`
          : '<span style="color: #10B981; font-size: 11px; font-weight: bold;">خالص ✅</span>';

        const customCutVal = (r.custom_deduction !== null && r.custom_deduction !== undefined) ? r.custom_deduction : '';

        return `
          <tr>
            <td>
              <div style="display: flex; align-items: center;">
                ${avatar}
                <div>
                  <strong>${nameSafe}</strong>
                  <div style="font-size: 11px; color: var(--text-muted); font-family: var(--font-code);">${escapeHtml(r.email || '')}</div>
                </div>
              </div>
            </td>
            <td>${roleBadge}</td>
            <td>${appliedCutBadge}</td>
            <td style="text-align: center; font-family: var(--font-code); font-weight: bold;">${r.total_articles || 0}</td>
            <td style="text-align: center; font-family: var(--font-code); color: #38BDF8;">${(isNaN(Number(r.gross_revenue)) ? 0 : Number(r.gross_revenue)).toFixed(2)} ج.م</td>
            <td style="text-align: center; font-family: var(--font-code); color: #F87171;">${(isNaN(Number(r.newspaper_cut)) ? 0 : Number(r.newspaper_cut)).toFixed(2)} ج.م</td>
            <td style="text-align: center; font-family: var(--font-code); font-weight: 800; color: #10B981;">${(isNaN(Number(r.net_profit ?? r.journalist_net)) ? 0 : Number(r.net_profit ?? r.journalist_net)).toFixed(2)} ج.م</td>
            <td style="text-align: center; font-family: var(--font-code); font-weight: bold; color: ${hasPending ? '#F59E0B' : '#10B981'};">
              ${(isNaN(pendingAmount) ? 0 : pendingAmount).toFixed(2)} ج.م
            </td>
            <td style="text-align: center;">
              <div style="display: flex; justify-content: center; gap: 6px; align-items: center; flex-wrap: wrap;">
                ${settleBtn}
                <button onclick="openSetCustomCutModal(${r.user_id}, '${nameSafe.replace(/'/g, "\\'")}', '${customCutVal}')" class="btn btn-secondary" style="font-size: 11px; padding: 3px 8px;" title="تخصيص نسبة استقطاع فردية">⚙️ النسبة</button>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--color-error); padding: 20px;">فشل جلب كشف الحسابات: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// Global Window Functions for Inline Events
window.deleteAccountingTx = async function (txId) {
  if (!confirm('هل أنت متأكد من رغبتك في حذف هذا السجل المالي؟')) return;
  try {
    const res = await apiCall(`/api/accounting/transactions/${txId}`, 'DELETE');
    showToast(res.message || 'تم حذف السجل المالي بنجاح 🗑️', 'info');
    await loadAccountingDashboard();
  } catch (err) {
    showToast(`فشل حذف المعاملة: ${err.message}`, 'error');
  }
};

window.settleReporterTransactions = async function (userId, reporterName, pendingAmount) {
  if (!confirm(`هل استلمت مبلغ التوريد (${pendingAmount} ج.م) بالكامل من الصحفي: ${reporterName} وتريد تسوية حسابه الآن؟`)) return;
  try {
    const res = await apiCall('/api/admin/accounting/settle', 'POST', { user_id: userId });
    showToast(res.message || `تمت تسوية حساب ${reporterName} بنجاح 💵`, 'success');
    await loadAccountingDashboard();
  } catch (err) {
    showToast(`فشل تسوية الحساب: ${err.message}`, 'error');
  }
};

window.openSetCustomCutModal = function (userId, reporterName, currentCut) {
  const modal = document.getElementById('modal-set-custom-cut');
  if (!modal) return;
  document.getElementById('custom-cut-user-id').value = userId;
  document.getElementById('custom-cut-user-name').textContent = reporterName;
  document.getElementById('custom-cut-input').value = currentCut !== '' ? currentCut : '';
  modal.style.display = 'flex';
  document.getElementById('custom-cut-input').focus();
};

function initAccountingView() {
  // 1. Time Range Filter Buttons
  document.querySelectorAll('.acc-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const range = btn.dataset.range;
      document.querySelectorAll('.acc-filter-btn').forEach(b => {
        b.classList.toggle('active', b === btn);
        b.classList.toggle('btn-gold', b === btn);
        b.classList.toggle('btn-secondary', b !== btn);
      });

      const customContainer = document.getElementById('acc-custom-date-container');
      if (range === 'custom') {
        if (customContainer) customContainer.style.display = 'flex';
      } else {
        if (customContainer) customContainer.style.display = 'none';
        State.accountingTimeRange = range;
        loadAccountingStats();
        loadAccountingTransactions();
        if (State.user?.role === 'admin') loadAdminVault();
      }
    });
  });

  // 2. Custom Date Range Apply Button
  document.getElementById('btn-apply-custom-range')?.addEventListener('click', () => {
    const start = document.getElementById('acc-custom-start')?.value;
    const end = document.getElementById('acc-custom-end')?.value;
    if (!start && !end) {
      showToast('يرجى تحديد تاريخ البداية أو النهاية', 'warning');
      return;
    }
    State.accountingTimeRange = 'custom';
    State.accountingCustomStart = start;
    State.accountingCustomEnd = end;
    loadAccountingStats();
    loadAccountingTransactions();
    if (State.user?.role === 'admin') loadAdminVault();
  });

  // 3. Refresh Transactions Button
  document.getElementById('btn-refresh-transactions')?.addEventListener('click', () => {
    loadAccountingDashboard();
    showToast('تم تحديث السجلات المالية 🔄', 'info');
  });

  // 4. Modal Open/Close Controls
  const txModal = document.getElementById('modal-add-accounting-transaction');
  document.getElementById('btn-open-add-transaction')?.addEventListener('click', () => {
    if (txModal) {
      txModal.style.display = 'flex';
      const searchInput = document.getElementById('tx-unbilled-search');
      if (searchInput) searchInput.value = '';
      loadUnbilledPicker();
      updateTxLivePreview();
      document.getElementById('tx-article-title')?.focus();
    }
  });

  // Search input live filtering for unbilled articles picker
  const unbilledSearchInput = document.getElementById('tx-unbilled-search');
  const btnClearUnbilledSearch = document.getElementById('btn-clear-unbilled-search');

  unbilledSearchInput?.addEventListener('input', (e) => {
    const query = e.target.value.trim();
    renderUnbilledPickerOptions(State.unbilledArticles || [], query);
  });

  btnClearUnbilledSearch?.addEventListener('click', () => {
    if (unbilledSearchInput) {
      unbilledSearchInput.value = '';
      renderUnbilledPickerOptions(State.unbilledArticles || [], '');
      unbilledSearchInput.focus();
    }
  });

  const closeTxModal = () => {
    if (txModal) txModal.style.display = 'none';
  };
  document.getElementById('btn-close-add-tx-modal')?.addEventListener('click', closeTxModal);
  document.getElementById('btn-cancel-add-tx')?.addEventListener('click', closeTxModal);

  // 5. Unbilled Picker Auto-Fill
  document.getElementById('tx-unbilled-picker')?.addEventListener('change', (e) => {
    const selectedId = e.target.value;
    if (!selectedId) return;

    const article = State.unbilledArticles.find(a => String(a.id) === String(selectedId));
    if (article) {
      document.getElementById('tx-article-title').value = article.title || '';
      document.getElementById('tx-article-url').value = article.post_url || '';
      document.getElementById('tx-client-name').value = article.client_name || '';
      document.getElementById('tx-client-phone').value = article.client_phone || '';
      document.getElementById('form-add-transaction').dataset.articleId = article.id;
      showToast('تم ملء بيانات الخبر والعميل تلقائياً ⚡', 'success');
      updateTxLivePreview();
    }
  });

  // 6. Live Preview Amount Paid Listener
  document.getElementById('tx-amount-paid')?.addEventListener('input', updateTxLivePreview);

  // 7. Transaction Form Submit
  document.getElementById('form-add-transaction')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const title = document.getElementById('tx-article-title')?.value.trim();
    const url = document.getElementById('tx-article-url')?.value.trim();
    const clientName = document.getElementById('tx-client-name')?.value.trim();
    const clientPhone = document.getElementById('tx-client-phone')?.value.trim();
    const amountPaid = parseFloat(document.getElementById('tx-amount-paid')?.value) || 0;
    const paymentMethod = document.getElementById('tx-payment-method')?.value || 'vodafone_cash';
    const notes = document.getElementById('tx-notes')?.value.trim();
    const articleId = form.dataset.articleId ? parseInt(form.dataset.articleId) : null;

    if (!title) {
      showToast('يرجى إدخال عنوان الخبر', 'warning');
      return;
    }
    if (!clientPhone) {
      showToast('يرجى إدخال رقم هاتف العميل', 'warning');
      return;
    }
    if (amountPaid <= 0) {
      showToast('يرجى إدخال مبلغ صحيح', 'warning');
      return;
    }

    const submitBtn = document.getElementById('btn-submit-transaction');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span>⏳ جاري التسجيل...</span>';
    }

    try {
      const res = await apiCall('/api/accounting/transactions', 'POST', {
        article_id: articleId,
        article_title: title,
        article_url: url,
        client_name: clientName,
        client_phone: clientPhone,
        amount_paid: amountPaid,
        payment_method: paymentMethod,
        notes: notes
      });

      showToast(res.message || 'تم تسجيل وتحصيل العملية بنجاح 💰', 'success');
      form.reset();
      delete form.dataset.articleId;
      closeTxModal();
      await loadAccountingDashboard();
    } catch (err) {
      showToast(`فشل تسجيل التحصيل: ${err.message}`, 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'اعتماد وتسجيل التحصيل 💰';
      }
    }
  });

  // 8. Admin Save Financial Settings
  document.getElementById('btn-save-financial-settings')?.addEventListener('click', async () => {
    const price = parseFloat(document.getElementById('setting-official-price')?.value) || 150;
    const certCut = parseFloat(document.getElementById('setting-cut-certified')?.value) || 0;
    const premCut = parseFloat(document.getElementById('setting-cut-premium')?.value) || 0;

    const btn = document.getElementById('btn-save-financial-settings');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span>⏳ جاري الحفظ...</span>';
    }

    try {
      const res = await apiCall('/api/admin/accounting/settings', 'POST', {
        official_article_price: price,
        cut_certified_journalist: certCut,
        cut_premium_editor: premCut
      });

      showToast(res.message || 'تم تحديث سياسة الأسعار والنسب الرسمية بنجاح 💾', 'success');
      await loadAccountingDashboard();
    } catch (err) {
      showToast(`فشل حفظ الإعدادات: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '💾 حفظ تعديلات الأسعار';
      }
    }
  });

  // 9. Admin Custom Cut Modal Form
  const customCutModal = document.getElementById('modal-set-custom-cut');
  const closeCustomCut = () => {
    if (customCutModal) customCutModal.style.display = 'none';
  };
  document.getElementById('btn-close-custom-cut-modal')?.addEventListener('click', closeCustomCut);
  document.getElementById('btn-cancel-custom-cut')?.addEventListener('click', closeCustomCut);

  document.getElementById('form-set-custom-cut')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const userId = parseInt(document.getElementById('custom-cut-user-id')?.value);
    const cutValRaw = document.getElementById('custom-cut-input')?.value.trim();
    const customCut = cutValRaw !== '' ? parseFloat(cutValRaw) : null;

    if (!userId) return;

    try {
      const res = await apiCall('/api/admin/accounting/user-cut', 'POST', {
        user_id: userId,
        custom_cut: customCut
      });

      showToast(res.message || 'تم تحديث النسبة الفردية للصحفي بنجاح ⚙️', 'success');
      closeCustomCut();
      await loadAccountingDashboard();
    } catch (err) {
      showToast(`فشل تخصيص النسبة: ${err.message}`, 'error');
    }
  });
}

// =============================================================================
// DOM CONTENT LOADED ENTRY POINT
// =============================================================================
document.addEventListener('DOMContentLoaded', async () => {
  // Theme Switching
  document.querySelectorAll('.theme-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const t = btn.dataset.themeSet;
      document.body.setAttribute('data-theme', t);
      document.querySelectorAll('.theme-btn').forEach(b => b.classList.toggle('active', b === btn));
      localStorage.setItem('td_theme', t);
    });
  });

  const savedTheme = localStorage.getItem('td_theme') || 'dark';
  document.body.setAttribute('data-theme', savedTheme);
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.toggle('active', b.dataset.themeSet === savedTheme));

  // Navigation Setup
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      switchView(item.dataset.view);
    });
  });

  // Login Form Submission
  const loginForm = document.getElementById('login-form');
  const loginError = document.getElementById('login-error-box');

  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('login-username').value.trim();
    const p = document.getElementById('login-password').value;

    loginError.style.display = 'none';

    try {
      const res = await apiCall('/api/auth/login', 'POST', { username: u, password: p });
      if (res.success && res.token) {
        State.token = res.token;
        State.user = res.user;
        localStorage.setItem('td_auth_token', res.token);
        updateUserProfileUI();
        hideLoginModal();
        showToast(`مرحباً بك مجدداً، ${res.user.full_name} ✨`, 'success');
      }
    } catch (err) {
      loginError.textContent = err.message;
      loginError.style.display = 'block';
    }
  });

  // Logout Button
  document.getElementById('btn-logout').addEventListener('click', async () => {
    try {
      await apiCall('/api/auth/logout', 'POST');
    } catch (e) { }
    State.token = '';
    State.user = null;
    localStorage.removeItem('td_auth_token');
    showLoginModal();
    showToast('تم تسجيل الخروج بنجاح', 'info');
  });

  // Init Controllers
  initCreateView();
  initVerificationView();
  initAccountingView();
  initReportersView();
  // ===========================================================================
  // UNIFIED PERMANENT CODE AUTHENTICATION
  // ===========================================================================
  let verifiedActivationCode = '';
  const btnVerifyAct = document.getElementById('btn-verify-activation');
  const inputActCode = document.getElementById('activation-code-input');
  const previewBox = document.getElementById('activation-preview-box');

  // Emergency Admin Toggle
  const btnToggleAdmin = document.getElementById('btn-toggle-admin-login');
  const loginFormAdmin = document.getElementById('login-form');
  if (btnToggleAdmin && loginFormAdmin) {
    btnToggleAdmin.addEventListener('click', () => {
      const isHidden = loginFormAdmin.style.display === 'none';
      loginFormAdmin.style.display = isHidden ? 'block' : 'none';
      btnToggleAdmin.textContent = isHidden ? '✕ إخفاء دخول الطوارئ' : '⚙️ خيار الإدارة: دخول بكلمة المرور (للطوارئ فقط)';
    });
  }

  async function handleCodeSubmission() {
    const code = inputActCode.value.trim().toUpperCase();
    if (!code) {
      showToast('يرجى إدخال كود الصحفي المعتمد', 'warning');
      inputActCode.focus();
      return;
    }

    if (loginError) loginError.style.display = 'none';
    btnVerifyAct.disabled = true;
    btnVerifyAct.innerHTML = '<span>⏳ جاري التحقق والدخول...</span>';

    try {
      const res = await apiCall('/api/auth/activation/verify', 'POST', { code });

      if (res.action === 'login' && res.token) {
        // PERMANENT CODE RE-LOGIN: Instant Login!
        State.token = res.token;
        State.user = res.user;
        localStorage.setItem('td_auth_token', res.token);
        localStorage.setItem('td_user', JSON.stringify(res.user));
        document.cookie = `td_auth_token=${res.token}; path=/; max-age=31536000; SameSite=Lax`;

        updateUserProfileUI();
        hideLoginModal();
        showToast(res.message || `مرحباً بك مجدداً يا ${res.user.full_name} ✨`, 'success');

        // Refresh background workers
        syncPublishCooldown();
        syncBloggerQuota();
      } else if (res.action === 'first_time') {
        // FIRST TIME REGISTRATION: Show Google Linking Card!
        verifiedActivationCode = code;
        const j = res.journalist;
        document.getElementById('act-preview-name').textContent = j.journalist_name || 'صحفي معتمد';
        document.getElementById('act-preview-phone').textContent = j.journalist_phone || '-';

        const badge = document.getElementById('act-preview-role-badge');
        if (badge) {
          if (j.role === 'admin') {
            badge.textContent = '👑 رئيس التحرير (Admin)';
            badge.className = 'badge badge-gold';
          } else if (j.role === 'editor') {
            badge.textContent = '⭐ صحفي مميز (مدير تحرير)';
            badge.className = 'badge badge-gold';
          } else {
            badge.textContent = '✍️ صحفي معتمد';
            badge.className = 'badge badge-success';
          }
        }

        previewBox.style.display = 'block';
        showToast(`أهلاً بك يا أستاذ ${j.journalist_name} ✨ اضغط أدناه لربط حساب Google وتفعيل المنظومة.`, 'info');
      }
    } catch (err) {
      previewBox.style.display = 'none';
      if (loginError) {
        loginError.textContent = err.message || 'كود الصحفي غير صحيح أو غير مسجل في الجريدة';
        loginError.style.display = 'block';
      }
      showToast(err.message, 'error');
    } finally {
      btnVerifyAct.disabled = false;
      btnVerifyAct.innerHTML = 'دخول 🚀';
    }
  }

  if (btnVerifyAct && inputActCode) {
    btnVerifyAct.addEventListener('click', handleCodeSubmission);
    inputActCode.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleCodeSubmission();
      }
    });
  }

  // Trigger Google Login with Activation Code
  const btnActGoogleLogin = document.getElementById('btn-act-google-login');
  if (btnActGoogleLogin) {
    btnActGoogleLogin.addEventListener('click', async () => {
      if (!verifiedActivationCode) {
        showToast('يرجى التحقق من الكود أولاً', 'warning');
        return;
      }
      try {
        btnActGoogleLogin.disabled = true;
        btnActGoogleLogin.innerHTML = '<span>⏳ جاري التوجيه لحساب Google...</span>';
        const res = await apiCall(`/api/auth/google/login?activation_code=${encodeURIComponent(verifiedActivationCode)}`);
        if (res.success && res.auth_url) {
          window.location.href = res.auth_url;
        } else {
          showToast('فشل إنشاء رابط تسجيل الدخول', 'error');
          btnActGoogleLogin.disabled = false;
        }
      } catch (err) {
        showToast(`خطأ: ${err.message}`, 'error');
        btnActGoogleLogin.disabled = false;
      }
    });
  }

  // Admin Generate Activation Code Form
  const formCreateAct = document.getElementById('form-create-activation-code');
  if (formCreateAct) {
    formCreateAct.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('new-act-name').value.trim();
      const phone = document.getElementById('new-act-phone').value.trim();
      const role = document.getElementById('new-act-role').value;
      if (!name || !phone) return;

      try {
        const res = await apiCall('/api/admin/activation-codes', 'POST', { name, phone, role });
        showToast(`تم إصدار كود التفعيل بنجاح: ${res.code} 🔑`, 'success');
        formCreateAct.reset();
        loadActivationCodesTable();
      } catch (err) {
        showToast(`خطأ في توليد الكود: ${err.message}`, 'error');
      }
    });
  }

  // Google OAuth Direct Login Button Handler
  const btnGoogleLogin = document.getElementById('btn-google-login');
  if (btnGoogleLogin) {
    btnGoogleLogin.addEventListener('click', async () => {
      try {
        btnGoogleLogin.disabled = true;
        btnGoogleLogin.innerHTML = '<span>⏳ جاري التوجيه لحساب Google...</span>';
        const res = await apiCall('/api/auth/google/login');
        if (res.success && res.auth_url) {
          window.location.href = res.auth_url;
        } else {
          showToast('فشل إنشاء رابط تسجيل الدخول بجوجل', 'error');
          btnGoogleLogin.disabled = false;
        }
      } catch (err) {
        showToast(`خطأ في الاتصال بجوجل: ${err.message}`, 'error');
        btnGoogleLogin.disabled = false;
      }
    });
  }

  // Toggle My Articles vs All Articles
  const btnToggleMyArticles = document.getElementById('btn-toggle-my-articles');
  if (btnToggleMyArticles) {
    btnToggleMyArticles.addEventListener('click', () => {
      State.filterMyArticlesOnly = !State.filterMyArticlesOnly;
      if (State.filterMyArticlesOnly) {
        btnToggleMyArticles.className = 'btn btn-gold';
        btnToggleMyArticles.textContent = '👤 مقالاتي فقط (مفعل)';
      } else {
        btnToggleMyArticles.className = 'btn btn-secondary';
        btnToggleMyArticles.textContent = '👤 مقالاتي فقط';
      }
      loadArticlesArchive();
    });
  }

  // Archive filters
  document.getElementById('archive-search-input')?.addEventListener('input', loadArticlesArchive);
  document.getElementById('archive-category-select')?.addEventListener('change', loadArticlesArchive);
  document.getElementById('btn-refresh-articles')?.addEventListener('click', loadArticlesArchive);

  // Initialize Telegram Bot Control View
  initBotControlView();

  // Google Account Settings Action Handlers
  const btnLogoutGoogle = document.getElementById('btn-logout-google');
  if (btnLogoutGoogle) {
    btnLogoutGoogle.addEventListener('click', async () => {
      if (!confirm('هل أنت متأكد من تسجيل الخروج وفك ربط حساب Google الحالي من مدونة Blogger؟\n(لن تتأثر جلسة دخولك الحالية للمنظومة، ولكن سيتوقف النشر على بلوجر حتى يتم ربط حساب جديد)')) {
        return;
      }

      btnLogoutGoogle.disabled = true;
      btnLogoutGoogle.innerHTML = '<span>⏳ جاري الخروج...</span>';

      try {
        const res = await apiCall('/api/blogger/disconnect', 'POST');
        showToast(res.message || 'تم تسجيل الخروج من حساب Google بنجاح 🚪', 'info');
        await loadSettingsData();
      } catch (err) {
        showToast(`فشل فك الارتباط: ${err.message}`, 'error');
      } finally {
        btnLogoutGoogle.disabled = false;
        btnLogoutGoogle.innerHTML = '<span>🚪</span><span>تسجيل خروج</span>';
      }
    });
  }

  const btnLoginNewGoogle = document.getElementById('btn-login-new-google');
  if (btnLoginNewGoogle) {
    btnLoginNewGoogle.addEventListener('click', async () => {
      btnLoginNewGoogle.disabled = true;
      btnLoginNewGoogle.innerHTML = '<span>⏳ جاري فتح مصادقة Google...</span>';

      try {
        const res = await apiCall('/api/blogger/auth-url?format=json');
        if (res.success && res.auth_url) {
          window.location.href = res.auth_url;
        } else {
          showToast('تعذر إنشاء رابط تسجيل الدخول بجوجل', 'error');
          btnLoginNewGoogle.disabled = false;
          btnLoginNewGoogle.innerHTML = '<span>🔄</span><span>تسجيل بحساب Google جديد (أو تبديل الحساب)</span>';
        }
      } catch (err) {
        showToast(`خطأ في بدء المصادقة: ${err.message}`, 'error');
        btnLoginNewGoogle.disabled = false;
        btnLoginNewGoogle.innerHTML = '<span>🔄</span><span>تسجيل بحساب Google جديد (أو تبديل الحساب)</span>';
      }
    });
  }

  // AI Personal Key Settings Handlers
  const btnToggleKeyVis = document.getElementById('btn-toggle-ai-key-visibility');
  const inputUserAiKey = document.getElementById('settings-user-zai-key');
  if (btnToggleKeyVis && inputUserAiKey) {
    btnToggleKeyVis.addEventListener('click', () => {
      if (inputUserAiKey.type === 'password') {
        inputUserAiKey.type = 'text';
        btnToggleKeyVis.textContent = '🔒';
      } else {
        inputUserAiKey.type = 'password';
        btnToggleKeyVis.textContent = '👁️';
      }
    });
  }

  const btnSaveAiKey = document.getElementById('btn-save-ai-key');
  if (btnSaveAiKey) {
    btnSaveAiKey.addEventListener('click', async () => {
      const val = (inputUserAiKey?.value || '').trim();
      if (!val) {
        showToast('يرجى كتابة أو لصق مفتاح Z.AI الخاص بك', 'warning');
        inputUserAiKey?.focus();
        return;
      }

      btnSaveAiKey.disabled = true;
      btnSaveAiKey.innerHTML = '<span>⏳ جاري الحفظ والتفعيل...</span>';

      try {
        const res = await apiCall('/api/user/ai-key', 'POST', { api_key: val });
        showToast(res.message || 'تم حفظ وتفعيل مفتاح الذكاء الاصطناعي بنجاح! 🔑✨', 'success');
        State.hasAiKey = true;
        State.maskedAiKey = res.masked_key || '';
        if (inputUserAiKey) {
          inputUserAiKey.value = '';
          inputUserAiKey.style.borderColor = '';
          inputUserAiKey.style.boxShadow = '';
        }
        updateAiKeyUI();
      } catch (err) {
        showToast(`خطأ في تفعيل المفتاح: ${err.message}`, 'error');
      } finally {
        btnSaveAiKey.disabled = false;
        btnSaveAiKey.innerHTML = '<span>💾</span><span>حفظ وتفعيل المفتاح الشخصي</span>';
      }
    });
  }

  const btnClearAiKey = document.getElementById('btn-clear-ai-key');
  if (btnClearAiKey) {
    btnClearAiKey.addEventListener('click', async () => {
      if (!confirm('هل أنت متأكد من رغبتك في حذف مفتاح Z.AI API الخاص بك؟\n(لن تتمكن من صياغة أو نشر أي أخبار حتى تقوم بإدخال مفتاح جديد)')) {
        return;
      }

      btnClearAiKey.disabled = true;
      try {
        const res = await apiCall('/api/user/ai-key', 'DELETE');
        showToast(res.message || 'تم حذف مفتاح الذكاء الاصطناعي بنجاح', 'info');
        State.hasAiKey = false;
        State.maskedAiKey = '';
        if (inputUserAiKey) inputUserAiKey.value = '';
        updateAiKeyUI();
      } catch (err) {
        showToast(`فشل حذف المفتاح: ${err.message}`, 'error');
      } finally {
        btnClearAiKey.disabled = false;
      }
    });
  }

  // Publish Celebration Modal Action Buttons
  document.getElementById('btn-pub-open-both')?.addEventListener('click', () => {
    if (!currentPublishResult) return;
    const postUrl = currentPublishResult.post_url;
    const waUrl = currentPublishResult.whatsapp_url;
    const blockedAlert = document.getElementById('pub-popup-blocked-alert');
    const retryBtn = document.getElementById('btn-pub-popup-retry-wa');

    if (!postUrl && !waUrl) {
      showToast('لا توجد روابط متاحة للفتح', 'warning');
      return;
    }

    if (!waUrl) {
      showToast('⚠️ لا يوجد رقم هاتف للعميل في هذا الخبر لفتح محادثة واتساب', 'warning');
      if (postUrl) window.open(postUrl, '_blank', 'noopener,noreferrer');
      return;
    }

    // Open both synchronously within the active user click gesture
    let postWin = null;
    let waWin = null;

    if (postUrl) {
      try {
        postWin = window.open(postUrl, '_blank', 'noopener,noreferrer');
      } catch (e) {
        console.error('Post window open error:', e);
      }
    }

    if (waUrl) {
      try {
        waWin = window.open(waUrl, '_blank', 'noopener,noreferrer');
      } catch (e) {
        console.error('WhatsApp window open error:', e);
      }
    }

    // Check if the WhatsApp window was blocked by the browser popup blocker
    const wasBlocked = !waWin || waWin.closed || typeof waWin.closed === 'undefined';

    if (wasBlocked) {
      if (blockedAlert) {
        blockedAlert.style.display = 'block';
        if (retryBtn) retryBtn.href = waUrl;
      }
      showToast('⚠️ حجب المتصفح نافذة واتساب — اضغط على الزر الأخضر لفتحها يدوياً', 'warning');
    } else {
      if (blockedAlert) blockedAlert.style.display = 'none';
      showToast('تم فتح رابط الخبر ورابط واتساب معاً بنجاح 🌟', 'success');
    }
  });

  document.getElementById('btn-pub-open-post')?.addEventListener('click', () => {
    if (currentPublishResult?.post_url) {
      window.open(currentPublishResult.post_url, '_blank');
    } else {
      showToast('رابط الخبر غير متوفر', 'warning');
    }
  });

  document.getElementById('btn-pub-open-wa')?.addEventListener('click', () => {
    if (currentPublishResult?.whatsapp_url) {
      window.open(currentPublishResult.whatsapp_url, '_blank');
    } else {
      showToast('لا يوجد رقم هاتف مسجل لفتح واتساب', 'warning');
    }
  });

  document.getElementById('btn-pub-copy-post')?.addEventListener('click', async () => {
    if (currentPublishResult?.post_url) {
      try {
        await navigator.clipboard.writeText(currentPublishResult.post_url);
        showToast('تم نسخ رابط الخبر بنجاح 📋', 'success');
      } catch (e) {
        showToast('فشل النسخ تلقائياً', 'warning');
      }
    } else {
      showToast('لا يوجد رابط خبر لنسخه', 'warning');
    }
  });

  document.getElementById('btn-pub-copy-wa')?.addEventListener('click', async () => {
    if (currentPublishResult?.whatsapp_text) {
      try {
        await navigator.clipboard.writeText(currentPublishResult.whatsapp_text);
        showToast('تم نسخ رسالة واتساب بنجاح 💬', 'success');
      } catch (e) {
        showToast('فشل النسخ تلقائياً', 'warning');
      }
    } else {
      showToast('لا توجد رسالة واتساب لنسخها', 'warning');
    }
  });

  document.getElementById('btn-pub-modal-close')?.addEventListener('click', () => {
    hidePublishModal();
  });

  // Dynamic footer port
  const portEl = document.getElementById('footer-server-port');
  if (portEl && window.location.port) {
    portEl.textContent = window.location.port;
  }

  // Sync drawer port
  const drawerPort = document.getElementById('drawer-server-port');
  if (drawerPort && window.location.port) {
    drawerPort.textContent = window.location.port;
  }

  // Check initial Auth
  await checkAuth();

  // Auto-switch view if requested via URL query (e.g. ?view=settings)
  const urlParamView = new URLSearchParams(window.location.search).get('view');
  if (urlParamView) {
    switchView(urlParamView);
  }

  // Background workers
  syncPublishCooldown();
  syncBloggerQuota();
  startCooldownTicker();
  initWebSocketLogs();

  // Poll sync every 15s
  setInterval(() => {
    syncPublishCooldown();
    syncBloggerQuota();
  }, 15000);

  // =========================================================================
  // MOBILE UX SYSTEM — Bottom Nav, Drawer, FAB
  // =========================================================================
  initMobileUX();
});

// =============================================================================
// MOBILE UX CONTROLLER
// =============================================================================
function initMobileUX() {

  // ─── Drawer State ──────────────────────────────────────────────────────────
  const drawer = document.getElementById('mobile-drawer');
  const overlay = document.getElementById('mobile-drawer-overlay');
  const btnOpenMenu = document.getElementById('btn-mobile-menu');
  const btnCloseDrawer = document.getElementById('btn-mobile-drawer-close');
  const drawerLogoutBtn = document.getElementById('btn-mobile-drawer-logout');

  function openDrawer() {
    if (!drawer || !overlay) return;
    overlay.style.display = 'block';
    // Allow repaint before animation
    requestAnimationFrame(() => {
      overlay.classList.add('open');
      drawer.classList.add('open');
    });
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    if (!drawer || !overlay) return;
    overlay.classList.remove('open');
    drawer.classList.remove('open');
    document.body.style.overflow = '';
    // Hide overlay after animation
    setTimeout(() => {
      if (!overlay.classList.contains('open')) {
        overlay.style.display = 'none';
      }
    }, 350);
  }

  // Expose helpers globally
  window.openMobileDrawer = openDrawer;
  window.closeMobileDrawer = closeDrawer;

  if (btnOpenMenu) {
    btnOpenMenu.addEventListener('click', (e) => {
      e.preventDefault();
      openDrawer();
    });
  }

  if (btnCloseDrawer) {
    btnCloseDrawer.addEventListener('click', (e) => {
      e.preventDefault();
      closeDrawer();
    });
  }

  if (overlay) {
    overlay.addEventListener('click', closeDrawer);
  }

  // Close drawer on ESC key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && drawer?.classList.contains('open')) {
      closeDrawer();
    }
  });

  // Drawer logout button
  if (drawerLogoutBtn) {
    drawerLogoutBtn.addEventListener('click', () => {
      closeDrawer();
      // Trigger the main logout
      const mainLogoutBtn = document.getElementById('btn-logout');
      if (mainLogoutBtn) mainLogoutBtn.click();
    });
  }

  // ─── Drawer Navigation Items ───────────────────────────────────────────────
  const drawerNavItems = document.querySelectorAll('[data-drawer-view]');
  drawerNavItems.forEach(item => {
    item.addEventListener('click', () => {
      const viewName = item.dataset.drawerView;
      closeDrawer();
      setTimeout(() => {
        switchView(viewName);
        syncMobileNav(viewName);
      }, 200);
    });
  });

  // ─── Bottom Navigation Bar ─────────────────────────────────────────────────
  const mobileNavItems = document.querySelectorAll('[data-mobile-view]');
  mobileNavItems.forEach(btn => {
    btn.addEventListener('click', () => {
      const viewName = btn.dataset.mobileView;
      if (viewName === '__more') {
        // Open drawer for "المزيد"
        openDrawer();
        return;
      }
      switchView(viewName);
      syncMobileNav(viewName);
    });
  });

  function syncMobileNav(viewName) {
    // Update Bottom Nav active state
    mobileNavItems.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mobileView === viewName);
    });
    // Update Drawer active state
    drawerNavItems.forEach(item => {
      item.classList.toggle('active', item.dataset.drawerView === viewName);
    });
  }

  // Override switchView to also sync mobile nav
  const _originalSwitchView = window._originalSwitchView || switchView;
  if (!window._mobileNavPatched) {
    window._mobileNavPatched = true;
    const origSV = switchView;

    // Monkey-patch: after any switchView call, sync mobile nav
    const observer = new MutationObserver(() => {
      const activeSection = document.querySelector('.view-section.active');
      if (activeSection) {
        const activeViewId = activeSection.id.replace('view-', '');
        syncMobileNav(activeViewId);
      }
    });

    const contentArea = document.querySelector('.content-area');
    if (contentArea) {
      observer.observe(contentArea, { subtree: true, attributes: true, attributeFilter: ['class'] });
    }
  }

  // ─── Sync drawer user info when user logs in ───────────────────────────────
  const origUpdateProfile = window.updateUserProfileUI;
  function syncDrawerUserInfo() {
    if (!State.user) return;
    const drawerUsername = document.getElementById('drawer-username');
    const drawerRole = document.getElementById('drawer-role');
    if (drawerUsername) {
      drawerUsername.textContent = State.user.full_name || State.user.username || 'الصحفي';
    }
    if (drawerRole) {
      let roleText = '✍️ صحفي معتمد';
      if (State.user.role === 'admin') roleText = '👑 رئيس التحرير';
      else if (State.user.role === 'editor') roleText = '⭐ صحفي مميز';
      drawerRole.textContent = roleText;
    }
    // Show admin sections in drawer
    if (State.user.role === 'admin') {
      document.querySelectorAll('.mobile-drawer-nav-item.admin-only, .mobile-drawer-section-label.admin-only').forEach(el => {
        el.style.display = '';
      });
    }
  }

  // Poll for user state (simple approach since updateUserProfileUI is called async)
  let drawerSyncInterval = setInterval(() => {
    if (State.user) {
      syncDrawerUserInfo();
      clearInterval(drawerSyncInterval);
    }
  }, 500);

  // ─── FAB Button ────────────────────────────────────────────────────────────
  const fabBtn = document.getElementById('mobile-fab');
  if (fabBtn) {
    fabBtn.addEventListener('click', () => {
      // Navigate to create view and scroll to textarea
      switchView('create');
      syncMobileNav('create');
      setTimeout(() => {
        const textarea = document.getElementById('input-raw-notes');
        if (textarea) {
          textarea.focus();
          textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }, 200);
    });
  }

  // ─── Auto-inject data-labels to all table TDs for mobile card layout ──────
  function injectTableDataLabels() {
    const tableConfigs = [
      {
        tbody: 'articles-table-body',
        labels: ['#', 'العنوان', 'الصحفي', 'العميل', 'الهاتف', 'القسم', 'الحالة', 'التاريخ', 'الإجراءات']
      },
      {
        tbody: 'accounting-table-body',
        labels: ['الخبر', 'العميل', 'الهاتف', 'المدفوع', 'نسبة الجريدة', 'صافي ربحك', 'طريقة الدفع', 'التاريخ', 'التوريد', 'الإجراءات']
      },
      {
        tbody: 'bot-reporters-table-body',
        labels: ['الصحفي', 'معرف تليجرام', 'الصفة', 'مفتاح API', 'اليوم', 'الإجمالي', 'الإجراءات']
      },
      {
        tbody: 'reporters-table-body',
        labels: ['الصحفي', 'معرف تليجرام', 'الصفة', 'مفتاح API', 'اليوم', 'الإجمالي', 'التاريخ', 'الإجراءات']
      },
      {
        tbody: 'vault-reporters-ledger-body',
        labels: ['الصحفي', 'الرتبة', 'عدد الأخبار', 'إجمالي التحصيل', 'حصة الجريدة', 'صافي الصحفي', 'المعلق', 'الإجراءات']
      },
      {
        tbody: 'users-table-body',
        labels: ['الصحفي', 'البريد الإلكتروني', 'تاريخ الانضمام', 'الرتبة الحالية', 'تحديد الرتبة']
      },
      {
        tbody: 'activation-codes-table-body',
        labels: ['الكود', 'الصحفي', 'رقم الهاتف', 'الرتبة', 'الحالة', 'تاريخ الإصدار', 'الإجراءات']
      }
    ];

    // Use a MutationObserver to label rows as they are dynamically added
    tableConfigs.forEach(cfg => {
      const tbody = document.getElementById(cfg.tbody);
      if (!tbody) return;

      function labelRows() {
        tbody.querySelectorAll('tr').forEach(row => {
          const cells = row.querySelectorAll('td');
          cells.forEach((td, i) => {
            if (cfg.labels[i] && !td.getAttribute('data-label')) {
              td.setAttribute('data-label', cfg.labels[i]);
            }
          });
        });
      }

      // Label existing rows
      labelRows();

      // Observe for future rows added by JS
      const observer = new MutationObserver(labelRows);
      observer.observe(tbody, { childList: true, subtree: true });
    });
  }

  // Run data-label injection
  injectTableDataLabels();

  // ─── Toast position on mobile ─────────────────────────────────────────────
  // Handled by CSS: bottom: 76px on mobile
}

