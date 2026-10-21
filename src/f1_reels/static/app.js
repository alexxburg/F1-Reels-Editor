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
document.getElementById("reel-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const status = document.getElementById("status");
  const download = document.getElementById("download");
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
  download.hidden = true;
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
  const jobId = payload.job_id;
  setStatus("queued: " + jobId, "queued");
  const poll = setInterval(async () => {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) {
      setStatus("poll failed: " + res.status, "error");
      clearInterval(poll);
      if (submitButton) {
        submitButton.disabled = false;
      }
      return;
    }
    const job = await res.json();
    setStatus(`${job.status}: ${job.message}`, job.status);
    if (job.status === "done") {
      clearInterval(poll);
      download.href = `/api/jobs/${jobId}/download`;
      download.hidden = false;
      if (submitButton) {
        submitButton.disabled = false;
      }
    } else if (job.status === "error") {
      clearInterval(poll);
      if (submitButton) {
        submitButton.disabled = false;
      }
    }
  }, 1000);
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
    return d.toLocaleString();
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

  async function loadReels() {
    const list = document.getElementById("reel-list");
    if (!list) {
      return;
    }
    let reels = [];
    try {
      const res = await fetch("/api/reels");
      if (res.ok) {
        const payload = await res.json();
        if (Array.isArray(payload.reels)) {
          reels = payload.reels;
        }
      }
    } catch (_) {
      reels = [];
    }
    list.querySelectorAll(".reel-row, .reel-empty").forEach((node) => {
      node.remove();
    });
    if (!reels.length) {
      const empty = document.createElement("div");
      empty.className = "reel-empty";
      empty.textContent = "No reels yet — render one first.";
      list.appendChild(empty);
      return;
    }
    reels.forEach((reel) => {
      const row = document.createElement("div");
      row.className = "reel-row";
      row.setAttribute("role", "row");
      const name = document.createElement("span");
      name.className = "reel-name";
      name.textContent = reel.name;
      const mp4 = document.createElement("a");
      mp4.href = `/api/jobs/${reel.job_id}/download`;
      mp4.textContent = "mp4";
      name.appendChild(document.createTextNode(" "));
      name.appendChild(mp4);
      const size = document.createElement("span");
      size.className = "reel-size";
      size.textContent = formatSize(reel.size);
      const modified = document.createElement("span");
      modified.className = "reel-modified";
      modified.textContent = formatDate(reel.modified);
      modified.title = reel.modified || "";
      row.appendChild(name);
      row.appendChild(size);
      row.appendChild(modified);
      list.appendChild(row);
    });
  }

  const refresh = document.getElementById("explorer-refresh");
  if (refresh) {
    refresh.addEventListener("click", loadReels);
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
