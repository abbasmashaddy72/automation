#!/usr/bin/env python3
"""Run a headless dashboard smoke test in a temporary checkout and browser."""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from container_workflows import source_ignore
from validate import ROOT

LOOPBACK = build_opener(ProxyHandler({}))


@contextmanager
def listen(command, *, cwd, env, name, pattern, stdin=subprocess.DEVNULL):
    log = cwd.parent / (name + ".log")
    with log.open("w") as output:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=stdin, stdout=output, stderr=output
        )
        try:
            deadline = time.monotonic() + 20
            while process.poll() is None and time.monotonic() < deadline:
                if match := re.search(pattern, log.read_text()):
                    yield f"http://127.0.0.1:{match[1]}"
                    return
                time.sleep(0.1)
            raise RuntimeError(f"{name} did not start:\n{log.read_text()}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def request(url, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        url, data=body, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with LOOPBACK.open(req, timeout=15) as response:
            return json.load(response)["value"]
    except HTTPError as error:
        raise RuntimeError(error.read().decode(errors="replace")) from error


def exercise(session, dashboard, base):
    def evaluate(script):
        return request(
            session + "/execute/sync", "POST", {"script": script, "args": []}
        )

    def wait_for(expression):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if evaluate("return Boolean(" + expression + ");"):
                return
            time.sleep(0.15)
        visible = evaluate("""
            return [...document.querySelectorAll("dialog[open], [role=status], #output")]
              .filter(node => node.getClientRects().length)
              .map(node => node.textContent.trim().slice(-400)).filter(Boolean);
        """)
        raise AssertionError(
            f"Condition was not met: {expression}\nVisible status: {visible}"
        )

    def click(label):
        control = (
            '[...(document.querySelector("dialog[open]") ?? document).querySelectorAll("button")].find(button => '
            f"button.textContent.trim() === {json.dumps(label)} && "
            "button.getClientRects().length && !button.disabled && "
            "!button.closest('[inert]'))"
        )
        wait_for(control)
        evaluate(control + ".click();")

    request(session + "/url", "POST", {"url": dashboard + "/#configure/configuration"})
    wait_for("document.querySelector('.project-option input')")
    evaluate("document.querySelector('.project-option input').click();")
    click("Run preview")
    wait_for(
        "document.querySelector('#result-summary').textContent.includes('toolkit-php-check/index.php')"
    )

    # Stub AI plans and approved install completion in the browser. No
    # mutation request is forwarded to the fixture server.
    evaluate("""
        localStorage.setItem("linux-setup-draft", JSON.stringify({
          ai: {model: "/srv/ai/models/fixture.gguf", backend: "cpu"}
        }));
        history.replaceState(null, "", "/#ai/ai-setup/service");
        location.reload();
    """)
    wait_for("document.querySelector('[data-ai-apply]')")
    evaluate(r"""
        window.storageError = "Restore the configured model filesystem";
        window.packageStatusRequests = 0;
        const realFetch = window.fetch;
        window.fetch = (url, options) => {
          const payload = JSON.parse(options?.body ?? "{}");
          if (url === "/execute") {
            if (window.mockInstallPath && payload.action === "ai-install" &&
                payload.confirmed === true && payload.data_root === window.mockInstallPath) {
              window.installedStorageRoot = payload.data_root;
              return Promise.resolve(new Response('{"status":0}\n'));
            }
            throw new Error("Fixture refuses mutations");
          }
          if (url === "/preview" && payload.action === "status") window.packageStatusRequests++;
          if (url !== "/preview" || !["ai-plan", "ai-eligibility"].includes(payload.action)) {
            return realFetch(url, options);
          }
          if (payload.action === "ai-eligibility") {
            window.automaticStorageRoot = payload.data_root ?? null;
          } else {
            window.previewStorageRoot = payload.data_root ?? null;
          }
          const storage = window.storageError ? {error: window.storageError} : {ready: true};
          return Promise.resolve(new Response(JSON.stringify({
            status: 0,
            output: JSON.stringify({
              storage, directories: ["", "", payload.data_root ?? window.installedStorageRoot ?? "/srv/ai"],
              hardware: {
                ram: {available_bytes: 8 * 1024 ** 3},
                system: {os: "Fixture", kernel: "fixture", architecture: "x86_64"},
                cpu: {model: "Fixture CPU"}, gpus: [], storage: []
              },
              backend_candidate: "cpu", model_recommendations: {},
              managed_install_supported: true
            })
          })));
        };
    """)
    for blocked in (True, False, True):
        value = "Restore the configured model filesystem" if blocked else ""
        evaluate(f"window.storageError = {json.dumps(value)};")
        click("Preview configuration")
        wait_for(
            "!document.querySelector('#tool-list').inert && "
            + "document.querySelector('#status').textContent === "
            + json.dumps(value if blocked else "Preview complete.")
        )
        assert (
            evaluate("return document.querySelector('[data-ai-apply]').disabled;")
            == blocked
        )
        assert (
            evaluate(
                'return document.querySelector(".ai-workflow label:has(input[type=checkbox]) input").disabled;'
            )
            == blocked
        )

    for choice, expected in (("/mnt/ai", "/mnt/ai"), ("", None)):
        evaluate('location.hash = "ai/ai-model-setup/storage";')
        wait_for("document.querySelector('select[data-ai-setting=\"store_choice\"]')")
        evaluate(f"""
            const picker = document.querySelector('select[data-ai-setting="store_choice"]');
            picker.value = {json.dumps(choice)};
            picker.dispatchEvent(new Event("change"));
            location.hash = "ai/ai-setup/build";
        """)
        wait_for(f"window.automaticStorageRoot === {json.dumps(expected)}")
        click("Check eligibility")
        wait_for(f"window.previewStorageRoot === {json.dumps(expected)}")
        shown = expected or "/srv/ai"
        wait_for(
            "document.querySelector('#result-summary').textContent.includes("
            + json.dumps(f"Model storage: {shown} ·")
            + ")"
        )

    first_tab = request(session + "/window")
    evaluate(
        'void decide("Draft sync fixture", "Keep this tab open during an external edit.");'
    )
    second_tab = request(session + "/window/new", "POST", {"type": "tab"})["handle"]
    request(session + "/window", "POST", {"handle": second_tab})
    request(session + "/url", "POST", {"url": dashboard + "/#install"})
    wait_for(
        "document.querySelector('nav button[aria-pressed=true]')?.dataset.page === 'install'"
    )
    evaluate("""
        const draft = JSON.parse(localStorage.getItem("linux-setup-draft"));
        draft.ai.store_choice = "custom";
        draft.ai.data_root = "/tmp/shared-models";
        draft.selected = ["git"];
        draft.projectPhpSample = true;
        localStorage.setItem("linux-setup-draft", JSON.stringify(draft));
    """)
    request(session + "/window", "POST", {"handle": first_tab})
    wait_for("draftPending")
    assert evaluate("return localModelRoot() === undefined;")
    click("Cancel")
    wait_for(
        'localModelRoot() === "/tmp/shared-models" && '
        'window.automaticStorageRoot === "/tmp/shared-models" && '
        'document.querySelector("#selected-ids li")?.textContent === "git"'
    )
    evaluate('location.hash = "configure/configuration";')
    wait_for("document.querySelector('.project-option input')?.checked")

    evaluate('location.hash = "install";')
    wait_for(
        '!document.querySelector("#install").hidden && window.packageStatusRequests > 0 && !packageStatusRunning'
    )
    status_calls = evaluate("return window.packageStatusRequests;")
    evaluate("renderPackages(); renderPackages();")
    assert evaluate("return window.packageStatusRequests;") == status_calls
    evaluate("""
        for (const name of packageStatusChecked.keys()) packageStatusChecked.set(name, 1);
        window.dispatchEvent(new Event("focus"));
    """)
    wait_for(f"window.packageStatusRequests > {status_calls} && !packageStatusRunning")
    status_calls = evaluate("return window.packageStatusRequests;")
    click("Refresh status")
    wait_for(
        f"window.packageStatusRequests > {status_calls} && !packageStatusRunning && "
        'document.querySelector("#package-status-message").textContent === "Package status updated."'
    )
    status_calls = evaluate("return window.packageStatusRequests;")

    evaluate("busy = true;")
    request(session + "/window", "POST", {"handle": second_tab})
    evaluate("""
        const draft = JSON.parse(localStorage.getItem("linux-setup-draft"));
        draft.ai.data_root = "/tmp/later-models";
        localStorage.setItem("linux-setup-draft", JSON.stringify(draft));
    """)
    request(session + "/window", "POST", {"handle": first_tab})
    wait_for("draftPending")
    added = evaluate("""
        const checkbox = document.querySelector("#packages input:not(:checked)");
        checkbox.click();
        return [...selected].find(name => name !== "git");
    """)
    assert added
    evaluate("busy = false; syncDashboardDraft();")
    wait_for(
        'localModelRoot() === "/tmp/later-models" && '
        f"selected.has({json.dumps(added)}) && "
        f'JSON.parse(localStorage.getItem("linux-setup-draft")).selected.includes({json.dumps(added)})'
    )

    evaluate("""
        aiSettings.model = "/tmp/later-models/fixture.gguf";
        window.storageError = "";
        window.mockInstallPath = "/tmp/later-models";
        location.hash = "ai/ai-setup/service";
    """)
    click("Preview configuration")
    wait_for('!document.querySelector("[data-ai-apply]").disabled')
    evaluate('document.querySelector("[data-ai-apply]").click();')
    click("Continue")
    wait_for('configuredModelRoot === "/tmp/later-models"')
    wait_for(
        'document.querySelector("#eligibility-summary").textContent.includes("/tmp/later-models")'
    )
    evaluate('location.hash = "ai/ai-model-setup/storage";')
    wait_for(
        'document.querySelector(\'select[data-ai-setting="store_choice"] option[value=""]\')'
        '?.textContent.includes("/tmp/later-models")'
    )
    evaluate('location.hash = "install";')
    wait_for(f"window.packageStatusRequests > {status_calls} && !packageStatusRunning")

    request(session + "/window/rect", "POST", {"width": 390, "height": 820})
    for route, selector in (
        ("install", "#package-select-panel"),
        ("advanced/restore", "#advanced-restore"),
        ("configure/zed", "#tool-list .form-action-row"),
        ("ai/ai-setup/service", "[data-ai-apply]"),
    ):
        evaluate(f"location.hash = {json.dumps(route)};")
        wait_for(
            f"location.hash === {json.dumps('#' + route)} && "
            f"document.querySelector({json.dumps(selector)})?.getClientRects().length"
        )
        assert evaluate(
            "return document.documentElement.scrollWidth <= document.documentElement.clientWidth;"
        )

    evaluate('location.hash = "install";')
    wait_for(
        '!document.querySelector("#install").hidden && document.querySelector("#packages input:not(:checked)")'
    )
    evaluate("busy = true;")
    queued = evaluate("""
        const before = new Set(selected);
        document.querySelector("#packages input:not(:checked)").click();
        return [...selected].find(name => !before.has(name));
    """)
    assert queued
    assert evaluate("return sessionStorage.getItem(draftRecoveryKey) !== null;")
    request(session + "/window", "POST", {"handle": second_tab})
    evaluate("""
        const draft = JSON.parse(localStorage.getItem("linux-setup-draft"));
        draft.projectPhpSample = false;
        localStorage.setItem("linux-setup-draft", JSON.stringify(draft));
    """)
    request(session + "/window", "POST", {"handle": first_tab})
    request(session + "/refresh", "POST", {})
    wait_for(
        f"selected.has({json.dumps(queued)}) && !projectPhpSample && "
        f"JSON.parse(localStorage.getItem(draftKey)).selected.includes({json.dumps(queued)}) && "
        "sessionStorage.getItem(draftRecoveryKey) === null"
    )

    evaluate('location.hash = "home";')
    wait_for('!document.querySelector("#home").hidden && !draftPending')
    profile_status_revision = evaluate("return packageStatusRevision;")
    click("Import Profile")
    wait_for('document.querySelector(`#decision button[value="accept"]`).disabled')
    evaluate("""
        const file = document.querySelector('#decision input[type="file"]');
        const transfer = new DataTransfer();
        transfer.items.add(new File([new Uint8Array(512 * 1024 + 1)], "large.json"));
        file.files = transfer.files;
        file.dispatchEvent(new Event("change", {bubbles: true}));
    """)
    wait_for(
        'document.querySelector("#profile-file-error").textContent.includes("exceeds 512 KiB") && '
        'document.querySelector(`#decision button[value="accept"]`).disabled'
    )
    assert evaluate("""
        const dialog = document.querySelector("#decision");
        const input = dialog.querySelector('input[type="file"]');
        const footer = dialog.querySelector(".dialog-actions");
        return dialog.scrollWidth === dialog.clientWidth &&
          input.getBoundingClientRect().right <= dialog.getBoundingClientRect().right &&
          footer.getBoundingClientRect().top > input.getBoundingClientRect().bottom &&
          parseFloat(getComputedStyle(footer).columnGap) >= 8;
    """)
    evaluate("""
        const file = document.querySelector('#decision input[type="file"]');
        const transfer = new DataTransfer();
        transfer.items.add(new File(['{invalid'], "broken.json"));
        file.files = transfer.files;
        file.dispatchEvent(new Event("change", {bubbles: true}));
    """)
    wait_for(
        'document.querySelector("#profile-file-error").textContent.includes("Invalid JSON at line 1")'
    )
    assert evaluate(
        'return document.querySelector(`#decision button[value="accept"]`).disabled;'
    )
    evaluate("""
        const transfer = new DataTransfer();
        transfer.items.add(new File([JSON.stringify({
          schema: 79, type: "automation-profile", application_version: "2026.11.18",
          sections: {
            setup: {selected: ["profile-fixture"], ai: {shell: "fish", port: 8081}},
            toolkit: {AUTOMATION_LERD: "false"},
            zed: {tab_size: 3},
          },
        })], "profile.json", {type: "application/json"}));
        const file = document.querySelector('#decision input[type="file"]');
        file.files = transfer.files;
        file.dispatchEvent(new Event("change", {bubbles: true}));
    """)
    wait_for(
        'document.querySelector("#profile-file-error").textContent.includes("Unsupported profile schema")'
    )
    click("Edit JSON")
    wait_for('document.querySelector("#decision textarea")')
    evaluate("""
        const editor = document.querySelector("#decision textarea");
        const data = JSON.parse(editor.value);
        data.schema = 2;
        editor.value = JSON.stringify(data);
    """)
    click("Format JSON")
    wait_for(
        r'document.querySelector("#decision textarea")?.value.includes("\n  \"schema\"")'
    )
    click("Review profile")
    wait_for(
        'document.querySelector(".profile-review")?.textContent.includes("profile-fixture") && '
        'document.querySelector(".profile-review")?.textContent.includes("retired Local AI shell preference")'
    )
    assert evaluate("""
        const details = [...document.querySelectorAll(".profile-review details")].find(row =>
            row.querySelector("pre").textContent.includes("profile-fixture"));
        details.querySelector("summary").click();
        return details.open;
    """)
    click("Edit settings")
    evaluate("""
        const editor = document.querySelector("#decision textarea");
        const data = JSON.parse(editor.value);
        data.sections.zed.tab_size = 4;
        editor.value = JSON.stringify(data);
    """)
    click("Review profile")
    click("Apply profile")
    wait_for(
        'document.querySelector("#profile-status").textContent.includes("Profile imported.") && !draftPending'
    )
    assert evaluate(
        'return !Object.hasOwn(aiSettings, "shell") && aiSettings.port === 8081;'
    )
    assert evaluate(f"return packageStatusRevision > {profile_status_revision};")
    request(session + "/refresh", "POST", {})
    wait_for('selected.has("profile-fixture")')
    evaluate("""
        const stored = JSON.parse(localStorage.getItem(draftKey));
        stored.ai = {...stored.ai, shell: "fish", port: 8081};
        localStorage.setItem(draftKey, JSON.stringify(stored));
    """)
    request(session + "/refresh", "POST", {})
    wait_for('aiSettings.shell === "fish" && aiSettings.port === 8081')
    evaluate("""
        const original = URL.createObjectURL;
        URL.createObjectURL = file => {
          file.text().then(value => { window.profileFixture = JSON.parse(value); });
          return original(file);
        };
    """)
    click("Export Profile")
    click("Download profile")
    wait_for(
        'window.profileFixture?.sections.setup.selected.includes("profile-fixture") && '
        "window.profileFixture?.sections.zed.tab_size === 4 && "
        "window.profileFixture?.sections.setup.ai.port === 8081"
    )
    assert evaluate(
        'return !Object.hasOwn(window.profileFixture.sections.setup.ai, "shell") && aiSettings.shell === "fish";'
    )
    wait_for(
        'document.querySelector("#profile-status").textContent.includes("skipped outdated or unsupported")'
    )

    evaluate('location.hash = "ai/ai-config";')
    wait_for('document.querySelector(`[aria-label="Backend to inspect"]`)')
    click("Check API authentication")
    wait_for(
        'document.querySelector("#tool-list").textContent.includes("API authentication ·")'
    )
    click("Inspect model endpoint")
    wait_for(
        'document.querySelector("#output-slot").textContent.includes("authentication")'
    )

    evaluate('location.hash = "home";')
    wait_for('!document.querySelector("#home").hidden')
    click("Import Profile")
    evaluate("""
        const file = document.querySelector('#decision input[type="file"]');
        const transfer = new DataTransfer();
        transfer.items.add(new File([JSON.stringify(window.profileFixture)], "export.json"));
        file.files = transfer.files;
        file.dispatchEvent(new Event("change", {bubbles: true}));
    """)
    click("Open profile")
    wait_for('document.querySelector("#decision textarea")')
    click("Cancel")

    state = base / "state/automation-toolkit"
    settings = base / "toolkit/.env"
    assert "AUTOMATION_LERD=false" in settings.read_text()
    zed = base / "config/zed/settings.json"
    assert json.loads(zed.read_bytes())["tab_size"] == 4

    def field(selector, value):
        evaluate(f"""
            const input = document.querySelector({json.dumps(selector)});
            input.value = {json.dumps(value)};
            input.dispatchEvent(new Event("input", {{bubbles: true}}));
        """)

    evaluate('location.hash = "advanced/restore";')
    wait_for("!document.querySelector('#advanced-restore').hidden")
    field("#advanced-backup-id", "invalid")
    click("Preview restore")
    wait_for(
        'document.querySelector("#advanced-restore-status").textContent.includes("full configuration backup ID")'
    )
    field("#advanced-backup-id", next(state.glob("config-*.json")).name)
    click("Preview restore")
    wait_for('document.querySelector("#decision").open')
    click("Restore settings")
    wait_for(
        'document.querySelector("#advanced-restore-status").textContent.includes("restored")'
    )
    assert "AUTOMATION_LERD" not in settings.read_text()

    evaluate('location.hash = "configure/zed";')
    wait_for('document.querySelector("#tool-list .form-action-row input")')
    field("#tool-list .form-action-row input", next(state.glob("zed-*.json")).name)
    click("Restore settings backup")
    click("Restore")
    wait_for('document.querySelector("#status").textContent.includes("complete")')
    assert zed.read_bytes() == b'{"tab_size": 2, "vim_mode": false}\n'

    click("Setup checklist")
    wait_for('document.querySelector("#manual-checks input")')
    evaluate('document.querySelector("#manual-checks input").click();')
    wait_for(
        'document.querySelector("#checklist-status").textContent.includes("progress saved")'
    )
    click("Close")
    click("Setup checklist")
    wait_for('document.querySelector("#manual-checks input")?.checked')
    click("Close")

    evaluate('location.hash = "maintenance/smart-backup";')
    wait_for('document.querySelector(`[aria-label="Documents format"]`)')
    field('[aria-label="Destination folder"]', str(base / "destination"))
    evaluate("""
        const choice = document.querySelector('[aria-label="Documents format"]');
        choice.value = "zip";
        choice.dispatchEvent(new Event("change", {bubbles: true}));
        const root = document.querySelector(".backup-toggles input");
        if (root.checked) root.click();
    """)
    click("Preview backup")
    click("Create backup")
    click("Create backup")
    wait_for(
        'document.querySelector("#tool-list").textContent.includes("Backup created and verified")'
    )
    (snapshot,) = (base / "destination").glob("smart-backup-*")
    assert (snapshot / "manifest.json").is_file()
    (archive,) = snapshot.rglob("*.zip")
    with zipfile.ZipFile(archive) as backup:
        (entry,) = [
            name
            for name in backup.namelist()
            if name.endswith("/fixture.txt") or name == "fixture.txt"
        ]
        assert backup.read(entry) == b"dashboard backup fixture\n"

    for route in ("maintenance/cleanup", "maintenance/system-cleanup"):
        evaluate(f"location.hash = {json.dumps(route)};")
        wait_for(f"activeRoute === {json.dumps('#' + route)}")
        click("Run preview")
        wait_for(
            'document.querySelector("#status").textContent.includes("Preview complete")'
        )

    evaluate('location.hash = "install";')
    wait_for('!document.querySelector("#install").hidden')
    click("Clear selection")
    click("All packages")
    field("#search", "python3")
    wait_for('document.querySelector(`[data-package-status="python3"]`)')
    evaluate(
        'document.querySelector(`[data-package-status="python3"]`).closest("label").querySelector("input").click();'
    )
    click("Next: preview selected packages")
    wait_for(
        'reviewed?.plan.packages.some(row => row.name === "python3" && row.status === "installed")'
    )
    click("Previous: select packages")
    assert evaluate(
        'return selected.has("python3") && !document.querySelector("#package-select-panel").hidden;'
    )

    routes = evaluate("""
        return [
            "home", "install", ...advancedModes.map(mode => "advanced/" + mode),
            ...Object.entries(toolPages).flatMap(([page, value]) =>
              value.tools.map(([tab]) => page + "/" + tab)),
            "ai/ai-setup/service", "ai/ai-model-setup/testing",
        ];
    """)
    for width in (320, 1260):
        request(session + "/window/rect", "POST", {"width": width, "height": 900})
        for route in routes:
            evaluate(f"location.hash = {json.dumps(route)};")
            wait_for(f"activeRoute.startsWith({json.dumps('#' + route)})")
            assert evaluate(
                "return document.documentElement.scrollWidth <= document.documentElement.clientWidth;"
            ), (width, route)
        evaluate('location.hash = "advanced/restore";')
        wait_for("!document.querySelector('#advanced-restore').hidden")
        assert evaluate(f"""
            const field = document.querySelector("#advanced-backup-id").getBoundingClientRect();
            const action = document.querySelector("#advanced-preview-restore").getBoundingClientRect();
            return {str(width < 544).lower()} ?
              action.top - field.bottom >= 8 :
              Math.abs(field.bottom - action.bottom) <= 1 && action.left - field.right >= 8;
        """), width


def main():
    driver = shutil.which("chromedriver")
    browser = shutil.which("google-chrome") or shutil.which("chromium")
    if not driver or not browser or os.geteuid() == 0:
        raise SystemExit(
            "Run as a regular user with Chrome or Chromium and matching ChromeDriver."
        )
    with (
        tempfile.TemporaryDirectory(prefix="automation-dashboard-") as temp,
        ExitStack() as stack,
    ):
        base = Path(temp)
        checkout = base / "toolkit"
        shutil.copytree(ROOT, checkout, ignore=source_ignore)
        home = base / "home"
        home.mkdir()
        (home / "Documents").mkdir()
        (home / "Documents/fixture.txt").write_text("dashboard backup fixture\n")
        (base / "destination").mkdir()
        (base / "config/zed").mkdir(parents=True)
        (base / "config/zed/settings.json").write_text(
            '{"tab_size": 2, "vim_mode": false}\n'
        )
        env = {
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_STATE_HOME": str(base / "state"),
            "XDG_CACHE_HOME": str(base / "cache"),
            "XDG_DATA_HOME": str(base / "data"),
        }
        master, terminal = os.openpty()
        stack.callback(os.close, master)
        stack.callback(os.close, terminal)
        dashboard = stack.enter_context(
            listen(
                ["bash", "setup.sh", "dashboard", "open", "0"],
                cwd=checkout,
                env=env,
                name="dashboard",
                pattern=r"Setup dashboard: http://127\.0\.0\.1:(\d+)",
                stdin=terminal,
            )
        )
        webdriver = stack.enter_context(
            listen(
                [driver, "--port=0"],
                cwd=checkout,
                env=env,
                name="chromedriver",
                pattern=r"ChromeDriver was started successfully on port (\d+)",
            )
        )
        session_id = request(
            webdriver + "/session",
            "POST",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "chrome",
                        "goog:chromeOptions": {
                            "binary": browser,
                            "args": [
                                "--headless",
                                "--disable-dev-shm-usage",
                                f"--user-data-dir={base / 'browser'}",
                            ],
                        },
                    }
                }
            },
        )["sessionId"]
        session = webdriver + "/session/" + session_id
        stack.callback(request, session, "DELETE")
        exercise(session, dashboard, base)
    print(
        "Isolated Chromium verified profiles, settings and Zed restore, checklist persistence, ZIP contents, package status, AI eligibility and endpoint checks, and responsive routes."
    )


if __name__ == "__main__":
    main()
