document.getElementById("reel-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const status = document.getElementById("status");
  const download = document.getElementById("download");
  const downloadSrt = document.getElementById("download-srt");
  status.textContent = "uploading...";
  download.hidden = true;
  downloadSrt.hidden = true;
  const response = await fetch("/api/jobs", {
    method: "POST",
    body: new FormData(form),
  });
  if (!response.ok) {
    status.textContent = "submit failed: " + (await response.text());
    return;
  }
  const payload = await response.json();
  const jobId = payload.job_id;
  status.textContent = "queued: " + jobId;
  const poll = setInterval(async () => {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) {
      status.textContent = "poll failed: " + res.status;
      clearInterval(poll);
      return;
    }
    const job = await res.json();
    status.textContent = `${job.status}: ${job.message}`;
    if (job.status === "done") {
      clearInterval(poll);
      download.href = `/api/jobs/${jobId}/download`;
      download.hidden = false;
      downloadSrt.href = `/api/jobs/${jobId}/download?format=srt`;
      downloadSrt.hidden = false;
    } else if (job.status === "error") {
      clearInterval(poll);
    }
  }, 1000);
});
