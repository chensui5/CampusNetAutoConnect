# -*- coding: utf-8 -*-
"""连接引擎。

流程：探测网络 →（逐个尝试候选认证页）→ 打开页面 → 轮询识别表单 →
填账号密码 → 提交 → 多轮复查网络 → 成功 / 失败（附截图与报告）。

之所以要"候选地址链"：很多人（包括我们自己）会误把认证**成功页**
（如深澜的 /srun_portal_success）填进来，那页面上根本没有表单。
所以这里会按优先级依次尝试：原地址 → 把 _success 换成登录页 → 站点根 →
靠网关劫持重定向的通用地址，直到找到真正的登录表单。
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .autofill import (build_autofill_js, build_inspect_js,
                       build_watch_js, parse_result)
from .config import ConfigManager, logs_dir
from .netcheck import check_online_multi, parse_probes

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 靠网关把任意 http 请求劫持到认证页，这是最通用的一招
HIJACK_URLS = (
    "http://connect.rom.miui.com/generate_204",
    "http://www.msftconnecttest.com/connecttest.txt",
    "http://www.gstatic.com/generate_204",
)

MAX_INJECT_ROUND = 9      # 表单已经出来了、只是按钮没渲染好 —— 值得多等
MAX_NOFORM_ROUND = 4      # 连账号密码框都没有，多半这页不是登录页，别耗着
MAX_VERIFY_ROUND = 3      # 提交后最多复查网络的次数


class ProbeWorker(QThread):
    """在工作线程里做网络探测，避免卡住界面。"""
    result = Signal(bool, str)

    def __init__(self, probes, timeout: float, parent=None):
        super().__init__(parent)
        self.probes = probes
        self.timeout = timeout

    def run(self):  # noqa: D102
        ok, detail = check_online_multi(self.probes, self.timeout)
        self.result.emit(ok, detail)


class ConnectEngine(QObject):
    """一次完整的连接流程。"""

    log = Signal(str)
    status = Signal(str)
    finished = Signal(bool, str)     # (成功, 说明)
    need_manual = Signal(str)        # 需要人工介入（验证码等）

    def __init__(self, cfg: ConfigManager, view, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.view = view
        self._busy = False
        self._cancel = False
        self._worker = None
        self._timers: list[QTimer] = []
        self._t0 = 0.0
        self._attempt = 0
        self._url_index = 0
        self._inject_round = 0
        self._candidates: list[str] = []
        self._ua_done = False
        self._seen_errors: list[str] = []
        self.report: dict = {}

    # ---------- 对外 ----------
    @property
    def busy(self) -> bool:
        return self._busy

    def stop(self):
        self._cancel = True
        self._busy = False
        self._clear_timers()
        self.status.emit("已停止")

    def _clear_timers(self):
        for t in self._timers:
            try:
                t.stop()
            except Exception:
                pass
        self._timers.clear()

    def _later(self, ms, fn):
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(fn)
        t.start(max(0, int(ms)))
        self._timers.append(t)
        return t

    def start(self, reason: str = "手动", submit: bool = True):
        if self._busy:
            self.log.emit("连接流程正在进行中，忽略本次请求")
            return
        s = self.cfg.settings
        if not s.url:
            self.log.emit("尚未配置认证页地址，请先填写")
            self.finished.emit(False, "未配置网址")
            return
        self._setup_ua()
        self._busy = True
        self._cancel = False
        self._attempt = 0
        self._url_index = 0
        self._inject_round = 0
        self._t0 = time.time()
        self._seen_errors = []
        self._candidates = self._build_candidates(s.url)
        self.report = {"reason": reason, "steps": [], "candidates": list(self._candidates),
                       "submit": submit}
        self.log.emit(f"=== 开始连接（{reason}）===")
        for i, u in enumerate(self._candidates):
            self.log.emit(f"  候选地址{i + 1}：{u}")
        self.status.emit("检测网络…")
        self._probe("前置检测", self._on_pre_probe, submit)

    # ---------- 候选地址 ----------
    @staticmethod
    def _build_candidates(raw: str) -> list[str]:
        raw = (raw or "").strip()
        if not raw:
            return []
        base = raw if "://" in raw else "http://" + raw
        out = [base]
        low = base.lower()
        p = urlparse(base)

        # 1) 认证成功页 / 结果页 → 换回登录页（深澜等 portal 常见）
        if "_success" in low or "/success" in low:
            for rep in ("_pc", ""):
                out.append(base.replace("_success", rep))
            out.append(base.replace("/success", "/pc"))
        # 2) 带上具体路径容易失效，补一个站点根
        if p.scheme and p.netloc:
            root = f"{p.scheme}://{p.netloc}/"
            if root.rstrip("/") != base.rstrip("/"):
                out.append(root)
            # 深澜默认入口
            if p.netloc and ("srun" in low or "/srun_portal" in low):
                out.append(f"{p.scheme}://{p.netloc}/srun_portal_pc?ac_id=1&theme=pro")
        # 3) 靠网关劫持重定向
        out.extend(HIJACK_URLS)

        seen, uniq = set(), []
        for u in out:
            if u and u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq

    def set_url(self, url: str):
        """用户在预览页手动导航后，把新地址作为第一候选。"""
        if url and self._candidates:
            if url not in self._candidates:
                self._candidates.insert(0, url)

    def _setup_ua(self):
        if self._ua_done:
            return
        try:
            self.view.page().profile().setHttpUserAgent(UA)
            self._ua_done = True
        except Exception:
            pass

    # ---------- 探测 ----------
    def _probes(self):
        s = self.cfg.settings
        return parse_probes(s.probe_url, s.probe_keyword)

    def _probe(self, label: str, slot, submit=True):
        self._worker = ProbeWorker(self._probes(), self.cfg.settings.probe_timeout, self)
        self._worker.result.connect(lambda ok, d: self._guard(ok, d, label, slot, submit))
        self._worker.start()

    def _guard(self, ok, detail, label, slot, submit):
        if self._cancel:
            return
        self.report["steps"].append({
            "step": label, "ok": ok, "detail": detail,
            "t": round(time.time() - self._t0, 1),
        })
        self.log.emit(f"{label}：{'在线' if ok else '离线'}（{detail}）")
        slot(ok, detail, submit)

    # ---------- 主流程 ----------
    def _on_pre_probe(self, online, detail, submit):
        s = self.cfg.settings
        if online and s.skip_if_online:
            self._done(True, "已经联网，无需重复连接")
            return
        if online:
            self.log.emit("当前显示已联网，但配置为仍然执行连接流程")
        self._attempt = 0
        self._url_index = 0
        self._open_page()

    def _open_page(self):
        s = self.cfg.settings
        if self._url_index >= len(self._candidates):
            self._retry_or_fail("试过所有候选地址都没找到登录表单")
            return
        url = self._candidates[self._url_index]
        self._last_url = url
        self.report["url"] = url
        self._inject_round = 0
        self.log.emit(f"打开认证页：{url}")
        self.status.emit("加载认证页…")
        self.view.load(url)
        self._load_handled = False

        def on_load(ok):
            if self._cancel or self._load_handled:
                return
            self._load_handled = True
            try:
                self.view.loadFinished.disconnect(on_load)
            except Exception:
                pass
            self.report["steps"].append({
                "step": f"加载 {url}", "ok": ok,
                "detail": "完成" if ok else "加载失败",
                "t": round(time.time() - self._t0, 1)})
            self.log.emit("页面加载" + ("完成" if ok else "失败"))
            if not ok:
                # 页面根本打不开（没网 / DNS 挂了 / 连不上网关）。
                # 这种情况下表单永远不会渲染出来，再等 9 轮纯属空转 ——
                # 实测白耗 39 秒。直接换下一个候选地址。
                self.log.emit("页面打不开，不等渲染了，直接换下一个候选地址")
                self._next_candidate("页面加载失败")
                return
            self._later(1000, self._pre_check)

        self.view.loadFinished.connect(on_load)
        self._later(s.page_load_timeout * 1000, lambda: self._on_load_timeout(on_load))

    def _pre_check(self):
        """开页面后先确认一件事：会不会其实已经是登录状态？

        校园网里网络探测点经常不通，容易把"明明在线"误判成"离线"。
        这里以页面自身状态为准：已登录且没有密码框，就直接算成功。
        """
        if self._cancel:
            return
        try:
            self.view.page().runJavaScript(build_watch_js(), self._on_pre_check)
        except Exception:
            self._inject(0)

    def _on_pre_check(self, res):
        if self._cancel:
            return
        data = parse_result(res)
        if data.get("loggedIn") and not data.get("hasPassword"):
            self.log.emit(f"页面显示当前已经是登录状态（{data.get('url')}）")
            self.report["steps"].append({
                "step": "页面状态预检", "ok": True, "detail": "已登录",
                "t": round(time.time() - self._t0, 1)})
            self._done(True, "当前已经是登录状态，无需重复认证")
            return
        self._inject(0)

    def _on_load_timeout(self, on_load):
        if self._cancel or self._load_handled:
            return
        self._load_handled = True
        try:
            self.view.loadFinished.disconnect(on_load)
        except Exception:
            pass
        self.log.emit(f"页面加载超时（{self.cfg.settings.page_load_timeout}s），尝试继续")
        self._pre_check()

    def _inject(self, rnd: int = 0):
        if self._cancel:
            return
        s = self.cfg.settings
        self._inject_round = rnd
        if rnd == 0:
            self.status.emit("识别并填写表单…")
        js = build_autofill_js(
            username=s.username,
            password=s.get_password(),
            sel_username=s.sel_username,
            sel_password=s.sel_password,
            sel_submit=s.sel_submit,
            auto_submit=self.report.get("submit", True),
            remember_checkbox=s.remember_checkbox,
            domain=s.domain,
        )
        try:
            self.view.page().runJavaScript(js, lambda res: self._on_autofill(res, rnd))
        except Exception as e:
            self.log.emit(f"注入脚本失败：{e}")
            self._next_candidate("脚本注入失败")

    def _on_autofill(self, res, rnd: int):
        if self._cancel:
            return
        res = parse_result(res)
        all_msgs = res.get("msg") or []
        # 只在第一轮把所有细节打出来，避免重试时刷屏
        if rnd == 0:
            for m in all_msgs:
                self.log.emit("· " + str(m))

        if not res.get("found"):
            # 注意这里用的是 MAX_NOFORM_ROUND，不是 MAX_INJECT_ROUND：
            # 「连账号密码框都没有」说明这一页多半就不是登录页，没必要耗 9 轮；
            # 而「框有了、只是按钮还没渲染出来」才是真的在等 SPA，那才值得多等。
            if rnd < MAX_NOFORM_ROUND - 1:
                self.log.emit(f"这一轮还没看到账号密码框，稍后再试"
                              f"（{rnd + 2}/{MAX_NOFORM_ROUND}）—— 页面还在渲染")
                self.status.emit(f"等待页面渲染…（{rnd + 2}/{MAX_NOFORM_ROUND}）")
                self._later(600, lambda: self._inject(rnd + 1))
                return
            self.log.emit("这个页面上没有账号/密码输入框，换个地址再试")
            self._next_candidate("页面上没有登录表单")
            return

        self.report["autofill"] = res
        self.report["steps"].append({
            "step": f"表单识别（第 {rnd + 1} 次）", "ok": True,
            "detail": f"账号 {res.get('userSel') or '未识别'} / 密码 {res.get('pwdSel')} / "
                      f"按钮 {res.get('btnSel') or '未识别'}",
            "t": round(time.time() - self._t0, 1)})
        self.log.emit(f"识别到表单：账号={res.get('userSel') or '未识别'}，"
                      f"密码={res.get('pwdSel')}，按钮={res.get('btnSel') or '未识别'}")

        if res.get("captcha"):
            self.log.emit("检测到疑似验证码，需要你手动输入后点击登录")
            self.status.emit("等待人工输入验证码")
            self.need_manual.emit("检测到验证码")
            self._later(max(15000, self.cfg.settings.post_submit_wait * 1000 * 5), self._verify)
            return

        if not self.report.get("submit", True):
            self._done(True, "已填写表单（测试模式，未提交）")
            return

        if not res.get("submitted"):
            if rnd < MAX_INJECT_ROUND - 1:
                why = ("页面还停在「单点登录 / 扫码」这类模式，等它切到账号登录"
                       if res.get("modeSwitch") else "登录按钮还没出现")
                self.log.emit(f"{why}，稍后再试（{rnd + 2}/{MAX_INJECT_ROUND}）")
                self.status.emit("等待页面就绪…")
                self._later(800, lambda: self._inject(rnd + 1))
                return
            self.log.emit("一直没找到可点的登录按钮")
            self.log.emit("可以在【高级】→【表单兜底】里手动填登录按钮选择器")
            self.status.emit("等待你手动点击登录")
            self.need_manual.emit("没找到可点击的登录按钮")
            self._later(12000, self._verify)
            return

        self.status.emit("已提交，等待网络就绪…")
        self._later(self.cfg.settings.post_submit_wait * 1000, lambda: self._verify(0))

    def _next_candidate(self, why: str):
        """当前页面没有表单，换下一个候选地址。"""
        self._url_index += 1
        total = len(self._candidates)
        if self._url_index < total:
            nxt = self._candidates[self._url_index]
            self.log.emit(f"{why} → 换个地址再试：{nxt}")
            self.status.emit("换地址重试…")
            self._later(600, self._open_page)
        else:
            self._retry_or_fail(why)

    def _verify(self, rnd: int = 0):
        """复查：先看页面是不是已经进到"已登录"状态，再测网络。

        深澜等 portal 登录成功后会跳到 xxx_success，这个信号比网络探测准得多
        （校园网里探测点经常不通，只靠探测会把成功误判成失败）。
        """
        if self._cancel:
            return
        self.status.emit("复查连接结果…")
        try:
            self.view.page().runJavaScript(build_watch_js(),
                                           lambda r: self._on_watch(r, rnd))
        except Exception:
            self._verify_net(rnd)

    def _on_watch(self, res, rnd: int):
        if self._cancel:
            return
        data = parse_result(res)
        if data:
            self.report.setdefault("watch", []).append({"round": rnd + 1, **data})
        if data.get("loggedIn"):
            self.log.emit(f"页面已进入已登录状态（{data.get('url')}）")
            self._done(True, "登录成功，页面已进入已登录状态")
            return
        for e in (data.get("errors") or []):
            if e not in self._seen_errors:
                self._seen_errors.append(e)
                self.log.emit(f"页面提示：{e}")
        self._verify_net(rnd)

    def _verify_net(self, rnd: int):
        self._probe(f"提交后复查{rnd + 1}",
                    lambda ok, d, submit: self._on_post_probe(ok, d, rnd))

    def _on_post_probe(self, online, detail, rnd: int):
        if self._cancel:
            return
        if online:
            self._done(True, "连接成功，网络已通")
            return
        if rnd + 1 < MAX_VERIFY_ROUND:
            wait = 2000 + rnd * 1500
            self.log.emit(f"还没通，{wait / 1000:.1f}s 后再看一次（{rnd + 2}/{MAX_VERIFY_ROUND}）")
            self._later(wait, lambda: self._verify(rnd + 1))
            return
        self._retry_or_fail("提交后仍然连不上")

    def _retry_or_fail(self, why: str):
        s = self.cfg.settings
        self._attempt += 1
        if self._attempt <= max(0, int(s.retry_times)):
            self.log.emit(f"{why}，{s.retry_delay}s 后整个流程重来（第 {self._attempt} 次）")
            self.status.emit(f"重试中 {self._attempt}/{s.retry_times}")
            self._url_index = 0
            self._later(s.retry_delay * 1000, self._open_page)
        else:
            self._done(False, why)

    def _snapshot(self, tag: str) -> str:
        try:
            os.makedirs(logs_dir(), exist_ok=True)
            path = os.path.join(logs_dir(), f"{tag}_{int(time.time())}.png")
            self.view.grab().save(path)
            return path
        except Exception:
            return ""

    def _done(self, ok: bool, msg: str):
        self._clear_timers()
        self._busy = False
        self.report["result"] = ok
        self.report["message"] = msg
        self.report["cost"] = round(time.time() - self._t0, 1)
        if not ok:
            if self._seen_errors:
                self.log.emit("页面给出的原因：" + " / ".join(self._seen_errors))
                self.report["page_errors"] = list(self._seen_errors)
            shot = self._snapshot("failed")
            if shot:
                self.report["snapshot"] = shot
                self.log.emit(f"已把当前页面截图存到：{shot}")
            self.log.emit("排查建议：① 到【预览】页手动打开认证页，确认能否看到账号密码输入框；"
                          "② 用【诊断页面】看识别结果；③ 还不行就在【高级】里手动填选择器")
        elif self._url_index > 0 and getattr(self, "_last_url", ""):
            self.log.emit(f"提示：真正能登录的是 {self._last_url}")
            self.log.emit("     可以在【预览】页点【设为认证页】把它存下来，下次就不用绕路了")
        self.log.emit(f"=== {'成功' if ok else '失败'}：{msg}（耗时 {self.report['cost']}s）===")
        self.status.emit(msg)
        self.finished.emit(ok, msg)

    # ---------- 诊断：只识别不提交 ----------
    def inspect(self):
        s = self.cfg.settings
        if not s.url:
            self.log.emit("尚未配置认证页地址")
            return
        self._setup_ua()
        candidates = self._build_candidates()
        url = candidates[0] if candidates else s.url
        self.log.emit(f"诊断模式：加载 {url}（不会填写和提交）")
        self.view.load(url)

        def on_load(ok):
            try:
                self.view.loadFinished.disconnect(on_load)
            except Exception:
                pass
            if not ok:
                self.log.emit("页面加载失败")
                return
            QTimer.singleShot(900, self._run_inspect)

        self.view.loadFinished.connect(on_load)

    def sel_domain(self) -> str:
        return getattr(self.cfg.settings, "domain", "") or ""

    def _run_inspect(self):
        def cb(res):
            res = parse_result(res)
            self.report["inspect"] = res
            self.log.emit("—— 页面结构诊断 ——")
            self.log.emit(f"地址：{res.get('url')}")
            self.log.emit(f"标题：{res.get('title')}")
            forms = res.get("forms") or []
            self.log.emit(f"表单 form 数量：{len(forms)}")
            for f in forms:
                self.log.emit(f"  form id={f.get('id')} action={f.get('action')} "
                              f"method={f.get('method')} 输入框={f.get('inputs')}")
            pw = res.get("password") or []
            for p in pw:
                self.log.emit(f"  密码框：{p.get('sel')}（可见={p.get('visible')}）")
            for t in (res.get("text") or [])[:8]:
                self.log.emit(f"  文本框：{t.get('sel')} placeholder={t.get('placeholder')}")
            for b in (res.get("buttons") or []):
                self.log.emit(f"  按钮：{b.get('sel')} 文本={b.get('text')}")
            dom = res.get("domain")
            if dom:
                self.log.emit(f"运营商选择框：{dom.get('tag')}，当前值={dom.get('value')!r}")
                for o in (dom.get("options") or []):
                    self.log.emit(f"    可选：{o}")
                if not self.sel_domain():
                    self.log.emit("    ★ 如果要指定运营商，填到【高级】→【表单兜底】→【运营商】")
            else:
                self.log.emit("运营商选择框：无（这个 portal 不用选运营商）")
            if not pw:
                self.log.emit("★ 这个页面上没有密码框 —— 很可能填的不是登录页。")
                self.log.emit("  提示：地址栏里带 _success / success 的通常是认证成功页，"
                              "去掉它才是登录页。")
        try:
            self.view.page().runJavaScript(build_inspect_js(), cb)
        except Exception as e:
            self.log.emit(f"诊断失败：{e}")
