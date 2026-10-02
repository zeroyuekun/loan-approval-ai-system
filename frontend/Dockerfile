# --- Build stage ---
FROM node:22-alpine AS builder

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so
# this is the API base URL every browser using the image will call. No
# localhost default: unset means the same-origin path /api/v1 (reverse proxy
# or Ingress in front of the app). Pass an absolute URL only when the API
# lives on another origin; the CSP connect-src is derived from it.
#   docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com/api/v1 .
ARG NEXT_PUBLIC_API_URL=/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL:-/api/v1}

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

RUN npm run build

# --- Production stage ---
FROM node:22-alpine AS runner

# Patch Alpine base packages (zlib CVE-2026-22184)
RUN apk update && apk upgrade --no-cache

WORKDIR /app

ENV NODE_ENV=production

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

COPY --from=builder /app/package*.json ./
# npm is only needed to install; removing it drops its bundled dependencies
# (pacote, sigstore, ...) from the runtime image and its scan.
RUN npm ci --omit=dev && \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

COPY --from=builder --chown=appuser:appgroup /app/.next ./.next
COPY --from=builder --chown=appuser:appgroup /app/public ./public
COPY --from=builder --chown=appuser:appgroup /app/next.config.js ./

USER 100:101

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=45s \
  CMD wget -q --spider http://localhost:3000 || exit 1

CMD ["node_modules/.bin/next", "start"]
