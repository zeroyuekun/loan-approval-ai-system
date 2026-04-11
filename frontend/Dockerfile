# --- Build stage ---
FROM node:22-alpine AS builder

# IMPORTANT: NEXT_PUBLIC_* vars are baked into the client bundle at BUILD time,
# not runtime. When deploying to Railway, Render, Fly, etc., the build step
# MUST pass --build-arg NEXT_PUBLIC_API_URL=https://<your-api-domain>/api/v1
# or the deployed frontend will silently point at localhost and fail.
# See backend/docs/DEPLOYMENT.md for the full deploy checklist.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

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
RUN npm ci --omit=dev

COPY --from=builder --chown=appuser:appgroup /app/.next ./.next
COPY --from=builder --chown=appuser:appgroup /app/public ./public
COPY --from=builder --chown=appuser:appgroup /app/next.config.js ./

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=45s \
  CMD wget -q --spider http://localhost:3000 || exit 1

CMD ["npm", "run", "start"]
