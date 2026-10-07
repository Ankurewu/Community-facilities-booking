"use strict";
const id = location.pathname.split("/").pop();
let csrf = "",
  booking = null;
const $ = (s) => document.querySelector(s);
const money = (c) =>
  new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(
    c / 100,
  );
async function api(path, method = "GET", data) {
  const r = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  const result = await r.json();
  if (!r.ok) throw Error(result.error || "Request failed");
  return result;
}
function render(p) {
  $("#checkoutDetails").replaceChildren();
  const text = document.createElement("p");
  text.textContent = `${booking.reference} · ${money(p.amount)} · Status: ${p.status}`;
  $("#checkoutDetails").append(text);
  if (p.status === "paid" || p.status === "refunded") {
    $("#checkoutForm").hidden = true;
    $("#checkoutNotice").textContent =
      "Demonstration payment recorded. Your booking portal is the authoritative status source.";
    const link = document.createElement("a");
    link.href = "/customer?paid=1";
    link.className = "primary-button";
    link.textContent = "Return to My bookings";
    $("#checkoutLinks").replaceChildren(link);
  } else {
    $("#payButton").textContent =
      p.status === "processing"
        ? "Reconcile authorisation (no second charge)"
        : "Confirm demo payment";
  }
}
$("#checkoutForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#payButton").disabled = true;
  try {
    const r = await api("/payments/" + id + "/pay", "POST", {
      outcome: $("#paymentOutcome").value,
    });
    render(r.payment);
    if (r.payment.status === "processing")
      $("#checkoutNotice").textContent =
        "The demo provider authorised the payment but its response timed out. Retry to reconcile the existing transaction. Do not create another payment.";
    if (r.payment.status === "declined")
      $("#checkoutNotice").textContent =
        "Declined by the demo provider. No money charged. You can retry.";
  } catch (err) {
    $("#checkoutNotice").textContent = err.message;
  } finally {
    $("#payButton").disabled = false;
  }
});
(async () => {
  const s = await api("/session");
  csrf = s.csrf;
  booking = await api("/payments/" + id);
  render(booking.payment);
  if (booking.booking_status !== "approved") {
    $("#checkoutForm").hidden = true;
    $("#checkoutNotice").textContent =
      "This booking is no longer awaiting payment.";
  }
})().catch((e) => {
  $("#checkoutNotice").textContent =
    e.message + " Sign in to the portal as the applicant.";
  $("#checkoutForm").hidden = true;
});
