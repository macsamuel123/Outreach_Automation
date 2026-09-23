import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { apiClient } from "../lib/api";

export default function Runs() {
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [selectedRun, setSelectedRun] = useState<any>(null);
  const [logs, setLogs] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(false);

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        setLoading(true);
        const res = await apiClient.listRuns(20);
        setRuns(res.data);

        // If run ID is in query params, select it
        if (router.query.id) {
          const selected = res.data.find((r: any) => r.github_run_id === parseInt(router.query.id as string));
          if (selected) {
            setSelectedRun(selected);
            fetchLogs(selected.github_run_id);
          }
        }
      } finally {
        setLoading(false);
      }
    };
    fetchRuns();
  }, [router.query.id]);

  const fetchLogs = async (runId: number) => {
    try {
      setLogsLoading(true);
      const res = await apiClient.getRunLogs(runId);
      setLogs(res.data.logs || "No logs available");
    } finally {
      setLogsLoading(false);
    }
  };

  const handleSelectRun = async (run: any) => {
    setSelectedRun(run);
    await fetchLogs(run.github_run_id);
  };

  if (loading) return <div className="text-center py-8">Loading...</div>;

  return (
    <div>
      <h1 className="text-3xl font-bold text-gray-900 mb-6">Pipeline Runs</h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Runs List */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg shadow">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">Recent Runs</h2>
            </div>
            <div className="divide-y divide-gray-200 max-h-96 overflow-y-auto">
              {runs.map((run) => (
                <button
                  key={run.github_run_id}
                  onClick={() => handleSelectRun(run)}
                  className={`w-full text-left px-6 py-4 hover:bg-gray-50 ${
                    selectedRun?.github_run_id === run.github_run_id ? "bg-blue-50" : ""
                  }`}
                >
                  <div className="font-medium text-gray-900">{run.run_id}</div>
                  <div className="text-sm text-gray-600">
                    {new Date(run.triggered_at).toLocaleString()}
                  </div>
                  <div className="mt-2">
                    <span
                      className={`px-3 py-1 rounded-full text-xs font-semibold ${
                        run.status === "success"
                          ? "bg-green-100 text-green-800"
                          : run.status === "failure"
                          ? "bg-red-100 text-red-800"
                          : "bg-yellow-100 text-yellow-800"
                      }`}
                    >
                      {run.status}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Logs */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-lg shadow">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">
                {selectedRun ? `Logs - ${selectedRun.run_id}` : "Select a run to view logs"}
              </h2>
            </div>
            {selectedRun && (
              <div className="p-6">
                {logsLoading ? (
                  <div className="text-center py-8">Loading logs...</div>
                ) : (
                  <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto max-h-96 overflow-y-auto text-xs">
                    {logs}
                  </pre>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
