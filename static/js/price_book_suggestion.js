/**
 * Vehicle + glass -> what this shop charged last time (B6 price book).
 *
 * One implementation, three callers (the job form, the owner's replacement
 * form, the replacement edit page) — the viscosity module's lesson: a fetch
 * hand-copied into each form is the copy that rots. A form opts in with a
 * container:
 *
 *     <div id="priceBookSuggestion" class="hidden"
 *          data-pricebook-endpoint="{% url 'get_price_book_suggestion' %}"
 *          data-pricebook-year="id_vehicle_year"        (input ids, read live)
 *          data-pricebook-make="id_vehicle_make"
 *          data-pricebook-model="id_vehicle_model"
 *          data-pricebook-position="id_glass_position"
 *          data-pricebook-customer="id_customer"        (optional: unit lookup)
 *          data-pricebook-unit="id_unit_number"
 *          data-pricebook-price="id_price"              (single-price form)
 *          data-pricebook-parts="id_parts_cost"         (parts/labor form)
 *          data-pricebook-labor="id_labor_cost"
 *          data-pricebook-adas="adas-checkbox"
 *          data-pricebook-adas-cost="adas-cost"
 *          data-pricebook-type-name="service_type"      (optional gate: only
 *          data-pricebook-type-value="replacement"       when this radio says so)
 *     ></div>
 *
 * A lookup key can also be a literal instead of an input id
 * (data-pricebook-fixed-year="2019" ...) for a page that shows the vehicle
 * but does not edit it.
 *
 * Suggest, never silently apply: an EMPTY price box is filled and the note
 * says so, with an Undo; a box the tech already typed in is left alone and
 * the note offers a "Use" button instead. A box this module filled is still
 * ours — when the vehicle changes, the number follows; the moment the tech
 * edits it, it is theirs.
 */
(function () {
    'use strict';

    var DEBOUNCE_MS = 400;
    var BASE = 'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ';
    var TONE = 'bg-brand-50 border-brand-200 text-brand-900';

    function byId(id) { return id ? document.getElementById(id) : null; }

    function build(box) {
        var endpoint = box.dataset.pricebookEndpoint;
        if (!endpoint) return null;
        var d = box.dataset;
        var inputs = {
            year: byId(d.pricebookYear), make: byId(d.pricebookMake),
            model: byId(d.pricebookModel), position: byId(d.pricebookPosition),
            customer: byId(d.pricebookCustomer), unit: byId(d.pricebookUnit)
        };
        var fixed = {
            year: d.pricebookFixedYear, make: d.pricebookFixedMake,
            model: d.pricebookFixedModel, position: d.pricebookFixedPosition
        };
        var targets = {
            price: byId(d.pricebookPrice), parts: byId(d.pricebookParts),
            labor: byId(d.pricebookLabor), adas: byId(d.pricebookAdas),
            adasCost: byId(d.pricebookAdasCost)
        };
        var layout = box.className.replace(/\bhidden\b/g, '').trim();
        var timer = null;
        var latest = 0;
        var current = null;         // last suggestion shown
        var filled = {};            // target key -> value we wrote

        function gateOpen() {
            if (!d.pricebookTypeName) return true;
            var checked = document.querySelector('input[name="' + d.pricebookTypeName + '"]:checked')
                || document.querySelector('input[name="' + d.pricebookTypeName + '"]');
            return !checked || checked.value === d.pricebookTypeValue;
        }

        function read(key) {
            if (inputs[key]) return (inputs[key].value || '').trim();
            return (fixed[key] || '').trim();
        }

        function isOurs(key) {
            var el = targets[key];
            return !!el && filled[key] !== undefined && (el.value || '') === filled[key];
        }
        function isEmpty(key) {
            var el = targets[key];
            return !!el && (el.value || '').trim() === '';
        }
        function canFill(key) { return isEmpty(key) || isOurs(key); }

        function setValue(key, value) {
            var el = targets[key];
            if (!el) return;
            el.value = value;
            filled[key] = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
        function setAdas(cost) {
            if (!targets.adas) return;
            var want = cost !== null && cost !== undefined;
            if (targets.adas.checked !== want) {
                targets.adas.checked = want;
                targets.adas.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (want && targets.adasCost) setValue('adasCost', cost);
        }

        // Which boxes this page has decides what "fill" means.
        function apply(data, force) {
            if (targets.price) {
                if (force || canFill('price')) { setValue('price', data.price); return true; }
                return false;
            }
            if (targets.parts || targets.labor) {
                if (data.has_breakdown) {
                    if (force || (canFill('parts') && canFill('labor'))) {
                        setValue('parts', data.parts_cost === null ? '' : data.parts_cost);
                        setValue('labor', data.labor_cost === null ? '' : data.labor_cost);
                        setAdas(data.adas_calibration_cost);
                        return true;
                    }
                    return false;
                }
                // One number, no split: never guessed into a box on its own.
                if (force) {
                    setValue('parts', data.price);
                    if (targets.labor) setValue('labor', '');
                    setAdas(null);
                    return true;
                }
            }
            return false;
        }

        // Take back every number this module wrote (and only those): the
        // Undo button, and any lookup that comes back different — a value
        // filled for the last vehicle must not sit under a note about this one.
        function clearOurs() {
            var any = false;
            Object.keys(filled).forEach(function (key) {
                if (isOurs(key)) {
                    targets[key].value = '';
                    targets[key].dispatchEvent(new Event('input', { bubbles: true }));
                    any = true;
                }
                delete filled[key];
            });
            if (any && targets.adas && targets.adas.checked && current && current.adas_calibration_cost !== null) {
                targets.adas.checked = false;
                targets.adas.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }

        function undo() {
            clearOurs();
            if (current) render(current, false);
        }

        function clear() {
            latest++;
            clearTimeout(timer);
            current = null;
            box.textContent = '';
            box.className = (layout + ' hidden').trim();
        }

        function render(data, didFill) {
            box.textContent = '';
            box.className = (layout + ' ' + BASE + TONE).trim();
            var icon = document.createElement('i');
            icon.className = 'fas fa-book-open mt-0.5 shrink-0 text-brand-600';
            var text = document.createElement('div');
            text.className = 'min-w-0 flex-1';
            var strong = document.createElement('strong');
            strong.textContent = didFill ? 'Filled from your price book. ' : 'From your price book: ';
            text.appendChild(strong);
            // textContent, never innerHTML — vehicle names are shop-typed text.
            text.appendChild(document.createTextNode(data.note));
            if (!didFill && !data.has_breakdown && (targets.parts || targets.labor) && !targets.price) {
                text.appendChild(document.createTextNode(' It was one price, not parts and labor.'));
            }
            box.appendChild(icon);
            box.appendChild(text);

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'shrink-0 text-sm font-medium underline text-brand-700 hover:text-brand-900 min-h-11 sm:min-h-0';
            if (didFill) {
                btn.textContent = 'Undo';
                btn.addEventListener('click', undo);
            } else {
                btn.textContent = 'Use $' + data.price;
                btn.addEventListener('click', function () {
                    apply(data, true);
                    render(data, true);
                });
            }
            box.appendChild(btn);
        }

        function refresh() {
            clearTimeout(timer);
            if (!gateOpen()) { clearOurs(); clear(); return; }
            var make = read('make'), model = read('model');
            var customer = read('customer'), unit = read('unit');
            if (!((make && model) || (customer && unit))) { clearOurs(); clear(); return; }
            timer = setTimeout(function () {
                var token = ++latest;
                var q = '?year=' + encodeURIComponent(read('year')) +
                        '&make=' + encodeURIComponent(make) +
                        '&model=' + encodeURIComponent(model) +
                        '&glass_position=' + encodeURIComponent(read('position')) +
                        '&customer=' + encodeURIComponent(customer) +
                        '&unit_number=' + encodeURIComponent(unit);
                fetch(endpoint + q, { credentials: 'same-origin' })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (token !== latest) return;    // a newer vehicle won
                        if (!data.success || !data.found) { clearOurs(); clear(); return; }
                        if (!current || current.entry_id !== data.entry_id) clearOurs();
                        current = data;
                        render(data, apply(data, false));
                    })
                    .catch(function () { clear(); });
            }, DEBOUNCE_MS);
        }

        Object.keys(inputs).forEach(function (key) {
            var el = inputs[key];
            if (!el) return;
            el.addEventListener('input', refresh);
            el.addEventListener('change', refresh);
        });
        if (d.pricebookTypeName) {
            var radios = document.querySelectorAll('input[name="' + d.pricebookTypeName + '"]');
            for (var i = 0; i < radios.length; i++) radios[i].addEventListener('change', refresh);
        }
        // A box the tech types into stops being ours.
        Object.keys(targets).forEach(function (key) {
            var el = targets[key];
            if (!el || key === 'adas') return;
            el.addEventListener('keydown', function () { delete filled[key]; });
        });
        // Autosaved drafts and validation re-renders come back with values.
        refresh();
        return { refresh: refresh, clear: clear };
    }

    var handles = [];
    function attach(box) {
        if (!box) return null;
        for (var i = 0; i < handles.length; i++) {
            if (handles[i][0] === box) return handles[i][1];
        }
        var handle = build(box);
        if (handle) handles.push([box, handle]);
        return handle;
    }
    function attachAll(root) {
        var boxes = (root || document).querySelectorAll('[data-pricebook-endpoint]');
        for (var i = 0; i < boxes.length; i++) attach(boxes[i]);
    }

    // For forms that set a lookup input programmatically (the job form's
    // customer picker writes a hidden select) and fire no input event.
    function refreshAll() {
        for (var i = 0; i < handles.length; i++) handles[i][1].refresh();
    }

    window.PriceBookSuggestion = { attach: attach, attachAll: attachAll, refreshAll: refreshAll };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { attachAll(); });
    } else {
        attachAll();
    }
})();
