import { randomUUID } from "node:crypto";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";

export async function startHttpServer({
  env,
  mcpServerFactory,
  oauthClient,
  tokenManager,
}) {
  const app = createMcpExpressApp({ host: env.HOST });
  const transports = {};

  app.get("/healthz", async (_req, res) => {
    const tokens = await tokenManager.getTokens();
    res.status(200).json({
      status: "ok",
      service: "bitrix24mcp",
      authorized: Boolean(tokens?.access_token),
      timestamp: new Date().toISOString(),
    });
  });

  app.get("/auth/status", async (_req, res) => {
    const tokens = await tokenManager.getTokens();
    res.status(200).json({
      authorized: Boolean(tokens?.access_token),
      expires_at: tokens?.expires_at ?? null,
      client_endpoint: tokens?.client_endpoint ?? null,
      updated_at: tokens?.updated_at ?? null,
    });
  });

  app.get("/auth/bitrix/start", (_req, res) => {
    try {
      const url = oauthClient.getAuthorizationUrl(randomUUID());
      res.redirect(url);
    } catch (error) {
      res.status(500).json({ error: error instanceof Error ? error.message : "Failed to build auth URL" });
    }
  });

  app.get("/auth/bitrix/callback", async (req, res) => {
    const code = String(req.query.code ?? "");
    const error = req.query.error ? String(req.query.error) : "";

    if (error) {
      res.status(400).send(`Bitrix authorization failed: ${error}`);
      return;
    }
    if (!code) {
      res.status(400).send("Missing OAuth code");
      return;
    }

    try {
      const payload = await oauthClient.exchangeCode(code);
      await tokenManager.saveFromOAuthResponse(payload);
      res.status(200).send("Bitrix24 authorization complete. You can return to your MCP client.");
    } catch (exchangeError) {
      res
        .status(500)
        .send(`Failed to exchange code: ${exchangeError instanceof Error ? exchangeError.message : "unknown error"}`);
    }
  });

  app.post(env.MCP_HTTP_PATH, async (req, res) => {
    const sessionId = req.headers["mcp-session-id"];

    try {
      let transport;
      if (sessionId && transports[sessionId]) {
        transport = transports[sessionId];
      } else if (!sessionId && isInitializeRequest(req.body)) {
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (newSessionId) => {
            transports[newSessionId] = transport;
          },
        });
        transport.onclose = () => {
          if (transport.sessionId && transports[transport.sessionId]) {
            delete transports[transport.sessionId];
          }
        };
        const server = mcpServerFactory();
        await server.connect(transport);
      } else {
        res.status(400).json({
          jsonrpc: "2.0",
          error: { code: -32000, message: "Bad Request: no valid session" },
          id: null,
        });
        return;
      }

      await transport.handleRequest(req, res, req.body);
    } catch (transportError) {
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: {
            code: -32603,
            message: transportError instanceof Error ? transportError.message : "Internal server error",
          },
          id: null,
        });
      }
    }
  });

  app.get(env.MCP_HTTP_PATH, async (req, res) => {
    const sessionId = req.headers["mcp-session-id"];
    if (!sessionId || !transports[sessionId]) {
      res.status(400).send("Invalid or missing session ID");
      return;
    }
    await transports[sessionId].handleRequest(req, res);
  });

  app.delete(env.MCP_HTTP_PATH, async (req, res) => {
    const sessionId = req.headers["mcp-session-id"];
    if (!sessionId || !transports[sessionId]) {
      res.status(400).send("Invalid or missing session ID");
      return;
    }
    await transports[sessionId].handleRequest(req, res);
  });

  await new Promise((resolve, reject) => {
    const server = app.listen(env.PORT, env.HOST, () => resolve());
    server.on("error", reject);
  });
}
