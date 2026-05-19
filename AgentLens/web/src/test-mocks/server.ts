import { setupServer } from "msw/node";

import { agentLensApiHandlers } from "./agentlens-api";

export const server = setupServer(...agentLensApiHandlers());
