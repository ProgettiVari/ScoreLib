# Project Setup

## Frontend
- Use `REACT_APP_API_URL` to point to the backend root URL.
- Example: `REACT_APP_API_URL=https://scorelib-backend.onrender.com`
- Do not hardcode backend URLs in React source files.

## Backend
- Use `MONGO_URL` and `DB_NAME` in `backend/.env` or Render environment variables.
- Set `BACKEND_CORS_ORIGINS` to allow the frontend origin(s), for example:
  `https://boh-emerg-wzsa.vercel.app,http://localhost:3000`
