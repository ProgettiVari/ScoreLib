export function shouldHideAppChrome(pathname) {
  const authRoutes = [
    "/login",
    "/register",
    "/forgot",
    "/reset",
    "/profile-setup",
    "/auth/callback",
    "/auth/google/callback",
  ];
  return authRoutes.some((p) => pathname.startsWith(p)) || pathname.startsWith("/viewer/");
}
