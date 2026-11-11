import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./": the app is served from https://storage.googleapis.com/<bucket>/, not from the root.
export default defineConfig({ base: "./", plugins: [react()] });
