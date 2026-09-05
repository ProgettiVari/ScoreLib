import axios from "axios";

// Per README.md: "Do not hardcode backend URLs in React source files. Use
// REACT_APP_API_URL". The literal URL below is kept only as a fallback so local/dev
// builds still work if the env var isn't set.
const BACKEND_URL = process.env.REACT_APP_API_URL || "https://scorelib-backend-docker.onrender.com";
export const API = `${BACKEND_URL}/api`;

const AUTH_TOKEN_KEY = "scorelib_session_token";
const LEGACY_AUTH_TOKEN_KEY = "scorelib_token";

function getAuthToken() {
  const token = localStorage.getItem(AUTH_TOKEN_KEY) || sessionStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    sessionStorage.setItem(AUTH_TOKEN_KEY, token);
    return token;
  }
  const legacy = localStorage.getItem(LEGACY_AUTH_TOKEN_KEY);
  if (!legacy) return null;
  localStorage.setItem(AUTH_TOKEN_KEY, legacy);
  sessionStorage.setItem(AUTH_TOKEN_KEY, legacy);
  localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY);
  return legacy;
}

const api = axios.create({
  baseURL: API,
  timeout: 15000,
});

api.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const body = error.response?.data;
    if (error.response?.status === 503 && body?.maintenance === true) {
      window.dispatchEvent(new CustomEvent("scorelib-maintenance", { detail: body }));
    }
    return Promise.reject(error);
  },
);

export default api;
export { BACKEND_URL, getAuthToken };
