# -*- coding: utf-8 -*-
"""注入到页面的 JavaScript：自动识别登录表单、填值、提交，以及换背景。"""

from __future__ import annotations

import json


def _js(obj) -> str:
    """安全的 JSON 内联（避免 </script> 等破坏脚本）。"""
    s = json.dumps(obj, ensure_ascii=False)
    return (s.replace("<", "\\u003c")
             .replace(">", "\\u003e")
             .replace("&", "\\u0026"))


def parse_result(raw) -> dict:
    """QtWebEngine 回传对象时容易丢值，统一用 JSON 字符串往返。"""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


AUTOFILL_JS = r"""
(function (CFG) {
  var out = {
    found: false, filled: false, submitted: false, captcha: false,
    hasForm: false, modeSwitch: false, domainSel: "", msg: [],
    userSel: "", pwdSel: "", btnSel: "", looseBtn: false, forcedBtn: false,
    userValue: "", title: document.title, url: location.href,
    inputCount: 0
  };
  function log(m) { out.msg.push(String(m)); }

  function q(root, sel) { try { return root.querySelector(sel); } catch (e) { return null; } }
  function qa(root, sel) { try { return Array.prototype.slice.call(root.querySelectorAll(sel)); } catch (e) { return []; } }

  function visible(el) {
    if (!el) return false;
    try {
      var s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
      if (parseFloat(s.opacity) === 0) return false;
      var r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    } catch (e) { return true; }
  }

  function looseVisible(el) {
    // 比 visible 宽松：不查 opacity/尺寸。开机时窗口隐藏，CSS 动画不跑，按钮卡在 opacity:0
    if (!el) return false;
    try {
      var s = getComputedStyle(el);
      return s.display !== 'none' && s.visibility !== 'hidden';
    } catch (e) { return true; }
  }

  function setValue(el, v) {
    try {
      var proto = Object.getPrototypeOf(el);
      var desc = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
      if (desc && desc.set) { desc.set.call(el, v); } else { el.value = v; }
    } catch (e) { el.value = v; }
    try {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: v.slice(-1) || 'a' }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      el.focus && el.focus();
    } catch (e) {}
  }

  function realClick(el) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var opt = { bubbles: true, cancelable: true, view: window };
    ['mousedown', 'mouseup'].forEach(function (t) {
      try { el.dispatchEvent(new MouseEvent(t, opt)); } catch (e) {}
    });
    try { el.focus && el.focus(); } catch (e) {}
    try { el.click(); return true; }
    catch (e) {
      try { el.dispatchEvent(new MouseEvent('click', opt)); return true; } catch (e2) { return false; }
    }
  }

  function describe(el) {
    if (!el) return "";
    var d = el.tagName ? el.tagName.toLowerCase() : "";
    if (el.id) return d + "#" + el.id;
    if (el.name) return d + "[name=" + el.name + "]";
    if (el.className && typeof el.className === 'string') return d + "." + el.className.trim().split(/\s+/)[0];
    return d;
  }

  function haystack(el) {
    return ((el.name || '') + ' ' + (el.id || '') + ' ' +
            (el.getAttribute && (el.getAttribute('placeholder') || '')) + ' ' +
            (el.getAttribute && (el.getAttribute('autocomplete') || '')) + ' ' +
            (el.className || '')).toLowerCase();
  }

  function scoreUser(el) {
    var k = haystack(el), s = 0;
    ['user', 'account', 'acct', 'login', 'name', 'id', 'stu', 'phone', 'mobile', 'tel', 'email',
     '账号', '用户名', '用户', '学号', '手机', '邮箱', '工号'].forEach(function (w) {
      if (k.indexOf(w) >= 0) s += 10;
    });
    if ((el.getAttribute && (el.getAttribute('autocomplete') || '').toLowerCase() === 'username')) s += 15;
    if (el.type === 'email' || el.type === 'tel') s += 6;
    if (el.type === 'text') s += 2;
    return s - (el.getBoundingClientRect ? -el.getBoundingClientRect().top / 1000 : 0);
  }

  // 这些是"切换到别的登录方式"的按钮，不是提交按钮 —— 点了等于白点
  var MODE_WORDS = ['单点', 'sso', '扫码', '二维码', '短信', '动态码', '其他方式',
                    'addmode', '忘记密码', '修改密码', '自助服务', '使用说明', '帮助'];

  function isModeSwitch(el) {
    if (!el) return false;
    var t = ((el.innerText || el.value || '') + ' ' + (el.className || '') +
             ' ' + (el.id || '')).toLowerCase();
    for (var i = 0; i < MODE_WORDS.length; i++) {
      if (t.indexOf(MODE_WORDS[i]) >= 0) return true;
    }
    return false;
  }

  function scoreButton(el) {
    var k = haystack(el) + ' ' + ((el.innerText || el.value || '')).toLowerCase(), s = 0;
    ['login', 'signin', 'submit', 'connect', '认证', '登录', '登 录', '上网', '连接', '确定', '进入',
     '注销', '认证上网'].forEach(function (w) { if (k.indexOf(w) >= 0) s += 12; });
    ['reset', 'clear', '重置', '清空', '取消', 'cancel', '注册', 'register', '忘记'].forEach(function (w) {
      if (k.indexOf(w) >= 0) s -= 20;
    });
    if (el.type === 'submit') s += 10;
    return s;
  }

  function findPassword(root) {
    if (CFG.selPassword) {
      var e = q(root, CFG.selPassword);
      if (e) { out.pwdSel = CFG.selPassword; return e; }
      log('自定义密码选择器未命中：' + CFG.selPassword);
    }
    var list = qa(root, 'input[type=password]').filter(visible);
    if (list.length) { out.pwdSel = describe(list[0]); return list[0]; }
    // 兜底：伪装成 text 的密码框
    var fake = qa(root, 'input').filter(function (el) {
      return visible(el) && /pass|pwd|密码/.test(haystack(el));
    });
    if (fake.length) { out.pwdSel = describe(fake[0]); return fake[0]; }
    return null;
  }

  function findContainer(el) {
    var c = el.closest ? el.closest('form') : null;
    if (c) { out.hasForm = true; return c; }
    var p = el.parentElement, guard = 0;
    while (p && guard++ < 6) {
      if (qa(p, 'input').length >= 2) return p;
      p = p.parentElement;
    }
    return document.body;
  }

  function findUser(container, pwdEl) {
    if (CFG.selUsername) {
      var e = q(document, CFG.selUsername);
      if (e) { out.userSel = CFG.selUsername; return e; }
      log('自定义用户名选择器未命中：' + CFG.selUsername);
    }
    var cand = qa(container, 'input, textarea').filter(function (el) {
      if (el === pwdEl) return false;
      if (!visible(el)) return false;
      if (el.disabled || el.readOnly) return false;
      var t = (el.type || 'text').toLowerCase();
      if (['hidden', 'password', 'checkbox', 'radio', 'button', 'submit', 'file', 'image'].indexOf(t) >= 0) return false;
      return true;
    });
    if (!cand.length) {
      cand = qa(document, 'input, textarea').filter(function (el) {
        if (el === pwdEl) return false;
        if (!visible(el)) return false;
        var t = (el.type || 'text').toLowerCase();
        return ['text', 'email', 'tel', 'number', ''].indexOf(t) >= 0;
      });
    }
    cand.sort(function (a, b) { return scoreUser(b) - scoreUser(a); });
    if (cand.length) { out.userSel = describe(cand[0]); return cand[0]; }
    return null;
  }

  function findButton(container) {
    if (CFG.selSubmit) {
      var e = q(document, CFG.selSubmit);
      if (e) { out.btnSel = CFG.selSubmit; return e; }
      log('自定义登录按钮选择器未命中：' + CFG.selSubmit);
    }
    // 先认这些一眼就知道是登录按钮的（深澜 portal 是 #login-account）
    var sure = ['#login-account', '[class*=btn-login]', '#loginBtn', '#login-btn',
                'button[type=submit]', 'input[type=submit]'];
    for (var i = 0; i < sure.length; i++) {
      var el = q(document, sure[i]);
      if (el && visible(el) && !isModeSwitch(el)) { out.btnSel = sure[i]; return el; }
    }
    // 第二遍：放宽可见性 —— 开机时窗口隐藏、CSS 动画没跑，按钮可能卡在 opacity:0
    for (var i2 = 0; i2 < sure.length; i2++) {
      var el2 = q(document, sure[i2]);
      if (el2 && looseVisible(el2) && !isModeSwitch(el2)) {
        out.btnSel = sure[i2]; out.looseBtn = true; return el2;
      }
    }
    // 页面上是不是压根还没切到"账号登录"模式？
    var sw = qa(document, 'span, a, div, button').filter(function (el) {
      return visible(el) && /单点|sso|扫码|短信|其他方式/.test(
        ((el.innerText || '') + ' ' + (el.className || '')).toLowerCase());
    });
    out.modeSwitch = sw.length > 0;
    var sel = 'button, input[type=submit], input[type=button], input[type=image], a, span, div';
    var cand = qa(container, sel).filter(function (el) {
      if (!visible(el)) return false;
      if (isModeSwitch(el)) return false;
      var txt = (el.innerText || el.value || el.getAttribute && el.getAttribute('title') || '');
      if (!txt && !el.type) return false;
      if (el.tagName === 'A' && !/login|登录|认证|连接|submit/.test((el.innerText || '') + (el.href || ''))) return false;
      return scoreButton(el) > 0;
    });
    if (!cand.length) {
      cand = qa(document, 'button, input[type=submit], input[type=button], a, span, div').filter(function (el) {
        return visible(el) && !isModeSwitch(el) && scoreButton(el) > 8;
      });
    }
    cand.sort(function (a, b) { return scoreButton(b) - scoreButton(a); });
    if (cand.length) { out.btnSel = describe(cand[0]); return cand[0]; }

    // 兜底：账号密码已填但按钮"不可见"，直接按 id 点下去（.click() 对隐藏元素也有效）
    if (out.filled) {
      var fb = q(document, '#login-account') || q(document, '#loginBtn') ||
               q(document, '#login-btn') || q(document, 'button[class*=btn-login]');
      if (fb && !isModeSwitch(fb)) {
        out.btnSel = describe(fb); out.forcedBtn = true;
        log('登录按钮在页面上但被判定为不可见，直接点击它');
        return fb;
      }
    }
    return null;
  }

  function detectCaptcha(container) {
    var imgs = qa(container, 'img').concat(qa(container, 'canvas'));
    for (var i = 0; i < imgs.length; i++) {
      if (!visible(imgs[i])) continue;          // 隐藏的验证码图片不算
      var src = (imgs[i].src || '') + ' ' + (imgs[i].id || '') + ' ' + (imgs[i].className || '');
      if (/captcha|verify|valid|checkcode|code\.|random|验证码/.test(src.toLowerCase())) return true;
    }
    var inputs = qa(container, 'input').filter(function (el) {
      if (!visible(el)) return false;
      var t = (el.type || '').toLowerCase();
      if (t === 'password' || t === 'hidden') return false;
      return /captcha|verify|valid|vcode|checkcode|验证码/.test(haystack(el));
    });
    return inputs.length > 0;
  }

  // 运营商 / 产品选择（深澜 portal 用 #domain 承载，值形如 @unicom）
  function applyDomain() {
    if (!CFG.domain) return '';
    var el = q(document, '#domain') || q(document, 'select[name=domain]') ||
             q(document, 'select[name*=domain]') || q(document, 'input[name=domain]');
    if (!el) return 'no-element';
    var want = String(CFG.domain).trim();
    var wantLow = want.toLowerCase().replace(/^@/, '');
    if (el.tagName === 'SELECT') {
      for (var i = 0; i < el.options.length; i++) {
        var o = el.options[i];
        var v = (o.value || '').toLowerCase().replace(/^@/, '');
        var t = (o.text || '').trim();
        if (v === wantLow || t === want || t.toLowerCase().indexOf(wantLow) >= 0) {
          setValue(el, o.value);
          out.domainSel = t + '（' + o.value + '）';
          return t;
        }
      }
      return 'no-match';
    }
    setValue(el, want);
    out.domainSel = want;
    return want;
  }

  // ---------- 主流程 ----------
  var doc = document;
  var pwdEl = findPassword(doc);
  if (!pwdEl && doc.querySelectorAll('iframe').length) {
    // 尝试同源 iframe
    var frames = qa(doc, 'iframe');
    for (var i = 0; i < frames.length && !pwdEl; i++) {
      try {
        var d = frames[i].contentDocument;
        if (d) { pwdEl = findPassword(d); if (pwdEl) doc = d; }
      } catch (e) {}
    }
  }
  if (!pwdEl) { log('未找到密码输入框'); return out; }
  out.found = true;

  var container = findContainer(pwdEl);
  out.inputCount = qa(container, 'input').length;
  out.captcha = detectCaptcha(container);

  var dom = applyDomain();
  if (dom === 'no-element') log('页面没有运营商选择框，按页面默认走');
  else if (dom === 'no-match') log('没匹配到运营商「' + CFG.domain + '」（可到【诊断页面】看有哪些可选）');
  else if (dom) log('已选择运营商：' + dom);

  var userEl = findUser(container, pwdEl);
  if (userEl) {
    setValue(userEl, CFG.username);
    out.userValue = CFG.username;
    log('已填写账号：' + out.userSel);
  } else {
    log('未找到账号输入框');
  }
  setValue(pwdEl, CFG.password);
  log('已填写密码：' + out.pwdSel);
  out.filled = !!userEl;

  if (CFG.rememberCheckbox) {
    qa(container, 'input[type=checkbox]').forEach(function (cb) {
      if (!cb.checked) { cb.click(); }
    });
  }

  var btn = findButton(container);
  if (btn) log('识别到登录按钮：' + out.btnSel + (btn.innerText ? '（' + btn.innerText.trim().slice(0, 10) + '）' : ''));

  if (!CFG.autoSubmit) { log('已按要求跳过自动提交'); return out; }

  if (btn) {
    realClick(btn) ? (out.submitted = true, log('已点击登录按钮')) : log('点击登录按钮失败');
  } else if (out.hasForm && container.requestSubmit) {
    try { container.requestSubmit(); out.submitted = true; log('已提交表单'); }
    catch (e) { log('提交表单失败：' + e); }
  } else if (out.hasForm) {
    try { container.submit(); out.submitted = true; log('已提交表单（fallback）'); }
    catch (e) { log('提交表单失败：' + e); }
  } else {
    log('未找到可点击的登录按钮，请手动点击');
  }
  return out;
})
"""

# 只识别不填写，用于"测试 / 诊断"
INSPECT_JS = r"""
(function () {
  function qa(root, sel) { try { return Array.prototype.slice.call(root.querySelectorAll(sel)); } catch (e) { return []; } }
  function visible(el) {
    if (!el) return false;
    var s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function realClick(el) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var opt = { bubbles: true, cancelable: true, view: window };
    ['mousedown', 'mouseup'].forEach(function (t) {
      try { el.dispatchEvent(new MouseEvent(t, opt)); } catch (e) {}
    });
    try { el.focus && el.focus(); } catch (e) {}
    try { el.click(); return true; }
    catch (e) {
      try { el.dispatchEvent(new MouseEvent('click', opt)); return true; } catch (e2) { return false; }
    }
  }

  function describe(el) {
    if (!el) return "";
    var d = el.tagName.toLowerCase();
    if (el.id) return d + "#" + el.id;
    if (el.name) return d + "[name=" + el.name + "]";
    return d;
  }
  var res = { forms: [], password: [], text: [], buttons: [], url: location.href,
              title: document.title, domain: null };
  (function () {
    var el = document.querySelector('#domain') || document.querySelector('select[name*=domain]');
    if (!el) return;
    var d = { tag: el.tagName.toLowerCase(), value: el.value || '', options: [] };
    if (el.tagName === 'SELECT') {
      for (var i = 0; i < el.options.length; i++) {
        d.options.push((el.options[i].value || '') + ' = ' + (el.options[i].text || '').trim());
      }
    }
    res.domain = d;
  })();
  qa(document, 'form').forEach(function (f) {
    res.forms.push({
      id: f.id || '', name: f.name || '', action: f.getAttribute('action') || '',
      method: (f.getAttribute('method') || 'get').toUpperCase(),
      inputs: qa(f, 'input').length
    });
  });
  qa(document, 'input[type=password]').forEach(function (el) {
    res.password.push({ sel: describe(el), visible: visible(el), name: el.name || '', id: el.id || '' });
  });
  qa(document, 'input').filter(function (el) {
    var t = (el.type || 'text').toLowerCase();
    return ['text', 'email', 'tel', 'number'].indexOf(t) >= 0;
  }).forEach(function (el) {
    res.text.push({ sel: describe(el), visible: visible(el), placeholder: el.getAttribute('placeholder') || '', name: el.name || '' });
  });
  qa(document, 'button, input[type=submit], input[type=button]').forEach(function (el) {
    res.buttons.push({ sel: describe(el), text: (el.innerText || el.value || '').trim().slice(0, 20), visible: visible(el) });
  });
  return res;
})
"""


def build_autofill_js(username: str, password: str, sel_username: str = "",
                      sel_password: str = "", sel_submit: str = "",
                      auto_submit: bool = True,
                      remember_checkbox: bool = True,
                      domain: str = "") -> str:
    cfg = {
        "username": username,
        "password": password,
        "selUsername": sel_username,
        "selPassword": sel_password,
        "selSubmit": sel_submit,
        "domain": domain,
        "autoSubmit": auto_submit,
        "rememberCheckbox": remember_checkbox,
    }
    return "JSON.stringify(" + AUTOFILL_JS + "(" + _js(cfg) + "))"


def build_inspect_js() -> str:
    return "JSON.stringify(" + INSPECT_JS + "())"


BACKGROUND_JS = r"""
(function (CFG) {
  var BG = '__campus_bg', DIM = '__campus_dim';
  function clear() {
    var a = document.getElementById(BG); if (a) a.parentNode.removeChild(a);
    var b = document.getElementById(DIM); if (b) b.parentNode.removeChild(b);
  }
  clear();
  if (!CFG.enabled || !CFG.uri) {
    document.documentElement.style.removeProperty('background');
    document.body && document.body.style.removeProperty('background');
    return { ok: false, msg: '背景未启用' };
  }
  var root = document.documentElement;
  var bg = document.createElement('div');
  bg.id = BG;
  bg.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;z-index:-2;pointer-events:none;' +
    'background-image:url("' + CFG.uri + '");background-size:' + CFG.fit + ';' +
    'background-position:center center;background-repeat:no-repeat;' +
    (CFG.blur > 0 ? 'filter:blur(' + CFG.blur + 'px);transform:scale(1.08);' : '');
  var dim = document.createElement('div');
  dim.id = DIM;
  dim.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;z-index:-1;pointer-events:none;' +
    'background:' + (CFG.light ? 'rgba(255,255,255,' : 'rgba(0,0,0,') + (CFG.dim / 100) + ');';
  root.appendChild(bg);
  root.appendChild(dim);
  root.style.setProperty('background', 'transparent', 'important');
  if (document.body) {
    document.body.style.setProperty('background', 'transparent', 'important');
    document.body.style.setProperty('background-color', 'transparent', 'important');
    if (CFG.hollow) {
      var kids = document.body.children;
      for (var i = 0; i < kids.length; i++) {
        kids[i].style.setProperty('background-color', 'transparent', 'important');
      }
    }
  }
  return { ok: true, msg: '背景已应用' };
})
"""


def build_background_js(uri: str, enabled: bool, dim: int, blur: int,
                        fit: str, light: bool, hollow: bool) -> str:
    cfg = {
        "uri": uri,
        "enabled": enabled,
        "dim": dim,
        "blur": blur,
        "fit": fit,
        "light": light,
        "hollow": hollow,
    }
    return "JSON.stringify(" + BACKGROUND_JS + "(" + _js(cfg) + "))"


WATCH_JS = r"""
(function () {
  function visible(el) {
    if (!el) return false;
    var s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  var text = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ');
  var errs = [];
  ['.panel-notice', '.notice', '.error', '.alert', '.tip', '.message', '.msg',
   '[class*=error]', '[class*=Error]', '[class*=tip]', '.layui-layer-content',
   '#notice-content', '#notice-title'].forEach(function (sel) {
    try {
      var list = document.querySelectorAll(sel);
      for (var i = 0; i < list.length; i++) {
        if (!visible(list[i])) continue;
        var t = (list[i].innerText || '').replace(/\s+/g, ' ').trim();
        if (!t || t.length > 100) continue;
        if (/使用说明|故障报修|领取|客服|二维码|版权|©|帮助|忘记密码|自助/.test(t)) continue;
        if (errs.indexOf(t) < 0) errs.push(t);
      }
    } catch (e) {}
  });
  return JSON.stringify({
    url: location.href,
    loggedIn: /_success|\/success/i.test(location.href)
              || !!document.querySelector('#logout, .btn-logout')
              || /已用流量|已用时长|注销/.test(text),
    hasPassword: !!document.querySelector('input[type=password]'),
    errors: errs.slice(0, 4),
    snippet: text.slice(0, 200)
  });
})()
"""


def build_watch_js() -> str:
    return WATCH_JS
