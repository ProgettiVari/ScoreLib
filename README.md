# Project Setup

## Frontend
- Use `REACT_APP_API_URL` to point to the backend root URL.
- Example: `REACT_APP_API_URL=https://scorelib-backend.onrender.com`
- Do not hardcode backend URLs in React source files.

## Backend
- Use `MONGO_URL` and `DB_NAME` in `backend/.env` or Render environment variables.
- Set `BACKEND_CORS_ORIGINS` to allow the frontend origin(s), for example:
  `https://boh-emerg-wzsa.vercel.app,http://localhost:3000`

## Android app
- The frontend is now PWA-ready and has a Capacitor config in `frontend/capacitor.config.json`.
- Build flow after installing Android Studio/JDK 17 and freeing disk space:
  1. `cd frontend`
  2. `npm install`
  3. set `REACT_APP_API_URL` to the production backend URL
  4. `npm run android:init`
  5. `npm run android:apk`
- The debug APK will be generated under `frontend/android/app/build/outputs/apk/debug/` once the Android SDK is available.
