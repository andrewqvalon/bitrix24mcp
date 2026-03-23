import path from "node:path";
import dotenv from "dotenv";

dotenv.config();

const defaults = {
  PORT: 4310,
  HOST: "0.0.0.0",
  MCP_HTTP_PATH: "/mcp",
  BASE_URL: "",
  BITRIX_SCOPES: "crm",
  TOKEN_STORE_PATH: "./data/tokens.json",
};

function normalizePath(value) {
  if (!value) return defaults.TOKEN_STORE_PATH;
  if (path.isAbsolute(value)) return value;
  return path.resolve(process.cwd(), value);
}

export function getEnvConfig() {
  const port = Number(process.env.PORT ?? defaults.PORT);
  if (!Number.isFinite(port) || port <= 0) {
    throw new Error(`Invalid PORT: ${process.env.PORT}`);
  }

  return {
    PORT: port,
    HOST: process.env.HOST ?? defaults.HOST,
    MCP_HTTP_PATH: process.env.MCP_HTTP_PATH ?? defaults.MCP_HTTP_PATH,
    BASE_URL: process.env.BASE_URL ?? defaults.BASE_URL,
    BITRIX_CLIENT_ID: process.env.BITRIX_CLIENT_ID ?? "",
    BITRIX_CLIENT_SECRET: process.env.BITRIX_CLIENT_SECRET ?? "",
    BITRIX_REDIRECT_URI: process.env.BITRIX_REDIRECT_URI ?? "",
    BITRIX_SCOPES: process.env.BITRIX_SCOPES ?? defaults.BITRIX_SCOPES,
    TOKEN_STORE_PATH: normalizePath(process.env.TOKEN_STORE_PATH),
  };
}
