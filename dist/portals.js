"use strict";
const $ = (selector) => document.querySelector(selector);
const entry = {
  portal: "customer",
  mode: "login",
  csrf: "",
  demo: null,
  challenge: null,
};
const escapeText = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
async function request(path, payload) {
  const response = await fetch("/api" + path, {
    method: payload ? "POST" : "GET",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": entry.csrf },
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  const result = await response.json();
  if (!response.ok)
    throw Error(result.error || "Could not complete this request.");
  if (result.csrf) entry.csrf = result.csrf;
  return result;
}
function render(mode) {
  entry.mode = mode;
  entry.challenge = null;
  const label = entry.portal === "admin" ? "Admin" : "Customer";
  $("#entryTitle").textContent =
    `${label} ${mode === "register" ? "sign up" : mode === "forgot" ? "password recovery" : "sign in"}`;
  $("#entryDescription").textContent =
    mode === "register"
      ? `Create your ${label.toLowerCase()} account.`
      : mode === "forgot"
        ? "Enter your email to request a password recovery link."
        : `Enter your email and password to access the ${label.toLowerCase()} section.`;
  $("#entryForm").innerHTML =
    `${mode === "register" ? '<label>Full name<input name="name" autocomplete="name" maxlength="100" required></label>' : ""}<label>Email address<input name="email" type="email" autocomplete="email" maxlength="254" required></label>${mode !== "forgot" ? `<label>${mode === "register" ? "Password (12+ characters)" : "Password"}<input name="password" type="password" autocomplete="${mode === "register" ? "new-password" : "current-password"}" ${mode === "register" ? 'minlength="12"' : ""} maxlength="128" required></label>` : ""}<button class="primary-button" type="submit">${mode === "register" ? "Create account" : mode === "forgot" ? "Send recovery link" : "Sign in"}</button>`;
  $("#entryError").textContent = "";
  $("#entryAccountPrompt").hidden = mode !== "login";
  $("#entryLoginPrompt").hidden = mode === "login";
  $("#entryForgot").hidden = mode !== "login";
  $("#entryDemo").hidden = !entry.demo || mode !== "login";
}
async function open(portal) {
  entry.portal = portal;
  entry.demo = null;
  render("login");
  if (!$("#entryDialog").open) $("#entryDialog").showModal();
  const submit = $('#entryForm button[type="submit"]');
  submit.disabled = true;
  for (const id of ["entrySignup", "entryLogin", "entryForgot"])
    $("#" + id).disabled = true;
  try {
    const session = await request("/session");
    entry.demo = session.demo_mode ? await request("/demo") : null;
    $("#entryDemo").hidden = !entry.demo || entry.mode !== "login";
  } catch (error) {
    $("#entryError").textContent = error.message;
  } finally {
    submit.disabled = false;
    for (const id of ["entrySignup", "entryLogin", "entryForgot"])
      $("#" + id).disabled = false;
  }
}
$("#entryForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = $('#entryForm button[type="submit"]');
  submit.disabled = true;
  $("#entryError").textContent = "";
  const values = Object.fromEntries(new FormData($("#entryForm")));
  try {
    const result = await request(
      entry.challenge
        ? "/auth/mfa"
        : entry.mode === "forgot"
          ? "/auth/reset-request"
          : "/auth/" + entry.mode,
      entry.challenge
        ? { challenge: entry.challenge, code: values.code }
        : { ...values, portal: entry.portal },
    );
    if (result.mfa_required) {
      entry.challenge = result.challenge;
      $("#entryTitle").textContent = "Verify admin access";
      $("#entryDescription").textContent =
        "Enter the six-digit authenticator code to complete sign in.";
      $("#entryForm").innerHTML =
        `${result.enrollment_secret ? `<p>Add this secret to your authenticator app for first-time setup:</p><code class="secret-code">${escapeText(result.enrollment_secret)}</code>` : ""}${result.demo_code ? `<p class="info-callout">Teacher demo verification code: <strong>${escapeText(result.demo_code)}</strong></p>` : ""}<label>Verification code<input name="code" value="${escapeText(result.demo_code || "")}" pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code" required></label><button class="primary-button" type="submit">Verify and sign in</button>`;
      for (const id of [
        "entryAccountPrompt",
        "entryLoginPrompt",
        "entryForgot",
        "entryDemo",
      ])
        $("#" + id).hidden = true;
      return;
    }
    if (entry.mode === "forgot") {
      $("#entryDescription").textContent = result.message;
      return;
    }
    const session = await request("/session");
    if (!session.user) throw Error("Please sign in to continue.");
    location.assign(session.user.role === "staff" ? "/admin" : "/customer");
  } catch (error) {
    $("#entryError").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
document
  .querySelectorAll("[data-portal]")
  .forEach((button) =>
    button.addEventListener("click", () => open(button.dataset.portal)),
  );
$("#entryClose").addEventListener("click", () => $("#entryDialog").close());
$("#entrySignup").addEventListener("click", () => render("register"));
$("#entryLogin").addEventListener("click", () => render("login"));
$("#entryForgot").addEventListener("click", () => render("forgot"));
$("#entryDemoFill").addEventListener("click", () => {
  const account = entry.demo?.accounts.find(
    (account) => account.role === entry.portal,
  );
  if (!account) return;
  $('#entryForm [name="email"]').value = account.email;
  $('#entryForm [name="password"]').value = entry.demo.password;
});
