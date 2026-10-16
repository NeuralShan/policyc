import { useQuery } from "@tanstack/react-query";

import { api, type GapCode } from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, type Tone } from "../components/ui";

const severityTone: Record<GapCode["default_severity"], Tone> = {
  error: "red",
  warning: "amber",
  info: "slate",
};

const tierTone: Record<GapCode["tier"], Tone> = {
  deterministic: "green",
  historical: "blue",
  judgment: "violet",
};

export function GapCodesPage() {
  const taxonomy = useQuery({ queryKey: ["taxonomy"], queryFn: api.taxonomy, staleTime: Infinity });
  const byCategory = Map.groupBy(taxonomy.data ?? [], (c) => c.category);

  return (
    <>
      <PageHeader
        title="Gap codes"
        subtitle="The compiler's error catalogue (taxonomy v1 for SOPs). Every finding carries one of these codes."
      />
      <ErrorNote error={taxonomy.error} />
      <div className="grid gap-6">
        {[...byCategory].map(([category, codes]) => (
          <Card key={category} title={category}>
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="w-20 py-2 font-medium">Code</th>
                  <th className="py-2 font-medium">Meaning</th>
                  <th className="w-24 py-2 font-medium">Severity</th>
                  <th className="w-32 py-2 font-medium">Detected by</th>
                  <th className="w-16 py-2 font-medium">Layer</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {codes.map((c) => (
                  <tr key={c.code}>
                    <td className="py-2 font-mono text-xs font-semibold">{c.code}</td>
                    <td className="py-2 text-slate-700">{c.title}</td>
                    <td className="py-2"><Badge tone={severityTone[c.default_severity]}>{c.default_severity}</Badge></td>
                    <td className="py-2"><Badge tone={tierTone[c.tier]}>{c.tier}</Badge></td>
                    <td className="py-2 text-slate-600">L{c.layer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
    </>
  );
}
