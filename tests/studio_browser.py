"""Opt-in headless UI acceptance; temporary data and fake inference only.

Run: python tests/studio_browser.py --screenshots-dir <absolute evidence folder>
Requires existing Python Playwright/Chromium; never installs dependencies.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import socket
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from playwright.sync_api import sync_playwright, expect
import uvicorn
from app import app
from api.characters import get_character_service
from api.models import get_model_service
from api.tts import get_tts_service, get_synthesis_service
from schemas.character import CharacterPatch
from services.character_service import CharacterService
from services.tts_service import ProbeResult
import test_synthesis as fixtures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots-dir", type=Path, required=True)
    args = parser.parse_args()
    args.screenshots_dir.mkdir(parents=True, exist_ok=True)
    fixture = fixtures.SynthesisTests()
    fixture.setUp()
    store = CharacterService(fixture.root / "characters", voice_validator=fixture.service.validate_voice)
    manager = fixture.manager
    manager._process = None
    manager._state = "unavailable"
    manager._factory = lambda *args, **kwargs: fixtures.Child()
    manager._probe = lambda *args: ProbeResult(
        manager._process is not None and manager._process.poll() is None,
        manager._process is not None, "test inference")
    tool = manager.settings.tool_root
    for filename in ("api_v2.py", "gpt", "sovits"): (tool / filename).touch()
    for directory in ("bert", "hubert"): (tool / directory).mkdir()
    source = fixture.root / "reference-source.wav"
    source.write_bytes(fixtures.pcm(3))
    app.dependency_overrides[get_character_service] = lambda: store
    app.dependency_overrides[get_model_service] = lambda: fixture.models
    app.dependency_overrides[get_synthesis_service] = lambda: fixture.service
    app.dependency_overrides[get_tts_service] = lambda: manager
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    address = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch("api.models.get_model_service", return_value=fixture.models))
            stack.enter_context(patch("services.file_service.UPLOAD_DIR", fixture.root / "uploads"))
            thread.start()
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            assert server.started, "Temporary UI backend did not start"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
                    page.set_default_timeout(8000)
                    expect.set_options(timeout=8000)
                    errors = []
                    console_errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                    page.goto(address + "/studio/")
                    page.wait_for_load_state("networkidle")
                    expect(page.get_by_role("heading", name="角色与声音", exact=True)).to_be_visible()
                    expect(page.get_by_text("还没有角色", exact=True)).to_be_visible()
                    page.get_by_label("角色名称", exact=True).fill("星野 / 测试角色")
                    page.get_by_label("角色提示词", exact=True).fill("温柔、简洁地回应，保持角色设定。")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.get_by_text("角色已保存", exact=True)).to_be_visible()
                    page.reload(); page.wait_for_load_state("networkidle")
                    expect(page.get_by_label("角色名称", exact=True)).to_have_value("星野 / 测试角色")
                    original_update = store.update
                    def delayed_update(*args, **kwargs):
                        time.sleep(.3)
                        return original_update(*args, **kwargs)
                    with patch.object(store, "update", side_effect=delayed_update):
                        page.get_by_label("角色名称", exact=True).fill("提交时的名称")
                        page.get_by_role("button", name="保存角色", exact=True).click()
                        page.locator("#character-name").evaluate("el => {el.value='保留的后续修改';el.dispatchEvent(new Event('input',{bubbles:true}));}")
                        expect(page.locator("#notice")).to_contain_text("后续修改")
                    expect(page.get_by_label("角色名称", exact=True)).to_have_value("保留的后续修改")
                    assert store.list()[0]["name"] == "提交时的名称"
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.get_by_text("角色已保存", exact=True)).to_be_visible()
                    page.get_by_label("角色名称", exact=True).fill("星野 / 测试角色")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.get_by_text("角色已保存", exact=True)).to_be_visible()
                    page.get_by_role("tab", name="角色", exact=True).focus()
                    page.get_by_role("tab", name="角色", exact=True).press("ArrowRight")
                    expect(page.get_by_role("tab", name="模型", exact=True)).to_have_attribute("aria-selected", "true")
                    page.get_by_role("tab", name="模型", exact=True).press("ArrowLeft")
                    expect(page.get_by_role("tab", name="角色", exact=True)).to_have_attribute("aria-selected", "true")
                    page.get_by_role("tab", name="模型", exact=True).click()
                    expect(page.get_by_text("文件已配对", exact=True).first).to_be_visible()
                    incomplete = fixture.models.gpt_weights_dir / "partial_deadbeef-e1.ckpt"
                    incomplete.touch()
                    page.get_by_role("button", name="刷新模型", exact=True).click()
                    expect(page.get_by_text("配对不完整", exact=True)).to_be_visible()
                    expect(page.locator(".model-row").filter(has_text="partial").get_by_role("button")).to_be_disabled()
                    incomplete.unlink()
                    page.get_by_role("button", name="刷新模型", exact=True).click()
                    expect(page.locator(".model-row")).to_have_count(1)
                    page.get_by_role("button", name="用于当前角色", exact=True).click()
                    invalid_source = fixture.root / "invalid.mp3"
                    invalid_source.write_bytes(b"invalid")
                    page.get_by_label("上传参考 WAV", exact=True).set_input_files(invalid_source)
                    expect(page.locator("#notice")).to_contain_text("非空 WAV")
                    assert len(list((fixture.root / "uploads").iterdir())) == 1
                    page.get_by_label("上传参考 WAV", exact=True).set_input_files(source)
                    expect(page.get_by_label("参考音频路径", exact=True)).to_have_value(re.compile(r"uploads/[0-9a-f]{32}\.wav"))
                    page.get_by_label("参考音频文字", exact=True).fill("reference")
                    page.get_by_label("参考音频语言", exact=True).select_option("en")
                    page.get_by_label("合成语言", exact=True).select_option("en")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.get_by_text("角色已保存", exact=True)).to_be_visible()
                    saved_reference = page.get_by_label("参考音频路径", exact=True).input_value()
                    page.get_by_label("参考音频路径", exact=True).fill("uploads/missing.wav")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.locator("#notice")).to_contain_text("保存失败")
                    expect(page.get_by_label("参考音频路径", exact=True)).to_have_value("uploads/missing.wav")
                    page.get_by_label("参考音频路径", exact=True).fill(saved_reference)
                    owned_probe = manager._probe
                    manager._probe = lambda *args: ProbeResult(True, True, "external fixture")
                    page.reload(); page.wait_for_load_state("networkidle")
                    expect(page.get_by_text("外部服务，仅可查看", exact=True)).to_be_visible()
                    expect(page.get_by_role("button", name="启动 CPU 服务", exact=True)).to_be_disabled()
                    expect(page.get_by_role("button", name="停止服务", exact=True)).to_be_disabled()
                    expect(page.get_by_role("button", name="生成试听", exact=True)).to_be_disabled()
                    manager._probe = owned_probe
                    page.reload(); page.wait_for_load_state("networkidle")
                    page.get_by_role("button", name="启动 CPU 服务", exact=True).click()
                    expect(page.get_by_text("托管服务已就绪", exact=True)).to_be_visible()
                    page.get_by_label("试听文本", exact=True).fill("Hello from the studio.")
                    fixture.upstream.delay = .4
                    page.get_by_role("button", name="生成试听", exact=True).click()
                    assert fixture.upstream.entered.wait(1)
                    expect(page.get_by_role("button", name="停止服务", exact=True)).to_be_disabled()
                    expect(page.get_by_role("button", name="新建角色", exact=True)).to_be_disabled()
                    expect(page.locator("#result-audio")).to_have_attribute("src", re.compile(r"/api/tts/audio/[0-9a-f]{32}"))
                    fixture.upstream.delay = 0
                    audio_url = page.locator("#result-audio").get_attribute("src")
                    audio = page.request.get(address + audio_url)
                    assert audio.status == 200 and audio.body() == fixtures.pcm()
                    page.screenshot(path=str(args.screenshots_dir / "studio-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile overflow"
                    page.screenshot(path=str(args.screenshots_dir / "studio-mobile.png"), full_page=True)
                    page.set_viewport_size({"width": 1440, "height": 1050})
                    page.get_by_role("button", name="停止服务", exact=True).click()
                    expect(page.get_by_text("服务已停止", exact=True)).to_be_visible()

                    removed_gpt = next(fixture.models.gpt_weights_dir.glob("*.ckpt"))
                    removed_gpt.unlink()
                    page.get_by_label("参考音频文字", exact=True).fill("invalid new binding")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.locator("#notice")).to_contain_text("Model pair is incomplete")
                    expect(page.get_by_role("button", name="重新加载角色", exact=True)).to_be_hidden()
                    expect(page.get_by_label("参考音频文字", exact=True)).to_have_value("invalid new binding")
                    removed_gpt.touch()
                    page.get_by_label("参考音频文字", exact=True).fill("reference")

                    role = store.list()[0]
                    store.update(role["id"], CharacterPatch(description="server changed", expected_revision=role["revision"]))
                    page.get_by_label("角色名称", exact=True).fill("尚未覆盖的草稿")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.locator("#notice")).to_contain_text("修订")
                    expect(page.get_by_label("角色名称", exact=True)).to_have_value("尚未覆盖的草稿")
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="重新加载角色", exact=True).click()
                    expect(page.get_by_label("角色名称", exact=True)).to_have_value("星野 / 测试角色")

                    # Missing saved model must not be silently cleared on unrelated edits.
                    for weight in fixture.models.gpt_weights_dir.glob("*.ckpt"): weight.unlink()
                    for weight in fixture.models.sovits_weights_dir.glob("*.pth"): weight.unlink()
                    page.get_by_role("tab", name="模型", exact=True).click()
                    page.get_by_role("button", name="刷新模型", exact=True).click()
                    expect(page.get_by_text("还没有发现模型", exact=True)).to_be_visible()
                    page.get_by_role("tab", name="角色", exact=True).click()
                    page.get_by_label("角色简介", exact=True).fill("名字之外的更新")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.get_by_text("角色已保存", exact=True)).to_be_visible()
                    assert store.get(role["id"])["voice_config"]["model_id"] == "1234abcd"

                    page.get_by_label("角色名称", exact=True).fill("dirty")
                    page.once("dialog", lambda dialog: dialog.dismiss())
                    page.get_by_role("button", name="新建角色", exact=True).click()
                    expect(page.get_by_label("角色名称", exact=True)).to_have_value("dirty")
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="新建角色", exact=True).click()
                    malicious = "<img src=x onerror='window.__studioXss=true'>"
                    page.get_by_label("角色名称", exact=True).fill(malicious)
                    page.get_by_label("角色提示词", exact=True).fill("test")
                    page.get_by_role("button", name="保存角色", exact=True).click()
                    expect(page.get_by_role("button", name=malicious, exact=True)).to_be_visible()
                    assert page.evaluate("window.__studioXss !== true")

                    get_role = store.get
                    entered_get, release_get = threading.Event(), threading.Event()
                    def delayed_get(identifier):
                        if identifier == role["id"]:
                            entered_get.set()
                            release_get.wait(5)
                        return get_role(identifier)
                    with patch.object(store, "get", side_effect=delayed_get):
                        with page.expect_response(lambda response: response.url.endswith("/api/characters/" + role["id"])) as delayed_response:
                            try:
                                page.get_by_role("button", name="星野 / 测试角色", exact=True).evaluate("el => el.click()")
                                assert entered_get.wait(1), "Delayed role request did not start"
                                page.get_by_role("button", name=malicious, exact=True).evaluate("el => el.click()")
                            finally: release_get.set()
                        # body() awaits completion without this installed Playwright
                        # version's leaked Response.finished() target-close task.
                        delayed_response.value.body()
                        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                        expect(page.get_by_label("角色名称", exact=True)).to_have_value(malicious)

                    page.route("**/api/characters", lambda route: route.abort())
                    page.reload(); page.wait_for_load_state("networkidle")
                    expect(page.get_by_text("角色列表加载失败", exact=True)).to_be_visible()
                    page.unroute("**/api/characters")
                    page.get_by_role("button", name="重试角色列表", exact=True).click()
                    expect(page.get_by_role("button", name=malicious, exact=True)).to_be_visible()
                    assert not errors, errors
                    unexpected_console = [message for message in console_errors if not (
                        message.startswith("Failed to load resource:") and re.search(r"status of (409|422)|net::ERR_(FAILED|ABORTED)", message))]
                    assert not unexpected_console, unexpected_console
                    print(json.dumps({"status": "PASS", "checks": ["create/edit/reload", "upload/bind",
                        "service start/stop", "audition/audio", "revision conflict", "missing model preservation",
                        "dirty confirmation", "pending draft", "role request identity", "safe DOM", "offline retry", "mobile overflow",
                        "incomplete model", "invalid WAV/422 draft", "unmanaged service", "busy controls", "keyboard tabs", "no unexpected console/page errors"],
                        "screenshots": str(args.screenshots_dir)}, ensure_ascii=False), flush=True)
                except Exception:
                    try:
                        page.screenshot(path=str(args.screenshots_dir / "studio-failure.png"), full_page=True)
                        print(page.locator("body").inner_text()[-5000:], flush=True)
                    except Exception: pass
                    raise
                finally: browser.close()
    finally:
        server.should_exit = True
        if thread.is_alive(): thread.join(10)
        listener.close()
        app.dependency_overrides.clear()
        fixture.doCleanups()


if __name__ == "__main__": main()
