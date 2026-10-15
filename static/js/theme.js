/*
 * Appearance switch: Light / Dark / Match device (staff app only).
 *
 * The server renders <html data-theme="…"> from the `rs_theme` cookie
 * (common.context_processors.ui_theme), so the page already paints in the
 * right theme before this file runs. All this does is answer a tap: write the
 * cookie for next time and flip the attribute now. Event delegation, not
 * onclick attributes — the CSP cannot enforce while those exist (S18b).
 */
(function () {
  var COOKIE = 'rs_theme';
  var THEMES = ['light', 'dark', 'system'];
  var DARK_BAR = '#161b22';
  var LIGHT_BAR = '#ffffff';

  function current() {
    var t = document.documentElement.getAttribute('data-theme');
    return THEMES.indexOf(t) === -1 ? 'light' : t;
  }

  function paintButtons(theme) {
    var buttons = document.querySelectorAll('[data-theme-choice]');
    for (var i = 0; i < buttons.length; i++) {
      var on = buttons[i].getAttribute('data-theme-choice') === theme;
      buttons[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }

  function paintStatusBar(theme) {
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i++) {
      var m = metas[i];
      if (theme === 'system') {
        // Two metas keyed on the device setting; collapse to one if needed.
        if (i === 0) {
          m.setAttribute('media', '(prefers-color-scheme: light)');
          m.setAttribute('content', LIGHT_BAR);
        } else {
          m.setAttribute('media', '(prefers-color-scheme: dark)');
          m.setAttribute('content', DARK_BAR);
        }
      } else {
        m.removeAttribute('media');
        m.setAttribute('content', theme === 'dark' ? DARK_BAR : LIGHT_BAR);
      }
    }
    if (theme === 'system' && metas.length === 1) {
      var extra = document.createElement('meta');
      extra.name = 'theme-color';
      extra.media = '(prefers-color-scheme: dark)';
      extra.content = DARK_BAR;
      metas[0].parentNode.insertBefore(extra, metas[0].nextSibling);
    }
  }

  function apply(theme) {
    if (THEMES.indexOf(theme) === -1) theme = 'light';
    document.documentElement.setAttribute('data-theme', theme);
    var secure = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = COOKIE + '=' + theme + '; Path=/; Max-Age=31536000; SameSite=Lax' + secure;
    paintButtons(theme);
    paintStatusBar(theme);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-theme-choice]');
    if (!btn) return;
    e.preventDefault();
    apply(btn.getAttribute('data-theme-choice'));
  });

  window.RSTheme = { apply: apply, current: current };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { paintButtons(current()); });
  } else {
    paintButtons(current());
  }
})();
