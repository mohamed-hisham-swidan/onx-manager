"use strict";

(function initLauncher() {
  const api = window.onxDesktop;
  if (!api) return;

  const backendDot = document.getElementById("backend-dot");
  const backendStatusText = document.getElementById("backend-status-text");
  const localSplash = document.getElementById("local-splash");
  const localError = document.getElementById("local-error");
  const backendLogs = document.getElementById("backend-logs");
  const btnConnectLocal = document.getElementById("btn-connect-local");
  const btnRestartLocal = document.getElementById("btn-restart-local");
  const btnToggleLogs = document.getElementById("btn-toggle-logs");

  const remoteForm = document.getElementById("remote-form");
  const remoteNameInput = document.getElementById("remote-name");
  const remoteUrlInput = document.getElementById("remote-url");
  const remoteStatus = document.getElementById("remote-status");
  const btnTestRemote = document.getElementById("btn-test-remote");
  const btnConnectRemote = document.getElementById("btn-connect-remote");
  const savedRemotesWrap = document.getElementById("saved-remotes-wrap");
  const savedRemotesList = document.getElementById("saved-remotes");

  function renderBackendStatus(backend) {
    if (!backend) return;
    backendDot.className = `dot ${backend.status}`;
    if (backend.status === "running") {
      backendStatusText.textContent = `Running on 127.0.0.1:${backend.port}`;
      if (localSplash) {
        localSplash.style.display = "none";
      }
    } else if (backend.status === "starting") {
      backendStatusText.textContent = "Starting local backend...";
      if (localSplash) {
        localSplash.style.display = "block";
        localSplash.textContent =
          "Launching local ONX panel service and preparing your dashboard...";
      }
    } else if (backend.status === "error") {
      backendStatusText.textContent = "Backend failed to start";
      if (localSplash) {
        localSplash.style.display = "none";
      }
    } else {
      backendStatusText.textContent = "Stopped";
      if (localSplash) {
        localSplash.style.display = "none";
      }
    }

    if (backend.error) {
      localError.style.display = "block";
      localError.textContent = backend.error;
    } else {
      localError.style.display = "none";
      localError.textContent = "";
    }
  }

  function showRemoteMessage(text, kind) {
    remoteStatus.style.display = "block";
    remoteStatus.className = `alert ${kind || ""}`;
    remoteStatus.textContent = text;
  }

  function renderSavedRemotes(remotes) {
    if (!Array.isArray(remotes) || remotes.length === 0) {
      savedRemotesWrap.style.display = "none";
      savedRemotesList.innerHTML = "";
      return;
    }
    savedRemotesWrap.style.display = "block";
    savedRemotesList.innerHTML = "";
    for (const item of remotes) {
      const row = document.createElement("div");
      row.className = "saved-item";

      const meta = document.createElement("div");
      meta.className = "saved-meta";
      const nameEl = document.createElement("div");
      nameEl.className = "saved-name";
      nameEl.textContent = item.name;
      const urlEl = document.createElement("div");
      urlEl.className = "saved-url";
      urlEl.textContent = item.url;
      meta.appendChild(nameEl);
      meta.appendChild(urlEl);

      const actions = document.createElement("div");
      actions.className = "row";
      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.textContent = "Connect";
      openBtn.addEventListener("click", async () => {
        showRemoteMessage(`Connecting to ${item.url}...`);
        try {
          await api.connectRemote({ id: item.id, name: item.name, url: item.url });
        } catch (err) {
          showRemoteMessage(err.message || "Failed to connect", "error");
        }
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "Remove";
      delBtn.addEventListener("click", async () => {
        const updated = await api.deleteRemote(item.id);
        renderSavedRemotes(updated.remotes);
      });

      actions.appendChild(openBtn);
      actions.appendChild(delBtn);
      row.appendChild(meta);
      row.appendChild(actions);
      savedRemotesList.appendChild(row);
    }
  }

  btnConnectLocal.addEventListener("click", async () => {
    btnConnectLocal.disabled = true;
    try {
      await api.connectLocal();
    } catch (err) {
      localError.style.display = "block";
      localError.textContent = err.message || "Failed to start local backend.";
    } finally {
      btnConnectLocal.disabled = false;
    }
  });

  btnRestartLocal.addEventListener("click", async () => {
    btnRestartLocal.disabled = true;
    try {
      await api.restartBackend();
    } catch (err) {
      localError.style.display = "block";
      localError.textContent = err.message || "Failed to restart local backend.";
    } finally {
      btnRestartLocal.disabled = false;
    }
  });

  btnToggleLogs.addEventListener("click", async () => {
    const isOpen = backendLogs.classList.toggle("open");
    if (isOpen) {
      const lines = await api.getBackendLogs();
      backendLogs.textContent = lines.length > 0 ? lines.join("\n") : "(no backend output captured yet)";
    }
  });

  btnTestRemote.addEventListener("click", async () => {
    const url = remoteUrlInput.value.trim();
    if (!url) {
      showRemoteMessage("Enter a remote panel URL first.", "error");
      return;
    }
    btnTestRemote.disabled = true;
    showRemoteMessage("Checking remote ONX panel...");
    try {
      const res = await api.probeRemote(url);
      if (res.ok) {
        const authLabel =
          res.authMode === "local_zero_login"
            ? "Passwordless Local"
            : res.authMode === "jwt"
              ? "JWT Login"
              : null;
        const meta = [
          res.version ? `v${res.version}` : null,
          res.deploymentProfile ? `${res.deploymentProfile.toUpperCase()} profile` : null,
          authLabel,
        ]
          .filter(Boolean)
          .join(" · ");
        showRemoteMessage(`Reachable (${meta || "ONX Panel OK"})`, "ok");
      } else {
        showRemoteMessage(res.error || "Remote panel did not respond as ONX Manager.", "error");
      }
    } catch (err) {
      showRemoteMessage(err.message || "Probe failed.", "error");
    } finally {
      btnTestRemote.disabled = false;
    }
  });

  remoteForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = remoteUrlInput.value.trim();
    const name = remoteNameInput.value.trim();
    if (!url) return;
    btnConnectRemote.disabled = true;
    showRemoteMessage(`Connecting to ${url}...`);
    try {
      await api.connectRemote({ name, url });
    } catch (err) {
      showRemoteMessage(err.message || "Failed to connect to remote panel.", "error");
    } finally {
      btnConnectRemote.disabled = false;
    }
  });

  api.onStatusChange((payload) => {
    if (payload && payload.backend) {
      renderBackendStatus(payload.backend);
    }
  });

  api.getState().then((state) => {
    renderBackendStatus(state.backend);
    renderSavedRemotes(state.store?.remotes || []);
  });
})();
