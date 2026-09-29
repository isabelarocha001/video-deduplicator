/**
 * Lux · video-deduplicator frontend
 * Feed real via /api/media · publish via /api/process-and-publish ou /api/upload-cdn
 */
(function () {
  const THEME_KEY = "lux-theme";
  const API = "/api";

  function $(id) {
    return document.getElementById(id);
  }

  function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#000000" : "#ffffff";
    localStorage.setItem(THEME_KEY, theme);
  }
  applyTheme(getPreferredTheme());
  $("themeToggle")?.addEventListener("click", () => {
    applyTheme(
      document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"
    );
  });

  // Profile defaults
  if ($("profileUsername")) $("profileUsername").textContent = "lux";
  if ($("profileDisplayName")) $("profileDisplayName").textContent = "Lux · Video Deduplicator";
  if ($("profileBio")) {
    $("profileBio").innerHTML =
      "Publique foto/vídeo · processa, sobe CDN e registra no Supabase<br /><span class=\"bio-link\">API /api/process-and-publish</span>";
  }

  // Show create controls
  ["btnOpenUpload"].forEach((id) => {
    const el = $(id);
    if (el) el.hidden = false;
  });

  // ── Feed ──────────────────────────────────────────────────────────────
  async function loadFeed() {
    const grid = $("postsGrid");
    const empty = $("emptyState");
    const stat = $("statPosts");
    if (!grid) return;

    grid.innerHTML = '<p class="empty-state">Carregando…</p>';
    try {
      const res = await fetch(`${API}/media?limit=48`);
      const data = await res.json();
      if (!data.ok) {
        grid.innerHTML = "";
        if (empty) {
          empty.hidden = false;
          empty.textContent = data.error || "Não foi possível carregar o feed.";
        }
        if (stat) stat.textContent = "0";
        return;
      }
      const items = data.items || [];
      if (stat) stat.textContent = String(items.length);
      if (!items.length) {
        grid.innerHTML = "";
        if (empty) {
          empty.hidden = false;
          empty.textContent = "Nenhuma publicação ainda. Seja o primeiro!";
        }
        return;
      }
      if (empty) empty.hidden = true;
      grid.innerHTML = items
        .map((item) => {
          const url = item.public_url || item.thumb_url || "";
          const isVideo =
            item.media_type === "video" ||
            (item.mime_type || "").startsWith("video/") ||
            /\.mp4($|\?)/i.test(url);
          const media = isVideo
            ? `<video src="${esc(url)}" muted playsinline preload="metadata"></video>`
            : `<img src="${esc(url)}" alt="" loading="lazy" />`;
          const caption = item.caption ? esc(item.caption) : "";
          return `<article class="grid-item" data-id="${esc(item.id || "")}">
            ${media}
            <div class="grid-meta">
              <span>${isVideo ? "▶ vídeo" : "♪"}</span>
              <span>${caption}</span>
            </div>
          </article>`;
        })
        .join("");
    } catch (err) {
      grid.innerHTML = "";
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Erro de rede ao carregar feed.";
      }
      console.error(err);
    }
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  // ── Upload modal ──────────────────────────────────────────────────────
  const modal = $("uploadModal");
  const fileInput = $("uploadFile");
  const hint = $("uploadHint");
  const preview = $("uploadPreview");
  const errEl = $("uploadError");
  const statusEl = $("uploadStatus");

  function openUpload() {
    if (!modal) return;
    modal.hidden = false;
    if (errEl) {
      errEl.hidden = true;
      errEl.textContent = "";
    }
    if (statusEl) {
      statusEl.hidden = true;
      statusEl.textContent = "";
    }
  }
  function closeUpload() {
    if (modal) modal.hidden = true;
    if (fileInput) fileInput.value = "";
    if (preview) {
      preview.hidden = true;
      preview.removeAttribute("src");
    }
    if (hint) hint.hidden = false;
  }

  $("btnOpenUpload")?.addEventListener("click", openUpload);
  $("navCreate")?.addEventListener("click", openUpload);
  $("uploadCancel")?.addEventListener("click", closeUpload);
  $("uploadDrop")?.addEventListener("click", () => fileInput?.click());

  fileInput?.addEventListener("change", () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;
    if (hint) hint.hidden = true;
    if (preview) {
      if (f.type.startsWith("image/")) {
        preview.hidden = false;
        preview.src = URL.createObjectURL(f);
      } else {
        preview.hidden = true;
        if (hint) {
          hint.hidden = false;
          hint.textContent = f.name + " (" + Math.round(f.size / 1024) + " KB)";
        }
      }
    }
  });

  $("uploadForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = fileInput && fileInput.files && fileInput.files[0];
    if (!f) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = "Escolha um arquivo.";
      }
      return;
    }

    const caption = ($("uploadCaption") && $("uploadCaption").value) || "";
    const subtle = $("optSubtle") ? $("optSubtle").checked : true;
    const register = $("optRegister") ? $("optRegister").checked : true;
    const useCdn = $("optCdn") ? $("optCdn").checked : true;

    if (!useCdn) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = "CDN é obrigatório para publicar no feed.";
      }
      return;
    }

    const fd = new FormData();
    fd.append("file", f);
    fd.append("caption", caption);
    fd.append("register_supabase", register ? "true" : "false");
    fd.append("cdn_prefix", "uploads");
    fd.append("subtle", subtle ? "true" : "false");
    fd.append("remove_metadata", "true");

    const submit = $("uploadSubmit");
    if (submit) submit.disabled = true;
    if (errEl) errEl.hidden = true;
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = subtle
        ? "Processando + enviando CDN…"
        : "Enviando para CDN…";
    }

    const endpoint = subtle ? `${API}/process-and-publish` : `${API}/upload-cdn`;

    try {
      const res = await fetch(endpoint, { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      if (statusEl) {
        statusEl.textContent =
          "Publicado: " + (data.public_url || data.media?.public_url || "ok");
      }
      closeUpload();
      await loadFeed();
    } catch (err) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = err.message || String(err);
      }
      if (statusEl) statusEl.hidden = true;
    } finally {
      if (submit) submit.disabled = false;
    }
  });

  // Auth modal kept visual-only for now
  $("btnAuth")?.addEventListener("click", () => {
    const m = $("authModal");
    if (m) m.hidden = !m.hidden;
  });
  $("authSwitch")?.addEventListener("click", () => {
    const field = $("authUsernameField");
    if (field) field.hidden = !field.hidden;
    const title = $("authTitle");
    if (title) title.textContent = field && !field.hidden ? "Criar conta" : "Entrar";
  });

  // Health badge in console
  fetch(`${API}/health`)
    .then((r) => r.json())
    .then((h) => console.info("[lux] health", h))
    .catch(() => {});

  loadFeed();
})();
