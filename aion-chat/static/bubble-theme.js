/* ── Aion 气泡样式 — 预设 + 已命名样式库，可随时切换 ── */

(function () {
  if (window._aionBubbleThemeLoaded) return;
  window._aionBubbleThemeLoaded = true;
  var STYLE_ID = 'aion-bubble-theme-css';

  // 预设样式：default=系统原色；{user,ai}=简易配色；{css}=完整自定义 CSS
  var BUBBLE_THEMES = {
    default: { name: '系统默认', css: '' },
    pink: {
      name: '粉漾',
      user: { bg: 'linear-gradient(145deg,#ffd6e8,#ffc2d8)', bd: 'rgba(255,140,180,.55)', fg: '#3b2030' },
      ai:   { bg: 'linear-gradient(145deg,#d5efd4,#bce4b8)', bd: 'rgba(110,180,120,.5)', fg: '#1c301c' }
    },
    blue: {
      name: '星夜',
      user: { bg: 'linear-gradient(145deg,#dbe6ff,#c8d6ff)', bd: 'rgba(120,150,255,.5)', fg: '#1e2a55' },
      ai:   { bg: 'linear-gradient(145deg,#d7e9f5,#c3dcec)', bd: 'rgba(90,150,200,.5)', fg: '#142a3a' }
    },
    mint: {
      name: '青柠',
      user: { bg: 'linear-gradient(145deg,#d4f5e8,#bfedda)', bd: 'rgba(80,180,150,.5)', fg: '#123a2f' },
      ai:   { bg: 'linear-gradient(145deg,#eaf6d8,#dcefc0)', bd: 'rgba(140,180,90,.5)', fg: '#2a3a14' }
    },
    purple: {
      name: '紫罗兰',
      user: { bg: 'linear-gradient(145deg,#e8daff,#d8c4ff)', bd: 'rgba(150,110,255,.5)', fg: '#2e1f4d' },
      ai:   { bg: 'linear-gradient(145deg,#ffd9ee,#ffc0df)', bd: 'rgba(230,110,170,.5)', fg: '#3a1630' }
    },
    sunset: {
      name: '日落',
      user: { bg: 'linear-gradient(145deg,#ffdcc2,#ffc9a3)', bd: 'rgba(240,150,80,.5)', fg: '#3d2410' },
      ai:   { bg: 'linear-gradient(145deg,#ffe9be,#ffdd9c)', bd: 'rgba(220,170,60,.5)', fg: '#3d2e10' }
    },
    mono: {
      name: '极简',
      user: { bg: '#ffffff', bd: 'rgba(120,120,120,.4)', fg: '#222222' },
      ai:   { bg: '#ececec', bd: 'rgba(120,120,120,.4)', fg: '#222222' }
    },
    wechat: {
      name: '微信',
      css: [
        '.msg-row.user .msg-bubble{background:linear-gradient(135deg,#b7f29a,#95ec69);border:1px solid rgba(150,220,120,.55);color:#111;border-bottom-right-radius:6px;}',
        '.msg-row.assistant .msg-bubble{background:#ffffff;border:1px solid rgba(0,0,0,.06);color:#111;border-bottom-left-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.06);}',
        'body[data-theme="dark"] .msg-row.assistant .msg-bubble{background:#3a3a3a;color:#eee;border-color:rgba(255,255,255,.08);}',
        '.message-row.user .bubble{background:linear-gradient(135deg,#b7f29a,#95ec69);border:1px solid rgba(150,220,120,.55);color:#111;border-bottom-right-radius:6px;}',
        '.message-row.aion .bubble,.message-row.connor .bubble{background:#ffffff;border:1px solid rgba(0,0,0,.06);color:#111;border-bottom-left-radius:6px;}',
        'body[data-theme="dark"] .message-row.aion .bubble,body[data-theme="dark"] .message-row.connor .bubble{background:#3a3a3a;color:#eee;border-color:rgba(255,255,255,.08);}'
      ].join('\n')
    }
  };

  // 把预设转成覆盖 CSS
  function themeCss(theme) {
    var t = BUBBLE_THEMES[theme];
    if (!t) return '';
    if (t.css != null) return t.css;
    var u = t.user, a = t.ai;
    return [
      '.msg-row.user .msg-bubble{background:' + u.bg + ';border:1px solid ' + u.bd + ';color:' + u.fg + ';}',
      '.msg-row.assistant .msg-bubble{background:' + a.bg + ';border:1px solid ' + a.bd + ';color:' + a.fg + ';}',
      '.message-row.user .bubble{background:' + u.bg + ';border:1px solid ' + u.bd + ';color:' + u.fg + ';}',
      '.message-row.aion .bubble,.message-row.connor .bubble{background:' + a.bg + ';border:1px solid ' + a.bd + ';color:' + a.fg + ';}'
    ].join('\n');
  }

  // active 可以是预设 key 或自定义样式 id；customCss 兼容旧接口
  function applyBubbleTheme(active, customCss) {
    var style = document.getElementById(STYLE_ID);
    if (!style) {
      style = document.createElement('style');
      style.id = STYLE_ID;
      document.head.appendChild(style);
    }
    var css = '';
    if (active && BUBBLE_THEMES[active]) {
      css = themeCss(active);
    } else if (window._bubbleStyles && active) {
      var found = window._bubbleStyles.find(function (s) { return s.id === active; });
      if (found) css = found.css || '';
    }
    if (customCss) css += '\n' + customCss;
    style.textContent = css;
  }

  async function loadBubbleTheme() {
    try {
      var resp = await fetch('/api/bubble-styles');
      if (!resp.ok) return;
      var data = await resp.json();
      window._bubbleStyles = data.styles || [];
      window._bubbleTheme = data;
      applyBubbleTheme(data.active, '');
    } catch (e) { /* 静默 */ }
  }

  window.BUBBLE_THEMES = BUBBLE_THEMES;
  window.applyBubbleTheme = applyBubbleTheme;
  window.loadBubbleTheme = loadBubbleTheme;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadBubbleTheme, { once: true });
  } else {
    loadBubbleTheme();
  }
})();
