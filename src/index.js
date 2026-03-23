import { getEnvConfig } from "./config/env.js";
import { TokenManager, TokenStore } from "./auth/tokenStore.js";
import { BitrixOAuthClient } from "./bitrix/oauth.js";
import { BitrixClient } from "./bitrix/client.js";
import { createBitrixMcpServer } from "./mcp/server.js";
import { startHttpServer } from "./transports/http.js";
import { startStdioServer } from "./transports/stdio.js";

async function main() {
  const mode = process.argv[2] ?? "http";
  const env = getEnvConfig();

  const oauthClient = new BitrixOAuthClient({
    clientId: env.BITRIX_CLIENT_ID,
    clientSecret: env.BITRIX_CLIENT_SECRET,
    redirectUri: env.BITRIX_REDIRECT_URI,
    scopes: env.BITRIX_SCOPES,
  });

  const tokenStore = new TokenStore(env.TOKEN_STORE_PATH);
  const tokenManager = new TokenManager({ store: tokenStore, oauthClient });
  const bitrixClient = new BitrixClient({ tokenManager });

  const mcpServerFactory = () =>
    createBitrixMcpServer({
      bitrixClient,
      tokenManager,
    });

  if (mode === "stdio") {
    const mcpServer = mcpServerFactory();
    await startStdioServer({ mcpServer });
    // eslint-disable-next-line no-console
    console.error("bitrix24mcp started in stdio mode");
    return;
  }

  await startHttpServer({
    env,
    oauthClient,
    tokenManager,
    mcpServerFactory,
  });
  // eslint-disable-next-line no-console
  console.error(`bitrix24mcp started on http://${env.HOST}:${env.PORT}${env.MCP_HTTP_PATH}`);
  // Keep process alive in long-running HTTP mode.
  setInterval(() => {}, 60_000);
}

main().catch((error) => {
  // eslint-disable-next-line no-console
  console.error("Failed to start bitrix24mcp:", error);
  process.exitCode = 1;
});
