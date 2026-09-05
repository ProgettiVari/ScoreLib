export function applyThemeSetting(theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
    root.style.colorScheme = "dark";
    return;
  }
  if (theme === "light") {
    root.classList.remove("dark");
    root.style.colorScheme = "light";
    return;
  }
  const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.classList.toggle("dark", isDark);
  root.style.colorScheme = isDark ? "dark" : "light";
}

export function resolveInitialTheme() {
  const stored = localStorage.getItem("theme");
  if (stored && ["light", "dark", "system"].includes(stored)) {
    return stored;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getThemeValue() {
  const stored = localStorage.getItem("theme");
  if (stored && ["light", "dark", "system"].includes(stored)) {
    return stored;
  }
  return resolveInitialTheme();
}
