FROM node:24-alpine AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
FROM dependencies AS builder
ARG FLOWSENTRY_API_URL=http://api:8000
ENV FLOWSENTRY_API_URL=$FLOWSENTRY_API_URL NEXT_TELEMETRY_DISABLED=1
COPY frontend/ ./
RUN npm run build
FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup -g 1001 -S flowsentry && adduser -S flowsentry -u 1001 -G flowsentry
COPY --from=builder --chown=flowsentry:flowsentry /app/.next/standalone ./
COPY --from=builder --chown=flowsentry:flowsentry /app/.next/static ./.next/static
USER flowsentry
EXPOSE 3000
CMD ["node", "server.js"]
