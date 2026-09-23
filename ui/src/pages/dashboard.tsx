import { useEffect, useState } from "react";
import Link from "next/link";
import { apiClient } from "../lib/api";

export default function Dashboard() {
  const [stats, setStats] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [statsRes, runsRes] = await Promise.all([
          apiClient.getStats(),
          apiClient.listRuns(5),
        ]);
        setStats(statsRes.data);
        setRuns(runsRes.data);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleTriggerRun = async () => {
    try {
      await apiClient.triggerRun();
      alert("Pipeline triggered! Check the Runs page for updates.");
    } catch (err: any) {
      alert(`Error: ${err.message}`);
    }
  };

  if (loading) {
    return <div className="text-center py-8">Loading...</div>;
  }

  if (error) {
    return <div className="text-center py-8 text-red-600">Error: {error}</div>;
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <button
          onClick={handleTriggerRun}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Trigger Pipeline Run
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        <div className="bg-white p-6 rounded-lg shadow">
          <div className="text-gray-500 text-sm">Discovered (This Week)</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats?.discovered_this_week || 0}
          </div>
        </div>

        <div className="bg-white p-6 rounded-lg shadow">
          <div className="text-gray-500 text-sm">Qualified</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats?.qualified_count || 0}
          </div>
        </div>

        <div className="bg-white p-6 rounded-lg shadow">
          <div className="text-gray-500 text-sm">Verified</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats?.verified_count || 0}
          </div>
        </div>

        <div className="bg-white p-6 rounded-lg shadow">
          <div className="text-gray-500 text-sm">Sent</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats?.sent_count || 0}
          </div>
        </div>

        <div className="bg-white p-6 rounded-lg shadow">
          <div className="text-gray-500 text-sm">Avg Email Confidence</div>
          <div className="text-3xl font-bold text-gray-900">
            {(stats?.avg_email_confidence || 0).toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Recent Runs */}
      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Recent Runs</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Run ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Triggered
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {runs.map((run) => (
                <tr key={run.github_run_id}>
                  <td className="px-6 py-4 text-sm text-gray-900">{run.run_id}</td>
                  <td className="px-6 py-4 text-sm">
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
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {new Date(run.triggered_at).toLocaleString()}
                  </td>
                  <td className="px-6 py-4 text-sm">
                    <Link
                      href={`/runs?id=${run.github_run_id}`}
                      className="text-blue-600 hover:text-blue-800"
                    >
                      View Logs
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
