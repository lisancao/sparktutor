const esbuild = require("esbuild");

const watch = process.argv.includes("--watch");

/** @type {import('esbuild').BuildOptions} */
const config = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "out/extension.js",
  external: ["vscode"],
  format: "cjs",
  platform: "node",
  target: "node18",
  sourcemap: true,
  minify: !watch,
};

if (watch) {
  esbuild.context(config).then((ctx) => {
    ctx.watch();
    console.log("Watching for changes...");
  });
} else {
  esbuild.build(config).then(() => {
    console.log("Build complete");
  });
}
