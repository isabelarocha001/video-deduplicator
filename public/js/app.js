/**
 * Lux social app — theme, auth, upload, feed (Supabase)
 */
(function () {
  const THEME_KEY = "lux-theme";
  const cfg = window.LUX_SUPABASE;
  if (!cfg || !window.supabase) {
    console.error("Supabase config or SDK missing");
    return;
  }

  const sb = window.supabase.createClient(cfg.url, cfg.anonKey);
  let session = null;
  let profile = null;
  let authMode = "login"; // login | signup

  // ---------- Theme ----------
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
  document.getElementById("themeToggle")?.addEventListener("click", () => {
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });

  // ---------- DOM helpers ----------
  const $ = (id) => document.getElementById(id);
  function show(el, on = true) {
    if (!el) return;
    el.hidden = !on;
  }
  function setError(id, msg) {
    const el = $(id);
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      show(el, true);
    } else {
      show(el, false);
    }
  }

  // ---------- Auth UI ----------
  function openAuth(mode) {
    authMode = mode || "login";
    $("authTitle").textContent = authMode === "login" ? "Entrar" : "Criar conta";
    $("authSubmit").textContent = authMode === "login" ? "Entrar" : "Cadastrar";
    $("authSwitch").textContent =
      authMode === "login" ? "Criar conta" : "Já tenho conta";
    show($("authUsernameField"), authMode === "signup");
    setError("authError", null);
    show($("authModal"), true);
  }
  function closeAuth() {
    show($("authModal"), false);
  }

  $("btnAuth")?.addEventListener("click", () => {
    if (session) {
      // toggle logout visibility already on profile
      $("btnLogout")?.focus();
      return;
    }
    openAuth("login");
  });
  $("authSwitch")?.addEventListener("click", () => {
    openAuth(authMode === "login" ? "signup" : "login");
  });
  $("authModal")?.addEventListener("click", (e) => {
    if (e.target === $("authModal")) closeAuth();
  });

  $("authForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    setError("authError", null);
    const email = $("authEmail").value.trim();
    const password = $("authPassword").value;
    const username = $("authUsername")?.value.trim();
    $("authSubmit").disabled = true;
    try {
      if (authMode === "signup") {
        const { data, error } = await sb.auth.signUp({
          email,
          password,
          options: { data: { username: username || email.split("@")[0], display_name: username || email.split("@")[0] } },
        });
        if (error) throw error;
        if (!data.session) {
          setError("authError", "Conta criada. Verifique o e-mail se a confirmação estiver ativa.");
        }
      } else {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) throw error;
      }
      closeAuth();
    } catch (err) {
      setError("authError", err.message || "Falha na autenticação");
    } finally {
      $("authSubmit").disabled = false;
    }
  });

  $("btnLogout")?.addEventListener("click", async () => {
    await sb.auth.signOut();
  });

  // ---------- Session / profile ----------
  async function loadProfile(userId) {
    const { data } = await sb.from("vd_profiles").select("*").eq("id", userId).maybeSingle();
    profile = data;
    return data;
  }

  async function refreshUserUI() {
    const { data: { session: s } } = await sb.auth.getSession();
    session = s;
    const logged = !!session?.user;

    show($("btnOpenUpload"), logged);
    show($("btnLogout"), logged);
    show($("btnFollow"), false);

    if (logged) {
      await loadProfile(session.user.id);
      const name = profile?.username || session.user.email?.split("@")[0] || "você";
      $("profileUsername").textContent = name;
      $("profileDisplayName").textContent = profile?.display_name || name;
      $("profileBio").textContent = profile?.bio || "Sua conta está conectada. Publique uma foto!";
      if (profile?.avatar_url) {
        $("avatarImg").src = profile.avatar_url;
        $("navAvatar").src = profile.avatar_url;
      }
      $("btnAuth").title = name;
    } else {
      profile = null;
      $("profileUsername").textContent = "visitante";
      $("profileDisplayName").textContent = "Lux";
      $("profileBio").textContent = "Entre para publicar e sincronizar com o Supabase.";
    }
    await loadPosts();
  }

  sb.auth.onAuthStateChange(() => {
    refreshUserUI();
  });

  // ---------- Posts ----------
  function mediaTypeFromFile(file) {
    if (file.type.startsWith("video/")) return "video";
    if (file.type.startsWith("image/")) return "image";
    return "unknown";
  }

  function publicUrl(path) {
    const { data } = sb.storage.from("vd-media").getPublicUrl(path);
    return data?.publicUrl || "";
  }

  async function loadPosts() {
    const grid = $("postsGrid");
    const empty = $("emptyState");
    grid.innerHTML = "";

    let q = sb
      .from("vd_media")
      .select("id, public_url, thumb_url, caption, media_type, status, created_at, user_id")
      .in("status", ["ready", "duplicate", "processing", "pending"])
      .order("created_at", { ascending: false })
      .limit(60);

    // Profile tab: own posts if logged in
    const activeTab = document.querySelector(".tab.is-active")?.dataset?.tab || "posts";
    if (activeTab === "posts" && session?.user) {
      q = q.eq("user_id", session.user.id);
    }

    const { data, error } = await q;
    if (error) {
      console.error(error);
      empty.textContent = "Erro ao carregar: " + error.message;
      show(empty, true);
      return;
    }

    const rows = data || [];
    $("statPosts").textContent = String(rows.length);
    show(empty, rows.length === 0);
    if (!rows.length) return;

    grid.innerHTML = rows
      .map((row) => {
        const url = row.public_url || row.thumb_url || "";
        const isVideo = row.media_type === "video";
        if (isVideo) {
          return `<article class="grid-item" data-id="${row.id}">
            <video src="${url}" muted playsinline preload="metadata"></video>
            <div class="grid-meta"><span>▶ vídeo</span></div>
          </article>`;
        }
        return `<article class="grid-item" data-id="${row.id}">
          <img src="${url}" alt="${(row.caption || "Publicação").replace(/"/g, "")}" loading="lazy" />
          <div class="grid-meta"><span>${row.caption ? "❝" : "♥"}</span></div>
        </article>`;
      })
      .join("");
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("is-active", t === tab);
      });
      loadPosts();
    });
  });

  // ---------- Upload ----------
  function openUpload() {
    if (!session) {
      openAuth("login");
      return;
    }
    setError("uploadError", null);
    $("uploadForm").reset();
    show($("uploadPreview"), false);
    $("uploadHint").hidden = false;
    show($("uploadModal"), true);
  }
  function closeUpload() {
    show($("uploadModal"), false);
  }

  $("btnOpenUpload")?.addEventListener("click", openUpload);
  $("navCreate")?.addEventListener("click", openUpload);
  $("uploadCancel")?.addEventListener("click", closeUpload);
  $("uploadModal")?.addEventListener("click", (e) => {
    if (e.target === $("uploadModal")) closeUpload();
  });

  $("uploadDrop")?.addEventListener("click", () => $("uploadFile").click());
  $("uploadFile")?.addEventListener("change", () => {
    const file = $("uploadFile").files?.[0];
    if (!file) return;
    if (file.type.startsWith("image/")) {
      const url = URL.createObjectURL(file);
      const img = $("uploadPreview");
      img.src = url;
      show(img, true);
      $("uploadHint").hidden = true;
    } else {
      $("uploadHint").textContent = file.name;
      $("uploadHint").hidden = false;
      show($("uploadPreview"), false);
    }
  });

  $("uploadForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    setError("uploadError", null);
    if (!session?.user) {
      openAuth("login");
      return;
    }
    const file = $("uploadFile").files?.[0];
    if (!file) {
      setError("uploadError", "Escolha um arquivo");
      return;
    }
    const caption = $("uploadCaption").value.trim();
    const btn = $("uploadSubmit");
    btn.disabled = true;
    btn.textContent = "Enviando…";

    try {
      const ext = (file.name.split(".").pop() || "bin").toLowerCase();
      const path = `${session.user.id}/${crypto.randomUUID()}.${ext}`;
      const { error: upErr } = await sb.storage.from("vd-media").upload(path, file, {
        cacheControl: "3600",
        upsert: false,
        contentType: file.type,
      });
      if (upErr) throw upErr;

      const url = publicUrl(path);
      const mediaType = mediaTypeFromFile(file);
      const { error: dbErr } = await sb.from("vd_media").insert({
        user_id: session.user.id,
        storage_path: path,
        original_name: file.name,
        media_type: mediaType,
        mime_type: file.type,
        size_bytes: file.size,
        caption,
        public_url: url,
        thumb_url: mediaType === "image" ? url : null,
        status: "ready",
        metadata: { source: "web-upload" },
      });
      if (dbErr) throw dbErr;

      closeUpload();
      await loadPosts();
    } catch (err) {
      console.error(err);
      setError("uploadError", err.message || "Falha no upload");
    } finally {
      btn.disabled = false;
      btn.textContent = "Publicar";
    }
  });

  // ---------- Init ----------
  refreshUserUI();
})();
