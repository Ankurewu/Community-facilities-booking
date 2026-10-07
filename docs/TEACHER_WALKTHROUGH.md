# A 10–15 minute teacher demonstration

Start `START_DEMO.bat` and keep the server window open. Use separate browser profiles/incognito windows for customer and staff. Avoid sensitive real details. Screens are the product; source/tests/traceability are the supporting evidence.

1. **Explain the service gap (1 minute).** Show facility comparison before registration: access, equipment, rules, hourly fees and capacity. State that these are coursework configuration, not confirmed Council data. Explain the shared record from enquiry to confirmation.
2. **Apply (2 minutes).** Use customer@demo.example via the demo panel. Choose Nightcliff, a future morning slot and two weekly occurrences. Enter a workshop, 40 people, setup 08:30 and cleanup 12:30. Confirm adult responsibility and privacy. Set alcohol to Yes; insurance and permit become required. Try continuing without evidence to show a recoverable error. Upload both sample PDFs, save a draft, resume it and submit.
3. **Show traceability (1 minute).** The customer gets a unique reference and authoritative status. The recurring dates and total access fee appear on the same record. Open History to show actor/time/version information.
4. **Assess with human control (2 minutes).** Sign in as coordinator in another browser. Complete the demo MFA step. Select the new case, Start assessment, request information with a reason. Customer replies on the same reference. Coordinator downloads/inspects the fictitious evidence, records verification, adds approval conditions and approves. Show that evidence gates approval.
5. **Pay and reconcile (2 minutes).** Customer refreshes My bookings and opens demo checkout. Choose authorised-then-timeout. Explain that card information is never collected. Retry: it reconciles the existing reference, not another charge. Return to the confirmed application, open the receipt and download the calendar file.
6. **Change and cancel (2 minutes).** Request an amendment before paying or choose a same-charge change after payment. Original time remains held until coordinator approval; accepted changes create a version and return for assessment. Then cancel and request a refund. A finance officer approves the refund with a reason/reference. Explain role separation and the negative permission tests.
7. **Operations (2 minutes).** Customer Service selects the same customer in the assisted panel, saves/resumes/submits a new application. Create a closure in Calendar and show blocked availability. Administrator changes a rate/equipment rule or adds a sample venue. Show the delivery queue failure/retry simulator.
8. **Evidence and limits (1 minute).** Open Reports and CSV export; explain unique applications versus recurring hours and elapsed cycle time versus active staff effort. Show audit integrity and a private backup. Discuss automated acceptance tests, recovery rehearsal, real integration gaps and independent accessibility/security/UAT still needed.

## A shorter reliable path

Use the three seeded customer applications if time is limited. They are standard community meetings requiring no mandatory evidence. Pick one in coordinator Assessment, approve with conditions, then switch to the customer and demonstrate checkout, receipt, cancellation/refund and finance. Add one new complex application to demonstrate adaptive evidence.

## Practical tips

- Stop the old server before starting the downloaded version; otherwise your browser may still show old code.
- Use Refresh on customer/staff screens after actions in another browser; the demo does not claim push notifications.
- If a staff TOTP code was just used, wait until the next 30-second code window before signing into that same account again. Different role accounts are independent.
- The demo allows early event completion for presentation. Normal mode waits until all dates finish.
- The local demo database persists. Restarting does not reset your work or create duplicate seeded records. For a fresh rehearsal, **stop the server** and rename `instance/demo.sqlite3` and `instance/demo.key` together to a private backup; never erase real data blindly.
- If a conflict occurs, choose another date/facility/time. That is the intended transactional control.
- Be prepared to explain why simulated integrations are separated from the authoritative application record and what real deployment would need.
- Use your actual work and contribution when updating the report's contribution statement. The demonstration cannot guarantee an HD mark.
