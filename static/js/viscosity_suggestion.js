/**
 * Temperature -> resin viscosity suggestion.
 *
 * A tech types the windshield temperature; the shop's own rules (Settings ->
 * Repair Resin Rules) answer with the resin to reach for. The API and those
 * rules have always worked. What kept breaking is the wiring: this fetch was
 * hand-copied into every form that has a temperature box, so each new form
 * either shipped without it or shipped with an older copy of it. The job form
 * had no copy at all, the multi-break modal had one that never followed the
 * break you were looking at, and the convert-to-batch rows had none.
 *
 * One implementation, four callers. A form opts in by rendering a container:
 *
 *     <div id="viscositySuggestion" class="hidden mt-2"
 *          data-viscosity-input="id_windshield_temperature"
 *          data-viscosity-endpoint="{% url 'get_viscosity_suggestion' %}"></div>
 *
 * Containers present at load wire themselves up. Forms that build rows at
 * runtime call ViscositySuggestion.attach(el) once the row is in the DOM, and
 * forms that move a value into the box themselves (the multi-break modal
 * reusing one dialog for every break) call refresh()/clear() so the
 * recommendation always describes the temperature actually on screen.
 */
(function () {
    'use strict';

    // Tone classes are written out in full. Tailwind purges anything it cannot
    // read as a literal string, and the shop picks the color per rule, so
    // 'bg-' + color would compile to nothing. All seven BADGE_COLOR_CHOICES
    // are here — the older copies stopped at five and quietly rendered a
    // shop's orange and purple rules gray.
    var TONES = {
        blue: 'bg-blue-50 border-blue-200 text-blue-800',
        green: 'bg-green-50 border-green-200 text-green-800',
        yellow: 'bg-yellow-50 border-yellow-200 text-yellow-800',
        orange: 'bg-orange-50 border-orange-200 text-orange-800',
        red: 'bg-red-50 border-red-200 text-red-800',
        purple: 'bg-purple-50 border-purple-200 text-purple-800',
        gray: 'bg-gray-50 border-gray-200 text-gray-700'
    };
    var BASE = 'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ';
    var DEBOUNCE_MS = 400;

    var handles = [];   // [element, handle] pairs; no Map, to keep this ES5.

    function lookup(box) {
        for (var i = 0; i < handles.length; i++) {
            if (handles[i][0] === box) return handles[i][1];
        }
        return null;
    }

    function build(box) {
        var input = document.getElementById(box.dataset.viscosityInput);
        var endpoint = box.dataset.viscosityEndpoint;
        if (!input || !endpoint) return null;

        // Whatever layout classes the template put on the box (column spans,
        // margins) have to survive every render, because show() rewrites
        // className wholesale to swap the tone.
        var layout = box.className.replace(/\bhidden\b/g, '').trim();

        var timer = null;
        // Bumped per request so a slow reply for an old temperature cannot
        // land on top of a newer one -- easy to hit typing "105" a digit at a
        // time, and the wrong resin is worse than none.
        var latest = 0;

        function clear() {
            latest++;
            clearTimeout(timer);
            box.textContent = '';
            box.className = (layout + ' hidden').trim();
        }

        function show(data) {
            box.textContent = '';
            box.className = (layout + ' ' + BASE + (TONES[data.badge_color] || TONES.gray)).trim();

            var icon = document.createElement('i');
            icon.className = 'fas fa-tint mt-0.5 shrink-0';
            var text = document.createElement('div');
            var strong = document.createElement('strong');
            strong.textContent = data.recommendation;
            text.appendChild(strong);
            if (data.suggestion_text) {
                // textContent, not innerHTML. suggestion_text is free text an
                // owner typed into Settings, and a technician is the one who
                // renders it -- innerHTML here is stored XSS inside the shop.
                text.appendChild(document.createTextNode(' — ' + data.suggestion_text));
            }
            box.appendChild(icon);
            box.appendChild(text);
        }

        function refresh() {
            var temperature = (input.value || '').trim();
            if (temperature === '') {
                clear();
                return;
            }
            clearTimeout(timer);
            timer = setTimeout(function () {
                var token = ++latest;
                fetch(endpoint + '?temperature=' + encodeURIComponent(temperature))
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (token !== latest) return;   // a newer temperature won
                        if (data.success && data.recommendation) {
                            show(data);
                        } else {
                            // No rule covers this temperature. Say nothing
                            // rather than nag -- a shop that never turned the
                            // rules on lands here on every keystroke.
                            clear();
                        }
                    })
                    .catch(function () { clear(); });
            }, DEBOUNCE_MS);
        }

        input.addEventListener('input', refresh);
        // Autosaved drafts and validation re-renders come back with a value
        // already in the box.
        if (input.value) refresh();

        return { refresh: refresh, clear: clear };
    }

    function attach(box) {
        if (!box) return null;
        var existing = lookup(box);
        if (existing) return existing;
        var handle = build(box);
        if (handle) handles.push([box, handle]);
        return handle;
    }

    // Accepts an id or an element. Attaches on first use, so a caller running
    // before DOMContentLoaded still gets a live handle.
    function get(idOrEl) {
        var box = typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
        return box ? attach(box) : null;
    }

    function attachAll(root) {
        var scope = root || document;
        var boxes = scope.querySelectorAll('[data-viscosity-endpoint]');
        for (var i = 0; i < boxes.length; i++) attach(boxes[i]);
    }

    window.ViscositySuggestion = { attach: attach, get: get, attachAll: attachAll };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { attachAll(); });
    } else {
        attachAll();
    }
})();
