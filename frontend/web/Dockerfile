# Tara web client — build the Vue app, serve it with nginx, and reverse-proxy
# the API + WebSocket so the whole platform is one origin (one domain on Dokploy).
#   build context = frontend/web
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . ./
# Same-origin defaults: API at /api/v1, WS derived from window.location.
ARG VITE_API_BASE=/api/v1
ARG VITE_WS_URL=
ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_WS_URL=$VITE_WS_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=10 \
  CMD wget -qO- http://localhost/healthz.txt >/dev/null 2>&1 || exit 1
