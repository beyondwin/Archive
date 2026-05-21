import { useQuery } from "@tanstack/react-query";

import { getJson } from "./client";

export type Meta = {
  agentlens_version: string;
  schema_version: string;
  store_path: string;
  store_exists: boolean;
  demo_mode: boolean;
};

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => getJson<Meta>("/api/v1/meta"),
  });
}
