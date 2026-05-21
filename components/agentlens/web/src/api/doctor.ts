import { useQuery } from "@tanstack/react-query";

import { getJson } from "./client";

export type DoctorReport = {
  integrations?: Record<string, unknown>;
  paths?: Record<string, unknown>;
  warnings?: unknown[];
};

export function useDoctor() {
  return useQuery({
    queryKey: ["doctor"],
    queryFn: () => getJson<DoctorReport>("/api/v1/doctor"),
  });
}
