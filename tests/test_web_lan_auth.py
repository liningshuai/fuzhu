# -*- coding: utf-8 -*-
"""WebUI LAN 鉴权静态安全契约（只读源文件，不启浏览器/ADB）。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_web_injects_x_admin_token_header():
    assert "X-Admin-Token" in APP_JS
    assert 'headers["X-Admin-Token"]' in APP_JS or "headers['X-Admin-Token']" in APP_JS


def test_web_no_admin_token_in_url():
    assert "admin_token=" not in APP_JS
    assert "URLSearchParams" not in APP_JS or "admin_token" not in APP_JS
    # 禁止 query 拼接口令
    assert "?admin_token" not in APP_JS
    assert "searchParams.set" not in APP_JS


def test_web_no_local_storage_session_cookie_idb():
    assert "localStorage" not in APP_JS
    assert "sessionStorage" not in APP_JS
    assert "document.cookie" not in APP_JS
    assert "indexedDB" not in APP_JS
    assert "IndexedDB" not in APP_JS


def test_web_password_input_type():
    assert 'type="password"' in INDEX or "type='password'" in INDEX
    assert 'id="adminTokenInput"' in INDEX


def test_web_401_clears_memory_and_returns_to_auth():
    assert "clearAdminAuth" in APP_JS
    assert "status === 401" in APP_JS or "res.status === 401" in APP_JS
    assert "showAuthGate" in APP_JS
    assert "state.adminToken = null" in APP_JS or "adminToken = null" in APP_JS
    assert "stopPolling" in APP_JS
    assert "鉴权失败，请重新输入管理口令" in APP_JS


def test_web_no_console_of_admin_password():
    # 不得 console 输出管理口令字段
    lowered = APP_JS.lower()
    for needle in (
        "console.log(state.admintoken",
        "console.info(state.admintoken",
        "console.error(state.admintoken",
        "console.log(value)",
        "console.log(input.value",
    ):
        assert needle not in lowered.replace(" ", "")
    # 无 console.* 与 adminToken 同语句
    for line in APP_JS.splitlines():
        if "console." in line:
            assert "adminToken" not in line
            assert "admin_token" not in line.lower()


def test_web_health_skip_auth_and_lan_gate_flow():
    assert "skipAuth" in APP_JS
    assert "/api/health" in APP_JS
    assert "allow_lan" in APP_JS or "allowLan" in APP_JS
    assert "authGate" in INDEX
    assert "mainPanels" in INDEX
