/* =========================================================
   FitnessAI – Frontend Application
   ========================================================= */

// If opened via file:// or running locally, point to localhost:8000. 
// If deployed to Cloud Run, use relative paths.
const API = (window.location.protocol === 'file:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : '';

// ── State ──────────────────────────────────────────────────
let state = {
  userId: null,
  currentView: 'dashboard',
  chatOpen: false,
  weekStart: getThisMonday(),
  selectedDate: todayISO(),
  chatHistory: [],
  plan: null,
  progress: null,
};

// ── Utilities ──────────────────────────────────────────────

function todayISO() {
  return new Date().toISOString().split('T')[0];
}

function getThisMonday() {
  const d = new Date();
  const day = d.getDay(); // 0=Sun
  const diff = (day === 0) ? -6 : 1 - day;
  const mon = new Date(d);
  mon.setDate(d.getDate() + diff);
  return mon.toISOString().split('T')[0];
}

function addDays(dateStr, n) {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + n);
  return d.toISOString().split('T')[0];
}

function formatDate(dateStr) {
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short'
  });
}

function formatDateFull(dateStr) {
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long'
  });
}

async function apiPost(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

async function apiGet(path) {
  const r = await fetch(API + path);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

function showToast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast ${type} show`;
  setTimeout(() => el.classList.remove('show'), 3000);
}

// ── User ID Management ─────────────────────────────────────

function initUserId() {
  const uid = localStorage.getItem('fitnessai_user_id');
  const appShell = document.getElementById('app-shell');
  const authShell = document.getElementById('auth-shell');

  if (!uid) {
    appShell.style.display = 'none';
    authShell.style.display = 'flex';
    return;
  }
  
  appShell.style.display = 'flex';
  authShell.style.display = 'none';
  
  state.userId = uid;
  const uname = localStorage.getItem('fitnessai_user_name') || 'Athlete';
  document.querySelector('.user-info .uid').textContent = uid.slice(0, 12) + '…';
  document.querySelector('.user-info .name').textContent = uname;
  
  const initials = uname.slice(0, 2).toUpperCase();
  const avatarEl = document.getElementById('avatar-initials') || document.querySelector('.user-avatar');
  if (avatarEl) avatarEl.textContent = initials;
  
  showView('dashboard');
}

// ── Auth Logic ─────────────────────────────────────────────

function toggleAuthMode(mode) {
  document.getElementById('login-form').style.display = mode === 'login' ? 'block' : 'none';
  document.getElementById('register-form').style.display = mode === 'register' ? 'block' : 'none';
}

async function handleLogin() {
  const email = document.getElementById('auth-email-login').value;
  const password = document.getElementById('auth-password-login').value;
  if (!email || !password) return showToast('Please enter email and password', 'error');

  const btn = event.target;
  const oldText = btn.textContent;
  btn.textContent = 'Signing in...';
  btn.disabled = true;

  try {
    const res = await apiPost('/login', { email, password });
    localStorage.setItem('fitnessai_user_id', res.user_id);
    localStorage.setItem('fitnessai_user_name', res.name || 'Athlete');
    showToast('Logged in successfully', 'success');
    initUserId();
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.textContent = oldText;
    btn.disabled = false;
  }
}

async function handleRegister() {
  const name = document.getElementById('auth-name-register').value;
  const email = document.getElementById('auth-email-register').value;
  const password = document.getElementById('auth-password-register').value;
  if (!email || !password) return showToast('Please enter email and password', 'error');

  const btn = event.target;
  const oldText = btn.textContent;
  btn.textContent = 'Registering...';
  btn.disabled = true;

  try {
    const res = await apiPost('/register', { email, password, name });
    localStorage.setItem('fitnessai_user_id', res.user_id);
    localStorage.setItem('fitnessai_user_name', res.name || 'Athlete');
    showToast('Registration successful!', 'success');
    initUserId();
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.textContent = oldText;
    btn.disabled = false;
  }
}

function handleLogout() {
  localStorage.removeItem('fitnessai_user_id');
  localStorage.removeItem('fitnessai_user_name');
  initUserId();
}

// ── View Routing ───────────────────────────────────────────

function showView(name) {
  state.currentView = name;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.view === name);
  });
  // Update topbar
  const titles = {
    dashboard: ['Dashboard', 'Your fitness overview'],
    calendar:  ['Weekly Calendar', 'View and track your 7-day plan'],
    chat:      ['AI Chat', 'Talk to your fitness assistant'],
  };
  document.querySelector('.topbar-title h2').textContent = titles[name][0];
  document.querySelector('.topbar-title p').textContent  = titles[name][1];

  if (name === 'dashboard') loadDashboard();
  if (name === 'calendar')  loadCalendar();
}

// ── Dashboard ──────────────────────────────────────────────

async function loadDashboard() {
  const el = document.getElementById('view-dashboard');
  try {
    const data = await apiGet(`/progress?user_id=${state.userId}`);
    state.progress = data;
    renderDashboard(data);
  } catch (e) {
    // No data yet – show welcome state
    renderWelcomeDashboard();
  }
}

function renderWelcomeDashboard() {
  document.getElementById('stat-consistency').textContent = '–';
  document.getElementById('stat-completed').textContent = '–';
  document.getElementById('stat-total').textContent = '–';
  document.getElementById('stat-weight').textContent = '–';
  document.getElementById('motivation-text').textContent =
    "Welcome to FitnessAI! Let's start by setting up your profile. Click the chat button 💬 to get started!";
  document.getElementById('recent-logs-body').innerHTML =
    '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:20px">No logs yet</td></tr>';
}

function renderDashboard(data) {
  const score = data.consistency_score || 0;
  document.getElementById('stat-consistency').textContent = score.toFixed(0) + '%';
  document.getElementById('stat-completed').textContent = data.completed_days || 0;
  document.getElementById('stat-total').textContent = data.total_days || 0;
  if (data.weight_change != null) {
    const sign = data.weight_change > 0 ? '+' : '';
    const color = data.weight_change < 0 ? 'var(--green)' : data.weight_change > 0 ? 'var(--red)' : 'var(--text)';
    const el = document.getElementById('stat-weight');
    el.textContent = sign + data.weight_change + ' kg';
    el.style.color = color;
  } else {
    document.getElementById('stat-weight').textContent = '0 kg';
    document.getElementById('stat-weight').title = 'Update your weight again to see change';
  }
  document.getElementById('motivation-text').textContent =
    data.motivational_message || 'Keep pushing!';

  const tbody = document.getElementById('recent-logs-body');
  if (!data.recent_logs?.length) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:20px">No activity logged yet</td></tr>';
    return;
  }
  tbody.innerHTML = data.recent_logs.slice(0, 5).map(l => `
    <tr>
      <td>${formatDate(l.date)}</td>
      <td>
        <span class="status-badge ${l.workout_done ? 'completed' : 'missed'}">
          ${l.workout_done ? '✓ Done' : '✗ Skipped'}
        </span>
      </td>
      <td style="color:var(--text-muted)">${l.calories || 0} kcal</td>
    </tr>
  `).join('');
}

// ── Calendar ───────────────────────────────────────────────

async function loadCalendar() {
  try {
    const data = await apiGet(
      `/calendar?user_id=${state.userId}&week_start=${state.weekStart}`
    );
    state.plan = data;
    renderCalendar(data);
    // Auto-load today's detail
    loadDayDetail(state.selectedDate);
  } catch (e) {
    document.getElementById('calendar-grid').innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <div class="big-icon">📅</div>
        <h3>No plan yet</h3>
        <p>Chat with the AI to generate your weekly fitness plan</p>
        <button class="btn btn-primary" style="margin-top:16px" onclick="openChatAndSuggest('generate my plan')">
          Generate Plan
        </button>
      </div>`;
    document.getElementById('day-detail-panel').innerHTML = '';
  }
}

function renderCalendar(data) {
  const grid = document.getElementById('calendar-grid');
  const today = todayISO();

  grid.innerHTML = data.days.map(day => {
    const isToday   = day.date === today;
    const isSelected = day.date === state.selectedDate;
    const cls = [
      'cal-day',
      day.status,
      isToday    ? 'today'    : '',
      isSelected ? 'selected' : '',
    ].filter(Boolean).join(' ');

    return `
      <div class="${cls}" onclick="selectDay('${day.date}')">
        <div class="day-name">${day.day_label.slice(0,3)}</div>
        <div class="day-number">${day.date.split('-')[2]}</div>
        <div class="day-type">${day.workout_type}</div>
        <div class="status-dot ${day.status}"></div>
        <span class="status-badge ${day.status}">${capitalize(day.status)}</span>
        <div class="cal-calories">${day.total_calories} kcal</div>
      </div>`;
  }).join('');

  // Update week label
  const start = data.days[0]?.date;
  const end   = data.days[6]?.date;
  document.getElementById('week-label').textContent =
    start && end ? `${formatDate(start)} – ${formatDate(end)}` : '';
}

function capitalize(s) { return s ? s[0].toUpperCase() + s.slice(1) : ''; }

function selectDay(dateStr) {
  state.selectedDate = dateStr;
  // Re-render calendar to update selection
  if (state.plan) renderCalendar(state.plan);
  loadDayDetail(dateStr);
}

async function loadDayDetail(dateStr) {
  const panel = document.getElementById('day-detail-panel');
  panel.innerHTML = '<div style="padding:20px;color:var(--text-muted)"><div class="spinner"></div> Loading…</div>';

  try {
    const data = await apiGet(`/day-plan?user_id=${state.userId}&date=${dateStr}`);
    renderDayDetail(data, dateStr);
  } catch (e) {
    panel.innerHTML = `
      <div class="empty-state">
        <div class="big-icon">📋</div>
        <h3>No plan for ${formatDate(dateStr)}</h3>
        <p>${e.message}</p>
      </div>`;
  }
}

function renderDayDetail(data, dateStr) {
  const panel = document.getElementById('day-detail-panel');
  const plan  = data.day_plan;
  const log   = data.log;
  const adjs  = data.adjustments || [];

  if (!plan) {
    panel.innerHTML = `<div class="empty-state"><div class="big-icon">📋</div><h3>No plan data</h3></div>`;
    return;
  }

  const exercisesHTML = (plan.exercises || []).map(ex => {
    const parts = [];
    if (ex.sets) {
      let s = `${ex.sets} sets`;
      if (ex.reps && ex.reps !== "null" && ex.reps !== null) s += ` × ${ex.reps}`;
      parts.push(s);
    }
    if (ex.duration_min && ex.duration_min !== "null" && ex.duration_min !== null) {
      parts.push(`${ex.duration_min} min`);
    }
    if (ex.notes) {
      parts.push(ex.notes);
    }
    return `
      <li class="exercise-item">
        <div>
          <div class="ex-name">${ex.name}</div>
          <div class="ex-meta">${parts.join(' · ')}</div>
        </div>
      </li>`;
  }).join('');

  const mealsHTML = (plan.meals || []).map(m => `
    <li class="meal-item" style="flex-direction:column;align-items:flex-start;gap:4px">
      <div class="meal-type">${m.meal_type}</div>
      <div class="meal-foods">${m.items?.join(', ')}</div>
      <div class="meal-cals">${m.calories} kcal · ${m.protein_g && m.protein_g !== "null" ? m.protein_g + 'g protein' : '? protein'}</div>
    </li>`).join('');

  const adjHTML = adjs.map(a => `
    <div class="adjustment-note">⚡ ${a.reason}</div>`).join('');

  const loggedHTML = log ? `
    <div style="background:var(--surface-2);border-radius:var(--radius-sm);padding:12px 14px;margin-top:12px">
      <div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:8px">TODAY'S LOG</div>
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <div><span class="status-badge ${log.workout_done ? 'completed' : 'missed'}">${log.workout_done ? '✓ Workout done' : '✗ Skipped'}</span></div>
        <div style="font-size:0.85rem;color:var(--text-muted)">${log.calories_consumed} kcal consumed</div>
      </div>
      ${log.food_intake?.length ? `<div style="margin-top:6px;font-size:0.82rem;color:var(--text-muted)">${log.food_intake.join(', ')}</div>` : ''}
    </div>` : '';

  panel.innerHTML = `
    <div class="day-detail">
      <div class="day-detail-header">
        <div>
          <h2>${formatDateFull(dateStr)}</h2>
          <p style="margin-top:4px">${plan.workout_type} · ${plan.workout_start} – ${plan.workout_end}</p>
        </div>
        <span class="status-badge ${plan.status}">${capitalize(plan.status)}</span>
      </div>
      <div class="day-detail-body">
        <div class="detail-section">
          <h3>🏋️ Workout</h3>
          <ul class="exercise-list">${exercisesHTML || '<li style="color:var(--text-muted);font-size:0.85rem">Rest day – no exercises</li>'}</ul>
          <div class="targets-grid">
            <div class="target-item">
              <div class="t-val">${plan.total_calories}</div>
              <div class="t-lbl">Calorie Target</div>
            </div>
            <div class="target-item">
              <div class="t-val">${plan.water_ml || 2500}ml</div>
              <div class="t-lbl">Water Goal</div>
            </div>
          </div>
          ${adjHTML}
          ${loggedHTML}
        </div>

        <div class="detail-section">
          <h3>🥗 Diet Plan</h3>
          <ul class="meal-list">${mealsHTML}</ul>
          <div style="margin-top:16px">
            <div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.08em">Log Today's Activity</div>
            <div class="log-form" id="log-form-${dateStr}">
              <div>
                <label>Did you complete your workout?</label>
                <div class="toggle-group">
                  <button class="toggle-btn" id="log-yes-${dateStr}" onclick="setWorkoutDone('${dateStr}', true)">✓ Yes</button>
                  <button class="toggle-btn" id="log-no-${dateStr}"  onclick="setWorkoutDone('${dateStr}', false)">✗ No</button>
                </div>
              </div>
              <div>
                <label>Calories consumed today</label>
                <input type="number" id="log-cal-${dateStr}" placeholder="e.g. 1800" min="0" max="5000" />
              </div>
              <div>
                <label>Food items (comma-separated)</label>
                <input type="text" id="log-food-${dateStr}" placeholder="e.g. rice, dal, salad" />
              </div>
              <button class="btn btn-primary btn-sm" onclick="submitLog('${dateStr}')">
                Save Log & Get Adjustment
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  // Pre-fill log if exists
  if (log) {
    const calEl   = document.getElementById(`log-cal-${dateStr}`);
    const foodEl  = document.getElementById(`log-food-${dateStr}`);
    if (calEl)  calEl.value = log.calories_consumed;
    if (foodEl) foodEl.value = (log.food_intake || []).join(', ');
    setWorkoutDone(dateStr, log.workout_done);
  }
}

// ── Log Activity ───────────────────────────────────────────

const logState = {};

function setWorkoutDone(dateStr, done) {
  logState[dateStr] = { ...(logState[dateStr] || {}), workoutDone: done };
  const yes = document.getElementById(`log-yes-${dateStr}`);
  const no  = document.getElementById(`log-no-${dateStr}`);
  if (!yes || !no) return;
  yes.className = 'toggle-btn' + (done ? ' active-yes' : '');
  no.className  = 'toggle-btn' + (!done ? ' active-no' : '');
}

async function submitLog(dateStr) {
  const ls       = logState[dateStr] || {};
  const calEl    = document.getElementById(`log-cal-${dateStr}`);
  const foodEl   = document.getElementById(`log-food-${dateStr}`);
  const calories = parseInt(calEl?.value) || 0;
  const foodRaw  = foodEl?.value || '';
  const foodItems = foodRaw.split(',').map(s => s.trim()).filter(Boolean);

  if (ls.workoutDone === undefined) {
    showToast('Please select whether you completed your workout', 'error');
    return;
  }

  try {
    const res = await apiPost('/log', {
      user_id: state.userId,
      date: dateStr,
      workout_done: ls.workoutDone,
      food_items: foodItems,
      calories: calories,
      notes: '',
    });
    showToast('Activity logged! ' + (res.adjustment_message ? '✓ Plan adjusted.' : ''), 'success');
    // Reload calendar and detail
    await loadCalendar();
    if (res.adjustment_message) {
      addChatMessage('assistant', '⚡ ' + res.adjustment_message);
    }
  } catch (e) {
    showToast('Failed to log: ' + e.message, 'error');
  }
}

// ── Week Navigation ────────────────────────────────────────

function prevWeek() {
  state.weekStart = addDays(state.weekStart, -7);
  loadCalendar();
}

function nextWeek() {
  state.weekStart = addDays(state.weekStart, 7);
  loadCalendar();
}

// ── Chat ───────────────────────────────────────────────────

function toggleChat() {
  state.chatOpen = !state.chatOpen;
  document.getElementById('chat-panel').classList.toggle('open', state.chatOpen);
  if (state.chatOpen && state.chatHistory.length === 0) {
    // Welcome message
    addChatMessage('assistant',
      "Hi! I'm FitBot 👋 I'll help you set up your fitness plan, track workouts, and keep you motivated. What's your fitness goal? (weight loss / muscle gain / maintenance)"
    );
  }
}

function closeChat() {
  state.chatOpen = false;
  document.getElementById('chat-panel').classList.remove('open');
}

function openChatAndSuggest(text) {
  state.chatOpen = true;
  document.getElementById('chat-panel').classList.add('open');
  document.getElementById('chat-input').value = text;
  sendMessage();
}

function addChatMessage(role, content) {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = content;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  state.chatHistory.push({ role, content });
}

function showTyping() {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.id = 'typing-indicator';
  div.className = 'msg-typing';
  div.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function hideTyping() {
  document.getElementById('typing-indicator')?.remove();
}

async function sendMessage() {
  const input = document.getElementById('chat-input');
  const text  = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = 'auto';
  addChatMessage('user', text);

  const sendBtn = document.getElementById('chat-send');
  sendBtn.disabled = true;
  showTyping();

  try {
    const res = await apiPost('/chat', {
      user_id: state.userId,
      message: text,
    });
    hideTyping();
    addChatMessage('assistant', res.reply);

    // If a plan was generated or modified, refresh calendar
    if (res.structured_data?.plan || res.intent === 'get_plan' ||
        res.intent === 'modify_plan' || res.structured_data?.plan_modified ||
        res.structured_data?.refresh_calendar) {
      setTimeout(() => {
        loadCalendar();
        if (state.currentView === 'calendar') loadDayDetail(state.selectedDate);
      }, 500);
    }
    // If profile was updated, refresh dashboard
    if (res.intent === 'profile') {
      setTimeout(() => {
        if (state.currentView === 'dashboard') loadDashboard();
      }, 500);
    }

    // Show quick chips based on intent
    renderQuickChips(res.intent);

  } catch (e) {
    hideTyping();
    addChatMessage('assistant', '⚠️ ' + (e.message || 'Something went wrong. Please try again.'));
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

function renderQuickChips(intent) {
  const container = document.getElementById('quick-chips');
  const suggestions = {
    profile:      ['Update my weight', 'Change diet to non-veg', 'My goal is muscle gain'],
    log_activity: ['I skipped today', 'Show my plan', 'How am I doing?'],
    get_plan:     ['Show today\'s workout', 'What should I eat?', 'Change my plan'],
    modify_plan:  ['I don\'t like running', 'Replace push-ups with something easier', 'Change my meals', 'I want home workouts only'],
    nutrition:    ['What can I eat for breakfast?', 'Is pizza okay?', 'High protein lunch ideas'],
    motivation:   ['Show my plan', 'Log my workout', 'How many calories?'],
    general:      ['Generate my plan', 'What\'s my goal?', 'Log today\'s workout'],
  };
  const chips = suggestions[intent] || suggestions.general;
  container.innerHTML = chips.map(c =>
    `<span class="chip" onclick="chipSend('${c}')">${c}</span>`
  ).join('');
}

function chipSend(text) {
  document.getElementById('chat-input').value = text;
  sendMessage();
}

// Handle Enter key in chat
function handleChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

// Auto-resize textarea
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 100) + 'px';
}

// ── Init ───────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initUserId();

  // Nav
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => showView(item.dataset.view));
  });

  // Chat input
  const chatInput = document.getElementById('chat-input');
  chatInput.addEventListener('keydown', handleChatKey);
  chatInput.addEventListener('input', () => autoResize(chatInput));

  document.getElementById('chat-send').addEventListener('click', sendMessage);

  // Initial quick chips
  renderQuickChips('general');

  // Update topbar date
  document.querySelector('.topbar-title p').textContent =
    new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
});
