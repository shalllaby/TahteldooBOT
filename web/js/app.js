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

  let displayMsg = message || '';
  if (typeof displayMsg === 'string') {
    if (
      displayMsg.includes('1113') ||
      displayMsg.includes('余额不足') ||
      displayMsg.includes('无可用资源包') ||
      displayMsg.includes('请充值') ||
      displayMsg.includes('1302') ||
      displayMsg.includes('速率限制')
    ) {
      displayMsg = 'حاول مرة أخرى.. يوجد ضغط حالياً ⏳';
      type = 'warning';
    }
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  let icon = 'ℹ️';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '❌';
  if (type === 'warning') icon = '⏳';

  toast.innerHTML = `<span>${icon}</span><span>${displayMsg}</span>`;
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
  if (logTxt) logTxt.textContent = `[نجاح]: تم البث على ووردبريس برابط: ${res.post_url || 'مباشر'}`;

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
      checkFirstTimeIdentitySetup();
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
    // Run initial AI health check in background
    checkAIHealth(false).catch(() => {});
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

async function checkAIHealth(isManual = false) {
  if (!State.token) return;

  const badge = document.getElementById('ai-health-status-badge');
  const latencyEl = document.getElementById('ai-health-latency');
  const modelEl = document.getElementById('ai-health-model');
  const lastCheckEl = document.getElementById('ai-health-last-check');
  const descEl = document.getElementById('ai-health-status-desc');
  const btnPing = document.getElementById('btn-ai-health-ping');
  const btnIcon = document.getElementById('ai-health-btn-icon');
  const btnText = document.getElementById('ai-health-btn-text');

  // Topbar HUD elements
  const hudPill = document.getElementById('hud-ai-health');
  const hudDot = document.getElementById('hud-ai-dot');
  const hudText = document.getElementById('hud-ai-text');

  if (isManual) {
    if (btnPing) btnPing.disabled = true;
    if (btnIcon) btnIcon.textContent = '⏳';
    if (btnText) btnText.textContent = 'جاري فحص الاتصال والضغط...';
  }

  if (hudText && isManual) {
    hudText.textContent = 'GLM: فحص...';
  }

  try {
    const res = await apiCall('/api/ai/health');
    const now = new Date();
    const timeStr = now.toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    if (modelEl && res.model) {
      modelEl.textContent = res.model;
    }
    if (lastCheckEl) {
      lastCheckEl.textContent = timeStr;
    }

    if (res.status === 'healthy') {
      // 🟢 HEALTHY
      if (badge) {
        badge.textContent = '🟢 مستقر وسريع';
        badge.style.background = 'rgba(16, 185, 129, 0.2)';
        badge.style.color = '#10B981';
        badge.style.borderColor = 'rgba(16, 185, 129, 0.45)';
      }
      if (latencyEl) {
        latencyEl.textContent = `${res.latency_sec} ثانية (${res.speed_rating || 'سريع'})`;
        latencyEl.style.color = '#10B981';
      }
      if (descEl) {
        descEl.textContent = res.message || 'السيرفر مستقر وسريع وجاهز للاستخدام فوراً.';
        descEl.style.borderRightColor = '#10B981';
      }
      if (hudPill) {
        hudPill.className = 'hud-pill success';
      }
      if (hudDot) {
        hudDot.style.background = '#10B981';
        hudDot.style.boxShadow = '0 0 6px #10B981';
      }
      if (hudText) {
        hudText.textContent = `GLM: متصل (${res.latency_sec}s) ⚡`;
      }
      if (isManual) {
        showToast(`✅ محرك GLM مستقر وسريع! سرعة الرد: ${res.latency_sec} ثانية`, 'success');
      }

    } else if (res.status === 'rate_limited') {
      // 🟡 RATE LIMITED (CODE 1302)
      if (badge) {
        badge.textContent = '🟡 ضغط مؤقت في الدقيقة';
        badge.style.background = 'rgba(245, 158, 11, 0.2)';
        badge.style.color = '#F59E0B';
        badge.style.borderColor = 'rgba(245, 158, 11, 0.45)';
      }
      if (latencyEl) {
        latencyEl.textContent = `${res.latency_sec} ثانية (محدودية RPM)`;
        latencyEl.style.color = '#F59E0B';
      }
      if (descEl) {
        descEl.textContent = res.message || 'يوجد ضغط مؤقت في معدل الطلبات بالدقيقة الحالية. انتظر 15-30 ثانية.';
        descEl.style.borderRightColor = '#F59E0B';
      }
      if (hudPill) {
        hudPill.className = 'hud-pill gold';
      }
      if (hudDot) {
        hudDot.style.background = '#F59E0B';
        hudDot.style.boxShadow = '0 0 6px #F59E0B';
      }
      if (hudText) {
        hudText.textContent = 'GLM: ضغط دقيقة ⏳';
      }
      if (isManual) {
        showToast('⚠️ يوجد ضغط في معدل الطلبات الحالية (Rate Limit). يرجى الانتظار 20 ثانية.', 'warning');
      }

    } else {
      // 🔴 ERROR / OVERLOAD / MISSING KEY
      const isMissing = (res.status === 'missing_key');
      const badgeText = isMissing ? '🔴 مفتاح غير محدد' : '🔴 غير متاح / صيانة';
      if (badge) {
        badge.textContent = badgeText;
        badge.style.background = 'rgba(239, 68, 68, 0.2)';
        badge.style.color = '#EF4444';
        badge.style.borderColor = 'rgba(239, 68, 68, 0.45)';
      }
      if (latencyEl) {
        latencyEl.textContent = res.latency_sec ? `${res.latency_sec} ثانية` : '—';
        latencyEl.style.color = '#EF4444';
      }
      if (descEl) {
        descEl.textContent = res.message || 'تعذر الاتصال بمحرك الذكاء الاصطناعي.';
        descEl.style.borderRightColor = '#EF4444';
      }
      if (hudPill) {
        hudPill.className = 'hud-pill';
        hudPill.style.borderColor = 'rgba(239,68,68,0.4)';
        hudPill.style.color = '#EF4444';
      }
      if (hudDot) {
        hudDot.style.background = '#EF4444';
        hudDot.style.boxShadow = '0 0 6px #EF4444';
      }
      if (hudText) {
        hudText.textContent = isMissing ? 'GLM: مفتاح مفقود' : 'GLM: صيانة سحابية';
      }
      if (isManual) {
        showToast(res.message || 'تعذر فحص المحرك.', 'error');
      }
    }

  } catch (err) {
    console.warn('AI health check failed:', err);
    if (hudText) hudText.textContent = 'GLM: خطأ اتصال';
    if (isManual) showToast(`فشل فحص المحرك: ${err.message}`, 'error');
  } finally {
    if (btnPing) btnPing.disabled = false;
    if (btnIcon) btnIcon.textContent = '⚡';
    if (btnText) btnText.textContent = 'فحص الاتصال والضغط اللحظي الآن (Ping Test)';
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
    const isFemale = (State.user.gender || '').toLowerCase() === 'female';
    let roleText = isFemale ? '✍️ صحفية معتمدة' : '✍️ صحفي معتمد';
    let roleColor = '#60A5FA';
    if (State.user.role === 'admin') {
      roleText = '👑 رئيس التحرير (Admin)';
      roleColor = '#F59E0B';
    } else if (State.user.role === 'deputy_editor') {
      roleText = isFemale ? '🎖️ نائبة رئيس التحرير' : '🎖️ نائب رئيس التحرير';
      roleColor = '#F59E0B';
    } else if (State.user.role === 'editor') {
      roleText = isFemale ? '⭐ صحفية مميزة (مديرة تحرير)' : '⭐ صحفي مميز (مدير تحرير)';
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

  // Toggle visibility of admin-only elements (Available to Admin and Deputy Editor)
  const canAdmin = (State.user.role === 'admin' || State.user.role === 'deputy_editor');
  const adminEls = document.querySelectorAll('.admin-only:not(.super-admin-only)');
  adminEls.forEach(el => {
    el.style.display = canAdmin ? '' : 'none';
  });

  // Toggle super-admin-only (Strictly Admin / Chief Editor Only - e.g. Central Vault & Newspaper Profits)
  const superAdminEls = document.querySelectorAll('.super-admin-only');
  superAdminEls.forEach(el => {
    el.style.display = (State.user.role === 'admin') ? '' : 'none';
  });

  if (canAdmin) {
    fetchBotTelemetry();
  }
  syncSettingsIdentityUI();
  checkTransferToolPermission();

  // Review Cleanup Nav Items visibility (Admin & Deputy Editor only)
  const rcNav = document.getElementById('nav-item-review-cleanup');
  const rcDrawer = document.getElementById('drawer-item-review-cleanup');
  if (rcNav) rcNav.style.display = canAdmin ? 'flex' : 'none';
  if (rcDrawer) rcDrawer.style.display = canAdmin ? 'flex' : 'none';

  // Customer Leads CRM Nav Items visibility (Strictly Chief Editor / Admin only)
  const isChiefAdmin = (State.user?.role === 'admin');
  const clNav = document.getElementById('nav-customer-leads');
  if (clNav) clNav.style.display = isChiefAdmin ? 'flex' : 'none';
  document.querySelectorAll('[data-drawer-view="customer-leads"]').forEach(el => {
    el.style.display = isChiefAdmin ? 'flex' : 'none';
  });

  // Facebook Hub Nav Items visibility (Admin & Deputy Editor)
  const fbNav = document.getElementById('nav-facebook-hub');
  if (fbNav) fbNav.style.display = canAdmin ? 'flex' : 'none';
  document.querySelectorAll('[data-drawer-view="facebook-hub"]').forEach(el => {
    el.style.display = canAdmin ? 'flex' : 'none';
  });

  // Gemini Fallback Nav Items visibility (Admin & Deputy Editor only)
  const gfNav = document.getElementById('nav-gemini-fallback');
  if (gfNav) gfNav.style.display = canAdmin ? 'flex' : 'none';
  document.querySelectorAll('[data-drawer-view="gemini-fallback"]').forEach(el => {
    el.style.display = canAdmin ? 'flex' : 'none';
  });
}

// =============================================================================
// JOURNALIST IDENTITY & GENDER ONBOARDING CONTROLLER
// =============================================================================

function checkFirstTimeIdentitySetup() {
  if (!State.user) return;
  const isUnset = !State.user.gender || State.user.gender === '' || 
                  (State.user.full_name && State.user.full_name.includes('مسوق تحت الضوء'));
  const modal = document.getElementById('identity-setup-modal');
  if (isUnset && modal) {
    modal.style.display = 'flex';
    const inp = document.getElementById('identity-fullname-input');
    if (inp) {
      inp.value = (State.user.full_name && !State.user.full_name.includes('مسوق تحت الضوء')) 
                  ? State.user.full_name : '';
      setTimeout(() => inp.focus(), 100);
    }
    selectIdentityGender('identity', 'male');
    updateIdentityPreview('identity');
  }
}

function selectIdentityGender(context, gender) {
  const isModal = context === 'identity';
  const radioName = isModal ? 'identity-gender' : 'settings-identity-gender';
  const maleCard = document.getElementById(isModal ? 'card-gender-male' : 'settings-card-gender-male');
  const femaleCard = document.getElementById(isModal ? 'card-gender-female' : 'settings-card-gender-female');
  
  const radio = document.querySelector(`input[name="${radioName}"][value="${gender}"]`);
  if (radio) radio.checked = true;

  if (maleCard && femaleCard) {
    if (gender === 'female') {
      femaleCard.style.borderColor = 'var(--accent-gold)';
      femaleCard.style.background = 'rgba(245, 158, 11, 0.12)';
      maleCard.style.borderColor = 'var(--border-subtle)';
      maleCard.style.background = 'var(--bg-surface-2)';
    } else {
      maleCard.style.borderColor = 'var(--accent-gold)';
      maleCard.style.background = 'rgba(245, 158, 11, 0.12)';
      femaleCard.style.borderColor = 'var(--border-subtle)';
      femaleCard.style.background = 'var(--bg-surface-2)';
    }
  }
  updateIdentityPreview(context);
}

function updateIdentityPreview(context) {
  const isModal = context === 'identity';
  const nameInput = document.getElementById(isModal ? 'identity-fullname-input' : 'settings-identity-name');
  const previewEl = document.getElementById(isModal ? 'identity-whatsapp-preview' : 'settings-identity-preview');
  const radioName = isModal ? 'identity-gender' : 'settings-identity-gender';
  const selectedGender = document.querySelector(`input[name="${radioName}"]:checked`)?.value || 'male';

  const roleText = selectedGender === 'female' ? 'صحفية لدى' : 'صحفي لدى';
  const rawName = nameInput ? nameInput.value.trim() : '';
  const displayName = rawName || (isModal ? '[اسمك الثنائي المعتمد]' : (State.user?.full_name || '[الاسم]'));

  if (previewEl) {
    previewEl.textContent = `أنا ${displayName}، ${roleText} جريدة تحت الضوء الإخبارية`;
  }
}

function initIdentityControllers() {
  // Modal Gender Card Clicks
  const modalMaleCard = document.getElementById('card-gender-male');
  const modalFemaleCard = document.getElementById('card-gender-female');
  if (modalMaleCard) {
    modalMaleCard.addEventListener('click', (e) => {
      e.preventDefault();
      selectIdentityGender('identity', 'male');
    });
  }
  if (modalFemaleCard) {
    modalFemaleCard.addEventListener('click', (e) => {
      e.preventDefault();
      selectIdentityGender('identity', 'female');
    });
  }

  // Modal Name Input live preview
  const modalNameInput = document.getElementById('identity-fullname-input');
  if (modalNameInput) {
    modalNameInput.addEventListener('input', () => updateIdentityPreview('identity'));
  }

  // Modal Form Submission
  const identityForm = document.getElementById('form-identity-setup');
  if (identityForm) {
    identityForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const inputName = document.getElementById('identity-fullname-input')?.value.trim() || '';
      const words = inputName.split(/\s+/).filter(Boolean);
      if (words.length < 2) {
        showToast('يرجى إدخال اسمك ثنائياً على الأقل (مثال: محمد ابراهيم أو هدى أحمد)', 'warning');
        return;
      }

      const gender = document.querySelector('input[name="identity-gender"]:checked')?.value || 'male';
      const btnSave = document.getElementById('btn-save-identity');
      const originalBtnText = btnSave ? btnSave.innerHTML : '';
      if (btnSave) {
        btnSave.disabled = true;
        btnSave.innerHTML = '<span>⏳ جاري الاعتماد والحفظ...</span>';
      }

      try {
        const res = await apiCall('/api/user/identity', 'POST', {
          full_name: inputName,
          gender: gender
        });

        if (res.success && res.user) {
          State.user = res.user;
          localStorage.setItem('td_user', JSON.stringify(res.user));
          updateUserProfileUI();
          syncSettingsIdentityUI();
          const modal = document.getElementById('identity-setup-modal');
          if (modal) modal.style.display = 'none';
          showToast(res.message || 'تم اعتماد هويتك الصحفية بنجاح! 🚀', 'success');
        }
      } catch (err) {
        showToast(err.message || 'فشل حفظ الهوية الصحفية', 'error');
      } finally {
        if (btnSave) {
          btnSave.disabled = false;
          btnSave.innerHTML = originalBtnText;
        }
      }
    });
  }

  // Settings Identity Form Setup
  const settingsMaleCard = document.getElementById('settings-card-gender-male');
  const settingsFemaleCard = document.getElementById('settings-card-gender-female');
  if (settingsMaleCard) {
    settingsMaleCard.addEventListener('click', (e) => {
      e.preventDefault();
      selectIdentityGender('settings', 'male');
    });
  }
  if (settingsFemaleCard) {
    settingsFemaleCard.addEventListener('click', (e) => {
      e.preventDefault();
      selectIdentityGender('settings', 'female');
    });
  }

  const settingsNameInput = document.getElementById('settings-identity-name');
  if (settingsNameInput) {
    settingsNameInput.addEventListener('input', () => updateIdentityPreview('settings'));
  }

  const settingsForm = document.getElementById('form-settings-identity');
  if (settingsForm) {
    settingsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const inputName = document.getElementById('settings-identity-name')?.value.trim() || '';
      const words = inputName.split(/\s+/).filter(Boolean);
      if (words.length < 2) {
        showToast('يرجى إدخال اسمك ثنائياً على الأقل (مثال: محمد ابراهيم أو هدى أحمد)', 'warning');
        return;
      }

      const gender = document.querySelector('input[name="settings-identity-gender"]:checked')?.value || 'male';
      const btnSave = document.getElementById('btn-save-settings-identity');
      const originalBtnText = btnSave ? btnSave.innerHTML : '';
      if (btnSave) {
        btnSave.disabled = true;
        btnSave.innerHTML = '<span>⏳ جاري الحفظ...</span>';
      }

      try {
        const res = await apiCall('/api/user/identity', 'POST', {
          full_name: inputName,
          gender: gender
        });

        if (res.success && res.user) {
          State.user = res.user;
          localStorage.setItem('td_user', JSON.stringify(res.user));
          updateUserProfileUI();
          syncSettingsIdentityUI();
          showToast(res.message || 'تم تحديث الهوية بنجاح! 💾', 'success');
        }
      } catch (err) {
        showToast(err.message || 'فشل تحديث الهوية', 'error');
      } finally {
        if (btnSave) {
          btnSave.disabled = false;
          btnSave.innerHTML = originalBtnText;
        }
      }
    });
  }
}

function syncSettingsIdentityUI() {
  if (!State.user) return;
  const nameInput = document.getElementById('settings-identity-name');
  if (nameInput) {
    nameInput.value = State.user.full_name || '';
  }
  const userGender = (State.user.gender || 'male').toLowerCase();
  selectIdentityGender('settings', userGender === 'female' ? 'female' : 'male');
  updateIdentityPreview('settings');
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
  if ((viewName === 'reporters' || viewName === 'bot-control') && State.user?.role !== 'admin' && State.user?.role !== 'deputy_editor') {
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
  if (viewName === 'whatsapp-tool') initWhatsAppTool();
  if (viewName === 'poster-studio') initPosterStudio();
  if (viewName === 'promote-tool') {
    if (!State.user?.is_allowed_transfer && State.user?.role !== 'admin' && State.user?.role !== 'deputy_editor' && State.user?.role !== 'editor') {
      showToast('عفواً، هذا القسم مخصص لرئيس التحرير والحسابات المصرح لها فقط 🔒', 'warning');
      switchView('create');
      return;
    }
    initPromoteTool();
  }
  if (viewName === 'review-cleanup') {
    if (State.user?.role !== 'admin' && State.user?.role !== 'deputy_editor') {
      showToast('عفواً، هذا القسم مخصص لرئيس التحرير ونائبه فقط 🔒', 'warning');
      switchView('create');
      return;
    }
    initReviewCleanup();
  }
  if (viewName === 'customer-leads') {
    if (State.user?.role !== 'admin') {
      showToast('عفواً، هذا القسم مخصص لرئيس التحرير العام فقط 🔒', 'warning');
      switchView('create');
      return;
    }
    loadCustomerLeads(1);
  }
  if (viewName === 'facebook-hub') {
    if (State.user?.role !== 'admin' && State.user?.role !== 'deputy_editor') {
      showToast('عفواً، قسم إدارة فيسبوك مخصص لرئيس التحرير ونائبه فقط 🔒', 'warning');
      switchView('create');
      return;
    }
    loadFacebookHub();
  }
  if (viewName === 'gemini-fallback') {
    if (State.user?.role !== 'admin' && State.user?.role !== 'deputy_editor') {
      showToast('عفواً، هذا القسم مخصص لرئيس التحرير ونائبه فقط 🔒', 'warning');
      switchView('create');
      return;
    }
    loadGeminiFallbackStats();
    loadGeminiFallbackLogs(1);
  }
  if (viewName === 'smart-editor') {
    initSmartEditor();
  }
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

  const role = State.user?.role || (JSON.parse(localStorage.getItem('td_user') || '{}')).role || '';
  const isPrivileged = ['admin', 'deputy_editor', 'editor'].includes(role);

  if (State.cooldownSeconds > 0) {
    if (isPrivileged) {
      el.className = 'hud-pill success';
      txt.textContent = `تدفق النشر: مستثنى (${State.cooldownSeconds}ث)`;
    } else {
      el.className = 'hud-pill warning';
      txt.textContent = `انتظار: ${State.cooldownSeconds} ثانية`;
    }
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
// WORDPRESS STATUS WORKER
// =============================================================================
async function syncBloggerQuota() {
  try {
    const q = await apiCall('/api/blogger/quota');
    const txt = document.getElementById('quota-text');
    if (txt && q) {
      txt.textContent = `ووردبريس: ${q.remaining?.toLocaleString()} متبقي (${q.status || 'OK'})`;
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

  // Helper to import image from external URL
  async function handleImageFromUrl(imgUrl) {
    if (!imgUrl || !imgUrl.startsWith('http')) return;
    try {
      showToast('جاري استيراد الصورة الملصقة من الرابط...', 'info');
      const res = await apiCall('/api/upload-url', 'POST', { url: imgUrl });
      if (res.success) {
        State.uploadedImagePath = res.local_path;
        thumb.src = res.url;
        thumb.style.display = 'block';
        placeholder.style.display = 'none';
        btnRemoveImg.style.display = 'inline-block';
        showToast('تم استيراد ورفع الصورة بنجاح ✅', 'success');
      }
    } catch (err) {
      console.warn('handleImageFromUrl error:', err);
      showToast(`تعذر استيراد الصورة: ${err.message}`, 'error');
    }
  }

  // Robust Clipboard Paste Image Support
  window.addEventListener('paste', async (e) => {
    if (State.currentView !== 'create') return;

    // 1. Check e.clipboardData.files (e.g. copied from Windows Explorer / Snipping Tool / WhatsApp)
    const files = e.clipboardData?.files;
    if (files && files.length > 0) {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (file.type.startsWith('image/') || /\.(jpe?g|png|webp|gif|bmp|jfif|avif)$/i.test(file.name)) {
          e.preventDefault();
          showToast('جاري رفع ملف الصورة الملصقة من الحافظة...', 'info');
          await handleImageUpload(file);
          return;
        }
      }
    }

    // 2. Check e.clipboardData.items for image blobs
    const items = e.clipboardData?.items;
    if (items && items.length > 0) {
      for (let item of items) {
        if (item.type && item.type.indexOf('image') !== -1) {
          e.preventDefault();
          const blob = item.getAsFile();
          if (blob) {
            const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
            const file = new File([blob], `pasted_image_${Date.now()}.${ext}`, { type: blob.type || 'image/png' });
            showToast('جاري رفع الصورة الملصقة من الحافظة...', 'info');
            await handleImageUpload(file);
            return;
          }
        }
      }
    }

    // 3. Check for HTML snippet with <img> tag (e.g. copied from web page / browser)
    try {
      const html = e.clipboardData?.getData('text/html');
      if (html) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const img = doc.querySelector('img');
        if (img && img.src && (img.src.startsWith('http://') || img.src.startsWith('https://') || img.src.startsWith('data:image/'))) {
          e.preventDefault();
          if (img.src.startsWith('data:image/')) {
            const fetchRes = await fetch(img.src);
            const blob = await fetchRes.blob();
            const ext = blob.type.split('/')[1] || 'png';
            const file = new File([blob], `pasted_image_${Date.now()}.${ext}`, { type: blob.type });
            await handleImageUpload(file);
          } else {
            await handleImageFromUrl(img.src);
          }
          return;
        }
      }
    } catch (_) {}

    // 4. Check for direct image URL in plain text (if focus is not on input/textarea with text intended)
    try {
      const text = e.clipboardData?.getData('text/plain')?.trim();
      if (text && /^https?:\/\/.+\.(jpe?g|png|webp|gif|bmp|jfif|avif)(\?.*)?$/i.test(text)) {
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
        if (activeTag !== 'textarea' && activeTag !== 'input') {
          e.preventDefault();
          await handleImageFromUrl(text);
          return;
        }
      }
    } catch (_) {}
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
    if (!file) return;
    const formData = new FormData();
    const fileName = file.name || `pasted_image_${Date.now()}.png`;
    formData.append('file', file, fileName);
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

    const userRole = State.user?.role || (JSON.parse(localStorage.getItem('td_user') || '{}')).role || '';
    const isPrivilegedUser = ['admin', 'deputy_editor', 'editor'].includes(userRole);

    if (State.cooldownSeconds > 0 && !isPrivilegedUser) {
      showToast(`⚠️ ليمت الجريدة: يرجى الانتظار ${State.cooldownSeconds} ثانية لتنظيم الأرشفة`, 'warning');
      return;
    }

    btnDirectPub.disabled = true;
    btnDirectPub.innerHTML = '⏳ جاري الصياغة والنشر المباشر...';

    // Show Progress Modal (1% to 100%)
    showPublishProgressModal();

    try {
      const res = await apiCall('/api/articles/direct-publish', 'POST', {
        raw_notes: text,
        local_image_path: State.uploadedImagePath,
      });

      syncPublishCooldown();
      syncBloggerQuota();

      // Show Celebration Dialog with Sound and Multi-Action buttons
      showPublishSuccessModal(res, res.title);

      rawInput.value = '';
      btnRemoveImg.click();
    } catch (err) {
      hidePublishModal();
      let msg = err.message || '';
      if (
        msg.includes('1113') ||
        msg.includes('余额不足') ||
        msg.includes('无可用资源包') ||
        msg.includes('请充值') ||
        msg.includes('1302') ||
        msg.includes('速率限制')
      ) {
        msg = 'حاول مرة أخرى.. يوجد ضغط حالياً ⏳';
      }
      showToast(msg, 'warning');
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

    window._archiveArticles = res.articles;

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
        <td style="text-align: center; white-space: nowrap;">
          <div style="display: inline-flex; gap: 6px; justify-content: center; align-items: center;">
            <!-- 1. فتح شات واتساب جاهز بالرسالة -->
            <button type="button" onclick="openArchiveArticleWhatsApp(${a.id})" class="btn-archive-action" title="فتح شات واتساب جاهز بالرسالة مع العميل" style="background: linear-gradient(135deg, #25D366 0%, #128C7E 100%); color: #FFFFFF; font-weight: 700; border: none; padding: 6px 11px; border-radius: 6px; font-size: 12px; display: inline-flex; align-items: center; gap: 5px; cursor: pointer; box-shadow: 0 2px 8px rgba(37, 211, 102, 0.35); transition: all 0.2s ease;">
              <span>💬</span>
              <span>شات واتساب</span>
            </button>

            <!-- 2. نسخ رسالة واتساب -->
            <button type="button" onclick="copyArchiveArticleWhatsApp(${a.id}, this)" class="btn-archive-action" title="نسخ نص رسالة الواتساب الجاهزة بالكامل" style="background: linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%); color: #FFFFFF; font-weight: 700; border: none; padding: 6px 11px; border-radius: 6px; font-size: 12px; display: inline-flex; align-items: center; gap: 5px; cursor: pointer; box-shadow: 0 2px 8px rgba(59, 130, 246, 0.35); transition: all 0.2s ease;">
              <span>📋</span>
              <span class="btn-text">نسخ الرسالة</span>
            </button>

            <!-- 3. فتح الرابط -->
            <button type="button" onclick="openArchiveArticleUrl(${a.id})" class="btn-archive-action" title="فتح وقراءة المقال على موقع الجريدة" style="background: linear-gradient(135deg, #10B981 0%, #059669 100%); color: #FFFFFF; font-weight: 700; border: none; padding: 6px 11px; border-radius: 6px; font-size: 12px; display: inline-flex; align-items: center; gap: 5px; cursor: pointer; box-shadow: 0 2px 8px rgba(16, 185, 129, 0.35); transition: all 0.2s ease;">
              <span>🌐</span>
              <span>فتح الرابط ↗</span>
            </button>
          </div>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--color-error); padding: 20px;">خطأ: ${err.message}</td></tr>`;
  }
}

window.openArchiveArticleWhatsApp = function(articleId) {
  const article = (window._archiveArticles || []).find(x => x.id === articleId);
  if (!article) return;

  if (article.whatsapp_url) {
    window.open(article.whatsapp_url, '_blank', 'noopener,noreferrer');
    return;
  }

  // If no phone or whatsapp_url
  let phone = (article.client_phone || '').trim();
  if (!phone) {
    phone = prompt('لم يتم العثور على رقم هاتف مسجل للعميل في هذا المقال.\nيرجى إدخال رقم هاتف العميل (واتساب):', '');
    if (!phone || !phone.trim()) return;
  }

  phone = phone.replace(/[^0-9]/g, '');
  if (phone.startsWith('01')) phone = '2' + phone;

  const authorName = (article.author_name || (window.currentUser && window.currentUser.full_name) || 'محمد شلبي').trim();
  const cName = (article.client_name || 'الكريم').trim();
  const postUrl = (article.post_url || '').trim();
  const defaultFallback = `السلام عليكم ورحمة الله وبركاته

أهلًا وسهلًا بحضرتك ${cName}، تشرفنا بتواصلنا مع حضرتك.

أنا ${authorName}، صحفي لدي جريدة تحت الضوء الإخبارية

- رابط الجريدة:
https://www.tahteldoo.com/

- صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن حضرتك تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضرتك لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

- رابط الخبر:
${postUrl}

مع خالص تمنياتنا لـ ${cName} بمزيد من النجاح والتوفيق.`;

  const text = article.whatsapp_text || defaultFallback;
  const directUrl = `https://wa.me/${phone}?text=${encodeURIComponent(text)}`;
  window.open(directUrl, '_blank', 'noopener,noreferrer');
};

window.copyArchiveArticleWhatsApp = function(articleId, btnEl) {
  const article = (window._archiveArticles || []).find(x => x.id === articleId);
  if (!article) return;

  const authorName = (article.author_name || (window.currentUser && window.currentUser.full_name) || 'محمد شلبي').trim();
  const cName = (article.client_name || 'الكريم').trim();
  const postUrl = (article.post_url || '').trim();
  const defaultFallback = `السلام عليكم ورحمة الله وبركاته

أهلًا وسهلًا بحضرتك ${cName}، تشرفنا بتواصلنا مع حضرتك.

أنا ${authorName}، صحفي لدي جريدة تحت الضوء الإخبارية

- رابط الجريدة:
https://www.tahteldoo.com/

- صفحة الجريدة على فيسبوك:
https://www.facebook.com/tahteldoo/

تم إعداد خبر صحفي عن حضرتك تمهيدًا لنشره على جريدة تحت الضوء، ويسعدنا إرسال رابط الخبر لحضرتك لمراجعته والتأكد من صحة جميع البيانات والمعلومات الواردة به:

- رابط الخبر:
${postUrl}

مع خالص تمنياتنا لـ ${cName} بمزيد من النجاح والتوفيق.`;

  const text = article.whatsapp_text || defaultFallback;

  navigator.clipboard.writeText(text).then(() => {
    showToast('📋 تم نسخ رسالة الواتساب الجاهزة بنجاح!', 'success');
    if (btnEl) {
      const textSpan = btnEl.querySelector('.btn-text');
      if (textSpan) {
        const oldText = textSpan.textContent;
        textSpan.textContent = 'تم النسخ! ✅';
        btnEl.style.filter = 'brightness(1.25)';
        setTimeout(() => {
          textSpan.textContent = oldText;
          btnEl.style.filter = 'none';
        }, 2200);
      }
    }
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('📋 تم نسخ رسالة الواتساب بنجاح!', 'success');
  });
};

window.openArchiveArticleUrl = function(articleId) {
  const article = (window._archiveArticles || []).find(x => x.id === articleId);
  if (!article) return;

  if (article.post_url) {
    window.open(article.post_url, '_blank', 'noopener,noreferrer');
  } else {
    showToast('⚠️ هذا المقال لم يتم تسجيل رابط منشور له بعد.', 'warning');
  }
};

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
  syncSettingsIdentityUI();
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

  // Load Journalist Roles and Activation Codes if Admin or Deputy
  if (State.user?.role === 'admin' || State.user?.role === 'deputy_editor') {
    // Restrict activation code role select if not admin
    const newActRole = document.getElementById('new-act-role');
    if (newActRole) {
      if (State.user?.role !== 'admin') {
        newActRole.value = 'journalist';
        newActRole.disabled = true;
        newActRole.title = 'منح الرتب مقتصر على رئيس التحرير فقط';
      } else {
        newActRole.disabled = false;
        newActRole.title = '';
      }
    }
    loadUsersManagementTable();
    loadActivationCodesTable();
    loadTransferPermissionsSettings();
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
        } else if (u.role === 'deputy_editor') {
          roleBadge = '<span class="badge badge-gold" style="background: rgba(245, 158, 11, 0.25); color:#FBBF24; border: 1px solid #F59E0B;">🎖️ نائب رئيس التحرير</span>';
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
              ${State.user?.role === 'admin' ? `
                <div style="display: flex; justify-content: center; gap: 8px; align-items: center;">
                  <select id="role-select-${u.id}" class="form-input" style="padding: 4px 8px; font-size: 12px; width: 140px;">
                    <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>👑 رئيس تحرير</option>
                    <option value="deputy_editor" ${u.role === 'deputy_editor' ? 'selected' : ''}>🎖️ نائب رئيس تحرير</option>
                    <option value="editor" ${u.role === 'editor' ? 'selected' : ''}>⭐ صحفي مميز</option>
                    <option value="journalist" ${u.role === 'journalist' ? 'selected' : ''}>✍️ صحفي معتمد</option>
                  </select>
                  <button onclick="changeUserRole(${u.id})" class="btn btn-gold" style="font-size: 11.5px; padding: 4px 10px;">حفظ</button>
                </div>
              ` : `
                <span style="font-size: 11px; color: var(--text-muted);">🔒 خاص برئيس التحرير</span>
              `}
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
  if (State.user?.role !== 'admin') {
    showToast('عفواً، ترقية وتعديل الرتب مقتصر على رئيس التحرير فقط 🔒', 'warning');
    return;
  }
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
        else if (c.role === 'deputy_editor') roleBadge = '<span class="badge badge-gold" style="background: rgba(245, 158, 11, 0.25); color:#FBBF24; border: 1px solid #F59E0B;">🎖️ نائب رئيس تحرير</span>';
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
        } else if (settingsRes.user_role === 'deputy_editor') {
          roleBadgeEl.textContent = '🎖️ نائب رئيس تحرير (إعفاء كامل 0%)';
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

  // 5. If Admin ONLY, load Master Financial Vault (Strictly Chief Editor)
  const vaultEl = document.getElementById('admin-accounting-vault');
  if (State.user?.role === 'admin') {
    if (vaultEl) vaultEl.style.display = 'block';
    await loadAdminVault();
  } else {
    if (vaultEl) vaultEl.style.display = 'none';
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
  if (State.user?.role !== 'admin') return;
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
        checkFirstTimeIdentitySetup();
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
        checkFirstTimeIdentitySetup();

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
        checkAIHealth(true).catch(() => {});
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
        checkAIHealth(false).catch(() => {});
      }
    });
  }

  // AI Engine Live Health & Ping Monitor Handlers
  const btnAiPing = document.getElementById('btn-ai-health-ping');
  if (btnAiPing) {
    btnAiPing.addEventListener('click', () => checkAIHealth(true));
  }

  const hudAiHealth = document.getElementById('hud-ai-health');
  if (hudAiHealth) {
    hudAiHealth.addEventListener('click', () => {
      if (State.currentView !== 'settings') {
        navigateTo('settings');
      }
      checkAIHealth(true);
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
  initIdentityControllers();
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
      else if (State.user.role === 'deputy_editor') roleText = '🎖️ نائب رئيس التحرير';
      else if (State.user.role === 'editor') roleText = '⭐ صحفي مميز';
      drawerRole.textContent = roleText;
    }
    // Show admin sections in drawer
    if (State.user.role === 'admin' || State.user.role === 'deputy_editor') {
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

  // Initialize WhatsApp tool listeners
  initWhatsAppTool();

  // ─── Toast position on mobile ─────────────────────────────────────────────
  // Handled by CSS: bottom: 76px on mobile
}

// =============================================================================
// VIEW: WHATSAPP DIRECT LINK GENERATOR & PHONE NORMALIZER CONTROLLER
// =============================================================================

let waRecentNumbers = [];
let waInputDebounceTimer = null;

function initWhatsAppTool() {
  if (window._waToolInitialized) return;
  window._waToolInitialized = true;

  const rawInput = document.getElementById('wa-input-raw');
  const msgInput = document.getElementById('wa-input-message');
  const clientInput = document.getElementById('wa-input-client-name');
  const pasteBtn = document.getElementById('btn-wa-paste-clipboard');
  const clearBtn = document.getElementById('btn-wa-clear-all');
  const clearMsgBtn = document.getElementById('btn-wa-clear-msg');
  const copyLinkBtn = document.getElementById('wa-btn-copy-link');
  const copyInlineBtn = document.getElementById('wa-btn-copy-inline');
  const clearHistBtn = document.getElementById('btn-wa-clear-history');

  if (rawInput) {
    rawInput.addEventListener('input', () => {
      clearTimeout(waInputDebounceTimer);
      waInputDebounceTimer = setTimeout(() => {
        if (rawInput.value.trim().length >= 8) {
          processWhatsAppPhone(true);
        }
      }, 400);
    });
  }

  if (msgInput) {
    msgInput.addEventListener('input', () => {
      clearTimeout(waInputDebounceTimer);
      waInputDebounceTimer = setTimeout(() => {
        if (rawInput && rawInput.value.trim().length >= 8) {
          processWhatsAppPhone(true);
        }
      }, 400);
    });
  }

  if (pasteBtn) {
    pasteBtn.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text && rawInput) {
          rawInput.value = text;
          showToast('تم اللصق من الحافظة 📋', 'info');
          processWhatsAppPhone();
        }
      } catch (e) {
        showToast('يرجى لصق النص يدوياً داخل الحقل', 'warning');
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      if (rawInput) rawInput.value = '';
      if (msgInput) msgInput.value = '';
      if (clientInput) clientInput.value = '';
      resetWhatsAppResult();
      showToast('تم مسح الحقول', 'info');
    });
  }

  if (clearMsgBtn) {
    clearMsgBtn.addEventListener('click', () => {
      if (msgInput) msgInput.value = '';
      if (rawInput && rawInput.value.trim().length >= 8) {
        processWhatsAppPhone(true);
      }
    });
  }

  if (copyLinkBtn) {
    copyLinkBtn.addEventListener('click', () => {
      copyWhatsAppLink();
    });
  }

  if (copyInlineBtn) {
    copyInlineBtn.addEventListener('click', () => {
      copyWhatsAppLink();
    });
  }

  if (clearHistBtn) {
    clearHistBtn.addEventListener('click', () => {
      waRecentNumbers = [];
      renderRecentWhatsAppList();
      showToast('تم مسح سجل الأرقام 🗑️', 'info');
    });
  }

  // Quick Template Buttons
  document.querySelectorAll('.wa-msg-template-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tmpl = btn.dataset.tmpl;
      const editorName = State.user?.full_name || 'محرر الجريدة';
      const editorRole = (State.user?.gender === 'female') ? 'صحفية لدى' : 'صحفي لدى';
      const clientName = (clientInput && clientInput.value.trim()) ? clientInput.value.trim() : 'أستاذنا الفاضل';

      let text = '';
      if (tmpl === 'intro') {
        text = `السلام عليكم ورحمة الله وبركاته\nمع حضرتك ${editorName}، ${editorRole} جريدة تحت الضوء الإخبارية.\nتشرفنا بتواصلنا مع حضرتك أ/ ${clientName} ✨`;
      } else if (tmpl === 'review') {
        text = `السلام عليكم ورحمة الله وبركاته\nمع حضرتك ${editorName}، ${editorRole} جريدة تحت الضوء الإخبارية.\nأهلًا بحضرتك أ/ ${clientName}، يسعدنا مراجعة تفاصيل ونشر الخبر الصحفي الخاص بحضرتكم في الجريدة.`;
      } else if (tmpl === 'welcome') {
        text = `أهلاً وسهلاً بحضرتك، تشرفنا بتواصلنا معك من جريدة تحت الضوء الإخبارية.`;
      }

      if (msgInput) {
        msgInput.value = text;
        if (rawInput && rawInput.value.trim().length >= 8) {
          processWhatsAppPhone(true);
        }
      }
    });
  });
}

function resetWhatsAppResult() {
  const resCard = document.getElementById('wa-result-card');
  const placeholderCard = document.getElementById('wa-placeholder-card');
  if (resCard) resCard.style.display = 'none';
  if (placeholderCard) placeholderCard.style.display = 'block';
}

async function processWhatsAppPhone(isSilent = false) {
  const rawInput = document.getElementById('wa-input-raw');
  const msgInput = document.getElementById('wa-input-message');
  const clientInput = document.getElementById('wa-input-client-name');

  const rawPhone = rawInput ? rawInput.value.trim() : '';
  if (!rawPhone) {
    if (!isSilent) showToast('يرجى إدخال رقم الهاتف أو نص يحتوي على رقم', 'warning');
    resetWhatsAppResult();
    return;
  }

  const message = msgInput ? msgInput.value.trim() : '';
  const clientName = clientInput ? clientInput.value.trim() : '';

  try {
    const res = await apiCall('/api/tools/whatsapp-link', 'POST', {
      raw_phone: rawPhone,
      message: message,
      client_name: clientName
    });

    if (!res || !res.success) {
      if (!isSilent) showToast(res?.error || 'تعذر معالجة رقم الهاتف المدخل', 'error');
      return;
    }

    // Populate Results
    const resCard = document.getElementById('wa-result-card');
    const placeholderCard = document.getElementById('wa-placeholder-card');
    if (placeholderCard) placeholderCard.style.display = 'none';
    if (resCard) resCard.style.display = 'block';

    const openBtn = document.getElementById('wa-btn-open-chat');
    if (openBtn) openBtn.href = res.wa_link;

    const displayLink = document.getElementById('wa-display-link');
    if (displayLink) displayLink.value = res.wa_link;

    const localPhoneEl = document.getElementById('wa-res-local-phone');
    if (localPhoneEl) localPhoneEl.textContent = res.local_formatted;

    const intlPhoneEl = document.getElementById('wa-res-intl-phone');
    if (intlPhoneEl) intlPhoneEl.textContent = res.intl_formatted;

    const opNameEl = document.getElementById('wa-res-operator-name');
    if (opNameEl) opNameEl.textContent = `${res.operator?.icon || '📱'} ${res.operator?.name || 'شبكة عامة'}`;

    const badgeOp = document.getElementById('wa-badge-operator');
    if (badgeOp && res.operator) {
      badgeOp.textContent = `${res.operator.icon} ${res.operator.name}`;
      badgeOp.style.background = `${res.operator.badge_color}22`;
      badgeOp.style.color = res.operator.badge_color;
      badgeOp.style.borderColor = `${res.operator.badge_color}66`;
    }

    const countryEl = document.getElementById('wa-res-country');
    if (countryEl) countryEl.textContent = `${res.country?.flag || '🌐'} ${res.country?.name || 'دولي'}`;

    const previewBox = document.getElementById('wa-msg-preview-box');
    const previewText = document.getElementById('wa-msg-preview-text');
    if (res.has_message) {
      if (previewBox) previewBox.style.display = 'block';
      if (previewText) previewText.textContent = res.message;
    } else {
      if (previewBox) previewBox.style.display = 'none';
    }

    // Add to recent numbers history (avoid duplicate top entry)
    if (!waRecentNumbers.find(item => item.clean_phone === res.clean_phone && item.wa_link === res.wa_link)) {
      waRecentNumbers.unshift({
        clean_phone: res.clean_phone,
        local_formatted: res.local_formatted,
        operator_name: res.operator?.name || '',
        operator_icon: res.operator?.icon || '📱',
        country_flag: res.country?.flag || '🇪🇬',
        wa_link: res.wa_link,
        client_name: clientName,
        time: new Date().toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' })
      });
      if (waRecentNumbers.length > 15) waRecentNumbers.pop();
      renderRecentWhatsAppList();
    }

    if (!isSilent) {
      showToast('تم تنظيم الرقم وتجهيز رابط الواتساب بنجاح ⚡', 'success');
    }

  } catch (err) {
    if (!isSilent) {
      showToast(err.message || 'حدث خطأ أثناء معالجة الرقم', 'error');
    }
  }
}

function copyWhatsAppLink() {
  const displayLink = document.getElementById('wa-display-link');
  if (!displayLink || !displayLink.value) return;

  navigator.clipboard.writeText(displayLink.value).then(() => {
    showToast('تم نسخ رابط الواتساب المباشر بنجاح 📋', 'success');
  }).catch(() => {
    displayLink.select();
    document.execCommand('copy');
    showToast('تم نسخ الرابط بالحافظة', 'success');
  });
}

function copySpecificLink(link) {
  if (!link) return;
  navigator.clipboard.writeText(link).then(() => {
    showToast('تم نسخ الرابط بنجاح 📋', 'success');
  });
}

function renderRecentWhatsAppList() {
  const container = document.getElementById('wa-recent-list');
  if (!container) return;

  if (!waRecentNumbers.length) {
    container.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); text-align: center; padding: 12px;">لا توجد أرقام منظمة بعد في هذه الجلسة.</div>';
    return;
  }

  container.innerHTML = waRecentNumbers.map(item => `
    <div class="wa-recent-item">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 16px;">${item.country_flag}</span>
        <div>
          <div style="font-size: 13px; font-weight: 700; color: var(--text-primary); font-family: var(--font-code);">${item.local_formatted} ${item.client_name ? `<span style="font-size: 11px; color: var(--accent-gold);">(${item.client_name})</span>` : ''}</div>
          <div style="font-size: 10.5px; color: var(--text-muted);">${item.operator_icon} ${item.operator_name} • ${item.time}</div>
        </div>
      </div>
      <div style="display: flex; gap: 6px;">
        <button type="button" onclick="copySpecificLink('${item.wa_link}')" class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;" title="نسخ الرابط">📋 نسخ</button>
        <a href="${item.wa_link}" target="_blank" class="btn" style="background: #25D366; color: #051B11; padding: 4px 8px; font-size: 11px; text-decoration: none; font-weight: 700; border-radius: 6px;" title="فتح في واتساب">📲 فتح</a>
      </div>
    </div>
  `).join('');
}



// =============================================================================
// ARTICLE TRANSFER CONTROLLER (REVIEW -> MAIN) & PERMISSIONS
// =============================================================================

async function checkTransferToolPermission() {
  try {
    const res = await apiCall('/api/transfer/permissions');
    const isAllowed = !!(res && res.is_allowed);
    if (State.user) {
      State.user.is_allowed_transfer = isAllowed;
    }
    const navItem = document.getElementById('nav-item-promote-tool');
    const drawerItem = document.getElementById('drawer-item-promote-tool');
    if (navItem) {
      navItem.style.display = isAllowed ? 'flex' : 'none';
    }
    if (drawerItem) {
      drawerItem.style.display = isAllowed ? 'flex' : 'none';
    }
  } catch (e) {
    console.warn('Could not check transfer permission:', e);
  }
}

function initPromoteTool() {
  if (window._promoteToolInitialized) return;
  window._promoteToolInitialized = true;

  const urlInput = document.getElementById('promote-input-url');
  const pasteBtn = document.getElementById('btn-promote-paste');
  const clearBtn = document.getElementById('btn-promote-clear');
  const copyBtn = document.getElementById('btn-promote-copy-url');
  const anotherBtn = document.getElementById('btn-promote-another');

  if (pasteBtn) {
    pasteBtn.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text && urlInput) {
          urlInput.value = text.trim();
          showToast('تم لصق الرابط من الحافظة 📋', 'info');
        }
      } catch (e) {
        showToast('يرجى لصق الرابط يدوياً داخل الحقل', 'warning');
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      if (urlInput) urlInput.value = '';
      resetPromoteResult();
      showToast('تم إفراغ الحقل', 'info');
    });
  }

  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const resInput = document.getElementById('promote-res-url');
      if (resInput && resInput.value) {
        navigator.clipboard.writeText(resInput.value).then(() => {
          showToast('تم نسخ الرابط الرسمي بنجاح 📋', 'success');
        }).catch(() => {
          resInput.select();
          document.execCommand('copy');
          showToast('تم نسخ الرابط 📋', 'success');
        });
      }
    });
  }

  if (anotherBtn) {
    anotherBtn.addEventListener('click', () => {
      if (urlInput) {
        urlInput.value = '';
        urlInput.focus();
      }
      resetPromoteResult();
    });
  }

  // Bind Save Permissions button in Settings
  const btnSavePermissions = document.getElementById('btn-save-transfer-permissions');
  if (btnSavePermissions) {
    btnSavePermissions.addEventListener('click', saveTransferPermissions);
  }
}

function resetPromoteResult() {
  const workflowContainer = document.getElementById('promote-workflow-container');
  const step1LoadingCard = document.getElementById('promote-step1-loading-card');
  const publishedCard = document.getElementById('promote-published-card');
  const titleEl = document.getElementById('promote-res-title');
  const urlEl = document.getElementById('promote-res-url');
  const openBtn = document.getElementById('btn-promote-open-url');

  if (workflowContainer) workflowContainer.style.display = 'none';
  if (step1LoadingCard) step1LoadingCard.style.display = 'none';
  if (publishedCard) publishedCard.style.display = 'none';
  if (titleEl) titleEl.textContent = '--';
  if (urlEl) urlEl.value = '';
  if (openBtn) openBtn.href = '#';
}

async function executePromoteReviewArticle() {
  const urlInput = document.getElementById('promote-input-url');
  const submitBtn = document.getElementById('btn-promote-submit');
  const btnText = document.getElementById('promote-btn-text');
  const btnIcon = document.getElementById('promote-btn-icon');

  const workflowContainer = document.getElementById('promote-workflow-container');
  const step1LoadingCard = document.getElementById('promote-step1-loading-card');
  const publishedCard = document.getElementById('promote-published-card');

  const resTitle = document.getElementById('promote-res-title');
  const resUrl = document.getElementById('promote-res-url');
  const openBtn = document.getElementById('btn-promote-open-url');

  if (!urlInput || !urlInput.value.trim()) {
    showToast('يرجى إدخال رابط خبر الريفيو المراد اعتماده 🔗', 'warning');
    if (urlInput) urlInput.focus();
    return;
  }

  const reviewUrl = urlInput.value.trim();

  if (!reviewUrl.startsWith('http://') && !reviewUrl.startsWith('https://')) {
    showToast('الرابط يجب أن يبدأ بـ https:// أو http://', 'error');
    return;
  }

  // Set initial UI state: Start Workflow
  if (submitBtn) submitBtn.disabled = true;
  if (btnText) btnText.textContent = 'جاري اعتماد ونقل الخبر وتسجيل البيانات...';
  if (btnIcon) btnIcon.textContent = '⏳';

  if (workflowContainer) workflowContainer.style.display = 'block';
  if (step1LoadingCard) step1LoadingCard.style.display = 'block';
  if (publishedCard) publishedCard.style.display = 'none';

  workflowContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const res = await apiCall('/api/articles/promote-review', 'POST', {
      review_url: reviewUrl,
      generate_caption: false,
      publish_to_facebook: false
    });

    if (!res.success) {
      throw new Error(res.message || 'حدث خطأ أثناء اعتماد ونقل الخبر');
    }

    if (step1LoadingCard) step1LoadingCard.style.display = 'none';

    // Populate Published Card
    if (resTitle) resTitle.textContent = res.title || 'تم اعتماد ونشر الخبر وتسجيل البيانات بنجاح';
    if (resUrl) resUrl.value = res.main_url || '';
    if (openBtn) {
      openBtn.href = res.main_url || '#';
    }

    // SHOW THE CELEBRATION PUBLISHED CARD IMMEDIATELY!
    if (publishedCard) {
      publishedCard.style.display = 'block';
      publishedCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    showToast('🎉 رائع! تم اعتماد ونقل الخبر وتسجيل البيانات بنجاح في المنظومة!', 'success');

    // Refresh archive in background
    if (typeof loadArticlesArchive === 'function') {
      loadArticlesArchive(true).catch(() => {});
    }

  } catch (err) {
    if (step1LoadingCard) step1LoadingCard.style.display = 'none';
    showToast(err.message || 'فشلت عملية الاعتماد، يرجى التأكد من الرابط والمحاولة مجدداً', 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
    if (btnText) btnText.textContent = 'اعتماد ونقل الخبر 🚀';
    if (btnIcon) btnIcon.textContent = '✅';
  }
}

async function loadTransferPermissionsSettings() {
  const container = document.getElementById('transfer-users-list-container');
  if (!container) return;

  try {
    const res = await apiCall('/api/transfer/permissions');
    if (res.success && res.users) {
      if (res.users.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">لا يوجد حسابات مسجلة حالياً.</div>';
        return;
      }
      container.innerHTML = res.users.map(u => {
        const isAlwaysAllowed = (u.role === 'admin' || u.role === 'deputy_editor' || u.role === 'editor');
        const checked = (u.is_allowed || isAlwaysAllowed) ? 'checked' : '';
        const disabled = isAlwaysAllowed ? 'disabled' : '';
        const note = isAlwaysAllowed ? ' <span style="font-size: 10.5px; color: var(--accent-gold); font-weight: bold;">(مفعل تلقائياً بالرتبة)</span>' : '';
        return `
          <label style="display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.03); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 14px; cursor: ${isAlwaysAllowed ? 'default' : 'pointer'};">
            <input type="checkbox" class="chk-transfer-user" value="${u.username}" ${checked} ${disabled} style="width: 16px; height: 16px; accent-color: #F59E0B; cursor: pointer;">
            <div>
              <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">
                ${u.full_name || u.username} ${note}
              </div>
              <div style="font-size: 11px; color: var(--text-muted); font-family: var(--font-code);">
                @${u.username} ${u.role ? `• ${u.role}` : ''}
              </div>
            </div>
          </label>
        `;
      }).join('');
    }
  } catch (err) {
    container.innerHTML = `<div style="color: var(--color-error); font-size: 13px;">فشل تحميل قائمة الصلاحيات: ${err.message}</div>`;
  }
}

async function saveTransferPermissions() {
  const btn = document.getElementById('btn-save-transfer-permissions');
  const checkboxes = document.querySelectorAll('.chk-transfer-user');
  const allowed = [];
  checkboxes.forEach(cb => {
    if (cb.checked && !cb.disabled) {
      allowed.push(cb.value);
    }
  });

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>جاري الحفظ... ⏳</span>';
  }

  try {
    const res = await apiCall('/api/transfer/permissions', 'POST', { allowed_usernames: allowed });
    showToast(res.message || 'تم حفظ صلاحيات نقل الأخبار بنجاح ✅', 'success');
  } catch (err) {
    showToast(`فشل حفظ الصلاحيات: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>💾 حفظ الصلاحيات المحددة</span>';
    }
  }
}

// =============================================================================
// REVIEW ARTICLES CLEANUP CONTROLLER (CHIEF & DEPUTY EDITOR)
// =============================================================================
let rcCurrentDate = null;
let rcCurrentDateFormatted = '';
let rcCurrentDayData = null;
let rcActiveFilter = 'all'; // 'all' | 'unapproved' | 'approved'
let rcSearchQuery = '';
let rcSelectedIds = new Set();
let rcPendingDeleteAction = null;
let _rcInitialized = false;

function initReviewCleanup() {
  if (!_rcInitialized) {
    _rcInitialized = true;

    // Refresh button
    const btnRefresh = document.getElementById('btn-refresh-review-cleanup');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => loadReviewCleanupDates());
    }

    // Custom date inspector button
    const btnCustomDate = document.getElementById('btn-rc-custom-date-inspect');
    if (btnCustomDate) {
      btnCustomDate.addEventListener('click', () => {
        const dateInput = document.getElementById('rc-custom-date-input');
        if (!dateInput || !dateInput.value) {
          showToast('يرجى تحديد تاريخ أولاً من خانة التاريخ', 'warning');
          return;
        }
        openReviewDayInspector(dateInput.value, dateInput.value);
      });
    }

    // Back button
    const btnBack = document.getElementById('btn-rc-back-to-dates');
    if (btnBack) {
      btnBack.addEventListener('click', () => {
        document.getElementById('rc-inspector-view').style.display = 'none';
        document.getElementById('rc-dates-view').style.display = 'block';
        rcCurrentDate = null;
        rcCurrentDayData = null;
        loadReviewCleanupDates();
      });
    }

    // Filter tabs
    document.querySelectorAll('.rc-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.rc-tab-btn').forEach(b => {
          b.classList.remove('active');
          b.style.background = 'rgba(255, 255, 255, 0.05)';
          b.style.borderColor = 'var(--border-subtle)';
          b.style.color = 'var(--text-secondary)';
        });
        btn.classList.add('active');
        btn.style.background = 'rgba(245, 158, 11, 0.15)';
        btn.style.borderColor = 'var(--accent-gold)';
        btn.style.color = 'var(--accent-gold)';
        rcActiveFilter = btn.dataset.rcFilter;
        renderReviewDayArticles();
      });
    });

    // Search input
    const searchInput = document.getElementById('rc-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        rcSearchQuery = e.target.value.trim().toLowerCase();
        renderReviewDayArticles();
      });
    }

    // Master checkbox
    const masterCb = document.getElementById('rc-select-all-cb');
    if (masterCb) {
      masterCb.addEventListener('change', (e) => {
        const checked = e.target.checked;
        const visibleCbs = document.querySelectorAll('.rc-article-cb');
        visibleCbs.forEach(cb => {
          cb.checked = checked;
          const idVal = cb.value;
          if (checked) {
            rcSelectedIds.add(idVal);
          } else {
            rcSelectedIds.delete(idVal);
          }
        });
        updateSelectedCountUI();
      });
    }

    // Action buttons
    const btnDelUnapproved = document.getElementById('btn-rc-delete-unapproved');
    if (btnDelUnapproved) {
      btnDelUnapproved.addEventListener('click', () => {
        if (!rcCurrentDayData || !rcCurrentDayData.articles) return;
        const unapproved = rcCurrentDayData.articles.filter(a => !a.is_on_main);
        if (unapproved.length === 0) {
          showToast('لا توجد مقالات غير معتمدة لحذفها في هذا اليوم! 🟢', 'info');
          return;
        }
        const postIds = unapproved.map(a => a.post_id).filter(Boolean);
        const artIds = unapproved.map(a => a.id).filter(Boolean);
        showRcConfirmModal(
          'تأكيد حذف المقالات غير المعتمدة فقط',
          `سيتم حذف جميع المقالات غير المعتمدة في يوم (${rcCurrentDateFormatted || rcCurrentDate}) وعددها (${unapproved.length}) خبراً نهائياً من موقع الريفيو (WordPress) وقاعدة البيانات، مع الحفاظ الكامل على المقالات المنقولة والمعتمدة على الجريدة الأساسية.`,
          unapproved.length,
          () => executeDeleteReviewArticles(postIds, artIds)
        );
      });
    }

    const btnDelAllDay = document.getElementById('btn-rc-delete-all-day');
    if (btnDelAllDay) {
      btnDelAllDay.addEventListener('click', () => {
        if (!rcCurrentDayData || !rcCurrentDayData.articles || rcCurrentDayData.articles.length === 0) return;
        const allArticles = rcCurrentDayData.articles;
        const postIds = allArticles.map(a => a.post_id).filter(Boolean);
        const artIds = allArticles.map(a => a.id).filter(Boolean);
        showRcConfirmModal(
          '⚠️ تحذير شديد: تأكيد حذف جميع أخبار هذا اليوم',
          `أنت على وشك حذف جميع أخبار الريفيو ليوم (${rcCurrentDateFormatted || rcCurrentDate}) بالكامل وعددها (${allArticles.length}) خبراً، بما فيها الأخبار المعتمدة على الأساسية. هذا الإجراء لا يمكن التراجع عنه.`,
          allArticles.length,
          () => executeDeleteReviewArticles(postIds, artIds)
        );
      });
    }

    const btnDelSelected = document.getElementById('btn-rc-delete-selected');
    if (btnDelSelected) {
      btnDelSelected.addEventListener('click', () => {
        if (rcSelectedIds.size === 0) return;
        if (!rcCurrentDayData || !rcCurrentDayData.articles) return;
        const selectedArticles = rcCurrentDayData.articles.filter(a => rcSelectedIds.has(String(a.post_id || a.id)));
        const postIds = selectedArticles.map(a => a.post_id).filter(Boolean);
        const artIds = selectedArticles.map(a => a.id).filter(Boolean);
        showRcConfirmModal(
          'تأكيد حذف المقالات المحددة يدوياً',
          `سيتم حذف (${selectedArticles.length}) مقال ريفيو تم تحديدها يدوياً نهائياً من موقع الريفيو (WordPress) وقاعدة البيانات.`,
          selectedArticles.length,
          () => executeDeleteReviewArticles(postIds, artIds)
        );
      });
    }

    // Modal buttons
    const btnModalCancel = document.getElementById('btn-rc-modal-cancel');
    if (btnModalCancel) {
      btnModalCancel.addEventListener('click', hideRcConfirmModal);
    }
    const btnModalConfirm = document.getElementById('btn-rc-modal-confirm');
    if (btnModalConfirm) {
      btnModalConfirm.addEventListener('click', async () => {
        if (typeof rcPendingDeleteAction === 'function') {
          const action = rcPendingDeleteAction;
          rcPendingDeleteAction = null;
          await action();
        }
      });
    }
  }

  // Show Dates View, hide Inspector
  document.getElementById('rc-dates-view').style.display = 'block';
  document.getElementById('rc-inspector-view').style.display = 'none';
  loadReviewCleanupDates();
}

async function loadReviewCleanupDates() {
  const loading = document.getElementById('rc-dates-loading');
  const empty = document.getElementById('rc-dates-empty');
  const grid = document.getElementById('rc-dates-grid');
  if (!grid) return;

  if (loading) loading.style.display = 'block';
  if (empty) empty.style.display = 'none';
  grid.innerHTML = '';

  try {
    const res = await apiCall('/api/admin/review-cleanup/dates');
    if (loading) loading.style.display = 'none';

    if (res.success && res.dates && res.dates.length > 0) {
      grid.innerHTML = res.dates.map(d => {
        return `
          <div class="glass-card" style="padding: 20px; border-radius: 14px; border: 1.5px solid rgba(245, 158, 11, 0.25); display: flex; flex-direction: column; justify-content: space-between; gap: 16px; transition: transform 0.2s, box-shadow 0.2s;">
            <div>
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                <div style="font-size: 16px; font-weight: 800; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
                  <span>🗓️</span>
                  <span>${d.date_formatted || d.date}</span>
                </div>
                <span class="badge badge-gold" style="font-size: 11px; font-family: var(--font-code); font-weight: 800;">
                  ${d.date}
                </span>
              </div>
              <div style="display: flex; align-items: center; gap: 8px; font-size: 13.5px; color: var(--text-secondary); background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 8px;">
                <span>📰 إجمالي أخبار الريفيو:</span>
                <strong style="color: var(--accent-gold); font-size: 15px; font-family: var(--font-code);">${d.total_count} خبر</strong>
              </div>
            </div>

            <div style="display: flex; gap: 8px;">
              <button type="button" class="btn btn-gold" onclick="openReviewDayInspector('${d.date}', '${d.date_formatted || d.date}')" style="flex: 1; padding: 9px 12px; font-size: 12.5px; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 6px;">
                <span>🔍</span>
                <span>فحص ومطابقة الأخبار</span>
              </button>
              <button type="button" class="btn btn-secondary" onclick="confirmDeleteAllDayDirect('${d.date}', '${d.date_formatted || d.date}', ${d.total_count})" style="border-color: rgba(239, 68, 68, 0.4); color: #EF4444; padding: 9px 12px; font-size: 12px;" title="حذف كل أخبار اليوم">
                <span>🗑️</span>
              </button>
            </div>
          </div>
        `;
      }).join('');
    } else {
      if (empty) empty.style.display = 'block';
    }
  } catch (err) {
    if (loading) loading.style.display = 'none';
    showToast(`فشل جلب تواريخ الريفيو: ${err.message}`, 'error');
  }
}

async function openReviewDayInspector(dateStr, dateFormatted) {
  rcCurrentDate = dateStr;
  rcCurrentDateFormatted = dateFormatted || dateStr;
  rcSelectedIds.clear();
  rcActiveFilter = 'all';
  rcSearchQuery = '';

  const datesView = document.getElementById('rc-dates-view');
  const inspectorView = document.getElementById('rc-inspector-view');
  if (datesView) datesView.style.display = 'none';
  if (inspectorView) inspectorView.style.display = 'block';

  const labelEl = document.getElementById('rc-inspector-date-label');
  if (labelEl) labelEl.textContent = rcCurrentDateFormatted;

  // Reset counters to loading
  document.getElementById('rc-stat-total').textContent = '...';
  document.getElementById('rc-stat-matched').textContent = '...';
  document.getElementById('rc-stat-unmatched').textContent = '...';
  document.getElementById('rc-btn-unapproved-count').textContent = '0';
  document.getElementById('rc-tab-count-all').textContent = '0';
  document.getElementById('rc-tab-count-unmatched').textContent = '0';
  document.getElementById('rc-tab-count-matched').textContent = '0';

  const winLabelEl = document.getElementById('rc-inspector-window-label');
  if (winLabelEl) winLabelEl.textContent = '...';
  const mainCountEl = document.getElementById('rc-inspector-main-count');
  if (mainCountEl) mainCountEl.textContent = '...';

  const tbody = document.getElementById('rc-articles-table-body');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 30px; color: var(--accent-gold);">⏳ جاري سحب مقالات الأساسية والريفيو (اليوم واليوم التالي) والمطابقة الذكية...</td></tr>';
  }

  try {
    const res = await apiCall(`/api/admin/review-cleanup/day-details?date=${encodeURIComponent(dateStr)}`);
    if (res.success) {
      rcCurrentDayData = res;
      document.getElementById('rc-stat-total').textContent = res.total_count;
      document.getElementById('rc-stat-matched').textContent = res.matched_count;
      document.getElementById('rc-stat-unmatched').textContent = res.unmatched_count;
      document.getElementById('rc-btn-unapproved-count').textContent = res.unmatched_count;
      document.getElementById('rc-tab-count-all').textContent = res.total_count;
      document.getElementById('rc-tab-count-unmatched').textContent = res.unmatched_count;
      document.getElementById('rc-tab-count-matched').textContent = res.matched_count;

      if (winLabelEl) winLabelEl.textContent = res.window_label || `${res.date} واليوم التالي`;
      if (mainCountEl) mainCountEl.textContent = res.main_articles_compared_count || '0';

      renderReviewDayArticles();
    } else {
      throw new Error(res.message || 'فشل جلب تفاصيل أخبار اليوم');
    }
  } catch (err) {
    showToast(`خطأ في فحص أخبار اليوم: ${err.message}`, 'error');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; padding: 25px; color: var(--color-error);">خطأ: ${err.message}</td></tr>`;
    }
  }
}

function renderReviewDayArticles() {
  const tbody = document.getElementById('rc-articles-table-body');
  const emptyFilterEl = document.getElementById('rc-inspector-empty');
  if (!tbody || !rcCurrentDayData || !rcCurrentDayData.articles) return;

  const articles = rcCurrentDayData.articles;
  const filtered = articles.filter(art => {
    // 1. Filter tab
    if (rcActiveFilter === 'unapproved' && art.is_on_main) return false;
    if (rcActiveFilter === 'approved' && !art.is_on_main) return false;

    // 2. Search query
    if (rcSearchQuery) {
      const titleLower = (art.title || '').toLowerCase();
      const pid = String(art.post_id || '');
      if (!titleLower.includes(rcSearchQuery) && !pid.includes(rcSearchQuery)) {
        return false;
      }
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = '';
    if (emptyFilterEl) emptyFilterEl.style.display = 'block';
    return;
  }

  if (emptyFilterEl) emptyFilterEl.style.display = 'none';

  tbody.innerHTML = filtered.map((art) => {
    const rowId = String(art.post_id || art.id);
    const isChecked = rcSelectedIds.has(rowId);

    // Status badge HTML
    let statusBadgeHtml = '';
    if (art.is_on_main) {
      statusBadgeHtml = `
        <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
          <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.4); font-size: 11.5px; font-weight: 700;">
            🟢 معتمد على الأساسية
          </span>
          ${art.main_url ? `<a href="${art.main_url}" target="_blank" style="font-size: 11px; color: var(--accent-gold); text-decoration: underline;">🔗 عرض بالأساسية</a>` : ''}
        </div>
      `;
    } else {
      statusBadgeHtml = `
        <span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.4); font-size: 11.5px; font-weight: 700;">
          🔴 غير معتمد (ريفيو فقط)
        </span>
      `;
    }

    return `
      <tr style="${art.is_on_main ? 'background: rgba(16, 185, 129, 0.02);' : 'background: rgba(239, 68, 68, 0.02);'}">
        <td style="text-align: center;">
          <input type="checkbox" class="rc-article-cb" value="${rowId}" ${isChecked ? 'checked' : ''} onchange="toggleRcArticleSelect('${rowId}', this.checked)" style="width: 16px; height: 16px; cursor: pointer;">
        </td>
        <td>
          <div style="font-size: 13.5px; font-weight: 700; color: var(--text-primary); margin-bottom: 4px; line-height: 1.4;">
            ${art.title || 'خبر بدون عنوان'}
          </div>
          <div style="display: flex; gap: 10px; font-size: 11px; color: var(--text-muted); align-items: center;">
            <span>ID: <code style="font-family: var(--font-code); color: var(--text-secondary);">${art.post_id || art.id}</code></span>
            ${art.post_url ? `<a href="${art.post_url}" target="_blank" style="color: var(--accent-gold); text-decoration: underline;">🔗 فتح خبر الريفيو</a>` : ''}
          </div>
        </td>
        <td style="text-align: center;">
          ${statusBadgeHtml}
        </td>
        <td style="text-align: center;">
          <button type="button" class="btn btn-secondary" onclick="confirmDeleteSingleArticle('${art.post_id || ''}', ${art.id || 0}, '${escapeHtml(art.title || '')}')" style="border-color: rgba(239, 68, 68, 0.4); color: #EF4444; padding: 5px 10px; font-size: 12px;" title="حذف هذا المقال">
            🗑️ حذف
          </button>
        </td>
      </tr>
    `;
  }).join('');

  updateSelectedCountUI();
}

function toggleRcArticleSelect(rowId, isChecked) {
  if (isChecked) {
    rcSelectedIds.add(rowId);
  } else {
    rcSelectedIds.delete(rowId);
  }
  updateSelectedCountUI();
}

function updateSelectedCountUI() {
  const count = rcSelectedIds.size;
  const btn = document.getElementById('btn-rc-delete-selected');
  const countSpan = document.getElementById('rc-btn-selected-count');
  if (countSpan) countSpan.textContent = count;

  if (btn) {
    if (count > 0) {
      btn.disabled = false;
      btn.style.opacity = '1';
      btn.style.borderColor = 'var(--accent-gold)';
      btn.style.color = 'var(--accent-gold)';
    } else {
      btn.disabled = true;
      btn.style.opacity = '0.5';
      btn.style.borderColor = 'rgba(255,255,255,0.1)';
      btn.style.color = 'var(--text-muted)';
    }
  }

  // Update master checkbox state
  const masterCb = document.getElementById('rc-select-all-cb');
  if (masterCb) {
    const visibleCbs = document.querySelectorAll('.rc-article-cb');
    if (visibleCbs.length > 0) {
      const allChecked = Array.from(visibleCbs).every(cb => cb.checked);
      masterCb.checked = allChecked;
    } else {
      masterCb.checked = false;
    }
  }
}

function showRcConfirmModal(title, description, count, onConfirm) {
  const modal = document.getElementById('modal-rc-confirm');
  const titleEl = document.getElementById('rc-modal-title');
  const descEl = document.getElementById('rc-modal-description');
  const countEl = document.getElementById('rc-modal-target-count');

  if (titleEl) titleEl.textContent = title;
  if (descEl) descEl.textContent = description;
  if (countEl) countEl.textContent = count;

  rcPendingDeleteAction = onConfirm;

  if (modal) modal.style.display = 'flex';
}

function hideRcConfirmModal() {
  const modal = document.getElementById('modal-rc-confirm');
  if (modal) modal.style.display = 'none';
  rcPendingDeleteAction = null;
}

function confirmDeleteSingleArticle(postId, articleId, articleTitle) {
  showRcConfirmModal(
    'تأكيد حذف مقال واحد',
    `هل أنت متأكد من رغبتك في حذف المقال: "${articleTitle}"؟ سيتم حذفه نهائياً من موقع الريفيو على WordPress ومن قاعدة البيانات.`,
    1,
    () => executeDeleteReviewArticles(postId ? [postId] : [], articleId ? [articleId] : [])
  );
}

function confirmDeleteAllDayDirect(dateStr, dateFormatted, totalCount) {
  showRcConfirmModal(
    '⚠️ تأكيد حذف جميع أخبار اليوم من أرشيف الريفيو',
    `أنت على وشك حذف جميع أخبار يوم (${dateFormatted || dateStr}) وعددها (${totalCount}) خبراً من موقع الريفيو (WordPress) ومن قاعدة البيانات. هل تريد المتابعة؟`,
    totalCount,
    async () => {
      try {
        const res = await apiCall(`/api/admin/review-cleanup/day-details?date=${encodeURIComponent(dateStr)}`);
        if (res.success && res.articles) {
          const postIds = res.articles.map(a => a.post_id).filter(Boolean);
          const artIds = res.articles.map(a => a.id).filter(Boolean);
          await executeDeleteReviewArticles(postIds, artIds);
        }
      } catch (err) {
        showToast(`فشل حذف أخبار اليوم: ${err.message}`, 'error');
      }
    }
  );
}

async function executeDeleteReviewArticles(itemsOrPostIds, maybeArticleIds) {
  hideRcConfirmModal();

  // 1. Normalize items into array of objects: { post_id, id, title }
  let items = [];
  if (Array.isArray(itemsOrPostIds) && itemsOrPostIds.length > 0 && typeof itemsOrPostIds[0] === 'object') {
    items = itemsOrPostIds;
  } else {
    const postIds = Array.isArray(itemsOrPostIds) ? itemsOrPostIds : [];
    const artIds = Array.isArray(maybeArticleIds) ? maybeArticleIds : [];
    const maxLen = Math.max(postIds.length, artIds.length);
    for (let i = 0; i < maxLen; i++) {
      items.push({
        post_id: postIds[i] || null,
        id: artIds[i] || null,
        title: ''
      });
    }
  }

  const totalItems = items.length;
  if (totalItems === 0) {
    showToast('لم يتم تحديد أي مقالات للحذف', 'warning');
    return;
  }

  // 2. Setup Progress Modal Elements
  const progressModal = document.getElementById('modal-rc-deletion-progress');
  const progressBar = document.getElementById('rc-del-progress-bar');
  const percentText = document.getElementById('rc-del-percent-text');
  const statusText = document.getElementById('rc-del-progress-status');
  const countCurrent = document.getElementById('rc-del-count-current');
  const countTotal = document.getElementById('rc-del-count-total');
  const batchInfo = document.getElementById('rc-del-batch-info');
  const logText = document.getElementById('rc-del-log-text');
  const progressTitle = document.getElementById('rc-del-progress-title');

  if (progressModal) progressModal.style.display = 'flex';
  if (countTotal) countTotal.textContent = totalItems;
  if (countCurrent) countCurrent.textContent = '0';
  if (progressBar) progressBar.style.width = '1%';
  if (percentText) percentText.textContent = '1%';
  if (progressTitle) {
    progressTitle.textContent = 'جاري حذف مقالات الريفيو...';
    progressTitle.style.color = '#FFFFFF';
  }
  if (statusText) {
    statusText.textContent = '⚡ جاري الاتصال بـ WordPress وقاعدة البيانات...';
    statusText.style.color = '#F87171';
  }
  if (batchInfo) batchInfo.textContent = 'جاري تجهيز الدفعات...';
  if (logText) logText.textContent = `بدء حذف ${totalItems} مقال...`;

  // 3. Batch processing (10 items per batch to avoid HTTP timeouts and provide smooth 1-100% progress)
  const BATCH_SIZE = 10;
  const totalBatches = Math.ceil(totalItems / BATCH_SIZE);
  let totalWpDeleted = 0;
  let totalDbDeleted = 0;
  let processedCount = 0;

  for (let b = 0; b < totalBatches; b++) {
    const chunk = items.slice(b * BATCH_SIZE, (b + 1) * BATCH_SIZE);
    const chunkPostIds = chunk.map(c => c.post_id).filter(Boolean);
    const chunkArtIds = chunk.map(c => c.id).filter(Boolean);
    const batchNum = b + 1;

    if (batchInfo) {
      batchInfo.textContent = `الدفعة ${batchNum} من ${totalBatches}`;
    }
    if (logText) {
      logText.textContent = `جاري حذف الدفعة ${batchNum}/${totalBatches} (${chunk.length} مقال)...`;
    }

    try {
      const res = await apiCall('/api/admin/review-cleanup/delete', 'POST', {
        post_ids: chunkPostIds,
        article_ids: chunkArtIds
      });

      if (res.success) {
        totalWpDeleted += (res.blogger_deleted_count || 0);
        totalDbDeleted += (res.db_deleted_count || 0);
      }
    } catch (err) {
      console.error(`Error in deletion batch ${batchNum}:`, err);
      if (logText) {
        logText.textContent = `⚠️ تنبيه في الدفعة ${batchNum}: ${err.message}`;
      }
    }

    processedCount += chunk.length;
    const pct = Math.min(100, Math.round((processedCount / totalItems) * 100));

    if (progressBar) progressBar.style.width = `${pct}%`;
    if (percentText) percentText.textContent = `${pct}%`;
    if (countCurrent) countCurrent.textContent = processedCount;
    if (statusText) {
      statusText.textContent = `⚡ تم إنجاز ${processedCount} من أصل ${totalItems} مقالاً (${pct}%)...`;
    }
  }

  // 4. Finished 100% State
  if (progressBar) progressBar.style.width = '100%';
  if (percentText) percentText.textContent = '100%';
  if (progressTitle) {
    progressTitle.textContent = '✅ اكتملت عملية الحذف بنجاح!';
    progressTitle.style.color = '#10B981';
  }
  if (statusText) {
    statusText.textContent = `🎉 تم حذف ${totalWpDeleted} مقال من موقع الريفيو و ${totalDbDeleted} من قاعدة البيانات.`;
    statusText.style.color = '#10B981';
  }
  if (logText) {
    logText.textContent = '✨ تمت تصفية وحذف المقالات المستهدفة بنجاح كامل.';
  }

  showToast(`✅ تم اكتمال الحذف بنجاح! (${totalWpDeleted} مقال من موقع الريفيو)`, 'success');

  // Short delay so the user clearly sees the 100% completion
  await new Promise(r => setTimeout(r, 1400));

  if (progressModal) progressModal.style.display = 'none';

  // Clear selections
  rcSelectedIds.clear();
  updateSelectedCountUI();

  // Reload current view
  if (rcCurrentDate) {
    openReviewDayInspector(rcCurrentDate, rcCurrentDateFormatted);
  } else {
    loadReviewCleanupDates();
  }
}

function escapeHtml(str) {
  return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// Global exposures
window.initPromoteTool = initPromoteTool;
window.resetPromoteResult = resetPromoteResult;
window.executePromoteReviewArticle = executePromoteReviewArticle;
window.loadTransferPermissionsSettings = loadTransferPermissionsSettings;
window.saveTransferPermissions = saveTransferPermissions;
window.checkTransferToolPermission = checkTransferToolPermission;

window.initReviewCleanup = initReviewCleanup;
window.loadReviewCleanupDates = loadReviewCleanupDates;
window.openReviewDayInspector = openReviewDayInspector;
window.toggleRcArticleSelect = toggleRcArticleSelect;
window.confirmDeleteSingleArticle = confirmDeleteSingleArticle;
window.confirmDeleteAllDayDirect = confirmDeleteAllDayDirect;
window.hideRcConfirmModal = hideRcConfirmModal;


// =============================================================================
// CHIEF EDITOR EXCLUSIVE CRM: CUSTOMER LEADS CONTROLLER
// =============================================================================

let _customerLeadsCurrentPage = 1;
let _customerLeadsSearchTimeout = null;
let _currentLeadNotesId = null;

function getCategoryBadgeConfig(cat) {
  const c = (cat || 'عام').trim();
  if (c.includes('قانون') || c.includes('محام') || c.includes('قضائ')) {
    return { icon: '⚖️', label: c, cls: 'crm-badge-tag legal' };
  } else if (c.includes('عقار') || c.includes('استثمار') || c.includes('إسكان') || c.includes('بناء')) {
    return { icon: '🏢', label: c, cls: 'crm-badge-tag realestate' };
  } else if (c.includes('صح') || c.includes('طب') || c.includes('علاج') || c.includes('تغذي') || c.includes('مستشف')) {
    return { icon: '🩺', label: c, cls: 'crm-badge-tag health' };
  } else if (c.includes('أعمال') || c.includes('شرك') || c.includes('اقتصاد') || c.includes('مال') || c.includes('تسويق')) {
    return { icon: '💼', label: c, cls: 'crm-badge-tag business' };
  } else if (c.includes('ذات') || c.includes('تعليم') || c.includes('تدريب') || c.includes('كوتش') || c.includes('تنمي')) {
    return { icon: '✨', label: c, cls: 'crm-badge-tag selfdev' };
  }
  return { icon: '📇', label: c, cls: 'crm-badge-tag general' };
}

async function loadCustomerLeads(page = 1) {
  _customerLeadsCurrentPage = page;
  const tbody = document.getElementById('customer-leads-tbody');
  if (tbody) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 45px; color: var(--text-muted);">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 10px;">
            <span style="font-size: 28px; animation: pulse 1.5s infinite;">⏳</span>
            <span style="font-size: 14px; font-weight: 600;">جاري تحديث واسترجاع بيانات عملاء النخبة...</span>
          </div>
        </td>
      </tr>
    `;
  }

  const search = (document.getElementById('filter-lead-search')?.value || '').trim();
  const category = document.getElementById('filter-lead-category')?.value || 'الكل';
  const status = document.getElementById('filter-lead-status')?.value || 'الكل';

  try {
    const query = new URLSearchParams({
      page: page,
      limit: 25,
      search: search,
      category: category,
      status: status
    });

    const res = await apiCall(`/api/admin/customer-leads?${query.toString()}`, 'GET');
    if (!res || !res.success) {
      throw new Error(res?.detail || 'فشل جلب بيانات العملاء');
    }

    // Update 4 HUD Stat Cards
    const totalEl = document.getElementById('stat-total-leads');
    const verifiedEl = document.getElementById('stat-verified-leads');
    const catsEl = document.getElementById('stat-categories-count');
    const vipEl = document.getElementById('stat-vip-leads');
    
    if (totalEl) totalEl.textContent = Number(res.total || 0).toLocaleString();
    if (verifiedEl) verifiedEl.textContent = Number(res.verified_phones || 0).toLocaleString();
    if (catsEl) catsEl.textContent = Number((res.categories || []).length).toLocaleString();
    if (vipEl) vipEl.textContent = Number(res.status_counts?.VIP || 0).toLocaleString();

    // Update Status Filter Pills Counters
    if (res.status_counts) {
      const sc = res.status_counts;
      const elAll = document.getElementById('pill-count-all');
      const elNew = document.getElementById('pill-count-new');
      const elContacted = document.getElementById('pill-count-contacted');
      const elVip = document.getElementById('pill-count-vip');
      const elNotInt = document.getElementById('pill-count-not-interested');
      if (elAll) elAll.textContent = (sc.ALL || 0).toLocaleString();
      if (elNew) elNew.textContent = (sc.NEW || 0).toLocaleString();
      if (elContacted) elContacted.textContent = (sc.CONTACTED || 0).toLocaleString();
      if (elVip) elVip.textContent = (sc.VIP || 0).toLocaleString();
      if (elNotInt) elNotInt.textContent = (sc.NOT_INTERESTED || 0).toLocaleString();
    }

    // Populate Category Dropdown if needed
    const catSelect = document.getElementById('filter-lead-category');
    if (catSelect && catSelect.options.length <= 1 && res.categories) {
      res.categories.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat;
        opt.textContent = `📁 ${cat}`;
        catSelect.appendChild(opt);
      });
    }

    renderCustomerLeadsTable(res.leads || [], page, res.total || 0, res.limit || 25);
  } catch (err) {
    console.error('Error loading customer leads:', err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:35px; color:var(--color-error); font-weight:700;">خطأ: ${err.message}</td></tr>`;
    }
  }
}

function renderCustomerLeadsTable(leads, page, total, limit) {
  const tbody = document.getElementById('customer-leads-tbody');
  if (!tbody) return;

  if (!leads || leads.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 50px 20px; color: var(--text-muted);">
          <div style="font-size: 38px; margin-bottom: 10px;">📇</div>
          <div style="font-size: 16px; font-weight: 800; color: #FFFFFF;">لا توجد بيانات عملاء مطابقة للبحث أو الفلتر المختار</div>
          <div style="font-size: 13px; margin-top: 6px; color: var(--text-muted);">يتم استخراج وسحب بيانات العملاء تلقائياً وسرياً عند اعتماد ونشر أي خبر جديد بالجريدة.</div>
        </td>
      </tr>
    `;
    updateCustomerLeadsPagination(0, 1, 25);
    return;
  }

  tbody.innerHTML = leads.map((l, index) => {
    const rowNum = (page - 1) * limit + index + 1;
    const phone = (l.client_phone || '').trim();
    const hasPhone = phone && phone.length >= 8;
    const cleanPhone = phone.replace(/[^\d+]/g, '');
    const waLink = hasPhone ? `https://wa.me/${cleanPhone}` : '#';
    const telLink = hasPhone ? `tel:${cleanPhone}` : '#';
    const badge = getCategoryBadgeConfig(l.category);
    const dateStr = (l.created_at || '').substring(0, 10);

    return `
      <tr class="crm-row">
        <td style="font-size: 12px; color: var(--text-muted); font-weight: 800; text-align: center;">${rowNum}</td>
        <td>
          <div style="display: flex; align-items: center; gap: 12px;">
            <div class="crm-avatar" title="${escapeHtml(l.category || '')}">
              ${badge.icon}
            </div>
            <div>
              <div style="font-weight: 800; color: #FFFFFF; font-size: 14px; letter-spacing: -0.2px;">
                ${escapeHtml(l.client_name || 'عميل مستهدف')}
              </div>
              <div style="display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-muted); margin-top: 3px;">
                <span>📅 استخراج: ${dateStr || '-'}</span>
              </div>
            </div>
          </div>
        </td>
        <td>
          ${hasPhone ? `
            <div style="display: flex; flex-direction: column; gap: 6px;">
              <span style="font-family: var(--font-code); font-weight: 700; font-size: 13px; color: #F1F5F9; direction: ltr; text-align: right; display: inline-block;">
                ${phone}
              </span>
              <div style="display: flex; align-items: center; gap: 5px;">
                <a href="${waLink}" target="_blank" class="crm-wa-btn" title="محادثة واتساب مباشرة">
                  <span>💬</span>
                  <span>واتساب فوري</span>
                </a>
                <button type="button" class="crm-phone-copy" onclick="copyLeadPhone('${phone}', this)" title="نسخ الرقم">📋</button>
                <a href="${telLink}" class="crm-phone-call" title="اتصال هاتفي">📞</a>
              </div>
            </div>
          ` : `
            <div style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: rgba(255, 255, 255, 0.04); border-radius: 6px; color: var(--text-muted); font-size: 11.5px;">
              <span>⚠️ غير متوفر بالخبر</span>
            </div>
          `}
        </td>
        <td>
          <span class="${badge.cls}">
            <span>${badge.icon}</span>
            <span>${escapeHtml(badge.label)}</span>
          </span>
        </td>
        <td style="max-width: 270px;">
          <div style="font-size: 12.5px; font-weight: 600; color: #E2E8F0; line-height: 1.4; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;" title="${escapeHtml(l.article_title || '')}">
            ${escapeHtml(l.article_title || '-')}
          </div>
          ${l.article_url ? `
            <a href="${l.article_url}" target="_blank" class="crm-article-link" title="فتح وقراءة المقال في تبويب جديد">
              <span>🌐 فتح المقال</span>
              <span>↗</span>
            </a>
          ` : ''}
        </td>
        <td>
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="width: 22px; height: 22px; border-radius: 50%; background: rgba(255, 255, 255, 0.08); display: flex; align-items: center; justify-content: center; font-size: 10px;">✍️</div>
            <span style="font-size: 12px; font-weight: 700; color: #E2E8F0;">${escapeHtml(l.promoted_by_name || 'الإدارة')}</span>
          </div>
        </td>
        <td>
          <div class="crm-status-wrapper">
            <select class="crm-status-dropdown" onchange="updateCustomerLeadStatus(${l.id}, this.value)">
              <option value="NEW" ${l.contact_status === 'NEW' ? 'selected' : ''}>✨ عميل جديد</option>
              <option value="CONTACTED" ${l.contact_status === 'CONTACTED' ? 'selected' : ''}>📞 تم التواصل</option>
              <option value="VIP" ${l.contact_status === 'VIP' ? 'selected' : ''}>⭐ عميل VIP</option>
              <option value="NOT_INTERESTED" ${l.contact_status === 'NOT_INTERESTED' ? 'selected' : ''}>⛔ غير مهتم</option>
            </select>
            <button type="button" class="crm-notes-badge-btn ${l.notes ? 'has-notes' : ''}" onclick="openLeadNotesModal(${l.id}, '${escapeHtml(l.notes || '')}', '${escapeHtml(l.client_name || '')}')" title="فتح نافذة الملاحظات وسجل العميل">
              <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                ${l.notes ? escapeHtml(l.notes) : '+ إضافة ملاحظات'}
              </span>
              <span style="font-size: 11px; opacity: 0.7;">✏️</span>
            </button>
          </div>
        </td>
        <td style="text-align: center;">
          <button type="button" class="crm-btn-delete" onclick="deleteCustomerLeadItem(${l.id})" title="حذف العميل نهائياً">
            🗑️
          </button>
        </td>
      </tr>
    `;
  }).join('');

  updateCustomerLeadsPagination(total, page, limit);
}

function updateCustomerLeadsPagination(total, page, limit) {
  const countInfo = document.getElementById('customer-leads-count-info');
  const pageDisplay = document.getElementById('customer-leads-page-display');
  const btnPrev = document.getElementById('btn-lead-prev');
  const btnNext = document.getElementById('btn-lead-next');

  const totalPages = Math.ceil(total / limit) || 1;
  if (countInfo) countInfo.textContent = `إجمالي النتائج: ${total.toLocaleString()} عميل (صفحة ${page} من ${totalPages})`;
  if (pageDisplay) pageDisplay.textContent = page;

  if (btnPrev) {
    btnPrev.disabled = (page <= 1);
    btnPrev.onclick = () => loadCustomerLeads(page - 1);
  }
  if (btnNext) {
    btnNext.disabled = (page >= totalPages);
    btnNext.onclick = () => loadCustomerLeads(page + 1);
  }
}

window.copyLeadPhone = function(phone, btnEl) {
  if (!phone) return;
  navigator.clipboard.writeText(phone).then(() => {
    showToast(`📋 تم نسخ الرقم: ${phone}`, 'success');
    if (btnEl) {
      const old = btnEl.textContent;
      btnEl.textContent = '✅';
      setTimeout(() => btnEl.textContent = old, 1500);
    }
  });
};

window.updateCustomerLeadStatus = async function(leadId, newStatus) {
  try {
    const res = await apiCall(`/api/admin/customer-leads/${leadId}`, 'PUT', { contact_status: newStatus });
    if (res && res.success) {
      showToast('تم تحديث حالة التواصل بنجاح ✅', 'success');
      loadCustomerLeads(_customerLeadsCurrentPage);
    } else {
      throw new Error(res?.detail || 'فشل التحديث');
    }
  } catch (err) {
    showToast(`خطأ: ${err.message}`, 'error');
    loadCustomerLeads(_customerLeadsCurrentPage);
  }
};

window.openLeadNotesModal = function(leadId, currentNotes, clientName) {
  _currentLeadNotesId = leadId;
  const nameEl = document.getElementById('modal-notes-client-name');
  const inputEl = document.getElementById('modal-lead-notes-input');
  const modal = document.getElementById('modal-crm-notes');

  if (nameEl) nameEl.textContent = `— ${clientName || 'عميل مستهدف'}`;
  if (inputEl) inputEl.value = currentNotes || '';
  if (modal) modal.style.display = 'flex';
};

window.closeLeadNotesModal = function() {
  const modal = document.getElementById('modal-crm-notes');
  if (modal) modal.style.display = 'none';
  _currentLeadNotesId = null;
};

window.appendQuickTag = function(tag) {
  const inputEl = document.getElementById('modal-lead-notes-input');
  if (!inputEl) return;
  const val = inputEl.value.trim();
  if (!val) {
    inputEl.value = tag;
  } else if (!val.includes(tag)) {
    inputEl.value = `${val} | ${tag}`;
  }
  inputEl.focus();
};

window.saveLeadNotesModal = async function() {
  if (!_currentLeadNotesId) return;
  const inputEl = document.getElementById('modal-lead-notes-input');
  const notes = (inputEl?.value || '').trim();

  try {
    const res = await apiCall(`/api/admin/customer-leads/${_currentLeadNotesId}`, 'PUT', { notes: notes });
    if (res && res.success) {
      showToast('تم حفظ سجل ملاحظات العميل بنجاح 📝', 'success');
      closeLeadNotesModal();
      loadCustomerLeads(_customerLeadsCurrentPage);
    } else {
      throw new Error(res?.detail || 'فشل حفظ الملاحظات');
    }
  } catch (err) {
    showToast(`خطأ: ${err.message}`, 'error');
  }
};

window.deleteCustomerLeadItem = async function(leadId) {
  if (!confirm('هل أنت متأكد من رغبتك في حذف هذا العميل من قاعدة البيانات؟')) return;

  try {
    const res = await apiCall(`/api/admin/customer-leads/${leadId}`, 'DELETE');
    if (res && res.success) {
      showToast('تم حذف سجل العميل بنجاح 🗑️', 'success');
      loadCustomerLeads(_customerLeadsCurrentPage);
    } else {
      throw new Error(res?.detail || 'فشل الحذف');
    }
  } catch (err) {
    showToast(`خطأ: ${err.message}`, 'error');
  }
};

function selectStatusPill(statusVal) {
  document.querySelectorAll('.crm-status-pill').forEach(btn => {
    if (btn.getAttribute('data-status') === statusVal) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  const select = document.getElementById('filter-lead-status');
  if (select) select.value = statusVal;

  loadCustomerLeads(1);
}

function initCustomerLeadsEvents() {
  document.getElementById('btn-refresh-customer-leads')?.addEventListener('click', () => {
    loadCustomerLeads(1);
  });

  document.getElementById('filter-lead-search')?.addEventListener('input', () => {
    clearTimeout(_customerLeadsSearchTimeout);
    _customerLeadsSearchTimeout = setTimeout(() => {
      loadCustomerLeads(1);
    }, 350);
  });

  document.getElementById('filter-lead-category')?.addEventListener('change', () => {
    loadCustomerLeads(1);
  });

  document.getElementById('filter-lead-status')?.addEventListener('change', (e) => {
    const statusVal = e.target.value;
    document.querySelectorAll('.crm-status-pill').forEach(btn => {
      if (btn.getAttribute('data-status') === statusVal) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
    loadCustomerLeads(1);
  });

  // Status Pills Bar click handler
  document.querySelectorAll('.crm-status-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const statusVal = btn.getAttribute('data-status') || 'الكل';
      selectStatusPill(statusVal);
    });
  });

  document.getElementById('btn-export-customer-leads')?.addEventListener('click', () => {
    const token = getAuthToken();
    const url = `/api/admin/customer-leads/export`;
    const a = document.createElement('a');
    a.href = url;
    a.setAttribute('download', '');
    fetch(url, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.blob())
      .then(blob => {
        const u = window.URL.createObjectURL(blob);
        a.href = u;
        a.download = `customer_leads_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(u);
        showToast('📥 تم تحميل ملف إكسل لبيانات العملاء بنجاح!', 'success');
      })
      .catch(err => {
        showToast('فشل تصدير الملف: ' + err.message, 'error');
      });
  });

  // Extract Customer Lead from News Article URL
  const btnExtractLead = document.getElementById('btn-extract-lead-from-url');
  const inputExtractUrl = document.getElementById('input-extract-lead-url');
  const btnExtractText = document.getElementById('btn-extract-lead-text');
  const resultBanner = document.getElementById('extract-lead-result-banner');
  const resultTitle = document.getElementById('extract-lead-result-title');
  const resultSub = document.getElementById('extract-lead-result-sub');
  const btnDismissBanner = document.getElementById('btn-extract-lead-dismiss');

  btnDismissBanner?.addEventListener('click', () => {
    if (resultBanner) resultBanner.style.display = 'none';
  });

  async function handleLeadExtraction() {
    const rawUrl = inputExtractUrl?.value?.trim() || '';
    if (!rawUrl) {
      showToast('يرجى إدخال رابط الخبر أولاً', 'warning');
      inputExtractUrl?.focus();
      return;
    }

    if (btnExtractLead) btnExtractLead.disabled = true;
    if (btnExtractText) btnExtractText.textContent = '⏳ جاري القراءة والسحب...';

    try {
      const res = await apiCall('/api/admin/customer-leads/extract-from-url', 'POST', { url: rawUrl });
      if (res?.success) {
        showToast(res.message || '✅ تم استخراج وحفظ بيانات العميل بنجاح!', 'success');
        if (inputExtractUrl) inputExtractUrl.value = '';

        // Show Live Result Banner
        if (resultBanner && res.lead) {
          const l = res.lead;
          resultBanner.style.display = 'flex';
          if (resultTitle) {
            resultTitle.textContent = `✅ تم سحب العميل: ${l.client_name || 'عميل جديد'}`;
          }
          if (resultSub) {
            resultSub.innerHTML = `📞 الهاتف: <strong>${l.client_phone || 'غير مسجل'}</strong> &nbsp;|&nbsp; 🏢 القطاع: <strong>${l.category || 'عام'}</strong> &nbsp;|&nbsp; 📰 الخبر: <em>${(l.article_title || '').substring(0, 45)}...</em>`;
          }
        }

        // Refresh leads table and stats
        loadCustomerLeads(1);
      } else {
        throw new Error(res?.detail || 'تعذر استخراج بيانات العميل');
      }
    } catch (err) {
      showToast(err.message || 'فشل سحب بيانات العميل من الرابط', 'error');
    } finally {
      if (btnExtractLead) btnExtractLead.disabled = false;
      if (btnExtractText) btnExtractText.textContent = 'سحب بيانات العميل الآن';
    }
  }

  btnExtractLead?.addEventListener('click', handleLeadExtraction);

  inputExtractUrl?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleLeadExtraction();
    }
  });
}

// Auto-initialize events
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initCustomerLeadsEvents);
} else {
  initCustomerLeadsEvents();
}

window.loadCustomerLeads = loadCustomerLeads;
window.initCustomerLeadsEvents = initCustomerLeadsEvents;

// =============================================================================
// GEMINI FALLBACK MONITORING CONTROLLER (CHIEF & DEPUTY EDITOR)
// =============================================================================

let _geminiFallbackCurrentPage = 1;
let _geminiFallbackLogsData = [];
let _geminiFallbackSearchTimeout = null;

async function loadGeminiFallbackStats() {
  try {
    const res = await apiCall('/api/admin/gemini-fallback/stats');
    if (res && res.success && res.stats) {
      const s = res.stats;
      const elTotal = document.getElementById('gemini-stat-total');
      const elLat = document.getElementById('gemini-stat-latency');
      const elToday = document.getElementById('gemini-stat-today');
      const elSuccess = document.getElementById('gemini-stat-success-rate');

      if (elTotal) elTotal.textContent = Number(s.total_invocations || 0).toLocaleString('ar-EG');
      if (elLat) elLat.textContent = `${s.avg_latency || 0.0} ث`;
      if (elToday) elToday.textContent = Number(s.today_invocations || 0).toLocaleString('ar-EG');
      if (elSuccess) elSuccess.textContent = `${s.success_rate || 100}%`;
    }
  } catch (err) {
    console.warn('Could not load Gemini Fallback stats:', err);
  }
}

async function loadGeminiFallbackLogs(page = 1) {
  _geminiFallbackCurrentPage = page;
  const tbody = document.getElementById('gemini-logs-tbody');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="9" style="text-align: center; padding: 40px 15px; color: var(--text-muted);">
        <div style="font-size: 28px; margin-bottom: 8px;">🔄</div>
        <div style="font-weight: 700; font-size: 13.5px; color: #FFFFFF;">جاري تحميل سجلات التدخل اللحظي...</div>
      </td>
    </tr>
  `;

  const searchInput = document.getElementById('gemini-search-input')?.value?.trim() || '';
  const statusFilter = document.getElementById('gemini-status-filter')?.value || 'الكل';

  try {
    let url = `/api/admin/gemini-fallback/logs?page=${page}&limit=25`;
    if (searchInput) url += `&search=${encodeURIComponent(searchInput)}`;
    if (statusFilter && statusFilter !== 'الكل') url += `&status=${encodeURIComponent(statusFilter)}`;

    const res = await apiCall(url);
    if (res && res.success) {
      _geminiFallbackLogsData = res.logs || [];
      renderGeminiFallbackTable(_geminiFallbackLogsData, res.total || 0, res.page || 1, res.limit || 25);
    } else {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; padding: 30px; color: #EF4444;">
            تعذر استرجاع السجلات من الخادم.
          </td>
        </tr>
      `;
    }
  } catch (err) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; padding: 30px; color: #EF4444;">
          خطأ أثناء جلب السجلات: ${err.message}
        </td>
      </tr>
    `;
  }
}

function renderGeminiFallbackTable(logs, total, page, limit) {
  const tbody = document.getElementById('gemini-logs-tbody');
  const badgeTotal = document.getElementById('gemini-logs-total-badge');
  const pageInfo = document.getElementById('gemini-page-info');
  const pageDisplay = document.getElementById('gemini-page-display');
  const btnPrev = document.getElementById('btn-gemini-prev');
  const btnNext = document.getElementById('btn-gemini-next');

  if (badgeTotal) badgeTotal.textContent = `${total} عملية مسجلة`;

  const totalPages = Math.max(1, Math.ceil(total / limit));
  if (pageInfo) pageInfo.textContent = `عرض السجلات (${logs.length} من أصل ${total}) — صفحة ${page} من ${totalPages}`;
  if (pageDisplay) pageDisplay.textContent = page;

  if (btnPrev) btnPrev.disabled = (page <= 1);
  if (btnNext) btnNext.disabled = (page >= totalPages);

  if (!logs || logs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="10" style="text-align: center; padding: 50px 20px; color: var(--text-muted);">
          <div style="font-size: 40px; margin-bottom: 10px;">🛡️</div>
          <div style="font-size: 15px; font-weight: 800; color: #FFFFFF; margin-bottom: 6px;">
            لم يتم تسجيل أي حالات تعثر لـ GLM حتى الآن!
          </div>
          <div style="font-size: 12.5px; color: var(--text-muted); max-width: 460px; margin: 0 auto;">
            محرك الذكاء الاصطناعي الأساسي يعمل بكفاءة تامة، وعند حدوث أي ضغط أو نفاد للكوتة سيتدخل البديل الأول Groq (openai/gpt-oss-120b) بسرعة خارقة، يليه Google Gemini، وستظهر العمليات هنا بالثواني والتفاصيل.
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = logs.map((log, index) => {
    const rowNum = (page - 1) * limit + index + 1;
    const isSuccess = (log.status === 'SUCCESS');
    
    // Status Badge
    const statusBadge = isSuccess
      ? `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.35); font-size: 11px; padding: 3px 8px;">✅ ناجحة</span>`
      : `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.35); font-size: 11px; padding: 3px 8px;">❌ فاشلة</span>`;

    // Rescued By Engine Badge
    const modelRaw = log.gemini_model || '';
    let engineBadge = `<span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(96, 165, 250, 0.3); font-size: 11px; padding: 3px 8px;">🛡️ ${escapeHtml(modelRaw)}</span>`;
    if (modelRaw.includes('Groq')) {
      engineBadge = `<span class="badge" style="background: rgba(249, 115, 22, 0.15); color: #FB923C; border: 1px solid rgba(249, 115, 22, 0.35); font-size: 11px; padding: 3px 8px; font-weight: 700;">⚡ ${escapeHtml(modelRaw)}</span>`;
    } else if (modelRaw.includes('Gemini') || modelRaw.includes('gemini')) {
      engineBadge = `<span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(96, 165, 250, 0.35); font-size: 11px; padding: 3px 8px; font-weight: 700;">🛡️ ${escapeHtml(modelRaw)}</span>`;
    }

    // Trigger Reason Style
    let triggerStyle = 'background: rgba(245, 158, 11, 0.15); color: #F59E0B; border: 1px solid rgba(245, 158, 11, 0.3);';
    if (log.trigger_reason && (log.trigger_reason.includes('1113') || log.trigger_reason.includes('رصيد'))) {
      triggerStyle = 'background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.3);';
    } else if (log.trigger_reason && log.trigger_reason.includes('Timeout')) {
      triggerStyle = 'background: rgba(249, 115, 22, 0.15); color: #FB923C; border: 1px solid rgba(249, 115, 22, 0.3);';
    }

    // Latency badge
    const latVal = log.latency_seconds || 0.0;
    const latencyBadge = `<span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(96, 165, 250, 0.3); font-size: 11.5px; padding: 2px 8px; font-family: monospace;">⚡ ${latVal} ث</span>`;

    // Tokens formatted
    const totalTokens = log.total_tokens || (log.prompt_tokens + log.completion_tokens) || 0;
    const tokensDisplay = `<span style="font-size: 11.5px; color: var(--text-muted);" title="Prompt: ${log.prompt_tokens || 0} | Output: ${log.completion_tokens || 0}">${totalTokens.toLocaleString('ar-EG')} توكن</span>`;

    // Format Date
    let dateStr = log.created_at || '';
    if (dateStr) {
      try {
        const d = new Date(dateStr);
        dateStr = d.toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'medium' });
      } catch (e) {}
    }

    const titleStr = log.article_title || 'خبر صحفي';
    const cleanTitle = titleStr.length > 45 ? titleStr.slice(0, 45) + '...' : titleStr;

    return `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.03)'" onmouseout="this.style.background='transparent'">
        <td style="padding: 12px; font-weight: 700; color: var(--text-muted);">${rowNum}</td>
        <td style="padding: 12px; white-space: nowrap; font-size: 12px; color: #CBD5E1;">${dateStr}</td>
        <td style="padding: 12px; font-weight: 700; color: #FFFFFF; white-space: nowrap;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span>👤</span>
            <span>${escapeHtml(log.reporter_name || 'محرر الجريدة')}</span>
          </div>
        </td>
        <td style="padding: 12px; font-weight: 600; color: #F1F5F9; max-width: 260px;" title="${escapeHtml(titleStr)}">
          ${escapeHtml(cleanTitle)}
        </td>
        <td style="padding: 12px; white-space: nowrap;">
          ${engineBadge}
        </td>
        <td style="padding: 12px; max-width: 240px;">
          <span class="badge" style="${triggerStyle} font-size: 11px; padding: 3px 8px; display: inline-block; white-space: normal; line-height: 1.4;">
            ${escapeHtml(log.trigger_reason || 'تعثر GLM')}
          </span>
        </td>
        <td style="padding: 12px; white-space: nowrap;">${latencyBadge}</td>
        <td style="padding: 12px; white-space: nowrap;">${tokensDisplay}</td>
        <td style="padding: 12px; white-space: nowrap;">${statusBadge}</td>
        <td style="padding: 12px; text-align: center; white-space: nowrap;">
          <button type="button" class="btn btn-secondary" onclick="showGeminiFallbackDetails(${log.id})" style="padding: 4px 10px; font-size: 11.5px; border-radius: 6px;">
            🔍 تفاصيل
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function showGeminiFallbackDetails(logId) {
  const log = _geminiFallbackLogsData.find(l => l.id === logId);
  if (!log) return;

  const idEl = document.getElementById('modal-gemini-id');
  const bodyEl = document.getElementById('modal-gemini-body');
  if (idEl) idEl.textContent = `سجل رقم #${log.id}`;

  const isSuccess = (log.status === 'SUCCESS');

  let dateStr = log.created_at || '';
  try {
    dateStr = new Date(dateStr).toLocaleString('ar-EG', { dateStyle: 'full', timeStyle: 'medium' });
  } catch (e) {}

  if (bodyEl) {
    bodyEl.innerHTML = `
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; background: rgba(0,0,0,0.25); padding: 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.06);">
        <div>
          <span style="font-size: 11.5px; color: var(--text-muted); display: block;">صاحب الخبر (المحرر):</span>
          <strong style="color: #fff; font-size: 13.5px;">👤 ${escapeHtml(log.reporter_name || 'غير محدد')}</strong>
        </div>
        <div>
          <span style="font-size: 11.5px; color: var(--text-muted); display: block;">توقيت العملية:</span>
          <span style="color: #CBD5E1; font-size: 12.5px;">🕒 ${dateStr}</span>
        </div>
      </div>

      <div style="margin-bottom: 12px;">
        <span style="font-size: 11.5px; color: var(--text-muted); display: block; margin-bottom: 4px;">موضوع / عنوان المقال:</span>
        <div style="padding: 10px 12px; background: rgba(255,255,255,0.04); border-radius: 8px; border-right: 3px solid #60A5FA; color: #FFFFFF; font-weight: 700;">
          ${escapeHtml(log.article_title || 'خبر صحفي')}
        </div>
      </div>

      <div style="margin-bottom: 12px;">
        <span style="font-size: 11.5px; color: var(--text-muted); display: block; margin-bottom: 4px;">المشكلة التي أدت للجوء للبديل (GLM Trigger Cause):</span>
        <div style="padding: 10px 12px; background: rgba(245, 158, 11, 0.1); border-radius: 8px; border-right: 3px solid #F59E0B; color: #FCD34D; font-weight: 600; font-size: 12.5px;">
          ⚠️ ${escapeHtml(log.trigger_reason || 'تعثر غير معروف')}
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 14px; text-align: center;">
        <div style="background: rgba(255,255,255,0.03); padding: 8px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05);">
          <span style="font-size: 11px; color: var(--text-muted); display: block;">النموذج الأساسي</span>
          <strong style="color: #94A3B8; font-size: 12px;">${escapeHtml(log.glm_model || 'glm-4.7-flash')}</strong>
        </div>
        <div style="background: rgba(59, 130, 246, 0.08); padding: 8px; border-radius: 8px; border: 1px solid rgba(59, 130, 246, 0.2);">
          <span style="font-size: 11px; color: #93C5FD; display: block;">النموذج البديل المنقذ</span>
          <strong style="color: #60A5FA; font-size: 12px;">🛡️ ${escapeHtml(log.gemini_model || 'gemini-3.6-flash')}</strong>
        </div>
        <div style="background: rgba(16, 185, 129, 0.08); padding: 8px; border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.2);">
          <span style="font-size: 11px; color: #6EE7B7; display: block;">سرعة الاستجابة</span>
          <strong style="color: #10B981; font-size: 13px;">⚡ ${log.latency_seconds || 0.0} ثانية</strong>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 14px; text-align: center;">
        <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 8px;">
          <span style="font-size: 10.5px; color: var(--text-muted); display: block;">توكنات الإدخال</span>
          <span style="color: #E2E8F0; font-size: 12px; font-weight: 700;">${(log.prompt_tokens || 0).toLocaleString('ar-EG')}</span>
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 8px;">
          <span style="font-size: 10.5px; color: var(--text-muted); display: block;">توكنات الإخراج</span>
          <span style="color: #E2E8F0; font-size: 12px; font-weight: 700;">${(log.completion_tokens || 0).toLocaleString('ar-EG')}</span>
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 8px;">
          <span style="font-size: 10.5px; color: var(--text-muted); display: block;">إجمالي التوكنات</span>
          <span style="color: #60A5FA; font-size: 12px; font-weight: 800;">${(log.total_tokens || 0).toLocaleString('ar-EG')}</span>
        </div>
      </div>

      ${log.error_details ? `
        <div style="margin-top: 10px;">
          <span style="font-size: 11.5px; color: #EF4444; display: block; margin-bottom: 4px;">تفاصيل الخطأ إن وجد:</span>
          <pre style="background: rgba(0,0,0,0.4); padding: 10px; border-radius: 8px; font-size: 11px; color: #FCA5A5; overflow-x: auto; white-space: pre-wrap; word-break: break-all;">${escapeHtml(log.error_details)}</pre>
        </div>
      ` : ''}
    `;
  }

  const modal = document.getElementById('modal-gemini-details');
  if (modal) modal.style.display = 'flex';
}

function closeGeminiModal() {
  const modal = document.getElementById('modal-gemini-details');
  if (modal) modal.style.display = 'none';
}

async function testGeminiFallbackPing() {
  const btn = document.getElementById('btn-test-gemini-ping');
  const icon = document.getElementById('gemini-ping-icon');
  const text = document.getElementById('gemini-ping-text');
  const banner = document.getElementById('gemini-test-banner');

  if (btn) btn.disabled = true;
  if (icon) icon.textContent = '⏳';
  if (text) text.textContent = 'جاري قياس زمن الاستجابة...';
  if (banner) banner.style.display = 'none';

  try {
    const res = await apiCall('/api/admin/gemini-fallback/test', 'POST');
    if (res && res.success) {
      if (banner) {
        banner.style.display = 'block';
        banner.style.background = 'rgba(16, 185, 129, 0.15)';
        banner.style.border = '1px solid rgba(16, 185, 129, 0.35)';
        banner.style.color = '#10B981';
        banner.innerHTML = `🟢 <strong>نجاح الفحص:</strong> محرك Google Gemini (${res.model}) جاهز بنسبة 100%، وسرعة الاستجابة فائقة (${res.latency_seconds} ثانية) ⚡`;
      }
      showToast(`✅ اتصال Gemini ناجح وسريع جداً: ${res.latency_seconds} ثانية`, 'success');
    } else {
      if (banner) {
        banner.style.display = 'block';
        banner.style.background = 'rgba(239, 68, 68, 0.15)';
        banner.style.border = '1px solid rgba(239, 68, 68, 0.35)';
        banner.style.color = '#EF4444';
        banner.innerHTML = `❌ <strong>تعثر الفحص:</strong> ${res.message || 'فشل الاتصال بمحرك Gemini'}`;
      }
      showToast('تعثر فحص Gemini: ' + (res.message || ''), 'error');
    }
  } catch (err) {
    if (banner) {
      banner.style.display = 'block';
      banner.style.background = 'rgba(239, 68, 68, 0.15)';
      banner.style.border = '1px solid rgba(239, 68, 68, 0.35)';
      banner.style.color = '#EF4444';
      banner.innerHTML = `❌ <strong>خطأ في الاتصال:</strong> ${err.message}`;
    }
    showToast('خطأ: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.textContent = '🛡️';
    if (text) text.textContent = 'فحص Gemini';
  }
}

async function testGroqFallbackPing() {
  const btn = document.getElementById('btn-test-groq-ping');
  const icon = document.getElementById('groq-ping-icon');
  const text = document.getElementById('groq-ping-text');
  const banner = document.getElementById('gemini-test-banner');

  if (btn) btn.disabled = true;
  if (icon) icon.textContent = '⏳';
  if (text) text.textContent = 'جاري قياس استجابة Groq...';
  if (banner) banner.style.display = 'none';

  try {
    const res = await apiCall('/api/admin/groq-fallback/test', 'POST');
    if (res && res.success) {
      if (banner) {
        banner.style.display = 'block';
        banner.style.background = 'rgba(249, 115, 22, 0.15)';
        banner.style.border = '1px solid rgba(249, 115, 22, 0.35)';
        banner.style.color = '#FB923C';
        banner.innerHTML = `⚡ <strong>نجاح فحص Groq:</strong> محرك البديل الأول Groq (${res.model}) جاهز بنسبة 100%، وسرعة الاستجابة خارقة (${res.latency_seconds} ثانية)!`;
      }
      showToast(`⚡ اتصال Groq 120B ناجح وخارق: ${res.latency_seconds} ثانية`, 'success');
    } else {
      if (banner) {
        banner.style.display = 'block';
        banner.style.background = 'rgba(239, 68, 68, 0.15)';
        banner.style.border = '1px solid rgba(239, 68, 68, 0.35)';
        banner.style.color = '#EF4444';
        banner.innerHTML = `❌ <strong>تعثر الفحص:</strong> ${res.message || 'فشل الاتصال بمحرك Groq'}`;
      }
      showToast('تعثر فحص Groq: ' + (res.message || ''), 'error');
    }
  } catch (err) {
    if (banner) {
      banner.style.display = 'block';
      banner.style.background = 'rgba(239, 68, 68, 0.15)';
      banner.style.border = '1px solid rgba(239, 68, 68, 0.35)';
      banner.style.color = '#EF4444';
      banner.innerHTML = `❌ <strong>خطأ في الاتصال:</strong> ${err.message}`;
    }
    showToast('خطأ: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.textContent = '⚡';
    if (text) text.textContent = 'فحص Groq (120B)';
  }
}

function initGeminiFallbackEvents() {
  document.getElementById('btn-refresh-gemini-logs')?.addEventListener('click', () => {
    loadGeminiFallbackStats();
    loadGeminiFallbackLogs(1);
    showToast('🔄 تم تحديث سجلات وإحصائيات البدائل', 'info');
  });

  document.getElementById('gemini-search-input')?.addEventListener('input', () => {
    clearTimeout(_geminiFallbackSearchTimeout);
    _geminiFallbackSearchTimeout = setTimeout(() => {
      loadGeminiFallbackLogs(1);
    }, 350);
  });

  document.getElementById('gemini-status-filter')?.addEventListener('change', () => {
    loadGeminiFallbackLogs(1);
  });

  document.getElementById('btn-test-groq-ping')?.addEventListener('click', () => {
    testGroqFallbackPing();
  });

  document.getElementById('btn-test-gemini-ping')?.addEventListener('click', () => {
    testGeminiFallbackPing();
  });

  document.getElementById('btn-gemini-prev')?.addEventListener('click', () => {
    if (_geminiFallbackCurrentPage > 1) {
      loadGeminiFallbackLogs(_geminiFallbackCurrentPage - 1);
    }
  });

  document.getElementById('btn-gemini-next')?.addEventListener('click', () => {
    loadGeminiFallbackLogs(_geminiFallbackCurrentPage + 1);
  });
}

// Auto-initialize events
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initGeminiFallbackEvents);
} else {
  initGeminiFallbackEvents();
}

window.loadGeminiFallbackStats = loadGeminiFallbackStats;
window.loadGeminiFallbackLogs = loadGeminiFallbackLogs;
window.showGeminiFallbackDetails = showGeminiFallbackDetails;
window.closeGeminiModal = closeGeminiModal;
window.testGeminiFallbackPing = testGeminiFallbackPing;
window.testGroqFallbackPing = testGroqFallbackPing;

// =============================================================================
// FACEBOOK COMMAND CENTER & COMMERCIAL HUB CONTROLLER
// =============================================================================

let _fbCurrentFilter = 'ALL';
let _fbCurrentPage = 1;
let _fbSearchTimeout = null;
let _currentEditFbPostId = null;

async function loadFacebookHub() {
  await Promise.all([
    loadFacebookOverview(),
    loadFacebookPosts(1)
  ]);
}

async function loadFacebookOverview() {
  try {
    const res = await apiCall('/api/admin/facebook/overview', 'GET');
    if (!res || !res.success) return;

    const page = res.page || {};
    const stats = res.stats || {};

    // Page Connection Status
    const chip = document.getElementById('fb-connection-chip');
    if (chip) {
      if (page.connected) {
        chip.className = 'fb-badge-live';
        chip.textContent = `متصل بـ صفحة ${page.name || 'تحت الضوء'}`;
      } else {
        chip.className = 'badge';
        chip.style.background = 'rgba(239, 68, 68, 0.2)';
        chip.style.color = '#EF4444';
        chip.textContent = 'غير متصل ⚠️';
      }
    }

    // Followers
    const followers = page.followers_count || 11657;
    const fChip = document.getElementById('fb-followers-chip');
    if (fChip) fChip.textContent = `${Number(followers).toLocaleString()} متابع`;

    const statFollowers = document.getElementById('fb-stat-followers');
    if (statFollowers) statFollowers.textContent = Number(followers).toLocaleString();

    // Paid Stats
    const statPaid = document.getElementById('fb-stat-paid');
    if (statPaid) statPaid.textContent = `${Number(stats.paid_amount || 0).toLocaleString()} ج.م`;

    const statPaidCount = document.getElementById('fb-stat-paid-count');
    if (statPaidCount) statPaidCount.textContent = `${stats.paid_posts || 0} منشور مسدد بالكامل`;

    // Unpaid Stats
    const statUnpaid = document.getElementById('fb-stat-unpaid');
    if (statUnpaid) statUnpaid.textContent = `${Number(stats.unpaid_amount || 0).toLocaleString()} ج.م`;

    const statUnpaidCount = document.getElementById('fb-stat-unpaid-count');
    if (statUnpaidCount) statUnpaidCount.textContent = `${stats.unpaid_posts || 0} منشور بانتظار السداد`;

    // Total Live Engagement
    const totalEngagement = (stats.total_likes || 0) + (stats.total_comments || 0) + (stats.total_shares || 0);
    const statEngagement = document.getElementById('fb-stat-engagement');
    if (statEngagement) statEngagement.textContent = Number(totalEngagement).toLocaleString();

    const statEngBreakdown = document.getElementById('fb-stat-engagement-breakdown');
    if (statEngBreakdown) {
      statEngBreakdown.textContent = `${stats.total_likes || 0} 👍 • ${stats.total_comments || 0} 💬 • ${stats.total_shares || 0} 🔄`;
    }

  } catch (err) {
    console.error('Error loading Facebook overview:', err);
  }
}

async function loadFacebookPosts(page = 1) {
  _fbCurrentPage = page;
  const tbody = document.getElementById('fb-posts-tbody');
  if (tbody) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; padding: 36px; color: var(--text-muted);">
          <div class="spinner" style="width: 28px; height: 28px; margin: 0 auto 10px;"></div>
          جاري جلب المنشورات من قاعدة البيانات...
        </td>
      </tr>
    `;
  }

  try {
    const searchVal = (document.getElementById('fb-posts-search')?.value || '').trim();
    const query = new URLSearchParams();
    if (_fbCurrentFilter && _fbCurrentFilter !== 'ALL') {
      query.append('payment_status', _fbCurrentFilter);
    }
    if (searchVal) {
      query.append('search', searchVal);
    }
    query.append('page', page);
    query.append('limit', 25);

    const res = await apiCall(`/api/admin/facebook/posts?${query.toString()}`, 'GET');
    if (!res || !res.success) {
      throw new Error(res?.detail || 'فشل جلب المنشورات');
    }

    const posts = res.posts || [];
    const total = res.total || 0;

    // Update Counter & Pagination
    const counterEl = document.getElementById('fb-posts-counter');
    if (counterEl) {
      const from = total === 0 ? 0 : (page - 1) * 25 + 1;
      const to = Math.min(page * 25, total);
      counterEl.textContent = `عرض ${from} إلى ${to} من إجمالي ${total} منشور`;
    }

    const pageEl = document.getElementById('fb-page-number');
    if (pageEl) pageEl.textContent = page;

    const prevBtn = document.getElementById('fb-btn-prev-page');
    if (prevBtn) prevBtn.disabled = (page <= 1);

    const nextBtn = document.getElementById('fb-btn-next-page');
    if (nextBtn) nextBtn.disabled = (page * 25 >= total);

    if (posts.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; padding: 48px; color: var(--text-muted);">
            <div style="font-size: 32px; margin-bottom: 10px;">📭</div>
            <div style="font-weight: 700; font-size: 15px; color: var(--text-secondary);">لا توجد منشورات مطابقة لهذا الفلتر</div>
            <div style="font-size: 12.5px; margin-top: 4px;">يمكنك مزامنة منشورات الصفحة أو إضافة منشور جديد الآن.</div>
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = posts.map(p => {
      const imgHtml = p.image_url 
        ? `<img src="${escapeHtml(p.image_url)}" class="fb-post-thumb" onerror="this.src='/favicon.ico'" />`
        : `<div class="fb-post-thumb" style="display:flex;align-items:center;justify-content:center;background:rgba(24,119,242,0.15);color:#1877F2;font-size:18px;">📘</div>`;

      // Status badge
      let badgeClass = 'editorial';
      let badgeLabel = 'خبر عام 📰';
      if (p.payment_status === 'PAID') {
        badgeClass = 'paid';
        badgeLabel = 'مدفوع 💰';
      } else if (p.payment_status === 'UNPAID') {
        badgeClass = 'unpaid';
        badgeLabel = 'معلق ⏳';
      } else if (p.payment_status === 'FREE') {
        badgeClass = 'editorial';
        badgeLabel = 'مجاملة 🎁';
      }

      const clientDisplay = p.client_name 
        ? `<div style="font-weight: 700; color: #fff;">${escapeHtml(p.client_name)}</div>`
        : `<div style="color: var(--text-muted); font-size: 12px;">جريدة تحت الضوء</div>`;

      const snippet = p.post_message ? escapeHtml(p.post_message.substring(0, 110)) + (p.post_message.length > 110 ? '...' : '') : 'منشور صورة/رابط';

      const amountDisplay = p.amount && p.amount > 0
        ? `<span style="font-family: var(--font-code); font-weight: 800; color: ${p.payment_status === 'PAID' ? '#10B981' : '#F59E0B'};">${p.amount} ج.م</span>`
        : `<span style="color: var(--text-muted);">-</span>`;

      const pubDate = p.published_at ? p.published_at.substring(0, 16).replace('T', ' ') : '-';

      const rawPostId = p.fb_post_id || p.id;
      const postUrl = p.post_url || `https://www.facebook.com/${rawPostId}`;

      return `
        <tr>
          <td>${imgHtml}</td>
          <td>
            <div style="font-size: 13px; line-height: 1.5; color: var(--text-primary); font-weight: 500;" title="${escapeHtml(p.post_message || '')}">
              ${snippet}
            </div>
            ${p.payment_notes ? `<div style="font-size: 11.5px; color: var(--accent-gold); margin-top: 4px;">📝 ${escapeHtml(p.payment_notes)}</div>` : ''}
          </td>
          <td>${clientDisplay}</td>
          <td>
            <span class="fb-pay-badge ${badgeClass}" onclick="openFbPaymentModal('${p.id}', '${p.payment_status}', ${p.amount || 0}, '${escapeHtml(p.payment_notes || '')}')" title="انقر لتعديل الحالة المالية">
              ${badgeLabel} ✎
            </span>
          </td>
          <td>${amountDisplay}</td>
          <td>
            <span class="fb-engagement-chip">
              <span>👍 ${p.likes_count || 0}</span>
              <span>💬 ${p.comments_count || 0}</span>
              <span>🔄 ${p.shares_count || 0}</span>
            </span>
          </td>
          <td style="font-size: 11.5px; color: var(--text-muted); font-family: var(--font-code); white-space: nowrap;">
            ${pubDate}
            <div style="color: var(--text-secondary); font-size: 11px;">${escapeHtml(p.published_by_name || '')}</div>
          </td>
          <td style="text-align: center; white-space: nowrap;">
            <div style="display: flex; gap: 6px; justify-content: center;">
              <a href="${postUrl}" target="_blank" class="btn btn-secondary" style="padding: 5px 8px; font-size: 11.5px;" title="عرض المنشور على فيسبوك">
                🔗
              </a>
              <button type="button" class="btn btn-secondary" style="padding: 5px 8px; font-size: 11.5px;" onclick="openFbPaymentModal('${p.id}', '${p.payment_status}', ${p.amount || 0}, '${escapeHtml(p.payment_notes || '')}')" title="تعديل الحالة المالية">
                💳
              </button>
              <button type="button" class="crm-btn-delete" style="padding: 5px 8px; font-size: 11.5px;" onclick="deleteFbPostRecord('${rawPostId}')" title="حذف المنشور">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    console.error('Error loading Facebook posts:', err);
    if (tbody) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" style="text-align: center; padding: 30px; color: #EF4444;">
            تعذر تحميل منشورات فيسبوك: ${err.message}
          </td>
        </tr>
      `;
    }
  }
}

function filterFbPosts(filterType) {
  _fbCurrentFilter = filterType;
  document.querySelectorAll('.fb-filter-btn').forEach(btn => {
    if (btn.getAttribute('data-fb-filter') === filterType) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
  loadFacebookPosts(1);
}

function debounceFbSearch() {
  clearTimeout(_fbSearchTimeout);
  _fbSearchTimeout = setTimeout(() => {
    loadFacebookPosts(1);
  }, 300);
}

function changeFbPage(delta) {
  loadFacebookPosts(_fbCurrentPage + delta);
}

function toggleFbQuickPublish(show) {
  const box = document.getElementById('fb-quick-publish-box');
  if (box) {
    box.style.display = show ? 'block' : 'none';
    if (show) {
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.getElementById('fb-quick-message')?.focus();
    }
  }
}

async function executeFbQuickPublish() {
  const msgInput = document.getElementById('fb-quick-message');
  const imgInput = document.getElementById('fb-quick-image');
  const linkInput = document.getElementById('fb-quick-link');
  const statusSelect = document.getElementById('fb-quick-payment-status');
  const amountInput = document.getElementById('fb-quick-amount');
  const clientInput = document.getElementById('fb-quick-client');
  const notesInput = document.getElementById('fb-quick-notes');
  const submitBtn = document.getElementById('btn-fb-submit-publish');

  const message = (msgInput?.value || '').trim();
  if (!message) {
    showToast('يرجى كتابة نص المنشور 📝', 'warning');
    return;
  }

  const payload = {
    message: message,
    image_url: (imgInput?.value || '').trim(),
    link: (linkInput?.value || '').trim(),
    payment_status: statusSelect?.value || 'EDITORIAL',
    amount: parseFloat(amountInput?.value || 0) || 0.0,
    client_name: (clientInput?.value || '').trim(),
    payment_notes: (notesInput?.value || '').trim()
  };

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span>⏳ جاري النشر على فيسبوك...</span>`;
  }

  try {
    const res = await apiCall('/api/admin/facebook/publish', 'POST', payload);
    if (!res || !res.success) {
      throw new Error(res?.detail || res?.message || 'فشل نشر المنشور');
    }

    showToast('🎉 تم نشر المنشور على صفحة فيسبوك بنجاح! 🚀', 'success');
    if (msgInput) msgInput.value = '';
    if (imgInput) imgInput.value = '';
    if (linkInput) linkInput.value = '';
    if (amountInput) amountInput.value = '';
    if (clientInput) clientInput.value = '';
    if (notesInput) notesInput.value = '';

    toggleFbQuickPublish(false);
    await Promise.all([
      loadFacebookOverview(),
      loadFacebookPosts(1)
    ]);
  } catch (err) {
    console.error('Publish error:', err);
    showToast('فشل النشر على فيسبوك: ' + err.message, 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>🚀 نشر المنشور على فيسبوك الآن</span>`;
    }
  }
}

function openFbPaymentModal(postId, status, amount, notes) {
  _currentEditFbPostId = postId;
  const modal = document.getElementById('modal-edit-facebook-payment');
  if (!modal) return;

  const statusSelect = document.getElementById('modal-fb-status-select');
  const amountInput = document.getElementById('modal-fb-amount-input');
  const notesInput = document.getElementById('modal-fb-notes-input');

  if (statusSelect) statusSelect.value = status || 'EDITORIAL';
  if (amountInput) amountInput.value = (amount && amount > 0) ? amount : '';
  if (notesInput) notesInput.value = notes || '';

  modal.style.display = 'flex';
}

function closeFbPaymentModal() {
  const modal = document.getElementById('modal-edit-facebook-payment');
  if (modal) modal.style.display = 'none';
  _currentEditFbPostId = null;
}

async function saveFbPaymentModal() {
  if (!_currentEditFbPostId) return;

  const statusSelect = document.getElementById('modal-fb-status-select');
  const amountInput = document.getElementById('modal-fb-amount-input');
  const notesInput = document.getElementById('modal-fb-notes-input');

  const payload = {
    payment_status: statusSelect?.value || 'EDITORIAL',
    amount: parseFloat(amountInput?.value || 0) || 0.0,
    payment_notes: (notesInput?.value || '').trim()
  };

  try {
    const res = await apiCall(`/api/admin/facebook/posts/${_currentEditFbPostId}/payment`, 'PUT', payload);
    if (!res || !res.success) {
      throw new Error(res?.detail || 'فشل تحديث الحالة المالية');
    }

    showToast('✅ تم حفظ التعديل المالي بنجاح', 'success');
    closeFbPaymentModal();
    await Promise.all([
      loadFacebookOverview(),
      loadFacebookPosts(_fbCurrentPage)
    ]);
  } catch (err) {
    showToast('خطأ أثناء التحديث المالي: ' + err.message, 'error');
  }
}

async function deleteFbPostRecord(postId) {
  if (!confirm('هل أنت متأكد من حذف هذا المنشور من النظام ومن صفحة فيسبوك؟')) {
    return;
  }

  try {
    const res = await apiCall(`/api/admin/facebook/posts/${postId}?delete_from_fb=true`, 'DELETE');
    if (!res || !res.success) {
      throw new Error(res?.detail || 'فشل الحذف');
    }

    showToast('🗑️ تم حذف المنشور بنجاح', 'info');
    await Promise.all([
      loadFacebookOverview(),
      loadFacebookPosts(_fbCurrentPage)
    ]);
  } catch (err) {
    showToast('تعذر حذف المنشور: ' + err.message, 'error');
  }
}

async function syncFbEngagement() {
  const btn = document.getElementById('btn-fb-sync');
  const icon = document.getElementById('fb-sync-icon');

  if (btn) btn.disabled = true;
  if (icon) icon.classList.add('spinning');

  try {
    showToast('جاري مزامنة المنشورات والتفاعل الحي من فيسبوك... ⏳', 'info');
    const res = await apiCall('/api/admin/facebook/sync?limit=30', 'POST');
    if (!res || !res.success) {
      throw new Error(res?.detail || 'فشلت المزامنة');
    }

    showToast(`✅ تمت المزامنة بنجاح! تم تحديث ${res.synced_count || 0} منشور بالرؤى الحية 👍`, 'success');
    await Promise.all([
      loadFacebookOverview(),
      loadFacebookPosts(1)
    ]);
  } catch (err) {
    showToast('فشلت مزامنة فيسبوك: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.classList.remove('spinning');
  }
}

function initFacebookHubEvents() {
  document.getElementById('btn-fb-sync')?.addEventListener('click', syncFbEngagement);
  document.getElementById('btn-fb-toggle-create')?.addEventListener('click', () => {
    const box = document.getElementById('fb-quick-publish-box');
    const isShown = box && box.style.display !== 'none';
    toggleFbQuickPublish(!isShown);
  });
}

// Auto-init events on DOM load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initFacebookHubEvents);
} else {
  initFacebookHubEvents();
}

window.loadFacebookHub = loadFacebookHub;
window.filterFbPosts = filterFbPosts;
window.debounceFbSearch = debounceFbSearch;
window.changeFbPage = changeFbPage;
window.toggleFbQuickPublish = toggleFbQuickPublish;
window.executeFbQuickPublish = executeFbQuickPublish;
window.openFbPaymentModal = openFbPaymentModal;
window.closeFbPaymentModal = closeFbPaymentModal;
window.saveFbPaymentModal = saveFbPaymentModal;
window.deleteFbPostRecord = deleteFbPostRecord;
window.syncFbEngagement = syncFbEngagement;

// =============================================================================
// AI POSTER STUDIO (استوديو البوسترات الصحفية الذكي v1.0)
// =============================================================================
let posterSelectedFile = null;
let currentGeneratedPoster = null;

function initPosterStudio() {
  updatePosterStudioEgyptDate();

  if (window._posterStudioInitialized) return;
  window._posterStudioInitialized = true;

  const dropzone = document.getElementById('poster-dropzone');
  const fileInput = document.getElementById('poster-file-input');
  const emptyView = document.getElementById('poster-dropzone-empty');
  const previewView = document.getElementById('poster-dropzone-preview');
  const thumbPreview = document.getElementById('poster-thumb-preview');
  const fileNameEl = document.getElementById('poster-file-name');
  const fileSizeEl = document.getElementById('poster-file-size');
  const btnRemoveFile = document.getElementById('btn-remove-poster-file');
  const btnGenerate = document.getElementById('btn-generate-ai-poster');
  const titleInput = document.getElementById('poster-input-title');
  const categorySelect = document.getElementById('poster-input-category');
  const urlInput = document.getElementById('poster-input-url');
  const toggleRemovePerson = document.getElementById('poster-toggle-remove-person');
  const btnReset = document.getElementById('btn-reset-poster-form');
  const btnCopyLink = document.getElementById('btn-copy-poster-link');

  // 1. Dropzone Click & Change
  if (dropzone && fileInput) {
    dropzone.addEventListener('click', (e) => {
      if (e.target.closest('#btn-remove-poster-file')) return;
      fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (file) handlePosterFileSelection(file);
    });

    // Drag & Drop
    ['dragenter', 'dragover'].forEach(evt => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.style.borderColor = 'var(--accent-gold)';
        dropzone.style.background = 'rgba(245, 158, 11, 0.08)';
      });
    });

    ['dragleave', 'drop'].forEach(evt => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.style.borderColor = 'rgba(245, 158, 11, 0.35)';
        dropzone.style.background = 'rgba(0,0,0,0.25)';
      });
    });

    dropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const file = dt.files?.[0];
      if (file) {
        if (!file.type.startsWith('image/')) {
          showToast('يرجى اختيار ملف صورة صالح (PNG, JPG, WEBP)', 'warning');
          return;
        }
        handlePosterFileSelection(file);
      }
    });
  }

  function handlePosterFileSelection(file) {
    if (file.size > 20 * 1024 * 1024) {
      showToast('حجم الصورة كبير جداً، الحد الأقصى المسموح هو 20 ميجابايت', 'warning');
      return;
    }
    posterSelectedFile = file;
    if (fileNameEl) fileNameEl.textContent = file.name;
    if (fileSizeEl) fileSizeEl.textContent = `${(file.size / 1024).toFixed(1)} KB`;

    const reader = new FileReader();
    reader.onload = (ev) => {
      if (thumbPreview) thumbPreview.src = ev.target.result;
      if (emptyView) emptyView.style.display = 'none';
      if (previewView) previewView.style.display = 'flex';
    };
    reader.readAsDataURL(file);
  }

  // 2. Remove File
  if (btnRemoveFile) {
    btnRemoveFile.addEventListener('click', (e) => {
      e.stopPropagation();
      posterSelectedFile = null;
      if (fileInput) fileInput.value = '';
      if (thumbPreview) thumbPreview.src = '';
      if (previewView) previewView.style.display = 'none';
      if (emptyView) emptyView.style.display = 'block';
    });
  }

  // 2.1 Paste Image from Clipboard Button
  const btnPasteImage = document.getElementById('btn-paste-poster-image');
  if (btnPasteImage) {
    btnPasteImage.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        if (!navigator.clipboard || !navigator.clipboard.read) {
          showToast('المتصفح يطلب استخدام اختصار (Ctrl + V) للصق الصورة مباشرة 📋', 'info');
          return;
        }

        const items = await navigator.clipboard.read();
        let imageFound = false;

        for (const item of items) {
          const imageType = item.types.find(t => t.startsWith('image/'));
          if (imageType) {
            const blob = await item.getType(imageType);
            const ext = imageType.split('/')[1] || 'png';
            const file = new File([blob], `pasted_news_${Date.now()}.${ext}`, { type: imageType });
            handlePosterFileSelection(file);
            showToast('تم لصق الصورة من الحافظة بنجاح! 📋✨', 'success');
            imageFound = true;
            break;
          }
        }

        if (!imageFound) {
          showToast('لم يتم العثور على صورة في الحافظة. انسخ صورة أولاً ثم اضغط لصق 📸', 'warning');
        }
      } catch (err) {
        console.warn('Clipboard read error:', err);
        showToast('اضغط في الصفحة واضغط (Ctrl + V) مباشرة للصق الصورة من الكيبورد 📋', 'info');
      }
    });
  }

  // 2.2 Keyboard Shortcut (Ctrl + V) for Image Paste
  if (!window._posterPasteListenerAdded) {
    window._posterPasteListenerAdded = true;
    document.addEventListener('paste', async (e) => {
      if (State.currentView !== 'poster-studio') return;

      // 1. Check e.clipboardData.files
      const files = e.clipboardData?.files;
      if (files && files.length > 0) {
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          if (file.type.startsWith('image/') || /\.(jpe?g|png|webp|gif|bmp|jfif|avif)$/i.test(file.name)) {
            e.preventDefault();
            handlePosterFileSelection(file);
            showToast('تم لصق الصورة من الحافظة بنجاح! 📋✨', 'success');
            return;
          }
        }
      }

      // 2. Check e.clipboardData.items
      const items = e.clipboardData?.items;
      if (items && items.length > 0) {
        for (let i = 0; i < items.length; i++) {
          if (items[i].type && items[i].type.startsWith('image/')) {
            e.preventDefault();
            const blob = items[i].getAsFile();
            if (blob) {
              const ext = blob.type.split('/')[1] || 'png';
              const file = new File([blob], `pasted_news_${Date.now()}.${ext}`, { type: blob.type });
              handlePosterFileSelection(file);
              showToast('تم لصق الصورة من الحافظة بنجاح! 📋✨', 'success');
              return;
            }
          }
        }
      }

      // 3. Check for HTML snippet with <img> tag
      try {
        const html = e.clipboardData?.getData('text/html');
        if (html) {
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, 'text/html');
          const img = doc.querySelector('img');
          if (img && img.src && (img.src.startsWith('http') || img.src.startsWith('data:image/'))) {
            e.preventDefault();
            const fetchRes = await fetch(img.src);
            const blob = await fetchRes.blob();
            const ext = blob.type.split('/')[1] || 'png';
            const file = new File([blob], `pasted_news_${Date.now()}.${ext}`, { type: blob.type });
            handlePosterFileSelection(file);
            showToast('تم استيراد ولصق الصورة بنجاح! 📋✨', 'success');
            return;
          }
        }
      } catch (_) {}
    });
  }

  // 3. Generate Poster
  if (btnGenerate) {
    btnGenerate.addEventListener('click', async () => {
      const title = titleInput ? titleInput.value.trim() : '';
      if (!title) {
        showToast('يرجى كتابة عنوان الخبر أو المانشيت أولاً ✍️', 'warning');
        if (titleInput) titleInput.focus();
        return;
      }

      const category = categorySelect ? categorySelect.value.trim() : '';
      const url = urlInput ? urlInput.value.trim() : '';
      const removePerson = toggleRemovePerson ? toggleRemovePerson.checked : false;

      // Start Loading / Progress
      setPosterStudioLoading(true);

      const formData = new FormData();
      formData.append('title', title);
      if (url) formData.append('url', url);
      if (category) formData.append('category', category);
      formData.append('remove_person', removePerson ? 'true' : 'false');
      if (posterSelectedFile) {
        formData.append('image', posterSelectedFile);
      }

      try {
        updatePosterProgress(1, 'فحص وضبط النص الصحفي وتدقيق الحروف...', 25);

        const respPromise = fetch('/api/v1/poster/upload-and-generate', {
          method: 'POST',
          body: formData
        });

        // Intermediate simulated progress steps while waiting
        setTimeout(() => updatePosterProgress(2, 'معالجة أبعاد الصورة والهوية البصرية...', 55), 700);
        setTimeout(() => updatePosterProgress(3, 'تركيب الإطارات وتثبيت خاتم التاريخ المصري...', 85), 1400);

        const response = await respPromise;
        if (!response.ok) {
          const errData = await response.json().catch(() => ({ detail: 'حدث خطأ أثناء المعالجة السحابية' }));
          throw new Error(errData.detail || `خطأ سيرفر (${response.status})`);
        }

        const data = await response.json();
        updatePosterProgress(4, 'تم تدقيق الجودة 100% بنجاح!', 100);

        setTimeout(() => {
          setPosterStudioLoading(false);
          displayGeneratedPoster(data);
          showToast('تم تصميم وتوليد البوستر الصحفي بنجاح! 🎨', 'success');
        }, 400);

      } catch (err) {
        console.error('Poster generation failed:', err);
        setPosterStudioLoading(false);
        showToast(`فشل توليد البوستر: ${err.message}`, 'error');
      }
    });
  }

  // 4. Reset Form
  if (btnReset) {
    btnReset.addEventListener('click', () => {
      if (titleInput) titleInput.value = '';
      if (urlInput) urlInput.value = '';
      if (categorySelect) categorySelect.value = '';
      if (toggleRemovePerson) toggleRemovePerson.checked = false;
      if (btnRemoveFile) btnRemoveFile.click();

      // Reset preview
      const img = document.getElementById('poster-rendered-img');
      const emptyBox = document.getElementById('poster-empty-preview');
      const actions = document.getElementById('poster-actions-panel');
      const badge = document.getElementById('poster-qc-badge');

      if (img) {
        img.style.display = 'none';
        img.src = '';
      }
      if (emptyBox) emptyBox.style.display = 'block';
      if (actions) actions.style.display = 'none';
      if (badge) badge.style.display = 'none';
      currentGeneratedPoster = null;
    });
  }

  // 5. Copy Link
  if (btnCopyLink) {
    btnCopyLink.addEventListener('click', () => {
      if (!currentGeneratedPoster?.preview_url) return;
      const fullUrl = window.location.origin + currentGeneratedPoster.preview_url;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(fullUrl).then(() => {
          showToast('تم نسخ رابط البوستر إلى الحافظة 📋', 'info');
        }).catch(() => {
          prompt('انسخ الرابط التالي:', fullUrl);
        });
      } else {
        prompt('انسخ الرابط التالي:', fullUrl);
      }
    });
  }
}

function updatePosterStudioEgyptDate() {
  const dateEl = document.getElementById('poster-studio-egypt-date');
  if (!dateEl) return;
  try {
    const formatter = new Intl.DateTimeFormat('ar-EG', {
      timeZone: 'Africa/Cairo',
      day: 'numeric',
      month: 'long',
      year: 'numeric'
    });
    dateEl.textContent = formatter.format(new Date());
  } catch (e) {
    const d = new Date();
    dateEl.textContent = `${d.getDate()}/${d.getMonth()+1}/${d.getFullYear()}`;
  }
}

function setPosterStudioLoading(isLoading) {
  const btn = document.getElementById('btn-generate-ai-poster');
  const btnText = document.getElementById('poster-btn-text');
  const progressBox = document.getElementById('poster-agent-progress');

  if (btn) btn.disabled = isLoading;
  if (btnText) {
    btnText.textContent = isLoading ? 'جاري التحليل والتوليد بالذكاء الاصطناعي...' : 'توليد البوستر الصحفي المعتمد (1024×1024)';
  }
  if (progressBox) {
    progressBox.style.display = isLoading ? 'block' : 'none';
  }
}

function updatePosterProgress(step, text, percent) {
  const statusEl = document.getElementById('poster-progress-status-text');
  const stepPill = document.getElementById('poster-progress-step-pill');
  const bar = document.getElementById('poster-progress-bar');

  if (statusEl) statusEl.textContent = text;
  if (stepPill) stepPill.textContent = `مرحلة ${step} من 4`;
  if (bar) bar.style.width = `${percent}%`;
}

function displayGeneratedPoster(data) {
  currentGeneratedPoster = data;
  const emptyPreview = document.getElementById('poster-empty-preview');
  const imgEl = document.getElementById('poster-rendered-img');
  const actionsPanel = document.getElementById('poster-actions-panel');
  const qcBadge = document.getElementById('poster-qc-badge');
  const btnDownload = document.getElementById('btn-download-poster-hd');
  const btnOpenFull = document.getElementById('btn-open-full-poster');

  if (emptyPreview) emptyPreview.style.display = 'none';

  if (imgEl && data.preview_url) {
    imgEl.src = `${data.preview_url}?t=${Date.now()}`;
    imgEl.style.display = 'block';
  }

  if (qcBadge) {
    const scorePct = Math.round((data.qc_score || 1) * 100);
    qcBadge.textContent = `✓ اجتاز فحص الجودة (${scorePct}%)`;
    qcBadge.style.display = 'inline-block';
  }

  if (actionsPanel) actionsPanel.style.display = 'flex';
  if (btnDownload && data.download_url) btnDownload.href = data.download_url;
  if (btnOpenFull && data.preview_url) btnOpenFull.href = data.preview_url;
}

window.initPosterStudio = initPosterStudio;
window.displayGeneratedPoster = displayGeneratedPoster;

// =============================================================================
// SMART SURGICAL ARTICLE EDITOR (GEMINI) CONTROLLER
// =============================================================================

let _smartEditorFetchedArticle = null;
let _smartEditorInitialized = false;
let _smartEditorLastBackup = null;

function initSmartEditor() {
  if (_smartEditorInitialized) return;
  _smartEditorInitialized = true;

  const btnFetch = document.getElementById('btn-smart-edit-fetch');
  const inputUrl = document.getElementById('smart-edit-url');
  const form = document.getElementById('form-smart-edit');
  const btnCopy = document.getElementById('btn-smart-edit-copy-link');
  const btnUndo = document.getElementById('btn-smart-edit-undo');

  if (btnFetch) {
    btnFetch.addEventListener('click', handleSmartEditFetch);
  }

  if (inputUrl) {
    inputUrl.addEventListener('paste', () => {
      setTimeout(handleSmartEditFetch, 200);
    });
  }

  if (form) {
    form.addEventListener('submit', handleSmartEditSubmit);
  }

  if (btnCopy) {
    btnCopy.addEventListener('click', () => {
      const openLink = document.getElementById('smart-edit-res-open-link');
      if (openLink && openLink.href) {
        navigator.clipboard.writeText(openLink.href).then(() => {
          showToast('تم نسخ رابط المقال المحدث بنجاح! 📋', 'success');
        }).catch(() => {
          prompt('انسخ الرابط:', openLink.href);
        });
      }
    });
  }

  if (btnUndo) {
    btnUndo.addEventListener('click', handleSmartEditUndo);
  }
}

async function handleSmartEditFetch() {
  const urlInput = document.getElementById('smart-edit-url');
  const url = (urlInput?.value || '').trim();
  if (!url) {
    showToast('يرجى كتابة أو لصق رابط المقال أولاً 🔗', 'warning');
    urlInput?.focus();
    return;
  }

  const btnText = document.getElementById('smart-edit-fetch-text');
  const spinner = document.getElementById('smart-edit-fetch-spinner');
  const btnFetch = document.getElementById('btn-smart-edit-fetch');
  const previewBox = document.getElementById('smart-edit-post-preview');

  if (btnText) btnText.style.display = 'none';
  if (spinner) spinner.style.display = 'inline-block';
  if (btnFetch) btnFetch.disabled = true;

  try {
    const res = await apiCall('/api/articles/smart-edit/fetch', 'POST', { url });
    if (res.success) {
      _smartEditorFetchedArticle = res;
      if (previewBox) previewBox.style.display = 'block';

      const badgeEl = document.getElementById('smart-edit-preview-badge');
      const idEl = document.getElementById('smart-edit-preview-id');
      const linkEl = document.getElementById('smart-edit-preview-link');
      const titleEl = document.getElementById('smart-edit-preview-title');
      const snippetEl = document.getElementById('smart-edit-preview-snippet');

      if (badgeEl) {
        const isReview = res.site_type === 'review';
        badgeEl.textContent = isReview ? 'موقع الريفيو' : 'الجريدة الأصلية الرسمية';
        badgeEl.className = isReview ? 'badge badge-gold' : 'badge badge-success';
      }
      if (idEl) idEl.textContent = `ID: ${res.post_id}`;
      if (linkEl) linkEl.href = res.link;
      if (titleEl) titleEl.textContent = res.title;
      if (snippetEl) snippetEl.textContent = res.preview_text || 'تم جلب محتوى المقال بنجاح وجاهز لاستقبال تعديلات العميل.';

      showToast('تم جلب بيانات المقال بنجاح! 📄', 'success');
      document.getElementById('smart-edit-notes')?.focus();
    } else {
      showToast(res.error || 'تعذر العثور على المقال عبر الرابط المدخل', 'error');
    }
  } catch (err) {
    showToast(err.message || 'تعذر الاتصال بالسيرفر لجلب المقال', 'error');
  } finally {
    if (btnText) btnText.style.display = 'inline';
    if (spinner) spinner.style.display = 'none';
    if (btnFetch) btnFetch.disabled = false;
  }
}

async function handleSmartEditSubmit(e) {
  e.preventDefault();
  const url = (document.getElementById('smart-edit-url')?.value || '').trim();
  const notes = (document.getElementById('smart-edit-notes')?.value || '').trim();
  const autoPublish = document.getElementById('smart-edit-auto-publish')?.checked ?? true;
  const syncBoth = document.getElementById('smart-edit-sync-both')?.checked ?? true;

  if (!url) {
    showToast('يرجى إدخال رابط المقال 🔗', 'warning');
    return;
  }
  if (!notes) {
    showToast('يرجى لصق ملاحظات وتعديلات العميل 💬', 'warning');
    document.getElementById('smart-edit-notes')?.focus();
    return;
  }

  const btnSubmit = document.getElementById('btn-smart-edit-submit');
  const submitText = document.getElementById('smart-edit-submit-text');
  const spinner = document.getElementById('smart-edit-submit-spinner');
  const resultCard = document.getElementById('smart-edit-result-card');

  if (submitText) submitText.textContent = 'جاري التعديل الجراحي عبر Gemini والرفع للموقع... ⏳';
  if (spinner) spinner.style.display = 'inline-block';
  if (btnSubmit) btnSubmit.disabled = true;

  try {
    const res = await apiCall('/api/articles/smart-edit/apply', 'POST', {
      url,
      client_notes: notes,
      auto_publish: autoPublish,
      sync_both_sites: syncBoth
    });

    if (res.success) {
      if (resultCard) {
        resultCard.style.display = 'block';
        resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }

      // Save backup state for 1-click Undo
      _smartEditorLastBackup = {
        url,
        post_id: res.post_id,
        site_type: res.site_type,
        original_title: res.original_title,
        original_content: res.original_content,
        backup_id: res.backup_id,
        sync_both_sites: syncBoth,
        article_url: res.article_url
      };

      const btnUndo = document.getElementById('btn-smart-edit-undo');
      if (btnUndo) {
        btnUndo.style.display = 'inline-flex';
        btnUndo.disabled = false;
      }
      const undoBanner = document.getElementById('smart-edit-undo-banner');
      if (undoBanner) undoBanner.style.display = 'none';

      const openLink = document.getElementById('smart-edit-res-open-link');
      const engineBadge = document.getElementById('smart-edit-engine-badge');
      const summaryEl = document.getElementById('smart-edit-res-summary');
      const titleEl = document.getElementById('smart-edit-res-new-title');
      const contentEl = document.getElementById('smart-edit-res-content-html');

      if (openLink) openLink.href = res.article_url;
      if (engineBadge) engineBadge.textContent = `المحرك: ${res.engine || 'Gemini'} ${res.synced_sister_site ? '• (تم التزامن مع الموقع الآخر بنجاح)' : ''}`;
      if (summaryEl) summaryEl.textContent = res.changes_summary || 'تم تطبيق التعديلات المحددة بدقة.';
      if (titleEl) titleEl.textContent = res.new_title || res.original_title;
      if (contentEl) contentEl.innerHTML = res.preview_html || '';

      showToast('تم تطبيق التعديلات ورفع الخبر المحدث بنجاح! 🚀', 'success');
      try {
        publishNotificationSound.currentTime = 0;
        publishNotificationSound.play().catch(() => {});
      } catch (audioErr) {}
    } else {
      showToast(res.message || res.error || 'حدث خطأ أثناء معالجة التعديل', 'error');
    }
  } catch (err) {
    showToast(err.message || 'فشلت معالجة التعديل بالذكاء الاصطناعي', 'error');
  } finally {
    if (submitText) submitText.textContent = 'تنفيذ التعديل الجراحي وتحديث الخبر عبر Gemini 🤖';
    if (spinner) spinner.style.display = 'none';
    if (btnSubmit) btnSubmit.disabled = false;
  }
}

async function handleSmartEditUndo() {
  if (!_smartEditorLastBackup) {
    showToast('لا توجد نسخة سابقة محفوظة للتراجع عنها', 'warning');
    return;
  }

  const confirmed = confirm('هل أنت متأكد من رغبتك في التراجع عن هذا التعديل واستعادة المقال الأصلي كما كان تماماً على الموقع؟');
  if (!confirmed) return;

  const btnUndo = document.getElementById('btn-smart-edit-undo');
  const undoText = document.getElementById('smart-edit-undo-text');
  const undoSpinner = document.getElementById('smart-edit-undo-spinner');
  const undoBanner = document.getElementById('smart-edit-undo-banner');

  if (undoText) undoText.textContent = 'جاري استعادة المقال الأصلي... ⏳';
  if (undoSpinner) undoSpinner.style.display = 'inline-block';
  if (btnUndo) btnUndo.disabled = true;

  try {
    const res = await apiCall('/api/articles/smart-edit/undo', 'POST', {
      url: _smartEditorLastBackup.url,
      post_id: String(_smartEditorLastBackup.post_id),
      site_type: _smartEditorLastBackup.site_type,
      backup_title: _smartEditorLastBackup.original_title,
      backup_content: _smartEditorLastBackup.original_content,
      backup_id: _smartEditorLastBackup.backup_id,
      sync_both_sites: _smartEditorLastBackup.sync_both_sites
    });

    if (res.success) {
      showToast('تم التراجع واستعادة المقال الأصلي بنجاح! ↩️', 'success');
      if (undoBanner) undoBanner.style.display = 'block';

      const titleEl = document.getElementById('smart-edit-res-new-title');
      const contentEl = document.getElementById('smart-edit-res-content-html');
      const summaryEl = document.getElementById('smart-edit-res-summary');

      if (titleEl) titleEl.textContent = _smartEditorLastBackup.original_title;
      if (contentEl) contentEl.innerHTML = _smartEditorLastBackup.original_content;
      if (summaryEl) summaryEl.textContent = '↩️ تم التراجع: تم إلغاء التعديل واستعادة العنوان والنص الأصلي للمقال بنجاح كما كان قبل التعديل.';

      if (btnUndo) btnUndo.style.display = 'none';
    } else {
      showToast(res.error || res.message || 'فشل التراجع عن التعديل', 'error');
    }
  } catch (err) {
    showToast(err.message || 'حدث خطأ أثناء محاولة التراجع', 'error');
  } finally {
    if (undoText) undoText.textContent = '↩️ تراجع واستعادة الأصل (Undo)';
    if (undoSpinner) undoSpinner.style.display = 'none';
    if (btnUndo) btnUndo.disabled = false;
  }
}

window.initSmartEditor = initSmartEditor;
window.handleSmartEditUndo = handleSmartEditUndo;






