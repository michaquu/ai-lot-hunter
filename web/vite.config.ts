import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig(({ mode }) => {
  // Load .env from repo root (../) AND web/ directory so a single root .env works everywhere
  const rootEnv = loadEnv(mode, path.resolve(__dirname, ".."), "");
  const webEnv = loadEnv(mode, __dirname, "");
  const env = { ...rootEnv, ...webEnv };

  const firebaseApiKey =
    env.VITE_FIREBASE_API_KEY || env.FIREBASE_API_KEY || env.FIREBASE_KEY || "";
  const firebaseProjectId =
    env.VITE_FIREBASE_PROJECT_ID || env.FIREBASE_PROJECT_ID || "ai-lot-hunter";
  const firebaseDatabaseUrl =
    env.VITE_FIREBASE_DATABASE_URL || env.FIREBASE_DATABASE_URL || "";
  const firebaseAppId = env.VITE_FIREBASE_APP_ID || env.FIREBASE_APP_ID || "";
  const firebaseUserId = env.VITE_FIREBASE_USER_ID || env.FIREBASE_USER_ID || "";

  return {
    plugins: [react(), tailwindcss()],
    define: {
      "import.meta.env.VITE_FIREBASE_API_KEY": JSON.stringify(firebaseApiKey),
      "import.meta.env.VITE_FIREBASE_PROJECT_ID": JSON.stringify(firebaseProjectId),
      "import.meta.env.VITE_FIREBASE_DATABASE_URL": JSON.stringify(firebaseDatabaseUrl),
      "import.meta.env.VITE_FIREBASE_APP_ID": JSON.stringify(firebaseAppId),
      "import.meta.env.VITE_FIREBASE_USER_ID": JSON.stringify(firebaseUserId),
    },
  };
});
