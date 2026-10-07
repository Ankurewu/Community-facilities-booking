const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const state = { user: null, csrf: '', venues: [], step: 1, venue: 'nightcliff', mode: 'customer', auth: 'login', bookings: [], selected: null, draft: null };
const statuses = { pending: 'Waiting for review', needs_info: 'More information requested', approved: 'Approved', rejected: 'Rejected', cancelled: 'Cancelled' };
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const dateLabel = value => new Date(`${value}T12:00:00+09:30`).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Australia/Darwin' });
function notice(message, error = false) {
  $('#notice').hidden = !message;
  $('#notice').textContent = message;
  $('#notice').classList.toggle('error-notice', error);
  $('#liveRegion').textContent = message;
}
async function api(path, method = 'GET', body) {
  const response = await fetch(`/api${path}`, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      state.user = null; updateAccount(); openAuth('login');
    }
    throw new Error(result.error || 'Request failed. Please try again.');
  }
  if (result.csrf) state.csrf = result.csrf;
  return result;
}
function safely(fn) {
  return async event => { try { await fn(event); } catch (error) { notice(error.message, true); } };
}
async function busy(button, task) {
  button.disabled = true;
  try { return await task(); } finally { button.disabled = false; }
}
function openAuth(mode = 'login') {
  state.auth = mode;
  const registering = mode === 'register', changing = mode === 'password';
  $('#authTitle').textContent = changing ? 'Change your password' : registering ? 'Create your account' : 'Welcome back';
  $('#authSubmit').textContent = changing ? 'Update password' : registering ? 'Create account' : 'Sign in';
  $('#nameField').hidden = !registering; $('#authName').required = registering;
  $('#emailField').hidden = changing; $('#authEmail').required = !changing;
  $('#currentPasswordField').hidden = !changing; $('#currentPassword').required = changing;
  $('#passwordHelp').hidden = !registering && !changing;
  $('#authPassword').minLength = registering || changing ? 12 : 1;
  $('#authPassword').autocomplete = registering || changing ? 'new-password' : 'current-password';
  $('#authPassword').value = ''; $('#currentPassword').value = ''; $('#authError').textContent = '';
  for (const [id, value] of [['loginTab', 'login'], ['registerTab', 'register'], ['passwordTab', 'password']]) {
    $(`#${id}`).classList.toggle('is-active', value === mode);
    $(`#${id}`).hidden = !!state.user && value !== 'password';
  }
  $('#passwordTab').hidden = !state.user;
  if (!$('#authDialog').open) $('#authDialog').showModal();
}
function updateAccount() {
  $('#accountButton').textContent = state.user ? state.user.name : 'Sign in';
  $('#logoutButton').hidden = !state.user;
  $('[data-mode="staff"]').hidden = state.user?.role !== 'staff';
  if (state.mode === 'staff' && state.user?.role !== 'staff') setMode('customer');
  $('#restoreDraft').hidden = !state.user || !state.draft;
}
async function loadDraft() {
  state.draft = state.user ? (await api('/draft')).draft : null;
  updateAccount();
}
function renderVenues() {
  const attendance = Number($('#attendanceFilter').value || 1), access = $('#accessFilter').value;
  const matches = state.venues.filter(v => v.capacity >= attendance && (access === 'any' || v.features.includes(access)));
  $('#venueList').innerHTML = matches.length ? matches.map(v => `<button type="button" class="venue-card${state.venue === v.id ? ' is-selected' : ''}" data-venue="${v.id}" aria-pressed="${state.venue === v.id}"><span class="selected-badge">Selected</span><p class="eyebrow">Community centre</p><h3>${escapeHTML(v.name)}</h3><p>Space for up to ${v.capacity} people.</p><div class="venue-meta"><span>Capacity ${v.capacity}</span><span>6 am–11:59 pm</span></div><ul class="venue-features">${v.labels.map(label => `<li>${escapeHTML(label)}</li>`).join('')}</ul></button>`).join('') : '<div class="info-callout span-2">No facility matches these requirements. Try another filter.</div>';
  $$('[data-venue]').forEach(button => button.addEventListener('click', () => { state.venue = button.dataset.venue; renderVenues(); }));
}
let availabilitySequence = 0;
async function loadAvailability(preselected = '') {
  const sequence = ++availabilitySequence;
  $('#slotList').textContent = 'Checking availability…';
  const result = await api(`/availability?venue=${encodeURIComponent(state.venue)}&date=${encodeURIComponent($('#eventDate').value)}`);
  if (sequence !== availabilitySequence) return;
  $('#slotList').innerHTML = result.slots.map(slot => `<label class="${slot.available ? '' : 'is-unavailable'}"><input type="radio" name="slot" value="${slot.value}" ${slot.available ? '' : 'disabled'} ${slot.available && slot.value === preselected ? 'checked' : ''}><span><strong>${slot.value}</strong><small>${slot.available ? 'Available' : 'Reserved'}</small></span></label>`).join('');
  $$('input[name="slot"]').forEach(input => input.addEventListener('change', () => {
    const [start, end] = input.value.split('–'); $('#setupTime').value = start; $('#cleanupTime').value = end;
  }));
}
function showStep(step) {
  state.step = step;
  $$('.journey-step').forEach(panel => { const active = Number(panel.dataset.step) === step; panel.hidden = !active; panel.classList.toggle('is-active', active); });
  $$('[data-step-indicator]').forEach(item => {
    const number = Number(item.dataset.stepIndicator);
    item.classList.toggle('is-current', number === step); item.classList.toggle('is-complete', number < step);
    $('span', item).textContent = number < step ? '✓' : String(number);
    if (number === step) item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
  });
  $(`.journey-step[data-step="${step}"] h2`).focus({ preventScroll: true });
}
function requestDetails() {
  return { venue: state.venue, eventDate: $('#eventDate').value, slot: $('input[name="slot"]:checked')?.value || '', eventName: $('#eventName').value.trim(), eventType: $('#eventType').value, attendance: Number($('#attendance').value), setupTime: $('#setupTime').value, cleanupTime: $('#cleanupTime').value, alcohol: $('input[name="alcohol"]:checked').value, notes: $('#bookingNotes').value, declaration: $('#declaration').checked };
}
function validateDetails() {
  $('#eventNameError').textContent = ''; $('#setupTimeError').textContent = '';
  $('#eventName').removeAttribute('aria-invalid'); $('#setupTime').removeAttribute('aria-invalid');
  if (!$('#requestForm').reportValidity()) return false;
  const b = requestDetails(), venue = state.venues.find(v => v.id === state.venue), [start, end] = b.slot.split('–');
  if (!b.eventName || b.eventName.length > 120) { $('#eventNameError').textContent = 'Enter an event name (maximum 120 characters).'; $('#eventName').setAttribute('aria-invalid', 'true'); return false; }
  if (!Number.isInteger(b.attendance) || b.attendance < 1 || b.attendance > venue.capacity) { notice(`Attendance must be between 1 and ${venue.capacity}.`, true); return false; }
  if (!(b.setupTime >= '06:00' && b.setupTime <= start && b.cleanupTime >= end && b.cleanupTime <= '23:59')) { $('#setupTimeError').textContent = 'Setup and cleanup must cover the chosen event period, within 6 am–11:59 pm.'; $('#setupTime').setAttribute('aria-invalid', 'true'); return false; }
  return true;
}
function review() {
  const b = requestDetails(), v = state.venues.find(v => v.id === b.venue);
  const items = [['Facility', v.name], ['Date and time', `${dateLabel(b.eventDate)} · ${b.slot}`], ['Event', `${b.eventName} · ${b.eventType}`], ['Attendance', `${b.attendance} people`], ['Reserved access period', `${b.setupTime}–${b.cleanupTime}`], ['Alcohol', b.alcohol], ['Additional notes', b.notes || 'None']];
  $('#reviewCard').innerHTML = items.map(([label, value]) => `<div class="review-item"><span>${label}</span><strong>${escapeHTML(value)}</strong></div>`).join('');
}
async function setMode(mode) {
  if (mode !== 'customer' && !state.user) { openAuth('login'); return; }
  if (mode === 'staff' && state.user?.role !== 'staff') return;
  state.mode = mode;
  for (const name of ['customer', 'bookings', 'staff']) $(`#${name}Mode`).hidden = name !== mode;
  $$('.mode-tab[data-mode]').forEach(b => { b.classList.toggle('is-active', b.dataset.mode === mode); b.setAttribute('aria-pressed', String(b.dataset.mode === mode)); });
  $(`#${mode === 'customer' ? 'customer' : mode === 'staff' ? 'staff' : 'bookings'}Title`).focus({ preventScroll: true });
  if (mode !== 'customer') await loadBookings();
}
function historyHTML(booking) {
  return `<details class="history"><summary>History and messages (${booking.history.length})</summary><ol>${booking.history.map(h => `<li><strong>${escapeHTML(statuses[h.action] || h.action)}</strong><p>${escapeHTML(h.note)}</p><small>${escapeHTML(h.actor_name)} · ${new Date(h.created_at).toLocaleString('en-AU', { timeZone: 'Australia/Darwin' })} Darwin time</small></li>`).join('')}</ol></details>`;
}
function bookingHTML(b, actions = true) {
  return `<article class="booking-card"><div class="case-header"><div><p class="eyebrow">${b.reference}</p><h2>${escapeHTML(b.event_name)}</h2></div><span class="status-pill ${b.status === 'approved' ? '' : 'waiting'}">${statuses[b.status]}</span></div><div class="case-grid"><div><span>Facility</span><strong>${escapeHTML(b.venue_name)}</strong></div><div><span>Event time (Darwin)</span><strong>${dateLabel(b.event_date)} · ${b.slot}</strong></div><div><span>Reserved access</span><strong>${b.setup_time}–${b.cleanup_time}</strong></div><div><span>Attendance</span><strong>${b.attendance} people</strong></div></div><p>${escapeHTML(b.notes)}</p>${historyHTML(b)}${actions && b.status === 'needs_info' ? `<form class="reply-form" data-booking="${b.id}"><label>Reply to staff<textarea name="note" rows="3" maxlength="2000" required></textarea></label><button class="primary-button" type="submit">Send information</button></form>` : ''}${actions && ['pending', 'needs_info', 'approved'].includes(b.status) && b.event_date > state.today ? `<button class="secondary-button cancel-booking" data-booking="${b.id}" type="button">Cancel booking</button>` : ''}</article>`;
}
async function loadBookings() {
  const result = await api('/bookings'); state.bookings = result.bookings;
  $('#myBookingList').innerHTML = result.bookings.filter(b => b.user_id === state.user.id).map(b => bookingHTML(b)).join('') || '<div class="info-callout">You have no bookings yet. Use Book a facility to get started.</div>';
  $$('.cancel-booking').forEach(button => button.addEventListener('click', safely(async () => {
    if (!window.confirm('Cancel this booking and release its reserved period?')) return;
    await busy(button, () => api(`/bookings/${button.dataset.booking}/cancel`, 'POST', {})); await loadBookings(); notice('Booking cancelled.');
  })));
  $$('.reply-form').forEach(form => form.addEventListener('submit', safely(async event => {
    event.preventDefault(); await busy($('button', form), () => api(`/bookings/${form.dataset.booking}/reply`, 'POST', { note: $('textarea', form).value })); await loadBookings(); notice('Your reply was sent to staff.');
  })));
  if (state.user.role === 'staff') renderQueue();
}
function renderQueue() {
  const filter = $('#staffFilter').value, bookings = state.bookings.filter(b => filter === 'all' || b.status === filter);
  $('#queueCount').textContent = `${bookings.length} requests`;
  $('#staffQueue').innerHTML = bookings.map(b => `<button class="queue-item${b.id === state.selected ? ' is-selected' : ''}" data-case="${b.id}" type="button"><span><strong>${b.reference}</strong><small>${escapeHTML(b.venue_name)} · ${dateLabel(b.event_date)}</small></span><span class="status-pill waiting">${statuses[b.status]}</span></button>`).join('') || '<p class="empty-state">No matching requests.</p>';
  $$('[data-case]').forEach(button => button.addEventListener('click', () => { state.selected = Number(button.dataset.case); renderQueue(); }));
  const b = bookings.find(b => b.id === state.selected);
  if (!b) { $('#staffCase').innerHTML = '<p>Select a request from the queue.</p>'; return; }
  const canDecide = ['pending', 'needs_info'].includes(b.status) && b.event_date > state.today && b.user_id !== state.user.id;
  $('#staffCase').innerHTML = `<p class="eyebrow">Applicant</p><h2>${escapeHTML(b.customer_name)}</h2><p>${escapeHTML(b.customer_email)}</p>${bookingHTML(b, false)}<div class="info-callout">Capacity: ${b.attendance} / ${state.venues.find(v => v.id === b.venue_id).capacity}. Alcohol: ${b.alcohol}. This request holds the full setup and cleanup period.</div>${canDecide ? '<label>Decision note<textarea id="decisionReason" rows="3" maxlength="2000" required placeholder="Explain your decision or the information required"></textarea></label><div class="action-row decision-actions"><button id="requestInfo" data-decision="needs_info" class="secondary-button" type="button">Request information</button><button id="rejectCase" data-decision="rejected" class="secondary-button" type="button">Reject</button><button id="approveCase" data-decision="approved" class="primary-button" type="button">Approve</button></div>' : '<p class="help-text">No decision is available for this request.</p>'}`;
  $$('[data-decision]').forEach(button => button.addEventListener('click', safely(async () => {
    const note = $('#decisionReason'); if (!note.value.trim()) { note.setAttribute('aria-invalid', 'true'); note.focus(); notice('Enter a decision note first.', true); return; }
    await busy(button, () => api(`/bookings/${b.id}/decision`, 'POST', { status: button.dataset.decision, note: note.value })); await loadBookings(); notice('Decision saved. The applicant can see your update.');
  })));
}
$('#authForm').addEventListener('submit', async event => {
  event.preventDefault(); $('#authError').textContent = '';
  try {
    const changing = state.auth === 'password';
    const body = changing ? { current_password: $('#currentPassword').value, new_password: $('#authPassword').value } : { name: $('#authName').value, email: $('#authEmail').value, password: $('#authPassword').value };
    const result = await busy($('#authSubmit'), () => api(`/auth/${state.auth}`, 'POST', body));
    if (result.user) state.user = result.user;
    $('#authDialog').close(); $('#authPassword').value = ''; $('#currentPassword').value = ''; await loadDraft(); updateAccount();
    notice(changing ? 'Password changed. Other sessions have been signed out.' : `Welcome, ${state.user.name}.`);
  } catch (error) { $('#authError').textContent = error.message; }
});
$('#accountButton').addEventListener('click', () => openAuth(state.user ? 'password' : 'login'));
$('#closeAuth').addEventListener('click', () => $('#authDialog').close());
$('#loginTab').addEventListener('click', () => openAuth('login'));
$('#registerTab').addEventListener('click', () => openAuth('register'));
$('#passwordTab').addEventListener('click', () => openAuth('password'));
$('#logoutButton').addEventListener('click', safely(async () => {
  await api('/auth/logout', 'POST', {}); state.user = null; state.draft = null; state.bookings = []; state.selected = null; updateAccount(); $('#myBookingList').textContent = ''; $('#staffCase').textContent = ''; $('#staffQueue').textContent = ''; $('#requestForm').reset(); $('#bookingConfirmation').textContent = ''; $('#declaration').checked = false; await setMode('customer'); showStep(1); notice('You have signed out.');
}));
$$('[data-mode]').forEach(b => b.addEventListener('click', safely(() => setMode(b.dataset.mode))));
$$('[data-next]').forEach(button => button.addEventListener('click', safely(async () => {
  const next = Number(button.dataset.next); notice('');
  if (state.step === 1) {
    const v = state.venues.find(v => v.id === state.venue), access = $('#accessFilter').value;
    if (!v || !$('#attendanceFilter').reportValidity() || v.capacity < Number($('#attendanceFilter').value) || (access !== 'any' && !v.features.includes(access))) { notice('Select a facility matching your requirements.', true); return; }
    $('#selectedVenueName').textContent = v.name; $('#attendance').max = v.capacity; $('#attendance').value = $('#attendanceFilter').value;
    await loadAvailability();
  }
  if (state.step === 2 && !$('#slotList input:checked')) { notice('Choose an available date and time.', true); return; }
  if (state.step === 3 && !validateDetails()) return;
  if (next === 4) review(); showStep(next);
})));
$$('[data-back]').forEach(button => button.addEventListener('click', () => showStep(Number(button.dataset.back))));
$('#attendanceFilter').addEventListener('input', renderVenues); $('#accessFilter').addEventListener('change', renderVenues);
$('#eventDate').addEventListener('change', safely(() => loadAvailability()));
$('#saveDraft').addEventListener('click', safely(async () => {
  if (!state.user) { openAuth('login'); notice('Sign in, then save your draft.'); return; }
  const b = requestDetails(); delete b.declaration; b.attendance = String(b.attendance); await busy($('#saveDraft'), () => api('/draft', 'PUT', b)); $('#saveState').textContent = 'Draft saved to your account'; await loadDraft(); notice('Draft saved. You can resume it after signing in again.');
}));
$('#restoreDraft').addEventListener('click', safely(async () => {
  const d = state.draft; if (!d) return;
  state.venue = d.venue; renderVenues(); $('#selectedVenueName').textContent = state.venues.find(v => v.id === d.venue)?.name || '';
  for (const id of ['eventName', 'eventType', 'attendance', 'setupTime', 'cleanupTime', 'eventDate']) if (d[id]) $(`#${id}`).value = d[id];
  $('#attendance').max = state.venues.find(v => v.id === d.venue)?.capacity || 120;
  $('#bookingNotes').value = d.notes || ''; $(`input[name="alcohol"][value="${d.alcohol === 'Yes' ? 'Yes' : 'No'}"]`).checked = true;
  showStep(2); await loadAvailability(d.slot); notice('Draft restored. Check current availability before continuing.');
}));
$('#submitRequest').addEventListener('click', safely(async () => {
  if (!state.user) { openAuth('login'); notice('Sign in or create an account, then submit your request.'); return; }
  if (!$('#declaration').checked) { $('#declaration').focus(); notice('Confirm the declaration before submitting.', true); return; }
  const result = await busy($('#submitRequest'), () => api('/bookings', 'POST', requestDetails()));
  $('#bookingConfirmation').innerHTML = bookingHTML(result.booking, false); state.draft = null; updateAccount(); showStep(5); notice(`Request ${result.booking.reference} saved.`);
}));
$('#restartJourney').addEventListener('click', () => { $('#requestForm').reset(); $('#declaration').checked = false; $('#saveState').textContent = 'Not saved'; showStep(1); notice(''); });
$('#viewBookings').addEventListener('click', safely(() => setMode('bookings')));
$('#refreshBookings').addEventListener('click', safely(() => loadBookings())); $('#refreshStaff').addEventListener('click', safely(() => loadBookings())); $('#staffFilter').addEventListener('change', renderQueue);
async function init() {
  const [session, catalog] = await Promise.all([api('/session'), api('/venues')]);
  state.user = session.user; state.csrf = session.csrf; state.venues = catalog.venues; state.today = catalog.today;
  const nextDay = new Date(`${catalog.today}T12:00:00Z`); nextDay.setUTCDate(nextDay.getUTCDate() + 1);
  $('#eventDate').min = nextDay.toISOString().slice(0, 10); $('#eventDate').max = catalog.max_date; $('#eventDate').value = $('#eventDate').min;
  $('#eventName').maxLength = 120; renderVenues(); updateAccount(); await loadDraft();
}
init().catch(error => notice(`Could not connect to the booking service: ${error.message}`, true));
