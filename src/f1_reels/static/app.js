const speedInput = document.querySelector('input[name="speed"]');
const speedValue = document.getElementById("speed-value");
if (speedInput && speedValue) {
  const updateSpeed = () => {
    speedValue.textContent = `${speedInput.value}x`;
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
  const downloadSrt = document.getElementById("download-srt");
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
  downloadSrt.hidden = true;
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
      downloadSrt.href = `/api/jobs/${jobId}/download?format=srt`;
      downloadSrt.hidden = false;
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
