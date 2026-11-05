// Tara Intelligence WP 2.4: what Dokploy will see of docker-compose.dokploy.yml.
// Dokploy re-dumps the compose with merge keys expanded and passes it base64-encoded
// in one shell argument (128 KiB cap): print that size and the feed containers' env.
const Y = require("../../frontend/web/node_modules/js-yaml");
const fs = require("fs");
const path = require("path");

const file = path.join(__dirname, "..", "..", "docker-compose.dokploy.yml");
const doc = Y.load(fs.readFileSync(file, "utf8"));
const s = doc.services;
const env = (name) => (s[name] && s[name].environment) || {};
console.log(
  JSON.stringify({
    size: Math.ceil((Y.dump(doc, { lineWidth: 1000 }).length * 4) / 3),
    signals: env("feed-signals").RUN_MIGRATIONS,
    feed: env("feed").RUN_MIGRATIONS,
    secret: "INTEL_SERVE_TOKEN_SECRET" in env("feed-signals"),
    synthetic: env("feed").INTEL_ACCEPT_SYNTHETIC,
  }),
);
