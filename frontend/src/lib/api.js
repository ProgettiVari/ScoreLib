import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_API_URL || process.env.REACT_APP_BACKEND_URL;
if (!BACKEND_URL) {
  throw new Error(
    "Environment variable REACT_APP_API_URL must be defined for frontend API requests"
  );
}

export const API = `${BACKEND_URL.replace(/\/+$|\s+$/g, "")}/api`;

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
  timeout: Number(process.env.REACT_APP_API_TIMEOUT_MS || 15000), // Reduced from 30s to 15s for responsiveness
});

api.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export default api;
export { BACKEND_URL, getAuthToken };
