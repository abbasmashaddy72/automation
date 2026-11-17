"use strict";

const byId = (id) => document.getElementById(id);
const toolPages = {
  configure: {
    title: "Configure",
    tools: [
      [
        "configuration",
        "Configuration and Project Sites",
        "Preview creating missing defaults and directories.",
      ],
      ["zed", "Zed settings", "Preview the settings merge."],
      [
        "desktop",
        "Desktop integration",
        "Check the active desktop and supported favorites.",
      ],
      ["system-telemetry", "System telemetry", "Check distribution reporting."],
      ["lerd", "Lerd", "Install or check the local development stack."],
      ["terminal", "Terminal", "Install and configure Bash, Fish and Zsh."],
    ],
  },
  maintenance: {
    title: "Maintenance",
    tools: [
      [
        "system",
        "System diagnostics",
        "Check your distribution, prerequisites and listeners.",
      ],
      [
        "cleanup",
        "Toolkit Cache Cleanup",
        "Preview expired toolkit cache entries.",
      ],
      [
        "system-cleanup",
        "System Cleanup",
        "Review system package archives, unused packages and journal usage.",
      ],
      [
        "inventory",
        "Package inventory",
        "Review installations recorded by the toolkit.",
      ],
      [
        "smart-backup",
        "Smart Backup",
        "Copy or ZIP selected folders to a backup destination.",
      ],
      ["recovery", "Recovery status", "Review the last recorded operations."],
    ],
  },
  ai: {
    title: "Local AI",
    tools: [
      [
        "ai-setup",
        "AI Installation",
        "Build llama.cpp and configure its managed service.",
      ],
      [
        "ai-config",
        "AI Configuration",
        "Set the shared execution location for installation and models.",
      ],
      [
        "ai-model-setup",
        "Models & Testing",
        "Add GGUF models, switch the active model, or run a generation test.",
      ],
      [
        "chat",
        "ChatGPT Lite",
        "Check requirements, build the client, then preview its launch.",
      ],
      [
        "webui",
        "Open WebUI",
        "Install and run the authenticated client using rootless Podman.",
      ],
    ],
  },
};

let catalog;
let category;
let selected = new Set();
let busy = false;
let reviewed;
const blankOutput = byId("results").cloneNode(true);
const outputPanels = new Map([["home", byId("results")]]);
let activeOutput = byId("results");

function mountOutput(page) {
  const selectedTab =
    toolPages[page] && (currentTab[page] ?? toolPages[page].tools[0][0]);
  const key =
    selectedTab === "ai-model-setup"
      ? `ai-model-setup/${modelTab}`
      : page === "advanced"
        ? `advanced/${advancedMode}`
        : selectedTab || page;
  if (!outputPanels.has(key))
    outputPanels.set(key, blankOutput.cloneNode(true));
  const panel = outputPanels.get(key);
  if (panel !== activeOutput) {
    activeOutput = panel;
    byId("output-slot").replaceChildren(panel);
  }
}

function outputPart(panel, id) {
  return panel.querySelector("#" + id);
}
const installed = new Map();
let statusRequest = 0;
let searchTimer;
let batch = [];
let batchSelection = "";
let engineStatus = [];
let packageReview = false;
let aiStep = "build";
let modelTab = "storage";
let remoteModels = null;
let testingStatus;
let aiEligibility;
let aiReviewed;
let localModels = null;
let projectPhpSample = false;
const modelDownload = {};
const modelTypes = {
  general: "Common / general chat",
  coding: "Programming",
  reasoning: "Reasoning",
  balanced: "Common / 4B",
  compact_2026: "Fast general chat",
  general_2026: "General chat and coding",
  balanced_2026: "General chat, coding and reasoning",
  deepseek_v3_distill: "Community · math and reasoning",
};
let zedDraft = { mode: "apply", profile: "" };
let aiCompleted = false;
let remoteEligibility;
const currentTab = {};
let activeRoute;
let terminalShell;
let aiSettings = {};
let aiSavedAt;
let aiSaveFailed = false;
let configDraft;
let advancedMode = "review";
let advancedLoading = false;
let advancedReviewMessage = "";
const advancedModes = ["review", "settings", "restore"];
const advancedActionLabels = {
  "config-edit": "Toolkit settings",
  configuration: "Project Sites",
  packages: "Packages",
  zed: "Missing Zed defaults",
  "ai-plan": "Local llama.cpp",
  "ai-install": "Local llama.cpp",
};

let chatStep;
let chatStatus;
let chatFailed = false;
const failedPackages = new Set();
const verifiedPackages = new Map();
let remoteSettings = {};
let allReviewed = false;
const completed = new Set();

function decide(title, message, fields = [], accept = "Continue") {
  const dialog = byId("decision");
  if (dialog.open) return Promise.resolve(false);
  byId("decision-title").textContent = title;
  byId("decision-text").textContent = message;
  byId("decision-fields").replaceChildren(...fields);
  dialog.querySelector('button[value="accept"]').textContent = accept;
  const form = dialog.querySelector("form");
  return new Promise((resolve) => {
    const finish = (confirmed) => {
      form.removeEventListener("submit", submit);
      dialog.removeEventListener("cancel", cancel);
      dialog.close();
      resolve(confirmed);
    };
    const submit = (event) => {
      event.preventDefault();
      finish(event.submitter?.value === "accept");
    };
    const cancel = (event) => {
      event.preventDefault();
      finish(false);
    };
    form.addEventListener("submit", submit);
    dialog.addEventListener("cancel", cancel);
    dialog.showModal();
  });
}

function persist() {
  try {
    localStorage.setItem(
      "linux-setup-draft",
      JSON.stringify({
        selected: [...selected],
        projects: byId("stage-projects").checked,
        zed: byId("stage-zed").checked,
        ai: aiSettings,
        remote: remoteSettings,
        aiSavedAt,
      }),
    );
    return true;
  } catch {
    return false;
  }
}

function saveAiDraft() {
  const previous = aiSavedAt;
  aiSavedAt = Date.now();
  aiSaveFailed = !persist();
  if (aiSaveFailed) aiSavedAt = previous;
}

function showAlternatives(name, rows, alternatives) {
  for (const item of rows.filter((row) => row.source.startsWith("aur:"))) {
    alternatives.append(
      button(`Review ${item.package} (${item.source})`, () => {
        byId("custom-name").value = item.package;
        byId("custom-name").focus();
        byId("custom-name").scrollIntoView({ block: "nearest" });
      }),
    );
  }
  for (const item of rows.filter((row) => row.source === "native")) {
    alternatives.append(
      button(`Use ${item.package} for ${name}`, async () => {
        if (
          await decide(
            "Save package mapping",
            `${name} → ${item.package} via ${catalog.manager}\nVerify that this is the app you want. The package ID will be checked before saving.`,
          )
        ) {
          await preview(
            { action: "mapping", name, actual: item.package, confirmed: true },
            true,
          );
        }
      }),
    );
  }
}

function setupStep(name, status) {
  let row = [...byId("steps").children].find(
    (item) => item.dataset.step === name,
  );
  if (!row) {
    row = document.createElement("li");
    row.dataset.step = name;
    byId("steps").append(row);
  }
  row.dataset.state = status;
  row.textContent = `${advancedActionLabels[name] ?? name} · ${status}`;
}

const packagePattern = /^[a-zA-Z0-9][a-zA-Z0-9+._-]{0,95}$/;
const operations = {
  configuration: [["configuration", "Apply setup"]],

  cleanup: [["cleanup", "Clear expired cache"]],
  "system-cleanup": [["system-cleanup", "Clean obsolete package archives"]],
  "system-telemetry": [
    ["system-telemetry-disable", "Disable reporting"],
    ["system-telemetry-restore", "Restore reporting preference"],
  ],
  chat: [
    ["chat-build", "Build ChatGPT Lite"],
    ["chat-remove", "Remove ChatGPT Lite build"],
  ],
};
const mutatingButtons = new Map();

function button(label, onClick) {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  element.addEventListener("click", onClick);
  return element;
}

function visiblePackages() {
  const query = byId("search").value.trim().toLowerCase();
  return catalog.packages.filter(
    (row) =>
      (category === null || row.category === category) &&
      row.id.toLowerCase().includes(query),
  );
}

function renderSelection() {
  const names = [...selected];
  if (
    batch.some((step) => ["packages", "repair"].includes(step.action)) &&
    batchSelection !== names.join(",")
  )
    allReviewed = false;
  persist();
  updateAdvancedReview();
  const displayed = packageReview && reviewed ? reviewed.names : names;
  byId("selection").textContent = displayed.length
    ? `${displayed.length} selected`
    : "No packages selected.";
  byId("selected-ids").replaceChildren(
    ...displayed.map((id) => {
      const item = document.createElement("li");
      item.textContent = id;
      return item;
    }),
  );
  byId("package-select-panel").hidden = packageReview;
  byId("package-back").hidden = !packageReview;
  byId("package-step").textContent = packageReview
    ? "Step 2 of 3 · Review installation plan"
    : "Step 1 of 3 · Select packages";
  byId("package-note").hidden = !packageReview;
  byId("preview").hidden = packageReview;
  byId("execute").hidden = !packageReview;
  byId("save-plan").hidden = !packageReview;
  byId("preview").disabled = busy || !names.length;
  const matches = reviewed && reviewed.selection === names.join(",");
  byId("save-plan").disabled = !matches || busy;
  byId("execute").disabled =
    !matches ||
    busy ||
    !catalog.terminal ||
    !reviewed.plan.packages.some((row) =>
      ["available", "installed"].includes(row.status),
    );
  for (const [control, action] of mutatingButtons) {
    control.disabled =
      busy || !catalog.terminal || activeOutput.dataset.checked !== action;
  }
  byId("copy-install").disabled = !names.length;
  byId("command-text").value = names.length
    ? `bash setup.sh packages install --select ${names.join(",")}${catalog.aur_helpers.length ? " --enable-aur" : ""}`
    : "";
  byId("install-command").hidden = !names.length;
}

async function refreshStatus() {
  const packages = visiblePackages().map((row) => row.id);
  const request = ++statusRequest;
  if (!packages.length || busy) return;
  try {
    const response = await send("/preview", { action: "status", packages });
    if (!response.ok) return;
    const result = await response.json();
    if (request !== statusRequest || result.status) return;
    for (const item of JSON.parse(result.output))
      installed.set(item.name, item);
    document.querySelectorAll("[data-package-status]").forEach((badge) => {
      badge.textContent = packageStatus(badge.dataset.packageStatus);
    });
  } catch {
    /* The explicit install preview reports lookup failures. */
  }
}

function packageStatus(name) {
  const actual = installed.get(name);
  if (actual?.status === "installed")
    return actual.actual !== name
      ? `Installed · ${actual.actual}`
      : "Installed";
  if (failedPackages.has(name)) return "Failed";
  const state = verifiedPackages.get(name);
  if (state === "available") return "Available";
  if (state === "unavailable") return "Unavailable";
  return actual ? "Not installed · preview to verify source" : "Checking…";
}

function renderPackages() {
  byId("category-title").textContent = category ?? "All packages";
  const packages = visiblePackages();
  const container = byId("packages");
  container.replaceChildren();
  byId("select-visible").disabled = !packages.length;
  byId("select-visible").textContent =
    packages.length && packages.every((row) => selected.has(row.id))
      ? "Clear visible"
      : "Select visible";
  if (!packages.length) {
    const message = document.createElement("p");
    message.textContent = "No packages match this view.";
    container.append(message);
  }
  for (const row of packages) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = selected.has(row.id);
    input.addEventListener("change", () => {
      if (input.checked) selected.add(row.id);
      else selected.delete(row.id);
      byId("select-visible").textContent = packages.every((item) =>
        selected.has(item.id),
      )
        ? "Clear visible"
        : "Select visible";
      renderSelection();
    });
    const name = document.createElement("span");
    name.textContent = row.id;
    const badge = document.createElement("small");
    badge.dataset.packageStatus = row.id;
    badge.textContent = packageStatus(row.id);
    const selection = document.createElement("small");
    selection.textContent = "Selected for review";
    selection.hidden = !input.checked;
    input.addEventListener("change", () => {
      selection.hidden = !input.checked;
    });
    name.append(badge, selection);
    label.append(input, name);
    container.append(label);
  }
  renderSelection();
  void refreshStatus();
}

function renderCategories() {
  const categories = [...new Set(catalog.packages.map((row) => row.category))];
  byId("categories").replaceChildren(
    ...[null, ...categories].map((name) => {
      const control = button(name ?? "All packages", () => {
        category = name;
        renderCategories();
        renderPackages();
        const index = name === null ? 0 : categories.indexOf(name) + 1;
        byId("categories").children[index].focus();
      });
      control.setAttribute("aria-pressed", String(name === category));
      return control;
    }),
  );
}

async function send(path, payload) {
  return fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Setup-Token": catalog.token,
    },
    body: JSON.stringify(payload),
  });
}

async function preview(payload, execute = false, panel = activeOutput) {
  if (busy) return;
  busy = true;
  const advancedBatch =
    payload.action === "batch" && panel === outputPanels.get("advanced/review");
  const resultNode = (id) => outputPart(panel, id);
  let lastAuthPhase;
  if (!execute && ["packages", "repair"].includes(payload.action))
    reviewed = null;
  delete panel.dataset.checked;
  renderSelection();
  byId("tool-list").inert = true;
  panel.hidden = false;
  resultNode("alternatives").replaceChildren();
  resultNode("status").textContent =
    payload.action === "remote-ai"
      ? "Running on the selected server over SSH…"
      : execute
        ? payload.action === "backup-run"
          ? "Creating and verifying the selected backup…"
          : payload.action.startsWith("webui-") ||
              payload.action.startsWith("chat-background-")
            ? "Working on the local client…"
            : "Running. Use the launching terminal for sudo authentication and AUR recipe review."
        : "Checking on this computer…";
  resultNode("output").textContent = "";
  resultNode("result-summary").hidden = true;
  panel.scrollIntoView({ block: "nearest" });
  const failedAur = new Map();
  let succeeded = false;
  const selectionAtStart = [...selected].join(",");
  let activeStep;
  try {
    const response = await send(execute ? "/execute" : "/preview", payload);
    if (!response.ok) throw new Error(await response.text());
    if (execute) {
      const reader = response.body
        .pipeThrough(new TextDecoderStream())
        .getReader();
      let pending = "";
      let status;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += value;
        const lines = pending.split("\n");
        pending = lines.pop();
        for (const line of lines) {
          const event = JSON.parse(line);
          resultNode("output").textContent = (
            resultNode("output").textContent + (event.output ?? "")
          ).slice(-100000);
          if (event.step) {
            setupStep(event.step, event.state);
            if (event.state === "running") activeStep = event.step;
            if (event.state === "completed" && advancedBatch)
              completed.add(event.step);
          }
          if (event.aur_failure) {
            failedAur.set(event.aur_failure.name, event.aur_failure);
            failedPackages.add(event.aur_failure.name);
          }
          if (event.package_result) {
            const { name, failed } = event.package_result;
            if (failed) failedPackages.add(name);
            else failedPackages.delete(name);
            verifiedPackages.delete(name);
          }
          if (event.authentication) {
            const text = {
              checking: "Checking your terminal’s sudo session…",
              pending:
                payload.action === "terminal-default"
                  ? "Waiting for login-shell authentication. Respond in the launching terminal."
                  : "Waiting for sudo authentication. Use the password prompt or fingerprint reader at the launching terminal.",
              complete: "Sudo authenticated. Operation running…",
              failed: "Sudo authentication failed or was cancelled.",
              "recipe-review":
                "AUR install running. Check the launching terminal for PKGBUILD review and the final transaction confirmation.",
            }[event.authentication];
            if (text) resultNode("status").textContent = text;
            const notice = byId("terminal-notice");
            if (["pending", "recipe-review"].includes(event.authentication)) {
              if (lastAuthPhase !== event.authentication) {
                byId("terminal-message").textContent =
                  text + " The dashboard does not collect credentials.";
                if (!notice.open) notice.showModal();
              }
            } else if (
              ["complete", "failed"].includes(event.authentication) &&
              notice.open
            ) {
              notice.close();
            }
            lastAuthPhase = event.authentication;
            if (
              activeStep &&
              ["pending", "recipe-review", "complete"].includes(
                event.authentication,
              )
            )
              setupStep(
                activeStep,
                event.authentication === "complete"
                  ? "running"
                  : "waiting for terminal input",
              );
          }
          if (event.status !== undefined) status = event.status;
        }
      }
      succeeded = status === 0;
      resultNode("status").textContent =
        status === 0
          ? "Operation complete."
          : status === 5
            ? "Completed with unavailable selections. Review the output."
            : status === undefined
              ? "Connection ended. Check the terminal for the operation result."
              : `Operation exited with status ${status}.`;
      if (advancedBatch && status === 0) {
        if (completed.has("configuration"))
          byId("stage-projects").checked = false;
        if (completed.has("zed")) byId("stage-zed").checked = false;
        if (completed.has("ai-install")) aiSettings.stage = false;
        if (completed.has("config-edit")) {
          configDraft = null;
          byId("advanced-fields").replaceChildren();
        }
        advancedReviewMessage = "Reviewed changes applied.";
        allReviewed = false;
        completed.clear();
      }
      if (!advancedBatch || status === 2) allReviewed = false;
      if (payload.action === "packages" || payload.action === "repair") {
        for (const name of payload.packages) {
          if (!status) failedPackages.delete(name);
          verifiedPackages.delete(name);
        }
      }
      if (payload.action === "chat-build" || payload.action === "chat-remove") {
        chatFailed = status !== 0;
        if (!chatFailed) chatStep = payload.action === "chat-build" ? 2 : 0;
        chatStatus = undefined;
      }
      if (["packages", "repair", "batch"].includes(payload.action)) {
        reviewed = null;
        packageReview = false;
        installed.clear();
      }
    } else {
      const result = await response.json();
      if (payload.action === "packages" || payload.action === "repair") {
        const planLine = result.output
          .split("\n")
          .find((line) =>
            line.startsWith('{"schema": 1, "type": "automation-plan"'),
          );
        reviewed =
          planLine && !result.status
            ? {
                names: payload.packages,
                selection: selectionAtStart,
                action: payload.action,
                flatpak: payload.flatpak,
                helper: payload.helper,
                plan: JSON.parse(planLine),
              }
            : null;
        if (reviewed && !byId("install").hidden) packageReview = true;
        for (const row of reviewed?.plan.packages ?? []) {
          verifiedPackages.set(row.name, row.status);
          if (row.status === "unavailable")
            showAlternatives(
              row.name,
              row.suggestions ?? [],
              resultNode("alternatives"),
            );
        }
        resultNode("output").textContent = result.output
          .split("\n")
          .filter((line) => line !== planLine)
          .join("\n");
      } else {
        resultNode("output").textContent = result.output;
        if (
          !result.status &&
          (payload.action === "ai-plan" ||
            (payload.action === "remote-ai" && payload.operation === "plan"))
        ) {
          const plan = JSON.parse(result.output);
          if (payload.action === "remote-ai") remoteEligibility = plan;
          else if (payload.eligibility) aiEligibility = plan;
          const summary = resultNode("result-summary");
          summary.textContent = aiSummary(plan);
          summary.hidden = false;
        }
        if (!result.status && payload.action === "configuration") {
          const jsonStart = result.output.search(/^\{/m);
          if (jsonStart < 0)
            throw new Error(
              "The setup preview did not return a configuration plan.",
            );
          const { checks } = JSON.parse(result.output.slice(jsonStart));
          const projects = checks.find((row) => row.id === "projects");
          const configuration = checks.find(
            (row) => row.id === "configuration",
          );
          const summary = resultNode("result-summary");
          summary.textContent = [
            "Toolkit configuration: " +
              (configuration?.status ?? "not selected"),
            "Project root: " + (projects?.target ?? "unavailable"),
            ...(projects?.directories_to_create?.length
              ? ["Folders to create:", ...projects.directories_to_create]
              : ["No missing folders."]),
            ...(projects?.files_to_create?.length
              ? ["Files to create:", ...projects.files_to_create]
              : ["No files will be created."]),
          ].join("\n");
          summary.hidden = false;
        }
        if (!result.status && payload.action === "search") {
          const row = result.output
            .split("\n")
            .find((line) => line.startsWith('{"name":'));
          if (row)
            showAlternatives(
              payload.query,
              JSON.parse(row).suggestions,
              resultNode("alternatives"),
            );
        }
      }
      succeeded = result.status === 0;
      if (succeeded) panel.dataset.checked = payload.action;
      const cleanup = ["cleanup", "system-cleanup"].includes(payload.action);
      if (succeeded && cleanup) {
        const details = JSON.parse(result.output);
        const count =
          details.expired_toolkit_cache_entries ?? details.listed_cache_entries;
        resultNode("status").textContent = count
          ? `Preview complete. ${count} listed · ${new Intl.NumberFormat().format(details.cache_total_bytes)} bytes estimated.`
          : details.cache_preview === null
            ? "Preview complete. The native cache scan is unavailable on this system."
            : "Preview complete. No removable cache entries found.";
        if (
          payload.action === "cleanup"
            ? !count
            : !details.cache_cleanup_supported
        )
          delete panel.dataset.checked;
      } else {
        resultNode("status").textContent = result.status
          ? `Check exited with status ${result.status}.`
          : payload.action === "webui-test"
            ? "Open WebUI is responding and requires sign-in."
            : "Preview complete.";
      }
    }
  } catch (error) {
    resultNode("status").textContent = error.message;
  } finally {
    const notice = byId("terminal-notice");
    if (notice.open) notice.close();
    busy = false;
    byId("tool-list").inert = false;
    renderSelection();
    if (execute) {
      document.querySelectorAll("[data-package-status]").forEach((badge) => {
        badge.textContent = "Checking…";
      });
      if (payload.action === "chat-build" || payload.action === "chat-remove") {
        if (
          byId("tools-title").textContent === "Local AI" &&
          !byId("tools").hidden
        )
          showPage("ai");
      }
    }
    renderPackages();
  }
  if (failedAur.size) {
    const extras = resultNode("alternatives");
    for (const failure of failedAur.values())
      void aurAlternatives(failure, extras);
    if (extras.isConnected) {
      extras.focus();
      extras.scrollIntoView({ block: "center" });
    }
  }
  return succeeded;
}

async function aurAlternatives(failed, container) {
  const extras = document.createElement("section");
  extras.className = "aur-recovery";
  container.append(extras);
  const detail = document.createElement("p");
  detail.textContent = `Installation of ${failed.name} via ${failed.helper} failed. Choose an alternative below.`;
  const choice = document.createElement("input");
  choice.placeholder = "Alternative package ID";
  choice.setAttribute("aria-label", "Alternative package ID");
  extras.append(
    detail,
    button("Search package alternatives", () =>
      preview({ action: "search", query: failed.name }),
    ),
    choice,
    button("Preview my package choice", () => {
      const name = choice.value.trim();
      if (packagePattern.test(name))
        void preview({ action: "packages", packages: selectReplacement(name) });
      else {
        detail.textContent =
          "Enter a valid package ID to preview your alternative.";
        choice.focus();
      }
    }),
  );
  const flatpakRequest = {
    action: "packages",
    packages: [failed.name],
    flatpak: true,
  };
  extras.append(
    button("Check Flatpak alternative", async (event) => {
      const control = event.currentTarget;
      control.disabled = true;
      const original = detail.textContent;
      detail.textContent = "Checking configured Flatpak sources…";
      try {
        const output = await previewResult(flatpakRequest);
        const row = output
          .split("\n")
          .find((line) =>
            line.startsWith('{"schema": 1, "type": "automation-plan"'),
          );
        const available =
          row &&
          JSON.parse(row).packages.some(
            (pkg) => pkg.status === "available" && pkg.source === "flatpak",
          );
        detail.textContent = original;
        if (available)
          control.replaceWith(
            button("Preview Flatpak alternative", () =>
              preview({
                ...flatpakRequest,
                packages: selectReplacement(failed.name),
              }),
            ),
          );
        else
          detail.textContent =
            original + " No configured Flatpak alternative was verified.";
      } catch (error) {
        detail.textContent = "Flatpak lookup failed. " + error.message;
      } finally {
        control.disabled = false;
      }
    }),
  );
  for (const helper of catalog.aur_helpers.filter(
    (name) => name !== failed.helper,
  )) {
    extras.append(
      button(`Check ${failed.actual} via ${helper}`, () =>
        preview({
          action: "packages",
          packages: selectReplacement(failed.actual),
          helper,
        }),
      ),
    );
  }
}

function selectReplacement(name) {
  selected.add(name);
  renderPackages();
  return [name];
}

function syncRoute(page, replace = false) {
  const tab =
    page === "advanced"
      ? advancedMode
      : toolPages[page] && (currentTab[page] ?? toolPages[page].tools[0][0]);
  const subtab =
    tab === "ai-model-setup"
      ? modelTab
      : tab === "ai-setup"
        ? aiStep
        : tab === "terminal"
          ? terminalShell
          : undefined;
  activeRoute = "#" + [page, tab, subtab].filter(Boolean).join("/");
  if (location.hash !== activeRoute) {
    if (replace) history.replaceState(null, "", activeRoute);
    else history.pushState(null, "", activeRoute);
  }
}

function restoreRoute() {
  if (location.hash === activeRoute) return;
  const [requested, tab, subtab] = location.hash.slice(1).split("/");
  const page = [
    "home",
    "install",
    "configure",
    "maintenance",
    "ai",
    "advanced",
  ].includes(requested)
    ? requested
    : "home";
  if (page === "advanced")
    advancedMode = advancedModes.includes(tab) ? tab : "review";
  const tools = toolPages[page]?.tools;
  if (tools)
    currentTab[page] = tools.find(([id]) => id === tab)?.[0] ?? tools[0][0];
  if (currentTab[page] === "ai-model-setup")
    modelTab = subtab === "testing" ? "testing" : "storage";
  if (currentTab[page] === "ai-setup")
    aiStep = subtab === "service" ? "service" : "build";
  if (currentTab[page] === "terminal")
    terminalShell = ["bash", "fish", "zsh"].includes(subtab)
      ? subtab
      : undefined;
  showPage(page, true);
}

function showPage(page, replaceRoute = false) {
  syncRoute(page, replaceRoute);
  mountOutput(page);
  for (const control of document.querySelectorAll("nav button")) {
    control.setAttribute("aria-pressed", String(control.dataset.page === page));
  }
  byId("install").hidden = page !== "install";
  byId("advanced-page").hidden = page !== "advanced";
  byId("home").hidden = page !== "home";
  byId("tools").hidden = ["home", "install", "advanced"].includes(page);
  if (page === "advanced") {
    for (const mode of advancedModes)
      byId("advanced-" + mode).hidden = mode !== advancedMode;
    for (const button of document.querySelectorAll("[data-advanced-mode]"))
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.advancedMode === advancedMode),
      );
    if (advancedMode === "settings" && !byId("advanced-fields").children.length)
      void advanced();
    updateAdvancedReview();
    return;
  }
  if (page === "install" || page === "home") return;
  mutatingButtons.clear();
  const { title, tools } = toolPages[page];
  const active = currentTab[page] ?? tools[0][0];
  byId("tool-tabs").replaceChildren(
    ...tools.map(([id, label]) => {
      const tab = button(label, () => {
        currentTab[page] = id;
        showPage(page);
        byId("tool-tabs").querySelector('[aria-pressed="true"]')?.focus();
      });
      tab.setAttribute("aria-pressed", String(id === active));
      return tab;
    }),
  );
  byId("tools-title").textContent = title;
  byId("tool-list").replaceChildren(
    ...tools
      .filter(([id]) => id === active)
      .map(([action, name, description]) => {
        const card = document.createElement("article");
        const heading = document.createElement("h2");
        const detail = document.createElement("p");
        const control = button("Run preview", () =>
          preview({
            action,
            ...(action === "configuration"
              ? { php_sample: projectPhpSample }
              : {}),
          }),
        );
        control.setAttribute("aria-label", `Run preview for ${name}`);

        card.className = "tool";
        heading.textContent = name;
        detail.textContent = description;
        card.append(heading, detail, control);
        if (action === "smart-backup") {
          control.remove();
          renderBackup(card);
          return card;
        }
        if (action === "lerd") {
          control.remove();
          renderLerd(card);
          return card;
        }
        if (action === "terminal") {
          control.remove();
          renderTerminal(card);
          return card;
        }
        if (action === "configuration") {
          const sample = document.createElement("input");
          sample.type = "checkbox";
          sample.checked = projectPhpSample;
          sample.onchange = () => {
            projectPhpSample = sample.checked;
            delete activeOutput.dataset.checked;
            byId("result-summary").hidden = true;
            renderSelection();
          };
          const label = document.createElement("label");
          label.className = "project-option";
          label.append(
            sample,
            " Create an optional Testing/toolkit-php-check/index.php",
          );
          card.append(label);
        }
        if (["ai-config", "ai-setup", "ai-model-setup"].includes(action)) {
          control.remove();
          renderAI(card, action);
          return card;
        }
        if (action === "zed") {
          const backup = document.createElement("input");
          backup.placeholder = "zed-…json";
          const field = document.createElement("label");
          field.className = "model-path";
          field.append("Restore backup ID", backup);
          card.append(
            button("View current settings", showZed),
            button("Check telemetry", () => preview({ action: "telemetry" })),
            field,
            button("Merge, override or replace", editZed),
          );
          for (const [operation, label] of [
            ["zed-backup", "Back up settings"],
            ["telemetry-disable", "Disable Zed telemetry"],
            ["telemetry-restore", "Restore telemetry preference"],
            ["zed-restore", "Restore settings backup"],
          ]) {
            const change = button(label, async () => {
              const request = {
                action: operation,
                backup: backup.value.trim(),
              };
              if (operation === "zed-restore") {
                try {
                  const restore = await previewResult(request);
                  if (!(await decide(label, restore.trim(), [], "Restore")))
                    return;
                } catch (error) {
                  await decide(
                    "Restore unavailable",
                    error.message,
                    [],
                    "Close",
                  );
                  return;
                }
              } else if (
                !(await decide(
                  label,
                  "Apply this change to your Zed configuration?",
                ))
              ) {
                return;
              }
              await preview({ ...request, confirmed: true }, true);
            });
            change.disabled = !catalog.terminal;
            card.append(change);
          }
        }
        if (action === "chat") {
          control.remove();
          renderChat(card);
          return card;
        }
        if (action === "webui") {
          control.remove();
          renderWebui(card);
          return card;
        }
        for (const [operation, label] of operations[action] ?? []) {
          const change = button(label, async () => {
            if (await decide(label, "Apply this change on this computer?")) {
              void preview(
                {
                  action: operation,
                  confirmed: true,
                  ...(action === "configuration"
                    ? { php_sample: projectPhpSample }
                    : {}),
                },
                true,
              );
            }
          });
          const checkAction = action === "chat" ? "chat-build" : action;
          mutatingButtons.set(change, checkAction);
          change.disabled =
            busy ||
            !catalog.terminal ||
            activeOutput.dataset.checked !== checkAction;
          card.append(change);
        }
        return card;
      }),
  );
}

function gib(bytes) {
  return Number.isFinite(bytes)
    ? `${(bytes / 1024 ** 3).toFixed(1)} GiB`
    : "Unknown";
}

function hardwareView(plan) {
  const { system, cpu, ram, gpus, storage } = plan.hardware;
  return [
    [
      "Operating system",
      `${system.os} · ${system.architecture} · Linux ${system.kernel}`,
    ],
    [
      "Processor",
      `${cpu.model ?? cpu.architecture} · ${cpu.logical_threads ?? "Unknown"} threads`,
    ],
    [
      "Memory",
      `${gib(ram.total_bytes)} installed · ${gib(ram.available_bytes)} available`,
    ],
    [
      "Graphics",
      gpus
        .map((gpu) =>
          [
            gpu.name ?? gpu.vendor,
            gpu.driver,
            gpu.dedicated_vram_mib
              ? `${gpu.dedicated_vram_mib} MiB VRAM`
              : "VRAM unknown",
          ]
            .filter(Boolean)
            .join(" · "),
        )
        .join("; ") || "No GPU identified",
    ],
    [
      "Storage",
      storage
        .map((disk) =>
          [disk.name, disk.model, disk.size].filter(Boolean).join(" · "),
        )
        .join("; ") || "No block devices identified",
    ],
    [
      "Model storage",
      plan.storage.error ||
        `${plan.storage.free_gib ?? "Unknown"} GiB free · ${plan.directories[2]}`,
    ],
  ];
}

function aiSummary(plan) {
  const fit = Object.keys(plan.model_recommendations).length > 0;
  const install = plan.managed_install_supported
    ? "Managed llama.cpp is supported on this system."
    : `Managed installation is unavailable. ${plan.install_blockers.join(" ")}`;
  const resources =
    plan.storage.error ||
    `${gib(plan.hardware.ram.available_bytes)} RAM available, ${plan.storage.free_gib ?? "unknown"} GiB free in the model store.`;
  return `${install} ${resources} ${fit ? "See Model setup for GGUF recommendations." : "Current CPU, GPU, RAM or disk conditions limit the reviewed model catalog."} Acceleration candidate: ${plan.backend_candidate.toUpperCase()}. GPU offload requires a runtime test.`;
}

async function loadSystem() {
  const output = byId("eligibility-summary");
  try {
    const systemPlan = JSON.parse(
      await previewResult({ action: "ai-eligibility" }),
    );
    aiEligibility ??= systemPlan;
    let desktop = {};
    try {
      desktop = JSON.parse(await previewResult({ action: "system-details" }));
    } catch {
      // Hardware remains available without desktop tools.
    }
    const { system, cpu, ram, gpus } = systemPlan.hardware;
    const details = [
      ["Operating System", desktop["Operating System"] || system.os],
      ...["KDE Plasma Version", "KDE Frameworks Version", "Qt Version"].map(
        (key) => [key, desktop[key]],
      ),
      [
        "Kernel Version",
        desktop["Kernel Version"] ||
          `${system.kernel} (${system.architecture})`,
      ],
      ["Graphics Platform", desktop["Graphics Platform"]],
      [
        "Processors",
        desktop.Processors ||
          `${cpu.logical_threads ?? "?"} × ${cpu.model ?? cpu.architecture}`,
      ],
      [
        "Memory",
        desktop.Memory ||
          `${gib(ram.total_bytes)} usable · ${gib(ram.available_bytes)} available`,
      ],
      ...(Object.entries(desktop).some(([label]) =>
        label.startsWith("Graphics Processor "),
      )
        ? Object.entries(desktop).filter(([label]) =>
            label.startsWith("Graphics Processor "),
          )
        : gpus.map((card, index) => [
            `Graphics Processor ${index + 1}`,
            card.name ?? card.vendor,
          ])),
      ...["Manufacturer", "Product Name", "System Version"].map((key) => [
        key,
        desktop[key],
      ]),
      ...hardwareView(systemPlan).filter(([key]) =>
        ["Storage", "Model storage"].includes(key),
      ),
    ];
    byId("hardware").replaceChildren(
      ...details
        .filter(([, value]) => value)
        .map(([label, value]) => {
          const row = document.createElement("div");
          const term = document.createElement("dt");
          const data = document.createElement("dd");
          term.textContent = label;
          data.textContent = value;
          row.append(term, data);
          return row;
        }),
    );
    output.textContent = aiSummary(systemPlan);
    engineStatus = JSON.parse(await previewResult({ action: "ai-engines" }));
    const engines = engineStatus.map(
      (engine) =>
        `${engine.engine}: ${engine.state}${engine.managed ? " (supported)" : " (external)"}`,
    );
    output.textContent += ` ${engines.join(" · ")}.`;
  } catch (error) {
    output.textContent = `System check could not complete. ${error.message}`;
  }
}

function localModelRoot() {
  if (
    aiSettings.store_choice === "custom" ||
    aiSettings.store_choice === undefined
  )
    return aiSettings.data_root;
  return aiSettings.store_choice || undefined;
}

function updateLlamaStatus(changes) {
  const engine = engineStatus.find((item) => item.engine === "llama.cpp");
  if (engine) Object.assign(engine, changes);
  else engineStatus.push({ engine: "llama.cpp", managed: true, ...changes });
}

function selectRecommendedModel(plan, initial) {
  const recommendations = plan.model_recommendations;
  const catalog = plan.model_catalog;
  const mode = document.createElement("select");
  mode.setAttribute("aria-label", "Model list");
  mode.add(new Option("Recommended for this hardware", "recommended"));
  mode.add(new Option("All catalog models (manual selection)", "manual"));
  if (
    !Object.keys(recommendations).length ||
    (catalog[initial] && !recommendations[initial])
  )
    mode.value = "manual";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Search by name, purpose, or quantization";
  search.setAttribute("aria-label", "Search recommended models");
  const list = document.createElement("div");
  list.className = "recommended-models";
  let selectedModel = catalog[initial] ? initial : undefined;
  const refresh = () => {
    const filter = search.value.trim().toLowerCase();
    const available = mode.value === "manual" ? catalog : recommendations;
    const entries = Object.entries(available).filter(([kind, entry]) =>
      [modelTypes[kind], entry.name, entry.filename]
        .join(" ")
        .toLowerCase()
        .includes(filter),
    );
    if (!entries.some(([kind]) => kind === selectedModel))
      selectedModel = undefined;
    list.replaceChildren(
      ...entries.map(([kind, entry]) => {
        const row = document.createElement("label");
        const choice = document.createElement("input");
        choice.type = "radio";
        choice.name = "recommended-model";
        choice.checked = selectedModel === kind;
        choice.onchange = () => {
          selectedModel = kind;
        };
        const details = document.createElement("span");
        details.textContent = [
          entry.name,
          entry.filename,
          gib(entry.size_bytes) +
            " · " +
            new Intl.NumberFormat().format(entry.size_bytes) +
            " bytes",
          modelTypes[kind],
          entry.year ? String(entry.year) : "",
          entry.runtime_note,
          entry.fit
            ? entry.fit_mode +
              " · ~" +
              entry.estimated_ram_gib +
              " GiB system RAM"
            : entry.fit_issues.join(". "),
        ]
          .filter(Boolean)
          .join(" · ");
        row.append(choice, details);
        return row;
      }),
    );
    if (!entries.length) list.textContent = "No matching catalog models.";
  };
  search.oninput = refresh;
  mode.onchange = refresh;
  refresh();
  const fit = plan.model_fit;
  const summary = document.createElement("p");
  const graphics =
    fit.available_vram_mib == null
      ? "GPU memory unavailable"
      : fit.gpu + " · " + fit.available_vram_mib + " MiB free VRAM";
  summary.textContent = [
    fit.cpu_threads + " CPU threads",
    fit.available_ram_gib + " GiB RAM available",
    fit.free_disk_gib + " GiB disk free",
    graphics,
    fit.backend.toUpperCase() +
      (fit.backend !== "cpu" && !fit.gpu_planning_ready
        ? " build prerequisites unavailable; using CPU estimates"
        : ""),
  ].join(" · ");
  return decide(
    "Choose a GGUF model",
    "Review estimated fit. A manual selection can include a community model or a model outside the current estimate.",
    [summary, mode, search, list],
    "Use model",
  ).then((accepted) => (accepted ? selectedModel : undefined));
}

function shellCommand(argv) {
  return argv
    .map((arg) => "'" + String(arg).replaceAll("'", "'\"'\"'") + "'")
    .join(" ");
}

function renderAI(card, section) {
  const modelsTab = section === "ai-model-setup";
  const installation = section === "ai-setup";
  const body = document.createElement("div");
  body.className = "workflow ai-workflow";
  card.append(body);

  function open(tab, subtab) {
    if (subtab) modelTab = subtab;
    currentTab.ai = tab;
    showPage("ai");
    byId("tool-tabs").querySelector('[aria-pressed="true"]')?.focus();
  }

  function draw() {
    const step = modelsTab ? modelTab : installation ? aiStep : "configuration";
    const remote = aiSettings.location === "ssh";
    const download = aiSettings.model_mode === "download";
    const pinnedModel =
      aiEligibility?.model_catalog?.[aiSettings.recommendation];
    if (download && pinnedModel && !modelDownload.model_url) {
      Object.assign(modelDownload, {
        model_url: pinnedModel.url,
        sha256: pinnedModel.sha256,
        size_bytes: pinnedModel.size_bytes,
      });
    }
    const modelOptions = download
      ? { ...modelDownload }
      : { model: aiSettings.model };
    const modelReady = () =>
      download
        ? /^https:\/\/.+\.gguf(?:$|[?#])/i.test(
            modelDownload.model_url ?? "",
          ) &&
          /^[a-f0-9]{64}$/i.test(modelDownload.sha256 ?? "") &&
          Number.isInteger(modelDownload.size_bytes) &&
          modelDownload.size_bytes >= 4
        : /^\/.+\.gguf$/i.test(aiSettings.model ?? "");
    const paragraph = (text) => {
      const p = document.createElement("p");
      p.textContent = text;
      body.append(p);
    };
    const field = (
      settings,
      key,
      label,
      { hint = "", choices, type = "text", readOnly = false } = {},
    ) => {
      const wrapper = document.createElement("label");
      wrapper.className = "model-path";
      const input = document.createElement(choices ? "select" : "input");
      if (choices) {
        input.dataset.aiSetting = key;
        for (const [value, text] of choices) input.add(new Option(text, value));
      } else {
        input.type = type;
        input.placeholder = hint;
        input.readOnly = readOnly;
      }
      input.value = settings[key] ?? choices?.[0]?.[0] ?? "";
      const update = () => {
        settings[key] =
          type === "number"
            ? input.value
              ? Number(input.value)
              : null
            : input.value.trim();
        aiReviewed = null;
        aiCompleted = false;
        allReviewed = false;
        if (
          settings === remoteSettings &&
          ["host", "user", "directory", "data_root"].includes(key)
        ) {
          remoteEligibility = null;
          remoteModels = null;
          remoteSettings.model = "";
          testingStatus = undefined;
        }
        if (settings === aiSettings && key === "location")
          testingStatus = undefined;
        if (
          settings === aiSettings &&
          ["data_root", "store_choice"].includes(key)
        ) {
          localModels = null;
          aiSettings.model = "";
        }
        if (settings !== modelDownload) {
          saveAiDraft();
          updateSaveNotice();
        }
        if (choices) {
          draw();
          body.querySelector(`select[data-ai-setting="${key}"]`)?.focus();
        } else {
          const install = body.querySelector("[data-ai-apply]");
          if (install) install.disabled = true;
          const downloadButton = body.querySelector("[data-model-download]");
          if (downloadButton)
            downloadButton.disabled = !modelReady() || !catalog.terminal;
        }
      };
      if (choices) input.onchange = update;
      else input.oninput = update;
      wrapper.append(label, input);
      body.append(wrapper);
    };
    const run = async (control, callback) => {
      control.disabled = true;
      const panel = activeOutput;
      try {
        await callback();
      } catch (error) {
        showAIReadError(error, panel);
      } finally {
        if (body.isConnected) draw();
      }
    };
    const task = (label, callback, parent = body) => {
      const control = button(label, () => run(control, callback));
      control.disabled = busy;
      parent.append(control);
      return control;
    };
    const engine = engineStatus.find((item) => item.managed);
    const options = {
      data_root: localModelRoot(),
      ...modelOptions,
      gpu_layers: aiSettings.gpu_layers,
      port: aiSettings.port,
      backend: aiSettings.backend || (engine?.owned_service ? "auto" : "cpu"),
      install_mode: engine?.owned_service
        ? aiSettings.install_mode || "update"
        : "install",
      reconfigure: Boolean(
        engine?.owned_service && (localModelRoot() || aiSettings.port),
      ),
    };
    body.replaceChildren();
    if (installation || modelsTab) {
      const target = document.createElement("div");
      target.className = "ai-target control-row";
      const location = document.createElement("p");
      location.textContent = remote
        ? `Target: ${remoteSettings.host || "SSH server not configured"}`
        : "Target: this computer";
      target.append(location);
      task("Change execution location", () => open("ai-config"), target);
      body.append(target);
    }
    if (modelsTab) {
      const tabs = document.createElement("div");
      tabs.className = "tool-tabs";
      tabs.setAttribute("role", "group");
      tabs.setAttribute("aria-label", "Model tools");
      for (const [id, title] of [
        ["storage", "Storage & Downloads"],
        ["testing", "Testing"],
      ]) {
        const tab = button(title, () => {
          modelTab = id;
          syncRoute("ai");
          mountOutput("ai");
          draw();
          if (id === "testing") void loadTestingStatus();
          body
            .querySelector(".tool-tabs")
            ?.querySelector('[aria-pressed="true"]')
            ?.focus();
        });
        tab.setAttribute("aria-pressed", String(modelTab === id));
        tabs.append(tab);
      }
      body.append(tabs);
    }
    if (installation) {
      const heading = document.createElement("h3");
      heading.textContent =
        step === "build" ? "Check and build" : "Configure service";
      body.append(heading);
    }
    const saveNotice = document.createElement("p");
    saveNotice.className = "ai-save";
    saveNotice.setAttribute("role", "status");
    updateSaveNotice();
    body.append(saveNotice);

    function updateSaveNotice() {
      saveNotice.dataset.state = aiSaveFailed
        ? "error"
        : aiSavedAt
          ? "saved"
          : "default";
      saveNotice.textContent = aiSaveFailed
        ? "Browser could not save these settings. Changes may be lost after closing the page."
        : aiSavedAt
          ? `Dashboard settings saved in this browser · ${new Date(aiSavedAt).toLocaleTimeString()}. Apply service changes from Configure service.`
          : "Dashboard choices save in this browser as you edit. Configure service applies them to the selected host.";
    }
    const remoteRequest = (operation, values = {}) => ({
      action: "remote-ai",
      host: remoteSettings.host,
      user: remoteSettings.user,
      directory: remoteSettings.directory,
      operation,
      ...(remoteSettings.data_root && ["plan", "models"].includes(operation)
        ? { data_root: remoteSettings.data_root }
        : {}),
      ...values,
    });
    const hasSSH = ["host", "user", "directory"].every(
      (key) => remoteSettings[key],
    );
    if (remote && !hasSSH && step !== "configuration") {
      paragraph(
        "Set the SSH host, user and toolkit path in AI Configuration first.",
      );
      return;
    }
    if (installation || step === "testing") {
      const statusBlock = document.createElement("p");
      statusBlock.className = "ai-state";
      statusBlock.textContent = llamaServiceSummary(testingStatus);
      body.append(statusBlock);
    }
    if (step === "configuration") {
      field(aiSettings, "location", "Run inference on", {
        choices: [
          ["local", "This computer"],
          ["ssh", "Remote Linux server over SSH"],
        ],
      });
      if (remote) {
        paragraph(
          "Use a trusted OpenSSH host with an existing key or agent. Enter the remote toolkit path so the dashboard can run its maintained checks.",
        );
        field(remoteSettings, "host", "Hostname or IP", {
          hint: "ai-server.local",
        });
        field(remoteSettings, "user", "SSH user", { hint: "operator" });
        field(remoteSettings, "directory", "Remote toolkit path", {
          hint: "/home/operator/automation",
        });
        task("Test SSH and inspect server", () =>
          preview(remoteRequest("plan")),
        );
        if (remoteEligibility) paragraph(aiSummary(remoteEligibility));
      }
      paragraph(
        "Enable terminal questions and command suggestions per shell from Configure → Terminal.",
      );
      task("Open Terminal configuration", () => {
        currentTab.configure = "terminal";
        showPage("configure");
      });
    } else if (step === "build") {
      if (remote) {
        paragraph(
          "Check the server first. Build and apply on the SSH terminal so you can handle native authentication.",
        );
        task("Check remote eligibility", () => preview(remoteRequest("plan")));
        if (remoteEligibility) paragraph(aiSummary(remoteEligibility));
        commandExample("bash setup.sh ai server build --yes");
      } else {
        paragraph(
          aiEligibility
            ? aiSummary(aiEligibility)
            : "Check this computer's hardware and supported build backends.",
        );
        task("Check eligibility", () =>
          preview({ action: "ai-plan", eligibility: true }),
        );
        paragraph(
          "Build only compiles llama.cpp. Configure service registers and starts the background service. A first-time service install can build the binary automatically.",
        );
        if (engine?.owned_service) {
          field(aiSettings, "install_mode", "Build action", {
            choices: [
              ["update", "Update upstream source"],
              ["reinstall", "Rebuild installed source"],
            ],
          });
        } else if (
          engine?.installed &&
          testingStatus &&
          !testingStatus.managed_binary
        ) {
          paragraph(
            "An external llama.cpp installation was detected. Its binary and service stay under their existing management. Review listeners before a separate toolkit installation.",
          );
        }
        const choices = engine?.owned_service
          ? [["auto", "Detect backend"]]
          : [["cpu", "CPU (works without GPU drivers)"]];
        if (
          aiEligibility?.backend_candidate !== "cpu" &&
          aiEligibility?.backend_candidate
        ) {
          const backend = aiEligibility.backend_candidate;
          choices.push([
            backend,
            `${backend.toUpperCase()} · CPU/GPU offload (verify after installation)`,
          ]);
        }
        field(aiSettings, "backend", "Inference build", { choices });
        const build = task("Build binary only", async () => {
          const selection = {
            action: "ai-build",
            backend: aiSettings.backend || options.backend,
            install_mode: options.install_mode,
          };
          if (
            await decide(
              "Build the llama.cpp binary",
              "Install compile prerequisites and build llama-server. Then use Configure service with a GGUF to start llama.cpp in the background.",
            )
          )
            if (
              (await preview({ ...selection, confirmed: true }, true)) &&
              body.isConnected
            )
              testingStatus = await readAI({ action: "ai-status" });
        });
        build.disabled =
          build.disabled ||
          !catalog.terminal ||
          !aiEligibility?.managed_install_supported;
      }
    } else if (step === "storage") {
      const storageActions = document.createElement("div");
      storageActions.className = "control-row";
      if (remote) {
        field(remoteSettings, "data_root", "Model storage on the server", {
          hint: remoteEligibility?.directories?.[2] ?? "/srv/ai",
        });
        task(
          "Scan remote GGUF files",
          async () => {
            remoteModels = await readAI(remoteRequest("models"));
          },
          storageActions,
        );
        task(
          "Check remote storage and model fit",
          () => preview(remoteRequest("plan")),
          storageActions,
        );
        body.append(storageActions);
        if (remoteModels?.length) {
          paragraph(`Found ${remoteModels.length} GGUF file(s) on the server.`);
          field(remoteSettings, "model", "Remote GGUF", {
            choices: [
              ["", "Choose a GGUF"],
              ...remoteModels.map(({ path, gib }) => [
                path,
                `${path} · ${gib} GiB`,
              ]),
            ],
          });
        } else {
          if (remoteModels)
            paragraph("No usable single-file GGUFs in this folder.");
          field(remoteSettings, "model", "Remote GGUF path", {
            hint: "/srv/ai/models/model.gguf",
          });
        }
        task("Review remote model download", async () => {
          const plan = await readAI(remoteRequest("plan"));
          if (!plan) return;
          const id = await selectRecommendedModel(plan);
          if (!id) return;
          const item = plan.model_catalog[id];
          const args = [
            "bash",
            "setup.sh",
            "ai",
            "server",
            "model-download",
            ...(remoteSettings.data_root
              ? ["--data-root", remoteSettings.data_root]
              : []),
            "--model-url",
            item.url,
            "--sha256",
            item.sha256,
            "--size-bytes",
            item.size_bytes,
            "--yes",
          ];
          await decide(
            "Download on the SSH server",
            `Run from the remote toolkit directory. After the verified download, scan the server folder again.\n\n${shellCommand(args)}`,
            [],
            "Close",
          );
        });
        task("Continue to service configuration", () => {
          aiStep = "service";
          open("ai-setup");
        });
      } else {
        const roots = [
          ...new Set(
            [
              aiEligibility?.directories[2] ?? "/srv/ai",
              "/srv/ai",
              "/mnt/ai",
              ...(aiSettings.store_choice === undefined && aiSettings.data_root
                ? [aiSettings.data_root]
                : []),
            ].filter(Boolean),
          ),
        ];
        field(aiSettings, "store_choice", "Model storage folder", {
          choices: [
            ["", "Configured model store"],
            ...roots.map((path) => [path, path]),
            ["custom", "Enter another absolute folder"],
          ],
        });
        if (aiSettings.store_choice === "custom") {
          field(aiSettings, "data_root", "Custom model storage folder", {
            hint: "/mnt/ai",
          });
        }
        const fitOptions = () => ({
          data_root: localModelRoot(),
          backend: aiSettings.backend || options.backend,
          gpu_layers:
            (aiSettings.backend || options.backend) === "cpu"
              ? null
              : aiSettings.gpu_layers,
        });
        task(
          "Check space and model fit",
          () =>
            preview({ action: "ai-plan", eligibility: true, ...fitOptions() }),
          storageActions,
        );
        task(
          "Inspect spare storage volumes",
          () => preview({ action: "ai-storage" }),
          storageActions,
        );
        body.append(storageActions);
        const recommendation =
          aiEligibility?.model_catalog?.[aiSettings.recommendation];
        task("Browse models", async () => {
          try {
            const plan = JSON.parse(
              await previewResult({ action: "ai-plan", ...fitOptions() }),
            );
            aiEligibility = plan;
            const kind = await selectRecommendedModel(
              plan,
              aiSettings.recommendation,
            );
            if (!kind) return;
            const entry = plan.model_catalog[kind];
            aiSettings.recommendation = kind;
            aiSettings.model_mode = "download";
            Object.assign(modelDownload, {
              model_url: entry.url,
              sha256: entry.sha256,
              size_bytes: entry.size_bytes,
            });
            aiReviewed = null;
            allReviewed = false;
            saveAiDraft();
          } catch (error) {
            await decide(
              "Could not assess model fit",
              error.message,
              [],
              "Close",
            );
          }
        });
        if (recommendation)
          paragraph(
            recommendation.name + " · " + gib(recommendation.size_bytes),
          );
        paragraph(
          "Recommendations use current hardware and disk. Use the manual list for other catalog entries, or provide your own GGUF below.",
        );
        field(aiSettings, "model_mode", "Model source", {
          choices: [
            ["existing", "Use a GGUF already on disk"],
            ["download", "Download a verified GGUF"],
          ],
        });
        if (download) {
          paragraph(
            "Custom download details are temporary. A catalog selection can be opened again after reloading.",
          );
          field(modelDownload, "model_url", "Direct HTTPS GGUF URL", {
            hint: "https://…/model.gguf",
            readOnly: Boolean(pinnedModel),
          });
          field(modelDownload, "sha256", "Independently verified SHA-256", {
            hint: "64 hexadecimal characters",
            readOnly: Boolean(pinnedModel),
          });
          field(modelDownload, "size_bytes", "Exact size in bytes", {
            type: "number",
            readOnly: Boolean(pinnedModel),
          });
          if (pinnedModel)
            task("Enter custom download details", () => {
              delete aiSettings.recommendation;
              Object.assign(modelDownload, {
                model_url: "",
                sha256: "",
                size_bytes: null,
              });
              aiReviewed = null;
              allReviewed = false;
              saveAiDraft();
            });
          const source =
            aiEligibility?.model_catalog?.[aiSettings.recommendation]?.url;
          if (source) {
            const link = document.createElement("a");
            link.textContent = "View the suggested file and publisher metadata";
            link.href = source.replace("/resolve/", "/blob/");
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            body.append(link);
          }
          const add = task("Download model", async () => {
            const request = {
              action: "ai-model-download",
              data_root: localModelRoot(),
              ...modelDownload,
            };
            if (
              !(await decide(
                "Download and verify model",
                request.model_url +
                  "\nSHA-256: " +
                  request.sha256 +
                  "\nBytes: " +
                  request.size_bytes,
              ))
            )
              return;
            if (await preview({ ...request, confirmed: true }, true)) {
              localModels = JSON.parse(
                await previewResult({
                  action: "ai-models",
                  data_root: localModelRoot(),
                }),
              );
              const filename = new URL(request.model_url).pathname
                .split("/")
                .at(-1);
              const downloaded = localModels.find(({ path }) =>
                path.endsWith("/" + filename),
              );
              if (downloaded) {
                aiSettings.model = downloaded.path;
                aiSettings.model_mode = "existing";
                aiReviewed = null;
                saveAiDraft();
              }
            }
          });
          add.dataset.modelDownload = "";
          add.disabled = add.disabled || !modelReady() || !catalog.terminal;
        } else {
          task("Scan local GGUF files", async () => {
            localModels = await readAI({
              action: "ai-models",
              data_root: localModelRoot(),
            });
          });
          if (localModels?.length) {
            paragraph(
              `Found ${localModels.length} GGUF file(s) on this computer.`,
            );
            field(aiSettings, "model", "Existing model", {
              choices: [
                ["", "Choose a GGUF"],
                ...localModels.map(({ path, gib }) => [
                  path,
                  path.split("/").at(-1) + " · " + gib + " GiB",
                ]),
              ],
            });
          } else {
            if (localModels)
              paragraph("No usable single-file GGUFs in this model store.");
            field(aiSettings, "model", "Existing GGUF file", {
              hint: "/srv/ai/models/model.gguf",
            });
          }
        }
        if (engine?.owned_service || options.backend !== "cpu") {
          field(
            aiSettings,
            "gpu_layers",
            "GPU layers (blank keeps automatic offload)",
            { type: "number", hint: "e.g. 25" },
          );
          paragraph(
            "Layers are an offload setting. GPU/CPU utilization varies with the model and context.",
          );
        }
        if (engine?.owned_service) {
          const activate = task("Switch active model", async () => {
            const model = aiSettings.model;
            if (
              await decide(
                "Switch active model",
                "Restart the managed service with " + model + "?",
              )
            )
              await preview(
                {
                  action: "ai-model-switch",
                  model,
                  gpu_layers: aiSettings.gpu_layers,
                  confirmed: true,
                },
                true,
              );
          });
          activate.disabled =
            activate.disabled || download || !modelReady() || !catalog.terminal;
        }
        task("Continue to service configuration", () => {
          aiStep = "service";
          open("ai-setup");
        });
      }
    } else if (step === "service") {
      explainPort();
      if (remote) {
        field(
          remoteSettings,
          "port",
          "Service loopback port (blank keeps existing/default)",
          { type: "number", hint: String(remoteEligibility?.port ?? 8080) },
        );
        portCheckButton(() =>
          remoteRequest("port-check", { port: remoteSettings.port }),
        );
        const model = remoteSettings.model;
        if (typeof model === "string" && /^\/.+\.gguf$/i.test(model)) {
          paragraph(`Selected remote model: ${model}`);
          const args = [
            "bash",
            "setup.sh",
            "ai",
            "server",
            "install",
            ...(remoteSettings.data_root
              ? ["--data-root", remoteSettings.data_root]
              : []),
            ...(remoteSettings.port ? ["--port", remoteSettings.port] : []),
            "--model",
            model,
            "--no-pull",
          ];
          commandExample(
            `${shellCommand([...args, "--dry-run"])}\n${shellCommand([...args, "--reconfigure", "--yes"])}`,
          );
        } else
          paragraph(
            "Select a remote GGUF before generating an installation command.",
          );
        task("Choose remote model", () => open("ai-model-setup", "storage"));
        task("Use currently configured model", useConfiguredModel);
      } else {
        field(
          aiSettings,
          "port",
          "Service loopback port (blank keeps existing/default)",
          {
            hint: String(aiEligibility?.port ?? 8080),
            type: "number",
          },
        );
        portCheckButton(() => ({
          action: "ai-port-check",
          port: aiSettings.port,
        }));
        if (modelReady())
          paragraph(
            `Selected model: ${options.model || pinnedModel?.name || "verified GGUF download"}`,
          );
        else
          paragraph(
            "Installation needs a GGUF. Scan an existing folder or choose a verified download.",
          );
        task(modelReady() ? "Change model" : "Choose a model", () =>
          open("ai-model-setup", "storage"),
        );
        if (engine?.owned_service)
          task("Use currently configured model", useConfiguredModel);
        const configured = () => ({
          ...options,
          port: aiSettings.port,
          reconfigure: Boolean(
            engine?.owned_service && (localModelRoot() || aiSettings.port),
          ),
        });
        const signature = JSON.stringify(configured());
        const review = task("Preview configuration", async () => {
          const proposed = configured();
          aiReviewed = (await preview({
            action: "ai-plan",
            eligibility: true,
            ...proposed,
          }))
            ? JSON.stringify(proposed)
            : null;
        });
        review.disabled = review.disabled || !modelReady();
        const install = task(
          options.install_mode === "update"
            ? "Update and test"
            : options.install_mode === "reinstall"
              ? "Reinstall and test"
              : "Install and test",
          async () => {
            if (
              !(await decide(
                "Apply llama.cpp configuration",
                `Model: ${options.model || "Verified GGUF download"}\nBuild: ${options.backend}\nStorage: ${options.data_root || aiEligibility?.directories[2]}\nThe installer registers a systemd service, enables it at boot and tests the API. After setup, the service runs independently of this dashboard and terminal.`,
              ))
            )
              return;
            aiCompleted = await preview(
              { action: "ai-install", ...options, confirmed: true },
              true,
            );
            if (aiCompleted) {
              aiStep = "service";
              updateLlamaStatus({
                installed: true,
                owned_service: true,
                state: "running",
              });
            }
            if (body.isConnected)
              testingStatus = await readAI({ action: "ai-status" });
          },
        );
        const queue = document.createElement("input");
        queue.type = "checkbox";
        queue.checked = Boolean(aiSettings.stage);
        queue.disabled = busy || (!queue.checked && signature !== aiReviewed);
        queue.onchange = () => {
          aiSettings.stage = queue.checked;
          allReviewed = false;
          saveAiDraft();
          renderSelection();
        };
        const queueLabel = document.createElement("label");
        queueLabel.append(
          queue,
          " Include this configuration in Advanced → Review All Changes",
        );
        body.append(queueLabel);
        install.dataset.aiApply = "";
        install.disabled ||=
          !catalog.terminal ||
          !aiEligibility?.managed_install_supported ||
          signature !== aiReviewed;
        if (aiCompleted) paragraph("Installation and smoke test completed.");
      }
    } else if (step === "testing") {
      const diagnostics = (action, operation, port) =>
        remote ? remoteRequest(operation, { port }) : { action, port };
      const testSettings = remote ? remoteSettings : aiSettings;
      const service = testingStatus?.service;
      const config = testingStatus?.config;
      const owned = remote
        ? Boolean(config?.model)
        : Boolean(engine?.owned_service || config?.model);
      if (config?.model)
        paragraph(
          `Active configuration: ${config.model} · ${config.context} configured tokens · ${config.parallel} slot(s) · port ${config.port}`,
        );
      explainPort();
      task("Refresh service status", async () => {
        testingStatus = await readAI(
          remote ? remoteRequest("status") : { action: "ai-status" },
        );
      });
      field(
        testSettings,
        "test_port",
        "Diagnostic port (blank uses the service port)",
        {
          type: "number",
          hint: String(
            config?.port ??
              (remote ? remoteEligibility?.port : aiEligibility?.port) ??
              8080,
          ),
        },
      );
      portCheckButton(() =>
        diagnostics("ai-port-check", "port-check", testSettings.test_port),
      );
      task("Verify API and loaded models", () =>
        preview(diagnostics("ai-verify", "verify", testSettings.test_port)),
      );
      task("Check effective context", () =>
        preview(
          diagnostics(
            "ai-runtime-context",
            "runtime-context",
            testSettings.test_port,
          ),
        ),
      );
      if (owned) {
        const test = task("Test active model", async () => {
          if (
            await decide(
              "Test active model",
              "Send a short test prompt to the running managed llama.cpp service on the selected target?",
            )
          ) {
            await preview(
              remote
                ? remoteRequest("test-model", { confirmed: true })
                : { action: "ai-model-test", confirmed: true },
              true,
            );
          }
        });
        test.disabled ||=
          (service && service !== "active") || (!remote && !catalog.terminal);
        paragraph(
          "The short generation test checks the managed model at its configured port. Context is the total token budget shared by parallel slots. Increasing it uses more RAM or VRAM.",
        );
        field(
          testSettings,
          "context_tokens",
          "New total context tokens (256–131072)",
          { type: "number", hint: String(config?.context ?? 4096) },
        );
        task("Review context change", async () => {
          const tokens = testSettings.context_tokens;
          const request = remote
            ? remoteRequest("context", { context_tokens: tokens })
            : { action: "ai-context", context_tokens: tokens };
          const plan = await readAI(request);
          if (!plan) return;
          const summary = `Configured: ${plan.configured_tokens} tokens. Requested: ${tokens} across ${plan.parallel_slots} slot(s), about ${plan.target_tokens_per_slot} per slot.\nThe test restarts the service if needed and restores the previous context if verification fails.`;
          if (remote || !catalog.terminal) {
            await decide(
              "Apply context in the target terminal",
              `${summary}\n\nbash setup.sh ai server context --context-tokens ${tokens} --yes`,
              [],
              "Close",
            );
          } else if (
            await decide(
              "Apply and test context",
              summary,
              [],
              "Apply and test",
            )
          ) {
            await preview({ ...request, confirmed: true }, true);
            if (body.isConnected)
              testingStatus = await readAI({ action: "ai-status" });
          }
        });
        const running = service
          ? service === "active"
          : engine?.state === "running";
        for (const operation of running ? ["stop", "restart"] : ["start"]) {
          const title = `${operation[0].toUpperCase()}${operation.slice(1)} managed service`;
          const control = task(title, async () => {
            if (
              await decide(
                title,
                "Apply this change to the managed service on the selected target?",
              )
            ) {
              await preview(
                remote
                  ? remoteRequest(operation, { confirmed: true })
                  : { action: "ai-" + operation, confirmed: true },
                true,
              );
              if (body.isConnected)
                testingStatus = await readAI(
                  remote ? remoteRequest("status") : { action: "ai-status" },
                );
            }
          });
          control.disabled ||= !remote && !catalog.terminal;
        }
      } else {
        paragraph(
          "Refresh service status after installation to enable managed model and context tests.",
        );
      }
    }

    if (installation) {
      const navigation = document.createElement("div");
      navigation.className = "presets";
      const switchStep = (target) => {
        aiStep = target;
        syncRoute("ai");
        draw();
        body.querySelector("h3")?.focus();
      };
      const heading = body.querySelector("h3");
      heading.tabIndex = -1;
      if (step === "build")
        navigation.append(
          button("Continue to service configuration", () =>
            switchStep("service"),
          ),
        );
      else
        navigation.append(
          button("Back to check and build", () => switchStep("build")),
        );
      navigation.append(
        button("Open Testing", () => open("ai-model-setup", "testing")),
      );
      body.append(navigation);
    }

    function explainPort() {
      paragraph(
        "The port is the HTTP endpoint on the machine running llama.cpp, usually http://127.0.0.1:8080/v1. Loopback is accessible from that machine only. SSH diagnostics check the server’s own loopback. Choose a different port only when needed; the toolkit LAN gateway requires port 8080.",
      );
    }
    function commandExample(text) {
      const pre = document.createElement("pre");
      pre.textContent = text;
      body.append(pre);
    }
    async function useConfiguredModel() {
      const panel = activeOutput;
      const details = await readAI(
        remote ? remoteRequest("status") : { action: "ai-status" },
      );
      if (!details) return;
      const { model, data_root: root } = details.config ?? {};
      if (!model || !root) {
        showAIReadError(
          new Error(
            "This target has no configured model and data root. Choose a model from Storage & Downloads.",
          ),
          panel,
        );
        return;
      }
      if (remote) {
        remoteSettings.model = model;
        remoteSettings.data_root = root;
        remoteModels = null;
      } else {
        aiSettings.model = model;
        aiSettings.data_root = root;
        aiSettings.store_choice = "custom";
        aiSettings.model_mode = "existing";
        localModels = null;
        aiReviewed = null;
        allReviewed = false;
      }
      saveAiDraft();
    }
    async function readAI(request) {
      const panel = activeOutput;
      try {
        return JSON.parse(await previewResult(request));
      } catch (error) {
        showAIReadError(error, panel);
        return null;
      }
    }
    function portCheckButton(request) {
      task("Check loopback port", async () => {
        const panel = activeOutput;
        const result = await readAI(request());
        if (!result) return;
        const status = outputPart(panel, "status");
        panel.hidden = false;
        status.textContent = {
          free: `Port ${result.port} is free; no inference service is listening there.`,
          healthy: `A healthy llama.cpp endpoint responded on port ${result.port}.`,
          unavailable: `Port ${result.port} cannot be bound and llama.cpp readiness was not confirmed.`,
        }[result.state];
        outputPart(panel, "result-summary").hidden = true;
        outputPart(panel, "output").textContent = result.detail ?? "";
      });
    }
  }
  draw();
  if (installation || (modelsTab && modelTab === "testing"))
    void loadTestingStatus();

  async function loadTestingStatus() {
    const request =
      aiSettings.location === "ssh"
        ? {
            action: "remote-ai",
            operation: "status",
            host: remoteSettings.host,
            user: remoteSettings.user,
            directory: remoteSettings.directory,
          }
        : { action: "ai-status" };
    if (
      request.action === "remote-ai" &&
      !(request.host && request.user && request.directory)
    )
      return;
    try {
      const details = JSON.parse(await previewResult(request));
      if (!body.isConnected || (!installation && modelTab !== "testing"))
        return;
      testingStatus = details;
      draw();
    } catch {
      // The explicit refresh control reports connection and CLI errors.
    }
  }
}

function llamaServiceSummary(status) {
  if (!status) return "Service status has yet to be checked.";
  const configured = status.configured ?? Boolean(status.config?.model);
  if (!configured) {
    return status.managed_binary
      ? "Binary built. Background service has yet to be configured. Choose a model and apply Configure service."
      : "No toolkit-managed llama.cpp service is configured on this host.";
  }
  const state =
    status.service_unit === "not-found"
      ? "unit missing"
      : status.service || "unknown";
  const boot =
    status.boot_state === "enabled"
      ? "enabled"
      : status.boot_state || "not verified";
  const api =
    status.api_ready === true
      ? "ready"
      : status.api_ready === false
        ? "unverified"
        : "not checked";
  return (
    `Service settings saved on host · systemd: ${state} · startup at boot: ${boot} · API: ${api}.` +
    (state === "active"
      ? " The service runs independently of this dashboard and terminal."
      : "")
  );
}

function showAIReadError(error, panel = activeOutput) {
  panel.hidden = false;
  outputPart(panel, "result-summary").hidden = true;
  outputPart(panel, "status").textContent = error.message.trim();
  outputPart(panel, "output").textContent = "";
}

const backupDraft = {
  source: "",
  destination: "",
  jobs: new Map(),
  folderHidden: new Map(),
  children: new Map(),
  expanded: new Set(),
  rootFiles: false,
  showHidden: false,
  verification: "checksum",
  hidden: false,
  exclusions: new Map(),
  extra: "",
};

async function backupBrowse(path, hidden = true) {
  return JSON.parse(
    await previewResult({ action: "backup-browse", path, hidden }),
  );
}

async function pickBackupFolder(start, home, onPick) {
  const current = document.createElement("p");
  const folder = document.createElement("select");
  folder.setAttribute("aria-label", "Subfolder");
  let opened;
  async function show(path) {
    try {
      opened = await backupBrowse(path);
      current.textContent = opened.path;
      folder.replaceChildren(new Option("Select a subfolder", ""));
      for (const name of opened.folders) folder.add(new Option(name, name));
      open.disabled = true;
      up.disabled = opened.path === opened.parent;
    } catch (error) {
      current.textContent = error.message.trim();
    }
  }
  const open = button("Open subfolder", () =>
    show(backupJoin(opened.path, folder.value)),
  );
  const up = button("Parent folder", () => show(opened.parent));
  const goHome = button("Home folder", () => show(home));
  folder.onchange = () => {
    open.disabled = !folder.value;
  };
  await show(start || home);
  if (
    await decide(
      "Browse directories",
      "Open a subfolder, or use the directory shown below.",
      [current, folder, backupGroup("backup-actions", up, goHome, open)],
      "Use this folder",
    )
  ) {
    if (opened) onPick(opened.path);
  }
}

function backupGroup(className, ...children) {
  const group = document.createElement("div");
  group.className = className;
  group.append(...children);
  return group;
}

function backupJoin(directory, child) {
  return directory.replace(/\/$/, "") + "/" + child;
}

function renderBackup(card) {
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const options = document.createElement("fieldset");
  options.disabled = true;
  const listing = document.createElement("div");
  listing.className = "backup-folders";
  listing.setAttribute("aria-label", "Backup folder selections");
  const columns = backupGroup("backup-tree-columns");
  for (const label of ["Folder", "Action", "Hidden files"]) {
    const heading = document.createElement("span");
    heading.textContent = label;
    columns.append(heading);
  }
  const summary = document.createElement("div");
  summary.className = "result-summary";
  summary.hidden = true;
  let defaults;
  let reviewedBackup;
  let confirming = false;

  function invalidate() {
    reviewedBackup = undefined;
    summary.hidden = true;
    create.disabled = true;
  }

  function inputField(name, value, change, placeholder = "") {
    const label = document.createElement("label");
    label.className = "model-path";
    const input = document.createElement("input");
    input.value = value;
    input.placeholder = placeholder;
    input.setAttribute("aria-label", name);
    input.oninput = () => {
      invalidate();
      change(input.value);
    };
    label.append(name, input);
    return [label, input];
  }

  const [sourceLabel, source] = inputField(
    "Source folder",
    backupDraft.source,
    (value) => {
      if (backupDraft.source !== value) clearSourceChoices();
      backupDraft.source = value;
      renderFolders();
    },
  );
  const [destLabel, dest] = inputField(
    "Destination folder",
    backupDraft.destination,
    (value) => {
      backupDraft.destination = value;
    },
    "/run/media/you/Backup",
  );
  const sourceBrowse = button("Browse source", () =>
    pickBackupFolder(source.value, defaults.home, (path) => {
      if (backupDraft.source !== path) clearSourceChoices();
      source.value = backupDraft.source = path;
      invalidate();
      void loadFolders();
    }),
  );
  const destBrowse = button("Browse destination", () =>
    pickBackupFolder(dest.value, defaults.home, (path) => {
      dest.value = backupDraft.destination = path;
      invalidate();
    }),
  );
  const drives = document.createElement("select");
  drives.setAttribute("aria-label", "Mounted external drives");
  drives.onchange = () => {
    if (drives.value) {
      dest.value = backupDraft.destination = drives.value;
      invalidate();
    }
  };
  const driveStatus = document.createElement("p");

  const [nestedLabel, nested] = inputField(
    "Add a nested or hidden folder",
    "",
    () => {},
    "For example, Documents/Project-Sites",
  );
  function addFolder(value) {
    const trimmed = value.trim();
    const parts = trimmed.split("/").filter((part) => part && part !== ".");
    const path = parts.join("/");
    if (!path || trimmed.startsWith("/") || parts.includes("..")) {
      status.textContent = "Enter a folder relative to the selected source.";
      return;
    }
    if (!backupDraft.jobs.has(path)) backupDraft.jobs.set(path, "");
    for (let depth = 1; depth < parts.length; depth += 1)
      backupDraft.expanded.add(parts.slice(0, depth).join("/"));
    invalidate();
    renderFolders();
    nested.value = "";
    findRowControl("path", path)?.focus();
  }

  function clearSourceChoices() {
    backupDraft.jobs.clear();
    backupDraft.folderHidden.clear();
    backupDraft.children.clear();
    backupDraft.expanded.clear();
    backupDraft.rootFiles = false;
    topFiles.checked = false;
  }

  function useHomeDefaults(result) {
    backupDraft.jobs = new Map(
      result.home_jobs.map(({ path, mode }) => [path, mode]),
    );
    backupDraft.folderHidden.clear();
    topFiles.checked = backupDraft.rootFiles = true;
    invalidate();
    renderFolders();
  }

  async function toggleFolder(path) {
    if (backupDraft.expanded.delete(path)) {
      renderFolders(path);
      return;
    }
    try {
      const requested = backupDraft.source;
      const result = await backupBrowse(backupJoin(requested, path), true);
      if (requested !== backupDraft.source || !listing.isConnected) return;
      backupDraft.children.set(path, result.folders);
      backupDraft.expanded.add(path);
      renderFolders(path);
      if (result.more)
        status.textContent =
          "Showing the first 250 subfolders. Add any remaining folders by path below.";
    } catch (error) {
      status.textContent = error.message.trim();
    }
  }

  function renderFolders(focusPath) {
    const rows = [];
    const selections = [...backupDraft.jobs.keys()];
    function children(parent) {
      const prefix = parent === "." ? "" : parent + "/";
      const known = selections
        .filter(
          (path) => path !== "." && path !== parent && path.startsWith(prefix),
        )
        .map((path) => path.slice(prefix.length).split("/")[0]);
      return [
        ...new Set([
          ...(backupDraft.children.get(parent) ?? []).filter(
            (name) => backupDraft.showHidden || !name.startsWith("."),
          ),
          ...known,
        ]),
      ].sort((a, b) => a.localeCompare(b));
    }
    function addRow(path, depth, inherited) {
      const root = path === ".";
      const name = root ? "Entire source folder" : path.split("/").pop();
      const row = document.createElement("div");
      row.className = "backup-tree-row";
      row.style.setProperty("--tree-depth", Math.min(depth, 6));
      const title = document.createElement("span");
      title.className = "backup-tree-name";
      if (!root) {
        const expanded = backupDraft.expanded.has(path);
        const expand = button(expanded ? "▾" : "▸", async () => {
          expand.disabled = true;
          await toggleFolder(path);
          expand.disabled = false;
        });
        expand.dataset.folder = path;
        expand.setAttribute(
          "aria-label",
          `${expanded ? "Collapse" : "Expand"} ${path}`,
        );
        expand.setAttribute("aria-expanded", String(expanded));
        title.append(expand);
      }
      const text = document.createElement("span");
      text.textContent = name;
      title.append(text);
      const format = document.createElement("select");
      format.dataset.path = path;
      format.setAttribute("aria-label", `${root ? name : path} format`);
      const inheritLabel =
        { copy: "Inherit Copy", zip: "Inherit ZIP", skip: "Inherit Skip" }[
          inherited
        ] || "Not selected";
      for (const [value, label] of [
        ["", inheritLabel],
        ["copy", "Copy"],
        ["zip", "ZIP archive"],
      ]) {
        format.add(new Option(label, value));
      }
      if (!root) format.add(new Option("Skip this folder", "skip"));
      format.value = backupDraft.jobs.get(path) || "";
      const hiddenMode = document.createElement("select");
      hiddenMode.setAttribute(
        "aria-label",
        `${root ? name : path} hidden entries`,
      );
      hiddenMode.add(new Option("Default", ""));
      hiddenMode.add(new Option("Include", "yes"));
      hiddenMode.add(new Option("Exclude", "no"));
      hiddenMode.value = backupDraft.folderHidden.get(path) || "";
      hiddenMode.hidden = !["copy", "zip"].includes(format.value);
      hiddenMode.onchange = () => {
        backupDraft.folderHidden.set(path, hiddenMode.value);
        invalidate();
      };
      format.onchange = () => {
        backupDraft.jobs.set(path, format.value);
        invalidate();
        renderFolders();
        findRowControl("path", path)?.focus();
      };
      row.append(title, format, hiddenMode);
      rows.push(row);
      if (!root && !backupDraft.expanded.has(path)) return;
      const listed = children(path);
      if (!root && !listed.length) {
        const empty = document.createElement("p");
        empty.className = "backup-tree-empty";
        empty.style.setProperty("--tree-depth", Math.min(depth + 1, 6));
        empty.textContent = "No visible subfolders.";
        rows.push(empty);
      }
      const effective = format.value || inherited;
      for (const child of listed)
        addRow(
          root ? child : `${path}/${child}`,
          root ? depth : depth + 1,
          effective,
        );
    }
    addRow(".", 0, "");
    listing.replaceChildren(columns, ...rows);
    if (focusPath) findRowControl("folder", focusPath)?.focus();
  }

  function findRowControl(key, path) {
    return [...listing.querySelectorAll(`[data-${key}]`)].find(
      (node) => node.dataset[key] === path,
    );
  }

  async function loadFolders({ preset = false } = {}) {
    if (!backupDraft.source.trim()) return;
    try {
      const requested = backupDraft.source;
      const result = await backupBrowse(requested, true);
      if (backupDraft.source !== requested || !listing.isConnected) return;
      backupDraft.children.set(".", result.folders);
      if (preset) useHomeDefaults(result);
      else renderFolders();
      status.textContent = result.more
        ? "Showing the first 250 folders. Add other folders by typing their path."
        : "Expand a folder to choose how its subfolders are backed up.";
    } catch (error) {
      status.textContent = error.message.trim();
    }
  }

  const topFiles = document.createElement("input");
  topFiles.type = "checkbox";
  topFiles.checked = backupDraft.rootFiles;
  topFiles.onchange = () => {
    backupDraft.rootFiles = topFiles.checked;
    invalidate();
  };
  const topFilesLabel = document.createElement("label");
  topFilesLabel.append(
    topFiles,
    " Copy visible files directly in the source folder",
  );

  const showHiddenFolders = document.createElement("input");
  showHiddenFolders.type = "checkbox";
  showHiddenFolders.checked = backupDraft.showHidden;
  showHiddenFolders.onchange = () => {
    backupDraft.showHidden = showHiddenFolders.checked;
    renderFolders();
  };
  const showHiddenLabel = document.createElement("label");
  showHiddenLabel.append(showHiddenFolders, " Show hidden folders in the tree");

  const hidden = document.createElement("input");
  hidden.type = "checkbox";
  hidden.checked = backupDraft.hidden;
  hidden.onchange = () => {
    backupDraft.hidden = hidden.checked;
    invalidate();
  };
  const hiddenLabel = document.createElement("label");
  hiddenLabel.append(
    hidden,
    " Include hidden files and folders inside selections",
  );

  const ignored = document.createElement("fieldset");
  const ignoredTitle = document.createElement("legend");
  ignoredTitle.textContent = "Skip directories named";
  ignored.append(ignoredTitle);
  const [extrasLabel] = inputField(
    "Additional directory names to skip (comma-separated)",
    backupDraft.extra,
    (value) => {
      backupDraft.extra = value;
    },
    ".cache, .venv, build",
  );
  const verification = document.createElement("select");
  const verificationLabel = document.createElement("label");
  verificationLabel.className = "model-path";
  verificationLabel.append("Verification", verification);
  verification.add(new Option("Checksums (recommended)", "checksum"));
  verification.add(new Option("Quick copy check and ZIP integrity", "quick"));
  verification.value = backupDraft.verification;
  verification.onchange = () => {
    backupDraft.verification = verification.value;
    invalidate();
  };

  const review = button("Preview backup", async () => {
    if (busy) return;
    invalidate();
    options.disabled = true;
    status.textContent = "Scanning selected folders and estimating space…";
    const spec = {
      source: source.value.trim(),
      destination: dest.value.trim(),
      root_files: topFiles.checked,
      hidden: hidden.checked,
      verification: verification.value,
      excludes: [
        ...[...backupDraft.exclusions]
          .filter(([, checked]) => checked)
          .map(([name]) => name),
        ...backupDraft.extra
          .split(",")
          .map((name) => name.trim())
          .filter(Boolean),
      ],
      jobs: [...backupDraft.jobs]
        .filter(([, mode]) => mode)
        .map(([path, mode]) => {
          const override = backupDraft.folderHidden.get(path);
          return override
            ? { path, mode, hidden: override === "yes" }
            : { path, mode };
        }),
    };
    try {
      const plan = JSON.parse(
        await previewResult({ action: "backup-run", spec }),
      );
      const rows = document.createElement("ul");
      for (const job of plan.jobs) {
        const row = document.createElement("li");
        const label = job.scope === "root-files" ? "Top-level files" : job.path;
        row.textContent = `${job.mode === "copy" ? "Copy" : "ZIP"} ${label} → ${job.output} · ${job.entries.toLocaleString()} entries · hidden entries ${job.hidden ? "included" : "excluded"}`;
        if (job.separate.length)
          row.append(` · handled separately: ${job.separate.join(", ")}`);
        if (job.excluded_folders.length)
          row.append(` · excluded folders: ${job.excluded_folders.join(", ")}`);
        if (job.skipped_special_or_other_device)
          row.append(
            ` · ${job.skipped_special_or_other_device} special or mounted entries skipped`,
          );
        rows.append(row);
      }
      const paths = document.createElement("p");
      paths.textContent = `${plan.source} → ${plan.destination}`;
      const space = document.createElement("p");
      space.textContent = `Estimated space: ${plan.estimated_bytes.toLocaleString()} bytes. Available: ${plan.free_bytes.toLocaleString()} bytes.`;
      const rules = document.createElement("p");
      rules.textContent = `Hidden entries ${plan.hidden ? "included" : "excluded"} by default. Directory exclusions: ${plan.excludes.join(", ") || "none"}. Verification: ${plan.verification}.`;
      summary.replaceChildren(paths, rows, space, rules);
      summary.hidden = false;
      const ready = plan.rsync_ready && plan.free_bytes >= plan.estimated_bytes;
      status.textContent = !plan.rsync_ready
        ? "Copy needs rsync. Install rsync from Packages or use ZIP."
        : ready
          ? "Review the destination, selections, and exclusions below."
          : "Choose a destination with more free space or back up fewer files.";
      if (ready)
        reviewedBackup = {
          action: "backup-run",
          spec,
          revision: plan.revision,
        };
      create.disabled = !ready;
    } catch (error) {
      status.textContent = error.message.trim();
    } finally {
      options.disabled = false;
    }
  });
  const create = button("Create backup", async () => {
    if (!reviewedBackup || busy || confirming) return;
    const request = reviewedBackup;
    confirming = true;
    try {
      if (
        await decide(
          "Create the reviewed backup?",
          `Create a new, verified backup under ${request.spec.destination}.`,
          [],
          "Create backup",
        )
      ) {
        if (reviewedBackup !== request) return;
        invalidate();
        status.textContent =
          "Backup started. See Operation output for progress.";
        const success = await preview({ ...request, confirmed: true }, true);
        status.textContent = success
          ? "Backup created and verified. See Operation output for its location."
          : "Backup did not complete. Review the operation output and preview again to retry.";
      }
    } finally {
      confirming = false;
    }
  });
  create.className = "primary";
  create.disabled = true;
  const details = document.createElement("p");
  details.textContent =
    "Expand folders to choose Copy, ZIP or Skip. Subfolders inherit the parent action until you choose a different one.";
  const archiveHelp = document.createElement("p");
  archiveHelp.textContent =
    "ZIP preserves Unix permissions and symlinks when the extraction tool supports them. Use Copy to preserve hard links, ACLs and extended attributes on a compatible drive.";
  const backupSettings = document.createElement("details");
  const optionTitle = document.createElement("summary");
  optionTitle.textContent = "Exclusions and verification";
  backupSettings.append(
    optionTitle,
    backupGroup(
      "backup-settings",
      hiddenLabel,
      ignored,
      extrasLabel,
      verificationLabel,
      archiveHelp,
    ),
  );
  const folderHeader = document.createElement("h3");
  folderHeader.textContent = "Folders to back up";
  options.append(
    backupGroup(
      "backup-fields",
      backupGroup(
        "backup-path",
        sourceLabel,
        backupGroup(
          "backup-actions",
          sourceBrowse,
          button("List source folders", () => loadFolders()),
        ),
      ),
      backupGroup(
        "backup-path",
        destLabel,
        backupGroup("backup-actions", destBrowse),
        driveStatus,
        drives,
      ),
    ),
    backupGroup(
      "backup-selection",
      folderHeader,
      details,
      backupGroup(
        "backup-actions backup-toggles",
        button("Use standard home defaults", () =>
          loadFolders({ preset: true }),
        ),
        topFilesLabel,
        showHiddenLabel,
      ),
      backupGroup("backup-tree", listing),
      backupGroup(
        "backup-add",
        nestedLabel,
        button("Add folder", () => addFolder(nested.value)),
      ),
    ),
    backupSettings,
    backupGroup("backup-actions", review, create),
  );
  options.className = "backup-options";
  options.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target === source) {
      event.preventDefault();
      void loadFolders();
    }
    if (event.key === "Enter" && event.target === nested) {
      event.preventDefault();
      addFolder(nested.value);
    }
  });
  card.append(options, status, summary);
  status.textContent = "Discovering the home folder and external drives…";
  void backupBrowse()
    .then(async (result) => {
      defaults = result;
      const firstOpen = !backupDraft.source;
      source.value = backupDraft.source ||= result.home;
      dest.value = backupDraft.destination ||= result.external[0] || "";
      drives.replaceChildren(
        new Option("Choose a mounted external drive", ""),
        ...result.external.map((path) => new Option(path, path)),
      );
      drives.value = result.external.includes(dest.value) ? dest.value : "";
      drives.hidden = !result.external.length;
      driveStatus.textContent = result.external.length
        ? "Choose a detected writable external drive or browse for another destination."
        : "No mounted writable external drive found. Browse or enter an existing destination folder.";
      for (const name of result.default_excludes) {
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        if (!backupDraft.exclusions.has(name))
          backupDraft.exclusions.set(name, true);
        box.checked = backupDraft.exclusions.get(name);
        box.onchange = () => {
          backupDraft.exclusions.set(name, box.checked);
          invalidate();
        };
        label.append(box, ` ${name}`);
        ignored.append(label);
      }
      options.disabled = false;
      if (firstOpen) {
        backupDraft.children.set(".", result.folders);
        useHomeDefaults(result);
        status.textContent =
          "Standard home folders selected. Expand a folder to review its subfolders.";
      } else {
        await loadFolders();
      }
    })
    .catch((error) => {
      status.textContent = error.message.trim();
    });
}

function renderTerminal(card) {
  const controls = document.createElement("div");
  controls.className = "workflow";
  card.append(controls);
  let shell = terminalShell;
  let lerdInstalled;

  async function refresh() {
    controls.textContent = "Checking login shell and installed shells…";
    try {
      const { default_shell: login, shells } = JSON.parse(
        await previewResult({ action: "terminal-status" }),
      );
      shell ??=
        Object.keys(shells).find((name) => login.split("/").at(-1) === name) ||
        "bash";
      try {
        lerdInstalled = JSON.parse(
          await previewResult({ action: "lerd-availability" }),
        ).installed;
      } catch {
        lerdInstalled = undefined;
      }
      if (card.isConnected) draw(login, shells);
    } catch (error) {
      controls.replaceChildren(
        error.message.trim(),
        button("Retry shell check", refresh),
      );
    }
  }

  function draw(login, shells) {
    controls.replaceChildren();
    const current = document.createElement("p");
    current.textContent = "Account login shell: " + login;
    const picker = document.createElement("select");
    const label = document.createElement("label");
    label.className = "model-path";
    for (const [name, title] of [
      ["bash", "Bash"],
      ["fish", "Fish"],
      ["zsh", "Zsh"],
    ]) {
      picker.add(
        new Option(
          `${title} · ${shells[name].installed ? "installed" : "missing"}`,
          name,
        ),
      );
    }
    picker.value = shell;
    picker.onchange = () => {
      shell = picker.value;
      terminalShell = shell;
      syncRoute("configure");
      draw(login, shells);
    };
    label.append("Shell to configure", picker);
    controls.append(current, label);
    const existing = button("Preview existing configuration", async () => {
      const selectedShell = shell;
      existing.disabled = true;
      try {
        const { path, exists, content } = JSON.parse(
          await previewResult({
            action: "terminal-current",
            shell: selectedShell,
          }),
        );
        if (!existing.isConnected) return;
        const fields = [];
        if (exists && content) {
          const view = document.createElement("textarea");
          view.setAttribute("aria-label", "Existing shell configuration");
          view.readOnly = true;
          view.spellcheck = false;
          view.value = content;
          fields.push(view);
        }
        const message = !exists
          ? "This shell has no startup file yet."
          : content
            ? "Read-only preview. The file can contain private values."
            : "This startup file is empty.";
        await decide(
          "Existing shell configuration",
          path + "\n\n" + message,
          fields,
          "Close",
        );
      } catch (error) {
        if (existing.isConnected)
          await decide(
            "Shell preview unavailable",
            error.message.trim(),
            [],
            "Close",
          );
      } finally {
        existing.disabled = false;
      }
    });
    controls.append(existing);
    const record = shells[shell];
    function describe(text) {
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      controls.append(paragraph);
    }
    function review(title, detail, request) {
      const control = button(title, async () => {
        control.disabled = true;
        try {
          if (
            (await preview(request)) &&
            card.isConnected &&
            (await decide(title, detail, [], "Apply"))
          ) {
            await preview({ ...request, confirmed: true }, true);
            if (card.isConnected) await refresh();
          }
        } finally {
          control.disabled = !catalog.terminal;
        }
      });
      control.disabled = !catalog.terminal;
      controls.append(control);
    }
    if (!catalog.terminal)
      describe(
        "Open the dashboard from an interactive terminal to apply changes.",
      );
    if (!record.installed) {
      review(
        "Review shell installation",
        `Install ${shell} from the configured native package manager?`,
        { action: "terminal-install", shell },
      );
      return;
    }
    if (record.login_allowed && login.split("/").at(-1) !== shell) {
      review(
        "Set as account login shell",
        "This affects new login sessions. Enter account authentication in the launching terminal if prompted.",
        { action: "terminal-default", shell },
      );
    }
    if (!record.login_allowed)
      describe(
        "This shell has no installed entry in /etc/shells for login use.",
      );
    if (record.error) {
      describe(record.error);
      return;
    }
    describe(
      `${record.configured ? "Toolkit settings found" : "Toolkit settings have yet to be applied"} · ${record.path}`,
    );
    describe(
      "Selections control the toolkit block. Existing shell definitions take precedence.",
    );
    const options = { ...record };
    const chosen = new Set(record.commands ?? []);
    const sections = document.createElement("div");
    sections.className = "terminal-sections";
    controls.append(sections);

    function group(title) {
      const field = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = title;
      field.append(legend);
      sections.append(field);
      return field;
    }
    function note(parent, text) {
      const element = document.createElement("p");
      element.className = "terminal-note";
      element.textContent = text;
      parent.append(element);
      return element;
    }
    function toggle(parent, text, checked, update) {
      const row = document.createElement("label");
      row.className = "terminal-toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = checked;
      input.onchange = () => update(input.checked);
      row.append(input, text);
      parent.append(row);
      return row;
    }
    function commands(parent, entries) {
      for (const [id, name] of entries) {
        const row = toggle(parent, name, chosen.has(id), (checked) => {
          if (checked) chosen.add(id);
          else chosen.delete(id);
        });
        if (record.personal_commands?.includes(id)) {
          const existing = document.createElement("small");
          existing.textContent = "Found in your startup file";
          row.append(existing);
        }
      }
    }

    const development = group("Development commands");
    if (lerdInstalled === true)
      note(
        development,
        "Lerd is detected. Choose only the shortcuts you want. Use Sail for projects that need it.",
      );
    else if (lerdInstalled === false)
      note(
        development,
        "Lerd is not installed. These shortcuts use your current shell and project tools.",
      );
    commands(development, [
      ["artisan", "artisan · Laravel CLI"],
      ["vbin", "vbin · Run a project’s vendor/bin tool"],
      ["pint", "pint · Code formatting"],
      ["sail", "sail · Laravel Sail"],
      ["fixer", "fixer · PHP CS Fixer"],
      ["pest", "pest · Pest tests"],
      ["phpunit", "phpunit · PHPUnit tests"],
    ]);
    const ai = group("Terminal AI");
    commands(ai, [
      ["ai-ask", "ai ask · Ask a question"],
      ["ai-suggest", "ai suggest · Suggest a command"],
    ]);
    note(
      ai,
      "The suggestion shortcut is Ctrl+X, then Ctrl+A when available. Review the editable command before pressing Enter.",
    );

    if (shell === "fish" || shell === "zsh") {
      const cleanup = group("Project cleanup");
      commands(cleanup, [
        ["clean-npm", "clean-npm · Reinstall npm dependencies"],
        ["clean-composer", "clean-composer · Reinstall Composer dependencies"],
      ]);
      note(
        cleanup,
        "Running either command deletes that project’s dependency directory and lockfile before reinstalling.",
      );
    }
    const startup = group("Startup preferences");
    toggle(
      startup,
      "Use the toolkit SSH agent when none is selected",
      Boolean(record.use_toolkit_agent),
      (checked) => {
        options.use_toolkit_agent = checked;
      },
    );
    if (shell === "fish")
      toggle(
        startup,
        "Hide the Fish greeting",
        record.fish_greeting === "off",
        (checked) => {
          options.fish_greeting = checked ? "off" : "keep";
        },
      );
    const banner = document.createElement("select");
    for (const [value, title] of [
      ["none", "None"],
      ["fastfetch", "Fastfetch (if installed)"],
      ["neofetch", "Neofetch (if installed)"],
    ])
      banner.add(new Option(title, value));
    banner.value = record.banner;
    const bannerLabel = document.createElement("label");
    bannerLabel.className = "model-path";
    bannerLabel.append("Startup system information", banner);
    startup.append(bannerLabel);

    if (record.legacy_blocks || record.legacy_review) {
      const legacy = document.createElement("details");
      legacy.className = "terminal-legacy";
      const summary = document.createElement("summary");
      summary.textContent = "Legacy configuration";
      legacy.append(summary);
      if (record.legacy_review) note(legacy, record.legacy_review);
      if (record.legacy_blocks) {
        toggle(
          legacy,
          "Replace recognized old toolkit shell blocks",
          false,
          (checked) => {
            options.migrate_legacy = checked;
          },
        );
        note(
          legacy,
          "Choose the commands you want to keep from the old blocks before applying.",
        );
      }
      controls.append(legacy);
    }
    const configure = button("Review shell configuration", async () => {
      const request = {
        action: "terminal-configure",
        shell,
        banner: banner.value,
        fish_greeting: options.fish_greeting,
        commands: [...chosen],
        use_toolkit_agent: options.use_toolkit_agent,
        migrate_legacy: options.migrate_legacy,
        current_sha256: record.sha256,
      };
      configure.disabled = true;
      try {
        if (
          (await preview(request)) &&
          card.isConnected &&
          (await decide(
            "Apply shell configuration",
            `Update the toolkit section in ${record.path} after a private backup?\n\nSelected commands: ${request.commands.map((name) => name.replace(/^ai-/, "ai ")).join(", ") || "None"}.`,
          ))
        ) {
          await preview({ ...request, confirmed: true }, true);
          if (card.isConnected) await refresh();
        }
      } finally {
        configure.disabled = !catalog.terminal;
      }
    });
    configure.disabled = !catalog.terminal;
    controls.append(configure);
  }
  void refresh();
}

function renderLerd(card) {
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const actions = document.createElement("div");
  actions.className = "presets";
  card.append(status, actions);

  async function refresh() {
    actions.replaceChildren();
    status.textContent = "Checking Lerd availability…";
    try {
      const { installed, compatible, blockers } = JSON.parse(
        await previewResult({ action: "lerd-availability" }),
      );
      status.textContent = compatible
        ? installed
          ? "Lerd is installed. Check status to see which services are set up."
          : "Lerd is missing and this host meets the toolkit’s installation checks."
        : `Lerd setup is unavailable on this host. ${blockers.join(" ")}`;
      if (installed)
        actions.append(
          button("Check Lerd status", () => preview({ action: "lerd" })),
        );
      if (!compatible) return;
      const action = installed ? "lerd-repair" : "lerd-install";
      const review = button(
        installed ? "Review Lerd setup or repair" : "Review and install Lerd",
        async () => {
          const panel = activeOutput;
          review.disabled = true;
          try {
            if (!(await preview({ action }, false, panel)) || !card.isConnected)
              return;
            const title = installed ? "Set up or repair Lerd" : "Install Lerd";
            const description = installed
              ? "Run the installed Lerd CLI’s setup command."
              : "Download and run the official Lerd installer over HTTPS.";
            if (
              await decide(
                title,
                `${description} Lerd can configure rootless Podman, local DNS, and user services. Respond to any prerequisite or sudo prompts in the terminal that launched the dashboard.`,
                [],
                title,
              )
            ) {
              await preview({ action, confirmed: true }, true, panel);
              if (card.isConnected) await refresh();
            }
          } finally {
            review.disabled = false;
          }
        },
      );
      if (!catalog.terminal) {
        status.textContent +=
          " Launch the dashboard from an interactive terminal to apply changes.";
        review.disabled = true;
      }
      actions.append(review);
    } catch (error) {
      status.textContent = `Could not check Lerd availability. ${error.message.trim()}`;
      actions.append(button("Retry availability check", refresh));
    }
  }

  void refresh();
}

function renderWebui(card) {
  const controls = document.createElement("div");
  controls.className = "workflow";
  card.append(controls);
  const port = document.createElement("input");
  port.type = "number";
  port.min = 1024;
  port.max = 65535;
  port.value = aiSettings.webuiPort ?? 3000;
  const image = document.createElement("input");
  image.value = catalog.webui_image;
  const allowPull = document.createElement("input");
  allowPull.type = "checkbox";
  const field = (label, input) => {
    const row = document.createElement("label");
    row.className = "model-path";
    row.append(label, input);
    return row;
  };
  const refresh = button("Refresh status", checkStatus);
  async function change(action, title, message) {
    if (await decide(title, message, [], title)) {
      await preview({ action, confirmed: true }, true);
      if (card.isConnected) await checkStatus();
    }
  }
  async function checkStatus() {
    controls.textContent = "Checking rootless Podman and Open WebUI…";
    let state;
    try {
      state = JSON.parse(await previewResult({ action: "webui" }));
    } catch (error) {
      controls.replaceChildren(error.message.trim(), refresh);
      return;
    }
    controls.replaceChildren();
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.textContent = state.recovery_pending
      ? "An interrupted setup needs recovery."
      : state.readiness;
    controls.append(status, refresh);
    if (state.other_podman_containers?.length) {
      const other = document.createElement("p");
      other.textContent =
        "Separate Podman containers: " +
        state.other_podman_containers
          .map(({ name, state }) => `${name} (${state})`)
          .join(", ");
      controls.append(other);
    }
    if (state.recovery_pending) {
      controls.append(
        button("Recover setup", () =>
          change(
            "webui-recover",
            "Recover setup",
            "Resume the recorded operation with its existing image, port and preserved data.",
          ),
        ),
      );
    } else if (state.available && state.installed) {
      controls.append(
        button(state.running ? "Stop Open WebUI" : "Start Open WebUI", () =>
          state.running
            ? change(
                "webui-stop",
                "Stop Open WebUI",
                "Stop the toolkit container and keep its application data.",
              )
            : change(
                "webui-start",
                "Start Open WebUI",
                "Start the toolkit container in the background.",
              ),
        ),
      );
      if (state.running) {
        controls.append(
          button("Test Open WebUI", async () => {
            await preview({ action: "webui-test" });
            if (card.isConnected) await checkStatus();
          }),
        );
        if (state.readiness === "ready") {
          const link = document.createElement("a");
          link.href = `http://127.0.0.1:${state.port}/`;
          link.textContent = "Launch Open WebUI";
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          controls.append(link);
        }
      }
    } else if (state.available) {
      const pinnedImage = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Image settings";
      pinnedImage.append(
        summary,
        field("Official image with SHA-256 digest", image),
      );
      const pull = document.createElement("label");
      pull.append(allowPull, " Download the pinned image if missing");
      const install = button("Review installation", async () => {
        if (!port.reportValidity() || !port.value) return;
        const settings = {
          port: port.valueAsNumber,
          image: image.value.trim(),
          allow_pull: allowPull.checked,
        };
        install.disabled = true;
        try {
          const plan = JSON.parse(
            await previewResult({ action: "webui-plan", ...settings }),
          );
          if (
            await decide(
              "Install Open WebUI",
              `Podman will start Open WebUI at http://127.0.0.1:${settings.port}/ with sign-in enabled.\n\n` +
                `Data volume: automation-open-webui-data\nImage: ${settings.image}\n` +
                (settings.allow_pull
                  ? "Download the image if it is missing."
                  : "Use a locally cached image.") +
                `\n\n${plan.note}`,
              [],
              "Install Open WebUI",
            )
          ) {
            aiSettings.webuiPort = settings.port;
            persist();
            await preview(
              { action: "webui-install", ...settings, confirmed: true },
              true,
            );
            if (card.isConnected) await checkStatus();
          }
        } catch (error) {
          status.textContent = error.message.trim();
        } finally {
          install.disabled = false;
        }
      });
      const actions = document.createElement("div");
      actions.append(install);
      controls.append(
        field("Local web port (1024–65535)", port),
        pinnedImage,
        pull,
        actions,
      );
    }
    const help = document.createElement("p");
    help.textContent =
      "Open WebUI runs independently of the dashboard. Test Open WebUI checks the web app and sign-in protection. Model generation is tested separately in Models & Testing.";
    controls.append(help);
  }
  void checkStatus();
}

function renderChat(card) {
  const controls = document.createElement("div");
  controls.className = "workflow";
  card.append(controls);
  async function checkStatus() {
    controls.textContent = "Checking build and preview status…";
    try {
      chatStatus = JSON.parse(
        await previewResult({ action: "chat", port: aiSettings.chatPort }),
      );
      chatStep ??= chatStatus.built && chatStatus.node_supported ? 2 : 0;
      if (!chatStatus.built && chatStep === 2) chatStep = 1;
      if (card.isConnected) draw();
    } catch (error) {
      controls.replaceChildren(
        error.message,
        button("Check status again", checkStatus),
      );
    }
  }
  void checkStatus();

  function draw() {
    controls.replaceChildren();
    const running = chatStatus.running || chatStatus.background_running;
    const ready =
      chatStatus.node_supported && (chatStatus.npm || chatStatus.built);
    const steps = document.createElement("ol");
    for (const [index, label] of [
      "Requirements",
      "Build",
      "Run preview",
    ].entries()) {
      const row = document.createElement("li");
      const state =
        index === chatStep
          ? chatFailed && index === 1
            ? "Failed"
            : "Current"
          : (index === 0 && ready) || (index === 1 && chatStatus.built)
            ? "Completed"
            : "Pending";
      row.textContent = `${label} · ${state}`;
      steps.append(row);
    }
    const port = document.createElement("input");
    port.type = "number";
    port.min = 1024;
    port.max = 65535;
    port.value = aiSettings.chatPort ?? 3001;
    port.disabled = running;
    port.onchange = () => {
      aiSettings.chatPort = Number(port.value);
      persist();
    };
    const field = document.createElement("label");
    field.className = "model-path";
    field.append("Loopback port (1024–65535, excluding 8080)", port);
    controls.append(steps, field);
    const previous = button("Previous", () => {
      chatStep--;
      draw();
    });
    previous.disabled = chatStep === 0 || busy;
    const next = button("Next", () => {
      chatStep++;
      draw();
    });
    next.disabled = busy || (chatStep === 0 ? !ready : !chatStatus.built);
    if (chatStep === 0 && !ready)
      controls.append("Install Node.js 22+ and npm, then refresh the page.");
    if (chatStep === 1 && running)
      controls.append("Stop ChatGPT Lite before rebuilding.");
    if (chatStep === 1) {
      const build = button(
        chatStatus.built ? "Rebuild client" : "Build client",
        async () => {
          if (
            await decide(
              "Build ChatGPT Lite",
              "Install locked Node dependencies and build the local client?",
            )
          )
            await preview(
              {
                action: "chat-build",
                port: aiSettings.chatPort,
                confirmed: true,
              },
              true,
            );
        },
      );
      build.disabled =
        busy ||
        !catalog.terminal ||
        !chatStatus.node_supported ||
        !chatStatus.npm ||
        Boolean(running);
      controls.append(build);
    }
    if (chatStep === 2 && chatStatus.built) {
      const info = document.createElement("p");
      info.setAttribute("role", "status");
      info.textContent = chatStatus.background_running
        ? chatStatus.background_ready
          ? "ChatGPT Lite is ready in the background. You can close the dashboard."
          : `Background service: ${chatStatus.background_state}. The web app has yet to respond.`
        : chatStatus.running
          ? chatStatus.preview_ready
            ? "ChatGPT Lite is ready in this dashboard session."
            : "The preview process is running. The web app has yet to respond."
          : "Build ready. Choose a dashboard-session preview or a background service.";
      controls.append(info);
      if (!running && chatStatus.port_in_use)
        info.textContent =
          "Build ready. The selected port is in use. Choose another port to start the preview.";
      if (chatStatus.preview_ready || chatStatus.background_ready) {
        const link = document.createElement("a");
        link.href =
          "http://127.0.0.1:" +
          (chatStatus.background_port ?? chatStatus.preview_port);
        link.textContent = "Open ChatGPT Lite at " + link.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        controls.append(link);
      }
      const launch = button(
        chatStatus.running ? "Stop preview" : "Start preview",
        async () => {
          launch.disabled = true;
          info.textContent = chatStatus.running
            ? "Stopping preview…"
            : "Starting preview and waiting for the local site…";
          try {
            const response = await send("/execute", {
              action: chatStatus.running
                ? "chat-preview-stop"
                : "chat-preview-start",
              port: aiSettings.chatPort ?? 3001,
              confirmed: true,
            });
            if (!response.ok) throw new Error(await response.text());
            if (card.isConnected) await checkStatus();
          } catch (error) {
            info.textContent = error.message.trim();
            launch.disabled = false;
          }
        },
      );
      launch.disabled = !chatStatus.running && chatStatus.port_in_use;
      if (!chatStatus.background_running) controls.append(launch);
      if (!chatStatus.running && chatStatus.background_available) {
        const stopping = chatStatus.background_running;
        const title = stopping
          ? "Stop background service"
          : "Start in background";
        const background = button(title, async () => {
          if (
            !(await decide(
              title,
              stopping
                ? "Stop the ChatGPT Lite service for this checkout."
                : "Run ChatGPT Lite on loopback as a systemd user service. It stays up when the dashboard closes during your login session.",
              [],
              title,
            ))
          )
            return;
          await preview(
            {
              action: stopping
                ? "chat-background-stop"
                : "chat-background-start",
              port: aiSettings.chatPort ?? 3001,
              confirmed: true,
            },
            true,
          );
          if (card.isConnected) await checkStatus();
        });
        background.disabled = !stopping && chatStatus.port_in_use;
        controls.append(background);
      }
      if (!chatStatus.background_available && chatStatus.background_detail)
        controls.append(document.createTextNode(chatStatus.background_detail));
      const remove = button("Remove build output", async () => {
        if (
          await decide(
            "Remove build output",
            "Remove the generated build directory?",
          )
        )
          await preview({ action: "chat-remove", confirmed: true }, true);
      });
      remove.disabled = busy || !catalog.terminal || Boolean(running);
      controls.append(remove);
    }
    controls.append(previous);
    if (chatStep < 2) controls.append(next);
    controls.append(
      button(running ? "Test ChatGPT Lite" : "Refresh status", checkStatus),
    );
  }
}

async function start() {
  const response = await fetch("/catalog");
  if (!response.ok) throw new Error("Could not load the setup catalog.");
  catalog = await response.json();
  category = catalog.packages[0]?.category ?? null;
  byId("home-host").textContent =
    `${catalog.distro} · ${catalog.manager ?? "No native package manager"} · ${catalog.architecture}`;
  byId("home-links").replaceChildren(
    button("Check available updates", () => preview({ action: "updates" })),
    button("View package inventory", () => preview({ action: "inventory" })),
  );
  byId("open-ai").onclick = () => showPage("ai");
  try {
    const saved = JSON.parse(localStorage.getItem("linux-setup-draft") || "{}");
    selected = new Set(
      (saved.selected ?? []).filter(
        (name) =>
          packagePattern.test(name) &&
          !catalog.separate_packages.includes(name),
      ),
    );
    for (const id of selected) {
      if (!catalog.packages.some((row) => row.id === id))
        catalog.packages.push({ id, category: "Custom packages" });
    }
    byId("stage-projects").checked = Boolean(saved.projects);
    byId("stage-zed").checked = Boolean(saved.zed);
    aiSettings = saved.ai ?? {};
    remoteSettings = saved.remote ?? {};
    if (Number.isFinite(saved.aiSavedAt)) aiSavedAt = saved.aiSavedAt;
  } catch {}
  byId("checklist").onclick = refreshChecklist;
  byId("open-checklist").onclick = () => {
    byId("checklist-panel").showModal();
    void refreshChecklist();
  };
  byId("review-all").onclick = reviewAll;
  byId("advanced-retry").onclick = advanced;
  byId("advanced-preview-restore").onclick = previewAdvancedRestore;
  for (const control of document.querySelectorAll("[data-advanced-mode]")) {
    control.onclick = () => {
      advancedMode = control.dataset.advancedMode;
      showPage("advanced");
    };
  }
  byId("apply-all").onclick = async () => {
    const steps = batch.filter((step) => !completed.has(step.action));
    if (
      steps.length &&
      (await decide(
        "Apply reviewed changes",
        steps.map((step) => advancedActionLabels[step.action]).join("\n"),
        [],
        "Apply changes",
      ))
    )
      await preview({ action: "batch", steps, confirmed: true }, true);
  };
  for (const id of ["stage-projects", "stage-zed"]) {
    byId(id).onchange = () => {
      allReviewed = false;
      advancedReviewMessage = "";
      renderSelection();
    };
  }
  byId("host").textContent =
    `${catalog.distro} · ${catalog.manager ?? "No native package manager"}`;
  byId("aur-option").hidden = !catalog.arch;
  byId("find-helper").hidden = !catalog.arch || catalog.aur_helpers.length > 0;
  byId("find-helper").addEventListener("click", () => {
    byId("custom-name").value = "yay";
    void preview({ action: "aur-helpers" });
  });
  byId("aur-option").textContent = catalog.aur_helpers.length
    ? `AUR · ${catalog.aur_helpers.join(", ")}`
    : "AUR unavailable · install a supported helper from a configured repository";
  byId("custom-package").addEventListener("submit", (event) => {
    event.preventDefault();
    const query = byId("custom-name").value.trim();
    if (packagePattern.test(query)) void preview({ action: "search", query });
  });
  byId("add-custom").addEventListener("click", () => {
    const id = byId("custom-name").value.trim();
    if (catalog.separate_packages.includes(id)) {
      void decide(
        "Configure " + id,
        id === "lerd" ? "Use Configure → Lerd." : "Use Configure → Terminal.",
        [],
        "Close",
      );
      return;
    }
    if (!packagePattern.test(id)) {
      byId("custom-name").reportValidity();
      return;
    }
    let row = catalog.packages.find((item) => item.id === id);
    if (!row) {
      row = { id, category: "Custom packages" };
      catalog.packages.push(row);
    }
    selected.add(id);
    category = row.category;
    byId("search").value = "";
    renderCategories();
    renderPackages();
  });
  byId("save-plan").addEventListener("click", () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(reviewed.plan, null, 2) + "\n"], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "automation-package-plan.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  byId("package-back").onclick = () => {
    packageReview = false;
    renderPackages();
    byId("search").focus();
  };
  byId("execute").addEventListener("click", async () => {
    const plan = reviewed;
    const available = plan.plan.packages.filter(
      (row) => row.status === "available",
    );
    const existing = plan.plan.packages.filter(
      (row) => row.status === "installed",
    );
    const reinstall = document.createElement("input");
    reinstall.type = "checkbox";
    const option = document.createElement("label");
    option.append(reinstall, " Reinstall selected packages");
    const review = plan.plan.packages
      .map((row) => `${row.actual || row.name} · ${row.status} · ${row.source}`)
      .join("\n");
    if (
      !(await decide(
        "Step 3 of 3 · Confirm installation",
        review,
        existing.length ? [option] : [],
      ))
    )
      return;
    const steps = [];
    if (available.length)
      steps.push({
        action: "packages",
        packages: available.map((row) => row.name),
        fingerprint: plan.plan.install_fingerprint,
        flatpak: plan.flatpak,
        helper: plan.helper,
      });
    if (reinstall.checked) {
      const request = {
        action: "repair",
        packages: existing.map((row) => row.name),
      };
      try {
        const output = await previewResult(request);
        const line = output
          .split("\n")
          .find((row) =>
            row.startsWith('{"schema": 1, "type": "automation-plan"'),
          );
        const repairPlan = JSON.parse(line);
        const rows = repairPlan.packages.filter(
          (row) => row.status === "available",
        );
        if (!rows.length) {
          await decide("Reinstall unavailable", output.replace(line, ""));
          return;
        }
        if (
          !(await decide(
            "Confirm verified reinstalls",
            output.replace(line, ""),
          ))
        )
          return;
        steps.push({
          ...request,
          packages: rows.map((row) => row.name),
          fingerprint: repairPlan.install_fingerprint,
        });
      } catch (error) {
        await decide("Could not review reinstalls", error.message);
        return;
      }
    }
    if (steps.length === 1)
      void preview({ ...steps[0], confirmed: true }, true);
    if (steps.length > 1)
      void preview({ action: "batch", steps, confirmed: true }, true);
  });
  for (const control of document.querySelectorAll("nav button")) {
    control.addEventListener("click", () => showPage(control.dataset.page));
  }
  for (const control of document.querySelectorAll("[data-profile]")) {
    control.addEventListener("click", () => {
      selected = new Set(catalog.profiles[control.dataset.profile]);
      category = null;
      byId("search").value = "";
      renderCategories();
      renderPackages();
    });
  }
  byId("clear").addEventListener("click", () => {
    selected.clear();
    renderPackages();
  });
  byId("search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderPackages, 180);
  });
  byId("select-visible").addEventListener("click", () => {
    const rows = visiblePackages();
    const clear = rows.every((row) => selected.has(row.id));
    for (const row of rows) {
      if (clear) selected.delete(row.id);
      else selected.add(row.id);
    }
    renderPackages();
  });
  byId("preview").addEventListener("click", () =>
    preview({
      action: "packages",
      packages: [...selected],
    }),
  );
  byId("copy-install").addEventListener("click", async () => {
    const field = byId("command-text");
    field.focus();
    field.select();
    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(field.value);
      } catch {
        /* The selected text can still be copied manually. */
      }
    }
  });
  renderCategories();
  renderPackages();
  window.addEventListener("popstate", restoreRoute);
  window.addEventListener("hashchange", restoreRoute);
  restoreRoute();
  void loadSystem();
}

start().catch((error) => {
  byId("results").hidden = false;
  byId("status").textContent = error.message;
});

async function previewResult(payload) {
  const response = await send("/preview", payload);
  if (!response.ok) throw new Error(await response.text());
  const result = await response.json();
  if (result.status) throw new Error(result.output);
  return result.output;
}

function updateAdvancedReview() {
  const stagedAi = aiSettings.stage && aiSettings.location !== "ssh";
  const rows = [
    [
      "Toolkit settings",
      configDraft ? "Staged" : "No edits staged",
      "#advanced/settings",
    ],
    [
      "Project Sites",
      byId("stage-projects").checked ? "Included" : "Optional",
      "#configure/configuration",
    ],
    [
      "Packages",
      selected.size ? `${selected.size} selected` : "No selection",
      "#install",
    ],
    [
      "Zed settings",
      byId("stage-zed").checked ? "Defaults included" : "Optional",
      "#configure/zed",
    ],
    [
      "Local AI",
      stagedAi ? "Staged" : "No local setup staged",
      "#ai/ai-setup/service",
    ],
  ];
  byId("advanced-queue").replaceChildren(
    ...rows.map(([name, status, url]) => {
      const row = document.createElement("li");
      const link = document.createElement("a");
      const state = document.createElement("span");
      link.href = url;
      link.textContent = name;
      state.textContent = status;
      row.append(link, state);
      return row;
    }),
  );
  const pending =
    allReviewed && batch.some((step) => !completed.has(step.action));
  byId("apply-all").disabled = busy || !pending || !catalog?.terminal;
  byId("review-all").disabled = busy;
  byId("advanced-plan-status").textContent = busy
    ? "Working on the setup plan…"
    : !catalog?.terminal
      ? "Launch the dashboard from an interactive terminal to apply changes."
      : pending
        ? "Review accepted. Apply the remaining steps when ready."
        : advancedReviewMessage ||
          "Review the plan whenever you change a selection.";
}

async function previewAdvancedRestore() {
  if (busy) return;
  const status = byId("advanced-restore-status");
  const control = byId("advanced-preview-restore");
  control.disabled = true;
  try {
    const backup = byId("advanced-backup-id").value.trim();
    if (!/^config-[a-f0-9]{32}\.json$/.test(backup))
      throw new Error("Enter the full configuration backup ID.");
    const payload = { action: "config-restore", backup };
    const output = await previewResult(payload);
    status.textContent = "Backup validated.";
    if (!catalog.terminal) {
      await decide(
        "Restore preview",
        "Launch from an interactive terminal to apply.",
        [advancedDetail("Configuration changes", output)],
        "Close",
      );
      return;
    }
    if (
      await decide(
        "Restore toolkit settings?",
        "Restore the settings recorded in this backup.",
        [advancedDetail("Configuration changes", output)],
        "Restore settings",
      )
    ) {
      if (await preview({ ...payload, confirmed: true }, true)) {
        configDraft = null;
        byId("advanced-fields").replaceChildren();
        status.textContent = "Toolkit settings restored.";
      } else status.textContent = "Restore failed. See the operation output.";
    }
  } catch (error) {
    status.textContent = error.message;
  } finally {
    control.disabled = false;
  }
}

function advancedDetail(title, output) {
  const detail = document.createElement("details");
  const heading = document.createElement("summary");
  const text = document.createElement("pre");
  heading.textContent = title;
  text.textContent = output.trim();
  detail.append(heading, text);
  return detail;
}

async function advanced() {
  if (advancedLoading) return;
  advancedLoading = true;
  const status = byId("advanced-status");
  byId("advanced-retry").hidden = true;
  status.textContent = "Loading toolkit settings…";
  try {
    const editor = JSON.parse(await previewResult({ action: "advanced" }));
    const labels = {
      AUTOMATION_PROJECT_SITES_DIR: "Project Sites folder",
      AUTOMATION_LERD: "Offer Lerd for development services",
      AUTOMATION_PREFER_FLATPAK: "Prefer Flatpak",
      AUTOMATION_PREFER_SHELLY: "Prefer Shelly for native packages",
      AUTOMATION_AUTO_SEARCH: "Suggest package name alternatives",
      AUTOMATION_ENABLE_AUR: "Allow exact AUR selections in the CLI",
    };
    const fields = new Map();
    function changed() {
      configDraft = null;
      allReviewed = false;
      advancedReviewMessage = "";
      status.textContent = "Preview your edits before saving or staging them.";
      updateAdvancedReview();
    }
    const rows = Object.entries(editor.fields)
      .filter(
        ([key]) =>
          catalog.arch ||
          !["AUTOMATION_PREFER_SHELLY", "AUTOMATION_ENABLE_AUR"].includes(key),
      )
      .map(([key, description]) => {
        const label = document.createElement("label");
        const help = document.createElement("small");
        label.className = "model-path advanced-setting";
        const input = key.endsWith("_DIR")
          ? document.createElement("input")
          : document.createElement("select");
        if (input.tagName === "SELECT") {
          for (const [name, value] of [
            ["Use default", ""],
            ["Enabled", "true"],
            ["Disabled", "false"],
          ])
            input.add(new Option(name, value));
        } else
          input.placeholder =
            editor.effective[key] || "/home/you/Documents/Project-Sites";
        input.value = Object.hasOwn(configDraft ?? {}, key)
          ? (configDraft[key] ?? "")
          : (editor.local[key] ?? "");
        input.oninput = changed;
        fields.set(key, input);
        const title = document.createElement("strong");
        title.textContent = labels[key] ?? key;
        help.textContent = `${description} Default: ${editor.defaults[key] || "automatic"}. Effective: ${editor.effective[key] || "automatic"}.`;
        label.append(title, input, help);
        return label;
      });
    const raw = document.createElement("textarea");
    const rawLabel = document.createElement("label");
    rawLabel.className = "model-path";
    rawLabel.append("JSON overrides", raw);
    raw.placeholder = '{"AUTOMATION_LERD":"false"}';
    raw.oninput = changed;
    const manual = document.createElement("details");
    const manualSummary = document.createElement("summary");
    manualSummary.textContent = "Edit settings as JSON";
    manual.append(manualSummary, rawLabel);
    const showPreview = async (save) => {
      if (busy) return;
      try {
        const values = Object.fromEntries(
          [...fields]
            .filter(([key, input]) => input.value !== (editor.local[key] ?? ""))
            .map(([key, input]) => [key, input.value || null]),
        );
        if (raw.value.trim()) {
          const overrides = JSON.parse(raw.value);
          if (
            !overrides ||
            Array.isArray(overrides) ||
            typeof overrides !== "object"
          )
            throw new Error(
              "JSON overrides must be an object with setting names.",
            );
          Object.assign(values, overrides);
        }
        if (!Object.keys(values).length) {
          status.textContent = "No changes to preview.";
          return;
        }
        const review = await previewResult({ action: "config-edit", values });
        const detail = advancedDetail("Configuration changes", review);
        detail.open = true;
        if (
          !(await decide(
            save ? "Save toolkit settings?" : "Stage toolkit settings?",
            save
              ? "Save these overrides and create a private backup."
              : "Include these overrides in Review & apply.",
            [detail],
            save ? "Save settings" : "Stage settings",
          ))
        )
          return;
        allReviewed = false;
        advancedReviewMessage = "";
        if (save) {
          if (
            await preview(
              { action: "config-edit", values, confirmed: true },
              true,
            )
          ) {
            configDraft = null;
            advancedLoading = false;
            await advanced();
            status.textContent =
              "Toolkit settings saved. The operation output has the backup ID.";
          } else
            status.textContent =
              "Settings could not be saved. See the operation output.";
        } else {
          configDraft = values;
          status.textContent = "Settings staged for Review & apply.";
          updateAdvancedReview();
        }
      } catch (error) {
        status.textContent = error.message;
      }
    };
    const save = button("Preview and save", () => showPreview(true));
    save.disabled = !catalog.terminal;
    byId("advanced-fields").replaceChildren(
      ...rows,
      manual,
      backupGroup(
        "advanced-actions",
        button("Preview and stage", () => showPreview(false)),
        save,
      ),
    );
    status.textContent = configDraft
      ? "Settings staged for Review & apply."
      : catalog.terminal
        ? ""
        : "Launch the dashboard from an interactive terminal to save changes.";
  } catch (error) {
    status.textContent = error.message;
    byId("advanced-retry").hidden = false;
  } finally {
    advancedLoading = false;
  }
}

async function reviewAll() {
  if (busy) return;
  allReviewed = false;
  advancedReviewMessage = "";
  completed.clear();
  batch = [];
  batchSelection = [...selected].join(",");
  const steps = [];
  if (configDraft) steps.push({ action: "config-edit", values: configDraft });
  if (byId("stage-projects").checked)
    steps.push({ action: "configuration", php_sample: projectPhpSample });
  if (selected.size)
    steps.push({
      action: "packages",
      packages: [...selected],
    });
  if (byId("stage-zed").checked) steps.push({ action: "zed" });
  if (aiSettings.stage && aiSettings.location !== "ssh") {
    const owned = engineStatus.some((item) => item.owned_service);
    const dataRoot = localModelRoot();
    steps.push({
      action: "ai-plan",
      data_root: dataRoot,
      ...(aiSettings.model_mode === "download"
        ? modelDownload
        : { model: aiSettings.model }),
      port: aiSettings.port,
      gpu_layers: aiSettings.gpu_layers,
      backend: aiSettings.backend || (owned ? "auto" : "cpu"),
      install_mode: owned ? aiSettings.install_mode || "update" : "install",
      reconfigure: Boolean(owned && (dataRoot || aiSettings.port)),
    });
  }
  if (!steps.length) {
    advancedReviewMessage = "Select packages or setup steps before reviewing.";
    updateAdvancedReview();
    return;
  }
  const outputs = [];
  busy = true;
  renderSelection();
  try {
    for (const step of steps) {
      setupStep(step.action, "checking");
      let output = await previewResult(step);
      if (
        step.action === "configuration" &&
        configDraft &&
        Object.hasOwn(configDraft, "AUTOMATION_PROJECT_SITES_DIR")
      ) {
        const target = configDraft.AUTOMATION_PROJECT_SITES_DIR;
        output +=
          "\n" +
          (await previewResult({
            action: "project-path",
            target,
            php_sample: step.php_sample,
          }));
      }
      if (step.action === "packages" || step.action === "repair") {
        const line = output
          .split("\n")
          .find((row) =>
            row.startsWith('{"schema": 1, "type": "automation-plan"'),
          );
        const plan = JSON.parse(line);
        const packages = plan.packages.filter(
          (row) => row.status === "available",
        );
        if (packages.length)
          batch.push({
            action: step.action,
            packages: packages.map((row) => row.name),
            fingerprint: plan.install_fingerprint,
          });
        output = output.replace(line, "");
        setupStep(step.action, packages.length ? "pending" : "skipped");
      } else {
        if (step.action === "ai-plan") {
          if (!(step.model || step.model_url))
            throw new Error(
              "Choose an existing GGUF or a verified download in Local AI.",
            );
          const plan = JSON.parse(output);
          if (!plan.managed_install_supported || plan.storage.error)
            throw new Error(output);
          batch.push({ ...step, action: "ai-install" });
        } else batch.push(step);
        setupStep(
          step.action === "ai-plan" ? "ai-install" : step.action,
          "pending",
        );
      }
      outputs.push(advancedDetail(advancedActionLabels[step.action], output));
    }
    const accepted = await decide(
      "Review all changes",
      batch.length
        ? `${batch.length} step${batch.length === 1 ? "" : "s"} ready. Expand each section for details.`
        : "The selected packages require no installable changes. Expand Packages for details.",
      outputs,
      batch.length ? "Accept review" : "Close",
    );
    allReviewed = Boolean(batch.length) && accepted;
    if (!batch.length)
      advancedReviewMessage = "There are no installable changes in this plan.";
  } catch (error) {
    await decide("Review stopped", error.message);
  } finally {
    busy = false;
    renderSelection();
  }
}

async function refreshChecklist() {
  const status = byId("checklist-status");
  status.textContent = "Checking…";
  byId("checklist").disabled = true;
  const item = (name, state, detail) => {
    const row = document.createElement("li");
    const label = document.createElement("strong");
    const badge = document.createElement("span");
    label.textContent = name;
    badge.textContent = state;
    row.dataset.state = state;
    row.append(label, badge);
    if (detail) {
      const description = document.createElement("small");
      description.textContent = detail;
      row.append(description);
    }
    return row;
  };
  try {
    const observed = JSON.parse(await previewResult({ action: "checklist" }));
    const manual = JSON.parse(
      await previewResult({ action: "checklist-tasks" }),
    );
    byId("observed-checks").replaceChildren(
      ...observed.checks.map((row) =>
        item(
          row.id === "projects" ? "Project Sites" : "Toolkit configuration",
          row.status,
          row.target ?? row.reason,
        ),
      ),
      ...Object.entries(observed.dependencies).map(([name, found]) =>
        item(name, found ? "detected" : "not detected"),
      ),
    );
    byId("manual-checks").replaceChildren(
      ...manual.tasks.map((row) => {
        const entry = item(
          row.title,
          row.status === "done" ? "completed" : row.status,
          row.category,
        );
        const completed = document.createElement("input");
        completed.type = "checkbox";
        completed.checked = row.status === "done";
        completed.setAttribute("aria-label", `Mark ${row.title} as completed`);
        completed.addEventListener("change", async () => {
          completed.disabled = true;
          status.textContent = "Saving…";
          try {
            const response = await send("/execute", {
              action: "checklist-mark",
              task: row.id,
              state: completed.checked ? "done" : "pending",
              confirmed: true,
            });
            if (!response.ok) throw new Error(await response.text());
            const events = (await response.text())
              .trim()
              .split("\n")
              .map((line) => JSON.parse(line));
            if (events.at(-1)?.status !== 0)
              throw new Error(
                events
                  .map((event) => event.output ?? "")
                  .join("")
                  .trim() || "Could not save checklist progress.",
              );
            row.status = completed.checked ? "done" : "pending";
            entry.dataset.state = completed.checked ? "completed" : "pending";
            entry.querySelector("span").textContent = entry.dataset.state;
            status.textContent = "Checklist progress saved.";
          } catch (error) {
            completed.checked = row.status === "done";
            status.textContent = error.message;
          } finally {
            completed.disabled = false;
          }
        });
        entry.querySelector("strong").prepend(completed, " ");
        return entry;
      }),
    );
    status.textContent = "";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    byId("checklist").disabled = false;
  }
}

async function showZed() {
  const panel = activeOutput;
  try {
    const current = await previewResult({ action: "zed-current" });
    const view = document.createElement("textarea");
    view.setAttribute("aria-label", "Current Zed settings");
    view.readOnly = true;
    view.value = current;
    await decide(
      "Current Zed settings",
      "Read-only contents of your Zed settings.json.",
      [view],
      "Close",
    );
  } catch (error) {
    panel.hidden = false;
    outputPart(panel, "status").textContent = error.message;
  }
}

async function testZedConnections(connections) {
  const results = [];
  for (const endpoint of connections) {
    const location = `${endpoint.provider} · ${endpoint.host}:${endpoint.port}`;
    if (endpoint.provider !== "llama.cpp" || !endpoint.can_test) {
      results.push(
        `${location}: test directly in Zed. The toolkit tests llama.cpp over a loopback HTTP endpoint.`,
      );
      continue;
    }
    try {
      const response = await previewResult({
        action: "ai-verify",
        host: endpoint.host,
        port: endpoint.port,
      });
      const { models } = JSON.parse(response);
      if (
        !models.length ||
        (endpoint.model && !models.includes(endpoint.model))
      )
        results.push(
          `${location}: requested model ${endpoint.model ?? "(auto-discover)"} is unavailable. Server lists ${models.join(", ") || "no models"}.`,
        );
    } catch (error) {
      results.push(`${location}: ${error.message.trim()}`);
    }
  }
  return results;
}

async function editZed() {
  const panel = activeOutput;
  const mode = document.createElement("select");
  mode.add(new Option("Merge missing values", "apply"));
  mode.add(new Option("Override supplied values", "override"));
  mode.add(new Option("Replace settings file", "replace"));
  mode.setAttribute("aria-label", "Zed settings mode");
  mode.value = zedDraft.mode;
  const profile = document.createElement("textarea");
  profile.placeholder = '{"vim_mode": false, "telemetry": {"metrics": false}}';
  profile.setAttribute("aria-label", "Zed JSON or JSONC settings");
  profile.value = zedDraft.profile;
  profile.oninput = () => {
    zedDraft.profile = profile.value;
  };
  mode.onchange = () => {
    zedDraft.mode = mode.value;
  };
  if (
    !(await decide(
      "Edit Zed settings",
      "Paste a JSON or JSONC object. Override preserves omitted keys. Replace removes omitted keys and creates a backup.",
      [mode, profile],
    ))
  )
    return;
  const payload = {
    action: "zed-edit",
    mode: mode.value,
    profile: profile.value,
  };
  try {
    const result = await previewResult(payload);
    const change = JSON.parse(result);
    const lines = ["add", "change", "remove"].flatMap((kind) =>
      change[kind].map((key) => {
        const pair = change.compare?.[key];
        return `${kind}: ${key}${pair ? ` · ${pair[0] ?? "unset"} → ${pair[1] ?? "unset"}` : ""}`;
      }),
    );
    const format = (items) =>
      items
        .map(
          ({ provider, host, port, model }) =>
            `${provider} · ${host}:${port} · ${model ?? "auto-discover"}`,
        )
        .join("\n") || "No custom API endpoints";
    const connectionChanged =
      JSON.stringify(change.connections_before) !==
        JSON.stringify(change.connections_after) ||
      lines.some((line) =>
        /: (language_models|agent(?:\.default_model)?)(?:\.|$)/.test(line),
      );
    const endpoints = connectionChanged ? change.connections_after : [];
    panel.hidden = false;
    outputPart(panel, "status").textContent = endpoints.length
      ? "Testing proposed local Zed connections…"
      : "Zed settings validated.";
    const warnings = await testZedConnections(endpoints);
    const review = [
      lines.join("\n") || "No changes.",
      `Current AI: ${format(change.connections_before)}`,
      `Proposed AI: ${format(change.connections_after)}`,
      ...(warnings.length
        ? ["Connection checks:", ...warnings]
        : endpoints.some((item) => item.provider === "llama.cpp")
          ? ["llama.cpp endpoint and model inventory verified."]
          : []),
    ].join("\n\n");
    outputPart(panel, "status").textContent = warnings.length
      ? "Zed preview completed with connection warnings."
      : "Zed preview complete.";
    if (
      (await decide(
        "Review Zed settings changes",
        review,
        [],
        !catalog.terminal
          ? "Close"
          : warnings.length
            ? "Apply anyway"
            : "Apply and back up",
      )) &&
      catalog.terminal &&
      lines.length
    )
      await preview(
        { ...payload, version: change.version, confirmed: true },
        true,
        panel,
      );
  } catch (error) {
    await decide("Zed settings could not be reviewed", error.message);
  }
}
