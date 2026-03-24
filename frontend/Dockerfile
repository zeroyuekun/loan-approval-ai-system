# --- Build stage ---
FROM node:22-alpine AS builder

ARG NEXT_PUBLIC_API_URL=http://localhost:8500/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

RUN npm run build

# --- Production stage ---
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

COPY --from=builder /app/package*.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder --chown=appuser:appgroup /app/next.config.js ./

USER appuser

EXPOSE 3000

CMD ["npm", "run", "start"]
