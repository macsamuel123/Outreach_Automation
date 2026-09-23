import { useEffect, useState } from "react";
import { apiClient } from "../lib/api";

export default function AuditLog() {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [stageFilter, setStageFilter] = useState<string>("");
  const [decisionFilter, setDecisionFilter] = useState<string>("");

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        setLoading(true);
        const res = await apiClient.searchAuditLog(
          stageFilter || undefined,
          decisionFilter || undefined
        );
        setLogs(res.data);
      } finally {
        setLoading(false);
      }
    };
    fetchLogs();
  }, [stageFilter, decisionFilter]);

  const handleExport = async () => {
    try {
      const res = await apiClient.exportAuditLog();
      const element = document.createElement("a");
      element.setAttribute("href", `data:text/csv;charset=utf-8,${encodeURIComponent(res.data.csv)}`);
      element.setAttribute("download", "audit-log.csv");
      element.style.display = "none";
      document.body.appendChild(element);
      element.click();
      document.body.removeChild(element);
    } catch (err) {
      alert("Error exporting audit log");
    }
  };

  if (loading) return <div className="text-center py-8">Loading...</div>;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Audit Log</h1>
        <button
          onClick={handleExport}
          className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
        >
          Export CSV
        </button>
      </div>

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Filter by stage:</label>
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            >
              <option value="">All</option>
              <option value="discover">Discover</option>
              <option value="qualify">Qualify</option>
              <option value="enrich">Enrich</option>
              <option value="verify">Verify</option>
              <option value="draft">Draft</option>
              <option value="send">Send</option>
              <option value="followup">Followup</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Filter by decision:</label>
            <select
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            >
              <option value="">All</option>
              <option value="qualified">Qualified</option>
              <option value="rejected">Rejected</option>
              <option value="enriched">Enriched</option>
              <option value="verified">Verified</option>
              <option value="invalid">Invalid</option>
              <option value="sent">Sent</option>
            </select>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="min-w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Stage
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Company
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Decision
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Reasoning
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Date
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {logs.map((log) => (
              <tr key={log.id}>
                <td className="px-6 py-4 text-sm font-medium text-gray-900">{log.stage}</td>
                <td className="px-6 py-4 text-sm text-gray-900">{log.company_name}</td>
                <td className="px-6 py-4 text-sm">
                  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-purple-100 text-purple-800">
                    {log.decision}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600 max-w-xs truncate">
                  {log.reasoning}
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {new Date(log.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
