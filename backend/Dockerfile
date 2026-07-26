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

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT dynamically — don't hardcode 8000 here.
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT