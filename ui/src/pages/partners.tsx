import { useEffect, useState } from "react";
import { apiClient } from "../lib/api";

export default function Partners() {
  const [partners, setPartners] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editData, setEditData] = useState<any>({});

  useEffect(() => {
    fetchPartners();
  }, [statusFilter]);

  const fetchPartners = async () => {
    try {
      setLoading(true);
      const res = await apiClient.listPartners(statusFilter || undefined);
      setPartners(res.data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleEdit = (partner: any) => {
    setEditingId(partner.id);
    setEditData({ ...partner });
  };

  const handleSave = async () => {
    try {
      await apiClient.updatePartner(editingId!, editData);
      setEditingId(null);
      fetchPartners();
      alert("Partner updated successfully");
    } catch (err: any) {
      alert(`Error: ${err.message}`);
    }
  };

  const handleCancel = () => {
    setEditingId(null);
    setEditData({});
  };

  if (loading) return <div className="text-center py-8">Loading...</div>;
  if (error) return <div className="text-center py-8 text-red-600">Error: {error}</div>;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Partners</h1>
        <div>
          <label className="text-sm font-medium text-gray-700 mr-3">Filter by status:</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg"
          >
            <option value="">All</option>
            <option value="PARTNER_STATUS_QUALIFIED">Qualified</option>
            <option value="PARTNER_STATUS_ENRICHED">Enriched</option>
            <option value="PARTNER_STATUS_VERIFIED">Verified</option>
            <option value="PARTNER_STATUS_DRAFTED">Drafted</option>
            <option value="PARTNER_STATUS_SENT">Sent</option>
          </select>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="min-w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Company
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Contact
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Email
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Confidence
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Action
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {partners.map((partner) => (
              <tr key={partner.id} className={editingId === partner.id ? "bg-blue-50" : ""}>
                <td className="px-6 py-4 text-sm text-gray-900">{partner.company_name}</td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {editingId === partner.id ? (
                    <input
                      type="text"
                      value={editData.contact_name || ""}
                      onChange={(e) => setEditData({ ...editData, contact_name: e.target.value })}
                      className="w-full px-2 py-1 border border-gray-300 rounded"
                    />
                  ) : (
                    partner.contact_name
                  )}
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">{partner.contact_email}</td>
                <td className="px-6 py-4 text-sm">
                  {editingId === partner.id ? (
                    <select
                      value={editData.status || ""}
                      onChange={(e) => setEditData({ ...editData, status: e.target.value })}
                      className="px-2 py-1 border border-gray-300 rounded"
                    >
                      <option>PARTNER_STATUS_QUALIFIED</option>
                      <option>PARTNER_STATUS_ENRICHED</option>
                      <option>PARTNER_STATUS_VERIFIED</option>
                      <option>PARTNER_STATUS_DRAFTED</option>
                      <option>PARTNER_STATUS_SENT</option>
                      <option>PARTNER_STATUS_NEEDS_REVIEW</option>
                    </select>
                  ) : (
                    <span className="px-3 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-800">
                      {partner.status}
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {partner.email_confidence ? `${partner.email_confidence.toFixed(0)}%` : "-"}
                </td>
                <td className="px-6 py-4 text-sm">
                  {editingId === partner.id ? (
                    <div className="flex gap-2">
                      <button
                        onClick={handleSave}
                        className="text-green-600 hover:text-green-800 font-semibold"
                      >
                        Save
                      </button>
                      <button
                        onClick={handleCancel}
                        className="text-red-600 hover:text-red-800 font-semibold"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => handleEdit(partner)}
                      className="text-blue-600 hover:text-blue-800 font-semibold"
                    >
                      Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
