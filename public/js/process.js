/**
 * Rota única /process → sempre POST /api/process-and-publish
 * subtle + CDN + Supabase em um único request.
 */
(function () {
  const form = document.getElementById("processForm");
  const fileInput = document.getElementById("file");
  const drop = document.getElementById("drop");
  const hint = document.getElementById("hint");
  const previewVideo = document.getElementById("previewVideo");
  const previewImg = document.getElementById("previewImg");
  const errorEl = document.getElementById("error");
  const submitBtn = document.getElementById("submit");
  const resultBox = document.getElementById("result");
  const resultUrl = document.getElementById("resultUrl");
  const resultId = document.getElementById("resultId");
  const steps = document.getElementById("steps");

  function setStep(name, state) {
    if (!steps) return;
    steps.querySelectorAll("li").forEach((li) => {
      if (li.getAttribute("data-step") === name) {
        li.classList.remove("is-active", "is-done", "is-fail");
        if (state) li.classList.add("is-" + state);
      }
    });
  }

  function resetSteps() {
    steps?.querySelectorAll("li").forEach((li) => {
      li.classList.remove("is-active", "is-done", "is-fail");
    });
  }

  function showError(msg) {
    if (!errorEl) return;
    errorEl.hidden = !msg;
    errorEl.textContent = msg || "";
  }

  drop?.addEventListener("click", () => fileInput?.click());
  ["dragenter", "dragover"].forEach((ev) => {
    drop?.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("is-drag");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    drop?.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("is-drag");
    });
  });
  drop?.addEventListener("drop", (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f && fileInput) {
      const dt = new DataTransfer();
      dt.items.add(f);
      fileInput.files = dt.files;
      onFile(f);
    }
  });

  fileInput?.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (f) onFile(f);
  });

  function onFile(f) {
    showError("");
    resultBox?.classList.remove("is-visible");
    if (hint) hint.hidden = true;
    if (previewVideo) {
      previewVideo.hidden = true;
      previewVideo.removeAttribute("src");
    }
    if (previewImg) {
      previewImg.hidden = true;
      previewImg.removeAttribute("src");
    }
    const url = URL.createObjectURL(f);
    if (f.type.startsWith("video/")) {
      if (previewVideo) {
        previewVideo.hidden = false;
        previewVideo.src = url;
      }
    } else if (f.type.startsWith("image/")) {
      if (previewImg) {
        previewImg.hidden = false;
        previewImg.src = url;
      }
    } else if (hint) {
      hint.hidden = false;
      hint.textContent = f.name + " (" + Math.round(f.size / 1024) + " KB)";
    }
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = fileInput?.files?.[0];
    if (!f) {
      showError("Escolha um arquivo.");
      return;
    }

    showError("");
    resetSteps();
    resultBox?.classList.remove("is-visible");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Processando…";
    }

    setStep("upload", "active");

    const fd = new FormData();
    fd.append("file", f);
    fd.append("subtle", "true");
    fd.append("remove_metadata", "true");
    fd.append("register_supabase", "true");
    fd.append("cdn_prefix", "uploads");
    fd.append("caption", document.getElementById("caption")?.value || "");
    // micro trim default to help republicação
    fd.append("trim_start", "0.3");
    fd.append("trim_end", "0.3");
    fd.append("crf", "20");
    fd.append("preset", "medium");

    setStep("upload", "done");
    setStep("process", "active");
    setStep("cdn", "active");
    setStep("db", "active");

    try {
      const res = await fetch("/api/process-and-publish", {
        method: "POST",
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || "Falha HTTP " + res.status);
      }

      setStep("process", "done");
      setStep("cdn", "done");
      if (data.media?.id) setStep("db", "done");
      else if (data.supabase_error) {
        setStep("db", "fail");
        showError("CDN ok, mas Supabase: " + data.supabase_error);
      } else setStep("db", "done");

      const url = data.public_url || data.media?.public_url || "";
      if (resultBox) resultBox.classList.add("is-visible");
      if (resultUrl) {
        resultUrl.innerHTML = url
          ? 'URL: <a href="' + url + '" target="_blank" rel="noopener">' + url + "</a>"
          : "Sem URL pública";
      }
      if (resultId) {
        resultId.textContent = data.media?.id
          ? "vd_media id: " + data.media.id
          : data.remote
            ? "remote: " + data.remote
            : "";
      }
    } catch (err) {
      setStep("process", "fail");
      setStep("cdn", "fail");
      setStep("db", "fail");
      showError(err.message || String(err));
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Processar e publicar";
      }
    }
  });
})();
