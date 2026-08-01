# -*- coding: utf-8 -*-
"""邮件/政务 YAML 成功语义（fake ADB + 脚本化找图，不连真机）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core.task import Task, TaskBlockedError, TaskError

ROOT = Path(__file__).resolve().parent.parent


class FakeADB:
    def screenshot(self):
        return np.zeros((100, 100, 3), dtype=np.uint8)

    def tap(self, x, y):
        pass

    def key_back(self):
        pass


def _match(found: bool, score: float = 0.9):
    return SimpleNamespace(found=found, score=score, x=10, y=20)


def _install_script(task: Task, present: set, *, on_tap=None, monkeypatch=None):
    """按 template 相对路径决定是否命中；tap 后可更新 present。"""
    last_rel = {"v": None}

    def load_template(template_dir, rel):
        last_rel["v"] = rel.replace("\\", "/")
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def find(screen, template, threshold=0.85, region=None):
        rel = last_rel["v"]
        return _match(bool(rel and rel in present))

    # 覆盖 Task 内与 core.task.vision 的真实找图（repeat/empty_is_blocked 会走 vision.find）
    import core.task as task_mod
    import core.vision as vision_mod

    if monkeypatch is not None:
        monkeypatch.setattr(task_mod.vision, "load_template", load_template)
        monkeypatch.setattr(task_mod.vision, "find", find)
        monkeypatch.setattr(vision_mod, "load_template", load_template)
        monkeypatch.setattr(vision_mod, "find", find)
    else:
        task_mod.vision.load_template = load_template
        task_mod.vision.find = find

    task._load_template_safe = lambda step: load_template(
        task.template_dir, step["template"]
    )

    def should_skip(step):
        skip_tpl = step.get("skip_if_image")
        if not skip_tpl:
            return False
        return skip_tpl in present

    def find_with_timeout(step, want_gone: bool = False):
        rel = step.get("template")
        last_rel["v"] = rel
        is_present = rel in present
        if want_gone:
            return _match(is_present)  # found=True means still visible
        return _match(is_present)

    def tap_image(step):
        if should_skip(step):
            return
        m = find_with_timeout(step)
        if m is None or not m.found:
            if step.get("optional", False):
                return
            task._raise_missing(
                step,
                f"超时未找到模板 {step['template']}",
            )
        task.step_events.append(f"点击 {step.get('template')}")
        tpl = step.get("template")
        if on_tap:
            on_tap(tpl, present)
        else:
            # 默认：点击 claim/accept/close 后从画面移除
            if tpl and (
                "claim" in tpl or "accept" in tpl or "close" in tpl
            ):
                present.discard(tpl)

    def wait_image(step):
        m = find_with_timeout(step)
        if m is None or not m.found:
            if step.get("optional", False):
                return
            task._raise_missing(step, f"超时未等到 {step['template']}")
        task.step_events.append(f"确认出现 {step.get('template')}")

    def wait_gone(step):
        m = find_with_timeout(step, want_gone=True)
        if m is not None and m.found and not step.get("optional", False):
            task._raise_missing(
                step, f"超时后 {step['template']} 仍未消失（后置验证失败）"
            )
        task.step_events.append(f"确认消失 {step.get('template')}")

    task._should_skip = should_skip
    task._find_with_timeout = find_with_timeout
    task._do_tap_image = tap_image
    task._do_wait_image = wait_image
    task._do_wait_gone = wait_gone


def _mail_task():
    return Task(
        str(ROOT / "tasks" / "mail.yaml"),
        FakeADB(),
        str(ROOT / "templates"),
    )


def _zhengwu_task():
    return Task(
        str(ROOT / "tasks" / "zhengwu.yaml"),
        FakeADB(),
        str(ROOT / "templates"),
    )


def test_mail_precondition_title_missing_failed(monkeypatch):
    task = _mail_task()
    # 可点邮件图标，但邮件标题始终不出现 → 前置确认失败
    present = {"mail/mail_icon_only.png"}
    _install_script(task, present, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is False
    assert task.last_status == "failed"
    assert "title" in (task.last_error or "")


def test_mail_claim_missing_blocked(monkeypatch):
    task = _mail_task()
    present = {"mail/title.png", "mail/mail_icon_only.png"}
    # 有 title 无 claim_all
    _install_script(task, present, monkeypatch=monkeypatch)

    # 跳过前面找 icon：给 skip 用 title 已在 present
    ok = task.run()
    assert ok is False
    assert task.last_status == "blocked"
    assert "claim" in (task.last_error or "").lower() or "claim_all" in (
        task.last_error or ""
    )


def test_mail_claim_still_visible_blocked(monkeypatch):
    task = _mail_task()
    present = {
        "mail/title.png",
        "mail/claim_all.png",
        "mail/close.png",
    }

    def on_tap(tpl, p):
        # 点击 claim 后故意保持可见
        if tpl == "mail/claim_all.png":
            p.add("mail/claim_all.png")

    _install_script(task, present, on_tap=on_tap, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is False
    assert task.last_status == "blocked"
    assert "消失" in (task.last_error or "") or "claim" in (task.last_error or "")


def test_mail_title_still_after_close_failed(monkeypatch):
    task = _mail_task()
    present = {
        "mail/title.png",
        "mail/claim_all.png",
        "mail/close.png",
    }

    def on_tap(tpl, p):
        if tpl == "mail/claim_all.png":
            p.discard("mail/claim_all.png")
        if tpl == "mail/close.png":
            p.discard("mail/close.png")
            # 标题故意残留
            p.add("mail/title.png")

    _install_script(task, present, on_tap=on_tap, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is False
    assert task.last_status == "failed"
    assert "title" in (task.last_error or "")


def test_mail_full_success(monkeypatch):
    task = _mail_task()
    present = {
        "mail/title.png",
        "mail/claim_all.png",
        "mail/close.png",
    }

    def on_tap(tpl, p):
        if tpl == "mail/claim_all.png":
            p.discard("mail/claim_all.png")
        if tpl == "mail/close.png":
            p.discard("mail/close.png")
            p.discard("mail/title.png")

    _install_script(task, present, on_tap=on_tap, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is True
    assert task.last_status == ""


def test_zhengwu_no_accept_blocked(monkeypatch):
    task = _zhengwu_task()
    present = {"zhengwu/title.png"}  # 无 accept
    _install_script(task, present, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is False
    assert task.last_status == "blocked"


def test_zhengwu_accept_never_gone_not_succeeded(monkeypatch):
    task = _zhengwu_task()
    present = {"zhengwu/title.png", "zhengwu/accept.png"}

    def on_tap(tpl, p):
        # 点了 accept 仍保留
        if tpl == "zhengwu/accept.png":
            p.add("zhengwu/accept.png")

    _install_script(task, present, on_tap=on_tap, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is False
    assert task.last_status in ("blocked", "failed")
    assert task.last_status != ""


def test_zhengwu_accept_then_gone_success(monkeypatch):
    task = _zhengwu_task()
    present = {"zhengwu/title.png", "zhengwu/accept.png", "zhengwu/back.png"}
    clicks = {"n": 0}

    def on_tap(tpl, p):
        if tpl == "zhengwu/accept.png":
            clicks["n"] += 1
            p.discard("zhengwu/accept.png")

    _install_script(task, present, on_tap=on_tap, monkeypatch=monkeypatch)
    ok = task.run()
    assert ok is True
    assert clicks["n"] >= 1
