// Optional Playwright acceptance run; always uses a separate temporary database.
const { chromium } = require("playwright");
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path"),
  assert = require("node:assert/strict");
const root = path.resolve(__dirname, ".."),
  temporary = fs.mkdtempSync(path.join(os.tmpdir(), "dcf-acceptance-"));
const python = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const env = {
  ...process.env,
  DATABASE_PATH: path.join(temporary, "test.sqlite3"),
  DEMO_MODE: "1",
};
execFileSync(
  python,
  [
    "-c",
    "from server import create_app; from features import seed_demo; app=create_app(); seed_demo(app)",
  ],
  { cwd: root, env },
);
const service = spawn(
  python,
  [
    "-c",
    "from server import create_app; create_app().run(host='127.0.0.1',port=8003,threaded=True)",
  ],
  { cwd: root, env, stdio: "ignore" },
);
const url = "http://127.0.0.1:8003";
let browser, current;
const errors = [],
  checks = [];
async function check(name, fn) {
  await fn();
  checks.push(name);
  console.log("PASS:", name);
}
async function modalSubmit(page, values) {
  for (const [name, value] of Object.entries(values))
    await page.locator('#workDialog [name="' + name + '"]').fill(String(value));
  await page.locator('#workDialog button[type="submit"]').click();
  await page.waitForFunction(() => !document.querySelector("#workDialog").open);
}
async function role(role) {
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url + (role === "customer" ? "/customer" : "/admin"));
  await page.waitForSelector("#demoTools");
  await page.locator("#demoTools summary").click();
  await page
    .locator('.demo-role[data-email="' + role + '@demo.example"]')
    .click();
  await page.locator('#authForm button[type="submit"]').click();
  if (role !== "customer") {
    await page.waitForSelector('#authForm input[name="code"]');
    await page.locator('#authForm button[type="submit"]').click();
  }
  await page.waitForFunction(() => !document.querySelector("#authDialog").open);
  await page.waitForSelector("#logoutButton");
  await page.click(
    '.site-header [data-mode="' +
      (role === "customer" || role === "service"
        ? "customer"
        : role === "finance"
          ? "finance"
          : role === "admin"
            ? "admin"
            : "staff") +
      '"]',
  );
  return page;
}
async function run() {
  for (let n = 0; n < 50; n++) {
    try {
      if ((await fetch(url + "/api/venues")).ok) break;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  const executable =
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
    (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined);
  browser = await chromium.launch({
    headless: true,
    ...(executable ? { executablePath: executable } : {}),
    args: ["--no-sandbox"],
  });
  await check("Entry page separates customer and admin portals", async () => {
    const page = await browser.newPage();
    await page.goto(url);
    assert.equal(
      await page.locator('button[data-portal="customer"]').count(),
      1,
    );
    assert.equal(await page.locator('button[data-portal="admin"]').count(), 1);
    await page.close();
  });
  await check(
    "Customer and admin buttons open login popups with signup links",
    async () => {
      const page = await browser.newPage();
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(url);
      for (const portal of ["customer", "admin"]) {
        await page.click('[data-portal="' + portal + '"]');
        await page.waitForSelector("#entryDemo");
        assert.equal(page.url(), url + "/");
        assert.equal(
          await page.locator('#entryForm input[name="email"]').isVisible(),
          true,
        );
        assert.equal(
          await page.locator('#entryForm input[name="password"]').isVisible(),
          true,
        );
        assert.equal(await page.locator("#entrySignup").isVisible(), true);
        await page.click("#entrySignup");
        assert.equal(
          await page.locator('#entryForm input[name="name"]').isVisible(),
          true,
        );
        await page.click("#entryLogin");
        await page.click("#entryClose");
      }
      await page.close();
    },
  );
  await check(
    "Customer signup creates a persistent account from the popup",
    async () => {
      const page = await browser.newPage();
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(url);
      await page.click('[data-portal="customer"]');
      await page.waitForSelector("#entryDemo");
      await page.click("#entrySignup");
      await page.fill('#entryForm [name="name"]', "New demonstration customer");
      await page.fill(
        '#entryForm [name="email"]',
        "popup-customer@example.com",
      );
      await page.fill(
        '#entryForm [name="password"]',
        "Popup customer password!",
      );
      await page.click('#entryForm button[type="submit"]');
      await page.waitForURL(url + "/customer");
      await page.waitForSelector("#logoutButton");
      assert.match(
        await page.locator("#accountButton").textContent(),
        /New demonstration customer/,
      );
      await page.reload();
      await page.waitForSelector("#logoutButton");
      await page.close();
    },
  );
  await check(
    "Admin signup requires verification and opens an empty request queue",
    async () => {
      const page = await browser.newPage();
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(url);
      await page.click('[data-portal="admin"]');
      await page.waitForSelector("#entryDemo");
      await page.click("#entrySignup");
      await page.fill(
        '#entryForm [name="name"]',
        "New demonstration administrator",
      );
      await page.fill('#entryForm [name="email"]', "popup-admin@example.com");
      await page.fill(
        '#entryForm [name="password"]',
        "Popup administrator password!",
      );
      await page.click('#entryForm button[type="submit"]');
      await page.waitForSelector('#entryForm [name="code"]');
      await page.click('#entryForm button[type="submit"]');
      await page.waitForURL(url + "/admin");
      await page.waitForSelector("#staffMode");
      assert.match(
        await page.locator("#staffQueue").textContent(),
        /No booking requests yet/,
      );
      assert.equal(await page.locator("#staffQueue [data-case]").count(), 0);
      await page.close();
    },
  );
  await check(
    "Popup email/password login opens the correct customer or staff section",
    async () => {
      for (const portal of ["customer", "admin"]) {
        const page = await browser.newPage();
        page.on("pageerror", (e) => errors.push(e.message));
        await page.goto(url);
        await page.click('[data-portal="' + portal + '"]');
        await page.waitForSelector("#entryDemo");
        await page.fill(
          '#entryForm [name="email"]',
          (portal === "admin" ? "auditor" : "customer") + "@demo.example",
        );
        await page.fill('#entryForm [name="password"]', "DemoBooking2026!");
        await page.click('#entryForm button[type="submit"]');
        if (portal === "admin") {
          await page.waitForSelector('#entryForm [name="code"]');
          await page.click('#entryForm button[type="submit"]');
        }
        await page.waitForURL(url + "/" + portal);
        await page.waitForSelector("#logoutButton");
        await page.close();
      }
    },
  );
  const customer = (current = await role("customer"));
  await check(
    "Portal dashboard and role routing stay separate after reload",
    async () => {
      assert.equal(
        await customer.locator("#portalLabel").textContent(),
        "Customer portal",
      );
      await customer.click('.site-header [data-mode="home"]');
      await customer.waitForSelector("#homeStats .portal-stat");
      assert.equal(
        await customer.locator("#homeActions .portal-card").count(),
        3,
      );
      await customer.goto(url + "/admin");
      await customer.waitForURL(url + "/customer");
      await customer.click('.site-header [data-mode="customer"]');
    },
  );
  await check(
    "Customer login exposes usable facility and booking screens",
    async () => {
      assert.equal(await customer.locator("[data-venue]").count(), 3);
      assert.equal(
        await customer.locator('[data-mode="staff"]').isVisible(),
        false,
      );
      await customer.locator("#equipmentFilter").selectOption("Projector");
      assert.equal(await customer.locator("[data-venue]").count(), 1);
      await customer.locator("#equipmentFilter").selectOption("any");
    },
  );
  await customer.locator('[data-venue="nightcliff"]').click();
  await customer.fill("#attendanceFilter", "40");
  await customer.click('[data-next="2"]');
  await customer.check('input[name="slot"][value="09:00–12:00"]');
  await customer.selectOption("#repeatCount", "2");
  await customer.click('[data-next="3"]');
  await customer.fill("#eventName", "Final-year inclusive workshop");
  await customer.selectOption("#eventType", "Workshop or class");
  await customer.fill("#setupTime", "08:30");
  await customer.fill("#cleanupTime", "12:30");
  await customer.check('input[name="alcohol"][value="Yes"]');
  await customer.check("#adultCheck");
  await customer.check("#privacyCheck");
  await check(
    "Adaptive form identifies insurance and alcohol permit evidence",
    async () => {
      assert.match(
        await customer.locator("#evidenceRequirements").textContent(),
        /insurance and permit/,
      );
      await customer.click('[data-next="4"]');
      assert.equal(await customer.locator('[data-step="3"]').isVisible(), true);
    },
  );
  await customer.setInputFiles(
    "#evidenceFile",
    path.join(root, "samples/insurance-demo.pdf"),
  );
  await customer.click("#uploadEvidence");
  await customer.waitForFunction(
    () =>
      document.querySelectorAll("#uploadedDocuments .document-item").length ===
      1,
  );
  await customer.selectOption("#evidenceKind", "permit");
  await customer.setInputFiles(
    "#evidenceFile",
    path.join(root, "samples/permit-demo.pdf"),
  );
  await customer.click("#uploadEvidence");
  await customer.waitForFunction(
    () =>
      document.querySelectorAll("#uploadedDocuments .document-item").length ===
      2,
  );
  await check(
    "Evidence uploads and account draft save/resume work",
    async () => {
      await customer.click("#saveDraft");
      await customer.waitForFunction(
        () =>
          document.querySelector("#saveState").textContent ===
          "Saved to account",
      );
      await customer.click("#restoreDraft");
      await customer.waitForSelector('input[name="slot"]:checked');
      await customer.click('[data-next="3"]');
      assert.equal(
        await customer.inputValue("#eventName"),
        "Final-year inclusive workshop",
      );
      assert.equal(
        await customer.locator("#uploadedDocuments .document-item").count(),
        2,
      );
    },
  );
  await customer.click('[data-next="4"]');
  await customer.check("#declaration");
  await customer.click("#submitRequest");
  await customer.waitForSelector('[data-step="5"]:visible');
  await customer.click("#viewBookings");
  await customer.waitForSelector("#myBookingList .booking-card");
  const booking = await customer.evaluate(async () => {
    const data = await (await fetch("/api/bookings")).json();
    return data.bookings.find(
      (b) => b.event_name === "Final-year inclusive workshop",
    );
  });
  assert.equal(booking.occurrences.length, 2);
  const bid = booking.id;
  const coordinator = (current = await role("coordinator"));
  await coordinator.waitForSelector("[data-case]");
  await coordinator.click('[data-case="' + bid + '"]');
  await check(
    "Staff return request and customer reply share the same reference",
    async () => {
      await coordinator.fill(
        "#decisionReason",
        "Please confirm accessible entry needs.",
      );
      await coordinator.click(
        '[data-action="decision"][data-id="' + bid + ':needs_info"]',
      );
      await coordinator.waitForFunction(() =>
        document
          .querySelector("#staffCase")
          .textContent.includes("More information requested"),
      );
      await customer.click("#refreshBookings");
      await customer.waitForSelector("#booking-" + bid + " .reply-form");
      await customer.fill(
        "#booking-" + bid + " .reply-form textarea",
        "Step-free entry is needed.",
      );
      await customer.click("#booking-" + bid + " .reply-form button");
      await customer.waitForFunction(
        (id) => !document.querySelector("#booking-" + id + " .reply-form"),
        bid,
      );
      await coordinator.click("#refreshStaff");
      await coordinator.waitForFunction(() =>
        document
          .querySelector("#staffCase")
          .textContent.includes("Step-free entry is needed."),
      );
    },
  );
  await check(
    "Human evidence verification gates approval and payment request",
    async () => {
      for (let i = 0; i < 2; i++) {
        await coordinator
          .locator('#staffCase [data-action="verify-doc"]')
          .first()
          .click();
        await modalSubmit(coordinator, {
          note: "Fictitious sample evidence inspected.",
        });
      }
      await coordinator.fill(
        "#decisionReason",
        "Required evidence and capacity checked.",
      );
      await coordinator.fill(
        "#decisionConditions",
        "Keep exits clear and leave the venue clean.",
      );
      await coordinator.click(
        '[data-action="decision"][data-id="' + bid + ':approved"]',
      );
      await coordinator.waitForFunction(
        () => !document.querySelector("#decisionReason"),
      );
      await customer.click("#refreshBookings");
      await customer.waitForSelector(
        "#booking-" + bid + ' a[href^="/checkout/"]',
      );
    },
  );
  await check(
    "Versioned amendment is approved before the changed booking is committed",
    async () => {
      await customer.click("#booking-" + bid + ' [data-action="amend"]');
      await modalSubmit(customer, {
        eventName: "Final-year accessible workshop",
        reason: "Clarify the event title.",
      });
      await coordinator.click("#refreshStaff");
      await coordinator.waitForSelector('[data-action="amend-decision"]');
      await coordinator.click(
        '[data-action="amend-decision"][data-id$=":yes"]',
      );
      await modalSubmit(coordinator, {
        note: "Event-title amendment accepted.",
      });
      await coordinator.waitForSelector("#decisionReason");
      await coordinator.fill("#decisionReason", "Amended event re-approved.");
      await coordinator.click(
        '[data-action="decision"][data-id="' + bid + ':approved"]',
      );
      await coordinator.waitForFunction(
        () => !document.querySelector("#decisionReason"),
      );
      await customer.click("#refreshBookings");
      await customer.waitForFunction(
        (id) =>
          document.querySelector("#booking-" + id + " h2").textContent ===
          "Final-year accessible workshop",
        bid,
      );
    },
  );
  await check(
    "Hosted demo checkout safely reconciles an authorisation timeout",
    async () => {
      await customer.click("#booking-" + bid + ' a[href^="/checkout/"]');
      await customer.waitForSelector("#checkoutDetails p");
      await customer.selectOption("#paymentOutcome", "timeout");
      await customer.click("#payButton");
      await customer.waitForFunction(() =>
        document
          .querySelector("#checkoutDetails")
          .textContent.includes("processing"),
      );
      await customer.click("#payButton");
      await customer.waitForSelector("#checkoutLinks a");
      await customer.click("#checkoutLinks a");
      await customer.waitForSelector("#booking-" + bid);
      assert.match(
        await customer
          .locator("#booking-" + bid + " .status-pill")
          .textContent(),
        /Confirmed/,
      );
    },
  );
  await check(
    "Customer receipt and calendar downloads are available after payment",
    async () => {
      const calendarDownload = customer.waitForEvent("download");
      await customer.click("#booking-" + bid + ' a[href$="calendar.ics"]');
      const download = await calendarDownload;
      assert.match(download.suggestedFilename(), /\.ics$/);
      const response = await customer.request.get(
        url + "/api/bookings/" + bid + "/receipt",
      );
      assert.equal(response.status(), 200);
      assert.match(await response.text(), /simulated payment receipt/);
    },
  );
  const finance = (current = await role("finance"));
  await finance.waitForSelector("#financeContent table");
  await check(
    "Finance role sees payment controls and cannot see assessment navigation",
    async () => {
      assert.equal(
        await finance.locator('[data-mode="staff"]').isVisible(),
        false,
      );
      assert.match(
        await finance.locator("#financeContent").textContent(),
        /DEMO-PAY-/,
      );
      await finance.click('[data-action="reconcile"]');
    },
  );
  await check(
    "Cancellation, refund request and authorised finance refund work",
    async () => {
      await customer.click("#booking-" + bid + ' [data-action="cancel"]');
      await modalSubmit(customer, {});
      await customer.waitForSelector(
        "#booking-" + bid + ' [data-action="refund"]',
      );
      await customer.click("#booking-" + bid + ' [data-action="refund"]');
      await modalSubmit(customer, { reason: "Event no longer needed." });
      await finance.click('[data-refresh="finance"]');
      await finance.waitForSelector('[data-action="refund-decision"]');
      await finance
        .locator('[data-action="refund-decision"][data-id$=":yes"]')
        .first()
        .click();
      await modalSubmit(finance, {
        note: "Refund approved for the coursework cancellation.",
      });
      assert.match(
        await finance.locator("#financeContent").textContent(),
        /DEMO-REF-/,
      );
    },
  );
  await check(
    "Calendar closure administration updates requestable availability",
    async () => {
      await coordinator.click('[data-mode="calendar"]');
      await coordinator
        .locator("details")
        .filter({ hasText: "Add a maintenance" })
        .locator("summary")
        .click();
      const d = await customer.locator("#eventDate").getAttribute("min");
      await coordinator.selectOption(
        '#closureForm [name="venue"]',
        "nightcliff",
      );
      await coordinator.fill('#closureForm [name="date"]', d);
      await coordinator.fill('#closureForm [name="start"]', "18:00");
      await coordinator.fill('#closureForm [name="end"]', "22:00");
      await coordinator.fill(
        '#closureForm [name="reason"]',
        "Demonstration maintenance",
      );
      await coordinator.click('#closureForm button[type="submit"]');
      await coordinator.waitForFunction(() =>
        document
          .querySelector("#calendarContent")
          .textContent.includes("Demonstration maintenance"),
      );
      const result = await customer.request.get(
        url + "/api/availability?venue=nightcliff&date=" + d,
      );
      assert.equal((await result.json()).slots[2].available, false);
    },
  );
  const servicePage = (current = await role("service"));
  await servicePage.waitForFunction(
    () => document.querySelector("#assistedApplicant").options.length > 1,
  );
  const applicant = await servicePage
    .locator("#assistedApplicant option")
    .filter({ hasText: "Community Hirer" })
    .getAttribute("value");
  await check(
    "Customer Service creates and resumes the same assisted application",
    async () => {
      await servicePage.selectOption("#assistedApplicant", applicant);
      await servicePage.click('[data-venue="malak"]');
      await servicePage.click('[data-next="2"]');
      await servicePage.check('input[name="slot"][value="13:00–17:00"]');
      await servicePage.click('[data-next="3"]');
      await servicePage.fill("#eventName", "Assisted telephone booking");
      await servicePage.selectOption("#eventType", "Community meeting");
      await servicePage.fill("#attendance", "20");
      await servicePage.check("#adultCheck");
      await servicePage.check("#privacyCheck");
      await servicePage.click("#saveDraft");
      await servicePage.waitForFunction(
        () =>
          document.querySelector("#saveState").textContent ===
          "Saved to account",
      );
      await servicePage.click("#restoreDraft");
      await servicePage.waitForSelector('input[name="slot"]:checked');
      await servicePage.click('[data-next="3"]');
      await servicePage.click('[data-next="4"]');
      await servicePage.check("#declaration");
      await servicePage.click("#submitRequest");
      await servicePage.waitForSelector('[data-step="5"]:visible');
      await customer.click("#refreshBookings");
      await customer.waitForFunction(() =>
        document
          .querySelector("#myBookingList")
          .textContent.includes("Assisted telephone booking"),
      );
    },
  );
  await check(
    "Queued message provider failure can be retried without losing portal status",
    async () => {
      await servicePage.click('[data-mode="notifications"]');
      await servicePage.waitForSelector("#outboxPanel details");
      await servicePage
        .locator("#outboxPanel details")
        .first()
        .locator("summary")
        .click();
      await servicePage
        .locator('#outboxPanel [data-action="delivery"][data-id$=":failed"]')
        .first()
        .click();
      await servicePage.waitForFunction(() =>
        document.querySelector("#outboxPanel").textContent.includes("Failed"),
      );
      await servicePage
        .locator("#outboxPanel details")
        .first()
        .locator("summary")
        .click();
      await servicePage
        .locator('#outboxPanel [data-action="delivery"][data-id$=":delivered"]')
        .first()
        .click();
      await servicePage.waitForFunction(() =>
        document
          .querySelector("#outboxPanel")
          .textContent.includes("Delivered"),
      );
    },
  );
  const admin = (current = await role("admin"));
  await admin.click('[data-mode="admin"]');
  await admin.waitForSelector("#adminContent table");
  await check(
    "Facility configuration adds a usable new venue and a versioned rule set",
    async () => {
      await admin.click('[data-action="new-venue"]');
      await modalSubmit(admin, {
        id: "sample-annex",
        name: "Sample Community Annex",
        reason: "Demonstrate configuration-based expansion.",
      });
      await admin.waitForFunction(() =>
        document
          .querySelector("#adminContent")
          .textContent.includes("Sample Community Annex"),
      );
      await customer.reload();
      await customer.click('[data-mode="customer"]');
      await customer.waitForSelector("[data-venue]");
      await customer.fill("#attendanceFilter", "40");
      await customer.waitForSelector('[data-venue="sample-annex"]');
    },
  );
  await check(
    "Role reports export CSV and show source-defined metrics",
    async () => {
      await admin.click('[data-mode="reports"]');
      await admin.waitForSelector("#reportContent meter");
      assert.match(
        await admin.locator("#reportContent").textContent(),
        /elapsed submission-to-first-decision/,
      );
      const wait = admin.waitForEvent("download");
      await admin.click("#reportForm a");
      assert.match((await wait).suggestedFilename(), /\.csv$/);
    },
  );
  await check(
    "Audit integrity verifies and private backup downloads through administrator access",
    async () => {
      await admin.click('[data-mode="audit"]');
      await admin.waitForSelector("#auditContent table");
      assert.match(
        await admin.locator("#auditContent").textContent(),
        /Integrity verified/,
      );
      await admin.click('[data-mode="admin"]');
      const wait = admin.waitForEvent("download");
      await admin.click('a[href="/api/admin/backup"]');
      const download = await wait;
      assert.match(download.suggestedFilename(), /private-backup\.zip$/);
    },
  );
  await check(
    "Admin request details offer Accept/Reject and rejection reaches the customer",
    async () => {
      const booking = await customer.evaluate(async () => {
        const catalog = await api("/venues");
        const day = new Date(catalog.today + "T12:00:00Z");
        day.setUTCDate(day.getUTCDate() + 55);
        return (
          await api("/bookings", "POST", {
            venue: "malak",
            eventDate: day.toISOString().slice(0, 10),
            slot: "18:00–22:00",
            eventName: "Request to review and reject",
            eventType: "Community meeting",
            attendance: 20,
            setupTime: "18:00",
            cleanupTime: "22:00",
            alcohol: "No",
            notes: "",
            declaration: true,
            adult: true,
            privacy: true,
          })
        ).booking;
      });
      await admin.click('.site-header [data-mode="staff"]');
      await admin.waitForSelector('[data-case="' + booking.id + '"]');
      await admin.click('[data-case="' + booking.id + '"]');
      assert.equal(
        await admin
          .locator('#staffCase [data-id="' + booking.id + ':approved"]')
          .textContent(),
        "Accept",
      );
      assert.equal(
        await admin
          .locator('#staffCase [data-id="' + booking.id + ':rejected"]')
          .textContent(),
        "Reject",
      );
      await admin.fill(
        "#decisionReason",
        "This event is outside the permitted facility use.",
      );
      admin.once("dialog", (dialog) => dialog.accept());
      await admin.click('#staffCase [data-id="' + booking.id + ':rejected"]');
      await admin.waitForFunction(() =>
        document.querySelector("#staffCase").textContent.includes("Rejected"),
      );
      await customer.click('.site-header [data-mode="bookings"]');
      await customer.waitForSelector("#booking-" + booking.id);
      assert.match(
        await customer.locator("#booking-" + booking.id).textContent(),
        /Rejected/,
      );
    },
  );
  await check("Mobile reflow and HTML-escaped user content", async () => {
    await customer.setViewportSize({ width: 390, height: 844 });
    await customer.click('[data-mode="bookings"]');
    await customer.waitForSelector("#myBookingList .booking-card");
    assert.equal(
      await customer.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      true,
    );
    await customer.screenshot({
      path: path.join(temporary, "mobile.png"),
      fullPage: true,
    });
    await customer.click("#accountButton");
    await modalSubmit(customer, { name: "<img src=x onerror=alert(1)> Demo" });
    assert.equal(await customer.locator("#accountButton img").count(), 0);
  });
  assert.deepEqual(errors, []);
  console.log(
    "PASS:",
    checks.length,
    "browser acceptance workflows; no JavaScript errors.",
  );
}
run()
  .catch(async (error) => {
    console.error(error);
    if (current)
      try {
        console.error(
          "Visible error:",
          await current.locator("#notice").textContent(),
        );
        console.error(
          "Dialog error:",
          await current.locator("#workError").textContent(),
        );
      } catch {}
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
    service.kill("SIGTERM");
    await new Promise((r) => setTimeout(r, 500));
    fs.rmSync(temporary, { recursive: true, force: true });
  });
