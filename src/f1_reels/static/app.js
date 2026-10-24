const speedInput = document.querySelector('input[name="speed"]');
const speedValue = document.getElementById("speed-value");
if (speedInput && speedValue) {
  const updateSpeed = () => {
    speedValue.textContent = `${speedInput.value}x`;
    const min = parseFloat(speedInput.min);
    const max = parseFloat(speedInput.max);
    const pct = ((parseFloat(speedInput.value) - min) / (max - min)) * 100;
    speedInput.style.setProperty("--fill", `${pct}%`);
  };
  speedInput.addEventListener("input", updateSpeed);
  updateSpeed();
}
const randomSeedButton = document.getElementById("random-seed");
if (randomSeedButton) {
  randomSeedButton.addEventListener("click", () => {
    const seedInput = document.querySelector('input[name="seed"]');
    if (!seedInput) {
      return;
    }
    const buf = new Uint32Array(1);
    crypto.getRandomValues(buf);
    seedInput.value = String(buf[0] % 2147483648);
  });
}
const scriptInput = document.getElementById("script_lines");
const footerText = document.getElementById("footer-text");
const footerCopy = document.getElementById("footer-copy");
const footerRegen = document.getElementById("footer-regenerate");
const footerHint = document.getElementById("footer-hint");
const footerDefaultHint = "Caption for social uploads. Regenerates 3s after you stop editing.";
if (scriptInput && footerText && footerCopy && footerRegen) {
  let footerTimer = null;
  let footerBusy = false;
  const scheduleFooter = () => {
    if (footerTimer !== null) {
      clearTimeout(footerTimer);
    }
    footerTimer = setTimeout(generateFooter, 3000);
  };
  async function generateFooter() {
    const script = scriptInput.value;
    if (!script.trim()) {
      return;
    }
    if (footerBusy) {
      scheduleFooter();
      return;
    }
    footerBusy = true;
    if (footerHint) {
      footerHint.textContent = "Generating caption...";
    }
    try {
      const body = new FormData();
      body.append("script_lines", script);
      const res = await fetch("/api/footer", { method: "POST", body });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const payload = await res.json();
      footerText.value = payload.footer || "";
      if (footerHint) {
        footerHint.textContent = footerDefaultHint;
      }
    } catch (err) {
      if (footerHint) {
        footerHint.textContent = `Caption failed: ${(err && err.message) || err}`;
      }
    } finally {
      footerBusy = false;
    }
  }
  scriptInput.addEventListener("input", scheduleFooter);
  footerRegen.addEventListener("click", generateFooter);
  footerCopy.addEventListener("click", async () => {
    const text = footerText.value;
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      footerText.select();
      document.execCommand("copy");
    }
    if (footerHint) {
      footerHint.textContent = "Copied to clipboard.";
    }
  });
}
document.getElementById("reel-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const status = document.getElementById("status");
  const submitButton = form.querySelector('button[type="submit"]');
  const setStatus = (text, state) => {
    status.textContent = text;
    if (state) {
      status.dataset.state = state;
    } else {
      delete status.dataset.state;
    }
  };
  setStatus("uploading...", "uploading");
  if (submitButton) {
    submitButton.disabled = true;
  }
  const response = await fetch("/api/jobs", {
    method: "POST",
    body: new FormData(form),
  });
  if (!response.ok) {
    setStatus("submit failed: " + (await response.text()), "error");
    if (submitButton) {
      submitButton.disabled = false;
    }
    return;
  }
  const payload = await response.json();
  // Handed to the background queue: reset the generator for the next reel.
  // Progress and downloads live in the Windows Explorer window.
  form.reset();
  setStatus("queued: " + payload.job_id, "queued");
  if (submitButton) {
    submitButton.disabled = false;
  }
});

// XP desktop: clock, start menu, window toggles, explorer. Existing
// submit/poll/download logic above is untouched.
(function () {
  function formatSize(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) {
      return "0 B";
    }
    if (n < 1024) {
      return `${n} B`;
    }
    const units = ["KB", "MB", "GB"];
    let value = n / 1024;
    let unit = units[0];
    for (let i = 0; i < units.length; i++) {
      unit = units[i];
      if (value < 1024 || i === units.length - 1) {
        break;
      }
      value /= 1024;
    }
    return `${value.toFixed(1)} ${unit}`;
  }

  function formatDate(iso) {
    if (!iso) {
      return "";
    }
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      return String(iso);
    }
    // Short Explorer-style stamp (no seconds) so the Modified column fits.
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  const clock = document.getElementById("tray-clock");
  function updateClock() {
    if (!clock) {
      return;
    }
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    clock.textContent = `${hh}:${mm}`;
  }
  updateClock();
  setInterval(updateClock, 10000);

  const startBtn = document.getElementById("start-btn");
  const startMenu = document.getElementById("start-menu");
  function closeMenu() {
    if (!startMenu) {
      return;
    }
    startMenu.hidden = true;
    if (startBtn) {
      startBtn.setAttribute("aria-expanded", "false");
    }
  }
  async function updateMenuCount() {
    const badge = document.getElementById("menu-reel-count");
    if (!badge) {
      return;
    }
    try {
      const res = await fetch("/api/reels");
      if (!res.ok) {
        return;
      }
      const payload = await res.json();
      const n = Array.isArray(payload.reels) ? payload.reels.length : 0;
      badge.textContent = `(${n})`;
    } catch (_) {
      /* keep stale count on network failure */
    }
  }
  if (startBtn && startMenu) {
    startBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = startMenu.hidden;
      startMenu.hidden = !willOpen;
      startBtn.setAttribute("aria-expanded", String(willOpen));
      if (willOpen) {
        updateMenuCount();
      }
    });
    document.addEventListener("click", (event) => {
      if (
        !startMenu.hidden &&
        !startMenu.contains(event.target) &&
        event.target !== startBtn
      ) {
        closeMenu();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeMenu();
      }
    });
  }

  const taskButtons = Array.from(
    document.querySelectorAll('#task-buttons [data-win]')
  );
  function syncPressed() {
    taskButtons.forEach((btn) => {
      const win = document.getElementById(btn.getAttribute("data-win"));
      btn.setAttribute("aria-pressed", String(!!win && !win.hidden));
    });
  }

  const filmIcon =
    '<img src="/static/video-icon.png" width="16" height="16" alt="">';

  function appendDeleteButton(container, reel) {
    const del = document.createElement("button");
    del.type = "button";
    del.className = "btn reel-delete";
    del.textContent = "Delete";
    del.setAttribute("aria-label", `Delete ${reel.name}`);
    del.addEventListener("click", async () => {
      if (!window.confirm(`Delete reel "${reel.name}"?`)) {
        return;
      }
      del.disabled = true;
      const res = await fetch(`/api/jobs/${reel.job_id}`, { method: "DELETE" });
      if (!res.ok) {
        del.disabled = false;
        return;
      }
      loadReels();
    });
    container.appendChild(document.createTextNode(" "));
    container.appendChild(del);
  }

  function renderActiveRow(list, reel) {
    const row = document.createElement("div");
    row.className = "reel-row reel-active";
    row.setAttribute("role", "row");
    const main = document.createElement("div");
    main.className = "reel-active-main";
    const icon = document.createElement("span");
    icon.className = "reel-file-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = filmIcon;
    main.appendChild(icon);
    const label = document.createElement("span");
    label.className = "reel-title";
    label.textContent = reel.name;
    label.title = reel.name;
    main.appendChild(label);
    const status = document.createElement("span");
    status.className = "reel-active-status";
    if (reel.status === "queued") {
      status.textContent = `Queued #${reel.queue_position}`;
    } else if (reel.status === "running") {
      const pct = Number(reel.progress);
      status.textContent = `Rendering… ${Number.isFinite(pct) ? pct : 0}%`;
    } else {
      status.textContent = reel.message || reel.status || "error";
    }
    main.appendChild(status);
    const actions = document.createElement("span");
    actions.className = "reel-actions";
    appendDeleteButton(actions, reel);
    main.appendChild(actions);
    row.appendChild(main);
    if (reel.status === "running") {
      const pct = Math.max(0, Math.min(100, Number(reel.progress) || 0));
      const track = document.createElement("div");
      track.className = "reel-progress";
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(pct));
      const fill = document.createElement("span");
      fill.style.width = `${pct}%`;
      track.appendChild(fill);
      row.appendChild(track);
    }
    list.appendChild(row);
  }

  // Last good list data: a failed poll must leave the displayed rows
  // stale-but-visible, never flash an empty list.
  let lastReels = null;
  let lastActive = null;

  async function loadReels() {
    const list = document.getElementById("reel-list");
    if (!list) {
      return;
    }
    let reels = null;
    try {
      const res = await fetch("/api/reels");
      if (res.ok) {
        const payload = await res.json();
        if (Array.isArray(payload.reels)) {
          reels = payload.reels;
        }
      }
    } catch (_) {
      reels = null;
    }
    let active = null;
    try {
      const res = await fetch("/api/jobs");
      if (res.ok) {
        const payload = await res.json();
        if (Array.isArray(payload.jobs)) {
          active = payload.jobs;
        }
      }
    } catch (_) {
      active = null;
    }
    if (reels !== null) {
      lastReels = reels;
    }
    if (active !== null) {
      lastActive = active;
    }
    if (lastReels === null && lastActive === null) {
      // Nothing ever loaded: fall through to the empty state below.
      reels = [];
      active = [];
    } else {
      reels = lastReels || [];
      active = lastActive || [];
    }
    list.querySelectorAll(".reel-row, .reel-empty").forEach((node) => {
      node.remove();
    });
    active.forEach((reel) => renderActiveRow(list, reel));
    if (!reels.length && !active.length) {
      const empty = document.createElement("div");
      empty.className = "reel-empty";
      empty.setAttribute("role", "row");
      empty.innerHTML =
        '<svg class="reel-empty-art" width="48" height="48" viewBox="0 0 40 40" aria-hidden="true"><ellipse cx="20" cy="36" rx="14" ry="2.2" fill="#000" opacity="0.3"/><rect x="4" y="14" width="32" height="20" fill="#33333d" stroke="#000" stroke-width="1"/><rect x="4" y="14" width="32" height="2.5" fill="#5a5a66"/><rect x="4" y="6" width="32" height="9" fill="#46464f" stroke="#000" stroke-width="1" transform="rotate(-6 20 10)"/><g transform="rotate(-6 20 10)"><rect x="6" y="7" width="6" height="7" fill="#fff"/><rect x="14" y="7" width="6" height="7" fill="#fff"/><rect x="22" y="7" width="6" height="7" fill="#fff"/></g><circle cx="12" cy="24" r="4" fill="#d9d9d9" stroke="#555" stroke-width="1"/><circle cx="10.8" cy="22.8" r="1.1" fill="#fff"/><circle cx="12" cy="24" r="1.5" fill="#333"/><circle cx="28" cy="24" r="4" fill="#d9d9d9" stroke="#555" stroke-width="1"/><circle cx="26.8" cy="22.8" r="1.1" fill="#fff"/><circle cx="28" cy="24" r="1.5" fill="#333"/></svg><p class="reel-empty-title">No reels yet</p><p class="reel-empty-hint">Render one from Reel Generator.</p>';
      list.appendChild(empty);
      return;
    }
    reels.forEach((reel) => {
      const row = document.createElement("div");
      row.className = "reel-row";
      row.setAttribute("role", "row");
      const name = document.createElement("span");
      name.className = "reel-name";
      const icon = document.createElement("span");
      icon.className = "reel-file-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.innerHTML = filmIcon;
      name.appendChild(icon);
      const label = document.createElement("span");
      label.className = "reel-title";
      label.textContent = reel.name;
      label.title = reel.name;
      name.appendChild(label);
      const size = document.createElement("span");
      size.className = "reel-size";
      size.textContent = formatSize(reel.size);
      const modified = document.createElement("span");
      modified.className = "reel-modified";
      modified.textContent = formatDate(reel.modified);
      modified.title = reel.modified || "";
      const actions = document.createElement("span");
      actions.className = "reel-actions";
      const dl = document.createElement("a");
      dl.className = "btn reel-download";
      dl.href = `/api/jobs/${reel.job_id}/download`;
      dl.textContent = "Download reel";
      actions.appendChild(dl);
      appendDeleteButton(actions, reel);
      row.appendChild(name);
      row.appendChild(size);
      row.appendChild(modified);
      row.appendChild(actions);
      list.appendChild(row);
    });
  }

  const refresh = document.getElementById("explorer-refresh");
  if (refresh) {
    refresh.addEventListener("click", loadReels);
  }

  // Live queue polling: refresh while the Explorer is visible, stop when
  // any other window shows (or on log-off).
  let explorerPoll = null;
  function stopExplorerPoll() {
    if (explorerPoll !== null) {
      clearInterval(explorerPoll);
      explorerPoll = null;
    }
  }
  function startExplorerPoll() {
    stopExplorerPoll();
    explorerPoll = setInterval(loadReels, 2000);
  }

  // Single visible app window at full size: show the target, hide the other.
  function showWindow(id) {
    const target = document.getElementById(id);
    if (!target) {
      return;
    }
    ["win-generator", "win-explorer"].forEach((wid) => {
      const w = document.getElementById(wid);
      if (!w) {
        return;
      }
      w.hidden = wid !== id;
    });
    syncPressed();
    if (id === "win-explorer") {
      loadReels();
      startExplorerPoll();
    } else {
      stopExplorerPoll();
    }
    closeMenu();
  }

  // Log Off maps to show-desktop since there is no session to end.
  const logoffBtn = document.getElementById("logoff-btn");
  if (logoffBtn) {
    logoffBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      ["win-generator", "win-explorer"].forEach((wid) => {
        const w = document.getElementById(wid);
        if (w) {
          w.hidden = true;
        }
      });
      syncPressed();
      stopExplorerPoll();
      closeMenu();
    });
  }

  document.querySelectorAll("[data-win]").forEach((btn) => {
    // Desktop icons open on single click — simpler than XP double-click.
    btn.addEventListener("click", () => {
      showWindow(btn.getAttribute("data-win"));
    });
  });
  syncPressed();
})();
