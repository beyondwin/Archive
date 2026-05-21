import { CheckCircle2, TriangleAlert } from "lucide-react";

import { useDoctor } from "@/api/doctor";

export function DoctorFooter() {
  const doctor = useDoctor();
  if (doctor.isLoading) return <div className="text-[11px] text-zinc-500">doctor</div>;
  if (doctor.error) {
    return (
      <div className="flex items-center gap-2 text-[11px] text-red-300">
        <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
        doctor error
      </div>
    );
  }
  const warnings = doctor.data?.warnings ?? [];
  const ok = warnings.length === 0;
  return (
    <div className="flex items-center gap-2 text-[11px] text-zinc-400">
      {ok ? (
        <CheckCircle2 aria-hidden className="h-3.5 w-3.5 text-emerald-300" />
      ) : (
        <TriangleAlert aria-hidden className="h-3.5 w-3.5 text-amber-300" />
      )}
      doctor: {ok ? "OK" : `${warnings.length} warnings`}
    </div>
  );
}
