import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import * as z from "zod";

export function createBitrixMcpServer({ bitrixClient, tokenManager }) {
  const server = new McpServer({
    name: "bitrix24mcp",
    version: "0.1.0",
  });

  server.registerTool(
    "auth_status",
    {
      title: "Auth status",
      description: "Returns if Bitrix24 OAuth token is currently available",
      inputSchema: {},
      outputSchema: {
        data: z.unknown(),
      },
      annotations: { readOnlyHint: true },
    },
    async () => {
      const tokens = await tokenManager.getTokens();
      return toolSuccess({
        authorized: Boolean(tokens?.access_token),
        expires_at: tokens?.expires_at ?? null,
        client_endpoint: tokens?.client_endpoint ?? null,
      });
    },
  );

  server.registerTool(
    "list_deals",
    {
      title: "List deals",
      description: "Returns latest CRM deals from Bitrix24",
      inputSchema: {
        limit: z.number().int().positive().max(100).optional(),
      },
      outputSchema: {
        data: z.unknown(),
      },
      annotations: { readOnlyHint: true },
    },
    async (args) => {
      try {
        const limit = Number(args?.limit ?? 20);
        const data = await bitrixClient.listDeals({ limit });
        return toolSuccess({ items: data, count: data.length });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "get_deal",
    {
      title: "Get deal by id",
      description: "Returns one CRM deal by ID",
      inputSchema: {
        id: z.union([z.string().min(1), z.number().int().positive()]),
      },
      outputSchema: {
        data: z.unknown(),
      },
      annotations: { readOnlyHint: true },
    },
    async (args) => {
      try {
        const id = String(args?.id ?? "");
        const data = await bitrixClient.getDeal({ id });
        return toolSuccess({ item: data });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "list_contacts",
    {
      title: "List contacts",
      description: "Returns latest CRM contacts from Bitrix24",
      inputSchema: {
        limit: z.number().int().positive().max(100).optional(),
      },
      outputSchema: {
        data: z.unknown(),
      },
      annotations: { readOnlyHint: true },
    },
    async (args) => {
      try {
        const limit = Number(args?.limit ?? 20);
        const data = await bitrixClient.listContacts({ limit });
        return toolSuccess({ items: data, count: data.length });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  return server;
}

function toolSuccess(data) {
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    structuredContent: { data },
  };
}

function toolError(error) {
  const shape = {
    error: {
      message: error instanceof Error ? error.message : "Unknown error",
    },
  };
  return {
    content: [{ type: "text", text: JSON.stringify(shape, null, 2) }],
    structuredContent: shape,
    isError: true,
  };
}
