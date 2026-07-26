# Needs BOTH Python (the app itself) and Node.js (Tavily/GitHub MCP servers
# launch as `npx` subprocesses — see app/mcp_client.py). This was the exact
# thing that silently broke Railway's nixpacks config if the node package
# was missing, so it's baked directly into the image here instead.
FROM python:3.11-slim

# Install Node.js 20.x (needed for npx to launch the MCP servers)
RUN apt-get update && apt-get install -y curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install the MCP server packages globally AT BUILD TIME, not via npx at
# runtime. Runtime `npx -y <pkg>` was causing production failures: parallel
# Send() branches racing to download+extract into the same npx cache
# directory simultaneously corrupted it permanently (ENOTEMPTY / TAR_ENTRY
# errors, then ERR_MODULE_NOT_FOUND forever after, since npx doesn't
# auto-detect or repair a corrupted cache entry). Installing globally here
# means the packages are baked into the image as verified, immutable files —
# no runtime download, no cache directory for concurrent requests to race on.
RUN npm install -g tavily-mcp @modelcontextprotocol/server-github

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT dynamically — don't hardcode 8000 here.
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT