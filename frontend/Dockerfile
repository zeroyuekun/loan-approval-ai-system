# --- Build stage ---
FROM node:22-alpine AS builder

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

CMD ["npm", "run", "start"]
