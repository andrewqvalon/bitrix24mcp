import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

export async function startStdioServer({ mcpServer }) {
  const transport = new StdioServerTransport();
  await mcpServer.connect(transport);
}
