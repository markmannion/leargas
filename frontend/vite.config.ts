import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

/**
 * Dev-only stand-in for Harry's `GET /drawing/{path}/image` (C5), so the mock mode shows the real
 * drawings straight from the local dataset. Swiss PDFs map to their PNG twin, ifc_models PDFs to
 * their SVG twin; other PDFs get a placeholder (the backend rasterises those with PyMuPDF).
 * When VITE_API_BASE is set, the app talks to the real API and this plugin is unused.
 */
function localDrawings(datasetRoot: string): Plugin {
  const types: Record<string, string> = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
  };
  return {
    name: "bt-local-drawings",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const m = req.url?.match(/^\/drawing\/(.+)\/image(?:\?.*)?$/);
        if (!m) return next();
        const rel = m[1].split("/").map(decodeURIComponent).join("/");
        let file = path.join(datasetRoot, rel);
        const ext = path.extname(file).toLowerCase();
        if (ext === ".pdf") {
          const png = file.slice(0, -4) + ".png";
          const svg = file.slice(0, -4) + ".svg";
          file = fs.existsSync(png) ? png : fs.existsSync(svg) ? svg : "";
        }
        if (!file || !fs.existsSync(file) || !file.startsWith(path.resolve(datasetRoot))) {
          res.statusCode = file ? 404 : 200;
          res.setHeader("Content-Type", "image/svg+xml");
          res.end(`<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1130" viewBox="0 0 1600 1130">
            <rect width="1600" height="1130" fill="#f7f9f8"/><text x="800" y="565" font-family="sans-serif"
            font-size="34" fill="#5a6573" text-anchor="middle">No local preview for ${rel.split("/").pop()}.
            The backend rasterises PDFs.</text></svg>`);
          return;
        }
        res.setHeader("Content-Type", types[path.extname(file).toLowerCase()] ?? "application/octet-stream");
        res.setHeader("Cache-Control", "max-age=3600");
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, ".."), "");
  const datasetRoot = path.resolve(__dirname, "..", env.JUNCTION_DATA || "datasets/junction-dataset");
  return {
    envDir: "..",
    plugins: [react(), localDrawings(datasetRoot)],
    server: { port: 5173, fs: { allow: [".."] } },
  };
});
