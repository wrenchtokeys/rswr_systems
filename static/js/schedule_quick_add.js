// Quick-add a job from the schedule (FIELD_OPS S10).
//
// A customer calls; this puts the job on a day in one submit. The endpoint
// (POST /tech/schedule/quick-job/) creates the job through the normal save()
// path and books the time through S4's confirm_appointment, in one
// transaction — so a booking failure leaves no unscheduled orphan behind.
//
// Plain IIFE + event delegation, house helpers only (window.UI), no
// framework and no npm. Same shape as schedule_dispatch.js / schedule_swap.js.
(function () {
    'use strict';

    var modal = document.getElementById('quick-job-modal');
    if (!modal) { return; }

    var POST_URL = modal.getAttribute('data-post-url');
    var SEARCH_URL = modal.getAttribute('data-search-url');

    var form = document.getElementById('quick-job-form');
    var custInput = document.getElementById('qj-customer');
    var results = document.getElementById('qj-customer-results');
    var chosenNote = document.getElementById('qj-customer-chosen');
    var newPerson = document.getElementById('qj-new-person');
    var duplicates = document.getElementById('qj-duplicates');
    var phoneInput = document.getElementById('qj-phone');
    var windowSelect = document.getElementById('qj-window');
    var exactWrap = document.getElementById('qj-exact');
    var priceRow = document.getElementById('qj-price-row');
    var errorLine = document.getElementById('qj-error');
    var submitBtn = document.getElementById('qj-submit');

    // Chosen existing customer id, or null when the typed name is a new
    // person. `confirmed` is set only after the shop answers the endpoint's
    // "did you mean this person?" with "no, different person".
    var chosenId = null;
    var confirmed = false;
    var busy = false;
    var searchTimer = null;

    var ACTIVE_TYPE_CLASSES = ['border-brand-500', 'bg-brand-50', 'text-brand-700'];
    var IDLE_TYPE_CLASSES = ['border-gray-300', 'text-gray-600'];

    function serviceType() {
        var pressed = modal.querySelector('[data-qj-type][aria-pressed="true"]');
        return pressed ? pressed.getAttribute('data-qj-type') : 'repair';
    }

    function setError(message) {
        if (!message) {
            errorLine.classList.add('hidden');
            errorLine.textContent = '';
            return;
        }
        errorLine.textContent = message;
        errorLine.classList.remove('hidden');
    }

    // --- service type ------------------------------------------------------
    modal.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-qj-type]');
        if (!btn) { return; }
        modal.querySelectorAll('[data-qj-type]').forEach(function (el) {
            var on = el === btn;
            el.setAttribute('aria-pressed', on ? 'true' : 'false');
            ACTIVE_TYPE_CLASSES.forEach(function (c) { el.classList.toggle(c, on); });
            IDLE_TYPE_CLASSES.forEach(function (c) { el.classList.toggle(c, !on); });
        });
        // A replacement has no price book to fall back on, so the form
        // refuses one without a price. Ask only where it's actually needed.
        priceRow.classList.toggle('hidden', btn.getAttribute('data-qj-type') !== 'replacement');
    });

    // --- exact-time reveal -------------------------------------------------
    windowSelect.addEventListener('change', function () {
        exactWrap.classList.toggle('hidden', windowSelect.value !== 'EXACT');
    });

    // --- customer search ---------------------------------------------------
    function clearChoice() {
        chosenId = null;
        confirmed = false;
        chosenNote.classList.add('hidden');
        duplicates.classList.add('hidden');
        duplicates.innerHTML = '';
    }

    function renderResults(rows) {
        results.innerHTML = '';
        if (!rows.length) {
            results.classList.add('hidden');
            // Nobody matched: the typed name becomes a new individual, and a
            // phone is worth having while the shop is on the call.
            newPerson.classList.remove('hidden');
            return;
        }
        newPerson.classList.add('hidden');
        rows.forEach(function (row) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'w-full text-left min-h-11 px-3 py-2 hover:bg-gray-50 focus:bg-gray-50 focus:outline-none';
            btn.setAttribute('data-qj-pick', row.id);
            btn.setAttribute('data-qj-name', row.name);
            var line = '<span class="text-sm font-medium text-gray-900"></span>';
            btn.innerHTML = line;
            btn.querySelector('span').textContent = row.name;
            if (row.phone || row.summary) {
                var sub = document.createElement('span');
                sub.className = 'block text-xs text-gray-500';
                sub.textContent = [row.phone, row.summary].filter(Boolean).join(' · ');
                btn.appendChild(sub);
            }
            results.appendChild(btn);
        });
        results.classList.remove('hidden');
    }

    custInput.addEventListener('input', function () {
        clearChoice();
        var query = custInput.value.trim();
        window.clearTimeout(searchTimer);
        if (query.length < 2) {
            results.classList.add('hidden');
            newPerson.classList.add('hidden');
            return;
        }
        searchTimer = window.setTimeout(function () {
            // `type=any` is not a thing the endpoint knows; it defaults to
            // individuals, so ask for both and merge — a fleet account is a
            // perfectly normal thing to be booking for.
            Promise.all([
                fetch(SEARCH_URL + '?type=individual&q=' + encodeURIComponent(query),
                      { credentials: 'same-origin' }).then(function (r) { return r.json(); }),
                fetch(SEARCH_URL + '?type=fleet&q=' + encodeURIComponent(query),
                      { credentials: 'same-origin' }).then(function (r) { return r.json(); })
            ]).then(function (both) {
                renderResults((both[0].results || []).concat(both[1].results || []));
            }).catch(function () {
                // A dead search must not block the motion: the typed name can
                // still go through as a new person.
                results.classList.add('hidden');
                newPerson.classList.remove('hidden');
            });
        }, 200);
    });

    results.addEventListener('click', function (e) {
        var pick = e.target.closest('[data-qj-pick]');
        if (!pick) { return; }
        chosenId = pick.getAttribute('data-qj-pick');
        custInput.value = pick.getAttribute('data-qj-name');
        results.classList.add('hidden');
        newPerson.classList.add('hidden');
        duplicates.classList.add('hidden');
        chosenNote.textContent = 'Existing customer selected.';
        chosenNote.classList.remove('hidden');
    });

    // --- the endpoint's "did you mean this person?" ------------------------
    function renderDuplicates(suggestions) {
        duplicates.innerHTML = '';
        var intro = document.createElement('p');
        intro.className = 'text-sm text-gray-700 mb-2';
        intro.textContent = 'Already a customer?';
        duplicates.appendChild(intro);

        suggestions.forEach(function (s) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'w-full text-left min-h-11 px-3 py-2 mb-1 border border-gray-200 rounded-lg hover:bg-gray-50';
            btn.setAttribute('data-qj-pick-dup', s.id);
            var name = document.createElement('span');
            name.className = 'text-sm font-medium text-gray-900';
            name.textContent = s.name;
            btn.appendChild(name);
            if (s.phone || s.summary) {
                var sub = document.createElement('span');
                sub.className = 'block text-xs text-gray-500';
                sub.textContent = [s.phone, s.summary].filter(Boolean).join(' · ');
                btn.appendChild(sub);
            }
            duplicates.appendChild(btn);
        });

        var no = document.createElement('button');
        no.type = 'button';
        no.className = 'btn btn-secondary btn-sm mt-1';
        no.setAttribute('data-qj-different', '1');
        no.textContent = 'No, different person';
        duplicates.appendChild(no);
        duplicates.classList.remove('hidden');
    }

    duplicates.addEventListener('click', function (e) {
        var pick = e.target.closest('[data-qj-pick-dup]');
        if (pick) {
            chosenId = pick.getAttribute('data-qj-pick-dup');
            duplicates.classList.add('hidden');
            newPerson.classList.add('hidden');
            chosenNote.textContent = 'Existing customer selected.';
            chosenNote.classList.remove('hidden');
            form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', {cancelable: true}));
            return;
        }
        if (e.target.closest('[data-qj-different]')) {
            confirmed = true;
            duplicates.classList.add('hidden');
            form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', {cancelable: true}));
        }
    });

    // --- submit ------------------------------------------------------------
    function payload() {
        var body = {
            service_type: serviceType(),
            unit_number: document.getElementById('qj-unit').value.trim(),
            work_done: document.getElementById('qj-work').value.trim(),
            date: document.getElementById('qj-date').value,
            window: windowSelect.value,
            // The day the list on screen is showing, so the server can say
            // whether the new row belongs on it rather than the page guessing.
            on_screen_date: modal.getAttribute('data-day')
        };
        if (chosenId) {
            body.customer = chosenId;
        } else {
            body.new_customer_name = custInput.value.trim();
            body.new_customer_phone = phoneInput.value.trim();
            if (confirmed) { body.confirmed_new_customer = true; }
        }
        if (windowSelect.value === 'EXACT') {
            body.start_time = document.getElementById('qj-start').value;
            body.end_time = document.getElementById('qj-end').value;
        }
        var price = document.getElementById('qj-price');
        if (price && price.value) { body.price = price.value; }
        var tech = document.getElementById('qj-tech');
        if (tech && tech.value) { body.technician = tech.value; }
        return body;
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (busy) { return; }
        setError('');

        if (!custInput.value.trim()) {
            setError('Who is this job for?');
            custInput.focus();
            return;
        }

        busy = true;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving…';

        fetch(POST_URL, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.UI ? window.UI.csrfToken() : ''
            },
            body: JSON.stringify(payload())
        }).then(function (res) {
            // Content type BEFORE res.ok, on purpose. These endpoints live
            // under /tech/, not /api/, so SubscriptionEnforcementMiddleware
            // answers a read-only tenant with a redirect that fetch follows —
            // an HTML page arrives as a 200 and res.json() would throw an
            // opaque parse error.
            var type = res.headers.get('Content-Type') || '';
            if (type.indexOf('application/json') === -1) {
                throw new Error('Couldn’t save that. Reload the page and try again.');
            }
            return res.json().then(function (data) {
                if (!res.ok || !data.ok) {
                    var err = new Error(data.error || 'Couldn’t save that.');
                    err.data = data;
                    throw err;
                }
                return data;
            });
        }).then(function (data) {
            insertRow(data);
            if (window.UI) { window.UI.toast(data.message, 'success'); }
            reset();
            if (window.UI) { window.UI.closeModal(modal); }
        }).catch(function (err) {
            // "Did you mean this person?" is a question, not a failure — keep
            // the modal open with everything the shop typed still in it.
            if (err.data && err.data.needs_confirmation) {
                renderDuplicates(err.data.suggestions || []);
                setError('');
            } else {
                setError(err.message);
            }
        }).then(function () {
            busy = false;
            submitBtn.disabled = false;
            submitBtn.textContent = 'Add & schedule';
        });
    });

    // --- put the new row on the page --------------------------------------
    function insertRow(data) {
        if (!data.day || !data.day.on_screen || !data.day.row_html) {
            // Booked onto a day that isn't on screen. Say so rather than
            // silently inserting a Friday row into Tuesday's list — the toast
            // already names the day.
            return;
        }
        // The row comes from the server, rendered through the same partial a
        // reload uses. A second copy of that markup in JS is how the triage
        // rail drifted (S7 notes) — don't reintroduce one.
        var group = document.querySelector(
            '[data-swap-group="tech-' + data.job.technician_id + '"]')
            || document.querySelector('[data-swap-group="own"]');
        if (!group) {
            // No list to insert into yet (an empty day still shows its empty
            // state). A reload is the honest fallback, and the flash carries
            // the message across it.
            if (window.UI) { window.UI.flash(data.message, 'success'); }
            window.location.reload();
            return;
        }
        var temp = document.createElement('div');
        temp.innerHTML = data.day.row_html.trim();
        var row = temp.firstElementChild;
        if (!row) { return; }

        // Keep the list in time order — the server sorts by (scheduled_for,
        // pk), so an appended row would sit in the wrong place until reload.
        var when = new Date(data.job.scheduled_for).getTime();
        var placed = false;
        Array.prototype.some.call(group.children, function (existing) {
            var raw = existing.getAttribute('data-scheduled-for');
            var other = raw ? new Date(raw).getTime() : NaN;
            if (!isNaN(other) && other > when) {
                group.insertBefore(row, existing);
                placed = true;
                return true;
            }
            return false;
        });
        if (!placed) { group.appendChild(row); }
        row.classList.add('motion-rise');
    }

    function reset() {
        form.reset();
        clearChoice();
        results.classList.add('hidden');
        newPerson.classList.add('hidden');
        exactWrap.classList.add('hidden');
        priceRow.classList.add('hidden');
        setError('');
        // form.reset() restores the markup defaults, which for the date is
        // the day on screen — exactly what a second call should default to.
    }

    // Opening the modal should land the cursor where typing starts.
    document.addEventListener('click', function (e) {
        var opener = e.target.closest('[data-modal-open="quick-job-modal"]');
        if (!opener) { return; }
        window.setTimeout(function () { custInput.focus(); }, 50);
    });
})();
