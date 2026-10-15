/**
 * "Is this the same windshield?" — the job form's check before a repair is
 * priced on the progressive ladder.
 *
 * The ladder counts repairs per unit and starts over when the windshield is
 * replaced. When THIS shop replaces it, that happens on its own. When another
 * company does, nobody tells us, and the first chip on brand-new glass is
 * billed as repair #3. Healed repairs are visible on the glass, so this shows
 * the tech where the earlier ones were; if they aren't there, one tap sets
 * new_windshield and create_job starts the unit over at #1.
 *
 *     <div id="windshieldHistory" class="hidden"
 *          data-endpoint="{% url 'get_windshield_history' %}"
 *          data-customer="id_customer"      (input ids, read live)
 *          data-unit="id_unit_number"
 *          data-flag="id_new_windshield"    (hidden input this module sets)
 *          data-type-name="service_type"    (only while this radio says repair)
 *          data-type-value="repair"></div>
 *
 * The form calls WindshieldHistory.refresh() when the picked customer
 * changes (the picker writes the hidden select without an input event).
 * Changing the customer or unit clears the flag: a tap is about one
 * windshield, never carried onto the next one typed.
 */
(function () {
    'use strict';

    var DEBOUNCE_MS = 350;
    var box, flag, customerEl, unitEl, timer = null, latest = 0;
    var lastKey = null, data = null;

    function byId(id) { return id ? document.getElementById(id) : null; }

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text) n.textContent = text;
        return n;
    }

    function money(s) {
        var n = parseFloat(s);
        if (isNaN(n)) return '';
        return '$' + (n % 1 === 0 ? n.toFixed(0) : n.toFixed(2));
    }

    function isRepair() {
        var name = box.dataset.typeName;
        if (!name) return true;
        var picked = document.querySelector('input[name="' + name + '"]:checked');
        return !picked || picked.value === box.dataset.typeValue;
    }

    function hide() {
        box.classList.add('hidden');
        box.textContent = '';
    }

    function setFlag(on) {
        if (flag) flag.value = on ? '1' : '';
        render();
    }

    // A small outline of the glass with a dot where each earlier repair was
    // marked. Same axes as the form's tap-to-mark diagram: 0-100% across
    // (driver -> passenger) and down.
    function diagram(spots) {
        var wrap = el('div', 'relative w-full max-w-xs h-24 mt-2 rounded-xl border-2 border-gray-300 bg-gray-100');
        wrap.setAttribute('aria-hidden', 'true');
        wrap.appendChild(el('span', 'absolute top-1 left-2 text-[10px] font-semibold text-gray-500', 'DRIVER'));
        wrap.appendChild(el('span', 'absolute top-1 right-2 text-[10px] font-semibold text-gray-500', 'PASSENGER'));
        spots.forEach(function (s) {
            var dot = el('span', 'absolute w-3 h-3 -ml-1.5 -mt-1.5 rounded-full bg-red-600 ring-2 ring-white');
            dot.style.left = Math.min(100, Math.max(0, s.x)) + '%';
            dot.style.top = Math.min(100, Math.max(0, s.y)) + '%';
            wrap.appendChild(dot);
        });
        return wrap;
    }

    function render() {
        if (!data || !data.show || !isRepair()) { hide(); return; }
        box.textContent = '';
        var reset = flag && flag.value === '1';
        var card = el('div', 'rounded-lg border px-3 py-2 text-sm ' +
            (reset ? 'border-brand-200 bg-brand-50 text-brand-900'
                   : 'border-gray-200 bg-gray-50 text-gray-700'));

        if (reset) {
            var line = el('p', '');
            line.appendChild(el('span', 'font-medium', 'New windshield.'));
            line.appendChild(document.createTextNode(
                ' This repair is #1 (' + money(data.first_price) + '). '));
            var undo = el('button', 'font-medium underline min-h-11 sm:min-h-0', 'Undo');
            undo.type = 'button';
            undo.addEventListener('click', function () { setFlag(false); });
            line.appendChild(undo);
            card.appendChild(line);
            box.appendChild(card);
            box.classList.remove('hidden');
            return;
        }

        var head = el('p', '');
        head.appendChild(el('span', 'font-medium',
            'Repair #' + data.next_number + ' on this windshield (' + money(data.next_price) + ').'));
        if (data.last_repaired) {
            head.appendChild(document.createTextNode(' Last repaired ' + data.last_repaired + '.'));
        }
        card.appendChild(head);

        if (data.spots && data.spots.length) {
            card.appendChild(el('p', 'mt-1 text-gray-500',
                'Your earlier repairs were here. Check the glass for them:'));
            card.appendChild(diagram(data.spots));
        }

        card.appendChild(el('p', 'mt-2 text-gray-500',
            'Earlier repairs not on the glass? It has been replaced since.'));
        var btn = el('button', 'btn-secondary mt-2 w-full sm:w-auto',
            'New windshield: charge as repair #1 (' + money(data.first_price) + ')');
        btn.type = 'button';
        btn.addEventListener('click', function () { setFlag(true); });
        card.appendChild(btn);

        box.appendChild(card);
        box.classList.remove('hidden');
    }

    function refresh() {
        if (!box) return;
        var customer = customerEl ? customerEl.value : '';
        var unit = unitEl ? unitEl.value.trim() : '';
        var key = customer + '|' + unit;
        clearTimeout(timer);
        if (key !== lastKey) {
            // A different vehicle: whatever was tapped was about the old one.
            if (lastKey !== null && flag) flag.value = '';
            lastKey = key;
            data = null;
        } else if (data) {
            render();  // same vehicle, e.g. the repair/replacement toggle
            return;
        }
        if (!customer || !unit) { latest++; hide(); return; }
        timer = setTimeout(function () {
            var token = ++latest;
            fetch(box.dataset.endpoint +
                  '?customer=' + encodeURIComponent(customer) +
                  '&unit_number=' + encodeURIComponent(unit),
                  { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (token !== latest) return;
                    data = d;
                    render();
                })
                .catch(function () {});
        }, DEBOUNCE_MS);
    }

    function init() {
        box = document.getElementById('windshieldHistory');
        if (!box) return;
        flag = byId(box.dataset.flag);
        customerEl = byId(box.dataset.customer);
        unitEl = byId(box.dataset.unit);
        if (unitEl) {
            unitEl.addEventListener('input', refresh);
            unitEl.addEventListener('blur', refresh);
        }
        if (customerEl) customerEl.addEventListener('change', refresh);
        if (box.dataset.typeName) {
            var radios = document.querySelectorAll('input[name="' + box.dataset.typeName + '"]');
            for (var i = 0; i < radios.length; i++) radios[i].addEventListener('change', render);
        }
        // lastKey starts null, so the first refresh keeps the flag: a bounced
        // POST re-renders with it still set and shows the tapped state.
        refresh();
    }

    window.WindshieldHistory = { refresh: refresh };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
