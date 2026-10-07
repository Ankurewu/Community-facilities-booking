"use strict";
const $ = (s, r = document) => r.querySelector(s),
  $$ = (s, r = document) => [...r.querySelectorAll(s)];
const state = {
  portal: location.pathname === "/admin" ? "admin" : "customer",
  user: null,
  csrf: "",
  demo: false,
  mode: "customer",
  step: 1,
  venue: "nightcliff",
  venues: [],
  bookings: [],
  selected: null,
  documents: [],
  draft: null,
  auth: "login",
  challenge: null,
  applicant: null,
  today: "",
};
const modes = [
  "home",
  "customer",
  "bookings",
  "staff",
  "calendar",
  "finance",
  "reports",
  "admin",
  "audit",
  "notifications",
  "help",
];
const labels = {
  pending: "Waiting for review",
  needs_info: "More information requested",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
  submitted: "Submitted",
  under_review: "Under review",
  payment_pending: "Awaiting demo payment",
  confirmed: "Confirmed",
  completed: "Completed",
  requested: "Requested",
  paid: "Paid",
  refunded: "Refunded",
  processing: "Awaiting reconciliation",
  declined: "Declined",
  queued: "Queued",
  delivered: "Delivered",
  failed: "Failed",
};
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const money = (cents) =>
  new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(
    cents / 100,
  );
const dateText = (value) =>
  new Date(`${value}T12:00:00+09:30`).toLocaleDateString("en-AU", {
    dateStyle: "medium",
    timeZone: "Australia/Darwin",
  });
const stamp = (value) =>
  new Date(value).toLocaleString("en-AU", { timeZone: "Australia/Darwin" });
const can = (p) => state.user?.permissions?.includes(p);
const statusText = (b) =>
  b.status === "approved"
    ? b.completed
      ? "Completed"
      : b.payment?.status === "paid"
        ? "Confirmed"
        : b.payment?.status === "refunded"
          ? "Refunded"
          : "Approved · payment pending"
    : b.phase === "under_review"
      ? "Under review"
      : labels[b.status];
function notice(message, error = false) {
  $("#notice").hidden = !message;
  $("#notice").textContent = message;
  $("#notice").classList.toggle("error-notice", error);
  $("#liveRegion").textContent = message;
  if (error)
    $("#notice").scrollIntoView({ behavior: "smooth", block: "center" });
}
async function api(path, method = "GET", payload) {
  const form = payload instanceof FormData;
  const headers = { "X-CSRF-Token": state.csrf };
  if (!form) headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers,
    ...(payload !== undefined
      ? { body: form ? payload : JSON.stringify(payload) }
      : {}),
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw Error(
      "The booking service did not return a valid response. Run python server.py demo, not a static HTML server.",
    );
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) {
      state.user = null;
      updateAccount();
      openAuth("login");
    }
    throw Error(result.error || "Request failed.");
  }
  if (result.csrf) state.csrf = result.csrf;
  return result;
}
function safe(fn) {
  return async (event) => {
    try {
      await fn(event);
    } catch (error) {
      notice(error.message, true);
    }
  };
}
async function busy(button, fn) {
  if (button) button.disabled = true;
  try {
    return await fn();
  } finally {
    if (button) button.disabled = false;
  }
}
const empty = (text) => `<div class="info-callout">${esc(text)}</div>`;
const button = (label, action, id = "", style = "secondary-button") =>
  `<button type="button" class="${style}" data-action="${action}" data-id="${esc(id)}">${esc(label)}</button>`;
const field = (label, name, value = "", type = "text", extra = "") =>
  `<label>${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
const area = (label, name, value = "", required = true) =>
  `<label>${esc(label)}<textarea name="${name}" rows="3" maxlength="2000" ${required ? "required" : ""}>${esc(value)}</textarea></label>`;
function dialog(title, html, onSubmit) {
  $("#workTitle").textContent = title;
  $("#workContent").innerHTML = html;
  $("#workError").textContent = "";
  if (!$("#workDialog").open) $("#workDialog").showModal();
  const form = $("form", $("#workContent"));
  if (form && onSubmit)
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      $("#workError").textContent = "";
      try {
        await busy($('button[type="submit"]', form), () =>
          onSubmit(Object.fromEntries(new FormData(form)), form),
        );
        $("#workDialog").close();
      } catch (err) {
        $("#workError").textContent = err.message;
      }
    });
}
function formHTML(content, submit = "Save") {
  return `<form class="dialog-form">${content}<button type="submit" class="primary-button">${esc(submit)}</button></form>`;
}
function openAuth(mode = "login") {
  state.auth = mode;
  state.challenge = null;
  $("#authTitle").textContent = {
    login:
      state.portal === "admin" ? "Admin & staff sign in" : "Customer sign in",
    register:
      state.portal === "admin"
        ? "Create admin account"
        : "Create customer account",
    password: "Change password",
    forgot: "Recover your account",
    reset: "Set a new password",
  }[mode];
  const content =
    mode === "register"
      ? field("Full name", "name", "", "text", 'required maxlength="100"') +
        field(
          "Email address",
          "email",
          "",
          "email",
          'required autocomplete="email"',
        ) +
        field(
          "Password (12+ characters)",
          "password",
          "",
          "password",
          'required minlength="12" maxlength="128" autocomplete="new-password"',
        )
      : mode === "password"
        ? field(
            "Current password",
            "current_password",
            "",
            "password",
            'required autocomplete="current-password"',
          ) +
          field(
            "New password (12+ characters)",
            "new_password",
            "",
            "password",
            'required minlength="12" maxlength="128" autocomplete="new-password"',
          )
        : mode === "forgot"
          ? field("Account email", "email", "", "email", "required")
          : mode === "reset"
            ? field(
                "New password (12+ characters)",
                "password",
                "",
                "password",
                'required minlength="12" maxlength="128" autocomplete="new-password"',
              )
            : field(
                "Email address",
                "email",
                "",
                "email",
                'required autocomplete="email"',
              ) +
              field(
                "Password",
                "password",
                "",
                "password",
                'required maxlength="128" autocomplete="current-password"',
              );
  $("#authForm").innerHTML =
    content +
    '<p id="authFormError" class="error-text" role="alert"></p><button class="primary-button" type="submit">' +
    {
      register: "Create account",
      password: "Update password",
      forgot: "Send recovery message",
      reset: "Save password",
      login: "Sign in",
    }[mode] +
    "</button>";
  for (const [id, m] of [
    ["loginTab", "login"],
    ["registerTab", "register"],
    ["forgotTab", "forgot"],
    ["passwordTab", "password"],
  ]) {
    $("#" + id).hidden = !!state.user && m !== "password";
    $("#" + id).classList.toggle("is-active", m === mode);
  }
  $("#passwordTab").hidden = !state.user;
  $("#authAccountPrompt").hidden = !!state.user || mode !== "login";
  $("#authLoginPrompt").hidden = !!state.user || mode === "login";
  if (!$("#authDialog").open) $("#authDialog").showModal();
}
async function authSubmit(e) {
  e.preventDefault();
  $("#authFormError").textContent = "";
  const values = {
    ...Object.fromEntries(new FormData($("#authForm"))),
    portal: state.portal,
  };
  try {
    const result = await busy($('button[type="submit"]', $("#authForm")), () =>
      state.challenge
        ? api("/auth/mfa", "POST", {
            challenge: state.challenge,
            code: values.code,
          })
        : state.auth === "forgot"
          ? api("/auth/reset-request", "POST", values)
          : state.auth === "reset"
            ? api("/auth/reset", "POST", {
                ...values,
                token: new URLSearchParams(location.search).get("reset"),
              })
            : api("/auth/" + state.auth, "POST", values),
    );
    if (result.mfa_required) {
      state.challenge = result.challenge;
      $("#authTitle").textContent = "Verify staff access";
      $("#authForm").innerHTML =
        `<p>Use the six-digit code from your authenticator app.</p>${result.enrollment_secret ? `<p>First-time setup: add this secret to your authenticator, then enter its code.</p><code class="secret-code">${esc(result.enrollment_secret)}</code>` : ""}${result.demo_code ? `<div class="info-callout">Local test code: <strong>${result.demo_code}</strong>. Normal mode does not show this code.</div>` : ""}${field("Verification code", "code", result.demo_code || "", "text", 'required pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code"')}<p id="authFormError" role="alert" class="error-text"></p><button class="primary-button" type="submit">Verify and sign in</button>`;
      return;
    }
    if (state.auth === "forgot") {
      notice(result.message);
      $("#authDialog").close();
      return;
    }
    if (state.auth === "reset") {
      history.replaceState({}, "", location.pathname);
      $("#authDialog").close();
      openAuth("login");
      notice("Password updated. Sign in with your new password.");
      return;
    }
    const session = await api("/session");
    state.user = session.user;
    $("#authDialog").close();
    state.challenge = null;
    await loadDraft();
    updateAccount();
    await loadInboxCount();
    if (can("assist")) await loadApplicants();
    await setMode(state.portal === "admin" && can("assess") ? "staff" : "home");
    notice(
      state.portal === "admin" && can("assess")
        ? "Signed in. Customer booking requests appear here. Select a request to accept or reject it."
        : "Signed in. Choose an action from your dashboard.",
    );
  } catch (err) {
    $("#authFormError").textContent = err.message;
  }
}
function updateAccount() {
  const user = state.user;
  $("#accountButton").textContent = user ? user.name : "Sign in";
  $("#logoutButton").hidden = !user;
  const access = {
    customer: state.portal === "customer" || can("assist"),
    bookings: state.portal === "customer" || can("assist"),
    staff: can("assess"),
    calendar: can("calendar") || can("assist"),
    finance: can("finance"),
    reports: can("reports"),
    admin: can("admin"),
    audit: can("audit"),
    notifications: !!user,
  };
  for (const [mode, allowed] of Object.entries(access)) {
    $(`[data-mode="${mode}"]`).hidden = !allowed;
  }
  $("#assistedPanel").hidden = !can("assist");
  $("#restoreDraft").hidden = !user || !state.draft;
  $("#portalSignIn").hidden = !!user;
  $("#portalSignIn").textContent =
    state.portal === "admin" ? "Admin & staff sign in" : "Customer sign in";
  const customerNav = $('.site-header [data-mode="customer"]');
  customerNav.textContent =
    state.portal === "admin" ? "Assisted booking" : "Find a facility";
  $('.site-header [data-mode="bookings"]').textContent =
    state.portal === "admin" ? "Applications" : "My bookings";
}
async function loadHome() {
  const admin = state.portal === "admin";
  $("#homeEyebrow").textContent = admin
    ? "Admin & staff portal"
    : "Customer portal";
  $("#homeTitle").textContent = state.user
    ? `Welcome, ${state.user.name}`
    : admin
      ? "Manage community facilities"
      : "Book a space for your community";
  $("#homeDescription").textContent = admin
    ? state.user
      ? `Signed in as ${state.user.staff_role}. Choose a task below.`
      : "Sign in with a staff account to review applications and manage facility operations."
    : "Find a suitable facility, submit a booking request, and track everything from approval to payment.";
  const links = admin
    ? [
        [
          "staff",
          "Assessment",
          "Review applications, verify evidence and record decisions.",
          "assess",
        ],
        [
          "customer",
          "Assisted booking",
          "Submit or resume an application on behalf of a customer.",
          "assist",
        ],
        [
          "calendar",
          "Calendar & closures",
          "Check reservations and manage facility availability.",
          "calendar",
        ],
        [
          "finance",
          "Finance",
          "Manage waivers, refunds and payment reconciliation.",
          "finance",
        ],
        [
          "reports",
          "Reports",
          "Explore demand, utilisation and service performance.",
          "reports",
        ],
        [
          "admin",
          "Administration",
          "Configure facilities, rates, equipment and staff access.",
          "admin",
        ],
        [
          "audit",
          "Audit",
          "Inspect activity, decisions and audit integrity.",
          "audit",
        ],
        [
          "notifications",
          "Inbox & delivery",
          "Read messages and check delivery outcomes.",
          "messages",
        ],
      ].filter(
        (entry) => can(entry[3]) || (entry[0] === "calendar" && can("assist")),
      )
    : [
        [
          "customer",
          "Find a facility",
          "Compare facilities, dates, accessibility and prices.",
        ],
        [
          "bookings",
          "My bookings",
          "Track requests, upload evidence, amend, pay or cancel.",
        ],
        [
          "notifications",
          "My inbox",
          "Read decisions, payment requests and booking updates.",
        ],
      ];
  $("#homeActions").innerHTML = links
    .map(
      ([mode, title, description]) =>
        `<button class="portal-card" type="button" data-open-mode="${mode}"><h2>${title}</h2><p>${description}</p><span>Open ${title.toLowerCase()} →</span></button>`,
    )
    .join("");
  $("#homeStats").replaceChildren();
  if (state.user) {
    const result = await api("/bookings");
    const bookings = result.bookings;
    const metrics = [
      ["Applications", bookings.length],
      [
        "Awaiting review",
        bookings.filter((b) => ["pending", "needs_info"].includes(b.status))
          .length,
      ],
      ["Approved", bookings.filter((b) => b.status === "approved").length],
    ];
    $("#homeStats").innerHTML = metrics
      .map(
        ([label, count]) =>
          `<div class="portal-stat"><strong>${count}</strong><span>${label}</span></div>`,
      )
      .join("");
  }
}
async function signOut() {
  await api("/auth/logout", "POST", {});
  state.user = null;
  state.applicant = null;
  state.documents = [];
  state.draft = null;
  state.bookings = [];
  state.selected = null;
  $("#requestForm").reset();
  $("#bookingConfirmation").innerHTML = "";
  updateAccount();
  await setMode("home");
  showStep(1);
  notice("Signed out.");
}
async function setMode(mode) {
  if (
    state.portal === "admin" &&
    ["customer", "bookings"].includes(mode) &&
    !can("assist")
  )
    return;
  if (
    state.portal === "customer" &&
    ["staff", "calendar", "finance", "reports", "admin", "audit"].includes(mode)
  )
    return;
  if (
    ![
      "home",
      "help",
      ...(state.portal === "customer" ? ["customer"] : []),
    ].includes(mode) &&
    !state.user
  ) {
    openAuth();
    return;
  }
  const needs = {
    staff: "assess",
    finance: "finance",
    reports: "reports",
    admin: "admin",
    audit: "audit",
  };
  if (needs[mode] && !can(needs[mode])) return;
  state.mode = mode;
  for (const name of modes) $("#" + name + "Mode").hidden = name !== mode;
  $$(".site-header [data-mode]").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.mode === mode);
    b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
  });
  $("#" + mode + "Title").focus({ preventScroll: true });
  notice("");
  if (mode === "home") await loadHome();
  if (mode === "bookings" || mode === "staff") await loadBookings();
  if (mode === "notifications") await loadNotifications();
  if (mode === "calendar") await loadCalendar();
  if (mode === "finance") await loadFinance();
  if (mode === "reports") await loadReports();
  if (mode === "admin") await loadAdmin();
  if (mode === "audit") await loadAudit();
}
function renderVenues() {
  const attendance = Number($("#attendanceFilter").value || 1),
    access = $("#accessFilter").value,
    search = $("#searchFilter").value.toLowerCase(),
    equipment = $("#equipmentFilter").value;
  const matching = state.venues.filter(
    (v) =>
      v.capacity >= attendance &&
      (access === "any" || v.features.includes(access)) &&
      (equipment === "any" || v.equipment.includes(equipment)) &&
      [v.name, v.description, ...v.equipment, ...v.labels]
        .join(" ")
        .toLowerCase()
        .includes(search),
  );
  $("#venueList").innerHTML =
    matching
      .map(
        (v) =>
          `<button type="button" class="venue-card${state.venue === v.id ? " is-selected" : ""}" data-venue="${esc(v.id)}" aria-pressed="${state.venue === v.id}"><span class="selected-badge">Selected</span><p class="eyebrow">Community centre</p><h3>${esc(v.name)}</h3><p>${esc(v.description)}</p><div class="venue-meta"><span>Capacity ${v.capacity}</span><span>${money(v.rate_cents)} / hour</span><span>${v.opens}–${v.closes}</span></div><ul class="venue-features">${[...v.labels, ...v.equipment].map((x) => `<li>${esc(x)}</li>`).join("")}</ul><p class="venue-conditions">${esc(v.conditions)}</p></button>`,
      )
      .join("") ||
    empty(
      "No matching facility. Try another attendance, equipment or accessibility filter.",
    );
}
function selectedVenue() {
  return state.venues.find((v) => v.id === state.venue);
}
function showStep(step) {
  state.step = step;
  $$(".journey-step").forEach((p) => {
    p.hidden = Number(p.dataset.step) !== step;
    p.classList.toggle("is-active", !p.hidden);
  });
  $$("[data-step-indicator]").forEach((i) => {
    const n = Number(i.dataset.stepIndicator);
    i.classList.toggle("is-current", n === step);
    i.classList.toggle("is-complete", n < step);
    $("span", i).textContent = n < step ? "✓" : n;
    if (n === step) i.setAttribute("aria-current", "step");
    else i.removeAttribute("aria-current");
  });
  $(`[data-step="${step}"] h2`).focus({ preventScroll: true });
}
let availabilitySequence = 0;
async function loadAvailability(preselected = "") {
  const sequence = ++availabilitySequence;
  $("#slotList").textContent = "Checking calendar…";
  const result = await api(
    "/availability?venue=" +
      encodeURIComponent(state.venue) +
      "&date=" +
      encodeURIComponent($("#eventDate").value),
  );
  if (sequence !== availabilitySequence) return;
  $("#slotList").innerHTML = result.slots
    .map(
      (s) =>
        `<label class="${s.available ? "" : "is-unavailable"}"><input type="radio" name="slot" value="${s.value}" ${s.available ? "" : "disabled"} ${s.available && s.value === preselected ? "checked" : ""}><span><strong>${s.value}</strong><small>${s.available ? "Requestable" : "Reserved or closed"}</small></span></label>`,
    )
    .join("");
  if (result.closures.length)
    $("#slotList").insertAdjacentHTML(
      "beforeend",
      `<p class="help-text">Closure: ${result.closures.map((c) => esc(c.reason)).join("; ")}</p>`,
    );
  $$('input[name="slot"]').forEach((i) =>
    i.addEventListener("change", () => {
      const [s, e] = i.value.split("–");
      $("#setupTime").value = s;
      $("#cleanupTime").value = e;
      updateRequirements();
    }),
  );
}
function requestDetails() {
  return {
    venue: state.venue,
    eventDate: $("#eventDate").value,
    slot: $('input[name="slot"]:checked')?.value || "",
    eventName: $("#eventName").value.trim(),
    eventType: $("#eventType").value,
    attendance: Number($("#attendance").value),
    setupTime: $("#setupTime").value,
    cleanupTime: $("#cleanupTime").value,
    alcohol: $('input[name="alcohol"]:checked').value,
    notes: $("#bookingNotes").value,
    repeatCount: Number($("#repeatCount").value),
    documentIds: state.documents.map((d) => d.id),
    adult: $("#adultCheck").checked,
    privacy: $("#privacyCheck").checked,
    declaration: $("#declaration").checked,
    ...(state.applicant ? { applicantId: state.applicant } : {}),
  };
}
function requiredEvidence(b = requestDetails()) {
  const v = selectedVenue();
  const required = [];
  if (
    v &&
    (v.insurance_required ||
      ["Private celebration", "Workshop or class"].includes(b.eventType) ||
      b.attendance >= v.insurance_threshold)
  )
    required.push("insurance");
  if (b.alcohol === "Yes") required.push("permit");
  return required;
}
const minutes = (value) =>
  value ? Number(value.slice(0, 2)) * 60 + Number(value.slice(3)) : 0;
function updateRequirements() {
  const required = requiredEvidence();
  $("#evidenceRequirements").textContent = required.length
    ? "Required for this event: " +
      required.join(" and ") +
      ". Staff must verify these documents before approval."
    : "No mandatory evidence for these choices. You may still attach supporting documents.";
  $("#uploadedDocuments").innerHTML = state.documents
    .map(
      (d) =>
        `<div class="document-item"><strong>${esc(d.kind)}</strong> · ${esc(d.filename)} ${button("Remove", "remove-doc", d.id, "text-button")}</div>`,
    )
    .join("");
  const b = requestDetails(),
    v = selectedVenue(),
    amount = v
      ? Math.ceil(
          (Math.max(0, minutes(b.cleanupTime) - minutes(b.setupTime)) *
            v.rate_cents) /
            60,
        ) * b.repeatCount
      : 0;
  $("#feeEstimate").innerHTML =
    `<span>Indicative total · ${b.repeatCount} occurrence(s)</span><strong>${money(amount)}</strong>`;
}
async function nextStep(next) {
  notice("");
  if (state.step === 1) {
    const v = selectedVenue(),
      access = $("#accessFilter").value;
    if (
      !v ||
      !$("#attendanceFilter").reportValidity() ||
      v.capacity < Number($("#attendanceFilter").value) ||
      (access !== "any" && !v.features.includes(access))
    ) {
      notice("Select a facility matching your requirements.", true);
      return;
    }
    $("#selectedVenueName").textContent = v.name;
    $("#attendance").max = v.capacity;
    $("#attendance").value = $("#attendanceFilter").value;
    await loadAvailability();
  }
  if (state.step === 2 && !$('input[name="slot"]:checked')) {
    notice("Choose an available event date and time.", true);
    return;
  }
  if (state.step === 3) {
    if (!$("#requestForm").reportValidity()) return;
    const b = requestDetails(),
      v = selectedVenue(),
      [start, end] = b.slot.split("–");
    if (!b.eventName) {
      $("#eventNameError").textContent = "Enter a meaningful event name.";
      return;
    }
    if (
      b.setupTime < v.opens ||
      b.setupTime > start ||
      b.cleanupTime < end ||
      b.cleanupTime > v.closes
    ) {
      notice(
        `Setup and cleanup must cover ${b.slot} within ${v.opens}–${v.closes}.`,
        true,
      );
      return;
    }
    const missing = requiredEvidence().filter(
      (k) => !state.documents.some((d) => d.kind === k),
    );
    if (missing.length) {
      notice("Upload required evidence: " + missing.join(", ") + ".", true);
      return;
    }
  }
  if (next === 4) renderReview();
  showStep(next);
  updateRequirements();
}
function renderReview() {
  const b = requestDetails(),
    v = selectedVenue();
  const items = [
    ["Facility", v.name],
    ["Event", b.eventName + " · " + b.eventType],
    ["First occurrence", dateText(b.eventDate) + " · " + b.slot],
    ["Schedule", b.repeatCount + " weekly occurrence(s)"],
    ["Full reserved period", b.setupTime + "–" + b.cleanupTime],
    ["Attendance", b.attendance + " people"],
    ["Alcohol", b.alcohol],
    [
      "Evidence",
      state.documents.map((d) => d.kind + ": " + d.filename).join("; ") ||
        "Not required",
    ],
    ["Notes", b.notes || "None"],
  ];
  $("#reviewCard").innerHTML = items
    .map(
      ([a, b]) =>
        `<div class="review-item"><span>${a}</span><strong>${esc(b)}</strong></div>`,
    )
    .join("");
}
function draftPath() {
  return "/draft" + (state.applicant ? "?applicant=" + state.applicant : "");
}
async function loadDraft() {
  state.draft = state.user ? (await api(draftPath())).draft : null;
  updateAccount();
}
async function saveDraft() {
  if (!state.user) {
    openAuth();
    notice("Sign in, then save your draft.");
    return;
  }
  await api(draftPath(), "PUT", requestDetails());
  $("#saveState").textContent = "Saved to account";
  await loadDraft();
  notice("Draft saved; an assisted draft belongs to the selected applicant.");
}
async function restoreDraft() {
  const d = state.draft;
  if (!d) return;
  state.venue = d.venue;
  renderVenues();
  $("#selectedVenueName").textContent = selectedVenue()?.name || "";
  for (const id of [
    "eventName",
    "eventType",
    "attendance",
    "setupTime",
    "cleanupTime",
    "eventDate",
    "repeatCount",
  ])
    if (d[id] !== undefined) $("#" + id).value = d[id];
  $("#bookingNotes").value = d.notes || "";
  $("#adultCheck").checked = !!d.adult;
  $("#privacyCheck").checked = !!d.privacy;
  $("#attendance").max = selectedVenue()?.capacity || 120;
  $(
    `input[name="alcohol"][value="${d.alcohol === "Yes" ? "Yes" : "No"}"]`,
  ).checked = true;
  const files = (
    await api(
      "/documents" + (state.applicant ? "?applicant=" + state.applicant : ""),
    )
  ).documents;
  state.documents = files.filter((x) => (d.documentIds || []).includes(x.id));
  showStep(2);
  await loadAvailability(d.slot);
  updateRequirements();
  notice("Draft restored. Availability is checked again before submission.");
}
async function uploadEvidence() {
  if (!state.user) {
    openAuth();
    notice("Sign in before uploading evidence.");
    return;
  }
  const file = $("#evidenceFile").files[0];
  if (!file) {
    notice("Choose a document first.", true);
    return;
  }
  const f = new FormData();
  f.append("file", file);
  f.append("kind", $("#evidenceKind").value);
  if (state.applicant) f.append("applicantId", String(state.applicant));
  const result = await api("/documents", "POST", f);
  state.documents.push(result.document);
  $("#evidenceFile").value = "";
  updateRequirements();
  notice("Evidence uploaded privately. Staff will verify authenticity.");
}
async function submit() {
  if (!state.user) {
    openAuth();
    notice("Sign in or create an account, then submit.");
    return;
  }
  if (!$("#declaration").checked) {
    notice("Confirm the booking declaration.", true);
    $("#declaration").focus();
    return;
  }
  const result = await api("/bookings", "POST", requestDetails());
  $("#bookingConfirmation").innerHTML = bookingHTML(result.booking, false);
  state.draft = null;
  state.documents = [];
  updateAccount();
  showStep(5);
  await loadInboxCount();
  notice(
    result.booking.reference +
      " saved. Open My bookings to follow assessment and payment.",
  );
}
function resetBooking() {
  state.documents = [];
  $("#requestForm").reset();
  $("#declaration").checked = false;
  $("#saveState").textContent = "Not saved";
  $("#repeatCount").value = "1";
  showStep(1);
  updateRequirements();
  notice("");
}
function historyHTML(b) {
  return `<details class="history"><summary>History, messages and versions (${b.history.length} events · ${b.version_count} versions)</summary><ol>${b.history.map((h) => `<li><strong>${esc(labels[h.action] || h.action.replaceAll("_", " "))}</strong><p>${esc(h.note)}</p><small>${esc(h.actor_name)} · ${stamp(h.created_at)} Darwin time</small></li>`).join("")}</ol></details>`;
}
function bookingHTML(b, actions = true) {
  const own = b.user_id === state.user?.id || can("assist"),
    active =
      ["pending", "needs_info", "approved"].includes(b.status) && !b.completed;
  return `<article class="booking-card" ${actions ? `id="booking-${b.id}"` : ""}><div class="case-header"><div><p class="eyebrow">${b.reference} · ${esc(b.channel)}</p><h2>${esc(b.event_name)}</h2></div><span class="status-pill ${b.status === "approved" ? "" : "waiting"}">${esc(statusText(b))}</span></div><div class="case-grid"><div><span>Facility</span><strong>${esc(b.venue_name)}</strong></div><div><span>First event (Darwin)</span><strong>${dateText(b.event_date)} · ${b.slot}</strong></div><div><span>Reserved access</span><strong>${b.setup_time}–${b.cleanup_time}</strong></div><div><span>Attendance</span><strong>${b.attendance} people</strong></div><div><span>Occurrences</span><strong>${b.occurrences.length} · ${b.occurrences.map(dateText).join(", ")}</strong></div><div><span>Authorised charge</span><strong>${money(b.amount_cents)}</strong></div></div><p>${esc(b.notes)}</p>${b.conditions ? `<div class="info-callout"><strong>Approval conditions:</strong> ${esc(b.conditions)}</div>` : ""}${b.documents.length ? `<div class="document-list">${b.documents.map((d) => `<div class="document-item"><a href="/api/documents/${d.id}" target="_blank" rel="noopener">${esc(d.kind)}: ${esc(d.filename)}</a> · ${d.verified ? "Verified" : "Awaiting staff verification"}</div>`).join("")}</div>` : ""}${historyHTML(b)}${actions && own && b.status === "needs_info" ? formReply(b) : ""}${b.amendments
    .filter((a) => a.status === "requested")
    .map(
      (a) =>
        `<div class="info-callout">Amendment awaiting review: ${esc(a.reason)}</div>`,
    )
    .join(
      "",
    )}${actions && own ? `<div class="action-row booking-actions">${active && b.event_date > state.today ? button("Request amendment", "amend", b.id) + button("Cancel booking", "cancel", b.id) : ""}${b.status === "approved" && b.payment && ["requested", "declined", "processing"].includes(b.payment.status) ? `<a class="primary-button" href="/checkout/${b.payment.id}">Open demo checkout</a>` : ""}${b.payment && ["paid", "refunded"].includes(b.payment.status) ? `<a class="secondary-button" href="/api/bookings/${b.id}/receipt" target="_blank" rel="noopener">Receipt / print PDF</a>` : ""}${b.status === "approved" ? `<a class="secondary-button" href="/api/bookings/${b.id}/calendar.ics">Add to calendar</a>` + button(b.feedback ? "Update feedback" : "Leave feedback", "feedback", b.id) : ""}${b.status === "cancelled" && b.payment?.status === "paid" && !b.refunds.some((r) => ["requested", "approved"].includes(r.status)) ? button("Request refund", "refund", b.id) : ""}</div>` : ""}${b.refunds.map((r) => `<p class="help-text">Refund ${labels[r.status] || r.status}: ${money(r.amount)} · ${esc(r.decision_reason || r.reason)} ${esc(r.reference || "")}</p>`).join("")}</article>`;
}
function formReply(b) {
  return `<form class="reply-form" data-id="${b.id}"><label>Reply to the staff request<textarea name="note" rows="3" maxlength="2000" required></textarea></label><button type="submit" class="primary-button">Send information</button></form>`;
}
async function loadBookings() {
  state.bookings = (await api("/bookings")).bookings;
  $("#myBookingList").innerHTML =
    state.bookings
      .filter((b) => b.user_id === state.user.id)
      .map((b) => bookingHTML(b))
      .join("") ||
    empty(
      "No applications yet. Choose Find a facility to start your first booking.",
    );
  $$(".reply-form").forEach((form) =>
    form.addEventListener(
      "submit",
      safe(async (e) => {
        e.preventDefault();
        await api(`/bookings/${form.dataset.id}/reply`, "POST", {
          note: $("textarea", form).value,
        });
        await loadBookings();
        notice("Reply recorded on the same application.");
      }),
    ),
  );
  if (can("assess")) renderQueue();
}
function renderQueue() {
  const filter = $("#staffFilter").value,
    bookings = state.bookings.filter(
      (b) => filter === "all" || b.status === filter,
    );
  if (!bookings.some((b) => b.id === state.selected))
    state.selected = bookings[0]?.id || null;
  $("#queueCount").textContent = bookings.length + " requests";
  $("#staffQueue").innerHTML =
    bookings
      .map(
        (b) =>
          `<button class="queue-item${b.id === state.selected ? " is-selected" : ""}" data-case="${b.id}" type="button"><span><strong>${b.reference}</strong><small>${esc(b.customer_name)} · ${dateText(b.event_date)}</small></span><span class="status-pill waiting">${esc(statusText(b))}</span></button>`,
      )
      .join("") ||
    empty(
      state.bookings.length
        ? "No matching requests."
        : "No booking requests yet. Customer requests will appear here after they submit a booking.",
    );
  const b = bookings.find((b) => b.id === state.selected);
  if (!b) {
    $("#staffCase").innerHTML = empty(
      state.bookings.length
        ? "Select a request from the queue."
        : "No customer has requested a booking yet.",
    );
    return;
  }
  const v = state.venues.find((v) => v.id === b.venue_id);
  const missing = b.required_docs.filter(
    (kind) => !b.documents.some((d) => d.kind === kind && d.verified),
  );
  const decidable =
    ["pending", "needs_info"].includes(b.status) &&
    !b.completed &&
    b.user_id !== state.user.id &&
    b.event_date > state.today;
  $("#staffCase").innerHTML =
    `<p class="eyebrow">Applicant</p><h2>${esc(b.customer_name)}</h2><p>${esc(b.customer_email)}</p>${bookingHTML(b, false)}<div class="info-callout"><strong>Decision checks:</strong> capacity ${b.attendance} / ${v?.capacity || "current limit"}; alcohol ${b.alcohol}; ${missing.length ? "verification needed: " + missing.join(", ") : "required evidence complete"}. Server rechecks calendar conflicts on approval.</div><div class="booking-actions">${b.documents
      .filter((d) => !d.verified)
      .map((d) => button("Verify " + d.kind, "verify-doc", d.id))
      .join(
        "",
      )}${b.status === "pending" && b.phase !== "under_review" ? button("Start assessment", "start-review", b.id) : ""}</div>${decidable ? `<label>Decision reason<textarea id="decisionReason" rows="3" maxlength="2000" required></textarea></label><label>Approval conditions<textarea id="decisionConditions" rows="2" maxlength="2000" placeholder="Key collection, cleaning, permit conditions…"></textarea></label><div class="action-row decision-actions">${button("Request information", "decision", b.id + ":needs_info")}${button("Reject", "decision", b.id + ":rejected")}${button("Accept", "decision", b.id + ":approved", "primary-button")}</div>` : ""}${b.status === "approved" && b.payment?.status === "paid" && !b.completed ? button("Mark event completed", "complete", b.id) : ""}${b.amendments
      .filter((a) => a.status === "requested")
      .map(
        (a) =>
          `<div class="field-card"><h3>Proposed amendment</h3><p>${esc(a.reason)}</p><p>${dateText(a.proposed.eventDate)} · ${esc(a.proposed.setupTime)}–${esc(a.proposed.cleanupTime)} · ${esc(a.proposed.eventName)}</p>${button("Approve amendment", "amend-decision", a.id + ":yes")}${button("Reject amendment", "amend-decision", a.id + ":no")}</div>`,
      )
      .join("")}`;
}
function findBooking(id) {
  const b = state.bookings.find((x) => x.id === Number(id));
  if (!b) throw Error("Refresh the booking list and try again.");
  return b;
}
async function amendmentDialog(id) {
  const b = findBooking(id),
    options = state.venues
      .map(
        (v) =>
          `<option value="${esc(v.id)}" ${v.id === b.venue_id ? "selected" : ""}>${esc(v.name)}</option>`,
      )
      .join("");
  const html = `<p>The original period stays reserved until staff approve your change. Paid changes must retain the same charge; otherwise cancel and request a refund.</p><label>Facility<select name="venue">${options}</select></label>${field("First date", "eventDate", b.event_date, "date", 'required min="' + $("#eventDate").min + '" max="' + $("#eventDate").max + '"')}<label>Event time<select name="slot">${["09:00–12:00", "13:00–17:00", "18:00–22:00"].map((s) => `<option ${s === b.slot ? "selected" : ""}>${s}</option>`).join("")}</select></label>${field("Event name", "eventName", b.event_name, "text", 'required maxlength="120"')}${field("Attendance", "attendance", b.attendance, "number", 'required min="1"')}${field("Setup starts", "setupTime", b.setup_time, "time", "required")}${field("Cleanup finishes", "cleanupTime", b.cleanup_time, "time", "required")}${area("Reason for change", "reason")}`;
  dialog(
    "Request a booking amendment",
    formHTML(html, "Send amendment"),
    async (values) => {
      const proposed = {
        venue: values.venue,
        eventDate: values.eventDate,
        slot: values.slot,
        eventName: values.eventName,
        eventType: b.event_type,
        attendance: Number(values.attendance),
        setupTime: values.setupTime,
        cleanupTime: values.cleanupTime,
        alcohol: b.alcohol,
        notes: b.notes,
        repeatCount: b.occurrences.length,
        documentIds: b.documents.map((d) => d.id),
        adult: true,
        privacy: true,
        declaration: true,
      };
      await api("/bookings/" + b.id + "/amend", "POST", {
        proposed,
        reason: values.reason,
      });
      await loadBookings();
      notice(
        "Amendment sent for approval; the original reservation remains held.",
      );
    },
  );
}
async function loadApplicants() {
  const result = await api("/staff/customers");
  const selected = state.applicant;
  $("#assistedApplicant").innerHTML =
    '<option value="">My own request</option>' +
    result.customers
      .map(
        (c) =>
          `<option value="${c.id}">${esc(c.name)} · ${esc(c.email)}</option>`,
      )
      .join("");
  $("#assistedApplicant").value = selected || "";
}
async function loadInboxCount() {
  if (!state.user) return;
  const result = await api("/notifications");
  $("#unreadCount").textContent =
    result.notifications.filter((n) => !n.read).length || "";
}
async function loadNotifications() {
  const result = await api("/notifications");
  $("#notificationList").innerHTML =
    result.notifications
      .map(
        (n) =>
          `<article class="booking-card"><p class="eyebrow">${n.read ? "Read" : "New"} · ${stamp(n.created_at)}</p><h2>${esc(n.title)}</h2><p class="prewrap">${esc(n.body)}</p><div class="booking-actions">${n.booking_id ? button("Open booking", "open-booking", n.booking_id) : ""}${!n.read ? button("Mark read", "read-note", n.id) : ""}</div></article>`,
      )
      .join("") || empty("No notifications yet.");
  $("#outboxPanel").innerHTML = "";
  if (can("messages")) {
    const messages = (await api("/staff/outbox")).messages;
    $("#outboxPanel").innerHTML =
      "<h2>Durable delivery queue · local simulator</h2>" +
      messages
        .map(
          (m) =>
            `<details class="booking-card"><summary>${esc(m.recipient)} · ${esc(m.subject)} · ${labels[m.status]} (${m.attempts} attempt(s))</summary><p class="prewrap">${esc(m.body)}</p><div class="booking-actions">${button("Simulate delivery / retry", "delivery", m.id + ":delivered")}${button("Simulate provider failure", "delivery", m.id + ":failed")}</div></details>`,
        )
        .join("");
  }
  await loadInboxCount();
}
async function openBooking(id) {
  await loadBookings();
  const b = findBooking(id);
  if (can("assess")) {
    state.selected = b.id;
    await setMode("staff");
    renderQueue();
  } else if (b.user_id === state.user.id) {
    await setMode("bookings");
    $("#booking-" + id).scrollIntoView({ behavior: "smooth" });
  } else dialog(b.reference, bookingHTML(b, true));
}
function table(headers, rows) {
  return `<div class="table-scroll" tabindex="0"><table><thead><tr>${headers.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") : `<tr><td colspan="${headers.length}">No records in this view.</td></tr>`}</tbody></table></div>`;
}
async function loadCalendar() {
  const result = await api("/calendar");
  const venueOptions = result.venues
    .map((v) => `<option value="${esc(v.id)}">${esc(v.name)}</option>`)
    .join("");
  $("#calendarContent").innerHTML =
    `<div class="filter-grid"><label>Facility<select id="calendarVenue"><option value="all">All facilities</option>${venueOptions}</select></label><label>From date<input id="calendarFrom" type="date" value="${state.today}"></label></div><div id="calendarRows"></div><h2>Closures</h2>${table(
      ["Facility", "Date", "Hours", "Reason", "Action"],
      result.closures.map((c) => [
        esc(
          (result.venues.find((v) => v.id === c.venue_id) || {}).name ||
            c.venue_id,
        ),
        dateText(c.event_date),
        c.start_time + "–" + c.end_time,
        esc(c.reason),
        can("calendar")
          ? button("Reopen", "remove-closure", c.id)
          : "Read only",
      ]),
    )}${can("calendar") ? `<details class="booking-card"><summary>Add a maintenance or event closure</summary><form id="closureForm" class="form-grid"><label>Facility<select name="venue">${venueOptions}</select></label>${field("Date", "date", "", "date", 'required min="' + $("#eventDate").min + '"')}${field("Closure starts", "start", "06:00", "time", "required")}${field("Closure ends", "end", "23:59", "time", "required")}${area("Reason", "reason")}<button type="submit" class="primary-button">Reserve closure</button></form></details>` : ""}`;
  function render() {
    const facility = $("#calendarVenue").value,
      from = $("#calendarFrom").value;
    $("#calendarRows").innerHTML = table(
      ["Reference", "Facility", "Date", "Reserved period", "Status"],
      result.entries
        .filter(
          (e) =>
            (facility === "all" || e.venue_id === facility) &&
            e.event_date >= from,
        )
        .map((e) => [
          button(
            "DCF-" + String(e.id).padStart(6, "0"),
            "open-booking",
            e.id,
            "text-button",
          ),
          esc(
            (result.venues.find((v) => v.id === e.venue_id) || {}).name ||
              e.venue_id,
          ),
          dateText(e.event_date),
          e.setup_time + "–" + e.cleanup_time,
          labels[e.status],
        ]),
    );
  }
  render();
  $("#calendarVenue").addEventListener("change", render);
  $("#calendarFrom").addEventListener("change", render);
  $("#closureForm")?.addEventListener(
    "submit",
    safe(async (e) => {
      e.preventDefault();
      await api(
        "/closures",
        "POST",
        Object.fromEntries(new FormData(e.target)),
      );
      await loadCalendar();
      notice("Closure created. Public availability now excludes this period.");
    }),
  );
}
async function loadFinance() {
  const r = await api("/finance");
  $("#financeContent").innerHTML =
    `<div class="metric-grid"><article class="metric"><span>Currently paid charges</span><strong>${money(r.charges)}</strong></article><article class="metric"><span>Authorised refunds</span><strong>${money(r.refund_total)}</strong></article></div><div class="action-row">${button("Reconcile provider records", "reconcile", "", "primary-button")}${button("Authorise a fee waiver", "waiver")}</div><h2>Payment ledger</h2>${table(
      [
        "Booking",
        "Customer",
        "Amount",
        "Portal status",
        "Provider reference",
        "Ledger match",
      ],
      r.payments.map((p) => [
        button(
          "DCF-" + String(p.booking_id).padStart(6, "0"),
          "open-booking",
          p.booking_id,
          "text-button",
        ),
        esc(p.customer_name),
        money(p.amount),
        labels[p.status] || p.status,
        esc(p.provider_reference || "Pending"),
        p.ledger_reference
          ? esc(p.ledger_reference) +
            (p.amount === p.ledger_amount ? " · Amount matched" : " · MISMATCH")
          : "No provider charge",
      ]),
    )}<h2>Refund requests</h2>${table(
      ["Booking", "Amount", "Reason", "Status", "Decision"],
      r.refunds.map((f) => [
        String(f.booking_id),
        money(f.amount),
        esc(f.reason),
        labels[f.status] || f.status,
        f.status === "requested"
          ? button("Approve", "refund-decision", f.id + ":yes") +
            button("Reject", "refund-decision", f.id + ":no")
          : esc(f.decision_reason || "") + " " + esc(f.reference || ""),
      ]),
    )}`;
}
async function loadReports(query = "") {
  const r = (await api("/reports" + query)).report;
  $("#reportContent").innerHTML =
    `<form id="reportForm" class="filter-grid">${field("From date", "from", r.from_date, "date", "required")}${field("To date", "to", r.to_date, "date", "required")}<button class="primary-button" type="submit">Generate report</button><a class="secondary-button" href="/api/reports/export?from=${r.from_date}&to=${r.to_date}">Download CSV</a></form><div class="metric-grid">${Object.entries(
      r.metrics,
    )
      .map(
        ([key, value]) =>
          `<article class="metric"><span>${esc(key.replaceAll("_", " "))}</span><strong>${value === null ? "No data" : value}</strong></article>`,
      )
      .join(
        "",
      )}</div><h2>Approved utilisation, including setup and cleaning</h2>${table(
      ["Facility", "Approved hours", "Available hours", "Utilisation"],
      r.utilisation.map((u) => [
        esc(u.name),
        u.booked_hours,
        u.available_hours,
        `<meter min="0" max="100" value="${u.percent}" aria-label="${esc(u.name)} utilisation"></meter> ${u.percent}%`,
      ]),
    )}<div class="info-callout">${esc(r.definitions)}</div>`;
  $("#reportForm").addEventListener(
    "submit",
    safe(async (e) => {
      e.preventDefault();
      await loadReports("?" + new URLSearchParams(new FormData(e.target)));
    }),
  );
}
async function loadAdmin() {
  const [v, u] = await Promise.all([api("/admin/venues"), api("/admin/users")]);
  $("#adminContent").innerHTML =
    `<h2>Facilities and rules</h2><div class="booking-actions">${button("Add another facility", "new-venue", "", "primary-button")}<a class="secondary-button" href="/api/admin/backup">Download private recovery backup</a></div><p class="help-text">Backup includes private account data, encrypted documents and the encryption key. Keep it private; never commit it to GitHub.</p>${table(
      ["Facility", "Capacity", "Hourly rate", "Configuration", "Action"],
      v.venues.map((x) => [
        esc(x.name),
        x.capacity,
        money(x.rate_cents),
        `Version ${x.version} · ${x.active ? "Active" : "Inactive"}`,
        button("Edit", "edit-venue", x.id) +
          button("Versions", "venue-versions", x.id),
      ]),
    )}<h2>Account roles</h2>${table(
      ["Name", "Email", "Role", "Action"],
      u.users.map((x) => [
        esc(x.name),
        esc(x.email),
        esc(x.role === "customer" ? "Customer" : x.staff_role),
        x.id === state.user.id
          ? "Current administrator"
          : button("Change access", "change-role", x.id) +
            (x.role === "staff" ? button("Reset MFA", "reset-mfa", x.id) : ""),
      ]),
    )}`;
  state.adminVenues = v.venues;
  state.adminUsers = u.users;
}
async function editVenue(id) {
  const v = state.adminVenues?.find((x) => x.id === id) || {
    id: "",
    name: "",
    capacity: 50,
    rate_cents: 2500,
    opens: "06:00",
    closes: "23:59",
    insurance_threshold: 80,
    active: true,
    insurance_required: false,
    features: ["stepfree"],
    labels: ["Step-free entry"],
    equipment: ["Tables and chairs"],
    description: "A flexible community space.",
    conditions: "Responsible hirer must be 18+. Include setup and cleanup.",
  };
  const html =
    field(
      "Facility ID (lowercase letters and hyphens)",
      "id",
      v.id,
      "text",
      'required pattern="[a-z][a-z0-9-]*" ' + (id ? "readonly" : ""),
    ) +
    field("Facility name", "name", v.name, "text", "required") +
    field(
      "Capacity",
      "capacity",
      v.capacity,
      "number",
      'required min="1" max="1000"',
    ) +
    field(
      "Hourly fee (AUD)",
      "rate",
      v.rate_cents / 100,
      "number",
      'required min="0" max="1000" step="0.01"',
    ) +
    field("Opens", "opens", v.opens, "time", "required") +
    field("Closes", "closes", v.closes, "time", "required") +
    field(
      "Insurance required at attendance",
      "insurance_threshold",
      v.insurance_threshold,
      "number",
      'required min="1" max="1000"',
    ) +
    field("Equipment (comma separated)", "equipment", v.equipment.join(", ")) +
    field(
      "Accessibility codes (stepfree, parking, hearing)",
      "features",
      v.features.join(", "),
    ) +
    field(
      "Accessibility descriptions (comma separated)",
      "labels",
      v.labels.join(", "),
    ) +
    area("Description", "description", v.description) +
    area("Booking rules", "conditions", v.conditions) +
    `<label class="confirmation-check"><input name="active" type="checkbox" ${v.active ? "checked" : ""}><span>Active for new applications</span></label><label class="confirmation-check"><input name="insurance_required" type="checkbox" ${v.insurance_required ? "checked" : ""}><span>Insurance evidence required for every event</span></label>` +
    area("Change reason", "reason");
  dialog(
    id ? "Edit facility configuration" : "Add another community facility",
    formHTML(html, "Save configuration"),
    async (f) => {
      const split = (s) =>
        s
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
      const venue = {
        id: f.id,
        name: f.name,
        capacity: Number(f.capacity),
        rate_cents: Math.round(Number(f.rate) * 100),
        opens: f.opens,
        closes: f.closes,
        insurance_threshold: Number(f.insurance_threshold),
        equipment: split(f.equipment),
        features: split(f.features),
        labels: split(f.labels),
        description: f.description,
        conditions: f.conditions,
        active: !!f.active,
        insurance_required: !!f.insurance_required,
      };
      await api("/admin/venues", "POST", { venue, reason: f.reason });
      state.venues = (await api("/venues")).venues;
      renderVenues();
      await loadAdmin();
      notice(
        "Configuration version saved. Existing authorised booking charges are retained.",
      );
    },
  );
}
async function loadAudit() {
  const r = await api("/audit");
  $("#auditContent").innerHTML =
    `<div class="info-callout ${r.integrity.valid ? "" : "error-notice"}"><strong>${r.integrity.valid ? "Integrity verified" : "Integrity failure"}</strong> · ${r.integrity.count || "Check failed"} events${r.integrity.head ? '<p class="hash">Head: ' + r.integrity.head + "</p>" : ""}</div><p>Append-only, HMAC-linked events record actors and times. This local integrity control is not an external immutable logging service.</p>${table(
      ["Time (Darwin)", "Actor", "Action", "Entity", "Detail"],
      r.events.map((e) => [
        stamp(e.created_at),
        esc(e.actor_name || "Unauthenticated"),
        esc(e.action),
        esc(e.entity),
        esc(e.detail),
      ]),
    )}`;
}
async function profileDialog() {
  const r = await api("/profile");
  dialog(
    "Your account",
    formHTML(
      field("Name", "name", r.user.name, "text", "required") +
        field(
          "Email (login identifier)",
          "email",
          r.user.email,
          "email",
          "readonly",
        ) +
        field("Phone", "phone", r.profile.phone) +
        field("Organisation", "organisation", r.profile.organisation) +
        button("Change password", "password"),
      "Update profile",
    ),
    async (values) => {
      const saved = await api("/profile", "PUT", values);
      state.user = saved.user;
      updateAccount();
      notice("Contact details updated.");
    },
  );
}
async function demoMailbox() {
  const r = await api("/demo/mailbox");
  dialog(
    "Local demo mailbox",
    r.messages
      .map(
        (m) =>
          `<article class="booking-card"><p class="eyebrow">${esc(m.recipient)} · ${labels[m.status]}</p><h3>${esc(m.subject)}</h3><p class="prewrap">${esc(m.body)}</p>${m.body.includes("/?reset=") ? `<a href="${esc(m.body.slice(m.body.indexOf("/?reset=")))}">Open recovery / activation link</a>` : ""}</article>`,
      )
      .join("") ||
      empty("No messages have been created for the sample accounts."),
  );
}
const actions = {
  "remove-doc": async (id) => {
    state.documents = state.documents.filter((d) => d.id !== id);
    updateRequirements();
  },
  cancel: async (id) => {
    dialog(
      "Cancel booking",
      formHTML(
        "<p>Cancel all occurrences and release the reserved calendar period? A paid booking may be eligible for a separately approved refund.</p>",
        "Confirm cancellation",
      ),
      async () => {
        await api("/bookings/" + id + "/cancel", "POST", {});
        await loadBookings();
        notice("Cancelled; the calendar period has been released.");
      },
    );
  },
  amend: amendmentDialog,
  refund: async (id) =>
    dialog(
      "Request a refund",
      formHTML(area("Reason for refund", "reason"), "Submit refund request"),
      async (f) => {
        await api("/bookings/" + id + "/refund", "POST", f);
        await loadBookings();
        notice("Refund request sent to finance.");
      },
    ),
  feedback: async (id) => {
    const b = findBooking(id);
    dialog(
      "Booking feedback",
      formHTML(
        `<label>Experience rating<select name="rating">${[5, 4, 3, 2, 1].map((r) => `<option value="${r}" ${b.feedback?.rating === r ? "selected" : ""}>${r} / 5</option>`).join("")}</select></label>` +
          area("Optional comment", "comment", b.feedback?.comment || "", false),
        "Save feedback",
      ),
      async (f) => {
        await api("/bookings/" + id + "/feedback", "POST", {
          rating: Number(f.rating),
          comment: f.comment,
        });
        await loadBookings();
        notice("Feedback recorded for service reporting.");
      },
    );
  },
  "verify-doc": async (id) =>
    dialog(
      "Verify evidence",
      formHTML(
        "<p>Download and inspect the document before recording verification. Automated checks do not establish insurance or permit authenticity.</p>" +
          area("Verification reason", "note"),
        "Record verification",
      ),
      async (f) => {
        await api("/documents/" + id + "/verify", "POST", f);
        await loadBookings();
        notice("Evidence verification recorded.");
      },
    ),
  "start-review": async (id) => {
    await api("/bookings/" + id + "/start-review", "POST", {});
    await loadBookings();
  },
  decision: async (value) => {
    const [id, status] = value.split(":");
    const note = $("#decisionReason").value.trim();
    if (!note) {
      $("#decisionReason").setAttribute("aria-invalid", "true");
      $("#decisionReason").focus();
      throw Error("Enter a decision reason.");
    }
    const conditions = $("#decisionConditions").value;
    if (
      status === "rejected" &&
      !confirm(
        "Reject this application? The reason will be visible to the applicant.",
      )
    )
      return;
    await api("/bookings/" + id + "/decision", "POST", {
      status,
      note,
      conditions,
    });
    await loadBookings();
    notice("Decision recorded and notification queued.");
  },
  "amend-decision": async (value) => {
    const [id, answer] = value.split(":");
    dialog(
      "Decide amendment",
      formHTML(area("Reason for your decision", "note"), "Confirm decision"),
      async (f) => {
        await api("/amendments/" + id + "/decision", "POST", {
          approve: answer === "yes",
          note: f.note,
        });
        await loadBookings();
        notice("Amendment decision and version recorded.");
      },
    );
  },
  complete: async (id) =>
    dialog(
      "Complete this booking",
      formHTML(
        "<p>Demo mode allows early completion to demonstrate the final workflow. Normal mode requires all occurrences to have finished.</p>" +
          area("Completion note", "note"),
        "Mark completed",
      ),
      async (f) => {
        await api("/bookings/" + id + "/complete", "POST", f);
        await loadBookings();
        notice("Booking completed.");
      },
    ),
  "read-note": async (id) => {
    await api("/notifications/" + id + "/read", "POST", {});
    await loadNotifications();
  },
  "open-booking": openBooking,
  delivery: async (value) => {
    const [id, outcome] = value.split(":");
    await api("/staff/outbox/" + id + "/retry", "POST", { outcome });
    await loadNotifications();
    notice("Local provider simulation recorded; no external message was sent.");
  },
  "remove-closure": async (id) =>
    dialog(
      "Reopen facility period",
      formHTML(area("Reason for reopening", "note"), "Remove closure"),
      async (f) => {
        await api("/closures/" + id, "DELETE", f);
        await loadCalendar();
      },
    ),
  reconcile: async () => {
    const r = await api("/finance/reconcile", "POST", {});
    await loadFinance();
    notice(
      r.corrected +
        " timed-out payment(s) reconciled without duplicate authorisation.",
    );
  },
  "refund-decision": async (value) => {
    const [id, answer] = value.split(":");
    dialog(
      "Authorise refund decision",
      formHTML(area("Finance decision reason", "note"), "Confirm decision"),
      async (f) => {
        await api("/refunds/" + id + "/decision", "POST", {
          approve: answer === "yes",
          note: f.note,
        });
        await loadFinance();
        notice("Refund decision and reference recorded.");
      },
    );
  },
  waiver: async () => {
    const r = await api("/bookings");
    const eligible = r.bookings.filter(
      (b) =>
        ["pending", "approved"].includes(b.status) &&
        (!b.payment || ["requested", "declined"].includes(b.payment.status)),
    );
    dialog(
      "Authorise fee waiver",
      formHTML(
        `<label>Application<select name="booking">${eligible.map((b) => `<option value="${b.id}">${b.reference} · ${money(b.amount_cents)}</option>`).join("")}</select></label>` +
          field(
            "Waiver amount (AUD)",
            "amount",
            "",
            "number",
            'required min="0.01" step="0.01"',
          ) +
          area("Authorisation reason", "note"),
        "Apply waiver",
      ),
      async (f) => {
        await api("/bookings/" + f.booking + "/waiver", "POST", {
          amount_cents: Math.round(Number(f.amount) * 100),
          note: f.note,
        });
        await loadFinance();
        notice("Authorised waiver recorded.");
      },
    );
  },
  "venue-versions": async (id) => {
    const r = await api("/admin/venues/" + id + "/versions");
    dialog(
      "Configuration versions",
      table(
        [
          "Version",
          "Effective time (Darwin)",
          "Actor",
          "Hourly fee",
          "Rules",
          "Reason",
        ],
        r.versions.map((v) => [
          String(v.version),
          stamp(v.created_at),
          esc(v.actor_name || "Initial configuration"),
          money(v.content.rate_cents),
          esc(v.content.conditions),
          esc(v.reason),
        ]),
      ),
    );
  },
  "new-venue": async () => editVenue(""),
  "edit-venue": editVenue,
  "change-role": async (id) =>
    dialog(
      "Change account access",
      formHTML(
        `<label>Role<select name="role">${["customer", "service", "coordinator", "finance", "admin", "auditor"].map((x) => `<option>${x}</option>`).join("")}</select></label>` +
          area("Access change reason", "note"),
        "Update role",
      ),
      async (f) => {
        await api("/admin/users/" + id + "/role", "POST", f);
        await loadAdmin();
        notice("Role changed; the account’s previous sessions were revoked.");
      },
    ),
  "reset-mfa": async (id) =>
    dialog(
      "Authorise staff MFA reset",
      formHTML(area("Reason for resetting MFA", "note"), "Reset MFA"),
      async (f) => {
        await api("/admin/users/" + id + "/reset-mfa", "POST", f);
        await loadAdmin();
        notice(
          "Sessions revoked. The staff member must enrol a new authenticator after signing in.",
        );
      },
    ),
  password: async () => {
    $("#workDialog").close();
    openAuth("password");
  },
};
document.addEventListener(
  "click",
  safe(async (e) => {
    const action = e.target.closest("[data-action]");
    if (action) {
      e.preventDefault();
      const handler = actions[action.dataset.action];
      if (handler) await busy(action, () => handler(action.dataset.id));
      return;
    }
    const mode = e.target.closest("[data-mode], [data-open-mode]");
    if (mode) {
      await setMode(mode.dataset.mode || mode.dataset.openMode);
      return;
    }
    const card = e.target.closest("[data-venue]");
    if (card) {
      state.venue = card.dataset.venue;
      state.documents = [];
      renderVenues();
      updateRequirements();
      return;
    }
    const selected = e.target.closest("[data-case]");
    if (selected) {
      state.selected = Number(selected.dataset.case);
      renderQueue();
      return;
    }
    const refresh = e.target.closest("[data-refresh]");
    if (refresh) await setMode(refresh.dataset.refresh);
  }),
);
$("#authForm").addEventListener("submit", authSubmit);
$("#accountButton").addEventListener(
  "click",
  safe(() => (state.user ? profileDialog() : openAuth())),
);
$("#closeAuth").addEventListener("click", () => $("#authDialog").close());
$("#authBackLogin").addEventListener("click", () => openAuth("login"));
for (const [id, mode] of [
  ["loginTab", "login"],
  ["registerTab", "register"],
  ["forgotTab", "forgot"],
  ["passwordTab", "password"],
])
  $("#" + id).addEventListener("click", () => openAuth(mode));
$("#logoutButton").addEventListener("click", safe(signOut));
$("#closeWork").addEventListener("click", () => $("#workDialog").close());
$$("[data-next]").forEach((b) =>
  b.addEventListener(
    "click",
    safe(() => busy(b, () => nextStep(Number(b.dataset.next)))),
  ),
);
$$("[data-back]").forEach((b) =>
  b.addEventListener("click", () => showStep(Number(b.dataset.back))),
);
for (const id of [
  "attendanceFilter",
  "accessFilter",
  "searchFilter",
  "equipmentFilter",
])
  $("#" + id).addEventListener(
    id === "accessFilter" || id === "equipmentFilter" ? "change" : "input",
    renderVenues,
  );
$("#eventDate").addEventListener(
  "change",
  safe(() => loadAvailability()),
);
for (const id of [
  "eventType",
  "attendance",
  "setupTime",
  "cleanupTime",
  "repeatCount",
])
  $("#" + id).addEventListener("change", updateRequirements);
$$('input[name="alcohol"]').forEach((i) =>
  i.addEventListener("change", updateRequirements),
);
$("#saveDraft").addEventListener(
  "click",
  safe(() => busy($("#saveDraft"), saveDraft)),
);
$("#restoreDraft").addEventListener("click", safe(restoreDraft));
$("#uploadEvidence").addEventListener(
  "click",
  safe(() => busy($("#uploadEvidence"), uploadEvidence)),
);
$("#submitRequest").addEventListener(
  "click",
  safe(() => busy($("#submitRequest"), submit)),
);
$("#restartJourney").addEventListener("click", resetBooking);
$("#viewBookings").addEventListener(
  "click",
  safe(() => setMode("bookings")),
);
$("#refreshBookings").addEventListener("click", safe(loadBookings));
$("#refreshStaff").addEventListener("click", safe(loadBookings));
$("#staffFilter").addEventListener("change", renderQueue);
$("#demoMailbox").addEventListener("click", safe(demoMailbox));
$("#privacyInfo").addEventListener("click", () =>
  dialog(
    "Privacy notice",
    "<p>This coursework system collects account contact details, application information, evidence, decisions and transaction references to demonstrate facility booking. Staff access is restricted by role. Evidence contents are encrypted. Do not enter real personal or payment data in demo mode.</p><p>You can correct contact details in your profile. Retention and lawful disposal are operator responsibilities; this demo does not claim an approved Council privacy assessment.</p>",
  ),
);
$("#assistedApplicant").addEventListener(
  "change",
  safe(async () => {
    state.applicant = Number($("#assistedApplicant").value) || null;
    state.documents = [];
    resetBooking();
    await loadDraft();
    $("#assistedSummary").textContent = state.applicant
      ? "Applying on behalf of the selected customer. Their account sees the same application."
      : "Applying for your own account.";
  }),
);
$("#createApplicant").addEventListener("click", () =>
  dialog(
    "Add assisted applicant",
    formHTML(
      field("Applicant name", "name", "", "text", "required") +
        field("Applicant email", "email", "", "email", "required") +
        "<p>An activation link is placed in the durable message queue. No shared password is assigned.</p>",
      "Create applicant",
    ),
    async (f) => {
      const r = await api("/staff/customers", "POST", f);
      state.applicant = r.customer.id;
      await loadApplicants();
      await loadDraft();
      resetBooking();
      notice(
        "Applicant created; fill in the same booking form on their behalf.",
      );
    },
  ),
);
async function init() {
  const [session, catalog] = await Promise.all([
    api("/session"),
    api("/venues"),
  ]);
  state.user = session.user;
  const query = new URLSearchParams(location.search);
  if (
    state.user &&
    !query.has("reset") &&
    (state.user.role === "staff") !== (state.portal === "admin")
  ) {
    location.replace(
      (state.user.role === "staff" ? "/admin" : "/customer") + location.search,
    );
    return;
  }
  document.title = `DCF-BAS · ${state.portal === "admin" ? "Admin & staff" : "Customer"} portal`;
  document.body.dataset.portal = state.portal;
  $("#portalLabel").textContent =
    state.portal === "admin" ? "Admin & staff portal" : "Customer portal";
  state.demo = session.demo_mode;
  state.venues = catalog.venues;
  state.today = catalog.today;
  const next = new Date(catalog.today + "T12:00:00Z");
  next.setUTCDate(next.getUTCDate() + 1);
  $("#eventDate").min = next.toISOString().slice(0, 10);
  $("#eventDate").max = catalog.max_date;
  $("#eventDate").value = $("#eventDate").min;
  $("#eventName").maxLength = 120;
  renderVenues();
  updateAccount();
  updateRequirements();
  await loadDraft();
  if (state.user) {
    await loadInboxCount();
    if (can("assist")) await loadApplicants();
  }
  if (state.demo) {
    $("#demoTools").hidden = false;
    const demo = await api("/demo");
    $("#demoAccounts").innerHTML = demo.accounts
      .filter((a) => (a.role === "customer") === (state.portal === "customer"))
      .map(
        (a) =>
          `<button class="secondary-button demo-role" type="button" data-email="${a.email}">${esc(a.role)}</button>`,
      )
      .join("");
    $$(".demo-role").forEach((b) =>
      b.addEventListener("click", () => {
        openAuth("login");
        $('[name="email"]', $("#authForm")).value = b.dataset.email;
        $('[name="password"]', $("#authForm")).value = demo.password;
      }),
    );
  }
  await setMode(state.portal === "admin" && can("assess") ? "staff" : "home");
  if (query.has("reset")) openAuth("reset");
  if (query.has("booking") && state.user)
    await openBooking(query.get("booking"));
  if (query.has("paid") && state.user) await setMode("bookings");
}
$("#portalSignIn").addEventListener("click", () => openAuth());
init().catch((error) =>
  notice(
    "Could not load booking functions: " +
      error.message +
      " Start the updated server with python server.py demo.",
    true,
  ),
);
