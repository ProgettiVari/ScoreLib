import api from "@/lib/api";

export function getGoogleRedirectUri() {
  return window.location.origin;
}

export async function startGoogleOAuth(mode = "login") {
  const redirectUri = getGoogleRedirectUri();
  sessionStorage.setItem("google_oauth_mode", mode);

  if (mode === "master") {
    const r = await api.post("/admin/master-drive/url", { redirect_uri: redirectUri });
    window.location.href = r.data.url;
    return;
  }

  const r = await api.post("/auth/google/url", { redirect_uri: redirectUri });
  window.location.href = r.data.url;
}
